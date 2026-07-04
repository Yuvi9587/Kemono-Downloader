import os
import time
import requests
import cloudscraper
from PyQt5.QtCore import QThread, pyqtSignal

from ...core.erome_client import fetch_erome_data
from ...utils.proxy_utils import get_proxies_from_settings

class EromeDownloadThread(QThread):
    """A dedicated QThread for handling erome.com downloads."""
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool)

    def __init__(self, url, output_dir, parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.erome_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def run(self):
        download_count = 0
        skip_count = 0
        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting Erome.com Download for: {self.erome_url}")
        
        album_name, files_to_download = fetch_erome_data(self.erome_url, self.progress_signal.emit, proxies=self.proxies)
        
        if not files_to_download:
            self.progress_signal.emit("❌ Failed to extract file information from Erome. Aborting.")
            self.finished_signal.emit(0, 0, self.is_cancelled)
            return

        if getattr(self, 'export_all_links_mode', False):
            export_file_path = os.path.join(self.output_dir, "all_file_links.txt")
            self.progress_signal.emit(f"📋 Export All Links Mode: Extracting {len(files_to_download)} links...")
            try:
                with open(export_file_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# Erome: {album_name}\n")
                    for file_data in files_to_download:
                        if file_data.get('url'):
                            f.write(file_data.get('url') + "\n")
                self.progress_signal.emit(f"✅ Exported links to {export_file_path}")
                download_count = len(files_to_download)
            except Exception as e:
                self.progress_signal.emit(f"❌ Failed to export links: {e}")
            self.finished_signal.emit(download_count, 0, self.is_cancelled)
            return

        album_path = os.path.join(self.output_dir, album_name)
        try:
            os.makedirs(album_path, exist_ok=True)
            self.progress_signal.emit(f"   Saving to folder: '{album_path}'")
        except OSError as e:
            self.progress_signal.emit(f"❌ Critical error creating directory: {e}")
            self.finished_signal.emit(0, len(files_to_download), self.is_cancelled)
            return

        total_files = len(files_to_download)
        session = cloudscraper.create_scraper()
        if self.proxies:
            session.proxies.update(self.proxies)

        for i, file_data in enumerate(files_to_download):
            if self.is_cancelled:
                self.progress_signal.emit("   Download cancelled by user.")
                skip_count = total_files - download_count
                break

            filename = file_data.get('filename', f'untitled_{i+1}.mp4')
            file_url = file_data.get('url')
            headers = file_data.get('headers')
            filepath = os.path.join(album_path, filename)
            
            if os.path.exists(filepath):
                self.progress_signal.emit(f"   -> Skip ({i+1}/{total_files}): '{filename}' already exists.")
                skip_count += 1
                continue

            self.progress_signal.emit(f"   Downloading ({i+1}/{total_files}): '{filename}'...")
            
            try:
                response = session.get(file_url, stream=True, headers=headers, timeout=60)
                response.raise_for_status()

                total_size = int(response.headers.get('content-length', 0))
                downloaded_size = 0
                last_update_time = time.time()

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
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
                    if os.path.exists(filepath): os.remove(filepath)
                    continue
                
                if total_size > 0:
                    self.file_progress_signal.emit(filename, (total_size, total_size))

                download_count += 1
            except requests.exceptions.RequestException as e:
                self.progress_signal.emit(f"   ❌ Failed to download '{filename}'. Error: {e}")
                if os.path.exists(filepath): os.remove(filepath)
                skip_count += 1
            except Exception as e:
                self.progress_signal.emit(f"   ❌ An unexpected error occurred with '{filename}': {e}")
                if os.path.exists(filepath): os.remove(filepath)
                skip_count += 1
        
        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(download_count, skip_count, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self.progress_signal.emit("   Cancellation signal received by Erome thread.")