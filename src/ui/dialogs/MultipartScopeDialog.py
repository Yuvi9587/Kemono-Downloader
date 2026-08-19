from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QRadioButton, QDialogButtonBox, QButtonGroup,
    QLabel, QLineEdit, QHBoxLayout, QFrame
)
from PySide6.QtGui import QIntValidator
from PySide6.QtCore import Qt

MAX_PARTS = 16 

class MultipartScopeDialog(QDialog):
    """
    A dialog to let the user select the scope, number of parts, and minimum size for multipart downloads.
    """
    SCOPE_VIDEOS = 'videos'
    SCOPE_ARCHIVES = 'archives'
    SCOPE_BOTH = 'both'

    def __init__(self, current_scope='both', current_parts=4, current_min_size_mb=100, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Multipart Download Options")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        self.options_group_box = QGroupBox("Apply multipart downloads to:")
        options_layout = QVBoxLayout()
        self.radio_videos = QRadioButton("Videos Only")
        self.radio_archives = QRadioButton("Archives Only (.zip, .rar, etc.)")
        self.radio_both = QRadioButton("Both Videos and Archives")

        if current_scope == self.SCOPE_VIDEOS:
            self.radio_videos.setChecked(True)
        elif current_scope == self.SCOPE_ARCHIVES:
            self.radio_archives.setChecked(True)
        else:
            self.radio_both.setChecked(True)

        self.button_group = QButtonGroup(self)
        self.button_group.addButton(self.radio_videos)
        self.button_group.addButton(self.radio_archives)
        self.button_group.addButton(self.radio_both)

        options_layout.addWidget(self.radio_videos)
        options_layout.addWidget(self.radio_archives)
        options_layout.addWidget(self.radio_both)
        self.options_group_box.setLayout(options_layout)
        layout.addWidget(self.options_group_box)

        self.settings_group_box = QGroupBox("Download settings:")
        settings_layout = QVBoxLayout()

        parts_layout = QHBoxLayout()
        self.parts_label = QLabel("Number of download parts per file:")
        self.parts_input = QLineEdit(str(current_parts))
        self.parts_input.setValidator(QIntValidator(2, MAX_PARTS, self))
        self.parts_input.setFixedWidth(40)
        self.parts_input.setToolTip(f"Set the number of concurrent connections per file (2-{MAX_PARTS}).")
        parts_layout.addWidget(self.parts_label)
        parts_layout.addStretch()
        parts_layout.addWidget(self.parts_input)
        settings_layout.addLayout(parts_layout)

        size_layout = QHBoxLayout()
        self.size_label = QLabel("Minimum file size for multipart (MB):")
        self.size_input = QLineEdit(str(current_min_size_mb))
        self.size_input.setValidator(QIntValidator(10, 10000, self))
        self.size_input.setFixedWidth(40)
        self.size_input.setToolTip("Files smaller than this will use a normal, single-part download.")
        size_layout.addWidget(self.size_label)
        size_layout.addStretch()
        size_layout.addWidget(self.size_input)
        settings_layout.addLayout(size_layout)

        self.settings_group_box.setLayout(settings_layout)
        layout.addWidget(self.settings_group_box)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def get_selected_scope(self):
        if self.radio_videos.isChecked():
            return self.SCOPE_VIDEOS
        if self.radio_archives.isChecked():
            return self.SCOPE_ARCHIVES
        return self.SCOPE_BOTH

    def get_selected_parts(self):
        try:
            parts = int(self.parts_input.text())
            return max(2, min(parts, MAX_PARTS))
        except (ValueError, TypeError):
            return 4

    def get_selected_min_size(self):
        """Returns the selected minimum size in MB as an integer."""
        try:
            size = int(self.size_input.text())
            return max(10, min(size, 10000))
        except (ValueError, TypeError):
            return 100