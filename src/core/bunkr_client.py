import logging
import os
import re
import requests
import html
import time
import datetime
import urllib.parse
import json
import random
import binascii
import itertools

class MockMessage:
    Directory = 1
    Url = 2
    Version = 3

class AlbumException(Exception): pass
class ExtractionError(AlbumException): pass
class HttpError(ExtractionError):
    def __init__(self, message="", response=None):
        self.response = response
        self.status = response.status_code if response is not None else 0
        super().__init__(message)
class ControlException(AlbumException): pass
class AbortExtraction(ExtractionError, ControlException): pass

try:
    re_compile = re._compiler.compile
except AttributeError:
    re_compile = re.sre_compile.compile
HTML_RE = re_compile(r"<[^>]+>")
def extr(txt, begin, end, default=""):
    try:
        first = txt.index(begin) + len(begin)
        return txt[first:txt.index(end, first)]
    except Exception: return default
def extract_iter(txt, begin, end, pos=None):
    try:
        index = txt.index
        lbeg = len(begin)
        lend = len(end)
        while True:
            first = index(begin, pos) + lbeg
            last = index(end, first)
            pos = last + lend
            yield txt[first:last]
    except Exception: return
def split_html(txt):
    try: return [html.unescape(x).strip() for x in HTML_RE.split(txt) if x and not x.isspace()]
    except TypeError: return []
def parse_datetime(date_string, format="%Y-%m-%dT%H:%M:%S%z", utcoffset=0):
    try:
        d = datetime.datetime.strptime(date_string, format)
        o = d.utcoffset()
        if o is not None: d = d.replace(tzinfo=None, microsecond=0) - o
        else:
            if d.microsecond: d = d.replace(microsecond=0)
            if utcoffset: d += datetime.timedelta(0, utcoffset * -3600)
        return d
    except (TypeError, IndexError, KeyError, ValueError, OverflowError): return None
unquote = urllib.parse.unquote
unescape = html.unescape

def decrypt_xor(encrypted, key, base64=True, fromhex=False):
    if base64: encrypted = binascii.a2b_base64(encrypted)
    if fromhex: encrypted = bytes.fromhex(encrypted.decode())
    div = len(key)
    return bytes([encrypted[i] ^ key[i % div] for i in range(len(encrypted))]).decode()
def advance(iterable, num):
    iterator = iter(iterable)
    next(itertools.islice(iterator, num, num), None)
    return iterator
def json_loads(s): return json.loads(s)
def json_dumps(obj): return json.dumps(obj, separators=(",", ":"))

class Extractor:
    def __init__(self, match, logger):
        self.log = logger
        self.url = match.string
        self.match = match
        self.groups = match.groups()
        self.proxies = None
        
        from curl_cffi import requests as cffi_requests
        self.session = cffi_requests.Session(impersonate="chrome120")
    @classmethod
    def from_url(cls, url, logger):
        if isinstance(cls.pattern, str): cls.pattern = re.compile(cls.pattern)
        match = cls.pattern.match(url)
        return cls(match, logger) if match else None
    def __iter__(self): return self.items()
    def items(self): yield MockMessage.Version, 1
    def request(self, url, method="GET", fatal=True, **kwargs):
        tries = 1
        if self.proxies and 'proxies' not in kwargs:
            kwargs['proxies'] = self.proxies
        while True:
            try:
                response = self.session.request(method, url, **kwargs)
                if response.status_code < 400: return response
                msg = f"'{response.status_code} {response.reason}' for '{response.url}'"
            except requests.exceptions.RequestException as exc:
                msg = str(exc)
            
            self.log.info("%s (retrying...)", msg)
            if tries > 4: break
            time.sleep(tries)
            tries += 1
        if not fatal: return None
        raise HttpError(msg)
    def request_json(self, url, **kwargs):
        response = self.request(url, **kwargs)
        try: return json_loads(response.text)
        except Exception as exc:
            self.log.warning("%s: %s", exc.__class__.__name__, exc)
            if not kwargs.get("fatal", True): return {}
            raise

BASE_PATTERN_BUNKR = r"(?:https?://)?(?:[a-zA-Z0-9-]+\.)?(bunkr\.[a-z]+|bunkrr\.[a-z]+|bunkr-albums\.[a-z]+|balbums\.[a-z]+)"
DOMAINS = ["bunkr.si", "bunkr.ws", "bunkr.la", "bunkr.red", "bunkr.black", "bunkr.media", "bunkr.site", "balbums.st"]
CF_DOMAINS = set()

class BunkrAlbumExtractor(Extractor):
    category = "bunkr"
    root = "https://bunkr.si"
    root_dl = "https://get.bunkrr.su"
    root_api = "https://apidl.bunkr.ru"
    pattern = re.compile(BASE_PATTERN_BUNKR + r"/a/([^/?#]+)")

    def __init__(self, match, logger):
        super().__init__(match, logger)
        domain_match = re.search(BASE_PATTERN_BUNKR, match.string)
        if domain_match:
            self.root = "https://" + domain_match.group(1)
        self.endpoint = self.root_api + "/api/_001_v2"
        self.album_id = self.groups[-1]

    def items(self):
        page = self.request(self.url).text
        title = unescape(unescape(extr(page, 'property="og:title" content="', '"')))
        items_html = list(extract_iter(page, '<div class="grid-images_box', "</a>"))

        album_data = {
            "album_id": self.album_id, 
            "album_name": title,
            "count": len(items_html),
        }
        yield MockMessage.Directory, album_data, {}

        for item_html in items_html:
            try:
                webpage_url = unescape(extr(item_html, ' href="', '"'))
                if webpage_url.startswith("/"):
                    webpage_url = self.root + webpage_url
                
                file_data = self._extract_file(webpage_url)
                info = split_html(item_html)

                if not file_data.get("name"):
                    file_data["name"] = info[-3]
                
                yield MockMessage.Url, file_data, {}
            except Exception as exc:
                self.log.error(f"{exc.__class__.__name__}: {exc}")

    def _extract_file(self, webpage_url):
        page = self.request(webpage_url).text
        data_id = extr(page, 'data-file-id="', '"')
        
        api_referer = self.root_dl + "/file/" + data_id
        headers = {"Referer": api_referer, "Origin": self.root_dl}
        data = self.request_json(self.endpoint, method="POST", headers=headers, json={"id": data_id})
        
        file_url = decrypt_xor(data["url"], f"SECRET_KEY_{data['timestamp'] // 3600}".encode()) if data.get("encrypted") else data["url"]
        
        file_name = extr(page, "<h1", "<").rpartition(">")[2]
        file_name_clean = unescape(file_name)

        # Bunkr's new URL Signing Logic
        try:
            parsed = urllib.parse.urlparse(file_url)
            sign_path = urllib.parse.quote(parsed.path, safe="")
            sign_url = f"https://glb-apisign.cdn.cr/sign?path={sign_path}"
            sign_data = self.request_json(sign_url, method="GET")
            
            token = sign_data.get("token")
            ex = sign_data.get("ex")
            
            if token and ex:
                query = urllib.parse.parse_qs(parsed.query)
                query["token"] = [token]
                query["ex"] = [str(ex)]
                if file_name_clean:
                    query["n"] = [file_name_clean]
                
                new_query = urllib.parse.urlencode(query, doseq=True)
                file_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        except Exception as e:
            self.log.warning(f"Failed to sign Bunkr URL: {e}")

        
        user_agent = self.session.headers.get("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:102.0) Gecko/20100101 Firefox/102.0")
        
        # Bunkr's CDN requires the Referer to be the exact API file endpoint
        download_referer = api_referer
        
        headers_dict = {
            "Referer": download_referer,
            "User-Agent": user_agent
        }
        
        cookie_str = "; ".join([f"{k}={v}" for k, v in self.session.cookies.get_dict().items()])
        if cookie_str:
            headers_dict["Cookie"] = cookie_str

        return {
            "url": file_url, 
            "name": unescape(file_name), 
            "_http_headers": headers_dict
        }

class BunkrMediaExtractor(BunkrAlbumExtractor):
    pattern = re.compile(BASE_PATTERN_BUNKR + r"(/[fvid]/[^/?#]+)")
    def items(self):
        try:
            media_path = self.groups[-1]
            file_data = self._extract_file(self.root + media_path)
            album_data = {"album_name": file_data.get("name", "bunkr_media"), "count": 1}

            yield MockMessage.Directory, album_data, {}
            yield MockMessage.Url, file_data, {}

        except Exception as exc:
            self.log.error(f"{exc.__class__.__name__}: {exc}")
            yield MockMessage.Directory, {"album_name": "error", "count": 0}, {}

def get_bunkr_extractor(url, logger, proxies=None):
    """Selects the correct Bunkr extractor based on the URL pattern."""
    extractor = None
    if BunkrAlbumExtractor.pattern.match(url):
        logger.info("Bunkr Album URL detected.")
        extractor = BunkrAlbumExtractor.from_url(url, logger)
    elif BunkrMediaExtractor.pattern.match(url):
        logger.info("Bunkr Media URL detected.")
        extractor = BunkrMediaExtractor.from_url(url, logger)
    else:
        logger.error(f"No suitable Bunkr extractor found for URL: {url}")
        return None
    if extractor and proxies:
        extractor.proxies = proxies
    return extractor

def fetch_bunkr_data(url, logger, proxies=None):
    """
    Main function to be called from the GUI.
    It extracts all file information from a Bunkr URL, now handling both albums and direct file links.
    
    Returns:
        A tuple of (album_name, list_of_files)
        - album_name (str): The name of the album.
        - list_of_files (list): A list of dicts, each containing 'url', 'name', and '_http_headers'.
        Returns (None, None) on failure.
    """
    try:
        parsed_url = urllib.parse.urlparse(url)
        
        # Bunkr constantly changes domains and puts strict Cloudflare Turnstile on some (like bunkr.black).
        # However, older/alternative domains like bunkr.cr often remain unprotected by Turnstile.
        # We forcibly rewrite the host to bunkr.cr to guarantee HTML scraping works.
        if parsed_url.hostname and 'bunkr' in parsed_url.hostname and 'cdn' not in parsed_url.hostname:
            parsed_url = parsed_url._replace(netloc='bunkr.cr')
            url = urllib.parse.urlunparse(parsed_url)

        is_direct_cdn_file = (parsed_url.hostname and 'cdn' in parsed_url.hostname and 'bunkr' in parsed_url.hostname and
                              any(parsed_url.path.lower().endswith(ext) for ext in ['.mp4', '.mkv', '.webm', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.rar']))

        if is_direct_cdn_file:
            # Direct CDN links without tokens now get blocked by Cloudflare or return 403.
            # We rewrite them into proper Bunkr Media URLs to force token extraction.
            filename = os.path.basename(parsed_url.path)
            url = f"https://bunkr.cr/f/{filename}"
            logger.info(f"Converted direct CDN link to Media URL: {url}")
    except Exception as e:
        logger.warning(f"Could not parse Bunkr URL for direct file check: {e}")

    extractor = get_bunkr_extractor(url, logger, proxies=proxies)
    if not extractor:
        return None, None

    try:
        album_name = "default_bunkr_album"
        files_to_download = []
        for msg_type, data, metadata in extractor:
            if msg_type == MockMessage.Directory:
                raw_album_name = data.get('album_name', 'untitled')
                album_name = re.sub(r'[<>:"/\\|?*]', '_', raw_album_name).strip() or "untitled"
                logger.info(f"Processing Bunkr album: {album_name}")
            elif msg_type == MockMessage.Url:
                files_to_download.append(data)
        
        if not files_to_download:
            logger.warning("No files found to download from the Bunkr URL.")
            return None, None
            
        return album_name, files_to_download
    
    except Exception as e:
        logger.error(f"An error occurred while extracting Bunkr info: {e}", exc_info=True)
        return None, None
