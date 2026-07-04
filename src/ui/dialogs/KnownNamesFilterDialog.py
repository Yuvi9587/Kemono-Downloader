from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme

class KnownNamesFilterDialog(QDialog):
    """
    A dialog to select names from the Known.txt list to add to the main
    character filter input field. This provides a convenient way for users
    to reuse their saved names and groups for filtering downloads.
    """

    def __init__(self, known_names_list, parent_app_ref, parent=None):
        """
        Initializes the dialog.

        Args:
            known_names_list (list): A list of known name objects (dicts) from Known.txt.
            parent_app_ref (DownloaderApp): A reference to the main application window.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.parent_app = parent_app_ref
        self.setModal(True)
        self.all_known_name_entries = sorted(known_names_list, key=lambda x: x['name'].lower())
        self.selected_entries_to_return = []

        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        scale_factor = getattr(self.parent_app, 'scale_factor', 1.0)

        base_width, base_height = 460, 450
        self.setMinimumSize(int(base_width * scale_factor), int(base_height * scale_factor))
        self.resize(int(base_width * scale_factor * 1.1), int(base_height * scale_factor * 1.1))

        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()

    def _init_ui(self):
        """Initializes all UI components and layouts for the dialog."""
        main_layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self._filter_list_display)
        main_layout.addWidget(self.search_input)

        self.names_list_widget = QListWidget()
        self._populate_list_widget()
        main_layout.addWidget(self.names_list_widget)

        buttons_layout = QHBoxLayout()

        self.select_all_button = QPushButton()
        self.select_all_button.clicked.connect(self._select_all_items)
        buttons_layout.addWidget(self.select_all_button)

        self.deselect_all_button = QPushButton()
        self.deselect_all_button.clicked.connect(self._deselect_all_items)
        buttons_layout.addWidget(self.deselect_all_button)
        buttons_layout.addStretch(1)

        self.add_button = QPushButton()
        self.add_button.clicked.connect(self._accept_selection_action)
        self.add_button.setDefault(True)
        buttons_layout.addWidget(self.add_button)

        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)
        main_layout.addLayout(buttons_layout)

    def _tr(self, key, default_text=""):
        """Helper to get translation based on the main application's current language."""
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets the text for all translatable UI elements."""
        self.setWindowTitle(self._tr("known_names_filter_dialog_title", "Add Known Names to Filter"))
        self.search_input.setPlaceholderText(self._tr("known_names_filter_search_placeholder", "Search names..."))
        self.select_all_button.setText(self._tr("known_names_filter_select_all_button", "Select All"))
        self.deselect_all_button.setText(self._tr("known_names_filter_deselect_all_button", "Deselect All"))
        self.add_button.setText(self._tr("known_names_filter_add_selected_button", "Add Selected"))
        self.cancel_button.setText(self._tr("fav_posts_cancel_button", "Cancel"))

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")

    def _populate_list_widget(self):
        """Populates the list widget with the known names."""
        self.names_list_widget.clear()
        for entry_obj in self.all_known_name_entries:
            item = QListWidgetItem(entry_obj['name'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, entry_obj)
            self.names_list_widget.addItem(item)

    def _filter_list_display(self):
        """Filters the displayed list based on the search input text."""
        search_text_lower = self.search_input.text().lower()
        for i in range(self.names_list_widget.count()):
            item = self.names_list_widget.item(i)
            entry_obj = item.data(Qt.UserRole)
            matches_search = not search_text_lower or search_text_lower in entry_obj['name'].lower()
            item.setHidden(not matches_search)

    def _select_all_items(self):
        """Checks all visible items in the list widget."""
        for i in range(self.names_list_widget.count()):
            item = self.names_list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked)

    def _deselect_all_items(self):
        """Unchecks all items in the list widget."""
        for i in range(self.names_list_widget.count()):
            self.names_list_widget.item(i).setCheckState(Qt.Unchecked)

    def _accept_selection_action(self):
        """Gathers the selected entries and accepts the dialog."""
        self.selected_entries_to_return = []
        for i in range(self.names_list_widget.count()):
            item = self.names_list_widget.item(i)
            if item.checkState() == Qt.Checked:
                self.selected_entries_to_return.append(item.data(Qt.UserRole))
        self.accept()

    def get_selected_entries(self):
        """Returns the list of known name entries selected by the user."""
        return self.selected_entries_to_return