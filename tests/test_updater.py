import os
import sys
import pytest
from PyQt5.QtWidgets import QApplication

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Initialize QApplication for headless testing
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from app.common.version import __version__, APP_NAME, GITHUB_REPO, GITHUB_OWNER
from app.services.updater import UpdateService, UpdateCheckWorker
from app.services.update_installer import UpdateInstaller
from app.views.components.update_dialog import UpdateDialog
from app.views.pages.settings_page import SettingsPage
from app.models.database import init_db, get_setting, set_setting


def test_version_parsing():
    init_db()
    # Semantic Version Parsing
    assert UpdateService.parse_version_tuple("v1.0.1")[0] == (1, 0, 1)
    assert UpdateService.parse_version_tuple("1.0.0")[0] == (1, 0, 0)
    assert UpdateService.parse_version_tuple("v2.1.34-beta")[0] == (2, 1, 34)
    assert UpdateService.parse_version_tuple("v0.9")[0] == (0, 9, 0)
    assert UpdateService.parse_version_tuple("")[0] == (0, 0, 0)


def test_version_comparison():
    # Comparisons with stable and prerelease
    assert UpdateService.is_newer("v1.0.1", "1.0.0") is True
    assert UpdateService.is_newer("1.0.2", "1.0.1") is True
    assert UpdateService.is_newer("1.0.1", "1.0.1") is False
    assert UpdateService.is_newer("1.0.0", "1.0.1") is False
    assert UpdateService.is_newer("2.0.0", "1.9.9") is True
    # Stable vs Beta of same version
    assert UpdateService.is_newer("1.2.0", "1.2.0-beta.1") is True
    assert UpdateService.is_newer("1.2.0-beta.2", "1.2.0-beta.1") is True


def test_update_installer_hash_and_paths():
    # Test hash computation and verification
    test_file = os.path.join(os.path.dirname(__file__), "test_sample.tmp")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("NeuroGet Test Update Binary Payload")
    
    sha256 = UpdateInstaller.compute_sha256(test_file)
    assert len(sha256) == 64
    assert UpdateInstaller.verify_hash(test_file, sha256) is True
    assert UpdateInstaller.verify_hash(test_file, "invalidhash") is False
    
    if os.path.exists(test_file):
        os.remove(test_file)


def test_update_dialog_ui():
    mock_update_info = {
        "success": True,
        "has_update": True,
        "current_version": "1.0.1",
        "latest_version": "1.0.2",
        "tag_name": "v1.0.2",
        "release_name": "NeuroGet v1.0.2 (Performance Boost)",
        "changelog": "### What's New:\n- Added Auto-Updater system.\n- Multi-threaded download speedups.",
        "download_url": "https://github.com/mohammadrezamirtaleb/NeuroGet/releases/download/v1.0.2/NeuroGet_Setup.exe",
        "asset_name": "NeuroGet_Setup.exe",
        "asset_size": 91290922,
        "expected_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "channel": "stable",
        "html_url": "https://github.com/mohammadrezamirtaleb/NeuroGet/releases/tag/v1.0.2"
    }
    dialog = UpdateDialog(mock_update_info)
    assert dialog is not None
    assert "Software Update" in dialog.windowTitle() or "v1.0.2" in dialog.windowTitle()
    assert hasattr(dialog, "btn_download")
    assert hasattr(dialog, "progress_bar")
    assert hasattr(dialog, "btn_install_now")


def test_settings_page_update_integration():
    init_db()
    sp = SettingsPage()
    assert hasattr(sp, "check_updates_btn"), "Check updates button missing from SettingsPage"
    assert hasattr(sp, "auto_check_update_cb"), "Auto-check updates checkbox missing"
    assert hasattr(sp, "channel_combo"), "Update channel selector missing"
    assert sp.version_info_lbl.text() == f"{APP_NAME} v{__version__}"

    sp.auto_check_update_cb.setChecked(False)
    assert get_setting("auto_check_updates") == "false"
    sp.auto_check_update_cb.setChecked(True)
    assert get_setting("auto_check_updates") == "true"


def test_checksum_extraction_from_release():
    mock_release_body = {
        "body": "### NeuroGet v1.2.0\nSHA-256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "assets": []
    }
    extracted = UpdateService.extract_expected_checksum(mock_release_body, "NeuroGet_Setup.exe")
    assert extracted == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
