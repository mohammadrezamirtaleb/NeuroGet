"""Keep Qt's global objects alive across all UI test modules."""
import pytest
import os
import sys
import tempfile
from pathlib import Path


def pytest_configure(config):
    if "app.models.database" in sys.modules:
        raise pytest.UsageError("Start tests with 'python -m pytest tests' before importing the application database.")
    # Configure storage before test collection imports app.models.database.
    # A plain `pytest tests` must never use the user's real download database.
    storage = tempfile.TemporaryDirectory(prefix=".pytest-runtime-", dir=Path(__file__).resolve().parents[1])
    config._neuroget_test_storage = storage
    config._neuroget_original_appdata = os.environ.get("LOCALAPPDATA")
    config._neuroget_original_tempdir = tempfile.tempdir
    os.environ["LOCALAPPDATA"] = storage.name
    tempfile.tempdir = storage.name


def pytest_unconfigure(config):
    storage = getattr(config, "_neuroget_test_storage", None)
    if storage is None:
        return
    database = sys.modules.get("app.models.database")
    if database is not None:
        database.engine.dispose()
    original = config._neuroget_original_appdata
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original
    tempfile.tempdir = config._neuroget_original_tempdir
    storage.cleanup()


@pytest.fixture(scope="session", autouse=True)
def keep_qt_application_alive():
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        yield None
        return
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def isolate_legacy_smoke_tests(request, monkeypatch, tmp_path):
    """Legacy UI/feature checks exercise fallbacks without user accounts/services."""
    module_name = request.module.__name__.split(".")[-1]
    if module_name not in {"test_ai_features", "test_ui_comprehensive", "test_updater"}:
        return
    from app.services.ai_client import AIClient
    from app.models import database
    from app.models.schemas import SmartRule
    monkeypatch.setattr(AIClient, "call_llm", lambda *_args, **_kwargs: None)
    database.init_db()
    database.set_setting("default_download_dir", str(tmp_path))
    with database.SessionLocal() as session:
        for rule in session.query(SmartRule).all():
            rule.destination_path = str(tmp_path / (rule.name or "Custom Rule"))
        session.commit()
    if module_name == "test_ui_comprehensive":
        from app.services.ai_scanner import LocalAIDetector
        monkeypatch.setattr(LocalAIDetector, "detect_providers", lambda: [])
        monkeypatch.setattr(AIClient, "_validate_download_result", lambda result: {
            **result, "direct_link_hint": ""
        })
        monkeypatch.setattr(request.module.MainWindow, "check_updates_on_startup", lambda _self: None)
