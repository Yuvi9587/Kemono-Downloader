import os
import re
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import QThread, pyqtSignal

from ...core.bunkr_client import fetch_bunkr_data

IMG_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif')
BUNKR_IMG_THREADS = 6

class BunkrDownloadThread(QThread):
    """A dedicated QThread for handling Bunkr downloads."""
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool, list)

    def __init__(self, url, output_dir, parent=None):
        super().__init__(parent)
        self.bunkr_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        
        self.lock = threading.Lock()
        self.download_count = 0
        self.skip_count = 0
        self.file_index = 0

        class ThreadLogger:
            def __init__(self, signal_emitter):
                self.signal_emitter = signal_emitter
            def info(self, msg, *args, **kwargs):
                self.signal_emitter.emit(str(msg))
            def error(self, msg, *args, **kwargs):
                self.signal_emitter.emit(f"❌ ERROR: {msg}")
            def warning(self, msg, *args, **kwargs):
                self.signal_emitter.emit(f"⚠️ WARNING: {msg}")
            def debug(self, msg, *args, **kwargs):
                pass

        self.logger = ThreadLogger(self.progress_signal)

    def _download_file(self, file_data, total_files, album_path, is_image_task=False):
        """
        A thread-safe method to download a single file.
        This function will be called by the main thread (for videos) 
        and worker threads (for images).
        """
        
        if self.is_cancelled:
            return

        with self.lock:
            self.file_index += 1
            current_file_num = self.file_index
        
        try:
            filename = file_data.get('name', 'untitled_file')
            file_url = file_data.get('url')
            headers = file_data.get('_http_headers')
            
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename).strip()
            filepath = os.path.join(album_path, filename)
            
            if os.path.exists(filepath):
                self.progress_signal.emit(f"   -> Skip ({current_file_num}/{total_files}): '{filename}' already exists.")
                with self.lock:
                    self.skip_count += 1
                return

            self.progress_signal.emit(f"   Downloading ({current_file_num}/{total_files}): '{filename}'...")
            
            from curl_cffi import requests as cffi_requests
            session = cffi_requests.Session(impersonate="chrome120")
            
            if headers and 'User-Agent' in headers:
                headers = dict(headers)
                headers.pop('User-Agent')
                
            response = session.get(file_url, stream=True, headers=headers, timeout=60)
            
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                self.progress_signal.emit(f"   ❌ Blocked by CDN! Downloaded a 42KB HTML page instead of the video.")
                if os.path.exists(filepath): os.remove(filepath)
                with self.lock: self.skip_count += 1
                return
                
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
                        
                        if not is_image_task:
                            current_time = time.time()
                            if total_size > 0 and (current_time - last_update_time) > 0.5:
                                self.file_progress_signal.emit(filename, (downloaded_size, total_size))
                                last_update_time = current_time
            
            if self.is_cancelled:
                self.progress_signal.emit(f"   Download cancelled for '{filename}'.")
                if os.path.exists(filepath): os.remove(filepath)
                return

            if total_size > 0:
                self.file_progress_signal.emit(filename, (total_size, total_size))
            
            with self.lock:
                self.download_count += 1

        except requests.exceptions.RequestException as e:
            self.progress_signal.emit(f"   ❌ Failed to download '{filename}'. Error: {e}")
            if os.path.exists(filepath): os.remove(filepath)
            with self.lock:
                self.skip_count += 1
        except Exception as e:
            self.progress_signal.emit(f"   ❌ An unexpected error occurred with '{filename}': {e}")
            if os.path.exists(filepath): os.remove(filepath)
            with self.lock:
                self.skip_count += 1

    def run(self):
        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting Bunkr Download for: {self.bunkr_url}")
        
        album_name, files_to_download = fetch_bunkr_data(self.bunkr_url, self.logger)
        
        if not files_to_download:
            self.progress_signal.emit("❌ Failed to extract file information from Bunkr. Aborting.")
            self.finished_signal.emit(0, 0, self.is_cancelled, [])
            return

        album_path = os.path.join(self.output_dir, album_name)
        try:
            os.makedirs(album_path, exist_ok=True)
            self.progress_signal.emit(f"   Saving to folder: '{album_path}'")
        except OSError as e:
            self.progress_signal.emit(f"❌ Critical error creating directory: {e}")
            self.finished_signal.emit(0, len(files_to_download), self.is_cancelled, [])
            return

        total_files = len(files_to_download)
        
        image_files = []
        other_files = []
        for f in files_to_download:
            name = f.get('name', '').lower()
            if name.endswith(IMG_EXTS):
                image_files.append(f)
            else:
                other_files.append(f)
        
        self.progress_signal.emit(f"   Found {len(image_files)} images and {len(other_files)} other files.")

        if other_files:
            self.progress_signal.emit(f"   Downloading {len(other_files)} videos/other files sequentially...")
            for file_data in other_files:
                if self.is_cancelled:
                    break
                self._download_file(file_data, total_files, album_path, is_image_task=False)

        if image_files and not self.is_cancelled:
            self.progress_signal.emit(f"   Downloading {len(image_files)} images concurrently ({BUNKR_IMG_THREADS} threads)...")
            with ThreadPoolExecutor(max_workers=BUNKR_IMG_THREADS, thread_name_prefix='BunkrImg') as executor:
                
                futures = {executor.submit(self._download_file, file_data, total_files, album_path, is_image_task=True): file_data for file_data in image_files}
                
                try:
                    for future in futures:
                        if self.is_cancelled:
                            future.cancel()
                        else:
                            future.result()
                except Exception as e:
                    self.progress_signal.emit(f"   ❌ A thread pool error occurred: {e}")

        if self.is_cancelled:
            self.progress_signal.emit("   Download cancelled by user.")
            self.skip_count = total_files - self.download_count
        
        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(self.download_count, self.skip_count, self.is_cancelled, [])

    def cancel(self):
        self.is_cancelled = True
        self.progress_signal.emit("   Cancellation signal received by Bunkr thread.")