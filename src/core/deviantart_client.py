import requests
import re
import os
import time
import threading
from urllib.parse import urlparse

class DeviantArtClient:
    CLIENT_ID = "5388"
    CLIENT_SECRET = "76b08c69cfb27f26d6161f9ab6d061a1"
    BASE_API = "https://www.deviantart.com/api/v1/oauth2"

    def __init__(self, logger_func=print, check_pause_func=None, proxies=None):
        self.session = requests.Session()
        self.logger = logger_func
        self.check_pause_func = check_pause_func
        
        if proxies:
            self.session.proxies.update(proxies)
            self.session.verify = False
            self.proxies_enabled = True
        else:
            self.proxies_enabled = False

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
        self.access_token = None
        
        self.logged_waits = set()
        self.log_lock = threading.Lock()

    def _smart_sleep(self, seconds):
        if not self.check_pause_func:
            time.sleep(seconds)
            return False
        for _ in range(int(seconds * 10)):
            if self.check_pause_func(): return True
            time.sleep(0.1)
        return False

    def authenticate(self):
        """Authenticates using client credentials flow."""
        try:
            url = "https://www.deviantart.com/oauth2/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.CLIENT_ID,
                "client_secret": self.CLIENT_SECRET
            }
            req_timeout = 30 if self.proxies_enabled else 10
            
            resp = self.session.post(url, data=data, timeout=req_timeout)
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token")
            return True
        except Exception as e:
            self.logger(f"DA Auth Error: {e}")
            return False

    def _api_call(self, endpoint, params=None):
        if not self.access_token:
            if not self.authenticate():
                raise Exception("Authentication failed")
        
        url = f"{self.BASE_API}{endpoint}"
        params = params or {}
        params['access_token'] = self.access_token
        params['mature_content'] = 'true'
        
        retries = 0
        max_retries = 4
        backoff_delay = 2 
        
        req_timeout = 30 if self.proxies_enabled else 20

        while True:
            if self.check_pause_func and self.check_pause_func():
                return {}

            try:
                resp = self.session.get(url, params=params, timeout=req_timeout)
                                
                if resp.status_code == 429:
                    retry_after = resp.headers.get('Retry-After')
                    if retry_after:
                        sleep_time = int(retry_after) + 2
                    else:
                        sleep_time = 15 
                    
                    self._log_once(sleep_time, f"   [DeviantArt] ⚠️ Rate limit (429). Sleeping {sleep_time}s...")
                    if self._smart_sleep(sleep_time):
                        return {}
                    continue

                if resp.status_code == 401: 
                    self.logger("   [DeviantArt] Token expired. Refreshing...")
                    if self.authenticate():
                        params['access_token'] = self.access_token
                        continue 
                    else:
                        raise Exception("Failed to refresh token")

                if 400 <= resp.status_code < 500:
                    resp.raise_for_status() 

                if 500 <= resp.status_code < 600:
                    resp.raise_for_status() 

                resp.raise_for_status()
                
                with self.log_lock:
                    self.logged_waits.clear()
                        
                return resp.json()

            except requests.exceptions.HTTPError as e:
                if e.response is not None and 400 <= e.response.status_code < 500:
                    raise e
                pass

            except requests.exceptions.RequestException as e:
                if retries < max_retries:
                    self._log_once("conn_error", f"   [DeviantArt] Connection error: {e}. Retrying...")
                    if self._smart_sleep(backoff_delay):
                        return {}
                    retries += 1
                    continue
                raise e
    
    def _log_once(self, key, message):
        """Helper to avoid spamming the same log message during loops."""
        should_log = False
        with self.log_lock:
            if key not in self.logged_waits:
                self.logged_waits.add(key)
                should_log = True
        if should_log:
            self.logger(message)

    def get_deviation_uuid(self, url):
        """Scrapes the deviation page to find the UUID."""
        try:
            req_timeout = 30 if self.proxies_enabled else 15
            resp = self.session.get(url, timeout=req_timeout)
            match = re.search(r'"deviationUuid":"([^"]+)"', resp.text)
            if match:
                return match.group(1)
            match = re.search(r'-(\d+)$', url)
            if match:
                return match.group(1)
        except Exception as e:
            self.logger(f"Error scraping UUID: {e}")
        return None

    def get_deviation_content(self, uuid):
        """Fetches download info."""
        try:
            data = self._api_call(f"/deviation/download/{uuid}")
            if 'src' in data:
                return data
        except Exception:
            pass
        
        try:
            meta = self._api_call(f"/deviation/{uuid}")
            if 'content' in meta:
                return meta['content']
        except Exception:
            pass
        return None

    def get_gallery_folder(self, username, offset=0, limit=24):
        """Fetches items from a user's gallery."""
        return self._api_call("/gallery/all", {"username": username, "offset": offset, "limit": limit})

    @staticmethod
    def extract_info_from_url(url):
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        parts = path.split('/')
        
        if len(parts) >= 3 and parts[1] == 'art':
            return 'post', parts[0], parts[2]
        elif len(parts) >= 2 and parts[1] == 'gallery':
            return 'gallery', parts[0], None
        elif len(parts) == 1:
            return 'gallery', parts[0], None
            
        return None, None, None