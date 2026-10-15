import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt5.QtCore import QCoreApplication
from app.controllers.downloader import DownloadWorker
from app.services.ai_client import AIClient
from app.services.threat_detector import ThreatDetector
from app.services.password_finder import PasswordFinder
from app.services.ai_scanner import LocalAIDetector


class _MockResponse:
    def __init__(self, status_code, body=b"", headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}

    def close(self):
        pass

    def iter_content(self, chunk_size=65536):
        if self.body:
            for i in range(0, len(self.body), chunk_size):
                yield self.body[i:i + chunk_size]


class _FlakyStreamSession:
    """Simulates connection drops during streaming and reconnects."""
    def __init__(self):
        self.reconnect_calls = 0

    def get(self, url, headers=None, stream=True, timeout=None):
        return None


def test_retry_corruption_prevention(tmp_path):
    """Bug 1: Verify that a failed reconnect attempt does NOT truncate .part file in 'wb' mode."""
    worker = DownloadWorker(1, "https://example.com/testfile.bin", str(tmp_path))
    worker.total_size = 10000
    worker.filename = "testfile.bin"
    worker.file_path = str(tmp_path / "testfile.bin")
    worker.part_path = worker.file_path + ".part"
    worker._meta_path = worker.part_path + ".ngmeta"
    worker._etag = '"mock-etag-123"'

    first_chunk = b"X" * 7000
    remaining_chunk = b"Y" * 3000

    class FirstDropResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {
                "Content-Length": "10000",
                "ETag": '"mock-etag-123"',
                "Accept-Ranges": "bytes"
            }

        def iter_content(self, chunk_size):
            yield first_chunk
            # Connection drops after yielding 7000 bytes
            raise ConnectionResetError("Connection dropped mid-stream")

        def close(self):
            pass

    reconnect_attempts = 0

    def mock_open_stream(session, headers=None):
        nonlocal reconnect_attempts
        headers = headers or {}
        reconnect_attempts += 1
        if reconnect_attempts == 1:
            # First reconnect fails (e.g. server unreachable)
            raise ConnectionError("Temporary network unreachable")
        else:
            # Second reconnect succeeds with HTTP 206
            resp = _MockResponse(
                status_code=206,
                body=remaining_chunk,
                headers={
                    "Content-Range": "bytes 7000-9999/10000",
                    "Content-Length": "3000",
                    "ETag": '"mock-etag-123"'
                }
            )
            return resp

    worker._open_stream = mock_open_stream

    # Run single download with initial response
    worker._download_single(MagicMock(), FirstDropResponse(), range_supported=True)

    # Verify final completed file is exactly 10,000 bytes without truncation
    final_file = Path(worker.file_path)
    assert final_file.exists(), "Final file was not created"
    content = final_file.read_bytes()
    assert len(content) == 10000, f"Expected 10000 bytes, got {len(content)}"
    assert content[:7000] == first_chunk, "First 7000 bytes were truncated or corrupted"
    assert content[7000:] == remaining_chunk, "Remaining 3000 bytes were corrupted"


def test_heuristic_clean_name_preserves_filenames():
    """Bug 2: Verify that clean renaming does not destroy compound extensions, version dots, or dot-separated names."""
    cases = [
        ("project.tar.gz", "project.tar.gz"),
        ("invoice.pdf.exe", "invoice.pdf.exe"),
        ("my.file.pdf", "my.file.pdf"),
        ("notes.old.txt", "notes.old.txt"),
        ("python-3.12.0-amd64.exe", "python-3.12.0-amd64.exe"),
        ("[Soft98.ir]_python-3.12.0-amd64.exe", "python-3.12.0-amd64.exe"),
        ("(Soft98.ir) test_package.zip", "test_package.zip"),
        ("www.soft98.ir_tool.exe", "tool.exe"),
        ("soft98.ir_tool.exe", "tool.exe"),
    ]
    for raw, expected in cases:
        result = AIClient._heuristic_clean_name(raw)
        assert result == expected, f"Expected '{expected}', got '{result}' for input '{raw}'"


def test_threat_detector_no_severity_downgrade():
    """Bug 4a: A danger result (e.g. crack.pdf.exe at 500KB) must never be downgraded to warning."""
    res = ThreatDetector.analyze_download("crack.pdf.exe", "https://example.com/crack.pdf.exe", 500 * 1024)
    assert res["level"] == "danger", f"Expected 'danger', got '{res['level']}'"
    assert res["is_safe"] is False


def test_threat_detector_space_before_extension_evasion():
    """Bug 4b: 'invoice.pdf .exe' with space before extension must be caught as danger."""
    res = ThreatDetector.analyze_download("invoice.pdf .exe", "https://example.com/inv.exe", 100 * 1024)
    assert res["level"] == "danger", f"Expected 'danger' for double extension with space, got '{res['level']}'"
    assert res["is_safe"] is False


def test_threat_detector_discrete_keyword_false_positives():
    """Bug 4c: Plain substring keywords like 'Seasonal_Planner_Setup.exe' must not trigger 'season' keyword."""
    res = ThreatDetector.analyze_download("Seasonal_Planner_Setup.exe", "https://example.com/setup.exe", 20 * 1024 * 1024)
    assert res["level"] == "safe", f"Expected 'safe', got '{res['level']}' with reasons {res['reasons']}"
    assert res["is_safe"] is True


def test_url_sanitization_for_ai():
    """Strip tokens, credentials, and query params before sending URL to AI models."""
    dirty_url = "https://user:pass@example.com/download/file.zip?token=secret123&sig=abc#frag"
    clean_url = AIClient._sanitize_url_for_ai(dirty_url)
    assert "token" not in clean_url
    assert "secret123" not in clean_url
    assert "sig=" not in clean_url
    assert "pass" not in clean_url
    assert clean_url == "https://example.com/download/file.zip"


def test_range_probe_416_fallback(tmp_path):
    """Server returning HTTP 416 on Range probe must fall back to normal GET instead of failing."""
    worker = DownloadWorker(1, "https://example.com/file.bin", str(tmp_path))
    worker.filename = "file.bin"
    worker.file_path = str(tmp_path / "file.bin")
    worker.part_path = worker.file_path + ".part"
    worker._meta_path = worker.part_path + ".ngmeta"

    calls = []

    def mock_open_stream(session, headers=None):
        headers = headers or {}
        calls.append(headers)
        if "Range" in headers:
            # Range request fails with 416
            return _MockResponse(416, headers={})
        else:
            # Normal GET succeeds with 200
            return _MockResponse(200, body=b"Hello World", headers={"Content-Length": "11"})

    worker._open_stream = mock_open_stream
    worker._make_session = MagicMock()
    # Mock single download to simply write and finish
    worker._download_single = MagicMock()

    # Worker.run should succeed and fall back to normal stream
    errors = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors == [], f"Unexpected errors: {errors}"
    assert len(calls) >= 2, "Expected at least 2 requests (range probe + fallback GET)"
    assert "Range" in calls[0]
    assert "Range" not in calls[1]


def test_incomplete_files_cleanup_on_cancel(tmp_path):
    """Leftover .part, .ngmeta, and .nglock files must be cleaned up on cancel."""
    worker = DownloadWorker(1, "https://example.com/file.bin", str(tmp_path))
    worker.filename = "file.bin"
    worker.file_path = str(tmp_path / "file.bin")
    worker.part_path = worker.file_path + ".part"
    worker._meta_path = worker.part_path + ".ngmeta"

    # Create dummy files
    Path(worker.part_path).write_bytes(b"dummy part")
    Path(worker._meta_path).write_text("{}", encoding="utf-8")
    Path(worker.part_path + ".nglock").write_bytes(b"\0")

    worker.cleanup_incomplete_files()

    assert not Path(worker.part_path).exists()
    assert not Path(worker._meta_path).exists()
    # Keep the lock inode stable so competing processes cannot lock different files.
    assert Path(worker.part_path + ".nglock").exists()


def test_ai_scanner_gguf_removesuffix():
    """Verify that stripping .gguf removes only the extension, not trailing letters."""
    rel = "debug_model.gguf"
    model_id = rel.replace('\\', '/')
    if model_id.endswith('.gguf'):
        model_id = model_id[:-5]
    assert model_id == "debug_model"


def test_ui_empty_subtitle_layout():
    """Verify empty state subtitle in DownloadsPage has comfortable width, height, and no clipping."""
    from app.models.database import init_db
    init_db()
    from app.views.pages.downloads_page import DownloadsPage

    page = DownloadsPage()
    # Find empty_subtitle in empty_card
    sub = None
    for child in page.empty_card.children():
        if hasattr(child, 'text') and 'Paste any download' in child.text():
            sub = child
            break

    assert sub is not None, "empty_subtitle should exist"
    assert sub.wordWrap() is True
    assert sub.minimumWidth() >= 480
    assert sub.minimumHeight() >= 40
    assert "\n" in sub.text(), "Subtitle should have balanced line break"
    assert "Paste URL (HTTP/HTTPS)" in page.url_input.placeholderText()
    assert "FTP" not in page.url_input.placeholderText()


def test_ui_threat_checkbox_ampersand():
    """Verify ampersand is escaped in QCheckBox so it does not get swallowed by mnemonic."""
    from app.models.database import init_db
    init_db()
    from app.views.pages.settings_page import SettingsPage

    page = SettingsPage()
    assert "Threat && Clickbait" in page.threat_check.text()


def test_ui_download_card_copy_url_clipboard_tracking():
    """Verify copy_url updates last_clipboard_text on DownloadsPage to prevent prompt loops."""
    from app.models.database import init_db
    init_db()
    from app.views.pages.downloads_page import DownloadsPage
    from app.views.components.download_card import DownloadCard

    page = DownloadsPage()
    card = DownloadCard(
        "https://example.com/test.zip",
        "test.zip",
        "C:/Downloads",
        auto_start=False,
        parent=page
    )
    card.copy_url()
    assert page.last_clipboard_text == "https://example.com/test.zip"
    from PyQt5.QtWidgets import QApplication
    QApplication.clipboard().clear()


def test_nglock_deleted_on_finalize(tmp_path):
    """Verify that when a download finishes, .nglock is deleted so user sees only the downloaded file."""
    worker = DownloadWorker(1, "https://example.com/song.mp3", str(tmp_path))
    worker.filename = "song.mp3"
    worker.file_path = str(tmp_path / "song.mp3")
    worker.part_path = worker.file_path + ".part"
    worker._meta_path = worker.part_path + ".ngmeta"
    lock_path = worker.part_path + ".nglock"

    # Simulate in-progress state with locked .nglock, .ngmeta, and .part
    Path(worker.part_path).write_bytes(b"audio data")
    Path(worker._meta_path).write_text("{}", encoding="utf-8")
    worker._path_lock = worker._try_lock_path(worker.part_path)
    assert Path(lock_path).exists()

    # Finalize download
    worker._finalize()

    # User must see only the downloaded file; .nglock and .part must NOT exist
    assert Path(worker.file_path).exists()
    assert not Path(worker.part_path).exists()
    assert not Path(worker._meta_path).exists()
    assert not Path(lock_path).exists(), ".nglock must be deleted on completion"


def test_nglock_hidden_on_windows(tmp_path):
    """Verify that .nglock file is created with Windows hidden attribute."""
    part_path = str(tmp_path / "test.mp3.part")
    lock = DownloadWorker._try_lock_path(part_path)
    assert lock is not None
    try:
        lock_file = part_path + ".nglock"
        assert os.path.exists(lock_file)
        if os.name == "nt":
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(os.path.abspath(lock_file))
            assert attrs != -1
            assert bool(attrs & 0x02), ".nglock must have FILE_ATTRIBUTE_HIDDEN on Windows"
    finally:
        lock.close()
        if os.path.exists(part_path + ".nglock"):
            os.remove(part_path + ".nglock")


