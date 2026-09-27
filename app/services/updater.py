import os
import re
import time
import requests
from PyQt5.QtCore import QThread, pyqtSignal

from app.common.version import (
    __version__, APP_NAME, GITHUB_RELEASES_API, GITHUB_ALL_RELEASES_API, GITHUB_REPO_URL
)
from app.models.database import get_setting
from app.services.update_installer import UpdateInstaller


class UpdateService:
    """Handles querying GitHub Releases for application updates, version comparison,
    checksum extraction, and update channels (Stable/Beta).
    """

    @staticmethod
    def parse_version_tuple(ver_str: str) -> tuple:
        """Parses a version string like 'v1.0.1' or '1.2.0-beta.1' into a comparable tuple.
        Returns ((major, minor, patch), prerelease_type, prerelease_num).
        Stable releases have higher precedence than pre-releases of the same major.minor.patch.
        """
        if not ver_str:
            return ((0, 0, 0), 10, 0)  # 10 indicates final/stable release

        cleaned = re.sub(r'^[vV]', '', ver_str.strip())
        
        # Check for pre-release tag
        prerelease_type = 10  # 10 = stable/final
        prerelease_num = 0

        if '-' in cleaned:
            parts = cleaned.split('-', 1)
            main_ver = parts[0]
            tag = parts[1].lower()
            if 'alpha' in tag:
                prerelease_type = 1
            elif 'beta' in tag:
                prerelease_type = 2
            elif 'rc' in tag:
                prerelease_type = 3
            else:
                prerelease_type = 0
            
            num_match = re.search(r'\d+', tag)
            if num_match:
                prerelease_num = int(num_match.group())
        else:
            main_ver = cleaned.split('+')[0]

        digits = []
        for segment in main_ver.split('.'):
            num_match = re.search(r'\d+', segment)
            if num_match:
                digits.append(int(num_match.group()))
            else:
                digits.append(0)

        while len(digits) < 3:
            digits.append(0)

        return (tuple(digits[:3]), prerelease_type, prerelease_num)

    @classmethod
    def is_newer(cls, remote_ver: str, local_ver: str = None) -> bool:
        """Returns True if remote_ver is strictly greater than local_ver."""
        if local_ver is None:
            local_ver = __version__

        remote_parsed = cls.parse_version_tuple(remote_ver)
        local_parsed = cls.parse_version_tuple(local_ver)

        return remote_parsed > local_parsed

    @classmethod
    def extract_expected_checksum(cls, release_data: dict, asset_name: str) -> str:
        """Attempts to find SHA-256 checksum from release body or checksum asset."""
        body = release_data.get("body", "")
        
        # 1. Search release body for sha256 hashes
        # Look for pattern: <asset_name> ... <64-hex> or SHA256: <64-hex>
        if asset_name:
            pattern = re.compile(re.escape(asset_name) + r'[\s\S]*?([0-9a-fA-F]{64})', re.IGNORECASE)
            match = pattern.search(body)
            if match:
                return match.group(1).lower()

        # Look for general SHA256 in body
        sha_match = re.search(r'(?:sha256|sha-256|hash)\s*[:=]\s*`?([0-9a-fA-F]{64})`?', body, re.IGNORECASE)
        if sha_match:
            return sha_match.group(1).lower()

        # 2. Check if a checksums.txt asset is attached
        for asset in release_data.get("assets", []):
            name = asset.get("name", "").lower()
            if "checksum" in name or name.endswith(".sha256") or name.endswith(".sha256.txt"):
                dl_url = asset.get("browser_download_url")
                if dl_url:
                    try:
                        res = requests.get(dl_url, timeout=5)
                        if res.status_code == 200:
                            content = res.content.decode('utf-8', errors='ignore')
                            for line in content.splitlines():
                                if asset_name and asset_name.lower() in line.lower():
                                    h_match = re.search(r'([0-9a-fA-F]{64})', line)
                                    if h_match:
                                        return h_match.group(1).lower()
                                elif not asset_name:
                                    h_match = re.search(r'([0-9a-fA-F]{64})', line)
                                    if h_match:
                                        return h_match.group(1).lower()
                    except Exception:
                        pass

        return ""

    @classmethod
    def check_for_updates(cls, current_version: str = None, channel: str = None, timeout: int = 6) -> dict:
        """Queries the GitHub Releases API for latest releases matching the channel.
        Returns a detailed dictionary with update status, changelog, and setup assets.
        """
        if current_version is None:
            current_version = __version__

        if channel is None:
            channel = get_setting("update_channel", "stable").lower()

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"{APP_NAME}-Desktop-Updater/{current_version}"
        }

        try:
            target_release = None
            
            if channel == "beta":
                # For beta, fetch all releases and pick the latest one including prereleases
                response = requests.get(GITHUB_ALL_RELEASES_API, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    releases = response.json()
                    if releases and isinstance(releases, list):
                        target_release = releases[0]
                    else:
                        return {"success": False, "error": "No releases found on GitHub."}
                else:
                    return {"success": False, "error": f"GitHub API error (status {response.status_code})"}
            else:
                # For stable, fetch latest release (GitHub automatically excludes prereleases)
                response = requests.get(GITHUB_RELEASES_API, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    target_release = response.json()
                elif response.status_code == 404:
                    # Fallback to list endpoint if no official latest tag
                    response = requests.get(GITHUB_ALL_RELEASES_API, headers=headers, timeout=timeout)
                    if response.status_code == 200:
                        releases = response.json()
                        stable_releases = [r for r in releases if not r.get("prerelease", False)]
                        if stable_releases:
                            target_release = stable_releases[0]
                        elif releases:
                            target_release = releases[0]
                        else:
                            return {"success": False, "error": "No releases found on GitHub."}
                    else:
                        return {"success": False, "error": f"GitHub API error (status {response.status_code})"}
                else:
                    return {"success": False, "error": f"GitHub API error (status {response.status_code})"}

            if not target_release:
                return {"success": False, "error": "No release data found."}

            tag_name = target_release.get("tag_name", "")
            release_name = target_release.get("name") or tag_name or "New Release"
            changelog_body = target_release.get("body", "").strip()
            html_url = target_release.get("html_url", GITHUB_REPO_URL)
            published_at = target_release.get("published_at", "")
            is_prerelease = target_release.get("prerelease", False)

            # Scan assets for installer/setup binary
            assets = target_release.get("assets", [])
            download_url = html_url
            asset_name = ""
            asset_size = 0

            # Prioritize Windows Executables (.exe / .msi)
            exe_asset = None
            for a in assets:
                name = a.get("name", "").lower()
                if name.endswith(".exe") or name.endswith(".msi"):
                    exe_asset = a
                    if "setup" in name:
                        break

            if exe_asset:
                download_url = exe_asset.get("browser_download_url", html_url)
                asset_name = exe_asset.get("name", f"{APP_NAME}_Setup.exe")
                asset_size = exe_asset.get("size", 0)
            elif assets:
                first_asset = assets[0]
                download_url = first_asset.get("browser_download_url", html_url)
                asset_name = first_asset.get("name", "")
                asset_size = first_asset.get("size", 0)

            has_update = cls.is_newer(tag_name, current_version)
            expected_hash = cls.extract_expected_checksum(target_release, asset_name)

            return {
                "success": True,
                "has_update": has_update,
                "current_version": current_version,
                "latest_version": tag_name.lstrip("vV"),
                "tag_name": tag_name,
                "release_name": release_name,
                "changelog": changelog_body,
                "download_url": download_url,
                "asset_name": asset_name,
                "asset_size": asset_size,
                "expected_hash": expected_hash,
                "is_prerelease": is_prerelease,
                "channel": channel,
                "html_url": html_url,
                "published_at": published_at
            }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Connection timed out while checking for updates."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "No internet connection to check for updates."}
        except Exception as e:
            return {"success": False, "error": str(e)}


class UpdateCheckWorker(QThread):
    """Background worker to check for updates asynchronously without freezing the UI."""
    finished_check = pyqtSignal(dict)
    failed_check = pyqtSignal(str)

    def __init__(self, current_version=None, channel=None, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.channel = channel

    def run(self):
        result = UpdateService.check_for_updates(
            current_version=self.current_version,
            channel=self.channel
        )
        if result.get("success"):
            self.finished_check.emit(result)
        else:
            self.failed_check.emit(result.get("error", "Unknown update error"))


class UpdateDownloadWorker(QThread):
    """Downloads the update installer in the background with progress reporting and checksum validation."""
    progress = pyqtSignal(int, int, float, str)  # (downloaded_bytes, total_bytes, speed_Bps, eta_str)
    download_finished = pyqtSignal(str)          # target filepath
    download_failed = pyqtSignal(str)            # error message

    def __init__(self, download_url: str, version_str: str, asset_name: str = "", expected_hash: str = "", parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.version_str = version_str
        self.asset_name = asset_name
        self.expected_hash = expected_hash
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if not self.download_url or not self.download_url.startswith("http"):
            self.download_failed.emit("Invalid update download URL.")
            return

        target_path = UpdateInstaller.get_target_installer_path(self.version_str, self.asset_name)
        temp_path = target_path + ".download"

        try:
            UpdateInstaller.cleanup_old_updates(keep_latest_file=target_path)
            
            headers = {
                "User-Agent": f"{APP_NAME}-Desktop-Updater/{__version__}"
            }

            response = requests.get(self.download_url, headers=headers, stream=True, timeout=(10, 30))
            if response.status_code != 200:
                self.download_failed.emit(f"Server returned HTTP {response.status_code}")
                return

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 65536  # 64 KB chunks
            start_time = time.time()
            last_emit_time = start_time
            bytes_since_last = 0

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if self._is_cancelled:
                        response.close()
                        if os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except Exception:
                                pass
                        self.download_failed.emit("Update download cancelled.")
                        return

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        bytes_since_last += len(chunk)

                        now = time.time()
                        if now - last_emit_time >= 0.2:
                            speed = bytes_since_last / (now - last_emit_time) if (now - last_emit_time) > 0 else 0
                            remaining = total_size - downloaded
                            eta_secs = int(remaining / speed) if speed > 0 and remaining > 0 else 0
                            
                            if eta_secs >= 3600:
                                eta_str = f"{eta_secs // 3600}h {(eta_secs % 3600) // 60}m"
                            elif eta_secs >= 60:
                                eta_str = f"{eta_secs // 60}m {eta_secs % 60}s"
                            elif eta_secs > 0:
                                eta_str = f"{eta_secs}s"
                            else:
                                eta_str = "--:--"

                            self.progress.emit(downloaded, total_size, speed, eta_str)
                            last_emit_time = now
                            bytes_since_last = 0

            # Atomic rename from .download to final .exe (atomic on Windows/POSIX)
            os.replace(temp_path, target_path)

            # Check integrity if expected hash is present
            if self.expected_hash:
                if not UpdateInstaller.verify_hash(target_path, self.expected_hash):
                    try:
                        os.remove(target_path)
                    except Exception:
                        pass
                    self.download_failed.emit("SHA-256 integrity verification failed. File may be corrupted.")
                    return

            self.download_finished.emit(target_path)

        except requests.exceptions.Timeout:
            self.download_failed.emit("Connection timed out while downloading the update.")
        except requests.exceptions.ConnectionError:
            self.download_failed.emit("Network connection interrupted during update download.")
        except Exception as e:
            self.download_failed.emit(f"Download failed: {str(e)}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
