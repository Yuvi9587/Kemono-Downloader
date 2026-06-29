import base64
import requests

class HotleaksClient:
    def __init__(self, proxies=None):
        self.base_url = "https://hotleaks.tv"
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
            'Origin': self.base_url,
            'Referer': f"{self.base_url}/"
        }

    def extract_username(self, url):
        """Extracts creator (and optional media filter) from url."""
        url = url.split('?')[0].strip('/')
        parts = url.split('/')
        try:
            domain_idx = parts.index('hotleaks.tv')
            creator = parts[domain_idx + 1]
            
            if len(parts) > domain_idx + 2 and parts[domain_idx + 2] in ['video', 'photo']:
                return f"{creator}/{parts[domain_idx + 2]}"
                
            return creator
        except (ValueError, IndexError):
            return parts[-1]

    def decode_video_url(self, encrypted_url):
        """Decrypts the video link."""
        try:
            core_string = encrypted_url[16:-16]
            reversed_string = core_string[::-1]
            return base64.b64decode(reversed_string).decode('utf-8')
        except Exception as e:
            return None

    def get_all_posts(self, creator):
        """Uses the hidden JSON API to get all posts."""
        page = 1
        all_posts = []
        
        while True:
            api_url = f"{self.base_url}/{creator}?page={page}"
            response = self.session.get(api_url, headers=self.headers)
            
            if response.status_code != 200:
                break
                
            data = response.json()
            if not data: 
                break
                
            all_posts.extend(data)
            page += 1
            
        return all_posts