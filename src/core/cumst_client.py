"""
cum.st API client.
Handles URL parsing and API communication for cum.st.

API base: https://cum.st/api/v1/{service}/user/{user_id}/posts?limit=50&offset=N
CDN base: https://e1.cum.st/media/{storageKey}/{variant_name}
"""

import re

try:
    from curl_cffi import requests as cffi_requests
    _CURL_AVAILABLE = True
except ImportError:
    import requests as cffi_requests
    _CURL_AVAILABLE = False

BASE_URL = "https://cum.st"
CDN_BASE = "https://e1.cum.st"
API_BASE = f"{BASE_URL}/api/v1"
POSTS_PER_PAGE = 50


class CumStClient:
    def __init__(self, proxies=None):
        self.proxies = proxies
        if _CURL_AVAILABLE:
            self.session = cffi_requests.Session(impersonate="chrome")
        else:
            self.session = cffi_requests.Session()
            self.session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": BASE_URL,
            })
        if proxies:
            self.session.proxies = proxies

    def parse_url(self, url):
        """
        Parse a cum.st creator URL and return (service, user_id).

        Supported formats:
          https://cum.st/creators/onlyfans/32696630
          https://cum.st/creators/onlyfans/32696630/post/2607896312
        Returns (None, None) if parsing fails.
        """
        m = re.search(r'/creators/([^/?#]+)/([^/?#]+)', url)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def get_posts_page(self, service, user_id, offset=0, limit=POSTS_PER_PAGE):
        """
        Fetch one page of posts from the API.
        Returns (total, posts_list) or raises on HTTP error.
        """
        url = f"{API_BASE}/{service}/user/{user_id}/posts?limit={limit}&offset={offset}"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("total", 0), data.get("posts", [])

    @staticmethod
    def build_cdn_url(storage_key, variant_name):
        """Build the direct CDN download URL for an attachment."""
        return f"{CDN_BASE}/media/{storage_key}/{variant_name}"

    @staticmethod
    def get_best_variant(variants):
        """
        Pick the best variant to download.
        Prefers 'original.*', otherwise takes the first variant.
        Returns the variant dict or None.
        """
        if not variants:
            return None
        for v in variants:
            if v.get("name", "").startswith("original"):
                return v
        return variants[0]
