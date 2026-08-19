from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout
)
from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
CONFIRM_ADD_ALL_ACCEPTED = 1
CONFIRM_ADD_ALL_SKIP_ADDING = 2
CONFIRM_ADD_ALL_CANCEL_DOWNLOAD = 3


class ConfirmAddAllDialog(QDialog):
    """
    A dialog to confirm adding multiple new character/series names to Known.txt.
    It appears when the user provides filter names that are not already known,
    allowing them to persist these names for future use.
    """

    def __init__(self, new_filter_objects_list, parent_app, parent=None):
        """
        Initializes the dialog.

        Args:
            new_filter_objects_list (list): A list of filter objects (dicts) to propose adding.
            parent_app (DownloaderApp): A reference to the main application window for theming and translations.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.parent_app = parent_app
        self.setModal(True)
        self.new_filter_objects_list = new_filter_objects_list
        self.user_choice = CONFIRM_ADD_ALL_CANCEL_DOWNLOAD
        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)
        screen_height = QApplication.primaryScreen().availableGeometry().height() if QApplication.primaryScreen() else 768
        scale_factor = screen_height / 768.0
        base_min_w, base_min_h = 480, 350
        scaled_min_w = int(base_min_w * scale_factor)
        scaled_min_h = int(base_min_h * scale_factor)
        self.setMinimumSize(scaled_min_w, scaled_min_h)
        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()

    def _init_ui(self):
        """Initializes all UI components and layouts for the dialog."""
        main_layout = QVBoxLayout(self)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        main_layout.addWidget(self.info_label)

        self.names_list_widget = QListWidget()
        self._populate_list()
        main_layout.addWidget(self.names_list_widget)
        selection_buttons_layout = QHBoxLayout()
        self.select_all_button = QPushButton()
        self.select_all_button.clicked.connect(self._select_all_items)
        selection_buttons_layout.addWidget(self.select_all_button)

        self.deselect_all_button = QPushButton()
        self.deselect_all_button.clicked.connect(self._deselect_all_items)
        selection_buttons_layout.addWidget(self.deselect_all_button)
        selection_buttons_layout.addStretch()
        main_layout.addLayout(selection_buttons_layout)
        buttons_layout = QHBoxLayout()
        self.add_selected_button = QPushButton()
        self.add_selected_button.clicked.connect(self._accept_add_selected)
        self.add_selected_button.setDefault(True)
        buttons_layout.addWidget(self.add_selected_button)

        self.skip_adding_button = QPushButton()
        self.skip_adding_button.clicked.connect(self._reject_skip_adding)
        buttons_layout.addWidget(self.skip_adding_button)
        buttons_layout.addStretch()

        self.cancel_download_button = QPushButton()
        self.cancel_download_button.clicked.connect(self._reject_cancel_download)
        buttons_layout.addWidget(self.cancel_download_button)

        main_layout.addLayout(buttons_layout)
        
    def _populate_list(self):
        """Populates the list widget with the new names to be confirmed."""
        for filter_obj in self.new_filter_objects_list:
            item_text = filter_obj["name"]
            list_item = QListWidgetItem(item_text)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Checked)
            list_item.setData(Qt.ItemDataRole.UserRole, filter_obj)
            self.names_list_widget.addItem(list_item)

    def _tr(self, key, default_text=""):
        """Helper to get translation based on the main application's current language."""
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets the text for all translatable UI elements."""
        self.setWindowTitle(self._tr("confirm_add_all_dialog_title", "Confirm Adding New Names"))
        self.info_label.setText(self._tr("confirm_add_all_info_label", "The following new names/groups..."))
        self.select_all_button.setText(self._tr("confirm_add_all_select_all_button", "Select All"))
        self.deselect_all_button.setText(self._tr("confirm_add_all_deselect_all_button", "Deselect All"))
        self.add_selected_button.setText(self._tr("confirm_add_all_add_selected_button", "Add Selected to Known.txt"))
        self.skip_adding_button.setText(self._tr("confirm_add_all_skip_adding_button", "Skip Adding These"))
        self.cancel_download_button.setText(self._tr("confirm_add_all_cancel_download_button", "Cancel Download"))

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and hasattr(self.parent_app, 'get_dark_theme') and self.parent_app.current_theme == "dark":
            self.setStyleSheet(self.parent_app.get_dark_theme())

    def _select_all_items(self):
        """Checks all items in the list."""
        for i in range(self.names_list_widget.count()):
            self.names_list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def _deselect_all_items(self):
        """Unchecks all items in the list."""
        for i in range(self.names_list_widget.count()):
            self.names_list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _accept_add_selected(self):
        """Sets the user choice to the list of selected items and accepts the dialog."""
        selected_objects = []
        for i in range(self.names_list_widget.count()):
            item = self.names_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                filter_obj = item.data(Qt.ItemDataRole.UserRole)
                if filter_obj:
                    selected_objects.append(filter_obj)
        
        self.user_choice = selected_objects
        self.accept()

    def _reject_skip_adding(self):
        """Sets the user choice to skip adding and rejects the dialog."""
        self.user_choice = CONFIRM_ADD_ALL_SKIP_ADDING
        self.reject()

    def _reject_cancel_download(self):
        """Sets the user choice to cancel the entire download and rejects the dialog."""
        self.user_choice = CONFIRM_ADD_ALL_CANCEL_DOWNLOAD
        self.reject()

    def exec_(self):
        """
        Overrides the default exec_ to handle the return value logic, ensuring a
        sensible default if no items are selected but the "Add" button is clicked.
        """
        super().exec()
        if isinstance(self.user_choice, list) and not self.user_choice:
            return CONFIRM_ADD_ALL_SKIP_ADDING
        return self.user_choice
