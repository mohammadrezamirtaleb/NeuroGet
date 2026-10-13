"""Focused regression tests for transfer integrity and files larger than 2 GiB."""
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch


try:
    from PyQt5.QtCore import QThread  # noqa: F401
except ImportError:
    class _Signal:
        def __set_name__(self, owner, name):
            self.name = name

        def __get__(self, instance, owner):
            if instance is None:
                return self
            return instance.__dict__.setdefault(
                self.name,
                types.SimpleNamespace(emit=lambda *args: instance._test_events.append((self.name, args)))
            )

    class _Thread:
        def __init__(self, *args, **kwargs):
            self._test_events = []

    qt_core = types.ModuleType("PyQt5.QtCore")
    qt_core.QThread = _Thread
    qt_core.pyqtSignal = lambda *args: _Signal()
    pyqt = types.ModuleType("PyQt5")
    pyqt.QtCore = qt_core
    sys.modules["PyQt5"] = pyqt
    sys.modules["PyQt5.QtCore"] = qt_core


from app.controllers.downloader import DownloadWorker


class _Response:
    def __init__(self, status=206, body=b"", headers=None):
        self.status_code = status
        self.body = body
        self.headers = headers or {}

    def close(self):
        pass

    def iter_content(self, _chunk_size):
        if self.body:
            yield self.body


class _Session:
    headers = {}

    def mount(self, *_args):
        pass

    def close(self):
        pass


def _worker(tmp_path, name="large.bin"):
    worker = DownloadWorker(1, f"https://example.test/{name}", str(tmp_path))
    if not hasattr(worker, "_test_events"):
        worker._test_events = []
        for signal_name in ("finished", "error"):
            getattr(worker, signal_name).connect(
                lambda *args, signal_name=signal_name: worker._test_events.append((signal_name, args))
            )
    worker.filename = name
    worker.file_path = str(tmp_path / name)
    worker.part_path = worker.file_path + ".part"
    worker._meta_path = worker.part_path + ".ngmeta"
    return worker


def test_large_file_segments_keep_64_bit_offsets(tmp_path):
    worker = _worker(tmp_path)
    worker.total_size = 5 * 1024**3 + 123
    worker._get_max_threads = lambda: 16

    segments = worker._create_segments()

    assert segments[0][0] == 0
    assert segments[-1][1] == worker.total_size - 1
    assert sum(end - start + 1 for start, end, _ in segments) == worker.total_size
    assert segments[-1][1] > 2**32


def test_content_range_parses_size_over_4_gib(tmp_path):
    worker = _worker(tmp_path)
    total = 7 * 1024**3 + 17
    response = _Response(headers={"Content-Range": f"bytes 0-0/{total}"})

    assert worker._parse_total_size(response.headers) == total
    worker.total_size = total
    assert worker._validate_content_range(response, 0, 0) == (0, 0)


def test_resume_rejects_partial_from_another_download(tmp_path):
    worker = _worker(tmp_path, "resume.bin")
    worker.total_size = 6
    Path(worker.part_path).write_bytes(b"OLD")
    Path(worker._meta_path).write_text(json.dumps({
        "mode": "single", "url": "https://other.test/file",
        "total_size": 6, "segments": None
    }), encoding="utf-8")
    initial = _Response(status=200, body=b"NEWnew", headers={"Content-Length": "6"})

    worker._download_single(None, initial, range_supported=True)

    assert Path(worker.file_path).read_bytes() == b"NEWnew"


def test_finalize_does_not_report_success_when_rename_fails(tmp_path):
    worker = _worker(tmp_path, "locked.bin")
    Path(worker.part_path).write_bytes(b"payload")
    Path(worker._meta_path).write_text("{}", encoding="utf-8")

    with patch("app.controllers.downloader.os.rename", side_effect=PermissionError("locked")), \
            patch("app.controllers.downloader.time.sleep", return_value=None):
        try:
            worker._finalize()
        except PermissionError:
            pass
        else:
            raise AssertionError("a failed final rename must raise")

    assert Path(worker.part_path).exists()
    assert Path(worker._meta_path).exists()
    assert not Path(worker.file_path).exists()
    if hasattr(worker, "_test_events"):
        assert not any(name == "finished" for name, _ in worker._test_events)


def test_output_name_collision_is_preserved(tmp_path):
    (tmp_path / "report.bin").write_bytes(b"original")
    worker = _worker(tmp_path, "report.bin")

    target, part, _meta = worker._select_output_paths()

    assert Path(target).name == "report (1).bin"
    assert Path(part).exists()
    assert (tmp_path / "report.bin").read_bytes() == b"original"
    worker._release_path_lock()


def test_segment_failure_emits_an_error(tmp_path):
    worker = _worker(tmp_path, "failure.bin")
    worker.total_size = 8 * 1024 * 1024
    worker._get_max_threads = lambda: 1
    worker._open_stream = lambda *_args, **_kwargs: _Response(status=503)

    with patch("app.controllers.downloader.time.sleep", return_value=None):
        worker._download_segmented(None)

    if hasattr(worker, "_test_events"):
        assert any(name == "error" for name, _ in worker._test_events)
        assert not any(name == "finished" for name, _ in worker._test_events)
    assert worker._failure == "Server returned HTTP 503"


def test_segmented_download_writes_every_byte(tmp_path):
    worker = _worker(tmp_path, "complete.bin")
    worker.total_size = 8 * 1024 * 1024
    worker._get_max_threads = lambda: 2
    worker._make_session = _Session

    def ranged_response(_session, headers):
        start_text, end_text = headers["Range"].removeprefix("bytes=").split("-")
        start, end = int(start_text), int(end_text)
        body = bytes([65 + start // (4 * 1024 * 1024)]) * (end - start + 1)
        return _Response(
            body=body,
            headers={"Content-Range": f"bytes {start}-{end}/{worker.total_size}"}
        )

    worker._open_stream = ranged_response
    worker._download_segmented(None)

    result = Path(worker.file_path).read_bytes()
    assert len(result) == worker.total_size
    assert result[:1] == b"A"
    assert result[-1:] == b"B"
    if hasattr(worker, "_test_events"):
        assert any(name == "finished" for name, _ in worker._test_events)


def test_tls_error_is_not_retried_without_verification(tmp_path):
    worker = _worker(tmp_path, "secure.bin")

    class FailingSession:
        def __init__(self):
            self.calls = 0

        def get(self, *_args, **_kwargs):
            import requests
            self.calls += 1
            raise requests.exceptions.SSLError("untrusted certificate")

    session = FailingSession()
    try:
        worker._open_stream(session)
    except Exception as exc:
        assert "untrusted certificate" in str(exc)
    else:
        raise AssertionError("TLS failure must be reported")
    assert session.calls == 1


def test_duplicate_url_cannot_reuse_an_active_partial(tmp_path):
    first = _worker(tmp_path, "duplicate.bin")
    second = _worker(tmp_path, "duplicate.bin")
    try:
        first.file_path, first.part_path, first._meta_path = first._select_output_paths()
        first._etag = '"v1"'
        first._save_meta(None, mode="single")
        second_path, _, _ = second._select_output_paths()
        assert second_path != first.file_path
    finally:
        first._release_path_lock()
        second._release_path_lock()


def test_partial_can_be_resumed_after_owner_releases_it(tmp_path):
    first = _worker(tmp_path, "resume-owner.bin")
    second = _worker(tmp_path, "resume-owner.bin")
    try:
        first.file_path, first.part_path, first._meta_path = first._select_output_paths()
        first._save_meta(None, mode="single")
        first._release_path_lock()
        second_path, _, _ = second._select_output_paths()
        assert second_path == first.file_path
    finally:
        first._release_path_lock()
        second._release_path_lock()


def test_resume_requires_a_matching_file_validator(tmp_path):
    worker = _worker(tmp_path)
    worker.total_size = 100
    meta = {"url": worker.url, "total_size": 100}
    assert not worker._meta_matches(meta)
    worker._etag = '"new"'
    assert not worker._meta_matches({**meta, "etag": '"old"'})
    assert worker._meta_matches({**meta, "etag": '"new"'})
    worker._etag = 'W/"weak"'
    assert not worker._meta_matches({**meta, "etag": worker._etag})
    worker._last_modified = "Wed, 01 Jan 2025 00:00:00 GMT"
    assert worker._meta_matches({**meta, "last_modified": worker._last_modified})


def test_range_request_includes_if_range(tmp_path):
    worker = _worker(tmp_path)
    worker._etag = '"file-v1"'
    session = types.SimpleNamespace(get=lambda *_a, **kw: kw)
    options = worker._open_stream(session, {"Range": "bytes=10-20"})
    assert options["headers"]["If-Range"] == '"file-v1"'


def test_stale_segment_metadata_restarts_all_segments(tmp_path):
    worker = _worker(tmp_path)
    worker.total_size = 6
    Path(worker.part_path).write_bytes(b"OLDold")
    Path(worker._meta_path).write_text(json.dumps({
        "mode": "segmented", "url": worker.url, "total_size": 6,
        "segments": [[0, 5, 3]]
    }), encoding="utf-8")
    assert worker._load_or_create_segments() == [[0, 5, 0]]
    assert worker.downloaded_size == 0
