import re
import os
import zipfile
import tarfile
import shutil
import subprocess
import requests
from urllib.parse import urlparse

class PasswordFinder:
    """Intelligently discovers archive extraction passwords from URLs, filenames,

    CDN maps, deep web page scraping, and provides automatic archive extraction.
    """

    CDN_MAP = {
        'pgupgame.com': ['www.par30games.net', 'par30games.net'],
        'soft98.ir': ['soft98.ir'],
        'yasdl.com': ['www.yasdl.com', 'yasdl.com'],
        'downloadha.com': ['www.downloadha.com', 'downloadha.com'],
        'p30download': ['www.p30download.com', 'www.p30download.ir'],
        'sarzamindownload': ['www.sarzamindownload.com'],
        'p30day': ['www.p30day.com', 'p30day.com'],
        'vgdl.ir': ['vgdl.ir', 'www.vgdl.ir'],
        'download.ir': ['www.download.ir', 'download.ir'],
        'farsroid.com': ['www.farsroid.com', 'farsroid.com'],
        'fitgirl-repacks': ['fitgirl-repacks.site', '1337x.to'],
        'dodi-repacks': ['dodi-repacks.site']
    }

    @classmethod
    def get_probable_passwords(cls, url, filename="", referrer_url=None):
        passwords = []

        # 1. Heuristic: Extract domain patterns from the filename
        if filename:
            domain_regex = r'(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}'
            matches = re.findall(domain_regex, filename, re.IGNORECASE)
            ignore_exts = {'zip', 'rar', '7z', 'tar', 'gz', 'exe', 'msi', 'apk', 'mp4', 'mkv', 'mp3', 'iso', 'part1', 'part2', 'part3', 'part4', 'part5', 'bin', '001', '002'}

            for match in matches:
                match_lower = match.lower()
                ext = match_lower.split('.')[-1]
                if ext not in ignore_exts:
                    passwords.append(match_lower)
                    if not match_lower.startswith('www.'):
                        passwords.append(f"www.{match_lower}")

        # 2. Parse URL & CDN Mapping
        parsed = urlparse(url)
        host = parsed.netloc
        if host:
            host = host.split(':')[0].lower()
            for cdn, source_passwords in cls.CDN_MAP.items():
                if cdn in host:
                    passwords.extend(source_passwords)

            parts = host.split('.')
            if host not in passwords:
                passwords.append(host)

            if len(parts) >= 2:
                root_domain = ".".join(parts[-2:])
                if root_domain not in passwords:
                    passwords.append(root_domain)

                www_domain = f"www.{root_domain}"
                if www_domain not in passwords:
                    passwords.append(www_domain)

            if host.startswith('www.'):
                stripped = host[4:]
                if stripped not in passwords:
                    passwords.append(stripped)

        # 3. Deep Web Page Scraping (if referrer is given or webpage URL)
        url_path = (parsed.path or "").lower()
        is_archive_url = bool(re.search(r'\.(?:zip|rar|7z|tar|gz|bz2|xz|tgz|7z\.\d+|part\d+\.rar)$', url_path, re.I))
        page_to_scrape = referrer_url or (None if is_archive_url else url)
        if page_to_scrape:
            page_pwds = cls.scrape_password_from_webpage(page_to_scrape)
            passwords.extend(page_pwds)

        # Return unique passwords while preserving order
        seen = set()
        unique_passwords = []
        for pwd in passwords:
            if pwd and pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)

        return unique_passwords

    @classmethod
    def scrape_password_from_webpage(cls, webpage_url):
        """Scrapes web page HTML for password patterns (e.g. 'رمز فایل: www.soft98.ir')."""
        found = []
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            with requests.get(webpage_url, headers=headers, stream=True, timeout=3) as res:
                if res.status_code == 200:
                    content_type = res.headers.get("Content-Type", "").lower()
                    if "text/html" not in content_type:
                        return []

                    raw_chunk = bytearray()
                    for chunk in res.iter_content(chunk_size=8192):
                        raw_chunk.extend(chunk)
                        if len(raw_chunk) >= 65536:
                            raw_chunk = raw_chunk[:65536]
                            break

                    encoding = res.encoding or "utf-8"
                    html = raw_chunk.decode(encoding, errors="replace")

                    # Look for common Persian and English password indicators
                    patterns = [
                        r'(?:رمز\s*فایل|پسورد|رمز|Password|Pass)\s*[:：\-]\s*([^\s<>"\'&]+)',
                        r'class=[\'"][^\'"]*pass[^\'"]*[\'"][^>]*>([^<]+)<',
                    ]
                    for p in patterns:
                        matches = re.findall(p, html, re.IGNORECASE)
                        for m in matches:
                            cleaned = m.strip().strip(':：- ')
                            if cleaned and len(cleaned) < 50 and not cleaned.startswith(('http', 'www.' + 'google')):
                                found.append(cleaned)
        except Exception:
            pass
        return found

    # --- Archive Auto-Extraction Engine ---
    @classmethod
    def extract_archive(cls, archive_path, candidate_passwords=None, output_dir=None, is_cancelled=None):
        """Extracts .zip, .tar, .gz (and .rar/.7z if tools/libs available) safely with path traversal protection."""
        if not os.path.exists(archive_path):
            return {"success": False, "message": "Archive file not found."}

        if not output_dir:
            base_dir = os.path.dirname(archive_path)
            folder_name = os.path.splitext(os.path.basename(archive_path))[0]
            output_dir = os.path.join(base_dir, folder_name)

        real_out = os.path.realpath(os.path.abspath(output_dir))
        os.makedirs(real_out, exist_ok=True)
        passwords_to_try = [None, ""] + (candidate_passwords or [])
        ext = os.path.splitext(archive_path)[1].lower()

        # 1. ZIP Archives
        if ext == '.zip':
            for pwd in passwords_to_try:
                if is_cancelled and is_cancelled():
                    return {"success": False, "message": "Extraction cancelled."}

                try:
                    pwd_bytes = pwd.encode('utf-8') if pwd else None
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        # Zip Slip Protection: Validate all member paths before extracting
                        for member in zf.infolist():
                            member_target = os.path.realpath(os.path.join(real_out, member.filename))
                            try:
                                common = os.path.commonpath([real_out, member_target])
                            except ValueError:
                                return {"success": False, "message": f"Security alert: Zip Slip directory traversal blocked ({member.filename})"}
                            if common != real_out:
                                return {"success": False, "message": f"Security alert: Zip Slip directory traversal blocked ({member.filename})"}

                        zf.extractall(path=real_out, pwd=pwd_bytes)

                    return {
                        "success": True,
                        "password_used": pwd or "(No password)",
                        "output_dir": real_out,
                        "message": f"Successfully extracted to {real_out}"
                    }
                except zipfile.BadZipFile:
                    return {"success": False, "message": "Corrupted archive or invalid ZIP format."}
                except (RuntimeError, zipfile.error):
                    # Incorrect password or encryption mismatch, try next password
                    continue
                except Exception as e:
                    return {"success": False, "message": str(e)}

        # 2. TAR / GZ Archives
        elif ext in ('.tar', '.gz', '.tgz', '.bz2', '.xz'):
            try:
                with tarfile.open(archive_path, 'r:*') as tf:
                    # Tar Slip Protection: Validate members against directory traversal
                    safe_members = []
                    for member in tf.getmembers():
                        # Block character devices, block devices, and FIFOs
                        if member.ischr() or member.isblk() or member.isfifo():
                            continue
                        if not (member.isreg() or member.isdir() or member.issym() or member.islnk()):
                            continue

                        member_target = os.path.realpath(os.path.join(real_out, member.name))
                        try:
                            common = os.path.commonpath([real_out, member_target])
                        except ValueError:
                            return {"success": False, "message": f"Security alert: Tar Slip directory traversal blocked ({member.name})"}
                        if common != real_out:
                            return {"success": False, "message": f"Security alert: Tar Slip directory traversal blocked ({member.name})"}

                        # Validate link targets for symlinks and hardlinks
                        if member.issym() or member.islnk():
                            link_target = os.path.realpath(os.path.join(os.path.dirname(member_target), member.linkname))
                            try:
                                common_link = os.path.commonpath([real_out, link_target])
                            except ValueError:
                                return {"success": False, "message": f"Security alert: Tar Slip link traversal blocked ({member.name} -> {member.linkname})"}
                            if common_link != real_out:
                                return {"success": False, "message": f"Security alert: Tar Slip link traversal blocked ({member.name} -> {member.linkname})"}

                        safe_members.append(member)

                    if hasattr(tarfile, 'data_filter'):
                        tf.extractall(path=real_out, members=safe_members, filter='data')
                    else:
                        tf.extractall(path=real_out, members=safe_members)

                return {
                    "success": True,
                    "password_used": "(No password)",
                    "output_dir": real_out,
                    "message": f"Successfully extracted to {real_out}"
                }
            except Exception as e:
                return {"success": False, "message": str(e)}

        # 3. 7z / WinRAR CLI Fallback for .rar and .7z on Windows
        elif ext in ('.rar', '.7z'):
            seven_zip = shutil.which("7z") or (r"C:\Program Files\7-Zip\7z.exe" if os.path.exists(r"C:\Program Files\7-Zip\7z.exe") else None)
            winrar = shutil.which("winrar") or (r"C:\Program Files\WinRAR\WinRAR.exe" if os.path.exists(r"C:\Program Files\WinRAR\WinRAR.exe") else None)

            if seven_zip:
                for pwd in passwords_to_try:
                    if is_cancelled and is_cancelled():
                        return {"success": False, "message": "Extraction cancelled."}

                    cmd = [seven_zip, 'x', f'-p{pwd or ""}', '-y', f'-o{real_out}', archive_path]
                    try:
                        proc = subprocess.run(cmd, capture_output=True, timeout=60)
                        if proc.returncode == 0:
                            return {
                                "success": True,
                                "password_used": pwd or "(No password)",
                                "output_dir": real_out,
                                "message": f"Successfully extracted using 7-Zip to {real_out}"
                            }
                    except subprocess.TimeoutExpired:
                        return {"success": False, "message": "Extraction timed out after 60 seconds."}

            elif winrar:
                for pwd in passwords_to_try:
                    if is_cancelled and is_cancelled():
                        return {"success": False, "message": "Extraction cancelled."}

                    cmd = [winrar, 'x', '-ibck', '-y', f'-p{pwd or ""}', archive_path, f'{real_out}\\']
                    try:
                        proc = subprocess.run(cmd, capture_output=True, timeout=60)
                        if proc.returncode == 0:
                            return {
                                "success": True,
                                "password_used": pwd or "(No password)",
                                "output_dir": real_out,
                                "message": f"Successfully extracted using WinRAR to {real_out}"
                            }
                    except subprocess.TimeoutExpired:
                        return {"success": False, "message": "Extraction timed out after 60 seconds."}

        return {
            "success": False,
            "message": "Extraction failed. Could not unpack archive with provided passwords or format requires external archiver tool."
        }