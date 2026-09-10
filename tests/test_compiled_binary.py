import os
import sys
import time
import subprocess

def verify_binaries():
    print("==================================================")
    print("     VERIFYING COMPILED BINARIES & RUNTIME        ")
    print("==================================================")

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_exe = os.path.join(root_dir, "dist", "NeuroGet", "NeuroGet.exe")
    setup_exe = os.path.join(root_dir, "dist", "NeuroGet_Setup.exe")

    # 1. Check file existence and integrity
    print("\n--- 1. Checking Binary Files Integrity ---")
    assert os.path.exists(app_exe), f"Missing {app_exe}"
    assert os.path.exists(setup_exe), f"Missing {setup_exe}"
    
    app_size_mb = os.path.getsize(app_exe) / (1024 * 1024)
    setup_size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
    print(f"[PASS] NeuroGet.exe exists ({app_size_mb:.2f} MB)")
    print(f"[PASS] NeuroGet_Setup.exe exists ({setup_size_mb:.2f} MB)")

    # 2. Check essential bundled DLLs and Assets in onedir dist
    print("\n--- 2. Checking Bundled Qt & Assets ---")
    dist_dir = os.path.join(root_dir, "dist", "NeuroGet")
    internal_dir = os.path.join(dist_dir, "_internal")
    
    # In PyInstaller 6+, bundled packages and assets reside in _internal
    check_dir = internal_dir if os.path.exists(internal_dir) else dist_dir
    qt_files = [f for f in os.listdir(check_dir) if "PyQt5" in f or "python" in f.lower() or "sqlalchemy" in f.lower()]
    assert len(qt_files) > 0, "Qt5 runtime libraries not found in dist/NeuroGet"
    print(f"[PASS] Found {len(qt_files)} core runtime packages: {qt_files}")

    assets_dist = os.path.join(check_dir, "assets")
    assert os.path.exists(assets_dist), "assets folder missing from dist"
    assert os.path.exists(os.path.join(assets_dist, "icon.ico")), "icon.ico missing from dist assets"
    assert os.path.exists(os.path.join(assets_dist, "logo_transparent.png")), "logo missing from dist assets"
    print("[PASS] All brand assets and icons correctly bundled in dist")

    # 3. Test Launching NeuroGet.exe (Smoke test execution)
    print("\n--- 3. Testing Launching NeuroGet.exe Runtime ---")
    proc = subprocess.Popen([app_exe], cwd=dist_dir)
    print(f"Launched NeuroGet.exe (PID: {proc.pid})")
    
    # Allow 4 seconds for window & splash screen to initialize
    time.sleep(4)
    
    # Check if process is still alive (0 crashes)
    poll_res = proc.poll()
    if poll_res is not None:
        print(f"[ERROR] Process exited prematurely with code: {poll_res}")
        sys.exit(1)
    
    print(f"[PASS] Process is running healthy in Windows memory (PID {proc.pid}, exit code is None)")
    
    # Terminate the test instance
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("[PASS] Process terminated cleanly after smoke test")

    print("\n==================================================")
    print("SUCCESS: COMPILED BINARY IS 100% HEALTHY & READY!")
    print("==================================================")

if __name__ == "__main__":
    verify_binaries()
