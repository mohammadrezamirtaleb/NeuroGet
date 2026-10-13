import os
import re
import time
import json
import requests
import urllib3
import urllib.parse
import shutil

from threading import Event, Lock
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter

from PyQt5.QtCore import QThread, pyqtSignal
from app.models.database import get_setting


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


DEFAULT_MAX_SEGMENTS = 16
MIN_SEGMENT_SIZE = 2 * 1024 * 1024
MIN_MULTITHREAD_SIZE = 8 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class DownloadWorker(QThread):
    metadata_ready = pyqtSignal(str, object)        # object allows >2GB int values
    progress_update = pyqtSignal(object, float, str) # object avoids int32 overflow
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, task_id, url, save_dir, parent=None):
        super().__init__(parent)

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
        self._session = None
        self._etag = ""
        self._last_modified = ""

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
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass

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

        # Use a standard browser User-Agent to avoid HTTP 403 blocks
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Encoding": "identity"
        })

        return session

    def _open_stream(self, session, headers=None):
        headers = headers or {}

        return session.get(
            self.url,
            headers=headers,
            stream=True,
            timeout=(10, 30)  # (connect_timeout, read_timeout)
        )

    def _extract_filename(self, response):
        if self.filename:
            return self._sanitize_filename(self.filename)

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
        return self._sanitize_filename(name) or "downloaded_file"

    def _clean_filename_if_enabled(self, filename):
        enabled = get_setting("enable_ai_clean_renaming", "true").lower() in (
            "true", "1", "yes"
        )
        if not enabled:
            return filename
        try:
            from app.services.ai_client import AIClient
            return self._sanitize_filename(AIClient._heuristic_clean_name(filename))
        except Exception:
            return filename

    @staticmethod
    def _sanitize_filename(name):
        """Remove Windows-illegal characters and reserved device names."""
        # Replace illegal chars: \ / : * ? " < > |
        name = re.sub(r'[\\/:*?"<>|]', '_', name)
        # Strip trailing dots and spaces (NTFS silently truncates these)
        name = name.rstrip('. ')
        # Block Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        base = name.split('.')[0].upper()
        if re.match(r'^(CON|PRN|AUX|NUL|COM\d|LPT\d)$', base):
            name = f"_{name}"
        return name or "downloaded_file"

    def _parse_total_size(self, headers, fallback=0):
        content_range = headers.get("Content-Range", "")

        if "/" in content_range:
            total = content_range.split("/")[-1].strip()
            if total.isdigit():
                return int(total)
            if total == "*" or content_range.strip().endswith("/*"):
                return fallback

        content_length = headers.get("Content-Length", str(fallback))

        try:
            return int(content_length or fallback)
        except Exception:
            return fallback

    def _get_max_threads(self):
        try:
            raw = get_setting("max_threads", str(DEFAULT_MAX_SEGMENTS))
            val = int(raw) if raw is not None else DEFAULT_MAX_SEGMENTS
            return min(32, max(1, val))
        except (ValueError, TypeError):
            return DEFAULT_MAX_SEGMENTS

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

    def _select_output_paths(self):
        """Choose a collision-free target while preserving this URL's partial file."""
        stem, ext = os.path.splitext(self.filename)
        index = 0
        while True:
            suffix = "" if index == 0 else f" ({index})"
            candidate = os.path.join(self.save_dir, f"{stem}{suffix}{ext}")
            part_path = candidate + ".part"
            meta_path = part_path + ".ngmeta"

            if (os.path.exists(meta_path) and os.path.exists(part_path)
                    and not os.path.exists(candidate)):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        if json.load(f).get("url") == self.url:
                            self.filename = os.path.basename(candidate)
                            return candidate, part_path, meta_path
                except Exception:
                    pass

            if not os.path.exists(candidate) and not os.path.exists(part_path):
                try:
                    # Reserve the partial path atomically so simultaneous downloads
                    # cannot select the same destination.
                    with open(part_path, "xb"):
                        pass
                    self.filename = os.path.basename(candidate)
                    return candidate, part_path, meta_path
                except FileExistsError:
                    pass
            index += 1

    def _capture_validators(self, response):
        self._etag = response.headers.get("ETag", "") or ""
        self._last_modified = response.headers.get("Last-Modified", "") or ""

    def _meta_matches(self, meta):
        if meta.get("url") != self.url:
            return False
        if int(meta.get("total_size", 0)) != self.total_size:
            return False
        old_etag = meta.get("etag", "")
        old_modified = meta.get("last_modified", "")
        if old_etag and self._etag and old_etag != self._etag:
            return False
        if old_modified and self._last_modified and old_modified != self._last_modified:
            return False
        return True

    def _validate_content_range(self, response, expected_start, expected_end=None):
        value = response.headers.get("Content-Range", "")
        match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)$", value, re.IGNORECASE)
        if not match:
            raise Exception("Server returned an invalid Content-Range header")
        actual_start, actual_end = int(match.group(1)), int(match.group(2))
        advertised_total = match.group(3)
        if actual_start != expected_start:
            raise Exception("Server resumed from an unexpected byte offset")
        if expected_end is not None and actual_end > expected_end:
            raise Exception("Server returned bytes outside the requested range")
        if advertised_total.isdigit() and self.total_size > 0:
            if int(advertised_total) != self.total_size:
                raise Exception("Remote file changed size while downloading")
        return actual_start, actual_end

    def _ensure_disk_space(self, remaining):
        if remaining <= 0:
            return
        free = shutil.disk_usage(self.save_dir).free
        if free < remaining:
            raise OSError(
                f"Not enough disk space: {remaining} bytes required, {free} bytes available"
            )

    def _finalize(self):
        # Rename atomically without overwriting a file created after path selection.
        finalized = False
        last_error = None
        for attempt in range(5):
            try:
                if os.path.exists(self.file_path):
                    raise FileExistsError(
                        f"A file already exists at the destination: {self.file_path}"
                    )
                os.rename(self.part_path, self.file_path)
                finalized = True
                break
            except PermissionError as exc:
                last_error = exc
                # Windows Defender or Explorer may briefly lock the file
                time.sleep(0.5 * (2 ** attempt))
            except Exception as exc:
                last_error = exc
                break

        if not finalized:
            raise last_error or OSError("Could not move completed download into place")

        if os.path.exists(self._meta_path):
            try:
                os.remove(self._meta_path)
            except Exception:
                pass

        self.finished.emit(self.file_path)

    def run(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            self._session = self._make_session()
            session = self._session

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

            self.filename = self._clean_filename_if_enabled(
                self._extract_filename(probe)
            )
            self._capture_validators(probe)

            if probe.status_code == 206:
                self._validate_content_range(probe, 0, 0)
                self.total_size = self._parse_total_size(probe.headers, 0)
                range_supported = True
                probe.close()
            else:
                self.total_size = self._parse_total_size(probe.headers, 0)
                normal_response = probe

            self.file_path, self.part_path, self._meta_path = self._select_output_paths()
            if self.total_size > 0:
                existing = os.path.getsize(self.part_path) if os.path.exists(self.part_path) else 0
                self._ensure_disk_space(max(0, self.total_size - existing))

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
            if not self.is_cancelled:
                self.error.emit(str(e))
        finally:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

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

            resume_meta = None
            if os.path.exists(self._meta_path):
                try:
                    with open(self._meta_path, "r", encoding="utf-8") as f:
                        candidate_meta = json.load(f)
                    if candidate_meta.get("mode") == "single" and self._meta_matches(candidate_meta):
                        resume_meta = candidate_meta
                except Exception:
                    pass

            if range_supported and existing > 0 and resume_meta is not None:
                response.close()

                if self.total_size > 0 and existing == self.total_size:
                    self.downloaded_size = existing
                    self._finalize()
                    return

                response = self._open_stream(
                    session,
                    {"Range": f"bytes={existing}-"}
                )

                if response.status_code == 206:
                    self._validate_content_range(response, existing)
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
                if existing > 0:
                    mode = "wb"
                    existing = 0
                self.total_size = self._parse_total_size(
                    response.headers,
                    self.total_size
                )

            self.downloaded_size = downloaded
            self._save_meta(None, mode="single")

            start_time = time.time()
            bytes_since_start = 0
            max_retries = 5
            retries = 0

            while True:
                if self.is_cancelled:
                    break

                if self.total_size > 0 and self.downloaded_size >= self.total_size:
                    break

                if not self._wait_active():
                    break

                stream_error = None
                try:
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

                                retries = 0
                except Exception as err:
                    stream_error = err
                finally:
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass
                        response = None

                if self.is_cancelled:
                    break

                if self.total_size > 0 and self.downloaded_size >= self.total_size:
                    break

                if stream_error is None and not self.is_paused and self.total_size <= 0:
                    break

                if not self._wait_active():
                    break

                if stream_error is not None or (self.total_size > 0 and self.downloaded_size < self.total_size):
                    retries += 1
                    if retries > max_retries:
                        if stream_error and not self.is_cancelled:
                            raise stream_error
                        break

                    time.sleep(min(1 * retries, 5))
                    if not self._wait_active():
                        break

                    headers = {"Range": f"bytes={self.downloaded_size}-"}
                    try:
                        response = self._open_stream(session, headers)
                        if response.status_code == 206:
                            self._validate_content_range(response, self.downloaded_size)
                            range_supported = True
                            mode = "ab"
                            continue
                        elif response.status_code == 200:
                            if not range_supported and self.downloaded_size == 0:
                                mode = "wb"
                                continue
                            else:
                                response.close()
                                response = None
                                raise Exception("Server does not support resuming range requests")
                        else:
                            status = response.status_code
                            response.close()
                            response = None
                            raise Exception(f"Server returned HTTP {status} on reconnect")
                    except Exception as conn_err:
                        if self.is_cancelled:
                            break
                        if retries >= max_retries:
                            raise conn_err
                        continue
                else:
                    break

            if self.is_cancelled:
                pass
            elif self.total_size > 0 and self.downloaded_size < self.total_size:
                self.error.emit("Connection lost. Download incomplete.")
            else:
                self._finalize()

        except Exception as e:
            if not self.is_cancelled:
                self.error.emit(str(e))

    def _load_or_create_segments(self):
        segments = []

        if os.path.exists(self._meta_path) and os.path.exists(self.part_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

                if meta.get("mode") == "segmented" and self._meta_matches(meta):
                    segments = meta.get("segments", [])
            except Exception:
                segments = []

        if not segments:
            if os.path.exists(self._meta_path):
                try:
                    os.remove(self._meta_path)
                except Exception:
                    pass

            segments = self._create_segments()

        if not os.path.exists(self.part_path):
            with open(self.part_path, "wb") as f:
                if self.total_size > 0:
                    try:
                        f.truncate(self.total_size)
                    except OSError as exc:
                        raise OSError(
                            f"Cannot prepare a {self.total_size}-byte download on the destination drive"
                        ) from exc
        elif self.total_size > 0:
            try:
                with open(self.part_path, "r+b") as f:
                    f.truncate(self.total_size)
            except OSError as exc:
                raise OSError(
                    f"Cannot prepare a {self.total_size}-byte download on the destination drive"
                ) from exc

        self.downloaded_size = sum(int(s[2]) for s in segments)
        return segments

    def _create_segments(self):
        """Build segment boundaries using unbounded Python integer offsets."""
        max_threads = self._get_max_threads()
        segment_count = min(
            max_threads,
            max(1, int(self.total_size // MIN_SEGMENT_SIZE))
        )
        if self.total_size <= 0:
            segment_count = 1

        size = self.total_size // segment_count if segment_count else 0
        start = 0
        segments = []
        for index in range(segment_count):
            end = self.total_size - 1 if index == segment_count - 1 else start + size - 1
            if end < start:
                end = start
            segments.append([start, end, 0])
            start = end + 1
        return segments

    def _save_meta(self, segments, mode="segmented"):
        try:
            # Deep-copy segments under lock to avoid data races
            safe_segments = None
            if segments is not None:
                with self._state_lock:
                    safe_segments = [[s[0], s[1], s[2]] for s in segments]

            meta = {
                "url": self.url,
                "total_size": self.total_size,
                "mode": mode,
                "etag": self._etag,
                "last_modified": self._last_modified,
                "segments": safe_segments
            }

            # Atomic write: serialize to .tmp, then os.replace to prevent corruption
            tmp_path = self._meta_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            os.replace(tmp_path, self._meta_path)
        except Exception:
            pass

    def _download_segmented(self, session):
        segments = self._load_or_create_segments()
        self._save_meta(segments)

        self._failure = None
        self._file = None
        executor = None

        try:
            self._file = open(self.part_path, "r+b")

            max_threads = self._get_max_threads()
            workers = min(max_threads, max(1, len(segments)))
            executor = ThreadPoolExecutor(max_workers=workers)

            futures = [
                executor.submit(self._segment_worker, session, seg)
                for seg in segments
            ]

            last_time = time.time()
            last_bytes = self.downloaded_size

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
                    if not self._failure and not self.is_cancelled:
                        self._failure = str(e)

        finally:
            if executor is not None:
                try:
                    executor.shutdown(wait=True, cancel_futures=True)
                except Exception:
                    pass

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
            pass
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

            if not self._wait_active():
                return False

            with self._state_lock:
                downloaded = int(seg[2])

            length = end - start + 1

            if downloaded >= length:
                return True

            pos = start + downloaded
            response = None
            segment_session = None

            try:
                headers = {"Range": f"bytes={pos}-{end}"}
                # requests.Session is not guaranteed to be thread-safe. Give each
                # segment an independent connection pool, especially for long transfers.
                segment_session = self._make_session()
                response = self._open_stream(segment_session, headers)

                if response.status_code == 200:
                    raise Exception("Server ignored range request")

                if response.status_code != 206:
                    raise Exception(
                        f"Server returned HTTP {response.status_code}"
                    )

                self._validate_content_range(response, pos, end)

                for chunk in response.iter_content(CHUNK_SIZE):
                    if not self._wait_active():
                        return False

                    if chunk:
                        # Clamp chunk to segment boundary to prevent overwriting next segment
                        remaining = end - pos + 1
                        if remaining <= 0:
                            break
                        if len(chunk) > remaining:
                            chunk = chunk[:remaining]

                        with self._file_lock:
                            if self._file and not self._file.closed:
                                self._file.seek(pos)
                                self._file.write(chunk)

                        n = len(chunk)
                        pos += n

                        with self._state_lock:
                            seg[2] = int(seg[2]) + n
                            self.downloaded_size += n

                if pos <= end:
                    raise Exception("Connection closed before the segment completed")
                return True

            except Exception as e:
                if attempt == retries - 1 or self.is_cancelled:
                    if not self.is_cancelled:
                        self._failure = str(e)
                    self._cancel_event.set()
                    self._pause_event.set()
                    return False

                time.sleep(1 + attempt)

            finally:
                # Always close response to prevent connection pool exhaustion
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                if segment_session is not None:
                    try:
                        segment_session.close()
                    except Exception:
                        pass

        return False
