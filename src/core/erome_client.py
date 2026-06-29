
import os
import re
import html
import time
import urllib.parse
import requests
from datetime import datetime
import cloudscraper


def extr(txt, begin, end, default=""):
    """Stripped-down version of 'extract()' to find text between two delimiters."""
    try:
        first = txt.index(begin) + len(begin)
        return txt[first:txt.index(end, first)]
    except (ValueError, IndexError):
        return default

def extract_iter(txt, begin, end):
    """Yields all occurrences of text between two delimiters."""
    try:
        index = txt.index
        lbeg = len(begin)
        lend = len(end)
        pos = 0
        while True:
            first = index(begin, pos) + lbeg
            last = index(end, first)
            pos = last + lend
            yield txt[first:last]
    except (ValueError, IndexError):
        return

def nameext_from_url(url):
    """Extracts filename and extension from a URL."""
    data = {}
    filename = urllib.parse.unquote(url.partition("?")[0].rpartition("/")[2])
    name, _, ext = filename.rpartition(".")
    if name and len(ext) <= 16:
        data["filename"], data["extension"] = name, ext.lower()
    else:
        data["filename"], data["extension"] = filename, ""
    return data

def parse_timestamp(ts, default=None):
    """Creates a datetime object from a Unix timestamp."""
    try:
        return datetime.fromtimestamp(int(ts))
    except (ValueError, TypeError):
        return default


def fetch_erome_data(url, logger, proxies=None):
    """
    Identifies and extracts all media files from an Erome album URL.

    Args:
        url (str): The Erome album URL (e.g., https://www.erome.com/a/albumID).
        logger (function): A function to log progress messages.

    Returns:
        tuple: A tuple containing (album_folder_name, list_of_file_dicts).
               Returns (None, []) if data extraction fails.
    """
    album_id_match = re.search(r"/a/(\w+)", url)
    if not album_id_match:
        logger(f"Error: The URL '{url}' does not appear to be a valid Erome album link.")
        return None, []

    album_id = album_id_match.group(1)
    page_url = f"https://www.erome.com/a/{album_id}"
    
    session = cloudscraper.create_scraper()
    if proxies:
        session.proxies.update(proxies)

    try:
        logger(f"   Fetching Erome album page: {page_url}")
        for attempt in range(5):
            response = session.get(page_url, timeout=30)
            response.raise_for_status()
            page_content = response.text
            if "<title>Please wait a few moments</title>" in page_content:
                logger(f"   Cloudflare check detected. Waiting 5 seconds... (Attempt {attempt + 1}/5)")
                time.sleep(5)
                continue
            break
        else:
            logger("   Error: Could not bypass Cloudflare check after several attempts.")
            return None, []

        title = html.unescape(extr(page_content, 'property="og:title" content="', '"'))
        user = urllib.parse.unquote(extr(page_content, 'href="https://www.erome.com/', '"', default="unknown_user"))
        
        sanitized_title = re.sub(r'[<>:"/\\|?*]', '_', title).strip()
        sanitized_user = re.sub(r'[<>:"/\\|?*]', '_', user).strip()
        
        album_folder_name = f"Erome - {sanitized_user} - {sanitized_title} [{album_id}]"
        
        urls = []
        media_groups = page_content.split('<div class="media-group"')
        for group in media_groups[1:]: 
            video_url = extr(group, '<source src="', '"') or extr(group, 'data-src="', '"')
            if video_url:
                urls.append(video_url)

        if not urls:
            logger("   Warning: No media URLs found on the album page.")
            return album_folder_name, []

        logger(f"   Found {len(urls)} media files in album '{title}'.")
        
        file_list = []
        for i, file_url in enumerate(urls, 1):
            filename_info = nameext_from_url(file_url)
            filename = f"{album_id}_{sanitized_title}_{i:03d}.{filename_info.get('extension', 'mp4')}"
            
            file_data = {
                "url": file_url,
                "filename": filename,
                "headers": {"Referer": page_url},
            }
            file_list.append(file_data)
            
        return album_folder_name, file_list

    except requests.exceptions.RequestException as e:
        logger(f"   Error fetching Erome page: {e}")
        return None, []
    except Exception as e:
        logger(f"   An unexpected error occurred during Erome extraction: {e}")
        return None, []