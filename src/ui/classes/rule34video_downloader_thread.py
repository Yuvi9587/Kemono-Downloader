import os
import time
import requests
from PyQt5.QtCore import QThread, pyqtSignal
import cloudscraper

from PIL import Image
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    imagehash = None
    IMAGEHASH_AVAILABLE = False
from ...core.database_manager import DatabaseManager

from ...core.rule34video_client import fetch_rule34video_data
from ...utils.file_utils import clean_folder_name
from ...utils.proxy_utils import get_proxies_from_settings

class Rule34VideoDownloadThread(QThread):
    """A dedicated QThread for handling rule34video.com downloads."""
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool)

    def __init__(self, url, output_dir, parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.video_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self.db = DatabaseManager()
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def run(self):
        download_count = 0
        skip_count = 0

        video_title, final_video_url, tags_list = fetch_rule34video_data(self.video_url, self.progress_signal.emit, proxies=self.proxies)

        if not final_video_url:
            self.progress_signal.emit("❌ Failed to get video data. Aborting.")
            self.finished_signal.emit(0, 1, self.is_cancelled)
            return

        if getattr(self, 'export_all_links_mode', False):
            export_file_path = os.path.join(self.output_dir, "all_file_links.txt")
            self.progress_signal.emit(f"📋 Export All Links Mode: Extracting link...")
            try:
                with open(export_file_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# Rule34Video: {video_title}\n")
                    f.write(final_video_url + "\n")
                self.progress_signal.emit(f"✅ Exported link to {export_file_path}")
            except Exception as e:
                self.progress_signal.emit(f"❌ Failed to export link: {e}")
            self.finished_signal.emit(1, 0, self.is_cancelled)
            return

        safe_title = clean_folder_name(video_title if video_title else "rule34video_file")
        filename = f"{safe_title}.mp4"
        filepath = os.path.join(self.output_dir, filename)

        if os.path.exists(filepath):
            self.progress_signal.emit(f"   -> Skip: '{filename}' already exists.")
            self.finished_signal.emit(0, 1, self.is_cancelled)
            return

        self.progress_signal.emit(f"   Downloading: '{filename}'...")
        try:
            scraper = cloudscraper.create_scraper()
            if self.proxies:
                scraper.proxies.update(self.proxies)
            headers = {'Referer': 'https://rule34video.com/'}
            response = scraper.get(final_video_url, stream=True, headers=headers, timeout=90)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            last_update_time = time.time()

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192 * 4):
                    if self.is_cancelled:
                        break
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        current_time = time.time()
                        if total_size > 0 and (current_time - last_update_time) > 0.5:
                            self.file_progress_signal.emit(filename, (downloaded_size, total_size))
                            last_update_time = current_time
            
            if self.is_cancelled:
                if os.path.exists(filepath):
                    os.remove(filepath)
                skip_count = 1
                self.progress_signal.emit(f"   Download cancelled for '{filename}'.")
            else:
                download_count = 1
                
                self.db.record_download(
                    file_path=filepath,
                    file_name=filename,
                    file_hash=None,
                    tags_list=tags_list,
                    phash=None
                )
        
        except Exception as e:
            self.progress_signal.emit(f"   ❌ Failed to download '{filename}': {e}")
            if os.path.exists(filepath):
                os.remove(filepath)
            skip_count = 1
        
        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(download_count, skip_count, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self.progress_signal.emit("   Cancellation signal received by Rule34Video thread.")