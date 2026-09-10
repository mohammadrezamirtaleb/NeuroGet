import re
import requests
from PyQt5.QtCore import QThread, pyqtSignal

from app.common.version import (
    __version__, APP_NAME, GITHUB_RELEASES_API, GITHUB_ALL_RELEASES_API, GITHUB_REPO_URL
)

class UpdateService:
    """Handles querying GitHub Releases for application updates, version comparison,

    and extracting changelogs and setup binaries.
    """

    @staticmethod
    def parse_version_tuple(ver_str: str) -> tuple:
        """Parses a version string like 'v1.0.1' or '1.2.0-beta' into a comparable integer tuple.

        Example: 'v1.0.1' -> (1, 0, 1)
        """
        if not ver_str:
            return (0, 0, 0)
        
        # Strip leading 'v' or 'V' and whitespaces
        cleaned = re.sub(r'^[vV]', '', ver_str.strip())
        # Extract the numeric part before any pre-release suffix like '-beta'
        main_part = cleaned.split('-')[0].split('+')[0]
        
        digits = []
        for segment in main_part.split('.'):
            # Extract numbers from segment
            num_match = re.search(r'\d+', segment)
            if num_match:
                digits.append(int(num_match.group()))
            else:
                digits.append(0)
                
        while len(digits) < 3:
            digits.append(0)
            
        return tuple(digits)

    @classmethod
    def is_newer(cls, remote_ver: str, local_ver: str = None) -> bool:
        """Returns True if remote_ver is strictly greater than local_ver."""
        if local_ver is None:
            local_ver = __version__
        
        remote_tuple = cls.parse_version_tuple(remote_ver)
        local_tuple = cls.parse_version_tuple(local_ver)
        
        return remote_tuple > local_tuple

    @classmethod
    def check_for_updates(cls, current_version: str = None, timeout: int = 6) -> dict:
        """Queries the GitHub Releases API for latest releases.

        Returns a detailed dictionary with update status, changelog, and setup assets.
        """
        if current_version is None:
            current_version = __version__

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"{APP_NAME}-Desktop-Updater/{current_version}"
        }

        try:
            response = requests.get(GITHUB_RELEASES_API, headers=headers, timeout=timeout)
            
            # If 404 (e.g. no release marked latest yet), try the list endpoint
            if response.status_code == 404:
                response = requests.get(GITHUB_ALL_RELEASES_API, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    releases = response.json()
                    if releases and isinstance(releases, list):
                        data = releases[0]
                    else:
                        return {"success": False, "error": "No releases found on GitHub."}
                else:
                    return {"success": False, "error": f"GitHub API error (status {response.status_code})"}
            elif response.status_code == 200:
                data = response.json()
            else:
                return {"success": False, "error": f"GitHub API error (status {response.status_code})"}

            tag_name = data.get("tag_name", "")
            release_name = data.get("name") or tag_name or "New Release"
            changelog_body = data.get("body", "").strip()
            html_url = data.get("html_url", GITHUB_REPO_URL)
            published_at = data.get("published_at", "")

            # Scan assets for installer/setup binary
            assets = data.get("assets", [])
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
                        # Highest priority match
                        break

            if exe_asset:
                download_url = exe_asset.get("browser_download_url", html_url)
                asset_name = exe_asset.get("name", "NeuroGet_Setup.exe")
                asset_size = exe_asset.get("size", 0)
            elif assets:
                first_asset = assets[0]
                download_url = first_asset.get("browser_download_url", html_url)
                asset_name = first_asset.get("name", "")
                asset_size = first_asset.get("size", 0)

            has_update = cls.is_newer(tag_name, current_version)

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

    def __init__(self, current_version=None, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        result = UpdateService.check_for_updates(current_version=self.current_version)
        if result.get("success"):
            self.finished_check.emit(result)
        else:
            self.failed_check.emit(result.get("error", "Unknown update error"))
