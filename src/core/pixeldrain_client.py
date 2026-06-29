import os
import re
import cloudscraper
from ..utils.file_utils import clean_folder_name
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def fetch_pixeldrain_data(url: str, logger, proxies=None):
    """
    Scrapes a given Pixeldrain URL to extract album or file information.
    Handles single files (/u/), albums/lists (/l/), and folders (/d/).
    """
    logger(f"Fetching data for Pixeldrain URL: {url}")
    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    root = "https://pixeldrain.com"

    try:
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        scraper.mount("https://", adapter)
        scraper.mount("http://", adapter)
        logger("   [Pixeldrain] Configured retry strategy for network requests.")
    except Exception as e:
        logger(f"   [Pixeldrain] ⚠️ Could not configure retry strategy: {e}")

    file_match = re.search(r"/u/(\w+)", url)
    album_match = re.search(r"/l/(\w+)", url)
    folder_match = re.search(r"/d/([^?]+)", url)

    try:
        if file_match:
            file_id = file_match.group(1)
            logger(f"   Detected Pixeldrain File ID: {file_id}")
            api_url = f"{root}/api/file/{file_id}/info"
            data = scraper.get(api_url).json()
            
            title = data.get("name", file_id)
            
            files = [{
                'url': f"{root}/api/file/{file_id}?download",
                'filename': data.get("name", f"{file_id}.tmp")
            }]
            return title, files

        elif album_match:
            album_id = album_match.group(1)
            logger(f"   Detected Pixeldrain Album ID: {album_id}")
            api_url = f"{root}/api/list/{album_id}"
            data = scraper.get(api_url).json()

            title = data.get("title", album_id)
            
            files = []
            for file_info in data.get("files", []):
                files.append({
                    'url': f"{root}/api/file/{file_info['id']}?download",
                    'filename': file_info.get("name", f"{file_info['id']}.tmp")
                })
            return title, files

        elif folder_match:
            path_id = folder_match.group(1)
            logger(f"   Detected Pixeldrain Folder Path: {path_id}")
            api_url = f"{root}/api/filesystem/{path_id}?stat"
            data = scraper.get(api_url).json()

            path_info = data["path"][data["base_index"]]
            title = path_info.get("name", path_id)

            files = []
            for child in data.get("children", []):
                if child.get("type") == "file":
                    files.append({
                        'url': f"{root}/api/filesystem{child['path']}?attach",
                        'filename': child.get("name")
                    })
            return title, files

        else:
            logger("   ❌ Could not identify Pixeldrain URL type (file, album, or folder).")
            return None, []

    except Exception as e:
        logger(f"❌ An error occurred while fetching Pixeldrain data: {e}")
        return None, []