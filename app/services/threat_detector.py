import re
import urllib.parse

class ThreatDetector:
    """Detects suspicious files, double extensions, clickbait payloads, and disguised malware."""

    SUSPICIOUS_EXECUTABLES = {
        '.exe', '.msi', '.bat', '.cmd', '.vbs', '.vbe', '.js', '.jse',
        '.wsf', '.wsh', '.scr', '.pif', '.hta', '.ps1', '.psm1',
        '.lnk', '.iso', '.img', '.chm', '.cpl', '.reg', '.jar'
    }
    DECOY_EXTENSIONS = {'.pdf', '.docx', '.doc', '.jpg', '.png', '.mp4', '.mkv', '.zip', '.rar', '.txt', '.xlsx', '.pptx'}
    MEDIA_KEYWORDS = {'1080p', '720p', '4k', '2160p', 'bluray', 'webrip', 'web-dl', 'x264', 'x265', 'hevc', 'movie', 'season', 'episode'}
    GAME_KEYWORDS = {'repack', 'crack', 'fitgirl', 'dodi', 'codex', 'skidrow', 'game', 'full-game'}

    @classmethod
    def analyze_download(cls, filename, url="", file_size=0):
        reasons = []
        level = "safe"

        # Sanitize trailing dots, spaces and null bytes that Windows silently strips
        fn_clean = filename.rstrip('. \t\x00')
        fn_lower = fn_clean.lower()

        # Detect Unicode Right-to-Left Override (RTLO) attack
        if '\u202e' in filename or '\u200f' in filename:
            level = "danger"
            reasons.append("Unicode Right-to-Left Override character detected — filename visually reversed to hide true extension.")

        parts = fn_lower.split('.')
        ext = f".{parts[-1]}" if len(parts) > 1 else ""

        # 1. Double Extension Detection (e.g. video.mp4.exe or doc.pdf.vbs)
        if len(parts) >= 3:
            # Check ALL intermediate extensions for decoy patterns
            for i in range(1, len(parts) - 1):
                intermediate = f".{parts[i]}"
                if ext in cls.SUSPICIOUS_EXECUTABLES and intermediate in cls.DECOY_EXTENSIONS:
                    level = "danger"
                    reasons.append(f"Double extension detected ({intermediate}{ext}). File disguises as '{intermediate}' but is actually executable.")
                    break

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
        if ext in {'.vbs', '.vbe', '.hta', '.scr', '.pif', '.wsf', '.ps1', '.lnk', '.chm'}:
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
