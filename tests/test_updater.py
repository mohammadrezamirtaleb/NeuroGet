import os
import sys
import unittest
from PyQt5.QtWidgets import QApplication

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Initialize QApplication for headless testing
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from app.common.version import __version__, APP_NAME, GITHUB_REPO, GITHUB_OWNER
from app.services.updater import UpdateService, UpdateCheckWorker
from app.views.components.update_dialog import UpdateDialog
from app.views.pages.settings_page import SettingsPage
from app.models.database import init_db, get_setting, set_setting

def run_updater_tests():
    print("==========================================")
    print("   TESTING NEUROGET AUTO-UPDATER SYSTEM   ")
    print("==========================================")

    init_db()

    # --- 1. Test Version Parsing ---
    print("\n--- 1. Testing Semantic Version Parsing ---")
    assert UpdateService.parse_version_tuple("v1.0.1") == (1, 0, 1)
    assert UpdateService.parse_version_tuple("1.0.0") == (1, 0, 0)
    assert UpdateService.parse_version_tuple("v2.1.34-beta") == (2, 1, 34)
    assert UpdateService.parse_version_tuple("v0.9") == (0, 9, 0)
    assert UpdateService.parse_version_tuple("") == (0, 0, 0)
    print("[PASS] Version parsing handles all standard formats")

    # --- 2. Test Version Comparison ---
    print("\n--- 2. Testing Version Comparisons ---")
    assert UpdateService.is_newer("v1.0.1", "1.0.0") is True
    assert UpdateService.is_newer("1.0.2", "1.0.1") is True
    assert UpdateService.is_newer("1.0.1", "1.0.1") is False
    assert UpdateService.is_newer("1.0.0", "1.0.1") is False
    assert UpdateService.is_newer("2.0.0", "1.9.9") is True
    print("[PASS] Semantic version comparison is 100% accurate")

    # --- 3. Test Live GitHub API Query on NeuroGet Repo ---
    print("\n--- 3. Testing Live GitHub API Release Check ---")
    res = UpdateService.check_for_updates(current_version="1.0.0")
    print(f"Update check with older local version (1.0.0):")
    print(f"  Success: {res.get('success')}")
    print(f"  Has Update: {res.get('has_update')}")
    print(f"  Latest Version: {res.get('latest_version')}")
    print(f"  Asset Name: {res.get('asset_name')}")
    print(f"  Download URL: {res.get('download_url')}")
    safe_log = res.get('changelog', '')[:100].encode('ascii', errors='replace').decode('ascii')
    print(f"  Changelog excerpt: {safe_log}...")

    assert res.get("success") is True, f"GitHub check failed: {res.get('error')}"
    assert res.get("has_update") is True, "Expected update to be detected for local version 1.0.0"
    assert res.get("latest_version") == "1.0.1", f"Expected latest version 1.0.1, got {res.get('latest_version')}"
    assert res.get("asset_name") == "NeuroGet_Setup.exe", f"Expected NeuroGet_Setup.exe asset, got {res.get('asset_name')}"
    print("[PASS] Live GitHub Releases query and setup asset extraction OK")

    # --- 4. Test Current Version (1.0.1 is up to date) ---
    print("\n--- 4. Testing Up-To-Date Scenario (v1.0.1) ---")
    res_current = UpdateService.check_for_updates(current_version="1.0.1")
    assert res_current.get("success") is True
    assert res_current.get("has_update") is False, "v1.0.1 falsely flagged as having an update"
    print(f"Current version v1.0.1 correctly recognized as up-to-date")
    print("[PASS] Up-to-date recognition OK")

    # --- 5. Test UpdateDialog UI ---
    print("\n--- 5. Testing UpdateDialog UI Component ---")
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
        "html_url": "https://github.com/mohammadrezamirtaleb/NeuroGet/releases/tag/v1.0.2"
    }
    dialog = UpdateDialog(mock_update_info)
    assert dialog is not None
    assert "v1.0.2" in dialog.windowTitle() or "Software Update" in dialog.windowTitle()
    print("[PASS] UpdateDialog rendered properly")

    # --- 6. Test Settings Page Update Integration ---
    print("\n--- 6. Testing Settings Page Update Integration ---")
    sp = SettingsPage()
    assert hasattr(sp, "check_updates_btn"), "Check updates button missing from SettingsPage"
    assert hasattr(sp, "auto_check_update_cb"), "Auto-check updates checkbox missing"
    assert sp.version_info_lbl.text() == f"{APP_NAME} v{__version__}"

    sp.auto_check_update_cb.setChecked(False)
    assert get_setting("auto_check_updates") == "false"
    sp.auto_check_update_cb.setChecked(True)
    assert get_setting("auto_check_updates") == "true"
    print("[PASS] Settings Page updates card & persistence OK")

    print("\n==========================================")
    print("SUCCESS: ALL AUTO-UPDATER TESTS PASSED 100%!")
    print("==========================================")

if __name__ == "__main__":
    run_updater_tests()
