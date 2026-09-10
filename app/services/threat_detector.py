import os
import re
import urllib.parse

class ThreatDetector:
    """Detects suspicious files, double extensions, clickbait payloads, and disguised malware."""

    SUSPICIOUS_EXECUTABLES = {'.exe', '.msi', '.bat', '.cmd', '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh', '.scr', '.pif', '.hta'}
    MEDIA_KEYWORDS = {'1080p', '720p', '4k', '2160p', 'bluray', 'webrip', 'web-dl', 'x264', 'x265', 'hevc', 'movie', 'season', 'episode'}
    GAME_KEYWORDS = {'repack', 'crack', 'fitgirl', 'dodi', 'codex', 'skidrow', 'game', 'full-game'}

    @classmethod
    def analyze_download(cls, filename, url="", file_size=0):
        reasons = []
        level = "safe"

        fn_lower = filename.lower()
        parts = fn_lower.split('.')
        ext = f".{parts[-1]}" if len(parts) > 1 else ""

        # 1. Double Extension Detection (e.g. video.mp4.exe or doc.pdf.vbs)
        if len(parts) >= 3:
            second_last = f".{parts[-2]}"
            if ext in cls.SUSPICIOUS_EXECUTABLES and second_last in {'.pdf', '.docx', '.doc', '.jpg', '.png', '.mp4', '.mkv', '.zip', '.rar', '.txt'}:
                level = "danger"
                reasons.append(f"Double extension detected ({second_last}{ext}). File disguises as '{second_last}' but is actually executable.")

        # 2. Fake Movie / Clickbait Executable Detection
        # e.g. "Interstellar.2014.1080p.exe" or size < 15MB for a "1080p movie"
        has_media_kw = any(kw in fn_lower for kw in cls.MEDIA_KEYWORDS)
        if ext in cls.SUSPICIOUS_EXECUTABLES and has_media_kw:
            level = "danger"
            reasons.append("Executable file disguised with media/movie keywords. High probability of adware/malware.")

        if has_media_kw and 0 < file_size < 15 * 1024 * 1024 and ext in cls.SUSPICIOUS_EXECUTABLES:
            level = "danger"
            reasons.append("File size is suspiciously small (< 15MB) for a high-definition video executable.")

        # 3. Fake Game Setup (e.g. 500KB exe for a modern repack)
        has_game_kw = any(kw in fn_lower for kw in cls.GAME_KEYWORDS)
        if has_game_kw and 0 < file_size < 2 * 1024 * 1024 and ext in cls.SUSPICIOUS_EXECUTABLES:
            level = "warning"
            reasons.append("Installer size is under 2MB for a full game repack; possible dropper or downloader stub.")

        # 4. Script Execution Files
        if ext in {'.vbs', '.vbe', '.hta', '.scr', '.pif', '.wsf'}:
            if level != "danger":
                level = "warning"
            reasons.append(f"Script/ScreenSaver payload ({ext}) downloaded from internet.")

        # 5. URL Phishing / IP host
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.split(':')[0]
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
            # Bare IP address host
            if ext in cls.SUSPICIOUS_EXECUTABLES:
                if level != "danger":
                    level = "warning"
                reasons.append("Executable downloaded directly from a raw IP address without domain certificate.")

        return {
            "level": level,
            "reasons": reasons,
            "is_safe": level == "safe"
        }
