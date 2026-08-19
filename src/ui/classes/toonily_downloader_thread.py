import os
import threading
import time
from urllib.parse import urlparse

import cloudscraper
from PySide6.QtCore import QThread, Signal

from PIL import Image
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    imagehash = None
    IMAGEHASH_AVAILABLE = False
from ...core.database_manager import DatabaseManager

from ...core.toonily_client import (
    fetch_chapter_data as toonily_fetch_data,
    get_chapter_list as toonily_get_list
)
from ...utils.file_utils import clean_folder_name
from ...utils.proxy_utils import get_proxies_from_settings


class ToonilyDownloadThread(QThread):
    """A dedicated QThread for handling toonily.com series or single chapters."""
    progress_signal = Signal(str)
    file_progress_signal = Signal(str, object)
    finished_signal = Signal(int, int, bool) 
    overall_progress_signal = Signal(int, int)

    def __init__(self, url, output_dir, parent=None):
        super().__init__(parent)
        self.start_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self.pause_event = parent.pause_event if hasattr(parent, 'pause_event') else threading.Event()
        self.db = DatabaseManager()
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def _check_pause(self):
        if self.is_cancelled: return True
        if self.pause_event and self.pause_event.is_set():
            self.progress_signal.emit("   Download paused...")
            while self.pause_event.is_set():
                if self.is_cancelled: return True
                time.sleep(0.5)
            self.progress_signal.emit("   Download resumed.")
        return self.is_cancelled

    def run(self):
        grand_total_dl = 0
        grand_total_skip = 0

        if '/chapter-' in self.start_url:
            chapters_to_download = [self.start_url]
            self.progress_signal.emit("ℹ️ Single Toonily chapter URL detected.")
        else:
            chapters_to_download = toonily_get_list(self.start_url, self.progress_signal.emit, proxies=self.proxies)

        if not chapters_to_download:
            self.progress_signal.emit("❌ No chapters found to download.")
            self.finished_signal.emit(0, 0, self.is_cancelled)
            return

        self.progress_signal.emit(f"--- Starting download of {len(chapters_to_download)} chapter(s) ---")
        self.overall_progress_signal.emit(len(chapters_to_download), 0)
        
        scraper = cloudscraper.create_scraper()
        if self.proxies:
            scraper.proxies.update(self.proxies)

        for chapter_idx, chapter_url in enumerate(chapters_to_download):
            if self._check_pause(): break
            
            self.progress_signal.emit(f"\n-- Processing Chapter {chapter_idx + 1}/{len(chapters_to_download)} --")
            series_title, chapter_title, image_urls = toonily_fetch_data(chapter_url, self.progress_signal.emit, scraper)
            
            if not image_urls:
                self.progress_signal.emit(f"❌ Failed to get data for chapter. Skipping.")
                continue

            series_folder_name = clean_folder_name(series_title)
            chapter_folder_name = clean_folder_name(chapter_title)
            final_save_path = os.path.join(self.output_dir, series_folder_name, chapter_folder_name)
            
            try:
                os.makedirs(final_save_path, exist_ok=True)
                self.progress_signal.emit(f"   Saving to folder: '{os.path.join(series_folder_name, chapter_folder_name)}'")
            except OSError as e:
                self.progress_signal.emit(f"❌ Critical error creating directory: {e}")
                grand_total_skip += len(image_urls)
                continue

            for i, img_url in enumerate(image_urls):
                if self._check_pause(): break
                
                try:
                    file_extension = os.path.splitext(urlparse(img_url).path)[1] or '.jpg'
                    filename = f"{i+1:03d}{file_extension}"
                    filepath = os.path.join(final_save_path, filename)

                    if os.path.exists(filepath):
                        self.progress_signal.emit(f"   -> Skip ({i+1}/{len(image_urls)}): '{filename}' already exists.")
                        grand_total_skip += 1
                    else:
                        self.progress_signal.emit(f"   Downloading ({i+1}/{len(image_urls)}): '{filename}'...")
                        response = scraper.get(img_url, stream=True, timeout=60, headers={'Referer': chapter_url})
                        response.raise_for_status()
                        
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded_size = 0
                        import time as _t
                        last_update_time = _t.time()
                        
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if self._check_pause(): break
                                if chunk:
                                    f.write(chunk)
                                    downloaded_size += len(chunk)
                                    current_time = _t.time()
                                    if current_time - last_update_time > 0.4:
                                        self.file_progress_signal.emit(filename, (downloaded_size, total_size))
                                        last_update_time = current_time
                        
                        if self._check_pause():
                            if os.path.exists(filepath): os.remove(filepath)
                            break
                        
                        self.file_progress_signal.emit(filename, (downloaded_size, total_size))
                        calculated_phash = None
                        valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
                        if file_extension.lower() in valid_exts:
                            try:
                                calculated_phash = str(imagehash.phash(Image.open(filepath), hash_size=16))
                            except Exception:
                                pass
                        self.db.record_tagless_download(
                            file_path=filepath,
                            file_name=filename,
                            file_hash=None,
                            phash=calculated_phash
                        )

                        grand_total_dl += 1
                        time.sleep(0.2)
                except Exception as e:
                    self.progress_signal.emit(f"   ❌ Failed to download '{filename}': {e}")
                    grand_total_skip += 1

            self.overall_progress_signal.emit(len(chapters_to_download), chapter_idx + 1)
            time.sleep(1)

        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(grand_total_dl, grand_total_skip, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self.progress_signal.emit("   Cancellation signal received by Toonily thread.")