import os
import re as re_module
import html
import urllib.parse
from curl_cffi import requests as cffi_requests

PATTERN_CACHE = {}

def re(pattern):
    """Compile a regular expression pattern and cache it."""
    try:
        return PATTERN_CACHE[pattern]
    except KeyError:
        p = PATTERN_CACHE[pattern] = re_module.compile(pattern)
        return p

def extract_from(txt, pos=None, default=""):
    """Returns a function that extracts text between two delimiters from 'txt'."""
    def extr(begin, end, txt=txt):
        nonlocal pos
        try:
            start_pos = pos if pos is not None else 0
            first = txt.index(begin, start_pos) + len(begin)
            last = txt.index(end, first)
            if pos is not None:
                pos = last + len(end)
            return txt[first:last]
        except (ValueError, IndexError):
            return default
    return extr

def nameext_from_url(url):
    """Extract filename and extension from a URL."""
    data = {}
    filename = urllib.parse.unquote(url.partition("?")[0].rpartition("/")[2])
    name, _, ext = filename.rpartition(".")
    if name and len(ext) <= 16:
        data["filename"], data["extension"] = name, ext.lower()
    else:
        data["filename"], data["extension"] = filename, ""
    return data

class BaseExtractor:
    """A simplified base class for extractors."""
    def __init__(self, match, session, logger):
        self.match = match
        self.groups = match.groups()
        self.session = session
        self.log = logger

    def request(self, url, **kwargs):
        """Makes an HTTP request using the curl_cffi session."""
        try:
            response = self.session.get(url, timeout=30, **kwargs)
            if response.status_code >= 400:
                self.log(f"      ❌ HTTP Error {response.status_code} for {url}")
                return None
                
            if "Just a moment..." in response.text or "Checking your browser" in response.text:
                self.log(f"      ❌ Caught by Cloudflare protection at {url}")
                return None
                
            return response
        except Exception as e:
            self.log(f"      ❌ Error making request to {url}: {e}")
            return None

class SaintAlbumExtractor(BaseExtractor):
    """Extractor for saint.su & turbo.cr albums."""
    pattern = re(r"(?:https?://)?(?:saint\d*\.(?:su|pk|cr|to)|turbo\.cr)/a/([^/?#]+)")

    def items(self):
        """Generator that yields all files from an album."""
        album_id = self.groups[0]
        
        response = self.request(f"https://turbo.cr/a/{album_id}")
        if not response:
            return None, []

        extr = extract_from(response.text)
        title = extr("<title>", "<").rpartition(" - ")[0]
        self.log(f"   Downloading album: {title}")

        files_html = re_module.findall(r'<a class="image".*?</a>', response.text, re_module.DOTALL)
        file_list = []
        for i, file_html in enumerate(files_html, 1):
            file_extr = extract_from(file_html)
            file_url = html.unescape(file_extr("onclick=\"play('", "'"))
            if not file_url:
                continue

            filename_info = nameext_from_url(file_url)
            filename = f"{filename_info['filename']}.{filename_info['extension']}"

            file_data = {
                "url": file_url,
                "filename": filename,
                "headers": {"Referer": response.url},
            }
            file_list.append(file_data)
        
        return title, file_list

class SaintMediaExtractor(BaseExtractor):
    """Extractor for single saint.su & turbo.cr media links."""
    pattern = re(r"(?:https?://)?(?:saint\d*\.(?:su|pk|cr|to)|turbo\.cr)(/(embe)?d/([^/?#]+))")

    def items(self):
        """Generator that yields the single file from a media page."""
        path, embed, media_id = self.groups
        
        embed_url = f"https://turbo.cr/embed/{media_id}"
        response = self.request(embed_url)
        
        title = media_id
        if response:
            extr = extract_from(response.text)
            title = extr("<title>", "<").rpartition(" - ")[0] or media_id

        file_url = ""

        self.log(f"      🔄 Requesting signed video URL from API for ID: {media_id}")
        api_url = f"https://turbo.cr/api/sign?v={media_id}"
        
        try:
            api_resp = self.session.get(api_url, headers={
                "Accept": "application/json",
                "Referer": embed_url
            })
            
            if api_resp.status_code == 200:
                data = api_resp.json()
                if data.get("success") and data.get("url"):
                    file_url = data["url"]
                    self.log("      ✅ Successfully fetched signed URL.")
        except Exception as e:
            self.log(f"      ⚠️ API sign request failed: {e}")

        if not file_url and response:
            clean_html = response.text.replace('\\/', '/').replace('\\"', '"')
            turbocdn_direct = re_module.search(r'(https?://[^"\'<>\s]*\.turbocdn\.[^"\'<>\s]+)', clean_html)
            if turbocdn_direct:
                file_url = turbocdn_direct.group(1)

        if not file_url:
            self.log(f"      ❌ Could not resolve true video URL for {media_id}. The video may be deleted.")
            return title, []

        file_url = html.unescape(file_url).replace("&amp;", "&")

        filename_info = nameext_from_url(file_url)
        ext = filename_info['extension'] or 'mp4'
        name = filename_info['filename'] or media_id
        
        name = name.split('?')[0]
        ext = ext.split('?')[0]

        filename = f"{name}.{ext}"

        file_data = {
            "url": file_url,
            "filename": filename,
            "headers": {
                "Referer": "https://turbo.cr/",
                "Origin": "https://turbo.cr",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*"
            },
            "cookies": self.session.cookies.get_dict()
        }
        
        return title, [file_data]


def fetch_saint2_data(url, logger, proxies=None):
    """
    Identifies the correct extractor for a saint2/turbo URL and returns the data.
    """
    extractors = [SaintMediaExtractor, SaintAlbumExtractor]
    
    session = cffi_requests.Session(impersonate="chrome120")
    session.headers.update({
        'Referer': 'https://turbo.cr/'
    })
    if proxies:
        # curl_cffi supports proxies on the Session object
        session.proxies = proxies

    for extractor_cls in extractors:
        match = extractor_cls.pattern.match(url)
        if match:
            extractor = extractor_cls(match, session, logger)
            album_title, files = extractor.items()
            sanitized_title = re_module.sub(r'[<>:"/\\|?*]', '_', album_title) if album_title else "turbo_cr_download"
            return sanitized_title, files

    logger(f"Error: The URL '{url}' does not match a known Saint2/Turbo pattern.")
    return None, []