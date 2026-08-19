import os
import re
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QAbstractItemView, QFileDialog, QCheckBox, QWidget
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from .ExportOptionsDialog import ExportOptionsDialog
from ...utils.resolution import get_dark_theme
from ...config.constants import AUTO_RETRY_ON_FINISH_KEY

class ErrorFilesDialog(QDialog):
    """
    Dialog to display files that were skipped due to errors and
    allows the user to retry downloading them or export the list of URLs.
    """
    retry_selected_signal = Signal(list)

    def __init__(self, error_files_info_list, parent_app, parent=None):
        super().__init__(parent)
        self.parent_app = parent_app
        self.setModal(True)
        self.error_files = error_files_info_list
        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        scale_factor = getattr(self.parent_app, 'scale_factor', 1.0)
        base_width, base_height = 600, 450
        self.setMinimumSize(int(base_width * scale_factor), int(base_height * scale_factor))
        self.resize(int(base_width * scale_factor * 1.1), int(base_height * scale_factor * 1.1))

        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()

        if hasattr(self.parent_app, 'finished_signal'):
            self.parent_app.finished_signal.connect(self._on_background_task_finished)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        main_layout.addWidget(self.info_label)

        self.files_list_widget = QListWidget()
        self.files_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files_list_widget.itemClicked.connect(self._toggle_item_check_state)
        main_layout.addWidget(self.files_list_widget)
        self._populate_list()

        buttons_layout = QHBoxLayout()

        self.select_all_button = QPushButton()
        self.select_all_button.clicked.connect(self._select_all_items)
        buttons_layout.addWidget(self.select_all_button)

        self.retry_button = QPushButton()
        self.retry_button.clicked.connect(self._handle_retry_selected)
        buttons_layout.addWidget(self.retry_button)

        self.load_button = QPushButton()
        self.load_button.clicked.connect(self._handle_load_errors_from_txt)
        buttons_layout.addWidget(self.load_button)

        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._handle_export_errors_to_txt)
        buttons_layout.addWidget(self.export_button)
        
        buttons_layout.addStretch(1)

        self.auto_retry_checkbox = QCheckBox()
        auto_retry_enabled = self.parent_app.settings.value(AUTO_RETRY_ON_FINISH_KEY, False, type=bool)
        self.auto_retry_checkbox.setChecked(auto_retry_enabled)
        self.auto_retry_checkbox.toggled.connect(self._save_auto_retry_setting)
        buttons_layout.addWidget(self.auto_retry_checkbox)
        
        self.ok_button = QPushButton()
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)
        buttons_layout.addWidget(self.ok_button)
        main_layout.addLayout(buttons_layout)

        has_errors = bool(self.error_files)
        self.select_all_button.setEnabled(has_errors)
        self.retry_button.setEnabled(has_errors)
        self.export_button.setEnabled(has_errors)

    def _populate_list(self):
        self.files_list_widget.clear()
        for error_info in self.error_files:
            self._add_item_to_list(error_info)

    def _handle_load_errors_from_txt(self):
        """Opens a file dialog to load URLs from a .txt file."""
        import re
        
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("error_files_load_dialog_title", "Load Error File URLs"),
            "",
            "Text Files (*.txt);;All Files (*)"
        )

        if not filepath:
            return

        try:
            detailed_pattern = re.compile(r"^(https?://[^\s]+)\s*\[Post: '(.*?)' \(ID: (.*?)\), File: '(.*?)'\]$")
            simple_pattern = re.compile(r'^(https?://[^\s]+)')

            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    url, post_title, post_id, filename = None, 'Loaded from .txt', 'N/A', None
                    
                    detailed_match = detailed_pattern.match(line)
                    if detailed_match:
                        url, post_title, post_id, filename = detailed_match.groups()
                    else:
                        simple_match = simple_pattern.match(line)
                        if simple_match:
                            url = simple_match.group(1)
                            filename = url.split('/')[-1]

                    if url:
                        simple_error_info = {
                            'is_loaded_from_txt': True, 'file_info': {'url': url, 'name': filename},
                            'post_title': post_title, 'original_post_id_for_log': post_id,
                            'target_folder_path': self.parent_app.dir_input.text().strip(),
                            'forced_filename_override': filename, 'file_index_in_post': 0,
                            'num_files_in_this_post': 1, 'service': None, 'user_id': None, 'api_url_input': ''
                        }
                        self.error_files.append(simple_error_info)
                        self._add_item_to_list(simple_error_info)
            
            self.info_label.setText(self._tr("error_files_found_label", "The following {count} file(s)...").format(count=len(self.error_files)))
            
            has_errors = bool(self.error_files)
            self.select_all_button.setEnabled(has_errors)
            self.retry_button.setEnabled(has_errors)
            self.export_button.setEnabled(has_errors)
            
        except Exception as e:
            QMessageBox.critical(self, self._tr("error_files_load_error_title", "Load Error"),
                                 self._tr("error_files_load_error_message", "Could not load or parse the file: {error}").format(error=str(e)))

    def _tr(self, key, default_text=""):
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        self.setWindowTitle(self._tr("error_files_dialog_title", "Files Skipped Due to Errors"))
        if not self.error_files:
            self.info_label.setText(self._tr("error_files_no_errors_label", "No files were recorded as skipped..."))
        else:
            self.info_label.setText(self._tr("error_files_found_label", "The following {count} file(s)...").format(count=len(self.error_files)))

        self.auto_retry_checkbox.setText(self._tr("error_files_auto_retry_checkbox", "Auto Retry at End"))
        self.select_all_button.setText(self._tr("error_files_select_all_button", "Select/Deselect All"))
        self.retry_button.setText(self._tr("error_files_retry_selected_button", "Retry Selected"))
        self.load_button.setText(self._tr("error_files_load_urls_button", "Load URLs from .txt"))       
        self.export_button.setText(self._tr("error_files_export_urls_button", "Export URLs to .txt"))
        self.ok_button.setText(self._tr("ok_button", "OK"))

    def _apply_theme(self):
        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")

    def _save_auto_retry_setting(self, checked):
        """Saves the state of the auto-retry checkbox to QSettings."""
        self.parent_app.settings.setValue(AUTO_RETRY_ON_FINISH_KEY, checked)

    def _add_item_to_list(self, error_info):
        """Creates and adds a single QListWidgetItem based on error_info content, with error reason on the right."""
        if error_info.get('is_loaded_from_txt'):
            filename = error_info.get('file_info', {}).get('name', 'Unknown Filename')
            post_title = error_info.get('post_title', 'N/A')
            post_id = error_info.get('original_post_id_for_log', 'N/A')
            item_text = f"<b>File:</b> {filename}<br><b>Post:</b> '{post_title}' (ID: {post_id}) [Loaded from .txt]"
        else:
            original_filename = error_info.get('file_info', {}).get('_original_name_for_log', error_info.get('file_info', {}).get('name', 'Unknown Filename'))
            saved_filename = error_info.get('forced_filename_override')
            
            if saved_filename and saved_filename != original_filename:
                file_display = f"{original_filename} ➔ <b>Saved As:</b> {saved_filename}"
            else:
                file_display = original_filename
                
            post_title = error_info.get('post_title', 'Unknown Post')
            post_id = error_info.get('original_post_id_for_log', 'N/A')
            
            service = error_info.get('service')
            user_id = error_info.get('user_id')
            
            creator_name = error_info.get('creator_name') or error_info.get('creator')
            
            if (not creator_name or str(creator_name).lower() == 'unknown creator') and service and user_id:
                if hasattr(self.parent_app, 'creator_name_cache'):
                    creator_name = self.parent_app.creator_name_cache.get((service.lower(), str(user_id)), str(user_id))
            
            if not creator_name or str(creator_name).lower() == 'unknown creator':
                override_dir = error_info.get('override_output_dir')
                if override_dir:
                    creator_name = os.path.basename(os.path.normpath(override_dir))
                else:
                    target_dir = error_info.get('target_folder_path', '')
                    if target_dir:
                        path_parts = os.path.normpath(target_dir).split(os.sep)
                        if len(path_parts) >= 2:
                            creator_name = path_parts[-2]

            if not creator_name:
                creator_name = "Unknown Creator"

            item_text = f"<b>File:</b> {file_display}<br><b>Creator:</b> {creator_name} - <b>Post:</b> '{post_title}' (ID: {post_id})"

        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        info_label = QLabel(item_text)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setWordWrap(True)
        layout.addWidget(info_label, stretch=1)

        error_reason = error_info.get('error_reason')
        if error_reason:
            error_code = str(error_reason).split(':')[0].strip()
            error_label = QLabel(f"⚠️ {error_code}")
            error_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
            error_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        widget.setLayout(layout)

        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, error_info)
        list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        list_item.setCheckState(Qt.CheckState.Unchecked)
        
        list_item.setSizeHint(QSize(0, 50))

        self.files_list_widget.addItem(list_item)
        self.files_list_widget.setItemWidget(list_item, widget)

    def _toggle_item_check_state(self, item):
        new_state = Qt.CheckState.Checked if item.checkState() == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
        item.setCheckState(new_state)
    def _select_all_items(self):
        """Toggles checking all items in the list."""
        is_currently_checked = self.files_list_widget.item(0).checkState() == Qt.CheckState.Checked if self.files_list_widget.count() > 0 else False
        new_state = Qt.CheckState.Unchecked if is_currently_checked else Qt.CheckState.Checked
        for i in range(self.files_list_widget.count()):
            self.files_list_widget.item(i).setCheckState(new_state)

    def _on_background_task_finished(self, dl_count, skip_count, is_cancelled, kept_names):
        """Re-enables the retry buttons once the background retry session finishes."""
        has_errors = self.files_list_widget.count() > 0
        self.retry_button.setEnabled(has_errors)
        self.select_all_button.setEnabled(has_errors)

    def _handle_retry_selected(self):
        if hasattr(self.parent_app, '_is_download_active') and self.parent_app._is_download_active():
            QMessageBox.warning(
                self,
                self._tr("retry_busy_title", "Busy"),
                self._tr("retry_busy_message", "A retry session or download is already in progress. Please wait for it to finish.")
            )
            return

        selected_files_for_retry = []
        
        for i in range(self.files_list_widget.count()):
            item = self.files_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                error_info = dict(item.data(Qt.ItemDataRole.UserRole))
                

                
                selected_files_for_retry.append(error_info)

        if selected_files_for_retry:
            self.retry_button.setEnabled(False)
            self.select_all_button.setEnabled(False)

            self.retry_selected_signal.emit(selected_files_for_retry)
            self.accept()
        else:
            QMessageBox.information(self, self._tr("fav_artists_no_selection_title", "No Selection"),
                                    self._tr("error_files_no_selection_retry_message", "Please check the box next to at least one file to retry."))
                                       
    def _handle_export_errors_to_txt(self):
        """Exports the URLs of failed files to a text file."""
        if not self.error_files:
            QMessageBox.information(
                self,
                self._tr("error_files_no_errors_export_title", "No Errors"),
                self._tr("error_files_no_errors_export_message", "There are no error file URLs to export.")
            )
            return

        options_dialog = ExportOptionsDialog(parent_app=self.parent_app, parent=self)
        if not options_dialog.exec() == QDialog.DialogCode.Accepted:
            return

        export_option = options_dialog.get_selected_option()

        lines_to_export = []
        for error_item in self.error_files:
            file_info = error_item.get('file_info', {})
            url = file_info.get('url')

            if url:
                if export_option == ExportOptionsDialog.EXPORT_MODE_WITH_DETAILS:
                    post_title = error_item.get('post_title', 'Unknown Post')
                    post_id = error_item.get('original_post_id_for_log', 'N/A')
                    
                    filename_to_display = error_item.get('forced_filename_override') or file_info.get('name', 'Unknown Filename')
                    
                    details_string = f" [Post: '{post_title}' (ID: {post_id}), File: '{filename_to_display}']"
                    lines_to_export.append(f"{url}{details_string}")
                else:
                    lines_to_export.append(url)

        if not lines_to_export:
            QMessageBox.information(
                self,
                self._tr("error_files_no_urls_found_export_title", "No URLs Found"),
                self._tr("error_files_no_urls_found_export_message", "Could not extract any URLs...")
            )
            return

        default_filename = "error_file_links.txt"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("error_files_save_dialog_title", "Save Error File URLs"),
            default_filename,
            "Text Files (*.txt);;All Files (*)"
        )

        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    for line in lines_to_export:
                        f.write(f"{line}\n")
                QMessageBox.information(
                    self,
                    self._tr("error_files_export_success_title", "Export Successful"),
                    self._tr("error_files_export_success_message", "Successfully exported...").format(
                        count=len(lines_to_export), filepath=filepath
                    )
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self._tr("error_files_export_error_title", "Export Error"),
                    self._tr("error_files_export_error_message", "Could not export...").format(error=str(e))
                )