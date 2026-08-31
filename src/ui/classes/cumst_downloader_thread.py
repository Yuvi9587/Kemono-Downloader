"""
cum.st downloader thread.
Follows the same pattern as HotleaksThread / CoomerfansThread.
"""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

from ...core.cumst_client import CumStClient
from ...utils.proxy_utils import get_proxies_from_settings

MAX_WORKERS = 3


class CumStDownloadThread(QThread):
    progress_signal = Signal(str)
    file_progress_signal = Signal(str, object)
    overall_progress_signal = Signal(int, int)
    finished_signal = Signal(int, int, bool, list)
    error_signal = Signal(str)

    def __init__(self, url, save_directory, main_app, export_all_links_mode=False):
        super().__init__(main_app)
        self.url = url
        self.save_directory = save_directory
        self.main_app = main_app
        self.export_all_links_mode = export_all_links_mode

        _proxies = get_proxies_from_settings(main_app.settings) if hasattr(main_app, "settings") else None
        self.client = CumStClient(proxies=_proxies)

        self.is_running = True
        self.download_count = 0
        self.skip_count = 0
        self._count_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public control API (called by main_window cancel/pause handlers)
    # ------------------------------------------------------------------

    def cancel(self):
        """Called by main_window's cancel_download_button_action."""
        self.is_running = False

    def pause(self):
        """Called by main_window's _handle_pause_resume_action (optional hook)."""
        pass  # pause is driven by main_app.pause_event, already polled in check_pause_and_cancel

    def resume(self):
        """Called by main_window's _handle_pause_resume_action (optional hook)."""
        pass  # resume is driven by main_app.pause_event.clear(), already handled

    # ------------------------------------------------------------------
    # Logging / control helpers
    # ------------------------------------------------------------------

    def log(self, message):
        if self.main_app and hasattr(self.main_app, "log_signal"):
            self.main_app.log_signal.emit(str(message))
        else:
            self.progress_signal.emit(str(message))

    def check_pause_and_cancel(self):
        """Returns True if we should continue, False if cancelled."""
        if getattr(self.main_app, "cancellation_event", None) and self.main_app.cancellation_event.is_set():
            self.is_running = False
            return False
        pause_evt = getattr(self.main_app, "pause_event", None)
        if pause_evt:
            while pause_evt.is_set():
                if getattr(self.main_app, "cancellation_event", None) and self.main_app.cancellation_event.is_set():
                    self.is_running = False
                    return False
                time.sleep(0.3)
        return True

    def _smart_sleep(self, seconds):
        """Sleep in small intervals so cancel still works."""
        for _ in range(int(seconds * 2)):
            if not self.check_pause_and_cancel():
                return False
            time.sleep(0.5)
        return True

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        try:
            service, user_id = self.client.parse_url(self.url)
            if not service or not user_id:
                self.log("❌ cum.st: Could not parse service/user_id from URL.")
                self.log("   Expected format: https://cum.st/creators/onlyfans/12345678")
                self.finished_signal.emit(0, 0, False, [])
                return

            self.log(f"🔞 cum.st — service: {service}, user_id: {user_id}")

            # Output folder: <save_directory>/<service>/<user_id>/
            creator_folder = os.path.join(self.save_directory, service, user_id)
            os.makedirs(creator_folder, exist_ok=True)

            # --- Collect all posts via paginated API ---
            all_posts = []
            offset = 0
            total = None

            while self.is_running:
                if not self.check_pause_and_cancel():
                    break
                try:
                    total, page_posts = self.client.get_posts_page(service, user_id, offset=offset)
                except Exception as e:
                    self.log(f"   ❌ API error at offset {offset}: {e}")
                    break

                if not page_posts:
                    break

                all_posts.extend(page_posts)
                self.log(f"   Fetched {len(all_posts)}/{total} posts…")

                if len(all_posts) >= total:
                    break

                offset += len(page_posts)
                if not self._smart_sleep(0.4):
                    break

            if not self.is_running:
                self.log("⚠️ Cancelled during post fetch.")
                self.finished_signal.emit(self.download_count, self.skip_count, True, [])
                return

            self.log(f"✅ Found {len(all_posts)} posts. Building download queue…")

            # --- Build flat list of download tasks ---
            tasks = []
            for post in all_posts:
                post_id = post.get("id", "unknown")
                for att in post.get("attachments", []):
                    if att.get("locked", False):
                        continue
                    storage_key = att.get("storageKey") or att.get("sha256")
                    variants = att.get("variants", [])
                    variant = self.client.get_best_variant(variants)
                    if not storage_key or not variant:
                        continue
                    variant_name = variant["name"]
                    original_filename = att.get("originalFilename") or f"{storage_key}_{variant_name}"
                    cdn_url = self.client.build_cdn_url(storage_key, variant_name)
                    tasks.append({
                        "post_id": post_id,
                        "url": cdn_url,
                        "filename": original_filename,
                        "kind": att.get("kind", "file"),
                    })

            self.log(f"📦 {len(tasks)} file(s) to download.")

            # --- Download with thread pool ---
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(self._download_file, task, creator_folder): task
                    for task in tasks
                }
                for future in as_completed(futures):
                    if not self.is_running:
                        for f in futures:
                            f.cancel()
                        break
                    try:
                        future.result()
                    except Exception as e:
                        task = futures[future]
                        self.log(f"   ❌ Error on {task['filename']}: {e}")

            is_cancelled = not self.is_running
            self.log(
                f"{'⚠️ Cancelled.' if is_cancelled else '✅ Done!'} "
                f"Downloaded: {self.download_count}, Skipped: {self.skip_count}"
            )
            self.finished_signal.emit(self.download_count, self.skip_count, is_cancelled, [])

        except Exception as e:
            self.log(f"❌ cum.st Engine Error: {e}")
            self.finished_signal.emit(self.download_count, self.skip_count, True, [])

    # ------------------------------------------------------------------
    # Per-file download
    # ------------------------------------------------------------------

    def _download_file(self, task, folder):
        if not self.is_running:
            return

        filename = task["filename"]
        url = task["url"]
        kind = task["kind"]
        save_path = os.path.join(folder, filename)

        # Skip already downloaded
        if os.path.exists(save_path):
            with self._count_lock:
                self.skip_count += 1
            return

        # Export-links mode
        if self.export_all_links_mode:
            export_path = os.path.join(self.save_directory, "all_file_links.txt")
            try:
                with open(export_path, "a", encoding="utf-8") as f:
                    f.write(url + "\n")
                self.log(f"   📋 Exported: {url}")
                with self._count_lock:
                    self.download_count += 1
            except Exception:
                pass
            return

        self.log(f"   [{kind}] ⬇ {filename}")

        try:
            resp = self.client.session.get(url, timeout=60, stream=True)
            resp.raise_for_status()

            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            # Write to temp file first, then rename (atomic)
            tmp_path = save_path + ".tmp"
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not self.is_running:
                        f.close()
                        os.remove(tmp_path)
                        return
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            mb_dl = downloaded / 1_048_576
                            mb_tot = total_size / 1_048_576
                            self.file_progress_signal.emit(
                                f"{kind.capitalize()}:",
                                f"{filename}: {pct}% ({mb_dl:.1f}MB / {mb_tot:.1f}MB)",
                            )

            os.replace(tmp_path, save_path)
            self.overall_progress_signal.emit(1, 1)
            with self._count_lock:
                self.download_count += 1

        except Exception as e:
            # Clean up incomplete temp file
            tmp_path = save_path + ".tmp"
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise e
