from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QRadioButton,
    QPushButton, QHBoxLayout, QButtonGroup, QLabel, QLineEdit
)
from PySide6.QtGui import QIntValidator
from ...i18n.translator import get_translation
from ...config.constants import DUPLICATE_HANDLING_HASH, DUPLICATE_HANDLING_KEEP_ALL

class KeepDuplicatesDialog(QDialog):
    """A dialog to choose the duplicate handling method, with a limit option."""

    def __init__(self, current_mode, current_limit, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.selected_mode = current_mode
        self.limit = current_limit

        self._init_ui()
        self._retranslate_ui()

        if self.parent_app and hasattr(self.parent_app, '_apply_theme_to_widget'):
            self.parent_app._apply_theme_to_widget(self)
        if current_mode == DUPLICATE_HANDLING_KEEP_ALL:
            self.radio_keep_everything.setChecked(True)
            self.limit_input.setText(str(current_limit) if current_limit > 0 else "")
        else:
            self.radio_skip_by_hash.setChecked(True)
            self.limit_input.setEnabled(False)

    def _init_ui(self):
        """Initializes the UI components."""
        main_layout = QVBoxLayout(self)
        info_label = QLabel()
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)

        options_group = QGroupBox()
        options_layout = QVBoxLayout(options_group)
        self.button_group = QButtonGroup(self)
        self.radio_skip_by_hash = QRadioButton()
        self.button_group.addButton(self.radio_skip_by_hash)
        options_layout.addWidget(self.radio_skip_by_hash)
        keep_everything_layout = QHBoxLayout()
        self.radio_keep_everything = QRadioButton()
        self.button_group.addButton(self.radio_keep_everything)
        keep_everything_layout.addWidget(self.radio_keep_everything)
        keep_everything_layout.addStretch(1)

        self.limit_label = QLabel()
        self.limit_input = QLineEdit()
        self.limit_input.setValidator(QIntValidator(0, 99))
        self.limit_input.setFixedWidth(50)
        keep_everything_layout.addWidget(self.limit_label)
        keep_everything_layout.addWidget(self.limit_input)
        options_layout.addLayout(keep_everything_layout)

        main_layout.addWidget(options_group)
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton()
        self.cancel_button = QPushButton()
        button_layout.addStretch(1)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.radio_keep_everything.toggled.connect(self.limit_input.setEnabled)

    def _tr(self, key, default_text=""):
        if self.parent_app and callable(get_translation):
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets the text for UI elements."""
        self.setWindowTitle(self._tr("duplicates_dialog_title", "Duplicate Handling Options"))
        self.findChild(QLabel).setText(self._tr("duplicates_dialog_info",
            "Choose how to handle files that have identical content to already downloaded files."))
        self.findChild(QGroupBox).setTitle(self._tr("duplicates_dialog_group_title", "Mode"))

        self.radio_skip_by_hash.setText(self._tr("duplicates_dialog_skip_hash", "Skip by Hash (Recommended)"))
        self.radio_keep_everything.setText(self._tr("duplicates_dialog_keep_all", "Keep Everything"))

        self.limit_label.setText(self._tr("duplicates_limit_label", "Limit:"))
        self.limit_input.setPlaceholderText(self._tr("duplicates_limit_placeholder", "0=all"))
        self.limit_input.setToolTip(self._tr("duplicates_limit_tooltip",
            "Set a limit for identical files to keep. 0 means no limit."))

        self.ok_button.setText(self._tr("ok_button", "OK"))
        self.cancel_button.setText(self._tr("cancel_button_text_simple", "Cancel"))

    def accept(self):
        """Sets the selected mode and limit when OK is clicked."""
        if self.radio_keep_everything.isChecked():
            self.selected_mode = DUPLICATE_HANDLING_KEEP_ALL
            try:
                self.limit = int(self.limit_input.text()) if self.limit_input.text() else 0
            except ValueError:
                self.limit = 0
        else:
            self.selected_mode = DUPLICATE_HANDLING_HASH
            self.limit = 0
        super().accept()

    def get_selected_options(self):
        """Returns the chosen mode and limit as a dictionary."""
        return {"mode": self.selected_mode, "limit": self.limit}