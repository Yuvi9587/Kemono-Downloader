from PySide6.QtCore import QThread, Signal

from ...services.drive_downloader import (
    download_dropbox_file,
    download_gdrive_file,
    download_mega_file as drive_download_mega_file,
)


class ExternalLinkDownloadThread(QThread):
    """A QThread to handle downloading multiple external links sequentially."""
    progress_signal = Signal(str)
    file_complete_signal = Signal(str, bool)
    finished_signal = Signal()
    overall_progress_signal = Signal(int, int)
    file_progress_signal = Signal(str, object)

    def __init__(self, tasks_to_download, download_base_path, parent_logger_func, parent=None, use_post_subfolder=False):
        super().__init__(parent)
        self.tasks = tasks_to_download
        self.download_base_path = download_base_path
        self.parent_logger_func = parent_logger_func
        self.is_cancelled = False
        self.use_post_subfolder = use_post_subfolder

    def run(self):
        total_tasks = len(self.tasks)
        self.progress_signal.emit(f"ℹ️ Starting external link download thread for {total_tasks} link(s).")
        self.overall_progress_signal.emit(total_tasks, 0)

        for i, task_info in enumerate(self.tasks):
            if self.is_cancelled:
                self.progress_signal.emit("External link download cancelled by user.")
                break

            self.overall_progress_signal.emit(total_tasks, i + 1)
            
            platform = task_info.get('platform', 'unknown').lower()
            full_url = task_info['url']
            post_title = task_info['title']

            self.progress_signal.emit(f"Download ({i + 1}/{total_tasks}): Starting '{post_title}' ({platform.upper()}) from {full_url}")

            try:
                if platform == 'mega':
                    drive_download_mega_file(
                        full_url,
                        self.download_base_path,
                        logger_func=self.parent_logger_func,
                        progress_callback_func=self.file_progress_signal.emit,
                        overall_progress_callback=self.overall_progress_signal.emit
                    )
                elif platform == 'google drive':
                    download_gdrive_file(
                        full_url,
                        self.download_base_path,
                        logger_func=self.parent_logger_func,
                        progress_callback_func=self.file_progress_signal.emit,
                        overall_progress_callback=self.overall_progress_signal.emit,
                        use_post_subfolder=self.use_post_subfolder,
                        post_title=post_title
                    )
                elif platform == 'dropbox':
                    download_dropbox_file(
                        full_url,
                        self.download_base_path,
                        logger_func=self.parent_logger_func,
                        progress_callback_func=self.file_progress_signal.emit,
                        use_post_subfolder=self.use_post_subfolder,
                        post_title=post_title
                    )
                else:
                    self.progress_signal.emit(f"⚠️ Unsupported platform '{platform}' for link: {full_url}")
                    self.file_complete_signal.emit(full_url, False)
                    continue
                self.file_complete_signal.emit(full_url, True)
            except Exception as e:
                self.progress_signal.emit(f"❌ Error downloading ({platform.upper()}) link '{full_url}': {e}")
                self.file_complete_signal.emit(full_url, False)

        self.finished_signal.emit()

    def cancel(self):
        """Sets the cancellation flag to stop the thread gracefully."""
        self.progress_signal.emit("   [External Links] Cancellation signal received by thread.")
        self.is_cancelled = True