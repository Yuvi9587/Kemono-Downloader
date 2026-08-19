import os
import time
import threading
import subprocess
import zipfile
import shutil
import requests
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from PySide6.QtCore import QThread, Signal
from ...core.hotleaks_client import HotleaksClient
from ...utils.proxy_utils import get_proxies_from_settings

MAX_WORKERS = 2  

class HotleaksThread(QThread):
    progress_signal = Signal(str)
    file_progress_signal = Signal(str, object)
    overall_progress_signal = Signal(int, int)
    finished_signal = Signal(int, int, bool, list)
    error_signal = Signal(str)

    def __init__(self, url, save_directory, main_app, export_all_links_mode=False):
        super().__init__(main_app)
        self.export_all_links_mode = export_all_links_mode
        self.url = url
        self.save_directory = save_directory
        self.main_app = main_app
        _proxies = get_proxies_from_settings(main_app.settings) if hasattr(main_app, 'settings') else None
        self.client = HotleaksClient(proxies=_proxies)
        self.is_running = True
        self.download_count = 0
        self.skip_count = 0
        self._count_lock = threading.Lock() 
        
        self.is_rate_limited = False
        self.rate_limit_lock = threading.Lock()

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
                self.log(f"   ⚠️ IP Ban/Rate limit hit on {item_name}. Pausing ALL threads for 30s to cool down...")
                self._smart_sleep(30)
                self.is_rate_limited = False
                
        while self.is_rate_limited and self.is_running:
            time.sleep(0.5)


    def ensure_ffmpeg(self):
        ffmpeg_path = os.path.join(self.main_app.app_base_dir, "ffmpeg.exe")
        if os.path.exists(ffmpeg_path):
            return True

        self.log("⚙️ FFmpeg not found. Downloading the video engine (this only happens once)...")
        zip_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        zip_path = os.path.join(self.main_app.app_base_dir, "ffmpeg_temp.zip")

        try:
            response = requests.get(zip_url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.check_pause_and_cancel():
                        return False
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            mb_dl = downloaded / (1024 * 1024)
                            mb_tot = total_size / (1024 * 1024)
                            self.file_progress_signal.emit("Setup:", f"Downloading FFmpeg: {percent}% ({mb_dl:.1f}MB / {mb_tot:.1f}MB)")

            self.log("📦 Extracting FFmpeg...")
            self.file_progress_signal.emit("Setup:", "Extracting FFmpeg...")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                ffmpeg_zip_path = next(
                    (name for name in zip_ref.namelist() if name.endswith('bin/ffmpeg.exe')), None
                )
                if not ffmpeg_zip_path:
                    raise Exception("Could not find ffmpeg.exe inside the downloaded ZIP.")
                with zip_ref.open(ffmpeg_zip_path) as source, open(ffmpeg_path, 'wb') as target:
                    shutil.copyfileobj(source, target)

            self.log("✅ FFmpeg installed successfully! Cleaning up temp files...")
            os.remove(zip_path)
            self.file_progress_signal.emit("Setup:", "FFmpeg Ready!")
            return True

        except Exception as e:
            self.log(f"❌ Failed to download FFmpeg: {e}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            return False


    def run(self):
        try:
            if not self.ensure_ffmpeg():
                self.finished_signal.emit(0, 0, True, [])
                return

            parsed = urllib.parse.urlparse(self.url)
            paths = [p for p in parsed.path.split('/') if p]

            if not paths:
                self.log("❌ Invalid Hotleaks URL.")
                self.finished_signal.emit(0, 0, False, [])
                return

            creator = paths[0]
            target_type = 'all'
            target_id = None

            if len(paths) >= 2:
                if 'photo' in paths[1].lower() or 'image' in paths[1].lower():
                    target_type = 0
                elif 'video' in paths[1].lower():
                    target_type = 1

            if len(paths) >= 3:
                target_id = str(paths[2])

            mode_text = "All Content"
            if target_type == 0: mode_text = "Photos Only"
            elif target_type == 1: mode_text = "Videos Only"
            if target_id: mode_text = f"Specific Post ({target_id})"

            self.log(f"Starting scrape for Hotleaks creator: {creator}")
            self.log(f"Mode: {mode_text}")

            creator_folder = os.path.join(self.save_directory, creator)
            os.makedirs(creator_folder, exist_ok=True)

            page = 1
            while self.is_running:
                if not self.check_pause_and_cancel():
                    break

                if not target_id:
                    self.log(f"Fetching API Page {page}...")

                api_url = f"{self.client.base_url}/{creator}?page={page}"
                response = self.client.session.get(api_url, headers=self.client.headers)

                if response.status_code != 200:
                    self.log(f"Server returned {response.status_code}. Stopping pagination.")
                    break

                posts = response.json()
                if not posts:
                    if not target_id:
                        self.log("Reached the end of the profile.")
                    else:
                        self.log(f"Could not find post {target_id} on this profile.")
                    break

                image_tasks = []   
                video_tasks = []   
                found_target = False

                for post in posts:
                    if not self.is_running: break

                    post_id = str(post.get('id'))
                    post_type = post.get('type')

                    if target_id and post_id != target_id: continue
                    if target_type != 'all' and post_type != target_type: continue

                    if post_type == 0:
                        post_url = f"{self.client.base_url}/{creator}/photo/{post_id}"
                        image_tasks.append((post_id, post_url))
                    elif post_type == 1:
                        encrypted_url = post.get('stream_url_play')
                        m3u8_url = self.client.decode_video_url(encrypted_url)
                        if m3u8_url:
                            video_tasks.append((m3u8_url, post_id))

                    if target_id and post_id == target_id:
                        found_target = True
                        break

                if image_tasks:
                    self.log(f"Downloading {len(image_tasks)} image(s) with {MAX_WORKERS} workers...")
                    self._run_image_tasks(image_tasks, creator_folder)

                if video_tasks:
                    self.log(f"Downloading {len(video_tasks)} video(s) with {MAX_WORKERS} workers...")
                    self._run_video_tasks(video_tasks, creator_folder)

                if found_target:
                    self.log(f"Target post {target_id} processed successfully.")
                    self.is_running = False
                    break

                page += 1

            if self.is_running or (target_id and not self.is_running):
                self.log("Complete! All Hotleaks items processed.")

            is_cancelled = (not self.is_running) if not target_id else False
            self.finished_signal.emit(self.download_count, self.skip_count, is_cancelled, [])

        except Exception as e:
            self.log(f"Hotleaks Engine Error: {str(e)}")


    def _run_image_tasks(self, tasks, creator_folder):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._download_image_post, post_id, post_url, creator_folder): post_id
                for post_id, post_url in tasks
            }
            for future in as_completed(futures):
                if not self.is_running:
                    for f in futures: f.cancel()
                    break

    def _run_video_tasks(self, tasks, creator_folder):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(self.download_video, m3u8_url, post_id, creator_folder): post_id
                for m3u8_url, post_id in tasks
            }
            for future in as_completed(futures):
                if not self.is_running:
                    for f in futures: f.cancel()
                    break


    def _download_image_post(self, post_id, post_url, creator_folder):
        if not self.is_running: return

        while self.is_rate_limited and self.is_running: time.sleep(0.5)

        self.log(f"Fetching image post: {post_id}")
        
        post_html = None
        for attempt in range(4):
            res = self.client.session.get(post_url, headers=self.client.headers)
            if res.status_code in [429, 403]:
                self._handle_global_rate_limit(f"image {post_id}")
                continue
            post_html = res.text
            break
            
        if not post_html: return

        soup = BeautifulSoup(post_html, 'html.parser')
        photo_div = soup.find('div', class_='photo-detail')
        if not photo_div: return

        img_tag = photo_div.find('img', class_='thumbnail')
        if not (img_tag and 'src' in img_tag.attrs): return

        image_url = img_tag['src']
        file_name = image_url.split('/')[-1].split('?')[0]
        save_path = os.path.join(creator_folder, file_name)

        if os.path.exists(save_path):
            with self._count_lock: self.skip_count += 1
            return

        if getattr(self, 'export_all_links_mode', False):
            export_file_path = os.path.join(self.save_directory, "all_file_links.txt")
            try:
                with open(export_file_path, "a", encoding="utf-8") as f:
                    f.write(image_url + "\n")
                self.log(f"📋 Exported link: {image_url}")
                with self._count_lock: self.download_count += 1
            except Exception as e:
                pass
            return

        self.log(f"Downloading image: {file_name}")
        
        img_res = None
        for attempt in range(4):
            img_res = self.client.session.get(image_url, headers=self.client.headers, stream=True)
            if img_res.status_code in [429, 403]:
                self._handle_global_rate_limit(f"download {file_name}")
                continue
            break
            
        if not img_res or img_res.status_code != 200: return

        total_size = int(img_res.headers.get('content-length', 0))
        downloaded = 0

        with open(save_path, 'wb') as f:
            for chunk in img_res.iter_content(chunk_size=8192):
                if not self.check_pause_and_cancel(): return
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        mb_dl = downloaded / (1024 * 1024)
                        mb_tot = total_size / (1024 * 1024)
                        self.file_progress_signal.emit("Image:", f"{file_name}: {percent}% ({mb_dl:.1f}MB / {mb_tot:.1f}MB)")

        if self.is_running:
            self.overall_progress_signal.emit(1, 1)
            with self._count_lock: self.download_count += 1

    def download_video(self, m3u8_url, post_id, folder):
        if not self.is_running: return

        output_ts = os.path.join(folder, f"{post_id}.ts")
        output_mp4 = os.path.join(folder, f"{post_id}.mp4")

        if os.path.exists(output_mp4):
            with self._count_lock: self.skip_count += 1
            return

        while self.is_rate_limited and self.is_running: time.sleep(0.5)

        if getattr(self, 'export_all_links_mode', False):
            export_file_path = os.path.join(self.save_directory, "all_file_links.txt")
            try:
                with open(export_file_path, "a", encoding="utf-8") as f:
                    f.write(m3u8_url + "\n")
                self.log(f"📋 Exported link: {m3u8_url}")
                with self._count_lock: self.download_count += 1
            except Exception as e:
                pass
            return

        self.log(f"Starting FFMPEG download for video: {post_id}")
        
        response = None
        for attempt in range(4):
            response = self.client.session.get(m3u8_url, headers=self.client.headers)
            if response.status_code in [429, 403]:
                self._handle_global_rate_limit(f"stream {post_id}")
                continue
            elif response.status_code != 200:
                self.log(f"   ❌ Blocked on stream {post_id}. Status Code: {response.status_code}")
                return
            break
            
        if not response or response.status_code != 200: return

        media_urls = []
        for line in response.text.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                if not line.startswith('http'):
                    base_url = m3u8_url.split('?')[0].rsplit('/', 1)[0]
                    query = m3u8_url.split('?')[1] if '?' in m3u8_url else ""
                    line = f"{base_url}/{line}?{query}" if query else f"{base_url}/{line}"
                media_urls.append(line)

        if media_urls and '.m3u8' in media_urls[-1]:
            return self.download_video(media_urls[-1], post_id, folder)

        self.log(f"Downloading {len(media_urls)} chunks for {post_id}...")
        with open(output_ts, 'wb') as f:
            for i, chunk_url in enumerate(media_urls):
                if not self.check_pause_and_cancel(): return
                
                chunk_res = None
                for chunk_attempt in range(4):
                    chunk_res = self.client.session.get(chunk_url, headers=self.client.headers)
                    if chunk_res.status_code in [429, 403]:
                        self._handle_global_rate_limit(f"chunk {i+1} of {post_id}")
                        continue
                    break
                
                if chunk_res and chunk_res.status_code == 200:
                    f.write(chunk_res.content)
                    percent = int(((i + 1) / len(media_urls)) * 100)
                    self.file_progress_signal.emit("Native HLS:", f"{post_id}: {percent}% (Chunk {i+1}/{len(media_urls)})")
                    
                    time.sleep(0.05)
                else:
                    self.log(f"   ❌ Failed chunk {i+1} for {post_id}. Video may be corrupt.")

        if not self.is_running: return

        self.log(f"Remuxing: {post_id}.mp4...")
        self.file_progress_signal.emit("FFmpeg:", f"Converting {post_id} to .mp4...")

        ffmpeg_path = os.path.join(self.main_app.app_base_dir, "ffmpeg.exe")
        try:
            subprocess.run(
                [ffmpeg_path, "-y", "-i", output_ts, "-c", "copy", "-bsf:a", "aac_adtstoasc", output_mp4],
                check=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if os.path.exists(output_mp4):
                os.remove(output_ts)
                self.log(f"✓ {post_id}.mp4")
                self.file_progress_signal.emit("Done:", f"{post_id}.mp4 saved!")
                self.overall_progress_signal.emit(1, 1)
                with self._count_lock:
                    self.download_count += 1
        except Exception as e:
            self.log(f"Remux failed, stream retained as raw video: {post_id}.ts")