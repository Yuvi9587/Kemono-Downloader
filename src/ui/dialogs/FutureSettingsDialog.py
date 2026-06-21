import os
import json
import sys

from PyQt5.QtCore import Qt, QStandardPaths, QTimer
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QGroupBox, QComboBox, QMessageBox, QGridLayout, QCheckBox, QLineEdit,
    QTabWidget, QWidget, QFileDialog
)
from ...i18n.translator import get_translation
from ...utils.resolution import get_dark_theme
from ..assets import get_app_icon_object

from ..main_window import get_app_icon_object
from ...config.constants import (
    THEME_KEY, LANGUAGE_KEY, DOWNLOAD_LOCATION_KEY,
    RESOLUTION_KEY, UI_SCALE_KEY, SAVE_CREATOR_JSON_KEY,
    DATE_PREFIX_FORMAT_KEY, 
    COOKIE_TEXT_KEY, USE_COOKIE_KEY,
    FETCH_FIRST_KEY, DISCORD_TOKEN_KEY, POST_DOWNLOAD_ACTION_KEY,
    PROXY_ENABLED_KEY, PROXY_HOST_KEY, PROXY_PORT_KEY, 
    PROXY_USERNAME_KEY, PROXY_PASSWORD_KEY, CREATE_DATABASE_KEY
)
from ...services.updater import UpdateChecker, UpdateDownloader, PatchDownloader

class CountdownMessageBox(QDialog):
    """
    A custom message box that includes a countdown timer for the 'Yes' button,
    which automatically accepts the dialog when the timer reaches zero.
    """
    def __init__(self, title, text, countdown_seconds=10, parent_app=None, parent=None):
        super().__init__(parent)
        self.parent_app = parent_app
        self.countdown = countdown_seconds
        
        self.setWindowTitle(title)
        self.setModal(True)
        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)
        
        self._init_ui(text)
        self._apply_theme()
        
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._update_countdown)
        self.timer.start()

    def _init_ui(self, text):
        """Initializes the UI components of the dialog."""
        main_layout = QVBoxLayout(self)
        
        self.message_label = QLabel(text)
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.message_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)

        self.yes_button = QPushButton()
        self.yes_button.clicked.connect(self.accept)
        self.yes_button.setDefault(True)
        
        self.no_button = QPushButton()
        self.no_button.clicked.connect(self.reject)

        buttons_layout.addWidget(self.yes_button)
        buttons_layout.addWidget(self.no_button)
        buttons_layout.addStretch(1)
        
        main_layout.addLayout(buttons_layout)
        
        self._retranslate_ui()
        self._update_countdown()

    def _tr(self, key, default_text=""):
        """Helper for translations."""
        if self.parent_app and hasattr(self.parent_app, 'current_selected_language'):
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets translated text for UI elements."""
        self.no_button.setText(self._tr("no_button_text", "No"))
        
    def _update_countdown(self):
        """Updates the countdown and button text each second."""
        if self.countdown <= 0:
            self.timer.stop()
            self.accept()
            return
            
        yes_text = self._tr("yes_button_text", "Yes")
        self.yes_button.setText(f"{yes_text} ({self.countdown})")
        self.countdown -= 1

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and hasattr(self.parent_app, 'current_theme') and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")

class FutureSettingsDialog(QDialog):
    """
    A dialog for managing application-wide settings like theme, language,
    and display options, using a tabbed layout.
    """
    def __init__(self, parent_app_ref, parent=None):
        super().__init__(parent)
        self.parent_app = parent_app_ref
        self.setModal(True)
        self.update_downloader_thread = None 

        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        screen_height = QApplication.primaryScreen().availableGeometry().height() if QApplication.primaryScreen() else 800
        scale_factor = screen_height / 1000.0 
        base_min_w, base_min_h = 550, 450
        scaled_min_w = int(base_min_w * scale_factor)
        scaled_min_h = int(base_min_h * scale_factor)
        self.setMinimumSize(scaled_min_w, scaled_min_h)

        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()
        
        self._load_proxy_settings()

    def _init_ui(self):
        """Initializes all UI components and layouts for the dialog."""
        main_layout = QVBoxLayout(self)
        
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.display_tab = QWidget()
        self.downloads_tab = QWidget()
        self.network_tab = QWidget()
        self.updates_tab = QWidget()

        self.tab_widget.addTab(self.display_tab, "Display")
        self.tab_widget.addTab(self.downloads_tab, "Downloads")
        self.tab_widget.addTab(self.network_tab, "Proxy/Network")
        
        tab_name = "Updates 🟢" if getattr(self.parent_app, 'patch_update_available', False) else "Updates"
        self.tab_widget.addTab(self.updates_tab, tab_name)

        display_tab_layout = QVBoxLayout(self.display_tab)
        self.display_group_box = QGroupBox()
        display_layout = QGridLayout(self.display_group_box)

        self.theme_label = QLabel()
        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.clicked.connect(self._toggle_theme)
        display_layout.addWidget(self.theme_label, 0, 0)
        display_layout.addWidget(self.theme_toggle_button, 0, 1)

        self.ui_scale_label = QLabel()
        self.ui_scale_combo_box = QComboBox()
        self.ui_scale_combo_box.currentIndexChanged.connect(self._display_setting_changed)
        display_layout.addWidget(self.ui_scale_label, 1, 0)
        display_layout.addWidget(self.ui_scale_combo_box, 1, 1)

        self.language_label = QLabel()
        self.language_combo_box = QComboBox()
        self.language_combo_box.currentIndexChanged.connect(self._language_selection_changed)
        display_layout.addWidget(self.language_label, 2, 0)
        display_layout.addWidget(self.language_combo_box, 2, 1)

        self.window_size_label = QLabel()
        self.resolution_combo_box = QComboBox()
        self.resolution_combo_box.currentIndexChanged.connect(self._display_setting_changed)
        display_layout.addWidget(self.window_size_label, 3, 0)
        display_layout.addWidget(self.resolution_combo_box, 3, 1)
        
        display_tab_layout.addWidget(self.display_group_box)
        display_tab_layout.addStretch(1) 

        downloads_tab_layout = QVBoxLayout(self.downloads_tab)
        self.download_settings_group_box = QGroupBox()
        download_settings_layout = QGridLayout(self.download_settings_group_box)

        self.default_path_label = QLabel()
        self.save_path_button = QPushButton()
        self.save_path_button.clicked.connect(self._save_settings)
        download_settings_layout.addWidget(self.default_path_label, 0, 0)
        download_settings_layout.addWidget(self.save_path_button, 0, 1)

        self.post_download_action_label = QLabel()
        self.post_download_action_combo = QComboBox()
        self.post_download_action_combo.currentIndexChanged.connect(self._post_download_action_changed)
        download_settings_layout.addWidget(self.post_download_action_label, 1, 0)
        download_settings_layout.addWidget(self.post_download_action_combo, 1, 1)

        self.date_prefix_format_label = QLabel()
        self.date_prefix_format_input = QLineEdit()
        self.date_prefix_format_input.textChanged.connect(self._date_prefix_format_changed)
        download_settings_layout.addWidget(self.date_prefix_format_label, 2, 0)
        download_settings_layout.addWidget(self.date_prefix_format_input, 2, 1)

        self.save_creator_json_checkbox = QCheckBox()
        self.save_creator_json_checkbox.stateChanged.connect(self._creator_json_setting_changed)
        download_settings_layout.addWidget(self.save_creator_json_checkbox, 3, 0, 1, 2)
        
        self.fetch_first_checkbox = QCheckBox()
        self.fetch_first_checkbox.stateChanged.connect(self._fetch_first_setting_changed)
        download_settings_layout.addWidget(self.fetch_first_checkbox, 4, 0, 1, 2)

        self.create_database_checkbox = QCheckBox()
        self.create_database_checkbox.stateChanged.connect(self._create_database_setting_changed)
        download_settings_layout.addWidget(self.create_database_checkbox, 5, 0, 1, 2)

        settings_file_layout = QHBoxLayout()
        self.load_settings_button = QPushButton()
        self.save_settings_button = QPushButton()
        settings_file_layout.addWidget(self.load_settings_button)
        settings_file_layout.addWidget(self.save_settings_button)
        settings_file_layout.addStretch(1)
        
        download_settings_layout.addLayout(settings_file_layout, 6, 0, 1, 2)
        
        self.load_settings_button.clicked.connect(self._handle_load_settings)
        self.save_settings_button.clicked.connect(self._handle_save_settings)

        downloads_tab_layout.addWidget(self.download_settings_group_box)
        downloads_tab_layout.addStretch(1) 

        network_tab_layout = QVBoxLayout(self.network_tab)
        self.proxy_group_box = QGroupBox()
        proxy_layout = QGridLayout(self.proxy_group_box)

        self.proxy_enabled_checkbox = QCheckBox()
        self.proxy_enabled_checkbox.stateChanged.connect(self._proxy_setting_changed)
        proxy_layout.addWidget(self.proxy_enabled_checkbox, 0, 0, 1, 2)

        self.proxy_type_label = QLabel("Proxy Type:") 
        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["HTTP", "SOCKS4", "SOCKS5"])
        self.proxy_type_combo.currentIndexChanged.connect(self._proxy_setting_changed)
        proxy_layout.addWidget(self.proxy_type_label, 1, 0)
        proxy_layout.addWidget(self.proxy_type_combo, 1, 1)


        self.proxy_host_label = QLabel()
        self.proxy_host_input = QLineEdit()
        self.proxy_host_input.setPlaceholderText("127.0.0.1")
        self.proxy_host_input.editingFinished.connect(self._proxy_setting_changed)
        proxy_layout.addWidget(self.proxy_host_label, 2, 0)
        proxy_layout.addWidget(self.proxy_host_input, 2, 1)

        self.proxy_port_label = QLabel()
        self.proxy_port_input = QLineEdit()
        self.proxy_port_input.setPlaceholderText("8080")
        self.proxy_port_input.setValidator(QIntValidator(1, 65535, self))
        self.proxy_port_input.editingFinished.connect(self._proxy_setting_changed)
        proxy_layout.addWidget(self.proxy_port_label, 3, 0)
        proxy_layout.addWidget(self.proxy_port_input, 3, 1)

        self.proxy_user_label = QLabel()
        self.proxy_user_input = QLineEdit()
        self.proxy_user_input.setPlaceholderText("(Optional)")
        self.proxy_user_input.editingFinished.connect(self._proxy_setting_changed)
        proxy_layout.addWidget(self.proxy_user_label, 4, 0)
        proxy_layout.addWidget(self.proxy_user_input, 4, 1)

        self.proxy_pass_label = QLabel()
        self.proxy_pass_input = QLineEdit()
        self.proxy_pass_input.setPlaceholderText("(Optional)")
        self.proxy_pass_input.setEchoMode(QLineEdit.Password)
        self.proxy_pass_input.editingFinished.connect(self._proxy_setting_changed)
        proxy_layout.addWidget(self.proxy_pass_label, 5, 0)
        proxy_layout.addWidget(self.proxy_pass_input, 5, 1)

        network_tab_layout.addWidget(self.proxy_group_box)
        network_tab_layout.addStretch(1)

        updates_tab_layout = QVBoxLayout(self.updates_tab)
        self.update_group_box = QGroupBox()
        update_layout = QGridLayout(self.update_group_box)
        self.version_label = QLabel()
        self.update_status_label = QLabel()
        self.check_update_button = QPushButton()
        self.check_update_button.clicked.connect(self._check_for_updates)
        update_layout.addWidget(self.version_label, 0, 0)
        update_layout.addWidget(self.update_status_label, 0, 1)
        update_layout.addWidget(self.check_update_button, 1, 0, 1, 2)
        updates_tab_layout.addWidget(self.update_group_box)
        
        # Patch Update Section
        self.patch_update_group_box = QGroupBox("Fast Patch Update (EXE Only)")
        patch_layout = QGridLayout(self.patch_update_group_box)
        self.patch_status_label = QLabel()
        self.download_patch_button = QPushButton("Download and Apply Patch")
        self.download_patch_button.clicked.connect(self._start_patch_download)
        
        if getattr(self.parent_app, 'patch_update_available', False):
            self.patch_status_label.setText("🟢 A fast patch update is available!")
            self.download_patch_button.setEnabled(True)
        else:
            self.patch_status_label.setText("You are on the latest patch.")
            self.download_patch_button.setEnabled(False)
            self.patch_update_group_box.setVisible(False)
            
        patch_layout.addWidget(self.patch_status_label, 0, 0)
        patch_layout.addWidget(self.download_patch_button, 1, 0)
        updates_tab_layout.addWidget(self.patch_update_group_box)

        updates_tab_layout.addStretch(1)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.ok_button = QPushButton()
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        main_layout.addLayout(button_layout)


    def _retranslate_ui(self):
        self.setWindowTitle(self._tr("settings_dialog_title", "Settings"))
        
        self.tab_widget.setTabText(0, self._tr("settings_tab_display", "Display"))
        self.tab_widget.setTabText(1, self._tr("settings_tab_downloads", "Downloads"))
        self.tab_widget.setTabText(2, self._tr("settings_tab_network", "Proxy/Network"))
        self.tab_widget.setTabText(3, self._tr("settings_tab_updates", "Updates"))

        self.display_group_box.setTitle(self._tr("display_settings_group_title", "Display Settings"))
        self.theme_label.setText(self._tr("theme_label", "Theme:"))
        self.ui_scale_label.setText(self._tr("ui_scale_label", "UI Scale:"))
        self.language_label.setText(self._tr("language_label", "Language:"))
        self.window_size_label.setText(self._tr("window_size_label", "Window Size:"))

        self.download_settings_group_box.setTitle(self._tr("download_settings_group_title", "Download Settings"))
        self.default_path_label.setText(self._tr("default_path_label", "Default Path:"))
        self.date_prefix_format_label.setText(self._tr("date_prefix_format_label", "Post Subfolder Format:"))
        self.date_prefix_format_input.setPlaceholderText(self._tr("date_prefix_format_placeholder", "e.g., YYYY-MM-DD {post} {postid}"))
        self.date_prefix_format_input.setToolTip(self._tr(
            "date_prefix_format_tooltip", 
            "Create a custom folder name using placeholders:\n"
            "• YYYY, MM, DD: for the date\n"
            "• {post}: for the post title\n"
            "• {postid}: for the post's unique ID\n\n"
            "Example: {post} [{postid}] [YYYY-MM-DD]"
        ))
        self.post_download_action_label.setText(self._tr("post_download_action_label", "Action After Download:"))
        self.save_creator_json_checkbox.setText(self._tr("save_creator_json_label", "Save Creator.json file"))
        self.fetch_first_checkbox.setText(self._tr("fetch_first_label", "Fetch First (Download after all pages are found)"))
        self.fetch_first_checkbox.setToolTip(self._tr("fetch_first_tooltip", "If checked, the downloader will find all posts from a creator first before starting any downloads.\nThis can be slower to start but provides a more accurate progress bar."))
        
        self.create_database_checkbox.setText(self._tr("create_database_label", "Create library.db"))
        self.create_database_checkbox.setToolTip(self._tr("create_database_tooltip", "If checked, the app will create and record downloads in library.db. If unchecked, the database feature is disabled."))

        self.save_path_button.setText(self._tr("settings_save_all_button", "Save Path + Cookie + Token"))
        self.save_path_button.setToolTip(self._tr("settings_save_all_tooltip", "Save the current 'Download Location', Cookie, and Discord Token settings for future sessions."))
        self.load_settings_button.setText(self._tr("load_settings_button", "Load Settings..."))
        self.load_settings_button.setToolTip(self._tr("load_settings_tooltip", "Load all download settings from a .json file."))
        self.save_settings_button.setText(self._tr("save_settings_button", "Save Settings..."))
        self.save_settings_button.setToolTip(self._tr("save_settings_tooltip", "Save all current download settings to a .json file."))
        
        self.proxy_group_box.setTitle(self._tr("proxy_settings_group_title", "Proxy Configuration"))
        self.proxy_enabled_checkbox.setText(self._tr("proxy_enabled_label", "Enable Proxy"))
        self.proxy_host_label.setText(self._tr("proxy_host_label", "Host / IP:"))
        self.proxy_port_label.setText(self._tr("proxy_port_label", "Port:"))
        self.proxy_user_label.setText(self._tr("proxy_user_label", "Username (Optional):"))
        self.proxy_pass_label.setText(self._tr("proxy_pass_label", "Password (Optional):"))

        self.update_group_box.setTitle(self._tr("update_group_title", "Application Updates"))
        current_version = self.parent_app.windowTitle().split(' v')[-1]
        self.version_label.setText(self._tr("current_version_label", f"Current Version: v{current_version}"))
        self.update_status_label.setText(self._tr("update_status_ready", "Ready to check."))
        self.check_update_button.setText(self._tr("check_for_updates_button", "Check for Updates"))

        self._update_theme_toggle_button_text()
        self.ok_button.setText(self._tr("ok_button", "OK"))
        
        self._populate_display_combo_boxes()
        self._populate_language_combo_box()
        self._populate_post_download_action_combo()
        self._load_date_prefix_format()
        self._load_checkbox_states()

    def _load_proxy_settings(self):
        """Loads proxy settings from QSettings into the UI."""
        self.proxy_enabled_checkbox.blockSignals(True)
        self.proxy_type_combo.blockSignals(True)
        self.proxy_host_input.blockSignals(True)
        self.proxy_port_input.blockSignals(True)
        self.proxy_user_input.blockSignals(True)
        self.proxy_pass_input.blockSignals(True)

        enabled = self.parent_app.settings.value(PROXY_ENABLED_KEY, False, type=bool)
        proxy_type = self.parent_app.settings.value("proxy_type", "HTTP", type=str)
        host = self.parent_app.settings.value(PROXY_HOST_KEY, "", type=str)
        port = self.parent_app.settings.value(PROXY_PORT_KEY, "", type=str)
        user = self.parent_app.settings.value(PROXY_USERNAME_KEY, "", type=str)
        password = self.parent_app.settings.value(PROXY_PASSWORD_KEY, "", type=str)

        self.proxy_enabled_checkbox.setChecked(enabled)
        
        index = self.proxy_type_combo.findText(proxy_type)
        if index >= 0:
            self.proxy_type_combo.setCurrentIndex(index)
        else:
            self.proxy_type_combo.setCurrentIndex(0)

        self.proxy_host_input.setText(host)
        self.proxy_port_input.setText(port)
        self.proxy_user_input.setText(user)
        self.proxy_pass_input.setText(password)

        self._update_proxy_fields_state(enabled)

        self.proxy_enabled_checkbox.blockSignals(False)
        self.proxy_type_combo.blockSignals(False)
        self.proxy_host_input.blockSignals(False)
        self.proxy_port_input.blockSignals(False)
        self.proxy_user_input.blockSignals(False)
        self.proxy_pass_input.blockSignals(False)

    def _proxy_setting_changed(self):
        """Saves the current proxy UI state to QSettings."""
        enabled = self.proxy_enabled_checkbox.isChecked()
        proxy_type = self.proxy_type_combo.currentText()
        host = self.proxy_host_input.text().strip()
        port = self.proxy_port_input.text().strip()
        user = self.proxy_user_input.text().strip()
        password = self.proxy_pass_input.text().strip()

        self.parent_app.settings.setValue(PROXY_ENABLED_KEY, enabled)
        self.parent_app.settings.setValue("proxy_type", proxy_type)
        self.parent_app.settings.setValue(PROXY_HOST_KEY, host)
        self.parent_app.settings.setValue(PROXY_PORT_KEY, port)
        self.parent_app.settings.setValue(PROXY_USERNAME_KEY, user)
        self.parent_app.settings.setValue(PROXY_PASSWORD_KEY, password)
        
        self.parent_app.settings.sync()

        self._update_proxy_fields_state(enabled)
        

    def _update_proxy_fields_state(self, enabled):
        """Enables or disables input fields based on the checkbox."""
        self.proxy_type_combo.setEnabled(enabled)
        self.proxy_host_input.setEnabled(enabled)
        self.proxy_port_input.setEnabled(enabled)
        self.proxy_user_input.setEnabled(enabled)
        self.proxy_pass_input.setEnabled(enabled)

    def _check_for_updates(self):
        self.check_update_button.setEnabled(False)
        self.update_status_label.setText(self._tr("update_status_checking", "Checking..."))
        current_version = self.parent_app.windowTitle().split(' v')[-1]
        
        self.update_checker_thread = UpdateChecker(current_version)
        self.update_checker_thread.update_available.connect(self._on_update_available)
        self.update_checker_thread.up_to_date.connect(self._on_up_to_date)
        self.update_checker_thread.update_error.connect(self._on_update_error)
        self.update_checker_thread.start()

    def _on_update_available(self, new_version, download_url):
        self.update_status_label.setText(self._tr("update_status_found", f"Update found: v{new_version}"))
        self.check_update_button.setEnabled(True)
        
        reply = QMessageBox.question(self, self._tr("update_available_title", "Update Available"),
                                     self._tr("update_available_message", f"A new version (v{new_version}) is available.\nWould you like to download and install it now?"),
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.ok_button.setEnabled(False)
            self.check_update_button.setEnabled(False)
            self.update_status_label.setText(self._tr("update_status_downloading", "Downloading update..."))
            self.update_downloader_thread = UpdateDownloader(download_url, self.parent_app)
            self.update_downloader_thread.download_finished.connect(self._on_download_finished)
            self.update_downloader_thread.download_error.connect(self._on_update_error)
            self.update_downloader_thread.start()

    def _on_download_finished(self):
        QApplication.instance().quit()
    
    def _on_up_to_date(self, message):
        self.update_status_label.setText(self._tr("update_status_latest", message))
        self.check_update_button.setEnabled(True)
    
    def _on_update_error(self, message):
        self.update_status_label.setText(self._tr("update_status_error", f"Error: {message}"))
        self.check_update_button.setEnabled(True)
        self.ok_button.setEnabled(True)

    def _load_checkbox_states(self):
        self.save_creator_json_checkbox.blockSignals(True)
        should_save = self.parent_app.settings.value(SAVE_CREATOR_JSON_KEY, True, type=bool)
        self.save_creator_json_checkbox.setChecked(should_save)
        self.save_creator_json_checkbox.blockSignals(False)

        self.fetch_first_checkbox.blockSignals(True)
        should_fetch_first = self.parent_app.settings.value(FETCH_FIRST_KEY, False, type=bool)
        self.fetch_first_checkbox.setChecked(should_fetch_first)
        self.fetch_first_checkbox.blockSignals(False)

        self.create_database_checkbox.blockSignals(True)
        should_create_db = self.parent_app.settings.value(CREATE_DATABASE_KEY, True, type=bool)
        self.create_database_checkbox.setChecked(should_create_db)
        self.create_database_checkbox.blockSignals(False)

    def _creator_json_setting_changed(self, state):
        is_checked = state == Qt.Checked
        self.parent_app.settings.setValue(SAVE_CREATOR_JSON_KEY, is_checked)
        self.parent_app.settings.sync()

    def _fetch_first_setting_changed(self, state):
        is_checked = state == Qt.Checked
        self.parent_app.settings.setValue(FETCH_FIRST_KEY, is_checked)
        self.parent_app.settings.sync()

    def _create_database_setting_changed(self, state):
        is_checked = state == Qt.Checked
        self.parent_app.settings.setValue(CREATE_DATABASE_KEY, is_checked)
        self.parent_app.settings.sync()

    def _tr(self, key, default_text=""):
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _apply_theme(self):
        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            base_stylesheet = get_dark_theme(scale)
            
            tab_stylesheet = """
                QTabWidget::pane {
                    border-top: 1px solid #444;
                    margin-top: -1px; /* Overlap with tab bar */
                    background-color: #2D2D2D;
                }
                QTabBar::tab {
                    background-color: #3D3D3D;
                    color: #BBBBBB;
                    border: 1px solid #444;
                    border-bottom: none; /* No bottom border for tabs */
                    padding: 6px 12px;
                    margin-right: 2px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background-color: #2D2D2D; /* Same as pane background */
                    color: #EEEEEE;
                    border-bottom: 1px solid #2D2D2D; /* Hides the pane top border */
                    margin-bottom: -1px; /* Pulls tab down to cover pane border */
                }
                QTabBar::tab:!selected:hover {
                    background-color: #4A4A4A;
                }
            """
            
            self.setStyleSheet(base_stylesheet + tab_stylesheet)
        else:
            self.setStyleSheet("")

    def _update_theme_toggle_button_text(self):
        if self.parent_app.current_theme == "dark":
            self.theme_toggle_button.setText(self._tr("theme_toggle_light", "Switch to Light Mode"))
        else:
            self.theme_toggle_button.setText(self._tr("theme_toggle_dark", "Switch to Dark Mode"))

    def _toggle_theme(self):
        new_theme = "light" if self.parent_app.current_theme == "dark" else "dark"
        self.parent_app.settings.setValue(THEME_KEY, new_theme)
        self.parent_app.settings.sync()
        self.parent_app.current_theme = new_theme
        self._apply_theme()
        if hasattr(self.parent_app, '_apply_theme_and_restart_prompt'):
            self.parent_app._apply_theme_and_restart_prompt()

    def _populate_display_combo_boxes(self):
        self.resolution_combo_box.blockSignals(True)
        self.resolution_combo_box.clear()
        resolutions = [("Auto", "Auto"), ("1280x720", "1280x720"), ("1600x900", "1600x900"), ("1920x1080", "1920x1080")]
        current_res = self.parent_app.settings.value(RESOLUTION_KEY, "Auto")
        for res_key, res_name in resolutions:
            self.resolution_combo_box.addItem(res_name, res_key)
            if current_res == res_key:
                self.resolution_combo_box.setCurrentIndex(self.resolution_combo_box.count() - 1)
        self.resolution_combo_box.blockSignals(False)

        self.ui_scale_combo_box.blockSignals(True)
        self.ui_scale_combo_box.clear()
        scales = [
            (0.5, "50%"), (0.7, "70%"), (0.9, "90%"), (1.0, "100% (Default)"),
            (1.25, "125%"), (1.50, "150%"), (1.75, "175%"), (2.0, "200%")
        ]
        current_scale = self.parent_app.settings.value(UI_SCALE_KEY, 1.0)
        for scale_val, scale_name in scales:
            self.ui_scale_combo_box.addItem(scale_name, scale_val)
            if abs(float(current_scale) - scale_val) < 0.01:
                self.ui_scale_combo_box.setCurrentIndex(self.ui_scale_combo_box.count() - 1)
        self.ui_scale_combo_box.blockSignals(False)

    def _display_setting_changed(self):
        selected_res = self.resolution_combo_box.currentData()
        selected_scale = self.ui_scale_combo_box.currentData()
        self.parent_app.settings.setValue(RESOLUTION_KEY, selected_res)
        self.parent_app.settings.setValue(UI_SCALE_KEY, selected_scale)
        self.parent_app.settings.sync()
        QMessageBox.information(self, self._tr("display_change_title", "Display Settings Changed"),
                                self._tr("language_change_message", "A restart is required..."))

    def _populate_language_combo_box(self):
        self.language_combo_box.blockSignals(True)
        self.language_combo_box.clear()
        languages = [
            ("en", "English"), ("ja", "日本語 (Japanese)"), ("fr", "Français (French)"),
            ("de", "Deutsch (German)"), ("es", "Español (Spanish)"), ("pt", "Português (Portuguese)"),
            ("ru", "Русский (Russian)"), ("zh_CN", "简体中文 (Simplified Chinese)"),
            ("zh_TW", "繁體中文 (Traditional Chinese)"), ("ko", "한국어 (Korean)")
        ]
        current_lang = self.parent_app.current_selected_language
        for lang_code, lang_name in languages:
            self.language_combo_box.addItem(lang_name, lang_code)
            if current_lang == lang_code:
                self.language_combo_box.setCurrentIndex(self.language_combo_box.count() - 1)
        self.language_combo_box.blockSignals(False)

    def _language_selection_changed(self, index):
        selected_lang_code = self.language_combo_box.itemData(index)
        if selected_lang_code and selected_lang_code != self.parent_app.current_selected_language:
            self.parent_app.settings.setValue(LANGUAGE_KEY, selected_lang_code)
            self.parent_app.settings.sync()
            self.parent_app.current_selected_language = selected_lang_code
            self._retranslate_ui()
            if hasattr(self.parent_app, '_retranslate_main_ui'):
                self.parent_app._retranslate_main_ui()
            QMessageBox.information(self, self._tr("language_change_title", "Language Changed"),
                                    self._tr("language_change_message", "A restart is required..."))

    def _populate_post_download_action_combo(self):
        """Populates the action dropdown and sets the current selection from settings."""
        self.post_download_action_combo.blockSignals(True)
        self.post_download_action_combo.clear()
        
        actions = [
            (self._tr("action_off", "Off"), "off"),
            (self._tr("action_notify", "Notify with Sound"), "notify"),
            (self._tr("action_sleep", "Sleep"), "sleep"),
            (self._tr("action_shutdown", "Shutdown"), "shutdown")
        ]
        
        current_action = self.parent_app.settings.value(POST_DOWNLOAD_ACTION_KEY, "off")
        
        for text, key in actions:
            self.post_download_action_combo.addItem(text, key)
            if current_action == key:
                self.post_download_action_combo.setCurrentIndex(self.post_download_action_combo.count() - 1)
        
        self.post_download_action_combo.blockSignals(False)

    def _post_download_action_changed(self):
        """Saves the selected post-download action to settings."""
        selected_action = self.post_download_action_combo.currentData()
        self.parent_app.settings.setValue(POST_DOWNLOAD_ACTION_KEY, selected_action)
        self.parent_app.settings.sync()

    def _load_date_prefix_format(self):
        """Loads the saved date prefix format and sets it in the input field."""
        self.date_prefix_format_input.blockSignals(True)
        current_format = self.parent_app.settings.value(DATE_PREFIX_FORMAT_KEY, "YYYY-MM-DD {post}", type=str)
        self.date_prefix_format_input.setText(current_format)
        self.date_prefix_format_input.blockSignals(False)

    def _date_prefix_format_changed(self, text):
        """Saves the date prefix format whenever it's changed."""
        self.parent_app.settings.setValue(DATE_PREFIX_FORMAT_KEY, text)
        self.parent_app.settings.sync()
        if hasattr(self.parent_app, 'date_prefix_format'):
            self.parent_app.date_prefix_format = text

    def _save_settings(self):
        path_saved = False
        cookie_saved = False
        token_saved = False

        if hasattr(self.parent_app, 'dir_input') and self.parent_app.dir_input:
            current_path = self.parent_app.dir_input.text().strip()
            if current_path and os.path.isdir(current_path):
                self.parent_app.settings.setValue(DOWNLOAD_LOCATION_KEY, current_path)
                path_saved = True
        
        if hasattr(self.parent_app, 'use_cookie_checkbox'):
            use_cookie = self.parent_app.use_cookie_checkbox.isChecked()
            cookie_content = self.parent_app.cookie_text_input.text().strip()
            if use_cookie and cookie_content:
                self.parent_app.settings.setValue(USE_COOKIE_KEY, True)
                self.parent_app.settings.setValue(COOKIE_TEXT_KEY, cookie_content)
                cookie_saved = True
            else:
                self.parent_app.settings.setValue(USE_COOKIE_KEY, False)
                self.parent_app.settings.setValue(COOKIE_TEXT_KEY, "")
        
        if (hasattr(self.parent_app, 'remove_from_filename_input') and
                hasattr(self.parent_app, 'remove_from_filename_label_widget')):
            
            label_text = self.parent_app.remove_from_filename_label_widget.text()
            if "Token" in label_text:
                discord_token = self.parent_app.remove_from_filename_input.text().strip()
                if discord_token:
                    self.parent_app.settings.setValue(DISCORD_TOKEN_KEY, discord_token)
                    token_saved = True
        
        self.parent_app.settings.sync()

        if path_saved or cookie_saved or token_saved:
            QMessageBox.information(self, "Settings Saved", "Settings have been saved successfully.")
        else:
            QMessageBox.warning(self, "Nothing to Save", "No valid settings were found to save.")

    def _get_settings_dir(self):
        """Helper to get a consistent directory for saving/loading profiles."""
        if hasattr(self.parent_app, 'user_data_path'):
            settings_dir = os.path.join(self.parent_app.user_data_path, "settings_profiles")
            os.makedirs(settings_dir, exist_ok=True)
            return settings_dir
        return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)

    def _handle_save_settings(self):
        """
        Calls the main app to get all settings, then saves them to a user-chosen JSON file.
        """
        if not hasattr(self.parent_app, '_get_current_ui_settings_as_dict'):
            QMessageBox.critical(self, self._tr("generic_error_title", "Error"),
                                 self._tr("settings_missing_save_func_error", "Parent application is missing the required save function."))
            return

        settings_dir = self._get_settings_dir()
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("save_settings_dialog_title", "Save Settings Profile"),
            settings_dir,
            self._tr("json_files_filter", "JSON Files (*.json)")
        )
        
        if filepath:
            if not filepath.endswith('.json'):
                filepath += '.json'
            
            try:
                settings_data = self.parent_app._get_current_ui_settings_as_dict()
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(settings_data, f, indent=2)
                
                QMessageBox.information(self, 
                    self._tr("save_settings_success_title", "Settings Saved"),
                    self._tr("save_settings_success_msg", "Settings successfully saved to:\n{filename}")
                    .format(filename=os.path.basename(filepath)))
            except Exception as e:
                QMessageBox.critical(self,
                    self._tr("save_settings_error_title", "Error Saving Settings"),
                    str(e))

    def _handle_load_settings(self):
        """
        Lets the user pick a JSON file, loads it, and applies the settings to the main app.
        """
        if not hasattr(self.parent_app, '_load_ui_from_settings_dict') or \
           not hasattr(self.parent_app, '_update_all_ui_states'):
            QMessageBox.critical(self, self._tr("generic_error_title", "Error"),
                                 self._tr("settings_missing_load_func_error", "Parent application is missing the required load functions."))
            return

        settings_dir = self._get_settings_dir()
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("load_settings_dialog_title", "Load Settings Profile"),
            settings_dir,
            self._tr("json_files_filter", "JSON Files (*.json)")
        )
        
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)
                
                if not isinstance(settings_data, dict):
                    raise ValueError(self._tr("settings_invalid_json_error", "File is not a valid settings dictionary."))
                
                self.parent_app._load_ui_from_settings_dict(settings_data)
                
                self.parent_app._update_all_ui_states()
                
                QMessageBox.information(self,
                    self._tr("load_settings_success_title", "Settings Loaded"),
                    self._tr("load_settings_success_msg", "Successfully loaded settings from:\n{filename}")
                    .format(filename=os.path.basename(filepath)))
                
                self.accept()
                
            except Exception as e:
                QMessageBox.critical(self,
                    self._tr("load_settings_error_title", "Error Loading Settings"),
                    str(e))

    def _start_patch_download(self):
        """Starts the patch download process."""
        download_url = getattr(self.parent_app, 'patch_download_url', None)
        if not download_url:
            QMessageBox.critical(self, "Error", "Patch download URL is missing.")
            return

        self.download_patch_button.setText("Downloading...")
        self.download_patch_button.setEnabled(False)
        self.patch_status_label.setText("Downloading patch, please wait...")

        self.patch_downloader_thread = PatchDownloader(download_url)
        self.patch_downloader_thread.download_finished.connect(self._on_patch_download_finished)
        self.patch_downloader_thread.download_error.connect(self._on_patch_download_error)
        self.patch_downloader_thread.start()

    def _on_patch_download_finished(self):
        """Called when the patch finishes downloading."""
        self.patch_status_label.setText("Patch downloaded! Restarting...")
        self.accept()

    def _on_patch_download_error(self, error_msg):
        """Called if patch download fails."""
        self.patch_status_label.setText("Patch download failed.")
        self.download_patch_button.setText("Retry Download")
        self.download_patch_button.setEnabled(True)
        QMessageBox.critical(self, "Download Error", f"An error occurred while downloading the patch:\n\n{error_msg}")

