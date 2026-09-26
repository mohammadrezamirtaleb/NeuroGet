"""
NeuroGet Version and Repository Configuration
"""
import os

APP_NAME = "NeuroGet"
__version__ = "1.2.0"

GITHUB_OWNER = "mohammadrezamirtaleb"
GITHUB_REPO = "NeuroGet"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_ALL_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"

# Update infrastructure directories
_APP_DATA = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "NeuroGet")
UPDATE_DIR = os.path.join(_APP_DATA, "updates")
BACKUP_DIR = os.path.join(_APP_DATA, "backup")
UPDATE_CHANNELS = ["stable", "beta"]

