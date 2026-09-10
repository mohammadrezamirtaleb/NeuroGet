import os
import sys
import shutil
import zipfile
import hashlib
import subprocess

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def build():
    print("==================================================")
    print("      NEUROGET PRODUCTION RELEASE BUILDER         ")
    print("==================================================")

    root_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")
    payload_zip = os.path.join(root_dir, "payload.zip")

    # 1. Clean previous build artifacts
    print("\n[1/5] Cleaning previous build artifacts...")
    for p in [dist_dir, build_dir, payload_zip]:
        if os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
    print("  Done.")

    # 2. Build NeuroGet Core Application (onedir)
    print("\n[2/5] Compiling NeuroGet core application (PyInstaller)...")
    main_py = os.path.join(root_dir, "main.py")
    icon_ico = os.path.join(root_dir, "assets", "icon.ico")
    assets_dir = os.path.join(root_dir, "assets")

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        main_py,
        "--name=NeuroGet",
        "--noconsole",
        "--onedir",
        f"--icon={icon_ico}",
        f"--add-data={assets_dir};assets",
        "--hidden-import=qfluentwidgets",
        "--hidden-import=sqlalchemy",
        "--hidden-import=sqlalchemy.dialects.sqlite",
        "--hidden-import=requests",
        "--hidden-import=urllib.parse",
        "--hidden-import=app",
        "--hidden-import=app.common",
        "--hidden-import=app.common.version",
        "--hidden-import=app.models",
        "--hidden-import=app.models.database",
        "--hidden-import=app.models.schemas",
        "--hidden-import=app.services",
        "--hidden-import=app.services.ai_client",
        "--hidden-import=app.services.ai_scanner",
        "--hidden-import=app.services.content_analyzer",
        "--hidden-import=app.services.password_finder",
        "--hidden-import=app.services.router",
        "--hidden-import=app.services.threat_detector",
        "--hidden-import=app.services.updater",
        "--hidden-import=app.controllers",
        "--hidden-import=app.controllers.download_manager",
        "--hidden-import=app.controllers.worker",
        "--hidden-import=app.views",
        "--hidden-import=app.views.splash_screen",
        "--hidden-import=app.views.pages.downloads_page",
        "--hidden-import=app.views.pages.smart_rules_page",
        "--hidden-import=app.views.pages.settings_page",
        "--hidden-import=app.views.components.download_card",
        "--hidden-import=app.views.components.ai_summary_dialog",
        "--hidden-import=app.views.components.update_dialog",
        "--clean",
        "-y"
    ]

    res = subprocess.run(pyinstaller_cmd, cwd=root_dir)
    if res.returncode != 0:
        print("[ERROR] Failed to compile NeuroGet core application!")
        sys.exit(1)

    app_folder = os.path.join(dist_dir, "NeuroGet")
    if not os.path.exists(app_folder):
        print(f"[ERROR] Output folder not found: {app_folder}")
        sys.exit(1)
    print("  NeuroGet core application compiled successfully.")

    # 3. Create payload.zip
    print("\n[3/5] Packaging core application into payload.zip...")
    total_files = 0
    with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for foldername, subfolders, filenames in os.walk(app_folder):
            for filename in filenames:
                file_path = os.path.join(foldername, filename)
                rel_path = os.path.relpath(file_path, app_folder)
                zf.write(file_path, rel_path)
                total_files += 1
    
    zip_size_mb = os.path.getsize(payload_zip) / (1024 * 1024)
    print(f"  Packaged {total_files} files into payload.zip ({zip_size_mb:.2f} MB).")

    # 4. Build Setup Wizard Installer (NeuroGet_Setup.exe)
    print("\n[4/5] Compiling Standalone Setup Wizard (NeuroGet_Setup.exe)...")
    setup_py = os.path.join(root_dir, "setup_wizard.py")

    setup_cmd = [
        sys.executable, "-m", "PyInstaller",
        setup_py,
        "--name=NeuroGet_Setup",
        "--noconsole",
        "--onefile",
        f"--icon={icon_ico}",
        f"--add-data={payload_zip};.",
        f"--add-data={assets_dir};assets",
        "--hidden-import=qfluentwidgets",
        "--hidden-import=app",
        "--hidden-import=app.common",
        "--hidden-import=app.common.version",
        "--clean",
        "-y"
    ]

    res_setup = subprocess.run(setup_cmd, cwd=root_dir)
    if res_setup.returncode != 0:
        print("[ERROR] Failed to compile Setup Wizard!")
        sys.exit(1)

    setup_exe = os.path.join(dist_dir, "NeuroGet_Setup.exe")
    if not os.path.exists(setup_exe):
        print(f"[ERROR] Output installer not found: {setup_exe}")
        sys.exit(1)

    # 5. Summary & Checksums
    print("\n[5/5] Finalizing Release Package...")
    size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
    sha256 = compute_sha256(setup_exe)

    # Clean intermediate payload.zip
    if os.path.exists(payload_zip):
        os.remove(payload_zip)

    print("\n" + "=" * 60)
    print("   BUILD SUCCESSFUL: PRODUCTION INSTALLER READY!   ")
    print("=" * 60)
    print(f"  Installer File : {setup_exe}")
    print(f"  File Size      : {size_mb:.2f} MB ({os.path.getsize(setup_exe):,} bytes)")
    print(f"  SHA-256 Digest : {sha256}")
    print("=" * 60)

if __name__ == "__main__":
    build()
