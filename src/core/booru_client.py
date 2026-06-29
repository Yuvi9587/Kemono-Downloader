
import os
import re
import time
import datetime
import urllib.parse
import requests
import logging
import cloudscraper


class BooruClientException(Exception):
    """Base class for exceptions in this client."""
    pass

class HttpError(BooruClientException):
    """HTTP request during data extraction failed."""
    def __init__(self, message="", response=None):
        self.response = response
        self.status = response.status_code if response else 0
        if response and not message:
            message = f"'{response.status_code} {response.reason}' for '{response.url}'"
        super().__init__(message)

class NotFoundError(BooruClientException):
    pass

def unquote(s):
    return urllib.parse.unquote(s)

def parse_datetime(date_string, fmt):
    try:
        return datetime.datetime.strptime(date_string, fmt)
    except (ValueError, TypeError):
        return None

def nameext_from_url(url, data=None):
    if data is None: data = {}
    try:
        path = urllib.parse.urlparse(url).path
        filename = unquote(os.path.basename(path))
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            data["filename"], data["extension"] = name, ext.lower()
        else:
            data["filename"], data["extension"] = filename, ""
    except Exception:
        data["filename"], data["extension"] = "", ""
    return data

USERAGENT_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0"


class Extractor:
    category = ""
    subcategory = ""
    directory_fmt = ("{category}", "{id}")
    filename_fmt = "{filename}.{extension}"
    _retries = 3
    _timeout = 30

    def __init__(self, match, logger_func=print, proxies=None):
        self.url = match.string
        self.match = match
        self.groups = match.groups()
        self.session = cloudscraper.create_scraper()
        self.session.headers["User-Agent"] = USERAGENT_FIREFOX
        if proxies:
            self.session.proxies.update(proxies)
        self.log = logger_func
        self.api_key = None
        self.user_id = None

    def set_auth(self, api_key, user_id):
        self.api_key = api_key
        self.user_id = user_id
        self._init_auth()

    def _init_auth(self):
        """Placeholder for extractor-specific auth setup."""
        pass

    def request(self, url, method="GET", fatal=True, **kwargs):
        for attempt in range(self._retries + 1):
            try:
                response = self.session.request(method, url, timeout=self._timeout, **kwargs)
                if response.status_code < 400:
                    return response
                if response.status_code == 404 and fatal:
                    raise NotFoundError(f"Resource not found at {url}")
                self.log(f"Request for {url} failed with status {response.status_code}. Retrying...")
            except requests.exceptions.RequestException as e:
                self.log(f"Request for {url} failed: {e}. Retrying...")
            if attempt < self._retries:
                time.sleep(2 ** attempt)
        if fatal:
            raise HttpError(f"Failed to retrieve {url} after {self._retries} retries.")
        return None

    def request_json(self, url, **kwargs):
        response = self.request(url, **kwargs)
        try:
            return response.json()
        except (ValueError, TypeError) as exc:
            self.log(f"Failed to decode JSON from {url}: {exc}")
            raise BooruClientException("Invalid JSON response")

    def items(self):
        data = self.metadata()
        for item in self.posts():
            if isinstance(item, tuple) and item[0] == 'PAGE_UPDATE':
                yield item
                continue

            post = item
            url = post.get("file_url")
            if not url: continue
            
            nameext_from_url(url, post)
            post["date"] = parse_datetime(post.get("created_at"), "%Y-%m-%dT%H:%M:%S.%f%z")

            if url.startswith("/"):
                url = self.root + url
            post['file_url'] = url
            
            post.update(data)
            yield post

class BaseExtractor(Extractor):
    instances = ()

    def __init__(self, match, logger_func=print):
        super().__init__(match, logger_func)
        self._init_category()

    def _init_category(self):
        parsed_url = urllib.parse.urlparse(self.url)
        self.root = f"{parsed_url.scheme}://{parsed_url.netloc}"
        for i, group in enumerate(self.groups):
            if group is not None:
                try:
                    self.category = self.instances[i][0]
                    return
                except IndexError:
                    continue
    
    @classmethod
    def update(cls, instances):
        pattern_list = []
        instance_list = cls.instances = []
        for category, info in instances.items():
            root = info["root"].rstrip("/") if info["root"] else ""
            instance_list.append((category, root, info))
            pattern = info.get("pattern", re.escape(root.partition("://")[2]))
            pattern_list.append(f"({pattern})") 
        return r"(?:https?://)?(?:" + "|".join(pattern_list) + r")"


class DanbooruExtractor(BaseExtractor):
    filename_fmt = "{category}_{id}_{filename}.{extension}"
    per_page = 200

    def __init__(self, match, logger_func=print):
        super().__init__(match, logger_func)
        self._auth_logged = False

    def _init_auth(self):
        if self.user_id and self.api_key:
            if not self._auth_logged:
                self.log("Danbooru auth set.")
                self._auth_logged = True
            self.session.auth = (self.user_id, self.api_key)


    def items(self):
        data = self.metadata()
        for item in self.posts():
            if isinstance(item, tuple) and item[0] == 'PAGE_UPDATE':
                yield item
                continue

            post = item
            url = post.get("file_url")
            if not url: continue
            
            nameext_from_url(url, post)
            post["date"] = parse_datetime(post.get("created_at"), "%Y-%m-%dT%H:%M:%S.%f%z")

            if url.startswith("/"):
                url = self.root + url
            post['file_url'] = url
            
            post.update(data)
            yield post

    def metadata(self):
        return {}

    def posts(self):
        return []

    def _pagination(self, endpoint, params, prefix="b"):
        url = self.root + endpoint
        params["limit"] = self.per_page
        params["page"] = 1
        threshold = self.per_page - 20

        while True:
            posts = self.request_json(url, params=params)
            if not posts: break
            yield ('PAGE_UPDATE', len(posts)) 
            yield from posts
            if len(posts) < threshold: return
            if prefix:
                params["page"] = f"{prefix}{posts[-1]['id']}"
            else:
                params["page"] += 1

BASE_PATTERN = DanbooruExtractor.update({
    "danbooru": {"root": None, "pattern": r"(?:danbooru|safebooru)\.donmai\.us"},
})

class DanbooruTagExtractor(DanbooruExtractor):
    subcategory = "tag"
    directory_fmt = ("{category}", "{search_tags}")
    pattern = BASE_PATTERN + r"(/posts\?(?:[^&#]*&)*tags=([^&#]*))"
    
    def metadata(self):
        self.tags = unquote(self.groups[-1].replace("+", " ")).strip()
        sanitized_tags = re.sub(r'[\\/*?:"<>|]', "_", self.tags)
        return {"search_tags": sanitized_tags}

    def posts(self):
        return self._pagination("/posts.json", {"tags": self.tags})

class DanbooruPostExtractor(DanbooruExtractor):
    subcategory = "post"
    pattern = BASE_PATTERN + r"(/post(?:s|/show)/(\d+))"
    
    def posts(self):
        post_id = self.groups[-1]
        url = f"{self.root}/posts/{post_id}.json"
        post = self.request_json(url)
        return (post,) if post else ()

class GelbooruBase(Extractor):
    category = "gelbooru"
    root = "https://gelbooru.com"

    def __init__(self, match, logger_func=print):
        super().__init__(match, logger_func)
        self._auth_logged = False
    
    def _api_request(self, params, key="post"):
        if self.api_key and self.user_id:
            if not self._auth_logged:
                self.log("Gelbooru auth set.")
                self._auth_logged = True
            params.update({"api_key": self.api_key, "user_id": self.user_id})

        url = self.root + "/index.php?page=dapi&q=index&json=1"
        data = self.request_json(url, params=params)
        
        if not key: return data
        posts = data.get(key, [])
        return posts if isinstance(posts, list) else [posts] if posts else []

    def items(self):
        base_data = self.metadata()
        base_data['category'] = self.category
        
        for item in self.posts():
            if isinstance(item, tuple) and item[0] == 'PAGE_UPDATE':
                yield item
                continue

            post = item
            url = post.get("file_url")
            if not url: continue
            
            data = base_data.copy()
            data.update(post)
            nameext_from_url(url, data)
            yield data

    def metadata(self): return {}
    def posts(self): return []

GELBOORU_PATTERN = r"(?:https?://)?(?:www\.)?gelbooru\.com"

class GelbooruTagExtractor(GelbooruBase):
    subcategory = "tag"
    directory_fmt = ("{category}", "{search_tags}")
    filename_fmt = "{category}_{id}_{md5}.{extension}"
    pattern = GELBOORU_PATTERN + r"(/index\.php\?page=post&s=list&tags=([^&#]*))"
    
    def metadata(self):
        self.tags = unquote(self.groups[-1].replace("+", " ")).strip()
        sanitized_tags = re.sub(r'[\\/*?:"<>|]', "_", self.tags)
        return {"search_tags": sanitized_tags}

    def posts(self):
        """Scrapes HTML search pages as API can be restrictive for tags."""
        pid = 0
        posts_per_page = 42
        search_url = self.root + "/index.php"
        params = {"page": "post", "s": "list", "tags": self.tags}
        
        while True:
            params['pid'] = pid
            self.log(f"Scraping search results page (offset: {pid})...")
            response = self.request(search_url, params=params)
            html_content = response.text
            post_ids = re.findall(r'id="p(\d+)"', html_content)
            
            if not post_ids:
                self.log("No more posts found on page. Ending scrape.")
                break
            yield ('PAGE_UPDATE', len(post_ids))             
            for post_id in post_ids:
                post_data = self._api_request({"s": "post", "id": post_id})
                yield from post_data
            
            pid += posts_per_page

class GelbooruPostExtractor(GelbooruBase):
    subcategory = "post"
    filename_fmt = "{category}_{id}_{md5}.{extension}"
    pattern = GELBOORU_PATTERN + r"(/index\.php\?page=post&s=view&id=(\d+))"

    def posts(self):
        post_id = self.groups[-1]
        return self._api_request({"s": "post", "id": post_id})


EXTRACTORS = [
    DanbooruTagExtractor,
    DanbooruPostExtractor,
    GelbooruTagExtractor,
    GelbooruPostExtractor,
]

def find_extractor(url, logger_func, proxies=None):
    for extractor_cls in EXTRACTORS:
        match = re.search(extractor_cls.pattern, url)
        if match:
            return extractor_cls(match, logger_func, proxies=proxies)
    return None

def fetch_booru_data(url, api_key, user_id, logger_func, proxies=None):
    """
    Main function to find an extractor and yield image data.
    """
    extractor = find_extractor(url, logger_func, proxies=proxies)
    if not extractor:
        logger_func(f"No suitable Booru extractor found for URL: {url}")
        return

    logger_func(f"Using extractor: {extractor.__class__.__name__}")
    extractor.set_auth(api_key, user_id)
    
    yield from extractor.items()