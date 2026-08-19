from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QRadioButton, QButtonGroup
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme

class ExportOptionsDialog(QDialog):
    """
    Dialog to choose the export format for error file links.
    It allows the user to select between exporting only the URLs or
    exporting URLs with additional details.
    """
    EXPORT_MODE_LINK_ONLY = 1
    EXPORT_MODE_WITH_DETAILS = 2

    def __init__(self, parent_app, parent=None):
        """
        Initializes the dialog.

        Args:
            parent_app (DownloaderApp): A reference to the main application window for theming and translations.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.parent_app = parent_app
        self.setModal(True)
        self.selected_option = self.EXPORT_MODE_LINK_ONLY

        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        screen_height = QApplication.primaryScreen().availableGeometry().height() if QApplication.primaryScreen() else 768
        scale_factor = screen_height / 768.0
        base_min_w = 350
        scaled_min_w = int(base_min_w * scale_factor)
        self.setMinimumWidth(scaled_min_w)

        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()

    def _init_ui(self):
        """Initializes all UI components and layouts for the dialog."""
        layout = QVBoxLayout(self)

        self.description_label = QLabel()
        layout.addWidget(self.description_label)

        self.radio_group = QButtonGroup(self)

        self.radio_link_only = QRadioButton()
        self.radio_link_only.setChecked(True)
        self.radio_group.addButton(self.radio_link_only, self.EXPORT_MODE_LINK_ONLY)
        layout.addWidget(self.radio_link_only)

        self.radio_with_details = QRadioButton()
        self.radio_group.addButton(self.radio_with_details, self.EXPORT_MODE_WITH_DETAILS)
        layout.addWidget(self.radio_with_details)

        button_layout = QHBoxLayout()
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._handle_export)
        self.export_button.setDefault(True)

        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addStretch(1)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def _tr(self, key, default_text=""):
        """Helper to get translation based on the main application's current language."""
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets the text for all translatable UI elements."""
        self.setWindowTitle(self._tr("export_options_dialog_title", "Export Options"))
        self.description_label.setText(self._tr("export_options_description_label", "Choose the format for exporting error file links:"))
        self.radio_link_only.setText(self._tr("export_options_radio_link_only", "Link per line (URL only)"))
        self.radio_link_only.setToolTip(self._tr("export_options_radio_link_only_tooltip", "Exports only the direct download URL..."))
        self.radio_with_details.setText(self._tr("export_options_radio_with_details", "Export with details (URL [Post, File info])"))
        self.radio_with_details.setToolTip(self._tr("export_options_radio_with_details_tooltip", "Exports the URL followed by details..."))
        self.export_button.setText(self._tr("export_options_export_button", "Export"))
        self.cancel_button.setText(self._tr("fav_posts_cancel_button", "Cancel"))

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and hasattr(self.parent_app, 'current_theme') and self.parent_app.current_theme == "dark":
            if hasattr(self.parent_app, 'get_dark_theme'):
                self.setStyleSheet(self.parent_app.get_dark_theme())

    def _handle_export(self):
        """Sets the selected export option and accepts the dialog."""
        self.selected_option = self.radio_group.checkedId()
        self.accept()

    def get_selected_option(self):
        """Returns the export mode chosen by the user."""
        return self.selected_option
