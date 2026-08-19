from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme

class CookieHelpDialog(QDialog):
    """
    A dialog to explain how to get a cookies.txt file.
    It can be displayed as a simple informational popup or as a modal choice
    when cookies are required but not found.
    """
    CHOICE_PROCEED_WITHOUT_COOKIES = 1
    CHOICE_CANCEL_DOWNLOAD = 2
    CHOICE_OK_INFO_ONLY = 3

    def __init__(self, parent_app, parent=None, offer_download_without_option=False):
        """
        Initializes the dialog.

        Args:
            parent_app (DownloaderApp): A reference to the main application window.
            parent (QWidget, optional): The parent widget. Defaults to None.
            offer_download_without_option (bool): If True, shows buttons to
                "Download without Cookies" and "Cancel Download". If False,
                shows only an "OK" button for informational purposes.
        """
        super().__init__(parent)
        self.parent_app = parent_app
        self.setModal(True)
        self.offer_download_without_option = offer_download_without_option
        self.user_choice = None

        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.setMinimumWidth(500)

        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()

    def _init_ui(self):
        """Initializes all UI components and layouts for the dialog."""
        main_layout = QVBoxLayout(self)

        self.info_label = QLabel()
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setOpenExternalLinks(True)
        self.info_label.setWordWrap(True)
        main_layout.addWidget(self.info_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        if self.offer_download_without_option:
            self.download_without_button = QPushButton()
            self.download_without_button.clicked.connect(self._proceed_without_cookies)
            button_layout.addWidget(self.download_without_button)

            self.cancel_button = QPushButton()
            self.cancel_button.clicked.connect(self._cancel_download)
            button_layout.addWidget(self.cancel_button)
        else:
            self.ok_button = QPushButton()
            self.ok_button.clicked.connect(self._ok_info_only)
            button_layout.addWidget(self.ok_button)

        main_layout.addLayout(button_layout)

    def _tr(self, key, default_text=""):
        """Helper to get translation based on the main application's current language."""
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets the text for all translatable UI elements."""
        self.setWindowTitle(self._tr("cookie_help_dialog_title", "Cookie File Instructions"))

        instruction_html = f"""
        {self._tr("cookie_help_instruction_intro", "<p>To use cookies...</p>")}
        {self._tr("cookie_help_how_to_get_title", "<p><b>How to get cookies.txt:</b></p>")}
        <ol>
            {self._tr("cookie_help_step1_extension_intro", "<li>Install extension...</li>")}
            {self._tr("cookie_help_step2_login", "<li>Go to website...</li>")}
            {self._tr("cookie_help_step3_click_icon", "<li>Click icon...</li>")}
            {self._tr("cookie_help_step4_export", "<li>Click export...</li>")}
            {self._tr("cookie_help_step5_save_file", "<li>Save file...</li>")}
            {self._tr("cookie_help_step6_app_intro", "<li>In this application:<ul>")}
            {self._tr("cookie_help_step6a_checkbox", "<li>Ensure checkbox...</li>")}
            {self._tr("cookie_help_step6b_browse", "<li>Click browse...</li>")}
            {self._tr("cookie_help_step6c_select", "<li>Select file...</li></ul></li>")}
        </ol>
        {self._tr("cookie_help_alternative_paste", "<p>Alternatively, paste...</p>")}
        """
        self.info_label.setText(instruction_html)

        if self.offer_download_without_option:
            self.download_without_button.setText(self._tr("cookie_help_proceed_without_button", "Download without Cookies"))
            self.cancel_button.setText(self._tr("cookie_help_cancel_download_button", "Cancel Download"))
        else:
            self.ok_button.setText(self._tr("ok_button", "OK"))

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and hasattr(self.parent_app, 'get_dark_theme') and self.parent_app.current_theme == "dark":
            self.setStyleSheet(self.parent_app.get_dark_theme())

    def _proceed_without_cookies(self):
        """Handles the user choice to proceed without using cookies."""
        self.user_choice = self.CHOICE_PROCEED_WITHOUT_COOKIES
        self.accept()

    def _cancel_download(self):
        """Handles the user choice to cancel the download."""
        self.user_choice = self.CHOICE_CANCEL_DOWNLOAD
        self.reject()

    def _ok_info_only(self):
        """Handles the acknowledgment when the dialog is purely informational."""
        self.user_choice = self.CHOICE_OK_INFO_ONLY
        self.accept()
