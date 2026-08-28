from urllib.parse import urlparse

class PasswordFinder:
    @staticmethod
    def get_probable_passwords(url):
        """
        Intelligently guesses extraction passwords based on the download URL.
        Many download sites (especially in certain regions) use their domain name as the archive password.
        """
        parsed = urlparse(url)
        host = parsed.netloc
        if not host:
            return []
            
        # Remove ports if any
        host = host.split(':')[0]
        
        passwords = []
        
        # If it's a subdomain (e.g. dl2.soft98.ir), the password is usually the root domain
        parts = host.split('.')
        
        # Heuristic 1: The exact host
        passwords.append(host)
        
        # Heuristic 2 & 3: Root domain and www. root domain
        if len(parts) >= 2:
            root_domain = ".".join(parts[-2:])
            if root_domain not in passwords:
                passwords.append(root_domain)
            
            www_domain = f"www.{root_domain}"
            if www_domain not in passwords:
                passwords.append(www_domain)
                
        # Heuristic 4: Removing 'www.' if the host started with it
        if host.startswith('www.'):
            stripped = host[4:]
            if stripped not in passwords:
                passwords.append(stripped)
                
        # Return unique passwords
        seen = set()
        return [x for x in passwords if not (x in seen or seen.add(x))]
