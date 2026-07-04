import os
import time
import requests
import re
import random
from datetime import datetime
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    imagehash = None
    IMAGEHASH_AVAILABLE = False
from PyQt5.QtCore import QThread, pyqtSignal

from PIL import Image
from ...core.database_manager import DatabaseManager

from ...core.deviantart_client import DeviantArtClient
from ...utils.file_utils import clean_folder_name

class DeviantArtDownloadThread(QThread):
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    overall_progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(int, int, bool, list)

    def __init__(self, url, output_dir, pause_event, cancellation_event, parent=None, proxies=None):
        super().__init__(parent)
        self.url = url
        self.output_dir = output_dir
        self.pause_event = pause_event
        self.cancellation_event = cancellation_event
        self.proxies = proxies
                
        self.parent_app = parent 
        self.download_count = 0
        self.skip_count = 0
        
        self.db = DatabaseManager()

    def _check_pause_cancel(self):
        if getattr(self, 'is_cancelled', False) or (self.cancellation_event and self.cancellation_event.is_set()):
            self.is_cancelled = True
            return True
            
        if self.pause_event and self.pause_event.is_set():
            self.progress_signal.emit("   Download paused...")
            
            while self.pause_event.is_set():
                if getattr(self, 'is_cancelled', False) or (self.cancellation_event and self.cancellation_event.is_set()):
                    self.is_cancelled = True
                    return True
                time.sleep(0.5)
                
            self.progress_signal.emit("   Download resumed.")
            
        return getattr(self, 'is_cancelled', False)

    def _smart_sleep(self, seconds):
        for _ in range(int(seconds * 10)):
            if self._check_pause_cancel(): return True
            time.sleep(0.1)
        return False

    def run(self):
        self.is_cancelled = False
        self.client = DeviantArtClient(
            logger_func=self.progress_signal.emit, 
            check_pause_func=self._check_pause_cancel, 
            proxies=self.proxies
        )

        if self.proxies:
             self.progress_signal.emit(f"   🌍 Network: Using Proxy {self.proxies}")
        else:
             self.progress_signal.emit("   🌍 Network: Direct Connection")

        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting DeviantArt download for: {self.url}")
        
        try:
            if not self.client.authenticate():
                self.progress_signal.emit("❌ Failed to authenticate with DeviantArt API.")
                self.finished_signal.emit(0, 0, True, [])
                return

            mode, username, _ = self.client.extract_info_from_url(self.url)
            
            if mode == 'post':
                self._process_single_post(self.url)
            elif mode == 'gallery':
                self._process_gallery(username)
            else:
                self.progress_signal.emit("❌ Could not parse DeviantArt URL type.")
                
        except Exception as e:
            self.progress_signal.emit(f"❌ Error during download: {e}")
            self.skip_count += 1
        finally:
            self.finished_signal.emit(self.download_count, self.skip_count, self.cancellation_event.is_set(), [])

    def _check_pause_cancel(self):
        if self.cancellation_event.is_set(): return True
        while self.pause_event.is_set():
            time.sleep(0.5)
            if self.cancellation_event.is_set(): return True
        return False

    def _process_single_post(self, url):
        self.progress_signal.emit(f"   Fetching deviation info...")
        uuid = self.client.get_deviation_uuid(url)
        if not uuid:
            self.progress_signal.emit("❌ Could not find Deviation UUID.")
            self.skip_count += 1
            return

        meta = self.client._api_call(f"/deviation/{uuid}")
        content = self.client.get_deviation_content(uuid)
        if not content:
            self.progress_signal.emit("❌ Could not retrieve download URL.")
            self.skip_count += 1
            return

        self._download_file(content['src'], meta)

    def _process_gallery(self, username):
        self.progress_signal.emit(f"   Fetching gallery for user: {username}...")
        offset = 0
        has_more = True
        
        base_folder = os.path.join(self.output_dir, clean_folder_name(username))
        if not os.path.exists(base_folder):
            os.makedirs(base_folder, exist_ok=True)

        while has_more:
            if self._check_pause_cancel(): break

            data = self.client.get_gallery_folder(username, offset=offset)
            results = data.get('results', [])
            has_more = data.get('has_more', False)
            offset = data.get('next_offset')

            if not results: break

            for deviation in results:
                if self._check_pause_cancel(): break
                self._process_deviation_task(deviation, base_folder)
                
                time.sleep(random.uniform(0.5, 1.2))

            time.sleep(1) 

    def _process_deviation_task(self, deviation, base_folder):
        if self._check_pause_cancel(): return

        dev_id = deviation.get('deviationid')
        title = deviation.get('title', 'Unknown')

        try:
            content = self.client.get_deviation_content(dev_id)
            if content:
                self._download_file(content['src'], deviation, override_dir=base_folder)
            else:
                self.skip_count += 1
        except Exception as e:
            self.progress_signal.emit(f"   ❌ Error processing {title}: {e}")
            self.skip_count += 1

    def _format_date(self, timestamp):
        if not timestamp: return "NoDate"
        try:
            fmt_setting = self.parent_app.manga_custom_date_format
            strftime_fmt = fmt_setting.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
            dt_obj = datetime.fromtimestamp(int(timestamp))
            return dt_obj.strftime(strftime_fmt)
        except Exception:
            return "InvalidDate"

    def _download_file(self, file_url, metadata, override_dir=None):
        if self._check_pause_cancel(): return

        parsed = requests.utils.urlparse(file_url)
        path_filename = os.path.basename(parsed.path)
        if '?' in path_filename: path_filename = path_filename.split('?')[0]
        _, ext = os.path.splitext(path_filename)

        title = metadata.get('title', 'Untitled')
        safe_title = clean_folder_name(title)
        if not safe_title: safe_title = "Untitled"
        
        final_filename = f"{safe_title}{ext}"

        if self.parent_app and self.parent_app.manga_mode_checkbox.isChecked():
            try:
                creator_name = metadata.get('author', {}).get('username', 'Unknown')
                published_ts = metadata.get('published_time')
                
                fmt_data = {
                    "creator_name": creator_name,
                    "title": title,
                    "published": self._format_date(published_ts),
                    "added": self._format_date(published_ts),
                    "edited": self._format_date(published_ts),
                    "id": metadata.get('deviationid', ''),
                    "service": "deviantart",
                    "name": safe_title 
                }

                custom_fmt = self.parent_app.custom_manga_filename_format
                new_name = custom_fmt.format(**fmt_data)
                final_filename = f"{clean_folder_name(new_name)}{ext}"
                
            except Exception as e:
                pass 

        save_dir = override_dir if override_dir else self.output_dir
        if not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir, exist_ok=True)
            except OSError: pass

        filepath = os.path.join(save_dir, final_filename)

        if os.path.exists(filepath):
            return

        try:
            self.progress_signal.emit(f"   ⬇️ Downloading: {final_filename}")
            
            timeout_val = (30, 120) if self.proxies else 30
            
            with requests.get(file_url, stream=True, timeout=timeout_val, proxies=self.proxies, verify=False) as r:
                r.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if self._check_pause_cancel():
                            f.close()
                            os.remove(filepath)
                            return
                        if chunk:
                            f.write(chunk)
            
            calculated_phash = None
            valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
            if ext.lower() in valid_exts:
                try:
                    calculated_phash = str(imagehash.phash(Image.open(filepath), hash_size=16))
                except Exception:
                    pass
            self.db.record_tagless_download(
                file_path=filepath,
                file_name=final_filename,
                file_hash=None,
                phash=calculated_phash
            )

            self.download_count += 1
            
        except Exception as e:
            self.progress_signal.emit(f"   ❌ Download failed: {e}")
            self.skip_count += 1