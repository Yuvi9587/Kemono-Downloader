import os
import time
import threading
import urllib.parse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtCore import QThread, pyqtSignal
from ...core.coomerfans_client import CoomerfansClient
from ...utils.proxy_utils import get_proxies_from_settings

MAX_WORKERS = 2  

class CoomerfansThread(QThread):
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    overall_progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(int, int, bool, list)
    error_signal = pyqtSignal(str)

    def __init__(self, url, save_directory, main_app):
        super().__init__()
        self.url = url
        self.save_directory = save_directory
        self.main_app = main_app
        _proxies = get_proxies_from_settings(main_app.settings) if hasattr(main_app, 'settings') else None
        self.client = CoomerfansClient(proxies=_proxies)
        self.is_running = True
        self.download_count = 0
        self.skip_count = 0
        self._count_lock = threading.Lock()  
        
        self.is_rate_limited = False
        self.rate_limit_lock = threading.Lock()
        self.rate_limit_step = 0
        
        self.skip_file_size_mb = None
        if hasattr(main_app, 'skip_words_input'):
            raw_text = main_app.skip_words_input.text().strip()
            if raw_text:
                size_pattern = re.compile(r'\[(\d+)\]')
                for part in raw_text.split(','):
                    match = size_pattern.fullmatch(part.strip())
                    if match:
                        self.skip_file_size_mb = int(match.group(1))

    def log(self, message):
        if self.main_app and hasattr(self.main_app, 'log_signal'):
            self.main_app.log_signal.emit(str(message))
        else:
            self.progress_signal.emit(str(message))

    def check_pause_and_cancel(self):
        if getattr(self.main_app, 'cancellation_event', None) and self.main_app.cancellation_event.is_set():
            self.is_running = False
            return False
        pause_evt = getattr(self.main_app, 'pause_event', None)
        if pause_evt:
            while pause_evt.is_set():
                if getattr(self.main_app, 'cancellation_event', None) and self.main_app.cancellation_event.is_set():
                    self.is_running = False
                    return False
                time.sleep(0.5)
        return True

    def _smart_sleep(self, seconds):
        """Sleeps in 0.5s intervals so the user can still cancel during a wait."""
        for _ in range(int(seconds * 2)):
            if not self.check_pause_and_cancel():
                return False
            time.sleep(0.5)
        return True

    def _handle_global_rate_limit(self, item_name):
        """Safely pauses all threads when the server issues a 429 or 403."""
        with self.rate_limit_lock:
            if not self.is_rate_limited:
                self.is_rate_limited = True
                sleep_times = [30, 45, 60]
                sleep_time = sleep_times[min(self.rate_limit_step, 2)]
                self.log(f"   ⚠️ Rate limit hit on {item_name}. Pausing ALL threads for {sleep_time}s to cool down...")
                self._smart_sleep(sleep_time)
                self.rate_limit_step += 1
                self.is_rate_limited = False
                
        while self.is_rate_limited and self.is_running:
            time.sleep(0.5)

    def sanitize_folder_name(self, name):
        name = re.sub(r'[\\/:*?"<>|]', '', name)
        name = name.replace('\n', '').replace('\r', '').strip()
        return name[:100].strip()

    def run(self):
        try:
            parsed = urllib.parse.urlparse(self.url)
            paths = [p for p in parsed.path.split('/') if p]
            creator = paths[-1] if paths else "UnknownCreator"

            self.log(f"Starting Coomerfans scrape for: {creator}")
            creator_folder = os.path.join(self.save_directory, creator)
            os.makedirs(creator_folder, exist_ok=True)

            if "/p/" in self.url:
                self.log("Single post detected. Fetching media...")
                
                post_id = paths[1] if len(paths) > 1 else ""
                post_info = {'url': self.url, 'id': post_id, 'title': 'Post'}
                
                media_tasks = self._collect_post_tasks(self.url, creator_folder, post_info)
                self._run_parallel_downloads(media_tasks)
            else:
                self.log("Profile detected. Scraping all pages...")
                page = 1
                while self.is_running:
                    if not self.check_pause_and_cancel():
                        break

                    self.log(f"Scanning Page {page}...")
                    page_url = f"{self.url}?page={page}"
                    post_items = self.client.get_posts_from_page(page_url)

                    if not post_items:
                        self.log("No more posts found. Reached the end of the profile.")
                        break

                    self.log(f"Found {len(post_items)} posts on page {page}. Queuing downloads...")

                    all_tasks = []
                    for post_item in post_items:
                        if not self.check_pause_and_cancel():
                            break
                        all_tasks.extend(self._collect_post_tasks(post_item['url'], creator_folder, post_item))

                    self._run_parallel_downloads(all_tasks)
                    page += 1

            if self.is_running:
                self.log("Complete! All Coomerfans media processed.")

            self.finished_signal.emit(self.download_count, self.skip_count, not self.is_running, [])

        except Exception as e:
            self.log(f"Coomerfans Engine Error: {str(e)}")


    def _collect_post_tasks(self, post_url, folder, post_info=None):
        media_urls, page_title, post_date = self.client.get_media_from_post(post_url)

        skip_images = hasattr(self.main_app, 'radio_videos') and self.main_app.radio_videos.isChecked()
        skip_videos = hasattr(self.main_app, 'radio_images') and self.main_app.radio_images.isChecked()
        
        use_subfolder = hasattr(self.main_app, 'use_subfolder_per_post_checkbox') and self.main_app.use_subfolder_per_post_checkbox.isChecked()
        
        if use_subfolder and post_info:
            title = post_info.get('title', 'Post')
            if title == 'Post' and page_title:
                title = page_title
                
            post_id = post_info.get('id', '')
            safe_title = self.sanitize_folder_name(title)
            
            if safe_title:
                subfolder_name = f"{safe_title} [{post_id}]" if post_id else safe_title
            else:
                subfolder_name = str(post_id) if post_id else "Unknown Post"

            use_date_prefix = hasattr(self.main_app, 'date_prefix_checkbox') and self.main_app.date_prefix_checkbox.isChecked()
            if use_date_prefix and post_date:
                parts = post_date.split('-')
                if len(parts) >= 3:
                    date_format = getattr(self.main_app, 'date_prefix_format', 'YYYY-MM-DD {post}')
                    prefix_str = date_format.replace('YYYY', parts[0]).replace('MM', parts[1]).replace('DD', parts[2])
                    if '{post}' in prefix_str:
                        subfolder_name = prefix_str.replace('{post}', subfolder_name)
                    else:
                        subfolder_name = f"{prefix_str} {subfolder_name}".strip()
                else:
                    subfolder_name = f"[{post_date}] {subfolder_name}"
                    
            subfolder_name = self.sanitize_folder_name(subfolder_name)
            folder = os.path.join(folder, subfolder_name)

        rename_style = None
        if hasattr(self.main_app, 'manga_mode_checkbox') and self.main_app.manga_mode_checkbox.isChecked():
            rename_style = getattr(self.main_app, 'manga_filename_style', "post_title")
            
        post_title_str = post_info.get('title', '') if post_info else ''
        if not post_title_str and page_title:
            post_title_str = page_title
        if not post_title_str:
            post_title_str = 'Post'
            
        post_title_str = self.sanitize_folder_name(post_title_str)

        tasks = []
        for index, media_url in enumerate(media_urls, 1):
            original_file_name = media_url.split('/')[-1].split('?')[0]
            ext = os.path.splitext(original_file_name)[1]
            from ...config.constants import VIDEO_EXTENSIONS
            is_video = ext.lower() in VIDEO_EXTENSIONS
            
            if is_video and skip_videos:
                continue
            if not is_video and skip_images:
                continue

            # Default to original
            file_name = original_file_name

            # Renaming Logic
            if rename_style == "post_title":
                if len(media_urls) > 1:
                    file_name = f"{post_title_str}_{index}{ext}"
                else:
                    file_name = f"{post_title_str}{ext}"
            elif rename_style == "date_post_title":
                date_prefix = f"[{post_date}] " if post_date else ""
                if len(media_urls) > 1:
                    file_name = f"{date_prefix}{post_title_str}_{index}{ext}"
                else:
                    file_name = f"{date_prefix}{post_title_str}{ext}"
                    
            # Sanitize file name but preserve extension
            base_name, ext_part = os.path.splitext(file_name)
            safe_base = self.sanitize_folder_name(base_name)
            
            # Ensure total length doesn't exceed reasonable limits (e.g., 200 chars to be safe on Windows)
            max_base_len = 200 - len(ext_part)
            safe_base = safe_base[:max_base_len].strip()
            file_name = f"{safe_base}{ext_part}"

            save_path = os.path.join(folder, file_name)

            if os.path.exists(save_path):
                with self._count_lock:
                    self.skip_count += 1
                continue

            os.makedirs(folder, exist_ok=True)
            tasks.append((media_url, save_path))

        return tasks


    def _run_parallel_downloads(self, tasks):
        if not tasks:
            return

        self.log(f"Downloading {len(tasks)} file(s) with {MAX_WORKERS} parallel workers...")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(self.download_file, url, path): path
                       for url, path in tasks}

            for future in as_completed(futures):
                if not self.is_running:
                    for f in futures:
                        f.cancel()
                    break
                exc = future.exception()
                if exc:
                    self.log(f"Worker error: {exc}")


    def download_file(self, url, save_path):
        if not self.is_running:
            return
            
        while self.is_rate_limited and self.is_running: time.sleep(0.5)
            
        file_name = os.path.basename(save_path)
        
        response = None
        for attempt in range(4):
            try:
                res = self.client.session.get(url, headers=self.client.headers, stream=True, timeout=30)
                if res.status_code in [429, 403]:
                    self._handle_global_rate_limit(file_name)
                    continue
                res.raise_for_status()
                response = res
                break
            except Exception as e:
                if "429" in str(e) or "403" in str(e):
                    self._handle_global_rate_limit(file_name)
                    continue
                self.log(f"Failed to connect to {file_name}: {e}")
                return

        if not response or response.status_code != 200:
            return

        try:
            total_size = int(response.headers.get('content-length', 0))
            
            if self.skip_file_size_mb is not None and total_size > 0:
                total_size_mb = total_size / (1024 * 1024)
                if total_size_mb < self.skip_file_size_mb:
                    self.log(f"Skipping {file_name} (Size {total_size_mb:.2f}MB is below {self.skip_file_size_mb}MB threshold)")
                    with self._count_lock:
                        self.skip_count += 1
                    return
            
            downloaded = 0
            file_type = "Video:" if file_name.lower().endswith(('.mp4', '.webm')) else "Image:"

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.check_pause_and_cancel():
                        return
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            mb_dl = downloaded / (1024 * 1024)
                            mb_tot = total_size / (1024 * 1024)
                            self.file_progress_signal.emit(
                                file_type,
                                f"{file_name}: {percent}% ({mb_dl:.1f}MB / {mb_tot:.1f}MB)"
                            )
                            
            time.sleep(0.1)

            if self.is_running:
                self.overall_progress_signal.emit(1, 1)
                self.rate_limit_step = 0
                self.log(f"✓ {file_name} ({url})")
                with self._count_lock:
                    self.download_count += 1
                
        except Exception as e:
            self.log(f"Error saving {file_name}: {e}")

    def stop(self):
        self.is_running = False