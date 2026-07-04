from collections import defaultdict
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QAbstractItemView, QLineEdit
)
from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme

class DownloadExtractedLinksDialog(QDialog):
    """
    A dialog to select and initiate the download for extracted, supported links
    from external cloud services like Mega, Google Drive, and Dropbox.
    """
    download_requested = pyqtSignal(list)

    def __init__(self, links_data, parent_app, parent=None):
        """
        Initializes the dialog.

        Args:
            links_data (list): A list of dictionaries, each containing info about an extracted link.
            parent_app (DownloaderApp): A reference to the main application window for theming and translations.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.links_data = links_data
        self.parent_app = parent_app
        app_icon = get_app_icon_object()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        scale_factor = getattr(self.parent_app, 'scale_factor', 1.0)
        base_width, base_height = 600, 450
        self.setMinimumSize(int(base_width * scale_factor), int(base_height * scale_factor))
        self.resize(int(base_width * scale_factor * 1.1), int(base_height * scale_factor * 1.1))
        self._init_ui()
        self._retranslate_ui()
        self._apply_theme()

    def _init_ui(self):
        """Initializes all UI components and layouts for the dialog."""
        layout = QVBoxLayout(self)

        self.main_info_label = QLabel()
        self.main_info_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.main_info_label.setWordWrap(True)
        layout.addWidget(self.main_info_label)
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self._filter_links)
        layout.addWidget(self.search_input)
        self.links_list_widget = QListWidget()
        self.links_list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self._populate_list()
        layout.addWidget(self.links_list_widget)
        button_layout = QHBoxLayout()
        self.select_all_button = QPushButton()
        self.select_all_button.clicked.connect(lambda: self._set_all_items_checked(Qt.Checked))
        button_layout.addWidget(self.select_all_button)

        self.deselect_all_button = QPushButton()
        self.deselect_all_button.clicked.connect(lambda: self._set_all_items_checked(Qt.Unchecked))
        button_layout.addWidget(self.deselect_all_button)
        button_layout.addStretch()

        self.download_button = QPushButton()
        self.download_button.clicked.connect(self._handle_download_selected)
        self.download_button.setDefault(True)
        button_layout.addWidget(self.download_button)

        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def _populate_list(self):
        """Populates the list widget with the provided links, grouped by post title."""
        grouped_links = defaultdict(list)
        for link_info_item in self.links_data:
            post_title_for_group = link_info_item.get('title', 'Untitled Post')
            grouped_links[post_title_for_group].append(link_info_item)

        sorted_post_titles = sorted(grouped_links.keys(), key=lambda x: x.lower())

        for post_title_key in sorted_post_titles:
            header_item = QListWidgetItem(f"{post_title_key}")
            header_item.setFlags(Qt.NoItemFlags)
            font = header_item.font()
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            header_item.setFont(font)
            self.links_list_widget.addItem(header_item)
            for link_info_data in grouped_links[post_title_key]:
                platform_display = link_info_data.get('platform', 'unknown').upper()
                display_text = f"  [{platform_display}] {link_info_data['link_text']} ({link_info_data['url']})"
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, link_info_data)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.links_list_widget.addItem(item)

    def _tr(self, key, default_text=""):
        """Helper to get translation based on current app language."""
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _retranslate_ui(self):
        """Sets the text for all translatable UI elements."""
        self.setWindowTitle(self._tr("download_external_links_dialog_title", "Download Selected External Links"))
        self.main_info_label.setText(self._tr("download_external_links_dialog_main_label", "Found {count} supported link(s)...").format(count=len(self.links_data)))
        self.search_input.setPlaceholderText(self._tr("search_links_placeholder", "Search by post title, URL, platform, or text..."))       
        self.select_all_button.setText(self._tr("select_all_button_text", "Select All"))
        self.deselect_all_button.setText(self._tr("deselect_all_button_text", "Deselect All"))
        self.download_button.setText(self._tr("download_selected_button_text", "Download Selected"))
        self.cancel_button.setText(self._tr("fav_posts_cancel_button", "Cancel"))
    
    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        is_dark_theme = self.parent_app and self.parent_app.current_theme == "dark"

        if is_dark_theme:
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")
        header_color = Qt.cyan if is_dark_theme else Qt.blue
        for i in range(self.links_list_widget.count()):
            item = self.links_list_widget.item(i)
            if not item.flags() & Qt.ItemIsUserCheckable:
                item.setForeground(header_color)

    def _set_all_items_checked(self, check_state):
        """Sets the checked state for all visible checkable items in the list."""
        for i in range(self.links_list_widget.count()):
            item = self.links_list_widget.item(i)
            if (item.flags() & Qt.ItemIsUserCheckable) and not item.isHidden():
                item.setCheckState(check_state)

    def _handle_download_selected(self):
        """Gathers selected links and emits the download_requested signal."""
        selected_links = []
        for i in range(self.links_list_widget.count()):
            item = self.links_list_widget.item(i)
            if item.flags() & Qt.ItemIsUserCheckable and item.checkState() == Qt.Checked and item.data(Qt.UserRole) is not None:
                selected_links.append(item.data(Qt.UserRole))

        if selected_links:
            self.download_requested.emit(selected_links)
            self.accept()
        else:
            QMessageBox.information(
                self,
                self._tr("no_selection_title", "No Selection"),
                self._tr("no_selection_message_links", "Please select at least one link to download.")
            )

    def _filter_links(self, search_term):
        """Filters the links in the dialog based on the search term."""
        search_term = search_term.lower().strip()
        
        current_header = None
        visible_children_count = 0
        
        for i in range(self.links_list_widget.count()):
            item = self.links_list_widget.item(i)
            
            if not (item.flags() & Qt.ItemIsUserCheckable):
                if current_header is not None:
                    current_header.setHidden(visible_children_count == 0)
                    
                current_header = item
                visible_children_count = 0
            else:
                link_data = item.data(Qt.UserRole)
                if not link_data:
                    continue
                    
                post_title = str(link_data.get('title', '')).lower()
                link_text = str(link_data.get('link_text', '')).lower()
                link_url = str(link_data.get('url', '')).lower()
                platform = str(link_data.get('platform', '')).lower()
                decryption_key = str(link_data.get('decryption_key', link_data.get('key', ''))).lower()
                
                matches_search = (
                    not search_term or
                    search_term in post_title or
                    search_term in link_text or
                    search_term in link_url or
                    search_term in platform or
                    search_term in decryption_key
                )
                
                item.setHidden(not matches_search)
                if matches_search:
                    visible_children_count += 1
                    
        if current_header is not None:
            current_header.setHidden(visible_children_count == 0)