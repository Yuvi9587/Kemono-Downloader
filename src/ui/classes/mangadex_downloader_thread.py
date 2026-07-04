import threading
from PyQt5.QtCore import QThread, pyqtSignal

from ...core.mangadex_client import fetch_mangadex_data
from ...utils.proxy_utils import get_proxies_from_settings


class MangaDexDownloadThread(QThread):
    """A wrapper QThread for running the MangaDex client function."""
    progress_signal = pyqtSignal(str)
    file_progress_signal = pyqtSignal(str, object)
    finished_signal = pyqtSignal(int, int, bool)
    overall_progress_signal = pyqtSignal(int, int)

    def __init__(self, url, output_dir, parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.start_url = url
        self.output_dir = output_dir
        self.is_cancelled = False
        self.pause_event = parent.pause_event if hasattr(parent, 'pause_event') else threading.Event()
        self.cancellation_event = parent.cancellation_event if hasattr(parent, 'cancellation_event') else threading.Event()
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None

    def run(self):
        downloaded = 0
        skipped = 0
        try:
            downloaded, skipped = fetch_mangadex_data(
                self.start_url,
                self.output_dir,
                logger_func=self.progress_signal.emit,
                file_progress_callback=self.file_progress_signal,
                overall_progress_callback=self.overall_progress_signal,
                pause_event=self.pause_event,
                cancellation_event=self.cancellation_event,
                proxies=self.proxies,
                export_all_links_mode=self.export_all_links_mode
            )
        except Exception as e:
            self.progress_signal.emit(f"❌ A critical error occurred in the MangaDex thread: {e}")
            skipped = 1
        finally:
            self.finished_signal.emit(downloaded, skipped, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        if self.cancellation_event:
            self.cancellation_event.set()
        self.progress_signal.emit("   Cancellation signal received by MangaDex thread.")