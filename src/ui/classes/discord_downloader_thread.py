import os
import time
import datetime
import requests
from PySide6.QtCore import QThread, Signal

from ..dialogs.discord_pdf_generator import create_pdf_from_discord_messages

_ff_ver = (datetime.date.today().toordinal() - 735506) // 28
USERAGENT_FIREFOX = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; "
                     f"rv:{_ff_ver}.0) Gecko/20100101 Firefox/{_ff_ver}.0")

class DiscordDownloadThread(QThread):
    """A dedicated QThread for handling all official Discord downloads."""
    progress_signal = Signal(str)
    progress_label_signal = Signal(str)
    finished_signal = Signal(int, int, bool, list)

    def __init__(self, mode, session, token, output_dir, server_id, channel_id, url, app_base_dir, limit=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.session = session
        self.token = token
        self.output_dir = output_dir
        self.server_id = server_id
        self.channel_id = channel_id
        self.api_url = url
        self.message_limit = limit
        self.app_base_dir = app_base_dir

        self.is_cancelled = False
        self.is_paused = False

    def run(self):
        if self.mode == 'pdf':
            self._run_pdf_creation()
        else:
            self._run_file_download()

    def cancel(self):
        self.progress_signal.emit("   Cancellation signal received by Discord thread.")
        self.is_cancelled = True

    def pause(self):
        self.progress_signal.emit("   Pausing Discord download...")
        self.is_paused = True

    def resume(self):
        self.progress_signal.emit("   Resuming Discord download...")
        self.is_paused = False

    def _check_events(self):
        if self.is_cancelled:
            return True
        while self.is_paused:
            time.sleep(0.5)
            if self.is_cancelled:
                return True
        return False

    def _fetch_all_messages(self):
        all_messages = []
        last_message_id = None
        headers = {'Authorization': self.token, 'User-Agent': USERAGENT_FIREFOX}

        while True:
            if self._check_events(): break
            
            endpoint = f"/channels/{self.channel_id}/messages?limit=100"
            if last_message_id:
                endpoint += f"&before={last_message_id}"
            
            try:
                resp = self.session.get(f"https://discord.com/api/v10{endpoint}", headers=headers, timeout=30)
                resp.raise_for_status()
                message_batch = resp.json()
            except Exception as e:
                self.progress_signal.emit(f"   ❌ Error fetching message batch: {e}")
                break

            if not message_batch:
                break
            
            all_messages.extend(message_batch)

            if self.message_limit and len(all_messages) >= self.message_limit:
                self.progress_signal.emit(f"   Reached message limit of {self.message_limit}. Halting fetch.")
                all_messages = all_messages[:self.message_limit]
                break

            last_message_id = message_batch[-1]['id']
            self.progress_label_signal.emit(f"Fetched {len(all_messages)} messages...")
            time.sleep(1)
        
        return all_messages

    def _run_pdf_creation(self):
        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting Discord PDF export for: {self.api_url}")
        self.progress_label_signal.emit("Fetching messages...")

        all_messages = self._fetch_all_messages()

        if self.is_cancelled:
            self.finished_signal.emit(0, 0, True, [])
            return
        
        self.progress_label_signal.emit(f"Collected {len(all_messages)} total messages. Generating PDF...")
        all_messages.reverse()
        
        import sys
        font_base_dir = getattr(sys, '_MEIPASS', self.app_base_dir)
        font_path = os.path.join(font_base_dir, 'data', 'dejavu-sans', 'DejaVuSans.ttf')
        output_filepath = os.path.join(self.output_dir, f"discord_{self.server_id}_{self.channel_id or 'server'}.pdf")

        success = create_pdf_from_discord_messages(
            all_messages, self.server_id, self.channel_id,
            output_filepath, font_path, logger=self.progress_signal.emit,
            cancellation_event=self, pause_event=self
        )
        
        if success:
            self.progress_label_signal.emit(f"✅ PDF export complete!")
        elif not self.is_cancelled:
            self.progress_label_signal.emit(f"❌ PDF export failed. Check log for details.")
        
        self.finished_signal.emit(0, len(all_messages), self.is_cancelled, [])

    def _run_file_download(self):
        download_count = 0
        skip_count = 0
        try:
            self.progress_signal.emit("=" * 40)
            self.progress_signal.emit(f"🚀 Starting Discord download for channel: {self.channel_id}")
            self.progress_label_signal.emit("Fetching messages...")
            all_messages = self._fetch_all_messages()

            if self.is_cancelled:
                self.finished_signal.emit(0, 0, True, [])
                return

            self.progress_label_signal.emit(f"Collected {len(all_messages)} messages. Starting downloads...")
            total_attachments = sum(len(m.get('attachments', [])) for m in all_messages)

            for message in reversed(all_messages):
                if self._check_events(): break
                for attachment in message.get('attachments', []):
                    if self._check_events(): break
                    
                    file_url = attachment['url']
                    original_filename = attachment['filename']
                    filepath = os.path.join(self.output_dir, original_filename)
                    filename_to_use = original_filename

                    counter = 1
                    base_name, extension = os.path.splitext(original_filename)
                    while os.path.exists(filepath):
                        filename_to_use = f"{base_name} ({counter}){extension}"
                        filepath = os.path.join(self.output_dir, filename_to_use)
                        counter += 1
                    
                    if filename_to_use != original_filename:
                        self.progress_signal.emit(f"   -> Duplicate name '{original_filename}'. Saving as '{filename_to_use}'.")

                    try:
                        self.progress_signal.emit(f"   Downloading ({download_count+1}/{total_attachments}): '{filename_to_use}'...")
                        response = requests.get(file_url, stream=True, timeout=60)
                        response.raise_for_status()
                        
                        download_cancelled_mid_file = False
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if self._check_events():
                                    download_cancelled_mid_file = True
                                    break
                                f.write(chunk)
                        
                        if download_cancelled_mid_file:
                            self.progress_signal.emit(f"   Download cancelled for '{filename_to_use}'. Deleting partial file.")
                            if os.path.exists(filepath):
                                os.remove(filepath)
                            continue
                        
                        download_count += 1
                    except Exception as e:
                        self.progress_signal.emit(f"   ❌ Failed to download '{filename_to_use}': {e}")
                        skip_count += 1
        finally:
            self.finished_signal.emit(download_count, skip_count, self.is_cancelled, [])