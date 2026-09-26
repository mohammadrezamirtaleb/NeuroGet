import os
import sys
import shutil
import hashlib
import subprocess
import time
from app.common.version import UPDATE_DIR, BACKUP_DIR, APP_NAME, __version__

class UpdateInstaller:
    """Manages update integrity verification, installer launching, and file backups."""

    @staticmethod
    def ensure_directories():
        """Ensure update and backup directories exist."""
        os.makedirs(UPDATE_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)

    @staticmethod
    def compute_sha256(filepath: str) -> str:
        """Compute SHA-256 hash of a local file."""
        if not os.path.exists(filepath):
            return ""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        return sha256.hexdigest().lower()

    @classmethod
    def verify_hash(cls, filepath: str, expected_hash: str) -> bool:
        """Verify that the file matches the expected SHA-256 hash (case-insensitive)."""
        if not expected_hash:
            return True  # If no hash provided, consider valid
        actual = cls.compute_sha256(filepath)
        return actual.lower() == expected_hash.strip().lower()

    @classmethod
    def get_target_installer_path(cls, version_str: str, asset_name: str = "") -> str:
        """Get destination path for the update binary."""
        cls.ensure_directories()
        clean_ver = version_str.lstrip("vV").replace(" ", "_")
        if not asset_name:
            asset_name = f"{APP_NAME}_Setup_v{clean_ver}.exe"
        return os.path.join(UPDATE_DIR, asset_name)

    @classmethod
    def launch_installer(cls, installer_path: str, auto_exit: bool = True) -> bool:
        """Launches the downloaded installer as an independent detached process."""
        if not os.path.exists(installer_path):
            return False

        try:
            if sys.platform == "win32":
                # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP ensures the installer
                # runs independently of the parent process after it exits
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                
                subprocess.Popen(
                    [installer_path],
                    creationflags=flags,
                    close_fds=True
                )
            else:
                subprocess.Popen([installer_path], start_new_session=True)

            return True
        except Exception as e:
            # Fallback to os.startfile on Windows
            try:
                os.startfile(installer_path)
                return True
            except Exception:
                return False

    @classmethod
    def cleanup_old_updates(cls, keep_latest_file: str = ""):
        """Remove old downloaded update binaries to save disk space."""
        cls.ensure_directories()
        try:
            for item in os.listdir(UPDATE_DIR):
                full_path = os.path.join(UPDATE_DIR, item)
                if os.path.isfile(full_path) and full_path != keep_latest_file:
                    try:
                        os.remove(full_path)
                    except Exception:
                        pass
        except Exception:
            pass
