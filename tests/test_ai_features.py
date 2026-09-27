import os
import sys
import tempfile
import zipfile
import tarfile
import pytest

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


def test_database_and_settings():
    init_db()
    set_setting("test_key", "test_value_123")
    val = get_setting("test_key")
    assert val == "test_value_123", f"Setting mismatch: {val}"

    rule_id = create_rule("Test eBooks", "ext", ".epub, .mobi", "C:\\Downloads\\Books", 1)
    rules = get_all_rules()
    assert any(r.id == rule_id for r in rules), "Rule not found in DB"
    delete_rule(rule_id)


def test_ai_clean_renaming():
    dirty_name = "[Soft98.ir]_python-3.12.0-amd64.exe"
    cleaned = AIClient._heuristic_clean_name(dirty_name)
    assert "Soft98" not in cleaned, "Site prefix was not removed"


def test_semantic_categorization():
    cat_pdf = AIClient.classify_category("Machine_Learning_Lecture.pdf")
    cat_exe = AIClient.classify_category("Visual_Studio_Code_Setup.exe")
    cat_media = AIClient.classify_category("Interstellar_1080p_BluRay.mkv")
    assert cat_pdf == "Documents", f"Expected Documents, got {cat_pdf}"
    assert cat_exe == "Software", f"Expected Software, got {cat_exe}"
    assert cat_media in ("Media", "Education / Course"), f"Expected Media, got {cat_media}"


def test_threat_detector():
    safe_check = ThreatDetector.analyze_download("document.pdf", "https://example.com/doc.pdf", 1024*1024)
    assert safe_check["is_safe"] is True, "Normal PDF marked unsafe"

    danger_check = ThreatDetector.analyze_download("video.mp4.exe", "https://fake.com/video.mp4.exe", 2*1024*1024)
    assert danger_check["level"] == "danger", "Double extension was not caught"

    fake_movie_check = ThreatDetector.analyze_download("Avatar.2024.1080p.BluRay.exe", "https://fake.com/av.exe", 3*1024*1024)
    assert fake_movie_check["level"] == "danger", "Disguised movie executable not caught"


def test_content_analyzer():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("NeuroGet is an advanced AI-powered download manager designed for Windows 11 Fluent Design.\nIt features multi-threaded downloading, intelligent routing, and smart password discovery.")
        temp_file = tf.name

    try:
        analysis = ContentAnalyzer.analyze_file(temp_file)
        assert analysis["word_count"] > 0, "Word count is zero"
    finally:
        os.remove(temp_file)


def test_smart_router():
    dest, rule_name = SmartRouter.route_download("https://example.com/paper.pdf", "paper.pdf")
    assert "Documents" in dest or "Documents" in rule_name, "Router did not route PDF to Documents"


def test_password_finder_url_with_query_params():
    # Verify that query strings on archive links do not cause binary scraping false positives
    url_with_query = "https://dl.soft98.ir/software/app.zip?token=secret123&expire=99999"
    passwords = PasswordFinder.get_probable_passwords(url_with_query, "app.zip")
    assert "soft98.ir" in passwords


def test_zip_extraction_and_bad_zip_handling():
    with tempfile.TemporaryDirectory() as td:
        # Valid ZIP test
        zip_path = os.path.join(td, "test_archive.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("secret.txt", "Hello NeuroGet AI World!", compress_type=zipfile.ZIP_DEFLATED)

        extract_res = PasswordFinder.extract_archive(zip_path, candidate_passwords=["wrong_pass", "soft98.ir"])
        assert extract_res["success"] is True

        # Corrupted ZIP test (should fail immediately without loop)
        corrupted_zip = os.path.join(td, "corrupted.zip")
        with open(corrupted_zip, "wb") as f:
            f.write(b"This is not a zip file at all")

        bad_res = PasswordFinder.extract_archive(corrupted_zip, candidate_passwords=["pass1", "pass2", "pass3"])
        assert bad_res["success"] is False
        assert "Corrupted archive" in bad_res["message"] or "invalid" in bad_res["message"]


def test_zip_slip_protection():
    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "malicious.zip")
        out_dir = os.path.join(td, "extracted")
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Create a zip with path traversal member
            zf.writestr("../../evil.txt", "Malicious content")

        res = PasswordFinder.extract_archive(zip_path, output_dir=out_dir)
        assert res["success"] is False
        assert "Zip Slip" in res["message"]


def test_tar_slip_protection():
    with tempfile.TemporaryDirectory() as td:
        tar_path = os.path.join(td, "malicious.tar")
        out_dir = os.path.join(td, "extracted")

        with tarfile.open(tar_path, "w") as tf:
            ti = tarfile.TarInfo(name="../../evil_tar.txt")
            ti.size = 4
            import io
            tf.addfile(ti, io.BytesIO(b"evil"))

        res = PasswordFinder.extract_archive(tar_path, output_dir=out_dir)
        assert res["success"] is False
        assert "Tar Slip" in res["message"]
