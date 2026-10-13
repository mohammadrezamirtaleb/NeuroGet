"""Real Qt regressions for queued starts, batch order, and follow-up chat."""
import time
from threading import Event
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QApplication

from app.controllers.downloader import DownloadWorker
from app.services.ai_client import AIClient
from app.views.pages.downloads_page import DownloadsPage
from app.views.components.ai_summary_dialog import AISummaryDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(monkeypatch, tmp_path, qt_app):
    import app.views.pages.downloads_page as page_module
    import app.views.components.download_card as card_module
    monkeypatch.setattr(page_module, "get_all_tasks", lambda: [])
    monkeypatch.setattr(page_module, "create_task", lambda *_a, **_k: 1)
    monkeypatch.setattr(page_module, "get_setting", lambda _key, _default=None: str(tmp_path))
    monkeypatch.setattr(card_module, "get_setting", lambda _key, default=None: default)
    monkeypatch.setattr(card_module, "update_task_metadata", Mock())
    monkeypatch.setattr(card_module, "update_task_progress", Mock())
    monkeypatch.setattr(card_module, "delete_task", Mock())
    monkeypatch.setattr(card_module.InfoBar, "error", Mock())
    monkeypatch.setattr(DownloadWorker, "start", Mock())
    widget = DownloadsPage()
    yield widget
    for child in widget.findChildren(DownloadWorker):
        assert not child.isRunning()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_resume_all_starts_a_standalone_queued_task(page):
    card = page.create_download_card("https://vendor.test/file.bin", auto_start=False)
    assert card.state == "queued"
    page.resume_all_downloads()
    assert card.state == "downloading"
    assert card.worker.start.call_count == 1


def test_resume_all_preserves_sequential_batch_order(page):
    page.enqueue_urls(["https://vendor.test/first.bin", "https://vendor.test/second.bin"])
    first = page.active_batch_card
    second = page.batch_queue[0]
    page.pause_all_downloads()
    first.cancel_download()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert page.active_batch_card is None
    assert second.state == "queued"
    page.resume_all_downloads()
    assert page.active_batch_card == second
    assert second.state == "downloading"
    assert second.worker.start.call_count == 2
    assert page.batch_queue == []


def test_context_menu_can_start_a_queued_task(page):
    card = page.create_download_card("https://vendor.test/file.bin", auto_start=False)
    card.toggle_pause()
    assert card.state == "downloading"


def test_retry_emits_completion_for_each_attempt(page):
    card = page.create_download_card("https://vendor.test/file.bin", auto_start=False)
    terminal = Mock()
    card.taskFinished.connect(terminal)
    card.start_download()
    card.on_error("test connection failure")
    card.toggle_pause()
    card.on_finished("test-file.bin")
    assert terminal.call_count == 2
    assert card.state == "completed"


def test_retry_waits_for_previous_worker_to_exit(page, monkeypatch):
    card = page.create_download_card("https://vendor.test/file.bin", auto_start=False)
    card.state = "error"
    previous = card.worker
    running = Mock(return_value=True)
    monkeypatch.setattr(previous, "isRunning", running)
    card.start_download()
    assert card.worker == previous
    assert card.retry_timer.isActive()
    running.return_value = False
    card.start_download()
    assert card.worker != previous
    assert not card.retry_timer.isActive()
    assert card.state == "downloading"


def wait_for_chat(dialog, app):
    deadline = time.monotonic() + 5
    while dialog.chat_worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not dialog.chat_worker.isRunning()


@pytest.fixture
def dialog(monkeypatch, tmp_path, qt_app):
    monkeypatch.setattr(AISummaryDialog, "_start_analysis", lambda _self: None)
    widget = AISummaryDialog(str(tmp_path / "document.txt"))
    widget._on_analysis_finished({"raw_text": "Aurora project details", "summary": "Overview", "metadata": {}})
    yield widget
    if widget.chat_worker is not None:
        widget.chat_worker.wait(5000)
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_chat_follow_up_passes_previous_turns_and_file(dialog, monkeypatch, qt_app):
    answer = Mock(return_value="Aurora deadline is November.")
    monkeypatch.setattr(AIClient, "chat_with_document", answer)
    dialog.chat_input.setText("What is <Aurora>?")
    dialog.send_chat_message()
    wait_for_chat(dialog, qt_app)
    dialog.chat_input.setText("When is its deadline?")
    dialog.send_chat_message()
    wait_for_chat(dialog, qt_app)
    kwargs = answer.call_args.kwargs
    assert kwargs["history"] == [
        {"role": "user", "content": "What is <Aurora>?"},
        {"role": "assistant", "content": "Aurora deadline is November."}
    ]
    assert kwargs["filepath"] == dialog.filepath
    assert "What is <Aurora>?" in dialog.chat_history.toPlainText()
    assert "Searching document and generating answer" not in dialog.chat_history.toPlainText()
    assert dialog.badge_ai_val.text() == "Local Summary"


def test_closing_chat_preserves_worker_until_it_finishes(dialog, monkeypatch, qt_app):
    started, release = Event(), Event()

    def answer(*_args, **_kwargs):
        started.set()
        release.wait(2)
        return "answer"

    monkeypatch.setattr(AIClient, "chat_with_document", answer)
    dialog.chat_input.setText("What is Aurora?")
    dialog.send_chat_message()
    assert started.wait(1)
    try:
        dialog.accept()
        assert dialog._pending_close_result == dialog.Accepted
        assert dialog.chat_worker.isRunning()
    finally:
        release.set()
        wait_for_chat(dialog, qt_app)
    assert dialog.result() == dialog.Accepted
    assert dialog._pending_close_result is None
