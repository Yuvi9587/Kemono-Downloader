import os
import json
import re
import csv
from collections import defaultdict
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QListWidget, QRadioButton,
    QButtonGroup, QCheckBox, QSplitter, QGroupBox, QDialog, QStackedWidget,
    QScrollArea, QListWidgetItem, QSizePolicy, QProgressBar, QAbstractItemView, QFrame,
    QMainWindow, QGridLayout,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

class ExportLinksDialog(QDialog):
    """
    A dialog for exporting extracted links with various format options, including custom templates.
    Operates in two modes:
    - Export Mode: links_data is provided. Exports data immediately.
    - Config Mode: links_data is None. Saves settings for later use.
    """
    def __init__(self, links_data=None, parent=None, default_config=None, context='both'):
        super().__init__(parent)
        self.links_data = links_data
        self.config_mode = links_data is None
        self.default_config = default_config or {}
        self.context = context
        
        title = "Export Extracted Links Settings" if self.config_mode else "Export Extracted Links"
        self.setWindowTitle(title)
        self.setMinimumWidth(600)
        self._setup_ui()
        self._load_default_config()
        self._update_options_visibility()

    def _setup_ui(self):
        """Initializes the UI components of the dialog."""
        main_layout = QVBoxLayout(self)

        format_group = QGroupBox("Export Format")
        format_layout = QHBoxLayout()
        self.radio_txt = QRadioButton("Plain Text (.txt)")
        self.radio_json = QRadioButton("JSON (.json)")
        self.radio_csv = QRadioButton("CSV (.csv)")
        self.radio_md = QRadioButton("Markdown (.md)")
        self.radio_txt.setChecked(True)
        format_layout.addWidget(self.radio_txt)
        format_layout.addWidget(self.radio_json)
        format_layout.addWidget(self.radio_csv)
        format_layout.addWidget(self.radio_md)
        format_group.setLayout(format_layout)
        main_layout.addWidget(format_group)

        self.txt_options_group = QGroupBox("TXT / Markdown Options")
        txt_options_layout = QVBoxLayout()
        
        self.txt_mode_group = QButtonGroup(self)
        self.radio_simple = QRadioButton("Simple (URL only, one per line)")
        self.radio_detailed = QRadioButton("Detailed (with metadata)")
        self.radio_custom = QRadioButton("Custom Format Template")
        
        self.txt_mode_group.addButton(self.radio_simple)
        self.txt_mode_group.addButton(self.radio_detailed)
        self.txt_mode_group.addButton(self.radio_custom)
        
        txt_options_layout.addWidget(self.radio_simple)
        txt_options_layout.addWidget(self.radio_detailed)
        
        self.detailed_options_widget = QWidget()
        detailed_layout = QVBoxLayout(self.detailed_options_widget)
        detailed_layout.setContentsMargins(20, 5, 0, 5)
        self.check_include_titles = QCheckBox("Include post/thread titles as separators")
        self.check_include_link_text = QCheckBox("Include link text/description")
        self.check_include_platform = QCheckBox("Include platform (e.g., Mega, Bunkr)")
        detailed_layout.addWidget(self.check_include_titles)
        detailed_layout.addWidget(self.check_include_link_text)
        detailed_layout.addWidget(self.check_include_platform)
        txt_options_layout.addWidget(self.detailed_options_widget)

        txt_options_layout.addWidget(self.radio_custom)

        self.custom_format_widget = QWidget()
        custom_layout = QVBoxLayout(self.custom_format_widget)
        custom_layout.setContentsMargins(20, 5, 0, 5)
        placeholders_label = QLabel("Click to insert placeholder:")
        custom_layout.addWidget(placeholders_label)
        btn_layout = QGridLayout()
        btn_layout.setContentsMargins(0, 0, 0, 5)
        btn_layout.setSpacing(5)
        
        all_placeholders = [
            ('{url}', 'URL of the file/page', 'both'), 
            ('{platform}', 'Source platform (Mega, etc)', 'both'), 
            ('{post_title}', 'Kemono Post Title', 'kemono'), 
            ('{link_text}', 'Link text description', 'kemono'), 
            ('{key}', 'Extracted file/folder key (Mega, GDrive, GoFile)', 'both'),
            ('{thread_title}', 'SimpCity Thread Title', 'simpcity'), 
            ('{post_id}', 'SimpCity Post ID', 'simpcity'), 
            ('{username}', 'Creator Username', 'simpcity'), 
            ('{date}', 'Published Date', 'simpcity')
        ]
        
        filtered_placeholders = [p for p in all_placeholders if p[2] == 'both' or p[2] == self.context or self.context == 'both']
        
        row, col = 0, 0
        for p_text, p_tooltip, _ in filtered_placeholders:
            btn = QPushButton(p_text)
            btn.setToolTip(p_tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            def insert_text(checked=False, t=p_text):
                formatted = f" {t}\n" if t == '{url}' else f"[{t}] "
                self.custom_format_input.insertPlainText(formatted)
                
            btn.clicked.connect(insert_text)
            btn_layout.addWidget(btn, row, col)
            col += 1
            if col > 4:
                col = 0
                row += 1

        self.custom_format_input = QTextEdit()
        self.custom_format_input.setAcceptRichText(False)
        self.custom_format_input.setPlaceholderText("Enter your format, e.g., Title: {post_title}\\nLink: {url}")
        self.custom_format_input.setText("{url}")
        self.custom_format_input.setFixedHeight(80)
        
        custom_layout.addLayout(btn_layout)
        custom_layout.addWidget(self.custom_format_input)
        txt_options_layout.addWidget(self.custom_format_widget)

        self.txt_options_group.setLayout(txt_options_layout)
        main_layout.addWidget(self.txt_options_group)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)
        
        self.check_separate_files = QCheckBox("Save each platform to a separate file (e.g., export_mega.txt)")
        main_layout.addWidget(self.check_separate_files)

        self.path_widget = QWidget()
        path_layout = QHBoxLayout(self.path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Output file path (or folder if separating by platform)")
        self.browse_button = QPushButton("Browse...")
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(self.browse_button)
        main_layout.addWidget(self.path_widget)
        
        if self.config_mode:
            self.path_widget.setVisible(False)
        
        button_layout = QHBoxLayout()
        self.reset_btn = QPushButton("Reset to Default")
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.clicked.connect(self._reset_custom_template)
        button_layout.addWidget(self.reset_btn)
        button_layout.addStretch(1)
        self.export_button = QPushButton("Save Settings" if self.config_mode else "Export")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.radio_txt.toggled.connect(self._update_options_visibility)
        self.radio_json.toggled.connect(self._update_options_visibility)
        self.radio_csv.toggled.connect(self._update_options_visibility)
        self.radio_md.toggled.connect(self._update_options_visibility)
        self.radio_simple.toggled.connect(self._update_options_visibility)
        self.radio_detailed.toggled.connect(self._update_options_visibility)
        self.radio_custom.toggled.connect(self._update_options_visibility)
        self.check_separate_files.toggled.connect(self._update_options_visibility)
        
        self.browse_button.clicked.connect(self._browse)
        self.export_button.clicked.connect(self._accept_and_export)
        self.cancel_button.clicked.connect(self.reject)
        
        self.radio_simple.setChecked(True)

    def _load_default_config(self):
        if not self.default_config: return
        fmt = self.default_config.get('format', 'txt')
        if fmt == 'txt': self.radio_txt.setChecked(True)
        elif fmt == 'json': self.radio_json.setChecked(True)
        elif fmt == 'csv': self.radio_csv.setChecked(True)
        elif fmt == 'md': self.radio_md.setChecked(True)
        
        mode = self.default_config.get('txt_mode', 'simple')
        if mode == 'simple': self.radio_simple.setChecked(True)
        elif mode == 'detailed': self.radio_detailed.setChecked(True)
        elif mode == 'custom': self.radio_custom.setChecked(True)
        
        self.check_include_titles.setChecked(self.default_config.get('include_titles', False))
        self.check_include_link_text.setChecked(self.default_config.get('include_link_text', False))
        self.check_include_platform.setChecked(self.default_config.get('include_platform', False))
        
        default_template = '[{platform}] [{thread_title}] [{post_id}] [{username}] [{date}] [{key}]\n{url}\n' if self.context == 'simpcity' else '{url}\n'
        self.custom_format_input.setText(self.default_config.get('custom_template', default_template))
        self.check_separate_files.setChecked(self.default_config.get('separate_files', False))
        self.path_input.setText(self.default_config.get('filepath', ''))

    def _reset_custom_template(self):
        default_template = '[{platform}] [{thread_title}] [{post_id}] [{username}] [{date}] [{key}]\n{url}\n' if self.context == 'simpcity' else '{url}\n'
        self.custom_format_input.setText(default_template)

    def _update_options_visibility(self):
        is_txt_or_md = self.radio_txt.isChecked() or self.radio_md.isChecked()
        self.txt_options_group.setVisible(is_txt_or_md)
        
        if is_txt_or_md:
            self.detailed_options_widget.setVisible(self.radio_detailed.isChecked())
            self.custom_format_widget.setVisible(self.radio_custom.isChecked())
            
        self.reset_btn.setVisible(is_txt_or_md and self.radio_custom.isChecked())
            
        QApplication.processEvents()
        self.adjustSize()

    def _browse(self):
        is_separate_files_mode = self.check_separate_files.isChecked()
        
        if is_separate_files_mode:
            dir_path = QFileDialog.getExistingDirectory(self, "Select Folder to Save Files")
            if dir_path:
                self.path_input.setText(os.path.join(dir_path, "exported_links"))
        else:
            default_filename = "exported_links"
            if self.radio_json.isChecked():
                default_filename += ".json"
                file_filter = "JSON Files (*.json)"
            elif self.radio_csv.isChecked():
                default_filename += ".csv"
                file_filter = "CSV Files (*.csv)"
            elif self.radio_md.isChecked():
                default_filename += ".md"
                file_filter = "Markdown Files (*.md)"
            else:
                default_filename += ".txt"
                file_filter = "Text Files (*.txt)"
            
            filepath, _ = QFileDialog.getSaveFileName(self, "Save Links", default_filename, file_filter)
            if filepath:
                self.path_input.setText(filepath)

    def get_config(self):
        fmt = 'txt'
        if self.radio_json.isChecked(): fmt = 'json'
        elif self.radio_csv.isChecked(): fmt = 'csv'
        elif self.radio_md.isChecked(): fmt = 'md'
        
        mode = 'simple'
        if self.radio_detailed.isChecked(): mode = 'detailed'
        elif self.radio_custom.isChecked(): mode = 'custom'
        
        return {
            'format': fmt,
            'txt_mode': mode,
            'include_titles': self.check_include_titles.isChecked(),
            'include_link_text': self.check_include_link_text.isChecked(),
            'include_platform': self.check_include_platform.isChecked(),
            'custom_template': self.custom_format_input.toPlainText().replace("\\n", "\n"),
            'separate_files': self.check_separate_files.isChecked(),
            'filepath': self.path_input.text().strip()
        }

    def _accept_and_export(self):
        if not self.config_mode:
            filepath = self.path_input.text().strip()
            if not filepath:
                QMessageBox.warning(self, "Input Error", "Please select a file path or folder.")
                return

        if self.config_mode:
            self.accept()
            return

        try:
            config = self.get_config()
            self._write_files(filepath, config)
            QMessageBox.information(self, "Export Successful", "Links successfully exported!")
            self.accept()
        except OSError as e:
            QMessageBox.critical(self, "Export Error", f"Could not write to file:\n{e}")

    def _write_files(self, base_filepath, config):
        if config['separate_files']:
            links_by_platform = defaultdict(list)
            for item in self.links_data:
                platform = "unknown"
                if isinstance(item, tuple) and len(item) == 5:
                    platform = item[3]
                elif isinstance(item, dict):
                    platform = item.get('platform', 'unknown')
                    
                sanitized_platform = re.sub(r'[<>:"/\\|?*]', '_', platform.lower().replace(' ', '_'))
                links_by_platform[sanitized_platform].append(item)
            
            base, ext = os.path.splitext(base_filepath)
            if not ext: ext = f".{config['format']}"

            for platform_key, items in links_by_platform.items():
                platform_filepath = f"{base}_{platform_key}{ext}"
                self._write_format(platform_filepath, items, config)
        else:
            self._write_format(base_filepath, self.links_data, config)

    @staticmethod
    def extract_key_from_url(url):
        if not url: return ""
        # mega.nz
        if 'mega.nz' in url:
            match = re.search(r'mega\.nz/(?:folder|file)/([^/?\s]+)', url)
            if match: return match.group(1)
            match = re.search(r'mega\.nz/(?:#F!|#!)([^/?\s]+)', url)
            if match: return match.group(1)
            
        # drive.google.com
        if 'drive.google.com' in url:
            match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
            if match: return match.group(1)
            match = re.search(r'/folders/([a-zA-Z0-9_-]+)', url)
            if match: return match.group(1)
            
        # gofile.io
        if 'gofile.io' in url:
            match = re.search(r'gofile\.io/d/([a-zA-Z0-9_-]+)', url)
            if match: return match.group(1)
            
        # pixeldrain
        if 'pixeldrain' in url:
            match = re.search(r'/u/([a-zA-Z0-9_-]+)', url)
            if match: return match.group(1)
            
        # bunkr
        if 'bunkr' in url:
            url_no_query = url.split('?')[0].split('#')[0].rstrip('/')
            last_segment = url_no_query.split('/')[-1]
            if '.' in last_segment:
                return last_segment.rsplit('.', 1)[0]
            return last_segment
            
        # saint2 / turbo.cr
        if 'turbo.cr' in url or 'saint' in url:
            match = re.search(r'/embed/([a-zA-Z0-9_-]+)', url)
            if match: return match.group(1)
            
        # generic fallback: extract the last path segment that is not an extension
        url_no_query = url.split('?')[0].split('#')[0].rstrip('/')
        last_segment = url_no_query.split('/')[-1]
        
        # Remove file extension if present
        if '.' in last_segment:
            last_segment = last_segment.rsplit('.', 1)[0]
            
        # If it has hyphens or underscores, the ID is usually the very last part 
        # (like Maplestar-SpyFamily-yLRzSZEQ -> yLRzSZEQ)
        parts = re.split(r'[-_]', last_segment)
        possible_id = parts[-1]
        
        if len(possible_id) >= 4 and re.match(r'^[a-zA-Z0-9]+$', possible_id):
            return possible_id
            
        return last_segment

    def _normalize_item(self, item):
        if isinstance(item, tuple) and len(item) == 5:
            url = item[2]
            key = item[4] if item[4] else self.extract_key_from_url(url)
            return {
                "post_title": item[0],
                "link_text": item[1],
                "url": url,
                "platform": item[3],
                "key": key,
                "thread_title": "",
                "post_id": "",
                "username": "",
                "date": ""
            }
        elif isinstance(item, dict):
            url = item.get("url", "")
            key = item.get("key", "")
            if not key:
                key = self.extract_key_from_url(url)
            return {
                "post_title": item.get("post_title", ""),
                "link_text": item.get("link_text", ""),
                "url": url,
                "platform": item.get("platform", ""),
                "key": key,
                "thread_title": item.get("thread_title", ""),
                "post_id": str(item.get("post_id", "")),
                "username": item.get("username", ""),
                "date": item.get("date", "")
            }
        return defaultdict(str)

    def _write_format(self, filepath, items, config):
        fmt = config['format']
        mode = 'a' if os.path.exists(filepath) else 'w'
        
        normalized_items = [self._normalize_item(i) for i in items]
        
        if fmt == 'json':
            data = []
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except: pass
            data.extend(normalized_items)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return

        with open(filepath, mode, encoding='utf-8', newline='') as f:
            if fmt == 'csv':
                writer = csv.DictWriter(f, fieldnames=["url", "platform", "post_title", "thread_title", "link_text", "key", "post_id", "username", "date"])
                if mode == 'w': writer.writeheader()
                for item in normalized_items:
                    writer.writerow({k: v for k, v in item.items() if k in writer.fieldnames})
                return

            is_md = (fmt == 'md')
            mode_txt = config['txt_mode']
            
            if mode_txt == 'simple':
                for item in normalized_items:
                    if is_md:
                        f.write(f"- [{item['link_text'] or item['url']}]({item['url']})\n")
                    else:
                        f.write(item['url'] + "\n")

            elif mode_txt == 'detailed':
                current_title = None
                for item in normalized_items:
                    title = item['thread_title'] or item['post_title']
                    if config['include_titles'] and title != current_title:
                        if current_title is not None: 
                            f.write("\n" + ("="*60 if not is_md else "---") + "\n\n")
                        if is_md:
                            f.write(f"### {title}\n")
                        else:
                            f.write(f"# Post/Thread: {title}\n")
                        current_title = title
                    
                    if is_md:
                        line = f"- **URL:** [{item['link_text'] or item['url']}]({item['url']})"
                        if config['include_platform'] and item['platform']: line += f" | **Platform:** {item['platform']}"
                        f.write(line + "\n")
                    else:
                        line_parts = [item['url']]
                        if config['include_platform'] and item['platform']: line_parts.append(f"Platform: {item['platform']}")
                        if config['include_link_text'] and item['link_text']: line_parts.append(f"Description: {item['link_text']}")
                        f.write(" | ".join(line_parts) + "\n")
            
            elif mode_txt == 'custom':
                template = config['custom_template']
                for item in normalized_items:
                    try:
                        formatted_line = template.format(
                            url=item.get('url', ''),
                            post_title=item.get('post_title', ''),
                            link_text=item.get('link_text', ''),
                            platform=item.get('platform', ''),
                            key=item.get('key', ''),
                            thread_title=item.get('thread_title', ''),
                            post_id=item.get('post_id', ''),
                            username=item.get('username', ''),
                            date=item.get('date', '')
                        )
                    except KeyError:
                        formatted_line = template
                    f.write(formatted_line)
                    if not formatted_line.endswith('\n'):
                        f.write('\n')