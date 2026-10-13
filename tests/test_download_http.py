"""Exercise real HTTP range transfers against a loopback server."""
import hashlib
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.controllers.downloader import DownloadWorker


@pytest.fixture
def download_server():
    payload = (b"NeuroGet range transfer integrity.\n" * 250000)[:8 * 1024 * 1024 + 31]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ranged = self.headers.get("Range", "")
            if ranged and ranged != "bytes=0-0" and self.headers.get("Cookie") != "download_session=valid":
                self.send_error(403)
                return
            start, end = 0, len(payload) - 1
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", ranged)
            status = 200
            if match and self.headers.get("If-Range", '"v1"') == '"v1"':
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                status = 206
            self.send_response(status)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="large.bin"')
            self.send_header("ETag", '"v1"')
            self.send_header("Set-Cookie", "download_session=valid; Path=/")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            self.end_headers()
            self.wfile.write(payload[start:end + 1])

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/file", payload
    server.shutdown()
    server.server_close()
    thread.join(2)


def test_real_segmented_http_transfer_preserves_session_and_bytes(monkeypatch, tmp_path, download_server):
    import app.controllers.downloader as module
    monkeypatch.setattr(module, "get_setting", lambda key, default=None: {
        "max_threads": "4", "enable_ai_clean_renaming": "false"
    }.get(key, default))
    url, payload = download_server
    worker = DownloadWorker(1, url, str(tmp_path))
    failures, completed = [], []
    worker.error.connect(failures.append)
    worker.finished.connect(completed.append)
    worker.run()
    assert failures == []
    assert completed == [str(tmp_path / "large.bin")]
    assert hashlib.sha256((tmp_path / "large.bin").read_bytes()).digest() == hashlib.sha256(payload).digest()
    assert not (tmp_path / "large.bin.part.ngmeta").exists()
