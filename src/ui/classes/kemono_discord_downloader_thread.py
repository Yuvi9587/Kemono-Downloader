import os
import time
import uuid
import threading
import cloudscraper
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtCore import QThread, pyqtSignal

try:
    from ...core.discord_client import fetch_server_channels, fetch_channel_messages
    from ...utils.file_utils import clean_filename
except ImportError as e:
    print(f"ERROR: Failed to import required modules for Kemono Discord thread: {e}")
    raise

class InterruptedError(Exception):
    """Custom exception for handling cancellations/pausing gracefully within download loops."""
    pass

class KemonoDiscordDownloadThread(QThread):
    """
    A dedicated QThread for downloading files from Kemono Discord server/channel pages,
    using the Kemono API via discord_client and multithreading for file downloads.
    Includes a single retry attempt after a 15-second delay for specific errors.
    """
    progress_signal = pyqtSignal(str)
    progress_label_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    permanent_file_failed_signal = pyqtSignal(list)
    finished_signal = pyqtSignal(int, int, bool, list)

    def __init__(self, server_id, channel_id, output_dir, cookies_dict, parent):
        """
        Initializes the Kemono Discord downloader thread.

        Args:
            server_id (str): The Discord server ID from Kemono.
            channel_id (str | None): The specific Discord channel ID from Kemono, if provided.
            output_dir (str): The base directory to save downloaded files.
            cookies_dict (dict | None): Cookies to use for requests.
            parent (QWidget): The parent widget (main_app) to access events/settings.
        """
        super().__init__(parent)
        self.server_id = server_id
        self.target_channel_id = channel_id
        self.output_dir = output_dir
        self.cookies_dict = cookies_dict
        self.parent_app = parent

        self.cancellation_event = getattr(parent, 'cancellation_event', threading.Event())
        self.pause_event = getattr(parent, 'pause_event', threading.Event())
        self._is_cancelled_internal = False

        self.download_count = 0
        self.skip_count = 0
        self.count_lock = threading.Lock()

        self.permanently_failed_details = []

        self.num_file_threads = 1
        try:
            use_mt = getattr(self.parent_app, 'use_multithreading_checkbox', None)
            thread_input = getattr(self.parent_app, 'thread_count_input', None)
            if use_mt and use_mt.isChecked() and thread_input:
                 thread_count_ui = int(thread_input.text().strip())
                 self.num_file_threads = max(1, min(thread_count_ui, 20))
        except (ValueError, AttributeError, TypeError):
             try: self.progress_signal.emit("⚠️ Warning: Could not read thread count setting, defaulting to 1.")
             except Exception: pass
             self.num_file_threads = 1

        try:
            self.scraper = cloudscraper.create_scraper(browser={'browser': 'firefox', 'platform': 'windows', 'mobile': False})
        except Exception as e:
             try: self.progress_signal.emit(f"❌ ERROR: Failed to initialize cloudscraper: {e}")
             except Exception: pass
             self.scraper = None

    def cancel(self):
        self._is_cancelled_internal = True
        self.cancellation_event.set()
        try: self.progress_signal.emit("   Cancellation requested for Kemono Discord download.")
        except Exception: pass

    def pause(self):
        if not self.pause_event.is_set():
            self.pause_event.set()
            try: self.progress_signal.emit("   Pausing Kemono Discord download...")
            except Exception: pass

    def resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            try: self.progress_signal.emit("   Resuming Kemono Discord download...")
            except Exception: pass

    def _check_events(self):
        if self._is_cancelled_internal or self.cancellation_event.is_set():
            if not self._is_cancelled_internal:
                self._is_cancelled_internal = True
                try: self.progress_signal.emit("   Cancellation detected by Kemono Discord thread check.")
                except Exception: pass
            return True

        was_paused = False
        while self.pause_event.is_set():
            if not was_paused:
                 try: self.progress_signal.emit("   Kemono Discord operation paused...")
                 except Exception: pass
                 was_paused = True
            if self.cancellation_event.is_set():
                self._is_cancelled_internal = True
                try: self.progress_signal.emit("   Cancellation detected while paused.")
                except Exception: pass
                return True
            time.sleep(0.5)
        return False

    def _download_single_kemono_file(self, file_info):
        """
        Downloads a single file, handles collisions after download,
        and automatically retries ONCE after 15s for specific network errors.

        Returns:
            tuple: (bool_success, dict_error_details_or_None)
        """
        MAX_ATTEMPTS = 2
        RETRY_DELAY_SECONDS = 15

        channel_dir = file_info['channel_dir']
        original_filename = file_info['original_filename']
        file_url = file_info['file_url']
        channel_id = file_info['channel_id']
        post_title = file_info.get('post_title', f"Message in channel {channel_id}")
        original_post_id_for_log = file_info.get('message_id', 'N/A')
        base_kemono_domain = "kemono.cr"

        if not self.scraper:
             try: self.progress_signal.emit(f"   ❌ Cannot download '{original_filename}': Cloudscraper not initialized.")
             except Exception: pass
             failure_details = { 'file_info': {'url': file_url, 'name': original_filename}, 'post_title': post_title, 'original_post_id_for_log': original_post_id_for_log, 'target_folder_path': channel_dir, 'error': 'Cloudscraper not initialized', 'service': 'discord', 'user_id': self.server_id }
             return False, failure_details

        if self._check_events(): return False, None

        cleaned_original_filename = clean_filename(original_filename)
        intended_final_filename = cleaned_original_filename
        unique_suffix = uuid.uuid4().hex[:8]
        temp_filename = f"{intended_final_filename}.{unique_suffix}.part"
        temp_filepath = os.path.join(channel_dir, temp_filename)

        download_successful = False
        last_exception = None
        should_retry = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = None
            try:
                if self._check_events(): raise InterruptedError("Cancelled/Paused before attempt")
                if attempt == 2 and should_retry:
                    try: self.progress_signal.emit(f"   ⏳ Retrying '{original_filename}' (Attempt {attempt}/{MAX_ATTEMPTS}) after {RETRY_DELAY_SECONDS}s...")
                    except Exception: pass
                    for _ in range(RETRY_DELAY_SECONDS):
                        if self._check_events(): raise InterruptedError("Cancelled/Paused during retry delay")
                        time.sleep(1)
                elif attempt == 2 and not should_retry:
                    break

                log_prefix = f"   ⬇️ Downloading:" if attempt == 1 else f"   🔄 Retrying:"
                try: self.progress_signal.emit(f"{log_prefix} '{original_filename}' (Attempt {attempt}/{MAX_ATTEMPTS})...")
                except Exception: pass
                if attempt == 1:
                    try: self.file_progress_signal.emit(original_filename, (0, 0))
                    except Exception: pass

                headers = { 'User-Agent': 'Mozilla/5.0 ...', 'Referer': f'https://{base_kemono_domain}/discord/channel/{channel_id}'}
                response = self.scraper.get(file_url, headers=headers, cookies=self.cookies_dict, stream=True, timeout=(15, 120))
                response.raise_for_status()

                total_size = int(response.headers.get('content-length', 0))
                downloaded_size = 0
                last_progress_emit_time = time.time()

                with open(temp_filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if self._check_events(): raise InterruptedError("Cancelled/Paused during chunk writing")
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            current_time = time.time()
                            if total_size > 0 and (current_time - last_progress_emit_time > 0.5 or downloaded_size == total_size):
                                try: self.file_progress_signal.emit(original_filename, (downloaded_size, total_size))
                                except Exception: pass
                                last_progress_emit_time = current_time
                            elif total_size == 0 and (current_time - last_progress_emit_time > 0.5):
                                try: self.file_progress_signal.emit(original_filename, (downloaded_size, 0))
                                except Exception: pass
                                last_progress_emit_time = current_time
                response.close()

                if self._check_events(): raise InterruptedError("Cancelled/Paused after download completion")

                if total_size > 0 and downloaded_size != total_size:
                    try: self.progress_signal.emit(f"   ⚠️ Size mismatch on attempt {attempt} for '{original_filename}'. Expected {total_size}, got {downloaded_size}.")
                    except Exception: pass
                    last_exception = IOError(f"Size mismatch: Expected {total_size}, got {downloaded_size}")
                    if os.path.exists(temp_filepath):
                         try: os.remove(temp_filepath)
                         except OSError: pass
                    should_retry = (attempt == 1)
                    continue
                else:
                    download_successful = True
                    break

            except InterruptedError as e:
                last_exception = e
                should_retry = False
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, cloudscraper.exceptions.CloudflareException) as e:
                last_exception = e
                try: self.progress_signal.emit(f"   ❌ Network/Cloudflare error on attempt {attempt} for '{original_filename}': {e}")
                except Exception: pass
                should_retry = (attempt == 1)
            except requests.exceptions.RequestException as e:
                status_code = getattr(e.response, 'status_code', None)
                if status_code and 500 <= status_code <= 599:
                    last_exception = e
                    try: self.progress_signal.emit(f"   ❌ Server error ({status_code}) on attempt {attempt} for '{original_filename}'. Will retry...")
                    except Exception: pass
                    should_retry = (attempt == 1)
                else:
                    last_exception = e
                    try: self.progress_signal.emit(f"   ❌ Non-retryable HTTP error for '{original_filename}': {e}")
                    except Exception: pass
                    should_retry = False
                    break
            except OSError as e:
                last_exception = e
                try: self.progress_signal.emit(f"   ❌ OS error during download attempt {attempt} for '{original_filename}': {e}")
                except Exception: pass
                should_retry = False
                break
            except Exception as e:
                last_exception = e
                try: self.progress_signal.emit(f"   ❌ Unexpected error on attempt {attempt} for '{original_filename}': {e}")
                except Exception: pass
                should_retry = False
                break
            finally:
                if response:
                    try: response.close()
                    except Exception: pass

        try: self.file_progress_signal.emit(original_filename, None)
        except Exception: pass

        if download_successful:
            final_filename_to_use = intended_final_filename
            final_filepath_on_disk = os.path.join(channel_dir, final_filename_to_use)
            counter = 1
            base_name, extension = os.path.splitext(intended_final_filename)
            while os.path.exists(final_filepath_on_disk):
                final_filename_to_use = f"{base_name} ({counter}){extension}"
                final_filepath_on_disk = os.path.join(channel_dir, final_filename_to_use)
                counter += 1
            if final_filename_to_use != intended_final_filename:
                 try: self.progress_signal.emit(f"   -> Name conflict for '{intended_final_filename}'. Renaming to '{final_filename_to_use}'.")
                 except Exception: pass
            try:
                os.rename(temp_filepath, final_filepath_on_disk)
                try: self.progress_signal.emit(f"   ✅ Saved: '{final_filename_to_use}'")
                except Exception: pass
                return True, None
            except OSError as e:
                try: self.progress_signal.emit(f"   ❌ OS error renaming temp file to '{final_filename_to_use}': {e}")
                except Exception: pass
                if os.path.exists(temp_filepath):
                     try: os.remove(temp_filepath)
                     except OSError: pass
                failure_details = { 'file_info': {'url': file_url, 'name': original_filename}, 'post_title': post_title, 'original_post_id_for_log': original_post_id_for_log, 'target_folder_path': channel_dir, 'intended_filename': intended_final_filename, 'error': f"Rename failed: {e}", 'service': 'discord', 'user_id': self.server_id }
                return False, failure_details
        else:
            if not isinstance(last_exception, InterruptedError):
                try: self.progress_signal.emit(f"   ❌ FAILED to download '{original_filename}' after {MAX_ATTEMPTS} attempts. Last error: {last_exception}")
                except Exception: pass
            if os.path.exists(temp_filepath):
                try: os.remove(temp_filepath)
                except OSError as e_rem:
                     try: self.progress_signal.emit(f"    (Failed to remove temp file '{temp_filename}': {e_rem})")
                     except Exception: pass
            failure_details = None
            if not isinstance(last_exception, InterruptedError):
                failure_details = {
                    'file_info': {'url': file_url, 'name': original_filename},
                    'post_title': post_title, 'original_post_id_for_log': original_post_id_for_log,
                    'target_folder_path': channel_dir, 'intended_filename': intended_final_filename,
                    'error': f"Failed after {MAX_ATTEMPTS} attempts: {last_exception}",
                    'service': 'discord', 'user_id': self.server_id,
                    'forced_filename_override': intended_final_filename,
                    'file_index_in_post': file_info.get('file_index', 0),
                    'num_files_in_this_post': file_info.get('num_files', 1)
                }
            return False, failure_details

    def run(self):
        """Main execution logic: Fetches channels/messages and dispatches file downloads."""
        self.download_count = 0
        self.skip_count = 0
        self._is_cancelled_internal = False
        self.permanently_failed_details = []

        if not self.scraper:
             try: self.progress_signal.emit("❌ Aborting Kemono Discord download: Cloudscraper failed to initialize.")
             except Exception: pass
             self.finished_signal.emit(0, 0, False, [])
             return

        try:
            try:
                self.progress_signal.emit("=" * 40)
                self.progress_signal.emit(f"🚀 Starting Kemono Discord download for server: {self.server_id}")
                self.progress_signal.emit(f"   Using {self.num_file_threads} thread(s) for file downloads.")
            except Exception: pass

            channels_to_process = []
            if self.target_channel_id:
                channels_to_process.append({'id': self.target_channel_id, 'name': self.target_channel_id})
                try: self.progress_signal.emit(f"   Targeting specific channel: {self.target_channel_id}")
                except Exception: pass
            else:
                try: self.progress_label_signal.emit("Fetching server channels via Kemono API...")
                except Exception: pass
                channels_data = fetch_server_channels(self.server_id, logger=self.progress_signal.emit, cookies_dict=self.cookies_dict)
                if self._check_events(): return
                if channels_data is not None:
                    channels_to_process = channels_data
                    try: self.progress_signal.emit(f"   Found {len(channels_to_process)} channels.")
                    except Exception: pass
                else:
                    try: self.progress_signal.emit(f"   ❌ Failed to fetch channels for server {self.server_id} via Kemono API.")
                    except Exception: pass
                    return

            for channel in channels_to_process:
                if self._check_events(): break

                channel_id = channel['id']
                channel_name = clean_filename(channel.get('name', channel_id))
                channel_dir = os.path.join(self.output_dir, channel_name)
                try:
                    os.makedirs(channel_dir, exist_ok=True)
                except OSError as e:
                    try: self.progress_signal.emit(f"   ❌ Failed to create directory for channel '{channel_name}': {e}. Skipping channel.")
                    except Exception: pass
                    continue

                try:
                    self.progress_signal.emit(f"\n--- Processing Channel: #{channel_name} ({channel_id}) ---")
                    self.progress_label_signal.emit(f"Fetching messages for #{channel_name}...")
                except Exception: pass

                file_tasks = []
                message_generator = fetch_channel_messages(
                    channel_id, logger=self.progress_signal.emit,
                    cancellation_event=self.cancellation_event, pause_event=self.pause_event,
                    cookies_dict=self.cookies_dict
                )

                try:
                    message_index = 0
                    for message_batch in message_generator:
                        if self._check_events(): break
                        for message in message_batch:
                            message_id = message.get('id', f'msg_{message_index}')
                            post_title_context = (message.get('content') or f"Message {message_id}")[:50] + "..."
                            attachments = message.get('attachments', [])
                            file_index_in_message = 0
                            num_files_in_message = len(attachments)

                            for attachment in attachments:
                                if self._check_events(): raise InterruptedError
                                file_path = attachment.get('path')
                                original_filename = attachment.get('name')
                                if file_path and original_filename:
                                    base_kemono_domain = "kemono.cr"
                                    if not file_path.startswith('/'): file_path = '/' + file_path
                                    file_url = f"https://{base_kemono_domain}/data{file_path}"
                                    file_tasks.append({
                                        'channel_dir': channel_dir, 'original_filename': original_filename,
                                        'file_url': file_url, 'channel_id': channel_id,
                                        'message_id': message_id, 'post_title': post_title_context,
                                        'file_index': file_index_in_message, 'num_files': num_files_in_message
                                    })
                                    file_index_in_message += 1
                            message_index += 1
                            if self._check_events(): raise InterruptedError
                        if self._check_events(): raise InterruptedError
                except InterruptedError:
                     try: self.progress_signal.emit("   Interrupted while collecting file tasks.")
                     except Exception: pass
                     break
                except Exception as e_msg:
                     try: self.progress_signal.emit(f"   ❌ Error fetching messages for channel {channel_name}: {e_msg}")
                     except Exception: pass
                     continue

                if self._check_events(): break

                if not file_tasks:
                    try: self.progress_signal.emit("   No downloadable file attachments found in this channel's messages.")
                    except Exception: pass
                    continue

                try:
                    self.progress_signal.emit(f"   Found {len(file_tasks)} potential file attachments. Starting downloads...")
                    self.progress_label_signal.emit(f"Downloading {len(file_tasks)} files for #{channel_name}...")
                except Exception: pass

                files_processed_in_channel = 0
                with ThreadPoolExecutor(max_workers=self.num_file_threads, thread_name_prefix=f"KDC_{channel_id[:4]}_") as executor:
                    futures = {executor.submit(self._download_single_kemono_file, task): task for task in file_tasks}
                    try:
                        for future in as_completed(futures):
                            files_processed_in_channel += 1
                            task_info = futures[future]
                            try:
                                success, details = future.result()
                                with self.count_lock:
                                    if success:
                                        self.download_count += 1
                                    else:
                                        self.skip_count += 1
                                        if details:
                                            self.permanently_failed_details.append(details)
                            except Exception as e_future:
                                filename = task_info.get('original_filename', 'unknown file')
                                try: self.progress_signal.emit(f"   ❌ System error processing download future for '{filename}': {e_future}")
                                except Exception: pass
                                with self.count_lock:
                                    self.skip_count += 1
                                failure_details = { 'file_info': {'url': task_info.get('file_url'), 'name': filename}, 'post_title': task_info.get('post_title', 'N/A'), 'original_post_id_for_log': task_info.get('message_id', 'N/A'), 'target_folder_path': task_info.get('channel_dir'), 'error': f"Future execution error: {e_future}", 'service': 'discord', 'user_id': self.server_id, 'forced_filename_override': clean_filename(filename), 'file_index_in_post': task_info.get('file_index', 0), 'num_files_in_this_post': task_info.get('num_files', 1) }
                                self.permanently_failed_details.append(failure_details)

                            try: self.progress_label_signal.emit(f"#{channel_name}: {files_processed_in_channel}/{len(file_tasks)} files processed")
                            except Exception: pass

                            if self._check_events():
                                 try: self.progress_signal.emit("   Cancelling remaining file downloads for this channel...")
                                 except Exception: pass
                                 executor.shutdown(wait=False, cancel_futures=True)
                                 break
                    except InterruptedError:
                         try: self.progress_signal.emit("   Download processing loop interrupted.")
                         except Exception: pass
                         executor.shutdown(wait=False, cancel_futures=True)

                if self._check_events(): break


        except Exception as e:
            try:
                self.progress_signal.emit(f"❌ Unexpected critical error in Kemono Discord thread run loop: {e}")
                import traceback
                self.progress_signal.emit(traceback.format_exc())
            except Exception: pass
        finally:
            try:
                try: self.progress_signal.emit("=" * 40)
                except Exception: pass
                cancelled = self._is_cancelled_internal or self.cancellation_event.is_set()

                if self.permanently_failed_details:
                    try:
                        self.progress_signal.emit(f"   Reporting {len(self.permanently_failed_details)} permanently failed files...")
                        self.permanent_file_failed_signal.emit(list(self.permanently_failed_details))
                    except Exception as e_emit_fail:
                         print(f"ERROR emitting permanent_file_failed_signal: {e_emit_fail}")

                try:
                    if cancelled and not self._is_cancelled_internal:
                        self.progress_signal.emit("   Kemono Discord download cancelled externally.")
                    elif self._is_cancelled_internal:
                        self.progress_signal.emit("   Kemono Discord download finished due to cancellation.")
                    else:
                         self.progress_signal.emit("✅ Kemono Discord download process finished.")
                except Exception: pass

                try: self.file_progress_signal.emit("", None)
                except Exception: pass

                with self.count_lock:
                     final_download_count = self.download_count
                     final_skip_count = self.skip_count

                self.finished_signal.emit(final_download_count, final_skip_count, cancelled, [])
            except Exception as e_final:
                 print(f"ERROR in KemonoDiscordDownloadThread finally block: {e_final}")