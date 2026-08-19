import os
import time
from curl_cffi import requests as cffi_requests
from PySide6.QtCore import QThread, Signal

from ...core.saint2_client import fetch_saint2_data
from ...utils.proxy_utils import get_proxies_from_settings

class Saint2DownloadThread(QThread):
    """A dedicated QThread for handling saint2.su downloads."""
    progress_signal = Signal(str)
    file_progress_signal = Signal(str, object)
    finished_signal = Signal(int, int, bool)

    def __init__(self, url, output_dir, parent=None):
        super().__init__(parent)
        self.saint2_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self._is_paused = False
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def run(self):
        download_count = 0
        skip_count = 0
        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting Saint2.su Download for: {self.saint2_url}")
        
        album_name, files_to_download = fetch_saint2_data(self.saint2_url, self.progress_signal.emit, proxies=self.proxies)
        
        if not files_to_download:
            self.progress_signal.emit("❌ Failed to extract file information from Saint2. Aborting.")
            self.finished_signal.emit(0, 0, self.is_cancelled)
            return

        album_path = os.path.join(self.output_dir, album_name)
        os.makedirs(album_path, exist_ok=True)
        self.progress_signal.emit(f"   Saving to folder: '{album_name}'")

        session = cffi_requests.Session(impersonate="chrome120")
        if self.proxies:
            session.proxies = self.proxies

        for file_data in files_to_download:
            if self.is_cancelled:
                break
            # Pause support: block the loop while paused
            while self._is_paused and not self.is_cancelled:
                import time as _time
                _time.sleep(0.3)

            file_url = file_data.get('url')
            filename = file_data.get('filename', 'video.mp4')
            filepath = os.path.join(album_path, filename)

            if os.path.exists(filepath):
                self.progress_signal.emit(f"   -> Skip: '{filename}' already exists.")
                skip_count += 1
                continue

            try:
                headers = file_data.get('headers', {'Referer': self.saint2_url})
                req_cookies = file_data.get('cookies', {})
                
                self.progress_signal.emit(f"       -> Downloading video stream: '{filename}'...")
                
                self.progress_signal.emit(f"       -> [DEBUG] Actual Link: {file_url}")
                self.progress_signal.emit(f"       -> [DEBUG] Cookies Transferred: {len(req_cookies)} cookies found.")
                
                response = session.get(file_url, stream=True, timeout=120, headers=headers, cookies=req_cookies)
                
                content_type = response.headers.get('Content-Type', 'Unknown')
                self.progress_signal.emit(f"       -> [DEBUG] CDN Response: {response.status_code} | Content-Type: {content_type}")
                
                response.raise_for_status()

                if 'text/html' in content_type:
                    self.progress_signal.emit(f"   ❌ Blocked by CDN! Received a 42KB HTML error page instead of a video.")
                    skip_count += 1
                    continue

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
                
                if total_size > 0:
                    self.file_progress_signal.emit(filename, (total_size, total_size))

                download_count += 1
            except Exception as e:
                self.progress_signal.emit(f"   ❌ An unexpected error occurred with '{filename}': {e}")
                if os.path.exists(filepath): os.remove(filepath)
                skip_count += 1
        
        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(download_count, skip_count, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self._is_paused = False
        self.progress_signal.emit("   Cancellation signal received by Saint2 thread...")

    def pause(self):
        self._is_paused = True
        self.progress_signal.emit("   Saint2 download paused.")

    def resume(self):
        self._is_paused = False
        self.progress_signal.emit("   Saint2 download resumed.")
