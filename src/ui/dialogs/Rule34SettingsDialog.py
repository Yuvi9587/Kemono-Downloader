import sys
import os
import urllib.request
import re
import json
import sqlite3
from ..assets import get_asset_path, get_asset_html_path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QCheckBox, QSpinBox, QComboBox, QGroupBox, 
    QMessageBox, QProgressBar, QWidget, QListWidget, QCompleter, QAbstractItemView, QScrollArea, QSizePolicy, QMenu
)
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QEvent, QSize

HELP_CONTENT = {
    "General Setup": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/settings.svg')}' width='18' height='18' align='top'> General & API Setup</h3>"
        "<p><b>[ Auto-Extract & Save Keys ]</b><br>"
        "Rule34 restricts how many images a guest can download and will eventually block your IP. "
        "This button pulls your logged-in session data from the main window and saves it. "
        "This allows the background downloader to act as a registered user, bypassing rate limits and connection drops.</p>"
    ),
    "Content Filters": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/target.svg')}' width='18' height='18' align='top'> Content & Quality Filters</h3>"
        "<ul>"
        "<li><b>Minimum Rating Allowed:</b> Tells the API to only fetch posts matching specific site ratings (Safe, Questionable, or Explicit).</li>"
        "<li><b>Minimum Post Score:</b> Skips any post that has fewer upvotes than the number you set. This is a great way to filter out low-effort or low-quality art.</li>"
        "<li><b>Maximum Total Downloads:</b> Acts as a kill-switch. If set to 100, the Downloader stops exactly after 100 successful saves. Setting it to 0 means it will scrape infinitely until there are no posts left.</li>"
        "<li><b>Download Image / Video Files:</b> Tells the engine whether to save static images (JPG, PNG, GIF), animated media (MP4, WEBM), or both.</li>"
        "</ul>"
    ),
    "Content Safety": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/block.svg')}' width='18' height='18' align='top'> Content Safety</h3>"
        "<ul>"
        "<li><b>Quick Exclusions:</b> Pre-configured safety nets (Gore, Scatology, Furry, Loli, etc.). Checking these adds massive lists of related tags to your active blacklist so you don't have to type them manually. Hover over them to see the exact blocked words.</li>"
        "<li><b>Exclude Custom:</b> Allows you to create your own Quick Exclusion preset. Click the <b>[+]</b> button to add tags you want blocked. Checking the box instantly activates your custom blocklist without cluttering your master blacklist.</li>"
        "</ul>"
    ),
    "Tag Control": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/tag.svg')}' width='18' height='18' align='top'> Tag Control</h3>"
        "<ul>"
        "<li><b>Priority Whitelist:</b> The ultimate override. If a post contains a tag written here (like a favorite artist), the downloader will save it even if the post also contains tags from your Blacklist.</li>"
        "<li><b>Custom Blacklist:</b> A comma-separated list of tags. If a post contains any of these words, it is instantly skipped.</li>"
        "</ul>"
    ),
    "Character Routing": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/folder.svg')}' width='18' height='18' align='top'> Character Routing (The 'WHO')</h3>"
        "<ul>"
        "<li><b>Enable Automatic Character Folders:</b> Turns on the primary routing engine. It scans downloaded tags for known characters and automatically creates a folder named after them.</li>"
        "<li><b>Favorites Manager:</b> Where you type character names. Uses a custom Autocomplete system. Press <i>Ctrl + Down Arrow</i> to rapidly select and lock in names.</li>"
        "<li><b>[ Add ] Button:</b> Saves the characters permanently into your characters.db file.</li>"
        "<li><b>Strict Mode / Favorites Only:</b> If checked, the app will only create dedicated folders for characters in your Favorites list. Unrecognized characters are bundled into an <code>\\Unknown\\</code> folder.</li>"
        "<li><b>[ Download Offline Tag Database ]:</b> Downloads a tag database from HuggingFace/GitHub so your Autocomplete works instantly without an internet connection.</li>"
        "</ul>"
    ),
    "Scene Routing": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/palette.svg')}' width='18' height='18' align='top'> Scene & Tag Routing (The 'WHAT / WHERE')</h3>"
        "<ul>"
        "<li><b>Enable Priority-Based Scene Sub-Folders:</b> Turns on the secondary routing engine. If Character sorting is on, these become sub-folders (e.g., <code>\\Makima\\Beach\\</code>).</li>"
        "<li><b>Scene Priority List:</b> The engine checks tags from Top to Bottom. If a post is tagged with both 'Bikini' and 'Beach', and 'Bikini' is higher on this list, the folder will be named <code>\\Bikini\\</code>.</li>"
        "<li><b>Movement Controls:</b> Use [ Move Up ], [ Move Down ], and [ Delete ] to adjust your priority order.</li>"
        "</ul>"
    ),
    "Tag Aliases": (
        f"<h3><img src='{get_asset_html_path('assets/Svg/link.svg')}' width='18' height='18' align='top'> Tag Aliases Engine (The Translator)</h3>"
        "<ul>"
        "<li><b>Alias Input:</b> Creates a translation rule formatted as <code>Master = alias1, alias2</code>.</li>"
        "<li><b>Alias List:</b> Shows active translations. When a file downloads, the engine instantly intercepts the internet's messy tags and standardizes them before any folders are created (e.g., intercepting 'swimwear' to 'bikini').</li>"
        "<li><b>[ Load Community Rules (GitHub) ]:</b> Reaches out to a raw text file hosted on GitHub, checks for duplicates, and instantly injects new alias rules into the UI without needing manual .txt downloads.</li>"
        "</ul>"
    )
}

class MultiCompleter(QCompleter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_prefix = ""

    def pathFromIndex(self, index):
        path = super().pathFromIndex(index)
        return f"{self.current_prefix}{path}"

    def splitPath(self, path):
        return [path.split(',')[-1].lstrip()]

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_Down:
                if self.popup() and self.popup().isVisible():
                    popup = self.popup()
                    current_index = popup.currentIndex()
                    if not current_index.isValid():
                        current_index = self.completionModel().index(0, 0)
                    
                    selected_text = self.completionModel().data(current_index)
                    if selected_text:
                        line_edit = self.widget()
                        current_text = line_edit.text()
                        
                        if ',' in current_text:
                            locked_prefix = current_text[:current_text.rfind(',') + 1]
                            if not locked_prefix.endswith(" "):
                                locked_prefix += " "
                        else:
                            locked_prefix = ""
                            
                        new_locked_text = f"{locked_prefix}{selected_text}, "
                        self.current_prefix = new_locked_text
                        
                        next_row = current_index.row() + 1
                        if next_row < self.completionModel().rowCount():
                            next_index = self.completionModel().index(next_row, 0)
                            popup.setCurrentIndex(next_index)
                            next_text = self.completionModel().data(next_index)
                            
                            line_edit.blockSignals(True)
                            line_edit.setText(f"{new_locked_text}{next_text}")
                            line_edit.blockSignals(False)
                        else:
                            line_edit.blockSignals(True)
                            line_edit.setText(new_locked_text)
                            line_edit.blockSignals(False)
                            
                        return True 
        return super().eventFilter(obj, event)

class MultiCompleterLineEdit(QLineEdit):
    pass 

class FavoritesListWidget(QListWidget):
    delete_requested = Signal()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.delete_requested.emit()
        else:
            super().keyPressEvent(event)

class SectionHelpButton(QPushButton):
    """A reusable, small button that pops up a contextual help dialog with an SVG icon."""
    def __init__(self, title, text_content, parent=None):
        super().__init__("", parent)
        self.title = title
        self.text_content = text_content
        self.setFixedSize(24, 24)
        self.setIcon(QIcon(get_asset_path("assets/Svg/help.svg")))
        self.setIconSize(QSize(18, 18))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Help: {title}")
        
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: #4f4f4f;
            }
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
        """)
        self.clicked.connect(self.show_popup)

    def show_popup(self):
        msg = QMessageBox(self.parent())
        msg.setWindowTitle(f"Help: {self.title}")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(self.text_content)
        
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #e0e0e0;
                font-size: 13px;
                line-height: 1.4;
            }
            QPushButton {
                background-color: #3b3b3b;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 6px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4f4f4f;
                border: 1px solid #87ceeb;
            }
        """)
        msg.exec()

class HuggingFaceDownloadThread(QThread):
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)

    def __init__(self, download_url, save_path, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.save_path = save_path

    def run(self):
        try:
            os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    downloaded = block_num * block_size
                    percent = int((downloaded / total_size) * 100)
                    self.progress_signal.emit(min(percent, 100))
            urllib.request.urlretrieve(self.download_url, self.save_path, reporthook=report_progress)
            self.finished_signal.emit(True, "Download successful!")
        except Exception as e:
            self.finished_signal.emit(False, str(e))

class Rule34SettingsDialog(QDialog):
    def __init__(self, main_app):
        super().__init__(main_app)
        self.main_app = main_app
        
        self.base_dir = self.main_app.app_base_dir
        
        self.appdata_dir = os.path.join(self.base_dir, "appdata")
        os.makedirs(self.appdata_dir, exist_ok=True)
        
        self.db_dir = os.path.join(self.appdata_dir, "Database")
        os.makedirs(self.db_dir, exist_ok=True)
        
        if getattr(sys, 'frozen', False):
            asset_base = sys._MEIPASS
        else:
            asset_base = self.base_dir
            
        self.assets_dir = os.path.join(asset_base, "assets", "svg")
        self.expand_icon_path = os.path.join(self.assets_dir, "large.svg")
        self.restore_icon_path = os.path.join(self.assets_dir, "minimize.svg")
        
        self.GITHUB_RAW_URL = "https://raw.githubusercontent.com/Yuvi63771/Rule34/main/alliases.txt"
        
        self.setWindowTitle("Rule34 Download Settings")
        self.setWindowIcon(QIcon(get_asset_path("assets/Svg/settings.svg")))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.setMinimumSize(800, 500) 
        
        self.all_tags_cache = [] 
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.update_completer_model)
        
        self.setup_ui()
        self.load_settings()
        self.setup_autocomplete()

    def setup_ui(self):
        master_layout = QVBoxLayout(self)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QScrollArea.NoFrame)
        
        scroll_content = QWidget()
        columns_layout = QHBoxLayout(scroll_content)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        
        self.left_container = QWidget()
        left_col = QVBoxLayout(self.left_container)
        left_col.setContentsMargins(0, 0, 0, 0)
        
        self.mid_container = QWidget()
        mid_col = QVBoxLayout(self.mid_container)
        mid_col.setContentsMargins(0, 0, 0, 0)
        
        self.right_container = QWidget()
        right_col = QVBoxLayout(self.right_container)
        right_col.setContentsMargins(0, 0, 0, 0)

        creds_group = QGroupBox()
        creds_layout = QVBoxLayout()
        
        creds_title_layout = QHBoxLayout()
        creds_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/key.svg')}' width='16' height='16' align='top'> <b>API CREDENTIALS</b>")
        creds_help = SectionHelpButton("General Setup", HELP_CONTENT["General Setup"])
        creds_title_layout.addWidget(creds_title)
        creds_title_layout.addStretch()
        creds_title_layout.addWidget(creds_help)
        creds_layout.addLayout(creds_title_layout)

        creds_desc = QLabel(f"<img src='{get_asset_html_path('assets/Svg/settings.svg')}' width='13' height='13' align='top'> Saving your credentials prevents rate-limiting!")
        creds_desc.setWordWrap(True)
        creds_layout.addWidget(creds_desc)
        
        self.save_creds_btn = QPushButton(" Auto-Extract Save Keys")
        self.save_creds_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
        self.save_creds_btn.setStyleSheet("background-color: #2b5c38; font-weight: bold; padding: 5px;")
        self.save_creds_btn.clicked.connect(self.save_credentials_to_settings)
        creds_layout.addWidget(self.save_creds_btn)
        creds_group.setLayout(creds_layout)
        left_col.addWidget(creds_group)

        filters_group = QGroupBox()
        filters_layout = QVBoxLayout()
        
        filters_title_layout = QHBoxLayout()
        filters_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/target.svg')}' width='16' height='16' align='top'> <b>CONTENT FILTERS</b>")
        filters_help = SectionHelpButton("Content Filters", HELP_CONTENT["Content Filters"])
        filters_title_layout.addWidget(filters_title)
        filters_title_layout.addStretch()
        filters_title_layout.addWidget(filters_help)
        filters_layout.addLayout(filters_title_layout)

        rating_layout = QHBoxLayout()
        rating_layout.addWidget(QLabel("Min Rating:"))
        self.rating_combo = QComboBox()
        self.rating_combo.addItems(["All Ratings", "Safe Only", "Questionable & Safe", "Explicit Only"])
        rating_layout.addWidget(self.rating_combo)
        filters_layout.addLayout(rating_layout)
        
        score_layout = QHBoxLayout()
        score_layout.addWidget(QLabel("Min Score:"))
        self.score_spin = QSpinBox()
        self.score_spin.setRange(0, 10000)
        score_layout.addWidget(self.score_spin)
        filters_layout.addLayout(score_layout)
        
        limit_layout = QHBoxLayout()
        limit_layout.addWidget(QLabel("Max Downloads:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 99999)
        limit_layout.addWidget(self.limit_spin)
        filters_layout.addLayout(limit_layout)
        
        self.dl_images_cb = QCheckBox("Download Images (JPG, PNG, GIF, WEBP…)")
        self.dl_videos_cb = QCheckBox("Download Videos (MP4, WEBM, MKV, AVI…)")
        filters_layout.addWidget(self.dl_images_cb)
        filters_layout.addWidget(self.dl_videos_cb)
        filters_group.setLayout(filters_layout)
        left_col.addWidget(filters_group)

        safety_group = QGroupBox()
        safety_main_layout = QVBoxLayout()
        
        safety_title_layout = QHBoxLayout()
        safety_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/block.svg')}' width='16' height='16' align='top'> <b>CONTENT SAFETY</b>")
        safety_help = SectionHelpButton("Content Safety", HELP_CONTENT["Content Safety"])
        safety_title_layout.addWidget(safety_title)
        safety_title_layout.addStretch()
        safety_title_layout.addWidget(safety_help)
        safety_main_layout.addLayout(safety_title_layout)
        
        safety_content_layout = QHBoxLayout()
        checkboxes_layout = QVBoxLayout()
        
        self.exclude_gore_cb = QCheckBox("Exclude Gore / Extreme Violence")
        self.exclude_scat_cb = QCheckBox("Exclude Scatology")
        self.exclude_furry_cb = QCheckBox("Exclude Hardcore Furry")
        self.exclude_loli_cb = QCheckBox("Exclude Loli / Shota")
        self.exclude_vore_cb = QCheckBox("Exclude Vore / Cannibalism")
        self.exclude_insects_cb = QCheckBox("Exclude Insects / Parasites")
        self.exclude_necro_cb = QCheckBox("Exclude Necrophilia / Death")

        self.exclude_gore_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>guro, amputat, decapitat, disembowel, mutilat,<br>impal, torture, prolapse, viscera, autopsy, vivisection</p>")
        self.exclude_scat_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>scat, feces, urine, watersports, vomit,<br>puke, copro, defecat, smegma, gaper, fart</p>")
        self.exclude_furry_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>bestiality, zoophil, feral, animal_genitalia,<br>animal_penis, animal_sex, furry, anthro</p>")
        self.exclude_loli_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>loli, shota, underage, child, toddler, infant, pedoph, cub</p>")
        self.exclude_vore_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>vore, cannibalism, unbirth, absorption, digestion</p>")
        self.exclude_insects_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>insects, bugs, arachnid, spider, parasite, worms, maggots, infestation</p>")
        self.exclude_necro_cb.setToolTip("<p style='white-space:pre'><b>Blocked Tags:</b><br>necrophilia, dead, corpse, zombie, rotting, decay</p>")

        checkboxes_layout.addWidget(self.exclude_gore_cb)
        checkboxes_layout.addWidget(self.exclude_scat_cb)
        checkboxes_layout.addWidget(self.exclude_furry_cb)
        checkboxes_layout.addWidget(self.exclude_loli_cb)
        checkboxes_layout.addWidget(self.exclude_vore_cb)
        checkboxes_layout.addWidget(self.exclude_insects_cb)
        checkboxes_layout.addWidget(self.exclude_necro_cb)
        
        self.exclude_custom_cb = QCheckBox("Exclude Custom:")
        self.edit_custom_tags_btn = QPushButton()
        self.edit_custom_tags_btn.setIcon(QIcon(get_asset_path('assets/Svg/add.svg')))
        self.edit_custom_tags_btn.setFixedSize(18, 18)
        self.edit_custom_tags_btn.setToolTip("Edit custom exclusion tags")
        self.edit_custom_tags_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 3px; }
            QPushButton:hover { background: rgba(255, 255, 255, 0.1); }
        """)
        self.edit_custom_tags_btn.clicked.connect(self.open_custom_tags_editor)
        
        custom_layout = QHBoxLayout()
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.addWidget(self.exclude_custom_cb)
        custom_layout.addWidget(self.edit_custom_tags_btn)
        custom_layout.addStretch()
        
        checkboxes_layout.addLayout(custom_layout)
        
        safety_content_layout.addLayout(checkboxes_layout)
        safety_content_layout.addStretch() 
        
        safety_info_layout = QVBoxLayout()
        safety_info_layout.addStretch()
        
        info_label = QLabel(f"<img src='{get_asset_html_path('assets/Svg/help.svg')}' width='13' height='13' align='top'> Hover checkboxes to<br>see exact blocked tags")
        info_label.setStyleSheet("color: #7f8c8d; font-size: 11px; font-style: italic;")
        info_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        
        safety_info_layout.addWidget(info_label)
        
        safety_content_layout.addLayout(safety_info_layout)
        safety_main_layout.addLayout(safety_content_layout)
        safety_group.setLayout(safety_main_layout)
        left_col.addWidget(safety_group)
        
        tag_control_group = QGroupBox()
        tag_control_layout = QVBoxLayout()
        
        tag_title_layout = QHBoxLayout()
        tag_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/tag.svg')}' width='16' height='16' align='top'> <b>TAG CONTROL</b>")
        tag_help = SectionHelpButton("Tag Control", HELP_CONTENT["Tag Control"])
        tag_title_layout.addWidget(tag_title)
        tag_title_layout.addStretch()
        tag_title_layout.addWidget(tag_help)
        tag_control_layout.addLayout(tag_title_layout)
        
        tag_control_layout.addWidget(QLabel("Whitelist (Master)"))
        self.whitelist_input = QLineEdit()
        self.whitelist_input.setPlaceholderText("e.g., artist:name, safe_collection")
        tag_control_layout.addWidget(self.whitelist_input)
        
        tag_control_layout.addWidget(QLabel("Blacklist (Custom)"))
        self.custom_blacklist_input = QLineEdit()
        self.custom_blacklist_input.setPlaceholderText("e.g., guro, furry, weird_tag")
        tag_control_layout.addWidget(self.custom_blacklist_input)
        
        tag_control_group.setLayout(tag_control_layout)
        left_col.addWidget(tag_control_group)
        left_col.addStretch()
        
        db_download_group = QGroupBox()
        db_download_layout = QVBoxLayout()
        
        db_title_layout = QHBoxLayout()
        db_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/download.svg')}' width='16' height='16' align='top'> <b>DOWNLOAD DATABASE</b>")
        db_title_layout.addWidget(db_title)
        db_title_layout.addStretch()
        db_download_layout.addLayout(db_title_layout)
        
        hf_layout = QHBoxLayout()
        self.hf_download_btn = QPushButton(" Download Tag Database")
        self.hf_download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
        
        db_menu = QMenu(self)
        self.db_links = {
            "AllTags.db": "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/AllTags.db",
            "artists.db": "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/artists.db",
            "general.db": "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/general.db",
            "metadata.db": "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/metadata.db",
            "series.db": "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/series.db"
        }
        
        for db_name in self.db_links.keys():
            action = QAction(db_name, self)
            action.triggered.connect(lambda checked, n=db_name: self.download_specific_db(n))
            db_menu.addAction(action)
            
        self.hf_download_btn.setMenu(db_menu)
        hf_layout.addWidget(self.hf_download_btn)
        
        self.hf_progress_bar = QProgressBar()
        self.hf_progress_bar.setVisible(False)
        hf_layout.addWidget(self.hf_progress_bar)
        
        db_download_layout.addLayout(hf_layout)
        db_download_group.setLayout(db_download_layout)
        mid_col.addWidget(db_download_group)

        char_group = QGroupBox()
        char_layout = QVBoxLayout()
        
        char_title_layout = QHBoxLayout()
        char_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/folder.svg')}' width='16' height='16' align='top'> <b>CHARACTER FOLDERS</b>")
        char_help = SectionHelpButton("Character Routing", HELP_CONTENT["Character Routing"])
        char_title_layout.addWidget(char_title)
        char_title_layout.addStretch()
        char_title_layout.addWidget(char_help)
        char_layout.addLayout(char_title_layout)
        
        char_header_layout = QHBoxLayout()
        self.use_smart_sort_cb = QCheckBox("Enable Character Folder Sorting")
        char_header_layout.addWidget(self.use_smart_sort_cb)
        char_header_layout.addStretch()
        char_layout.addLayout(char_header_layout)
        
        char_layout.addWidget(QLabel(f"<img src='{get_asset_html_path('assets/Svg/star.svg')}' width='13' height='13' align='top'> Favorites Manager"))
        fav_input_layout = QHBoxLayout()
        self.new_fav_input = MultiCompleterLineEdit()
        self.new_fav_input.setPlaceholderText("Ctrl+Down to harvest!")
        self.add_fav_btn = QPushButton("Add")
        self.add_fav_btn.clicked.connect(self.add_character_to_db)
        fav_input_layout.addWidget(self.new_fav_input)
        fav_input_layout.addWidget(self.add_fav_btn)
        char_layout.addLayout(fav_input_layout)

        self.fav_list_widget = FavoritesListWidget()
        self.fav_list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.fav_list_widget.delete_requested.connect(self.remove_selected_favorites)
        char_layout.addWidget(self.fav_list_widget)

        self.favorites_only_cb = QCheckBox("Only create folders for favorites")
        char_layout.addWidget(self.favorites_only_cb)

        char_group.setLayout(char_layout)
        mid_col.addWidget(char_group)

        scene_group = QGroupBox()
        scene_layout = QVBoxLayout()
        
        scene_title_layout = QHBoxLayout()
        scene_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/palette.svg')}' width='16' height='16' align='top'> <b>SCENE / TAG FOLDERS (PRIORITY BASED)</b>")
        scene_help = SectionHelpButton("Scene Routing", HELP_CONTENT["Scene Routing"])
        scene_title_layout.addWidget(scene_title)
        scene_title_layout.addStretch()
        scene_title_layout.addWidget(scene_help)
        
        self.expand_scene_btn = QPushButton()
        self.expand_scene_btn.setFixedSize(28, 28)
        self.expand_scene_btn.setToolTip("Expand to Full Screen")
        self.expand_scene_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if os.path.exists(self.expand_icon_path):
            self.expand_scene_btn.setIcon(QIcon(self.expand_icon_path))
            self.expand_scene_btn.setIconSize(QSize(18, 18))
        else:
            self.expand_scene_btn.setText("🗖") 
            
        self.expand_scene_btn.setStyleSheet("""
            QPushButton { 
                background-color: transparent; 
                border-radius: 4px; 
            }
            QPushButton:hover { background-color: #3b3b3b; }
        """)
        self.expand_scene_btn.clicked.connect(self.toggle_scene_fullscreen)
        scene_title_layout.addWidget(self.expand_scene_btn)
        
        scene_layout.addLayout(scene_title_layout)
        
        scene_top_layout = QHBoxLayout()
        self.use_scene_sort_cb = QCheckBox("Enable Scene/Tag Folder Sorting")
        
        scene_top_layout.addWidget(self.use_scene_sort_cb)
        scene_top_layout.addStretch() 
        
        scene_layout.addLayout(scene_top_layout)
        
        scene_input_layout = QHBoxLayout()
        self.scene_input = QLineEdit()
        self.scene_input.setPlaceholderText("e.g., bikini, beach, 2girls...")
        self.add_scene_btn = QPushButton(" Add Tag")
        self.add_scene_btn.setIcon(QIcon(get_asset_path("assets/Svg/add.svg")))
        self.add_scene_btn.clicked.connect(self.add_scene_tag)
        scene_input_layout.addWidget(self.scene_input)
        scene_input_layout.addWidget(self.add_scene_btn)
        scene_layout.addLayout(scene_input_layout)

        self.scene_list_widget = QListWidget()
        self.scene_list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.scene_list_widget.setDragDropMode(QAbstractItemView.InternalMove) 
        scene_layout.addWidget(self.scene_list_widget)

        priority_btn_layout = QHBoxLayout()
        self.scene_up_btn = QPushButton("↑ Move Up")
        self.scene_down_btn = QPushButton("↓ Move Down")
        self.scene_del_btn = QPushButton(" Delete")
        self.scene_del_btn.setIcon(QIcon(get_asset_path("assets/Svg/trash.svg")))
        self.scene_up_btn.clicked.connect(self.move_scene_up)
        self.scene_down_btn.clicked.connect(self.move_scene_down)
        self.scene_del_btn.clicked.connect(self.delete_scene_tag)

        priority_btn_layout.addWidget(self.scene_up_btn)
        priority_btn_layout.addWidget(self.scene_down_btn)
        priority_btn_layout.addWidget(self.scene_del_btn)
        scene_layout.addLayout(priority_btn_layout)

        scene_note = QLabel(f"<img src='{get_asset_html_path('assets/Svg/help.svg')}' width='13' height='13' align='top'> Note: Tags must exactly match general tags on Rule34.xxx")
        scene_note.setStyleSheet("color: gray; font-style: italic;")
        scene_layout.addWidget(scene_note)

        scene_group.setLayout(scene_layout)
        right_col.addWidget(scene_group)

        self.alias_group = QGroupBox()
        alias_layout = QVBoxLayout()
        
        alias_title_layout = QHBoxLayout()
        alias_title = QLabel(f"<img src='{get_asset_html_path('assets/Svg/link.svg')}' width='16' height='16' align='top'> <b>TAG ALIASES (MERGE SYNONYMS)</b>")
        alias_help = SectionHelpButton("Tag Aliases", HELP_CONTENT["Tag Aliases"])
        alias_title_layout.addWidget(alias_title)
        alias_title_layout.addStretch()
        alias_title_layout.addWidget(alias_help)
        alias_layout.addLayout(alias_title_layout)

        alias_header_layout = QHBoxLayout()
        alias_desc = QLabel("Format: Master_Tag = alias1, alias2")
        alias_desc.setStyleSheet("color: gray; font-style: italic;")
        alias_header_layout.addWidget(alias_desc)
        alias_header_layout.addStretch()
        alias_layout.addLayout(alias_header_layout)

        alias_input_layout = QHBoxLayout()
        self.alias_input = QLineEdit()
        self.alias_input.setPlaceholderText("e.g., 1girl = solo, female")
        self.add_alias_btn = QPushButton(" Add Rule")
        self.add_alias_btn.setIcon(QIcon(get_asset_path("assets/Svg/add.svg")))
        self.add_alias_btn.clicked.connect(self.add_alias)
        alias_input_layout.addWidget(self.alias_input)
        alias_input_layout.addWidget(self.add_alias_btn)
        alias_layout.addLayout(alias_input_layout)

        self.alias_list_widget = QListWidget()
        self.alias_list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        alias_layout.addWidget(self.alias_list_widget)
        
        alias_action_layout = QHBoxLayout()
        self.del_alias_btn = QPushButton(" Delete Rule")
        self.del_alias_btn.setIcon(QIcon(get_asset_path("assets/Svg/trash.svg")))
        self.del_alias_btn.clicked.connect(self.delete_alias)
        
        self.fetch_alias_btn = QPushButton(" Load Community Rules")
        self.fetch_alias_btn.setIcon(QIcon(get_asset_path("assets/Svg/link.svg")))
        self.fetch_alias_btn.setStyleSheet("background-color: #2b4b7c; color: white; font-weight: bold;")
        self.fetch_alias_btn.clicked.connect(self.fetch_github_aliases)
        
        alias_action_layout.addWidget(self.del_alias_btn)
        alias_action_layout.addWidget(self.fetch_alias_btn)
        alias_layout.addLayout(alias_action_layout)

        self.alias_group.setLayout(alias_layout)
        right_col.addWidget(self.alias_group)

        columns_layout.addWidget(self.left_container, 1)
        columns_layout.addWidget(self.mid_container, 1)
        columns_layout.addWidget(self.right_container, 1)
        
        settings_scroll.setWidget(scroll_content)
        master_layout.addWidget(settings_scroll)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 10, 0, 10) 
        
        save_btn = QPushButton("Save Settings")
        cancel_btn = QPushButton("Cancel")
        
        save_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        master_layout.addLayout(btn_layout)
        
        # Force the window to fit the content perfectly so no scrollbar is needed
        ideal_height = scroll_content.sizeHint().height() + 120
        self.resize(1150, ideal_height)

    def toggle_scene_fullscreen(self):
        self.scene_is_expanded = getattr(self, 'scene_is_expanded', False)
        
        if not self.scene_is_expanded:
            self.left_container.setVisible(False)
            self.mid_container.setVisible(False)
            self.alias_group.setVisible(False)
            
            if os.path.exists(self.restore_icon_path):
                self.expand_scene_btn.setIcon(QIcon(self.restore_icon_path))
            else:
                self.expand_scene_btn.setText("🗗") 
                
            self.expand_scene_btn.setToolTip("Restore Default View")
            self.scene_is_expanded = True
        else:
            self.left_container.setVisible(True)
            self.mid_container.setVisible(True)
            self.alias_group.setVisible(True)
            
            if os.path.exists(self.expand_icon_path):
                self.expand_scene_btn.setIcon(QIcon(self.expand_icon_path))
            else:
                self.expand_scene_btn.setText("🗖") 
                
            self.expand_scene_btn.setToolTip("Expand to Full Screen")
            self.scene_is_expanded = False

    def fetch_github_aliases(self):
        if not self.GITHUB_RAW_URL or "YOUR_USERNAME" in self.GITHUB_RAW_URL:
            QMessageBox.warning(self, "Setup Required", "Please update the 'GITHUB_RAW_URL' in the code with your actual GitHub link!")
            return
            
        try:
            req = urllib.request.Request(self.GITHUB_RAW_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                text = response.read().decode('utf-8')
                
            added_count = 0
            existing_rules = [self.alias_list_widget.item(i).text() for i in range(self.alias_list_widget.count())]
            
            for line in text.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'): 
                    continue
                if "=" in line and line not in existing_rules:
                    self.alias_list_widget.insertItem(0, line)
                    existing_rules.append(line)
                    added_count += 1
                    
            if added_count > 0:
                QMessageBox.information(self, "Success", f"Successfully loaded {added_count} new alias rules from GitHub!")
            else:
                QMessageBox.information(self, "Up to Date", "No new rules found. You are completely up to date!")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch rules from GitHub:\n{str(e)}")

    def add_scene_tag(self):
        tags = [t.strip().lower() for t in self.scene_input.text().split(',') if t.strip()]
        for tag in tags:
            items = self.scene_list_widget.findItems(tag, Qt.MatchFlag.MatchExactly)
            if not items:
                self.scene_list_widget.insertItem(0, tag) 
        self.scene_input.clear()

    def move_scene_up(self):
        row = self.scene_list_widget.currentRow()
        if row > 0:
            item = self.scene_list_widget.takeItem(row)
            self.scene_list_widget.insertItem(row - 1, item)
            self.scene_list_widget.setCurrentRow(row - 1)

    def move_scene_down(self):
        row = self.scene_list_widget.currentRow()
        if row < self.scene_list_widget.count() - 1 and row != -1:
            item = self.scene_list_widget.takeItem(row)
            self.scene_list_widget.insertItem(row + 1, item)
            self.scene_list_widget.setCurrentRow(row + 1)

    def delete_scene_tag(self):
        for item in self.scene_list_widget.selectedItems():
            self.scene_list_widget.takeItem(self.scene_list_widget.row(item))

    def add_alias(self):
        text = self.alias_input.text().strip()
        if "=" in text:
            self.alias_list_widget.insertItem(0, text)
            self.alias_input.clear()
        else:
            QMessageBox.warning(self, "Invalid Format", "Please use the format: Master_Tag = alias1, alias2")

    def delete_alias(self):
        for item in self.alias_list_widget.selectedItems():
            self.alias_list_widget.takeItem(self.alias_list_widget.row(item))

    def load_settings(self):
        settings = self.main_app.settings
        self.rating_combo.setCurrentIndex(int(settings.value("r34_rating_filter", 0)))
        self.score_spin.setValue(int(settings.value("r34_min_score", 0)))
        self.limit_spin.setValue(int(settings.value("r34_max_downloads", 0)))
        self.dl_images_cb.setChecked(settings.value("r34_download_images", True, type=bool))
        self.dl_videos_cb.setChecked(settings.value("r34_download_videos", True, type=bool))
        self.custom_blacklist_input.setText(settings.value("r34_custom_blacklist", ""))
        
        self.exclude_gore_cb.setChecked(settings.value("r34_exclude_gore", False, type=bool))
        self.exclude_scat_cb.setChecked(settings.value("r34_exclude_scat", False, type=bool))
        self.exclude_furry_cb.setChecked(settings.value("r34_exclude_furry", False, type=bool))
        self.exclude_loli_cb.setChecked(settings.value("r34_exclude_loli", False, type=bool))
        self.exclude_vore_cb.setChecked(settings.value("r34_exclude_vore", False, type=bool))
        self.exclude_insects_cb.setChecked(settings.value("r34_exclude_insects", False, type=bool))
        self.exclude_necro_cb.setChecked(settings.value("r34_exclude_necro", False, type=bool))
        self.exclude_custom_cb.setChecked(settings.value("r34_exclude_custom", False, type=bool))
        self.custom_safety_tags_str = str(settings.value("r34_custom_safety_tags", ""))
        
        self.whitelist_input.setText(settings.value("r34_whitelist", ""))
        
        self.use_smart_sort_cb.setChecked(settings.value("r34_smart_sort", False, type=bool))
        self.favorites_only_cb.setChecked(settings.value("r34_favorites_only", False, type=bool))
        
        self.use_scene_sort_cb.setChecked(settings.value("r34_use_scene_sort", False, type=bool))
        scene_tags_str = settings.value("r34_scene_tags", "1girl,bikini,beach")
        if scene_tags_str:
            self.scene_list_widget.addItems(scene_tags_str.split(','))

        alias_str = settings.value("r34_tag_aliases", "1girl = solo, single, women")
        if alias_str:
            self.alias_list_widget.addItems(alias_str.split('||'))
            
        fav_str = settings.value("r34_character_favorites", "")
        if fav_str:
            self.fav_list_widget.addItems([f for f in fav_str.split('||') if f])

    def accept(self):
        settings = self.main_app.settings
        settings.setValue("r34_rating_filter", self.rating_combo.currentIndex())
        settings.setValue("r34_min_score", self.score_spin.value())
        settings.setValue("r34_max_downloads", self.limit_spin.value())
        settings.setValue("r34_download_images", self.dl_images_cb.isChecked())
        settings.setValue("r34_download_videos", self.dl_videos_cb.isChecked())
        settings.setValue("r34_custom_blacklist", self.custom_blacklist_input.text().strip())
        
        settings.setValue("r34_exclude_gore", self.exclude_gore_cb.isChecked())
        settings.setValue("r34_exclude_scat", self.exclude_scat_cb.isChecked())
        settings.setValue("r34_exclude_furry", self.exclude_furry_cb.isChecked())
        settings.setValue("r34_exclude_loli", self.exclude_loli_cb.isChecked())
        settings.setValue("r34_exclude_vore", self.exclude_vore_cb.isChecked())
        settings.setValue("r34_exclude_insects", self.exclude_insects_cb.isChecked())
        settings.setValue("r34_exclude_necro", self.exclude_necro_cb.isChecked())
        settings.setValue("r34_exclude_custom", self.exclude_custom_cb.isChecked())
        settings.setValue("r34_custom_safety_tags", getattr(self, 'custom_safety_tags_str', ""))
        
        settings.setValue("r34_whitelist", self.whitelist_input.text().strip())
        
        settings.setValue("r34_smart_sort", self.use_smart_sort_cb.isChecked())
        settings.setValue("r34_favorites_only", self.favorites_only_cb.isChecked())
        
        settings.setValue("r34_use_scene_sort", self.use_scene_sort_cb.isChecked())
        scenes = [self.scene_list_widget.item(i).text() for i in range(self.scene_list_widget.count())]
        settings.setValue("r34_scene_tags", ",".join(scenes))

        aliases = [self.alias_list_widget.item(i).text() for i in range(self.alias_list_widget.count())]
        settings.setValue("r34_tag_aliases", "||".join(aliases))
        
        favs = [self.fav_list_widget.item(i).text() for i in range(self.fav_list_widget.count())]
        settings.setValue("r34_character_favorites", "||".join(favs))
        
        super().accept()

    def add_character_to_db(self):
        input_text = self.new_fav_input.text()
        new_chars = [c.strip().lower() for c in input_text.split(',') if c.strip()]
        if not new_chars: return
        
        for new_char in reversed(new_chars):
            items = self.fav_list_widget.findItems(new_char, Qt.MatchFlag.MatchExactly)
            if not items:
                self.fav_list_widget.insertItem(0, new_char)
                
        self.new_fav_input.clear()
        if hasattr(self, 'char_completer'):
            self.char_completer.current_prefix = "" 

    def remove_selected_favorites(self):
        selected_items = self.fav_list_widget.selectedItems()
        if not selected_items: return
        
        for item in selected_items:
            self.fav_list_widget.takeItem(self.fav_list_widget.row(item))

    def save_credentials_to_settings(self):
        has_creds = hasattr(self.main_app, 'booru_creds_input')
        has_url = hasattr(self.main_app, 'link_input')
        if not has_creds or not has_url: return
        
        current_creds = self.main_app.booru_creds_input.text().strip()
        current_url = self.main_app.link_input.text().strip().lower()
        
        api_match = re.search(r'api_key=([a-zA-Z0-9_-]+)', current_creds)
        user_match = re.search(r'user_id=([0-9]+)', current_creds)
        
        is_booru_url = any(site in current_url for site in ["rule34.xxx", "gelbooru.com", "danbooru.donmai.us"])
        
        if is_booru_url and api_match:
            self.main_app.settings.setValue("r34_api_key", api_match.group(1))
            if user_match: 
                self.main_app.settings.setValue("r34_user_id", user_match.group(1))
            QMessageBox.information(self, "Success", "✅ Booru Credentials saved successfully!")
        elif not is_booru_url:
            QMessageBox.warning(self, "Invalid URL", "Please paste a valid Booru link (Rule34, Gelbooru, Danbooru) in the main window before saving credentials.")
        else:
            QMessageBox.warning(self, "Missing Key", "Could not find 'api_key=' in the credentials box.")

    def download_specific_db(self, db_name):
        url = self.db_links.get(db_name)
        if not url: return
            
        save_path = os.path.join(self.db_dir, db_name)
            
        self.hf_download_btn.setEnabled(False)
        self.hf_progress_bar.setVisible(True)
        self.hf_progress_bar.setValue(0)
        
        self.download_thread = HuggingFaceDownloadThread(
            url, 
            save_path, 
            self
        )
        self.download_thread.progress_signal.connect(self.hf_progress_bar.setValue)
        self.current_download_db = db_name
        self.download_thread.finished_signal.connect(self.on_db_download_finished)
        self.download_thread.start()

    def on_db_download_finished(self, success, message):
        self.hf_progress_bar.setVisible(False)
        db_name = getattr(self, 'current_download_db', "Database")
        if success:
            if db_name == "AllTags.db":
                self.all_tags_cache.clear()
                self.setup_autocomplete()
            
            QMessageBox.information(self, "Success", f"{db_name} downloaded and installed successfully!")
        else:
            QMessageBox.critical(self, "Download Failed", f"Failed to fetch {db_name}: {message}")
            
        self.hf_download_btn.setEnabled(True)

    def setup_autocomplete(self):
        def make_completer(line_edit):
            completer = MultiCompleter([], self)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setMaxVisibleItems(15) 
            completer.setWrapAround(False) 
            try:
                line_edit.textEdited.disconnect()
            except TypeError:
                pass
            line_edit.setCompleter(completer)
            line_edit.textEdited.connect(lambda text, le=line_edit, c=completer: self.on_text_edited(text, le, c))
            return completer
            
        if hasattr(self, 'new_fav_input'):
            self.char_completer = make_completer(self.new_fav_input)
        self.gen_completer = make_completer(self.scene_input)
        self.all_completer1 = make_completer(self.whitelist_input)
        self.all_completer2 = make_completer(self.custom_blacklist_input)
        self.all_completer3 = make_completer(self.alias_input)

    def on_text_edited(self, text, line_edit, completer):
        if ',' in text:
            prefix = text[:text.rfind(',') + 1]
            if not prefix.endswith(" "):
                prefix += " "
            completer.current_prefix = prefix
        else:
            completer.current_prefix = ""
            
        self.active_completer_data = (line_edit, completer)
        self.search_timer.start(300)

    def update_completer_model(self):
        if not hasattr(self, 'active_completer_data'):
            return
            
        line_edit, completer = self.active_completer_data
        
        try:
            text = line_edit.text()
        except RuntimeError:
            # Widget was deleted (e.g. custom dialog closed)
            return
        search_text = text.split(',')[-1].strip().lower()
        
        if line_edit == getattr(self, 'alias_input', None) and '=' in search_text:
            search_text = search_text.split('=')[-1].strip()
            
        if len(search_text) < 2:
            completer.model().setStringList([])
            return

        search_sql = f"%{search_text}%"
        all_tags_db = os.path.join(self.db_dir, "AllTags.db")
        raw_matches = []
        
        def _query(path, query, params):
            if not os.path.exists(path): return []
            try:
                with sqlite3.connect(path) as conn:
                    c = conn.cursor()
                    c.execute(query, params)
                    return c.fetchall()
            except Exception as e:
                print(f"DB Query Error: {e}")
                return []

        if line_edit == getattr(self, 'new_fav_input', None):
            rows = _query(all_tags_db, "SELECT name FROM CharacterTags WHERE name LIKE ? ORDER BY count DESC LIMIT 200", (search_sql,))
            raw_matches = [r[0] for r in rows]
                
        elif line_edit == getattr(self, 'scene_input', None):
            gen_db = os.path.join(self.db_dir, "general.db")
            if os.path.exists(gen_db):
                rows = _query(gen_db, "SELECT name FROM Tags WHERE name LIKE ? ORDER BY count DESC LIMIT 200", (search_sql,))
                raw_matches = [r[0] for r in rows]
            else:
                rows = _query(all_tags_db, "SELECT name FROM GeneralTags WHERE name LIKE ? ORDER BY count DESC LIMIT 200", (search_sql,))
                raw_matches = [r[0] for r in rows]
                
        else:
            if os.path.exists(all_tags_db):
                tables = ["CharacterTags", "GeneralTags", "ArtistTags", "SeriesTags", "MetadataTags"]
                queries = [f"SELECT name, count FROM {t} WHERE name LIKE ?" for t in tables]
                full_query = " UNION ALL ".join(queries) + " ORDER BY count DESC LIMIT 200"
                params = (search_sql,) * len(tables)
                rows = _query(all_tags_db, full_query, params)
                raw_matches = [r[0] for r in rows]
            else:
                dbs = ["characters.db", "general.db", "artists.db", "series.db", "metadata.db"]
                all_results = []
                for db_name in dbs:
                    db_path = os.path.join(self.db_dir, db_name)
                    all_results.extend(_query(db_path, "SELECT name, count FROM Tags WHERE name LIKE ? ORDER BY count DESC LIMIT 100", (search_sql,)))
                all_results.sort(key=lambda x: x[1], reverse=True)
                raw_matches = [x[0] for x in all_results[:200]]

        if not raw_matches:
            completer.model().setStringList([])
            return

        def get_score(tag):
            t = tag.lower()
            has_franchise = "(" in t and ")" in t
            if has_franchise and (t.startswith(search_text + " ") or t.startswith(search_text + "_") or t.startswith(search_text + "(")): return 1
            if t == search_text: return 2
            if t.startswith(search_text + " ") or t.startswith(search_text + "_"): return 3
            if t.startswith(search_text) and has_franchise: return 4
            if t.startswith(search_text): return 5
            if f" {search_text}" in t or f"_{search_text}" in t or f"({search_text}" in t: return 6 if has_franchise else 7
            return 8

        raw_matches.sort(key=lambda x: (get_score(x), len(x), x))
        completer.model().setStringList(raw_matches[:40])
        completer.complete()

    def open_custom_tags_editor(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Exclusion Tags")
        dialog.setMinimumSize(350, 450)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Add tags to your custom exclusion preset:"))
        
        input_layout = QHBoxLayout()
        tag_input = MultiCompleterLineEdit()
        tag_input.setPlaceholderText("Search tags to exclude...")
        add_btn = QPushButton("Add")
        input_layout.addWidget(tag_input)
        input_layout.addWidget(add_btn)
        layout.addLayout(input_layout)
        
        completer = MultiCompleter([], self)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setMaxVisibleItems(15)
        completer.setWrapAround(False)
        tag_input.setCompleter(completer)
        tag_input.textEdited.connect(lambda text, le=tag_input, c=completer: self.on_text_edited(text, le, c))
        
        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        current_tags_str = getattr(self, 'custom_safety_tags_str', "")
        current_tags = [t.strip() for t in current_tags_str.split(',') if t.strip()]
        for tag in current_tags:
            list_widget.addItem(tag)
        layout.addWidget(list_widget)
        
        def add_tag():
            text = tag_input.text().strip().lower()
            if text:
                for t in text.split(','):
                    t = t.strip()
                    if t and not list_widget.findItems(t, Qt.MatchFlag.MatchExactly):
                        list_widget.addItem(t)
                tag_input.clear()
                
        add_btn.clicked.connect(add_tag)
        tag_input.returnPressed.connect(add_tag)
        
        remove_btn = QPushButton("Remove Selected")
        def remove_tags():
            for item in list_widget.selectedItems():
                list_widget.takeItem(list_widget.row(item))
        remove_btn.clicked.connect(remove_tags)
        
        def keyPressEvent(event):
            if event.key() == Qt.Key.Key_Delete:
                remove_tags()
            else:
                QListWidget.keyPressEvent(list_widget, event)
        list_widget.keyPressEvent = keyPressEvent
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(remove_btn)
        
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
        
        def on_close():
            if hasattr(self, 'active_completer_data') and self.active_completer_data[0] == tag_input:
                del self.active_completer_data
                
        dialog.finished.connect(lambda result: on_close())
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            tags = [list_widget.item(i).text() for i in range(list_widget.count())]
            self.custom_safety_tags_str = ",".join(tags)