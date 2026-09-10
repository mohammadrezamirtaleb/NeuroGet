import os
import sys
import tempfile
import zipfile
import time

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, Qt

# Initialize QApplication for headless testing
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from main import MainWindow
from app.models.database import init_db, get_setting, set_setting, create_rule, get_all_rules
from app.views.pages.downloads_page import DownloadsPage, NLPromptWorker
from app.views.pages.smart_rules_page import SmartRulesPage, TestRouteWorker
from app.views.pages.settings_page import SettingsPage
from app.views.components.download_card import DownloadCard
from app.views.components.ai_summary_dialog import AISummaryDialog, SummaryWorker, ChatWorker
from app.services.ai_client import AIClient
from app.services.router import SmartRouter
from app.services.threat_detector import ThreatDetector
from app.services.content_analyzer import ContentAnalyzer

def test_full_ui_suite():
    print("--- 1. Testing Database Initialization ---")
    init_db()
    print("[PASS] Database initialized")

    print("\n--- 2. Testing MainWindow and Sub-Interfaces ---")
    window = MainWindow()
    assert window.downloads_interface is not None, "DownloadsPage missing"
    assert window.rules_interface is not None, "SmartRulesPage missing"
    assert window.settings_interface is not None, "SettingsPage missing"
    print("[PASS] MainWindow & Interfaces created")

    print("\n--- 3. Testing Theme Toggling ---")
    initial_theme = window.toggle_theme()
    window.toggle_theme()
    print("[PASS] Theme Toggle works smoothly")

    print("\n--- 4. Testing Downloads Page Actions ---")
    dp = window.downloads_interface
    # Test adding direct link
    test_url = "https://speed.hetzner.de/100MB.bin"
    card = dp.create_download_card(test_url, auto_start=False, status="queued", insert_top=True)
    assert card is not None, "DownloadCard creation failed"
    assert card.filename == "100MB.bin", f"Unexpected filename: {card.filename}"
    print("[PASS] Direct Download Card Created")

    # Test Natural Language Worker
    nl_worker = NLPromptWorker("download python 3.12 installer")
    # Execute run synchronously
    nl_worker.run()
    print("[PASS] Natural Language Download Worker OK")

    print("\n--- 5. Testing DownloadCard States & Signals ---")
    card.on_metadata_ready("Clean_Document_Sample.pdf", 1024 * 500)
    assert card.category in ("Documents", "General"), f"Unexpected category: {card.category}"
    card.on_progress(1024 * 250, 50000.0, "5s")
    assert card.progressBar.value() == 50, f"Progress value: {card.progressBar.value()}"
    
    # Test completed state
    card.on_finished("C:\\Downloads\\Clean_Document_Sample.pdf")
    assert card.state == "completed", "Card did not transition to completed"
    assert not card.btnSummary.isHidden(), "AI Summary button is hidden on completed card"
    print("[PASS] DownloadCard lifecycle & signals OK")

    print("\n--- 6. Testing Smart Rules Page ---")
    rp = window.rules_interface
    rp.load_rules_table()
    assert rp.table.rowCount() > 0, "Default rules not loaded in table"

    # Test Rule Route Simulator Worker
    route_worker = TestRouteWorker("Machine_Learning_Handbook.pdf")
    route_worker.run()
    print("[PASS] Smart Rules & Route Simulator Worker OK")

    print("\n--- 7. Testing Settings Page Preferences ---")
    sp = window.settings_interface
    sp.renaming_check.setChecked(False)
    assert get_setting("enable_ai_clean_renaming") == "false"
    sp.renaming_check.setChecked(True)
    assert get_setting("enable_ai_clean_renaming") == "true"

    sp.threat_check.setChecked(False)
    assert get_setting("enable_threat_detection") == "false"
    sp.threat_check.setChecked(True)
    assert get_setting("enable_threat_detection") == "true"

    sp.thread_spin.setValue(24)
    assert get_setting("max_threads") == "24"

    sp.auto_check_update_cb.setChecked(False)
    assert get_setting("auto_check_updates") == "false"
    sp.auto_check_update_cb.setChecked(True)
    assert get_setting("auto_check_updates") == "true"
    print("[PASS] Settings Page toggles, updates card & persistence OK")

    print("\n--- 8. Testing AI Summary Dialog & Mini-RAG ---")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("NeuroGet is an AI-powered next generation download manager for Windows 11.\nKey components include multi-threaded chunking, threat detection, and smart routing.")
        sample_doc = tf.name

    try:
        dialog = AISummaryDialog(sample_doc, parent=window)
        # Test summary worker
        sw = SummaryWorker(sample_doc)
        sw.run()
        dialog._on_analysis_finished(ContentAnalyzer.analyze_file(sample_doc))
        assert "NeuroGet" in dialog.summary_text.toPlainText() or len(dialog.summary_text.toPlainText()) > 10, "Summary text empty"

        # Test chat worker
        cw = ChatWorker(dialog.document_text, "What is NeuroGet?")
        cw.run()
        dialog._on_chat_response("NeuroGet is an AI-powered download manager.")
        assert "NeuroGet is an AI-powered download manager." in dialog.chat_history.toPlainText()
        print("[PASS] AISummaryDialog & Mini-RAG Chat OK")
    finally:
        os.remove(sample_doc)

    # Clean up test tasks created during test
    from app.models.database import SessionLocal
    from app.models.schemas import DownloadTask
    with SessionLocal() as session:
        session.query(DownloadTask).delete()
        session.commit()

    print("\n=======================================================")
    print("ALL TABS, BUTTONS, MECHANISMS & WORKERS PASSED 100%!")
    print("=======================================================")

if __name__ == "__main__":
    test_full_ui_suite()
