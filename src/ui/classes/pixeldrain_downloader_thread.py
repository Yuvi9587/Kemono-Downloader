import os
import time
import requests
import cloudscraper
from PyQt5.QtCore import QThread, pyqtSignal

from ...core.pixeldrain_client import fetch_pixeldrain_data
from ...utils.file_utils import clean_folder_name
from ...utils.proxy_utils import get_proxies_from_settings


class PixeldrainDownloadThread(QThread):
    """A dedicated QThread for handling pixeldrain.com downloads."""
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool)

    def __init__(self, url, output_dir, parent=None):
        super().__init__(parent)
        self.pixeldrain_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self._is_paused = False
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def run(self):
        download_count = 0
        skip_count = 0
        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting Pixeldrain.com Download for: {self.pixeldrain_url}")

        album_title_raw, files_to_download = fetch_pixeldrain_data(self.pixeldrain_url, self.progress_signal.emit, proxies=self.proxies)

        if not files_to_download:
            self.progress_signal.emit("❌ Failed to extract file information from Pixeldrain. Aborting.")
            self.finished_signal.emit(0, 0, self.is_cancelled)
            return

        album_folder_name = clean_folder_name(album_title_raw)
        album_path = os.path.join(self.output_dir, album_folder_name)
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
            # Pause support
            while self._is_paused and not self.is_cancelled:
                import time as _time
                _time.sleep(0.3)

            filename = file_data.get('filename')
            file_url = file_data.get('url')
            filepath = os.path.join(album_path, filename)

            if os.path.exists(filepath):
                self.progress_signal.emit(f"   -> Skip ({i+1}/{total_files}): '{filename}' already exists.")
                skip_count += 1
                continue

            self.progress_signal.emit(f"   Downloading ({i+1}/{total_files}): '{filename}'...")

            try:
                response = session.get(file_url, stream=True, timeout=90)
                response.raise_for_status()

                total_size = int(response.headers.get('content-length', 0))
                downloaded_size = 0
                last_update_time = time.time()

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.is_cancelled:
                            break
                        # Pause support: block chunk writing while paused
                        while self._is_paused and not self.is_cancelled:
                            import time as _time
                            _time.sleep(0.3)
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

                download_count += 1
            except requests.exceptions.RequestException as e:
                self.progress_signal.emit(f"   ❌ Failed to download '{filename}'. Error: {e}")
                if os.path.exists(filepath): os.remove(filepath)
                skip_count += 1

        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(download_count, skip_count, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self._is_paused = False
        self.progress_signal.emit("   Cancellation signal received by Pixeldrain thread.")

    def pause(self):
        self._is_paused = True
        self.progress_signal.emit("   Pixeldrain download paused.")

    def resume(self):
        self._is_paused = False
        self.progress_signal.emit("   Pixeldrain download resumed.")