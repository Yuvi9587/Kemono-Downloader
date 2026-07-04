import os
import threading
import time
from urllib.parse import urlparse

import cloudscraper
import requests
from PyQt5.QtCore import QThread, pyqtSignal

from ...core.allcomic_client import (fetch_chapter_data as allcomic_fetch_data,
                                     get_chapter_list as allcomic_get_list)
from ...utils.file_utils import clean_folder_name


class AllcomicDownloadThread(QThread):
    """A dedicated QThread for handling allcomic.com downloads."""
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool) 
    overall_progress_signal = pyqtSignal(int, int) 

    def __init__(self, url, output_dir, parent=None, proxies=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.comic_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        
        self.pause_event = parent.pause_event if hasattr(parent, 'pause_event') else threading.Event()
        self.cancellation_event = parent.cancellation_event if hasattr(parent, 'cancellation_event') else None
        self.proxies = proxies

    def _check_pause(self):
        if self.is_cancelled or (self.cancellation_event and self.cancellation_event.is_set()):
            self.is_cancelled = True
            return True
            
        if self.pause_event and self.pause_event.is_set():
            self.progress_signal.emit("   Download paused...")
            
            while self.pause_event.is_set():
                if self.is_cancelled or (self.cancellation_event and self.cancellation_event.is_set()):
                    self.is_cancelled = True
                    return True
                time.sleep(0.5)
                
            self.progress_signal.emit("   Download resumed.")
            
        return self.is_cancelled

    def _smart_sleep(self, seconds):
        iterations = int(seconds * 10)
        for _ in range(iterations):
            if self._check_pause():
                return True
            time.sleep(0.1)
        return False

    def run(self):
        grand_total_dl = 0
        grand_total_skip = 0

        if self.proxies:
            self.progress_signal.emit(f"   🌍 Network: Using Proxy {self.proxies}")
        else:
            self.progress_signal.emit("   🌍 Network: Direct Connection (No Proxy)")

        scraper = requests.Session()
        scraper.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })

        chapters_to_download = allcomic_get_list(scraper, self.comic_url, self.progress_signal.emit, check_pause_func=self._check_pause, proxies=self.proxies)

        if not chapters_to_download and not self.is_cancelled:
            chapters_to_download = [self.comic_url]

        if self._check_pause():
            self.file_progress_signal.emit("", None)
            self.finished_signal.emit(grand_total_dl, grand_total_skip, self.is_cancelled)
            return

        self.progress_signal.emit(f"--- Starting download of {len(chapters_to_download)} chapter(s) ---")

        for chapter_idx, chapter_url in enumerate(chapters_to_download):
            if self._check_pause(): break
            
            self.progress_signal.emit(f"\n-- Processing Chapter {chapter_idx + 1}/{len(chapters_to_download)} --")
            
            comic_title, chapter_title, image_urls = allcomic_fetch_data(scraper, chapter_url, self.progress_signal.emit, check_pause_func=self._check_pause, proxies=self.proxies)
            
            if self._check_pause(): break

            if not image_urls:
                self.progress_signal.emit(f"❌ Failed to get data for chapter. Skipping.")
                continue

            if getattr(self, 'export_all_links_mode', False):
                export_file_path = os.path.join(self.output_dir, "all_file_links.txt")
                self.progress_signal.emit(f"📋 Export All Links Mode: Extracting {len(image_urls)} links for chapter...")
                try:
                    with open(export_file_path, "a", encoding="utf-8") as f:
                        f.write(f"\n# AllComic: {comic_title} - {chapter_title}\n")
                        for link in image_urls:
                            f.write(link + "\n")
                    self.progress_signal.emit(f"✅ Exported links to {export_file_path}")
                    grand_total_dl += len(image_urls)
                except Exception as e:
                    self.progress_signal.emit(f"❌ Failed to export links: {e}")
                
                if self._smart_sleep(0.5): break
                continue

            series_folder_name = clean_folder_name(comic_title)
            chapter_folder_name = clean_folder_name(chapter_title)
            final_save_path = os.path.join(self.output_dir, series_folder_name, chapter_folder_name)
            
            try:
                os.makedirs(final_save_path, exist_ok=True)
                self.progress_signal.emit(f"   Saving to folder: '{os.path.join(series_folder_name, chapter_folder_name)}'")
            except OSError as e:
                self.progress_signal.emit(f"❌ Critical error creating directory: {e}")
                grand_total_skip += len(image_urls)
                continue

            total_files_in_chapter = len(image_urls)
            self.overall_progress_signal.emit(total_files_in_chapter, 0)
            headers = {'Referer': chapter_url}

            img_timeout = (30, 120) if self.proxies else 60

            for i, img_url in enumerate(image_urls):
                if self._check_pause(): break

                file_extension = os.path.splitext(urlparse(img_url).path)[1] or '.jpg'
                filename = f"{i+1:03d}{file_extension}"
                filepath = os.path.join(final_save_path, filename)

                if os.path.exists(filepath):
                    self.progress_signal.emit(f"   -> Skip ({i+1}/{total_files_in_chapter}): '{filename}' already exists.")
                    grand_total_skip += 1
                else:
                    download_successful = False
                    max_retries = 8
                    for attempt in range(max_retries):
                        if self._check_pause(): break
                        try:
                            self.progress_signal.emit(f"   Downloading ({i+1}/{total_files_in_chapter}): '{filename}' (Attempt {attempt + 1})...")
                            
                            response = scraper.get(img_url, stream=True, headers=headers, timeout=img_timeout, proxies=self.proxies, verify=False)
                            response.raise_for_status()

                            with open(filepath, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    if self._check_pause(): break
                                    f.write(chunk)
                            
                            if self._check_pause():
                                if os.path.exists(filepath): os.remove(filepath)
                                break 
                            
                            download_successful = True
                            grand_total_dl += 1
                            break
                        
                        except requests.RequestException as e:
                            self.progress_signal.emit(f"      ⚠️ Attempt {attempt + 1} failed for '{filename}': {e}")
                            if attempt < max_retries - 1:
                                wait_time = 2 * (attempt + 1)
                                self.progress_signal.emit(f"         Retrying in {wait_time} seconds...")
                                if self._smart_sleep(wait_time):
                                    break
                            else:
                                self.progress_signal.emit(f"   ❌ All attempts failed for '{filename}'. Skipping.")
                                grand_total_skip += 1
                
                self.overall_progress_signal.emit(total_files_in_chapter, i + 1)
                
                if self._smart_sleep(0.5):
                    break
            
            if self._check_pause(): break

        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(grand_total_dl, grand_total_skip, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self.progress_signal.emit("   Cancellation signal received by AllComic thread.")