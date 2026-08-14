import os
import time
import requests
from PyQt5.QtCore import QThread, pyqtSignal
from ...core.hentaifox_client import get_gallery_metadata, get_image_link_for_page, get_gallery_id
from ...utils.file_utils import clean_folder_name
from ...core.database_manager import DatabaseManager
from ...utils.proxy_utils import get_proxies_from_settings

class HentaiFoxDownloadThread(QThread):
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool, list)
    overall_progress_signal = pyqtSignal(int, int)

    def __init__(self, url_or_id, output_dir, parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.gallery_id = get_gallery_id(url_or_id)
        self.output_dir = output_dir
        self.is_running = True
        self.downloaded_count = 0
        self.skipped_count = 0
        self.db = DatabaseManager()
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def run(self):
        try:
            db_gallery_id = f"hentaifox_{self.gallery_id}"
            if self.db.check_manga_exists(db_gallery_id):
                self.progress_signal.emit("✅ Gallery already in database. Skipping download.")
                self.finished_signal.emit(0, 0, False, [])
                return

            self.progress_signal.emit(f"🔍 [HentaiFox] Fetching metadata for ID: {self.gallery_id}...")
            
            try:
                data = get_gallery_metadata(self.gallery_id, proxies=self.proxies)
            except Exception as e:
                self.progress_signal.emit(f"❌ [HentaiFox] Failed to fetch metadata: {e}")
                self.finished_signal.emit(0, 0, False, [])
                return

            title = clean_folder_name(data['title'])
            total_pages = data['total_pages']
            tags = data.get('tags', [])
            artist = data.get('artist')
            
            if self.export_all_links_mode:
                self.progress_signal.emit(f"📋 Export All Links Mode: Extracting links for HentaiFox {self.gallery_id}...")
                export_file_path = os.path.join(self.output_dir, "all_file_links.txt")
                extracted_links = []
                
                for i in range(1, total_pages + 1):
                    if not self.is_running: break
                    img_url = get_image_link_for_page(self.gallery_id, i, proxies=self.proxies)
                    if img_url:
                        extracted_links.append(img_url)
                    time.sleep(0.1)
                
                try:
                    with open(export_file_path, "a", encoding="utf-8") as f:
                        f.write(f"\n# HentaiFox Gallery: {title} ({self.gallery_id})\n")
                        for link in extracted_links:
                            f.write(link + "\n")
                    self.progress_signal.emit(f"✅ Exported {len(extracted_links)} links to {export_file_path}")
                except Exception as e:
                    self.progress_signal.emit(f"❌ Failed to write links to {export_file_path}: {e}")
                    
                self.finished_signal.emit(len(extracted_links), 0, False, [])
                return

            save_folder = os.path.join(self.output_dir, f"[{self.gallery_id}] {title}")
            os.makedirs(save_folder, exist_ok=True)
            
            self.progress_signal.emit(f"📂 Saving to: {save_folder}")
            self.progress_signal.emit(f"📄 Found {total_pages} pages. Starting download...")

            for i in range(1, total_pages + 1):
                if not self.is_running: 
                    self.progress_signal.emit("🛑 Download cancelled by user.")
                    break
                
                try:
                    img_url = get_image_link_for_page(self.gallery_id, i, proxies=self.proxies)
                    
                    if img_url:
                        ext = img_url.split('.')[-1]
                        filename = f"{i:03d}.{ext}"
                        filepath = os.path.join(save_folder, filename)
                        
                        if os.path.exists(filepath):
                            self.progress_signal.emit(f"⚠️ [{i}/{total_pages}] Skipped (Exists): {filename}")
                            self.skipped_count += 1
                        else:
                            self.progress_signal.emit(f"⬇️ [{i}/{total_pages}] Downloading: {filename}")
                            
                            success = self.download_image_with_progress(img_url, filepath, filename)
                            
                            if success:
                                self.progress_signal.emit(f"✅ [{i}/{total_pages}] Finished: {filename}")
                                self.downloaded_count += 1
                            else:
                                self.progress_signal.emit(f"❌ [{i}/{total_pages}] Failed: {filename}")
                                self.skipped_count += 1
                    else:
                        self.progress_signal.emit(f"❌ [{i}/{total_pages}] Error: No image link found.")
                        self.skipped_count += 1

                except Exception as e:
                    self.progress_signal.emit(f"❌ [{i}/{total_pages}] Exception: {e}")
                    self.skipped_count += 1

                # Emit overall page progress
                self.overall_progress_signal.emit(total_pages, i)
                time.sleep(0.5) 

            summary = (
                f"\n🏁 [HentaiFox] Task Complete!\n"
                f"   - Total: {total_pages}\n"
                f"   - Downloaded: {self.downloaded_count}\n"
                f"   - Skipped: {self.skipped_count}\n"
            )
            self.progress_signal.emit(summary)
            
            if self.is_running and self.downloaded_count + self.skipped_count == total_pages and total_pages > 0:
                self.db.record_manga_download(db_gallery_id, "hentaifox", title, save_folder, artist=artist, tags_list=tags)

        except Exception as e:
            self.progress_signal.emit(f"❌ Critical Error: {str(e)}")
        
        self.finished_signal.emit(self.downloaded_count, self.skipped_count, not self.is_running, [])

    def download_image_with_progress(self, url, path, filename):
        """Downloads file while emitting byte-level progress signals."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://hentaifox.com/"
        }
        
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=20, proxies=self.proxies)
            if r.status_code != 200:
                return False
            
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            
            chunk_size = 1024
            
            with open(path, 'wb') as f:
                for chunk in r.iter_content(chunk_size):
                    if not self.is_running:
                        r.close()
                        return False
                        
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        self.file_progress_signal.emit(filename, (downloaded_size, total_size))
            
            return True
        except Exception as e:
            print(f"Download Error: {e}")
            return False

    def stop(self):
        self.is_running = False

    def cancel(self):
        """Alias for stop() so the main cancel button works correctly."""
        self.is_running = False
        self.progress_signal.emit("   Cancellation signal received by HentaiFox thread.")

    def pause(self):
        """Pause is not supported; no-op to satisfy the generic pause handler."""
        pass

    def resume(self):
        """Resume is not supported; no-op to satisfy the generic pause handler."""
        pass