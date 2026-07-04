import json
import os
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QAbstractItemView, QLabel, QCheckBox
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme

class UpdateCheckDialog(QDialog):
    """
    A dialog that lists all creator .json profiles with checkboxes
    and allows the user to select multiple to check for updates.
    """
    
    def __init__(self, user_data_path, parent_app_ref, parent=None):
        super().__init__(parent)
        self.parent_app = parent_app_ref
        self.user_data_path = user_data_path
        self.selected_profiles_list = []
        
        self._default_checkbox_tooltip = (
            "If checked, the settings fields will be unlocked and editable.\n"
            "If unchecked, settings will still load, but in 'Read-Only' mode."
        )

        self._init_ui()
        self._load_profiles()
        self._retranslate_ui()

        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")

    def _init_ui(self):
        """Initializes the UI components."""
        self.setWindowTitle("Check for Updates")
        self.setMinimumSize(400, 450)
        
        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        layout = QVBoxLayout(self)

        self.info_label = QLabel("Select creator profiles to check for updates:")
        layout.addWidget(self.info_label)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.itemChanged.connect(self._handle_item_changed)
        layout.addWidget(self.list_widget)

        self.edit_settings_checkbox = QCheckBox("Enable Editing (Unlock Settings)")
        self.edit_settings_checkbox.setToolTip(self._default_checkbox_tooltip)
        
        self.edit_settings_checkbox.setChecked(True) 
        
        layout.addWidget(self.edit_settings_checkbox)

      
        button_layout = QHBoxLayout()
        button_layout.setSpacing(6)

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self._toggle_all_checkboxes)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.clicked.connect(self._toggle_all_checkboxes)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)

        self.check_button = QPushButton("Check Selected")
        self.check_button.clicked.connect(self.on_check_selected)
        self.check_button.setDefault(True)

        button_layout.addWidget(self.select_all_button)
        button_layout.addWidget(self.deselect_all_button)
        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.check_button)

        layout.addLayout(button_layout)

    def _tr(self, key, default_text=""):
        """Helper to get translation based on current app language."""
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Translates the UI elements."""
        self.setWindowTitle(self._tr("update_check_dialog_title", "Check for Updates"))
        self.info_label.setText(self._tr("update_check_dialog_info_multiple", "Select creator profiles to check for updates:"))
        self.select_all_button.setText(self._tr("select_all_button_text", "Select All"))
        self.deselect_all_button.setText(self._tr("deselect_all_button_text", "Deselect All"))
        self.check_button.setText(self._tr("update_check_dialog_check_button", "Check Selected"))
        self.close_button.setText(self._tr("update_check_dialog_close_button", "Close"))
        self.edit_settings_checkbox.setText(self._tr("update_check_enable_editing_checkbox", "Enable Editing (Unlock Settings)"))

    def _load_profiles(self):
        """Loads all .json files from the creator_profiles directory as checkable items."""
        appdata_dir = self.user_data_path
        profiles_dir = os.path.join(appdata_dir, "creator_profiles")

        if not os.path.isdir(profiles_dir):
            QMessageBox.warning(self, 
                self._tr("update_check_dir_not_found_title", "Directory Not Found"),
                self._tr("update_check_dir_not_found_msg", 
                         "The creator profiles directory does not exist yet.\n\nPath: {path}")
                         .format(path=profiles_dir))
            return

        profiles_found = []
        for filename in os.listdir(profiles_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(profiles_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if 'creator_url' in data and 'processed_post_ids' in data:
                        creator_name = os.path.splitext(filename)[0]
                        profiles_found.append({'name': creator_name, 'data': data})
                    else:
                        print(f"Skipping invalid profile: {filename}")
                except Exception as e:
                    print(f"Failed to load profile {filename}: {e}")

        profiles_found.sort(key=lambda x: x['name'].lower())

        for profile_info in profiles_found:
            item = QListWidgetItem(profile_info['name'])
            item.setData(Qt.UserRole, profile_info)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)
            
        if not profiles_found:
            self.list_widget.addItem(self._tr("update_check_no_profiles", "No creator profiles found."))
            self.list_widget.setEnabled(False)
            self.check_button.setEnabled(False)
            self.select_all_button.setEnabled(False)
            self.deselect_all_button.setEnabled(False)
            self.edit_settings_checkbox.setEnabled(False)

    def _toggle_all_checkboxes(self):
        """Handles Select All and Deselect All button clicks."""
        sender = self.sender()
        check_state = Qt.Checked if sender == self.select_all_button else Qt.Unchecked
        
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(check_state)
        self.list_widget.blockSignals(False)
        
        self._handle_item_changed(None)

    def _handle_item_changed(self, item):
        """
        Monitors how many items are checked.
        If more than 1 item is checked, disable the 'Enable Editing' checkbox.
        """
        checked_count = 0
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).checkState() == Qt.Checked:
                checked_count += 1
        
        if checked_count > 1:
            self.edit_settings_checkbox.setChecked(False)
            self.edit_settings_checkbox.setEnabled(False)
            self.edit_settings_checkbox.setToolTip(
                self._tr("update_check_multi_selection_warning", 
                         "Editing settings is disabled when multiple profiles are selected.")
            )
        else:
            self.edit_settings_checkbox.setEnabled(True)
            self.edit_settings_checkbox.setToolTip(self._default_checkbox_tooltip)

    def on_check_selected(self):
        """Handles the 'Check Selected' button click."""
        self.selected_profiles_list = []
        
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                profile_info = item.data(Qt.UserRole)
                if profile_info:
                    self.selected_profiles_list.append(profile_info)
        
        if not self.selected_profiles_list:
            QMessageBox.warning(self, 
                self._tr("update_check_no_selection_title", "No Selection"),
                self._tr("update_check_no_selection_msg", "Please select at least one creator to check."))
            return
        
        self.accept()

    def get_selected_profiles(self):
        """Returns the list of profile data selected by the user."""
        return self.selected_profiles_list
    
    def should_load_into_ui(self):
        """
        Returns True if the settings SHOULD be loaded into the UI.
        
        NEW LOGIC: Returns True if exactly ONE profile is selected.
        It does NOT care about the checkbox state anymore, because we want
        to load settings even if the user can't edit them.
        """
        return len(self.selected_profiles_list) == 1
    
    def should_enable_editing(self):
        """
        NEW METHOD: Returns True if the user is allowed to edit the settings.
        This is linked to the checkbox.
        """
        return self.edit_settings_checkbox.isEnabled() and self.edit_settings_checkbox.isChecked()