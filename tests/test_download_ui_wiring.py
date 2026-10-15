"""Verify real Qt background routing and persisted destination updates."""
import time
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication

from app.controllers.downloader import DownloadWorker
from app.services.ai_client import AIClient
from app.views.pages.downloads_page import DownloadsPage


class Response:
    def __init__(self, status, headers, body=b""):
        self.status_code = status
        self.headers = headers
        self.body = body

    def close(self):
        pass

    def iter_content(self, _size):
        yield self.body


def test_routing_runs_in_worker_and_updates_card(monkeypatch, tmp_path):
    import app.views.pages.downloads_page as page_module
    import app.views.components.download_card as card_module
    import app.controllers.downloader as downloader_module
    import app.services.router as router_module
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(page_module, "get_all_tasks", lambda: [])
    monkeypatch.setattr(page_module, "create_task", lambda *_a, **_k: 1)
    monkeypatch.setattr(page_module, "get_setting", lambda _key, _default=None: str(tmp_path))
    monkeypatch.setattr(card_module, "get_setting", lambda _key, default=None: default)
    metadata = Mock()
    monkeypatch.setattr(card_module, "update_task_metadata", metadata)
    monkeypatch.setattr(card_module, "update_task_progress", Mock())
    monkeypatch.setattr(downloader_module, "get_setting", lambda _key, default=None: default)
    monkeypatch.setattr(router_module, "get_setting", lambda _key, default=None: default)
    monkeypatch.setattr(router_module, "get_all_rules", lambda: [])
    monkeypatch.setattr(DownloadsPage, "prompt_download_confirmation", lambda *a, **k: None)
    threads = []

    def classify(*_args):
        threads.append(QThread.currentThread())
        return "Games"

    monkeypatch.setattr(AIClient, "classify_category", classify)
    monkeypatch.setattr(DownloadWorker, "_make_session", lambda _self: SimpleNamespace(close=lambda: None))

    def stream(_self, _session, headers=None):
        if headers and headers.get("Range") == "bytes=0-0":
            return Response(206, {"Content-Range": "bytes 0-0/7", "ETag": '"v1"'})
        return Response(200, {"Content-Length": "7", "ETag": '"v1"'}, b"payload")

    monkeypatch.setattr(DownloadWorker, "_open_stream", stream)
    page = DownloadsPage()
    card = page.create_download_card("https://vendor.test/file.bin", auto_start=False)
    assert not threads
    card.start_download()
    deadline = time.monotonic() + 5
    while card.worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    try:
        assert not card.worker.isRunning()
        assert threads and threads[0] != app.thread()
        assert card.state == "completed"
        assert card.category == "Games"
        assert card.save_dir == str(tmp_path / "Games")
        assert (tmp_path / "Games" / "file.bin").read_bytes() == b"payload"
        metadata.assert_any_call(1, save_path=str(tmp_path / "Games"), category="Games")
    finally:
        card.worker.cancel()
        card.worker.wait(5000)
        page.deleteLater()
        app.processEvents()
