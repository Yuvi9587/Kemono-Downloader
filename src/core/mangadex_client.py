
import os
import re
import time
import cloudscraper
from collections import defaultdict
from ..utils.file_utils import clean_folder_name

def fetch_mangadex_data(start_url, output_dir, logger_func, file_progress_callback, overall_progress_callback, pause_event, cancellation_event, proxies=None):
    """
    Fetches and downloads all content from a MangaDex series or chapter URL.
    Returns a tuple of (downloaded_count, skipped_count).
    """
    grand_total_dl = 0
    grand_total_skip = 0
    
    api = _MangadexAPI(logger_func, proxies=proxies)

    def _check_pause():
        if cancellation_event and cancellation_event.is_set(): return True
        if pause_event and pause_event.is_set():
            logger_func("   Download paused...")
            while pause_event.is_set():
                if cancellation_event and cancellation_event.is_set(): return True
                time.sleep(0.5)
            logger_func("   Download resumed.")
        return cancellation_event.is_set()

    series_match = re.search(r"mangadex\.org/(?:title|manga)/([0-9a-f-]+)", start_url)
    chapter_match = re.search(r"mangadex\.org/chapter/([0-9a-f-]+)", start_url)

    chapters_to_process = []
    if series_match:
        series_id = series_match.group(1)
        logger_func(f"   Series detected. Fetching chapter list for ID: {series_id}")
        chapters_to_process = api.get_manga_chapters(series_id, cancellation_event, pause_event)
    elif chapter_match:
        chapter_id = chapter_match.group(1)
        logger_func(f"   Single chapter detected. Fetching info for ID: {chapter_id}")
        chapter_info = api.get_chapter_info(chapter_id)
        if chapter_info:
            chapters_to_process = [chapter_info]
    
    if not chapters_to_process:
        logger_func("❌ No chapters found or failed to fetch chapter info.")
        return 0, 0

    logger_func(f"✅ Found {len(chapters_to_process)} chapter(s) to download.")
    if overall_progress_callback:
        overall_progress_callback.emit(len(chapters_to_process), 0)

    for chap_idx, chapter_json in enumerate(chapters_to_process):
        if _check_pause(): break
        try:
            metadata = api.transform_chapter_data(chapter_json)
            logger_func("-" * 40)
            logger_func(f"Processing Chapter {chap_idx + 1}/{len(chapters_to_process)}: Vol. {metadata['volume']} Ch. {metadata['chapter']}{metadata['chapter_minor']} - {metadata['title']}")
            
            server_info = api.get_at_home_server(chapter_json["id"])
            if not server_info:
                logger_func("   ❌ Could not get image server for this chapter. Skipping.")
                continue
            
            base_url = f"{server_info['baseUrl']}/data/{server_info['chapter']['hash']}/"
            image_files = server_info['chapter']['data']

            series_folder = clean_folder_name(metadata['manga'])
            chapter_folder_title = metadata['title'] or ''
            chapter_folder = clean_folder_name(f"Vol {metadata['volume']:02d} Chap {metadata['chapter']:03d}{metadata['chapter_minor']} - {chapter_folder_title}".strip().strip('-').strip())
            final_save_path = os.path.join(output_dir, series_folder, chapter_folder)
            os.makedirs(final_save_path, exist_ok=True)

            for img_idx, filename in enumerate(image_files):
                if _check_pause(): break
                
                full_img_url = base_url + filename
                img_path = os.path.join(final_save_path, f"{img_idx + 1:03d}{os.path.splitext(filename)[1]}")

                if os.path.exists(img_path):
                    logger_func(f"   -> Skip ({img_idx+1}/{len(image_files)}): '{os.path.basename(img_path)}' already exists.")
                    grand_total_skip += 1
                    continue
                
                logger_func(f"   Downloading ({img_idx+1}/{len(image_files)}): '{os.path.basename(img_path)}'...")
                
                try:
                    response = api.session.get(full_img_url, stream=True, timeout=60, headers={'Referer': 'https://mangadex.org/'})
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))
                    
                    if file_progress_callback:
                        file_progress_callback.emit(os.path.basename(img_path), (0, total_size))

                    with open(img_path, 'wb') as f:
                        downloaded_bytes = 0
                        for chunk in response.iter_content(chunk_size=8192):
                            if _check_pause(): break
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if file_progress_callback:
                                file_progress_callback.emit(os.path.basename(img_path), (downloaded_bytes, total_size))
                    
                    if _check_pause():
                        if os.path.exists(img_path): os.remove(img_path)
                        break
                    
                    grand_total_dl += 1
                except Exception as e:
                    logger_func(f"      ❌ Failed to download page {img_idx+1}: {e}")
                    grand_total_skip += 1
            
            if overall_progress_callback:
                overall_progress_callback.emit(len(chapters_to_process), chap_idx + 1)
            time.sleep(1)

        except Exception as e:
            logger_func(f"   ❌ An unexpected error occurred while processing chapter {chapter_json.get('id')}: {e}")

    return grand_total_dl, grand_total_skip

class _MangadexAPI:
    def __init__(self, logger_func, proxies=None):
        self.logger_func = logger_func
        self.session = cloudscraper.create_scraper()
        if proxies:
            self.session.proxies.update(proxies)
        self.root = "https://api.mangadex.org"

    def _call(self, endpoint, params=None, cancellation_event=None):
        if cancellation_event and cancellation_event.is_set(): return None
        try:
            response = self.session.get(f"{self.root}{endpoint}", params=params, timeout=30)
            if response.status_code == 429:
                retry_after = int(response.headers.get("X-RateLimit-Retry-After", 5))
                self.logger_func(f"   ⚠️ Rate limited. Waiting for {retry_after} seconds...")
                time.sleep(retry_after)
                return self._call(endpoint, params, cancellation_event)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger_func(f"   ❌ API call to '{endpoint}' failed: {e}")
            return None

    def get_manga_chapters(self, series_id, cancellation_event, pause_event):
        all_chapters = []
        offset = 0
        limit = 500
        base_params = {
            "limit": limit, "order[volume]": "asc", "order[chapter]": "asc",
            "translatedLanguage[]": ["en"], "includes[]": ["scanlation_group", "user", "manga"]
        }
        while True:
            if cancellation_event.is_set(): break
            while pause_event.is_set(): time.sleep(0.5)
            
            params = {**base_params, "offset": offset}
            data = self._call(f"/manga/{series_id}/feed", params, cancellation_event)
            if not data or data.get("result") != "ok": break
            
            results = data.get("data", [])
            all_chapters.extend(results)
            
            if (offset + limit) >= data.get("total", 0): break
            offset += limit
        return all_chapters

    def get_chapter_info(self, chapter_id):
        params = {"includes[]": ["scanlation_group", "user", "manga"]}
        data = self._call(f"/chapter/{chapter_id}", params)
        return data.get("data") if data and data.get("result") == "ok" else None

    def get_at_home_server(self, chapter_id):
        return self._call(f"/at-home/server/{chapter_id}")

    def transform_chapter_data(self, chapter):
        relationships = {item["type"]: item for item in chapter.get("relationships", [])}
        manga = relationships.get("manga", {})
        c_attrs = chapter.get("attributes", {})
        m_attrs = manga.get("attributes", {})
        
        chapter_num_str = c_attrs.get("chapter", "0") or "0"
        chnum, sep, minor = chapter_num_str.partition(".")
        
        return {
            "manga": (m_attrs.get("title", {}).get("en") or next(iter(m_attrs.get("title", {}).values()), "Unknown Series")),
            "title": c_attrs.get("title", ""),
            "volume": int(float(c_attrs.get("volume", 0) or 0)),
            "chapter": int(float(chnum or 0)),
            "chapter_minor": sep + minor if minor else ""
        }