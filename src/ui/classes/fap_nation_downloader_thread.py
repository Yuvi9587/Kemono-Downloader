import os
import sys
import re
import threading
import time
from PyQt5.QtCore import QThread, pyqtSignal, QProcess
import cloudscraper

from ...core.fap_nation_client import fetch_fap_nation_data
from ...services.multipart_downloader import download_file_in_parts
from ...utils.proxy_utils import get_proxies_from_settings

class FapNationDownloadThread(QThread):
    """
    A dedicated QThread for Fap-Nation that uses a hybrid approach, choosing
    between yt-dlp for HLS streams and a multipart downloader for direct links.
    """
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool, list)
    overall_progress_signal = pyqtSignal(int, int)

    def __init__(self, url, output_dir, use_post_subfolder, pause_event, cancellation_event, gui_signals, parent=None):
        super().__init__(parent)
        self.album_url = url
        self.output_dir = output_dir
        self.use_post_subfolder = use_post_subfolder
        self.is_cancelled = False
        self.process = None
        self.current_filename = "Unknown File"
        self.album_name = "fap-nation_album"
        self.pause_event = pause_event
        self.cancellation_event = cancellation_event
        self.gui_signals = gui_signals
        self._is_finished = False
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None
        
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_ytdlp_output)

    def run(self):
        self.progress_signal.emit("=" * 40)
        self.progress_signal.emit(f"🚀 Starting Fap-Nation Download for: {self.album_url}")
        
        self.album_name, files_to_download = fetch_fap_nation_data(self.album_url, self.progress_signal.emit, proxies=self.proxies)
        
        if self.is_cancelled or not files_to_download:
            self.progress_signal.emit("❌ Failed to extract file information. Aborting.")
            self.finished_signal.emit(0, 1, self.is_cancelled, [])
            return

        self.overall_progress_signal.emit(1, 0)

        save_path = self.output_dir
        if self.use_post_subfolder:
            save_path = os.path.join(self.output_dir, self.album_name)
            self.progress_signal.emit(f"   Subfolder per Post is ON. Saving to: '{self.album_name}'")
        os.makedirs(save_path, exist_ok=True)
        
        file_data = files_to_download[0]
        self.current_filename = file_data.get('filename')
        download_url = file_data.get('url')
        link_type = file_data.get('type')
        filepath = os.path.join(save_path, self.current_filename)
        
        if os.path.exists(filepath):
            self.progress_signal.emit(f"   -> Skip: '{self.current_filename}' already exists.")
            self.overall_progress_signal.emit(1, 1)
            self.finished_signal.emit(0, 1, self.is_cancelled)
            return

        if link_type == 'hls':
            self.download_with_ytdlp(filepath, download_url)
        elif link_type == 'direct':
            self.download_with_multipart(filepath, download_url) 
        else:
            self.progress_signal.emit(f"   ❌ Unknown link type '{link_type}'. Aborting.")
            self._on_ytdlp_finished(-1)

    def download_with_ytdlp(self, filepath, playlist_url):
        self.progress_signal.emit(f"   Downloading (HLS Stream): '{self.current_filename}' using yt-dlp...")
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
                ytdlp_path = os.path.join(base_path, "yt-dlp.exe")
            else:
                ytdlp_path = "yt-dlp.exe"

            if not os.path.exists(ytdlp_path):
                 self.progress_signal.emit(f"   ❌ ERROR: yt-dlp.exe not found at '{ytdlp_path}'.")
                 self._on_ytdlp_finished(-1)
                 return

            command = [ytdlp_path, '--no-warnings', '--progress', '--output', filepath, '--merge-output-format', 'mp4', playlist_url]
            
            self.process.start(command[0], command[1:])
            self.process.waitForFinished(-1) 
            self._on_ytdlp_finished(self.process.exitCode())

        except Exception as e:
            self.progress_signal.emit(f"   ❌ Failed to start yt-dlp: {e}")
            self._on_ytdlp_finished(-1)

    def download_with_multipart(self, filepath, direct_url):
        self.progress_signal.emit(f"   Downloading (Direct Link): '{self.current_filename}' using multipart downloader...")
        try:
            session = cloudscraper.create_scraper()
            head_response = session.head(direct_url, allow_redirects=True, timeout=20)
            head_response.raise_for_status()
            total_size = int(head_response.headers.get('content-length', 0))

            success, _, _, _ = download_file_in_parts(
                file_url=direct_url, save_path=filepath, total_size=total_size, num_parts=5,
                headers=session.headers, api_original_filename=self.current_filename,
                emitter_for_multipart=self.gui_signals,
                cookies_for_chunk_session=session.cookies, 
                cancellation_event=self.cancellation_event,
                skip_event=None, logger_func=self.progress_signal.emit, pause_event=self.pause_event
            )
            self._on_ytdlp_finished(0 if success else 1)
        except Exception as e:
            self.progress_signal.emit(f"   ❌ Multipart download failed: {e}")
            self._on_ytdlp_finished(1)

    def handle_ytdlp_output(self):
        if not self.process:
            return
            
        output = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        for line in reversed(output.strip().splitlines()):
            line = line.strip()
            progress_match = re.search(r'\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+\w+B)', line)
            if progress_match:
                percent, size = progress_match.groups()
                self.file_progress_signal.emit("yt-dlp:", f"{percent}% of {size}")
                break

    def _on_ytdlp_finished(self, exit_code):
        if self._is_finished:
            return
        self._is_finished = True
        
        download_count, skip_count = 0, 0
        
        if self.is_cancelled:
            self.progress_signal.emit(f"   Download of '{self.current_filename}' was cancelled.")
            skip_count = 1
        elif exit_code == 0:
            self.progress_signal.emit(f"   ✅ Download process finished successfully for '{self.current_filename}'.")
            download_count = 1
        else:
            self.progress_signal.emit(f"   ❌ Download process exited with an error (Code: {exit_code}) for '{self.current_filename}'.")
            skip_count = 1
        
        self.overall_progress_signal.emit(1, 1)
        self.process = None
        self.finished_signal.emit(download_count, skip_count, self.is_cancelled, [])

    def cancel(self):
        self.is_cancelled = True
        self.cancellation_event.set()
        if self.process and self.process.state() == QProcess.Running:
            self.progress_signal.emit("   Cancellation signal received, terminating yt-dlp process.")
            self.process.kill()