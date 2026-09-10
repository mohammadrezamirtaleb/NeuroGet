import os
import re
import time
import json
import requests
import urllib3
import urllib.parse

from threading import Event, Lock
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter

from PyQt5.QtCore import QThread, pyqtSignal


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


MAX_SEGMENTS = 16
MIN_SEGMENT_SIZE = 2 * 1024 * 1024
MIN_MULTITHREAD_SIZE = 8 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class DownloadWorker(QThread):
    metadata_ready = pyqtSignal(str, int)
    progress_update = pyqtSignal(int, float, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, task_id, url, save_dir):
        super().__init__()

        self.task_id = task_id
        self.url = url
        self.save_dir = save_dir

        self.filename = ""
        self.total_size = 0
        self.downloaded_size = 0

        self.file_path = ""
        self.part_path = ""
        self._meta_path = ""

        self.is_paused = False
        self.is_cancelled = False

        self._pause_event = Event()
        self._pause_event.set()

        self._cancel_event = Event()

        self._state_lock = Lock()
        self._file_lock = Lock()

        self._file = None
        self._failure = None

    def pause(self):
        self.is_paused = True
        self._pause_event.clear()

    def resume(self):
        self.is_paused = False
        self._pause_event.set()

    def cancel(self):
        self.is_cancelled = True
        self.is_paused = False
        self._cancel_event.set()
        self._pause_event.set()

    def _wait_active(self):
        while not self._cancel_event.is_set():
            if self._pause_event.is_set():
                return True
            time.sleep(0.1)
        return False

    def _make_session(self):
        session = requests.Session()

        adapter = HTTPAdapter(
            pool_connections=32,
            pool_maxsize=32,
            max_retries=1
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _open_stream(self, session, headers=None):
        headers = headers or {}

        try:
            return session.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=20
            )
        except requests.exceptions.SSLError:
            return session.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=20,
                verify=False
            )

    def _extract_filename(self, response):
        if self.filename:
            return self.filename

        name = ""
        cd = response.headers.get("content-disposition", "")

        if cd:
            matches = re.findall(
                r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?",
                cd,
                re.IGNORECASE
            )

            if matches:
                name = matches[0].strip().strip('"\'')
                name = urllib.parse.unquote(name)

        if not name:
            path = urllib.parse.urlparse(self.url).path
            name = os.path.basename(urllib.parse.unquote(path))

        name = os.path.basename(name.replace("\\", "/")).strip()
        return name or "downloaded_file"

    def _parse_total_size(self, headers, fallback=0):
        content_range = headers.get("Content-Range", "")

        if "/" in content_range:
            total = content_range.split("/")[-1].strip()
            if total.isdigit():
                return int(total)

        content_length = headers.get("Content-Length", str(fallback))

        try:
            return int(content_length or fallback)
        except Exception:
            return fallback

    def _emit_progress(self, speed):
        eta = "Unknown"

        if speed > 0 and self.total_size > 0:
            remaining = max(0, self.total_size - self.downloaded_size)
            eta_secs = int(remaining / speed)

            mins, secs = divmod(eta_secs, 60)
            hours, mins = divmod(mins, 60)

            if hours > 0:
                eta = f"{hours}h {mins}m {secs}s"
            else:
                eta = f"{mins}m {secs}s"

        self.progress_update.emit(
            self.downloaded_size,
            float(speed),
            eta
        )

    def _finalize(self):
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except Exception:
                pass

        os.rename(self.part_path, self.file_path)

        if os.path.exists(self._meta_path):
            try:
                os.remove(self._meta_path)
            except Exception:
                pass

        self.finished.emit(self.file_path)

    def run(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            session = self._make_session()

            probe = None
            normal_response = None
            range_supported = False

            try:
                probe = self._open_stream(session, {"Range": "bytes=0-0"})
            except requests.exceptions.RequestException:
                probe = self._open_stream(session)

            if probe.status_code not in (200, 206):
                status = probe.status_code
                probe.close()
                raise Exception(f"Server returned HTTP {status}")

            self.filename = self._extract_filename(probe)
            self.file_path = os.path.join(self.save_dir, self.filename)
            self.part_path = self.file_path + ".part"
            self._meta_path = self.part_path + ".ngmeta"

            if probe.status_code == 206:
                self.total_size = self._parse_total_size(probe.headers, 0)
                range_supported = True
                probe.close()
            else:
                self.total_size = self._parse_total_size(probe.headers, 0)
                normal_response = probe

            self.metadata_ready.emit(self.filename, self.total_size)

            if range_supported and self.total_size >= MIN_MULTITHREAD_SIZE:
                self._download_segmented(session)
            else:
                if normal_response is not None:
                    self._download_single(
                        session,
                        normal_response,
                        range_supported=False
                    )
                else:
                    response = self._open_stream(session)

                    if response.status_code not in (200, 206):
                        status = response.status_code
                        response.close()
                        raise Exception(f"Server returned HTTP {status}")

                    self._download_single(
                        session,
                        response,
                        range_supported=range_supported
                    )

        except Exception as e:
            self.error.emit(str(e))

    def _download_single(self, session, response, range_supported=False):
        try:
            mode = "wb"
            downloaded = 0

            if not range_supported and os.path.exists(self._meta_path):
                try:
                    os.remove(self._meta_path)
                except Exception:
                    pass

                if os.path.exists(self.part_path):
                    try:
                        os.remove(self.part_path)
                    except Exception:
                        pass

            existing = (
                os.path.getsize(self.part_path)
                if os.path.exists(self.part_path)
                else 0
            )

            if range_supported and existing > 0 and not os.path.exists(self._meta_path):
                response.close()

                response = self._open_stream(
                    session,
                    {"Range": f"bytes={existing}-"}
                )

                if response.status_code == 206:
                    downloaded = existing
                    mode = "ab"

                    content_range_total = self._parse_total_size(response.headers, 0)
                    content_length = int(response.headers.get("Content-Length", 0) or 0)

                    if content_range_total > 0:
                        self.total_size = content_range_total
                    else:
                        self.total_size = downloaded + content_length

                elif response.status_code == 200:
                    downloaded = 0
                    mode = "wb"
                    self.total_size = self._parse_total_size(
                        response.headers,
                        self.total_size
                    )

                else:
                    status = response.status_code
                    response.close()
                    raise Exception(f"Server returned HTTP {status}")
            else:
                self.total_size = self._parse_total_size(
                    response.headers,
                    self.total_size
                )

            self.downloaded_size = downloaded

            start_time = time.time()
            bytes_since_start = 0

            with open(self.part_path, mode) as f:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if not self._wait_active():
                        break

                    if chunk:
                        f.write(chunk)
                        n = len(chunk)

                        self.downloaded_size += n
                        bytes_since_start += n

                        elapsed = time.time() - start_time

                        if elapsed >= 0.5:
                            speed = bytes_since_start / elapsed if elapsed > 0 else 0.0
                            self._emit_progress(speed)

                            start_time = time.time()
                            bytes_since_start = 0

            response.close()

            if self.is_cancelled:
                self.error.emit("Download cancelled.")
            elif self.total_size > 0 and self.downloaded_size < self.total_size:
                self.error.emit("Connection lost. Download incomplete.")
            else:
                self._finalize()

        except Exception as e:
            self.error.emit(str(e))

    def _load_or_create_segments(self):
        segments = []

        if os.path.exists(self._meta_path) and os.path.exists(self.part_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

                if (
                    meta.get("url") == self.url and
                    int(meta.get("total_size", 0)) == self.total_size
                ):
                    segments = meta.get("segments", [])
            except Exception:
                segments = []

        if not segments:
            if os.path.exists(self.part_path):
                try:
                    os.remove(self.part_path)
                except Exception:
                    pass

            if os.path.exists(self._meta_path):
                try:
                    os.remove(self._meta_path)
                except Exception:
                    pass

            segment_count = min(
                MAX_SEGMENTS,
                max(1, int(self.total_size // MIN_SEGMENT_SIZE))
            )

            if self.total_size <= 0:
                segment_count = 1

            size = (
                self.total_size // segment_count
                if segment_count else 0
            )

            start = 0
            segments = []

            for i in range(segment_count):
                if i == segment_count - 1:
                    end = self.total_size - 1
                else:
                    end = start + size - 1

                if end < start:
                    end = start

                segments.append([start, end, 0])
                start = end + 1

        if not os.path.exists(self.part_path):
            open(self.part_path, "wb").close()

        self.downloaded_size = sum(int(s[2]) for s in segments)
        return segments

    def _save_meta(self, segments):
        try:
            meta = {
                "url": self.url,
                "total_size": self.total_size,
                "segments": segments
            }

            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f)
        except Exception:
            pass

    def _download_segmented(self, session):
        segments = self._load_or_create_segments()
        self._save_meta(segments)

        self._failure = None
        self._file = open(self.part_path, "r+b")

        workers = min(MAX_SEGMENTS, max(1, len(segments)))
        executor = ThreadPoolExecutor(max_workers=workers)

        futures = [
            executor.submit(self._segment_worker, session, seg)
            for seg in segments
        ]

        last_time = time.time()
        last_bytes = self.downloaded_size

        try:
            while True:
                if self.is_cancelled:
                    break

                if all(f.done() for f in futures):
                    break

                time.sleep(0.5)

                current = self.downloaded_size
                now = time.time()

                if self.is_paused:
                    last_time = now
                    last_bytes = current
                    continue

                elapsed = now - last_time

                if elapsed >= 0.5:
                    speed = (current - last_bytes) / elapsed if elapsed > 0 else 0.0
                    self._emit_progress(speed)

                    last_time = now
                    last_bytes = current

                    self._save_meta(segments)

                if self.total_size > 0 and current >= self.total_size:
                    break

            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    if not self._failure:
                        self._failure = str(e)

        finally:
            executor.shutdown(wait=True, cancel_futures=True)

            if self._file:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass

                self._file = None

        if self._failure:
            self.error.emit(self._failure)
        elif self.is_cancelled:
            self.error.emit("Download cancelled.")
        elif self.total_size > 0 and self.downloaded_size < self.total_size:
            self.error.emit("Connection lost. Download incomplete.")
        else:
            self._save_meta(segments)
            self._finalize()

    def _segment_worker(self, session, seg):
        start = int(seg[0])
        end = int(seg[1])
        retries = 3

        for attempt in range(retries):
            if self.is_cancelled:
                return False

            with self._state_lock:
                downloaded = int(seg[2])

            length = end - start + 1

            if downloaded >= length:
                return True

            pos = start + downloaded
            response = None

            try:
                headers = {"Range": f"bytes={pos}-{end}"}
                response = self._open_stream(session, headers)

                if response.status_code == 200:
                    raise Exception("Server ignored range request")

                if response.status_code != 206:
                    raise Exception(
                        f"Server returned HTTP {response.status_code}"
                    )

                for chunk in response.iter_content(CHUNK_SIZE):
                    if not self._wait_active():
                        return False

                    if chunk:
                        with self._file_lock:
                            self._file.seek(pos)
                            self._file.write(chunk)

                        n = len(chunk)
                        pos += n

                        with self._state_lock:
                            seg[2] = int(seg[2]) + n
                            self.downloaded_size += n

                return True

            except Exception as e:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

                if attempt == retries - 1 or self.is_cancelled:
                    self._failure = str(e)
                    self.cancel()
                    return False

                time.sleep(1 + attempt)

        return False