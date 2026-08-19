import os
import time
import requests 
from PySide6.QtCore import QThread, Signal

from ...utils.file_utils import clean_folder_name
from ...core.database_manager import DatabaseManager


class NhentaiDownloadThread(QThread):
    progress_signal = Signal(str)
    file_progress_signal = Signal(str, object)
    finished_signal = Signal(int, int, bool)
    overall_progress_signal = Signal(int, int)

    IMAGE_SERVERS = [
        "https://i.nhentai.net", "https://i2.nhentai.net", "https://i3.nhentai.net",
        "https://i5.nhentai.net", "https://i7.nhentai.net"
    ]
    
    EXTENSION_MAP = {'j': 'jpg', 'p': 'png', 'g': 'gif', 'w': 'webp' }

    def __init__(self, gallery_data, output_dir, parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.gallery_data = gallery_data
        self.output_dir = output_dir
        self.is_cancelled = False
        self._is_paused = False
        self.proxies = None
        self.db = DatabaseManager()

    def run(self):
        if self.proxies:
            self.progress_signal.emit(f"   🌍 Network: Using Proxy {self.proxies}")
        else:
            self.progress_signal.emit("   🌍 Network: Direct Connection (No Proxy)")

        title = self.gallery_data.get("title", {}).get("english", f"gallery_{self.gallery_data.get('id')}")
        gallery_id = self.gallery_data.get("id")
        media_id = self.gallery_data.get("media_id")
        pages_info = self.gallery_data.get("pages", [])

        folder_name = clean_folder_name(title)
        save_path = os.path.join(self.output_dir, folder_name)
        
        try:
            os.makedirs(save_path, exist_ok=True)
            self.progress_signal.emit(f"   Saving to: {folder_name}")
        except Exception as e:
            self.progress_signal.emit(f"   ❌ Error creating directory: {e}")
            self.finished_signal.emit(0, len(pages_info), False)
            return

        download_count = 0
        skip_count = 0
        total_pages = len(pages_info)
        
        db_gallery_id = f"nhentai_{gallery_id}"
        if self.db.check_manga_exists(db_gallery_id):
            self.progress_signal.emit("   ✅ Gallery already in database. Skipping download.")
            self.finished_signal.emit(0, total_pages, False)
            return

        artist_name = None
        tags_list = []
        for tag_info in self.gallery_data.get('tags', []):
            tag_type = tag_info.get('type')
            tag_name = tag_info.get('name')
            if not tag_name:
                continue
            if tag_type == 'artist':
                if artist_name:
                    artist_name += f", {tag_name}"
                else:
                    artist_name = tag_name
            else:
                tags_list.append(tag_name)

        scraper = requests.Session()
        
        img_timeout = (30, 120) if self.proxies else 60


        if self.export_all_links_mode:
            self.progress_signal.emit(f"📋 Export All Links Mode: Extracting links for nHentai Gallery {gallery_id}...")
            export_file_path = os.path.join(self.output_dir, "all_file_links.txt")
            extracted_links = []
            
            for i, page_data in enumerate(pages_info):
                page_path = page_data.get('path', '')
                full_url = f"https://i.nhentai.net/{page_path}"
                extracted_links.append(full_url)
            
            try:
                with open(export_file_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# nHentai Gallery: {title} ({gallery_id})\n")
                    for link in extracted_links:
                        f.write(link + "\n")
                self.progress_signal.emit(f"✅ Exported {len(extracted_links)} links to {export_file_path}")
            except Exception as e:
                self.progress_signal.emit(f"❌ Failed to write links to {export_file_path}: {e}")
                
            self.finished_signal.emit(len(extracted_links), 0, False)
            return

        for i, page_data in enumerate(pages_info):
            if self.is_cancelled: break
            # Pause support
            while self._is_paused and not self.is_cancelled:
                import time as _time
                _time.sleep(0.3)
            
            page_path = page_data.get('path', '')
            
            file_ext = page_path.split('.')[-1] if '.' in page_path else 'jpg'
            
            local_filename = f"{i+1:03d}.{file_ext}"
            filepath = os.path.join(save_path, local_filename)

            if os.path.exists(filepath):
                self.progress_signal.emit(f"   Skipping {local_filename} (already exists).")
                skip_count += 1
                continue

            download_successful = False
            
            for server in self.IMAGE_SERVERS:
                if self.is_cancelled: break
                
                full_url = f"{server}/{page_path}"
                
                try:
                    self.progress_signal.emit(f"   Downloading page {i+1}/{total_pages}: {local_filename}...")
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Referer': f'https://nhentai.net/g/{gallery_id}/'
                    }

                    response = scraper.get(full_url, headers=headers, timeout=img_timeout, stream=True, proxies=self.proxies, verify=False)
                    
                    if response.status_code == 200:
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded_size = 0
                        last_update_time = time.time()
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if self.is_cancelled: break
                                while self._is_paused and not self.is_cancelled:
                                    import time as _time; _time.sleep(0.3)
                                if chunk:
                                    f.write(chunk)
                                    downloaded_size += len(chunk)
                                    current_time = time.time()
                                    if current_time - last_update_time > 0.5:
                                        self.file_progress_signal.emit(local_filename, (downloaded_size, total_size))
                                        last_update_time = current_time
                        if not self.is_cancelled:
                            self.file_progress_signal.emit(local_filename, (downloaded_size, total_size))
                            download_count += 1
                            download_successful = True
                        else:
                            if os.path.exists(filepath): os.remove(filepath)
                        break
                        
                except Exception as e:
                    self.progress_signal.emit(f"   ⚠️ Server {server} failed for page {i+1}: {e}")
            
            if not download_successful:
                self.progress_signal.emit(f"   ❌ Failed to download {local_filename} from all servers.")
                skip_count += 1

            # Emit overall page progress after each page attempt
            self.overall_progress_signal.emit(total_pages, i + 1)
            time.sleep(0.5)

        if not self.is_cancelled and download_count + skip_count == total_pages and total_pages > 0:
            self.db.record_manga_download(db_gallery_id, "nhentai", title, save_path, artist=artist_name, tags_list=tags_list)

        self.file_progress_signal.emit("", None)
        self.finished_signal.emit(download_count, skip_count, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self._is_paused = False

    def pause(self):
        self._is_paused = True
        self.progress_signal.emit("   Nhentai download paused.")

    def resume(self):
        self._is_paused = False
        self.progress_signal.emit("   Nhentai download resumed.")
