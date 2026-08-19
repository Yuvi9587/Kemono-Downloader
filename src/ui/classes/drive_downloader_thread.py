from PySide6.QtCore import QThread, Signal

from ...services.drive_downloader import (
    download_dropbox_file,
    download_gdrive_file,
    download_gofile_folder,
    download_mega_file as drive_download_mega_file,
)


class DriveDownloadThread(QThread):
    """A dedicated QThread for handling direct Mega, GDrive, and Dropbox links."""
    file_progress_signal = Signal(str, object)
    finished_signal = Signal(int, int, bool, list)
    overall_progress_signal = Signal(int, int)

    def __init__(self, url, output_dir, platform, use_post_subfolder, cancellation_event, pause_event, logger_func, parent=None):
        super().__init__(parent)
        self.drive_url = url
        self.output_dir = output_dir
        self.platform = platform
        self.use_post_subfolder = use_post_subfolder
        self.is_cancelled = False
        self.cancellation_event = cancellation_event
        self.pause_event = pause_event
        self.logger_func = logger_func

    def run(self):
        self.logger_func("=" * 40)
        self.logger_func(f"🚀 Starting direct {self.platform.capitalize()} Download for: {self.drive_url}")
        
        try:
            if self.platform == 'mega':
                drive_download_mega_file(
                    self.drive_url, self.output_dir,
                    logger_func=self.logger_func,
                    progress_callback_func=self.file_progress_signal.emit,
                    overall_progress_callback=self.overall_progress_signal.emit,
                    cancellation_event=self.cancellation_event,
                    pause_event=self.pause_event
                )
            elif self.platform == 'gdrive':
                download_gdrive_file(
                    self.drive_url, self.output_dir,
                    logger_func=self.logger_func,
                    progress_callback_func=self.file_progress_signal.emit,
                    overall_progress_callback=self.overall_progress_signal.emit,
                    use_post_subfolder=self.use_post_subfolder,
                    post_title="Google Drive Download"
                )
            elif self.platform == 'dropbox':
                download_dropbox_file(
                    self.drive_url, self.output_dir,
                    logger_func=self.logger_func,
                    progress_callback_func=self.file_progress_signal.emit,
                    use_post_subfolder=self.use_post_subfolder,
                    post_title="Dropbox Download"
                )
            elif self.platform == 'gofile':
                download_gofile_folder(
                    self.drive_url,
                    self.output_dir,
                    logger_func=self.logger_func,
                    progress_callback_func=self.file_progress_signal.emit,
                    overall_progress_callback=self.overall_progress_signal.emit,
                    use_post_subfolder=self.use_post_subfolder
                )

            self.finished_signal.emit(1, 0, self.is_cancelled, [])

        except Exception as e:
            self.logger_func(f"❌ An unexpected error occurred in DriveDownloadThread: {e}")
            self.finished_signal.emit(0, 1, self.is_cancelled, [])

    def cancel(self):
        self.is_cancelled = True
        if self.cancellation_event:
            self.cancellation_event.set()
        self.logger_func(f"   Cancellation signal received by {self.platform.capitalize()} thread.")