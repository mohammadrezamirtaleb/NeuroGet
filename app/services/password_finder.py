import re
from urllib.parse import urlparse

class PasswordFinder:
    # A mapping of common CDNs or download servers to their actual website passwords
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
        'farsroid.com': ['www.farsroid.com', 'farsroid.com']
    }

    @staticmethod
    def get_probable_passwords(url, filename=""):
        passwords = []
        
        # 1. Heuristic: Extract domain patterns from the filename
        # Many sites name their files like [www.site.com]_file.zip or site.ir_file.rar
        if filename:
            # Look for domain-like strings in the filename
            domain_regex = r'(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}'
            matches = re.findall(domain_regex, filename, re.IGNORECASE)
            
            # Common file extensions that might be caught as domains by mistake
            ignore_exts = {'zip', 'rar', '7z', 'tar', 'gz', 'exe', 'msi', 'apk', 'mp4', 'mkv', 'mp3', 'iso', 'part1', 'part2', 'part3', 'part4', 'part5', 'bin', '001', '002'}
            
            for match in matches:
                match_lower = match.lower()
                ext = match_lower.split('.')[-1]
                if ext not in ignore_exts:
                    passwords.append(match_lower)
                    if not match_lower.startswith('www.'):
                        passwords.append(f"www.{match_lower}")

        # Parse URL
        parsed = urlparse(url)
        host = parsed.netloc
        if host:
            host = host.split(':')[0].lower()
            
            # 2. Heuristic: Check CDN mapping
            for cdn, source_passwords in PasswordFinder.CDN_MAP.items():
                if cdn in host:
                    passwords.extend(source_passwords)
            
            # 3. Heuristic: The exact host and root domain
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
                    
        # Return unique passwords while preserving order (priority)
        seen = set()
        unique_passwords = []
        for pwd in passwords:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)
                
        return unique_passwords