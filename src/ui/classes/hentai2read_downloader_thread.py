import threading
import time
from PySide6.QtCore import QThread, Signal

from ...core.Hentai2read_client import run_hentai2read_download as h2r_run_download
from ...utils.proxy_utils import get_proxies_from_settings


class Hentai2readDownloadThread(QThread):
    """
    A dedicated QThread that calls the self-contained Hentai2Read client to
    perform scraping and downloading.
    """
    progress_signal = Signal(str)
    file_progress_signal = Signal(str, object)
    finished_signal = Signal(int, int, bool)
    overall_progress_signal = Signal(int, int)

    def __init__(self, url, output_dir, parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.start_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self.pause_event = parent.pause_event if hasattr(parent, 'pause_event') else threading.Event()
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def _check_pause(self):
        """Helper to handle pausing and cancellation events."""
        if self.is_cancelled: return True
        if self.pause_event and self.pause_event.is_set():
            self.progress_signal.emit("   Download paused...")
            while self.pause_event.is_set():
                if self.is_cancelled: return True
                time.sleep(0.5)
            self.progress_signal.emit("   Download resumed.")
        return self.is_cancelled

    def run(self):
        """
        Executes the main download logic by calling the dedicated client function.
        """
        downloaded, skipped = h2r_run_download(
            start_url=self.start_url,
            output_dir=self.output_dir,
            progress_callback=self.progress_signal.emit,
            overall_progress_callback=self.overall_progress_signal.emit,
            check_pause_func=self._check_pause,
            proxies=self.proxies,
            export_all_links_mode=self.export_all_links_mode
        )
        
        self.finished_signal.emit(downloaded, skipped, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True