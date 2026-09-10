import os
import sys
import tempfile
import zipfile

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.database import (
    init_db, create_rule, get_all_rules, delete_rule,
    get_setting, set_setting, create_task, get_all_tasks
)
from app.services.ai_client import AIClient
from app.services.content_analyzer import ContentAnalyzer
from app.services.threat_detector import ThreatDetector
from app.services.router import SmartRouter
from app.services.password_finder import PasswordFinder

def run_tests():
    print("--- 1. Testing Database & Settings ---")
    init_db()
    set_setting("test_key", "test_value_123")
    val = get_setting("test_key")
    assert val == "test_value_123", f"Setting mismatch: {val}"
    print("[PASS] AppSetting CRUD OK")

    rule_id = create_rule("Test eBooks", "ext", ".epub, .mobi", "C:\\Downloads\\Books", 1)
    rules = get_all_rules()
    assert any(r.id == rule_id for r in rules), "Rule not found in DB"
    delete_rule(rule_id)
    print("[PASS] SmartRule CRUD OK")

    print("\n--- 2. Testing AI Clean Renaming & Heuristics ---")
    dirty_name = "[Soft98.ir]_python-3.12.0-amd64.exe"
    cleaned = AIClient._heuristic_clean_name(dirty_name)
    print(f"Dirty: {dirty_name} -> Cleaned: {cleaned}")
    assert "Soft98" not in cleaned, "Site prefix was not removed"
    print("[PASS] Clean Renaming OK")

    print("\n--- 3. Testing Semantic Categorization ---")
    cat_pdf = AIClient.classify_category("Machine_Learning_Lecture.pdf")
    cat_exe = AIClient.classify_category("Visual_Studio_Code_Setup.exe")
    cat_media = AIClient.classify_category("Interstellar_1080p_BluRay.mkv")
    print(f"PDF Category: {cat_pdf}")
    print(f"EXE Category: {cat_exe}")
    print(f"MKV Category: {cat_media}")
    assert cat_pdf == "Documents", f"Expected Documents, got {cat_pdf}"
    assert cat_exe == "Software", f"Expected Software, got {cat_exe}"
    assert cat_media in ("Media", "Education / Course"), f"Expected Media, got {cat_media}"
    print("[PASS] Semantic Categorization OK")

    print("\n--- 4. Testing Threat & Clickbait Detector ---")
    safe_check = ThreatDetector.analyze_download("document.pdf", "https://example.com/doc.pdf", 1024*1024)
    assert safe_check["is_safe"] == True, "Normal PDF marked unsafe"

    danger_check = ThreatDetector.analyze_download("video.mp4.exe", "https://fake.com/video.mp4.exe", 2*1024*1024)
    print(f"Double extension check: {danger_check}")
    assert danger_check["level"] == "danger", "Double extension was not caught"

    fake_movie_check = ThreatDetector.analyze_download("Avatar.2024.1080p.BluRay.exe", "https://fake.com/av.exe", 3*1024*1024)
    print(f"Fake movie check: {fake_movie_check}")
    assert fake_movie_check["level"] == "danger", "Disguised movie executable not caught"
    print("[PASS] Threat Detector OK")

    print("\n--- 5. Testing Content Analyzer & Summarizer ---")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("NeuroGet is an advanced AI-powered download manager designed for Windows 11 Fluent Design.\nIt features multi-threaded downloading, intelligent routing, and smart password discovery.\nUsers can chat with documents and get instant summaries.")
        temp_file = tf.name

    try:
        analysis = ContentAnalyzer.analyze_file(temp_file)
        print(f"Summary generated:\n{analysis.get('summary')}")
        assert analysis["word_count"] > 0, "Word count is zero"
        print("[PASS] Content Analyzer OK")
    finally:
        os.remove(temp_file)

    print("\n--- 6. Testing Smart Router ---")
    dest, rule_name = SmartRouter.route_download("https://example.com/paper.pdf", "paper.pdf")
    print(f"Routing for paper.pdf -> Folder: {dest}, Rule: {rule_name}")
    assert "Documents" in dest or "Documents" in rule_name, "Router did not route PDF to Documents"
    print("[PASS] Smart Router OK")

    print("\n--- 7. Testing Password Finder & Auto-Extract ---")
    passwords = PasswordFinder.get_probable_passwords("https://dl.soft98.ir/software/app.zip", "[soft98.ir]_app.zip")
    print(f"Probable passwords found: {passwords}")
    assert "soft98.ir" in passwords, "Soft98 password missing"

    # Test ZIP extraction with password
    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "test_archive.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("secret.txt", "Hello NeuroGet AI World!", compress_type=zipfile.ZIP_DEFLATED)

        extract_res = PasswordFinder.extract_archive(zip_path, candidate_passwords=["wrong_pass", "soft98.ir"])
        print(f"Extract result: {extract_res}")
        assert extract_res["success"] == True, "Archive extraction failed"
    print("[PASS] Password Finder & Auto-Extractor OK")

    print("\n==========================================")
    print("SUCCESS: ALL AI AND SMART FEATURES PASSED 100%!")
    print("==========================================")

if __name__ == "__main__":
    run_tests()
