from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
    QDialogButtonBox, QTextEdit
)
from PySide6.QtCore import Qt

class CustomFilenameDialog(QDialog):
    """A dialog for creating a custom filename format string."""
    
    DISPLAY_KEY_MAP = {
        "PostID": "id",
        "CreatorName": "creator_name",  
        "service": "service",
        "title": "title",
        "added": "added",
        "published": "published",
        "edited": "edited",
        "name": "name",
        "Suffix": "suffix",
        "Description": "content"  
    }

    DA_ALLOWED_KEYS = ["creator_name", "title", "published", "suffix"]
    SIMPCITY_ALLOWED_KEYS = ["published", "creator_name", "id", "content", "suffix", "name"]

    def __init__(self, current_format, current_date_format, current_suffix_format, parent=None, is_deviantart=False, is_simpcity=False):
        super().__init__(parent)
        self.setWindowTitle("Custom Filename Format")
        self.setMinimumWidth(600)
        self.is_deviantart = is_deviantart
        self.is_simpcity = is_simpcity
        
        self.current_format = current_format
        self.current_date_format = current_date_format
        self.current_suffix_format = current_suffix_format
        
        layout = QVBoxLayout(self)

        desc_text = "Create a filename format using placeholders. The date/time values will be automatically formatted. Use {suffix} to insert a file index (e.g. 001, 002)."
        if is_deviantart:
            desc_text += "\n\n(DeviantArt Mode: Only Creator Name, Title, Upload Date, and Suffix are available. Other buttons are disabled.)"
        elif is_simpcity:
            desc_text += "\n\n(SimpCity Mode: Only Creator Name {creator_name}, Upload Date {published}, Post ID {id}, Description {content}, Original Name {name}, and Suffix {suffix} are available.)"
            
        description_label = QLabel(desc_text)
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        
        format_label = QLabel("Filename Format:")
        layout.addWidget(format_label)
        self.format_input = QLineEdit(self)
        self.format_input.setText(self.current_format)
        
        if is_deviantart:
            self.format_input.setPlaceholderText("e.g., {published} {title} {creator_name}")
        elif is_simpcity:
            self.format_input.setPlaceholderText("e.g., {published} {creator_name} {id}")
        else:
            self.format_input.setPlaceholderText("e.g., {published} {title} {id}")
            
        layout.addWidget(self.format_input)

        formats_layout = QHBoxLayout()

        date_layout = QVBoxLayout()
        date_format_label = QLabel("Date Format (for {published}):")
        date_layout.addWidget(date_format_label)
        self.date_format_input = QLineEdit(self)
        self.date_format_input.setText(self.current_date_format or "YYYY-MM-DD")
        self.date_format_input.setPlaceholderText("e.g., YYYY-MM-DD")
        date_layout.addWidget(self.date_format_input)
        formats_layout.addLayout(date_layout)

        suffix_layout = QVBoxLayout()
        suffix_format_label = QLabel("Suffix Format (for {suffix}):")
        suffix_layout.addWidget(suffix_format_label)
        self.suffix_format_input = QLineEdit(self)
        self.suffix_format_input.setText(self.current_suffix_format)
        self.suffix_format_input.setPlaceholderText("e.g., 001, Image1, Pg01")
        suffix_layout.addWidget(self.suffix_format_input)
        formats_layout.addLayout(suffix_layout)

        layout.addLayout(formats_layout)

        keys_label = QLabel("Click to add a placeholder:")
        layout.addWidget(keys_label)
        
        keys_layout = QHBoxLayout()
        keys_layout.setSpacing(5)
        
        for display_key, internal_key in self.DISPLAY_KEY_MAP.items():
            key_button = QPushButton(f"{{{display_key}}}")

            if display_key == "Description":
                key_button.setToolTip("⚠️ Warning: Using this requires an extra API request per post, significantly slowing down downloads.")

            if is_deviantart:
                if internal_key in self.DA_ALLOWED_KEYS:
                    key_button.setStyleSheet("font-weight: bold;")
                    key_button.setEnabled(True)
                else:
                    key_button.setEnabled(False) 
                    key_button.setToolTip("Not available for DeviantArt")
            elif is_simpcity:
                if internal_key in self.SIMPCITY_ALLOWED_KEYS:
                    key_button.setStyleSheet("font-weight: bold;")
                    key_button.setEnabled(True)
                else:
                    key_button.setEnabled(False) 
                    key_button.setToolTip("Not available for SimpCity")
            
            key_button.clicked.connect(lambda checked, key=internal_key: self.add_key_to_input(key))
            keys_layout.addWidget(key_button)
        keys_layout.addStretch()

        layout.addLayout(keys_layout)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def add_key_to_input(self, key_to_insert):
        """Adds the corresponding internal key placeholder to the input field."""
        self.format_input.insert(f" {{{key_to_insert}}} ")
        self.format_input.setFocus()

    def get_format_string(self):
        return self.format_input.text().strip()

    def get_date_format_string(self):
        return self.date_format_input.text().strip()

    def get_suffix_format_string(self):
        return self.suffix_format_input.text().strip()