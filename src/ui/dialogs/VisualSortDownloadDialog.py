import os
import requests
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QProgressBar, 
                             QPushButton, QMessageBox, QRadioButton, QButtonGroup, 
                             QHBoxLayout, QGroupBox, QTabWidget, QWidget, QSlider, 
                             QSpinBox, QDialogButtonBox, QScrollArea, QCheckBox,
                             QLineEdit)
from PySide6.QtCore import Qt, QThread, Signal, QSettings

class UpdateCheckerThread(QThread):
    """Background thread to silently check if a new fallback.csv exists."""
    update_available_signal = Signal(bool, str)

    def __init__(self, url, current_etag):
        super().__init__()
        self.url = url
        self.current_etag = current_etag

    def run(self):
        try:
            response = requests.head(self.url, timeout=10, allow_redirects=True)
            remote_etag = response.headers.get('ETag', '').strip('"')
            
            if not remote_etag:
                remote_etag = response.headers.get('Last-Modified', '')

            if remote_etag and remote_etag != self.current_etag:
                self.update_available_signal.emit(True, remote_etag)
            else:
                self.update_available_signal.emit(False, remote_etag)
        except Exception:
            self.update_available_signal.emit(False, self.current_etag)


class DownloadWorker(QThread):
    status_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str, bool)

    def __init__(self, files, models_dir, model_path, csv_path, is_full_download=True):
        super().__init__()
        self.files = files
        self.models_dir = models_dir
        self.model_path = model_path
        self.csv_path = csv_path
        self.is_full_download = is_full_download

    def run(self):
        try:
            os.makedirs(self.models_dir, exist_ok=True)
            
            for url, path, label in self.files:
                self.status_signal.emit(label)
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                total = int(response.headers.get('content-length', 0))
                
                downloaded = 0
                with open(path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.isInterruptionRequested():
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                self.progress_signal.emit(int(downloaded / total * 100))
            
            if self.is_full_download or (self.files and "fallback" in self.files[0][0]):
                self.status_signal.emit("Refreshing AI engine tags in memory...")
                if os.path.exists(self.model_path) and os.path.exists(self.csv_path):
                    try:
                        from src.core.visual_sorter import VisualSorter
                    except ImportError:
                        from ...core.visual_sorter import VisualSorter
                    
                    VisualSorter._instance = None
                    VisualSorter.get_instance(self.model_path, self.csv_path)
            
            self.finished_signal.emit(True, "Success", self.is_full_download)
        except Exception as e:
            self.finished_signal.emit(False, str(e), self.is_full_download)


class BestSettingsInfoDialog(QDialog):
    """Custom dialog for 'Best Settings' that includes a functional download button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pro Tips for Best Results")
        self.setMinimumWidth(550)
        self.parent_ref = parent 
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        info_text = QLabel(
            "<h3 style='color: #4CAF50;'>🚀 The 'Golden Rule' for Accuracy</h3>"
            "<p>For the best results, always use <b>Visual Sort</b> in combination with <b>'Separate folder by known.txt'</b>.</p>"
            "<hr>"
            "<h4 style='color: #81C784;'>1. Expand your Known.txt</h4>"
            "<p>The AI works much faster and more accurately when it has a list of names to look for first. "
            "Add your favorite characters to <b>Known.txt</b> (one per line or as alias groups).</p>"
            "<h4 style='color: #81C784;'>2. Use the Developer's Master List</h4>"
            "<p>Instead of building a list manually, you can download the <b>Master Known List</b> below. "
            "It contains thousands of pre-configured character names and aliases.</p>"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #EEEEEE; font-size: 13px;")
        layout.addWidget(info_text)

        self.dl_btn = QPushButton("📥 Download & Install Master Known.txt")
        self.dl_btn.setMinimumHeight(40)
        self.dl_btn.setStyleSheet("""
            QPushButton {
                background-color: #2E5A88; 
                color: white; 
                font-weight: bold; 
                font-size: 13px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #3a71a9; }
        """)
        self.dl_btn.clicked.connect(self.trigger_download)
        layout.addWidget(self.dl_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setStyleSheet("background-color: #2D2D2D;")

    def trigger_download(self):
        self.accept() 
        if self.parent_ref:
            self.parent_ref.start_known_txt_download() 


class VisualSortSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Visual Sort Setup")
        self.setObjectName("VisualSortSetupDialog") 
        
        self.setMinimumSize(520, 600)
        self.resize(550, 650) 
        self.setWindowModality(Qt.WindowModality.WindowModal)
        
        self.settings = QSettings("MediaDownloader", "VisualSort")

        self.models_dir = os.path.abspath(os.path.join("appdata", "models"))
        self.model_path = os.path.join(self.models_dir, "model.onnx")
        self.csv_path = os.path.join(self.models_dir, "selected_tags.csv")
        self.fallback_path = os.path.join(self.models_dir, "fallback.csv")
        
        self.fallback_url = "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/models/fallback.csv"
                            
        self.worker = None
        self.checker = None
        self.latest_fallback_etag = self.settings.value("fallback_etag", "", type=str)

        self.known_txt_url = "https://huggingface.co/datasets/Yuvi9587/Database/resolve/main/Known.txt"
        self.known_checker = None
        self.latest_known_etag = self.settings.value("known_etag", "", type=str)

        self.model_urls = {
            0: {
                "model": "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main/model.onnx",
                "csv": "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main/selected_tags.csv"
            },
            1: {
                "model": "https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/resolve/main/model.onnx",
                "csv": "https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/resolve/main/selected_tags.csv"
            },
            2: {
                "model": "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/model.onnx",
                "csv": "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/selected_tags.csv"
            }
        }

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        self.tabs = QTabWidget()
        self.tabs.setObjectName("SetupTabs") 
        main_layout.addWidget(self.tabs)
        
        self.setup_download_tab()
        self.setup_settings_tab()
        self.setup_known_tab()
        
        bottom_layout = QHBoxLayout()
        
        self.help_btn = QPushButton("❓ How does this work?")
        self.help_btn.setToolTip("Click for a detailed explanation of Visual Sort and its settings.")
        self.help_btn.clicked.connect(self.show_help_dialog)
        self.help_btn.setMinimumHeight(30)
        
        self.best_settings_btn = QPushButton("ⓘ Best Settings")
        self.best_settings_btn.setToolTip("Click to see the recommended setup for maximum accuracy.")
        self.best_settings_btn.clicked.connect(self.show_best_settings_dialog)
        self.best_settings_btn.setMinimumHeight(30)
        self.best_settings_btn.setStyleSheet("color: #4CAF50; font-weight: bold;")
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        self.button_box.accepted.connect(self.apply_and_close)
        self.button_box.rejected.connect(self.close)
        
        bottom_layout.addWidget(self.help_btn)
        bottom_layout.addWidget(self.best_settings_btn)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.button_box)
        
        main_layout.addLayout(bottom_layout)

        self.set_custom_styles()
        self.check_for_fallback_updates()
        self.check_for_known_updates()

    def show_help_dialog(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("How Visual Sort Works")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setObjectName("HelpDialog") 
        
        help_text = """
        <h3 style='color: #4CAF50;'>What is Visual Sort?</h3>
        <p>Visual Sort uses an AI model to scan your downloaded images and automatically organize them into folders named after the characters detected in the image.</p>
        <hr>
        <h3 style='color: #4CAF50;'>How the Settings Work:</h3>
        
        <p><b>1. Primary Character Detection Threshold</b><br>
        The AI looks at the image and guesses the character's name directly. If its confidence score is <i>higher</i> than this percentage, it immediately sorts the image into that character's folder.<br>
        <span style='color: #888;'><i>(Recommended: 50%)</i></span></p>

        <p><b>2. Fallback: Required Tag Matches</b><br>
        If the AI isn't confident enough about the character's face, the <b>Fallback System</b> activates. Instead of looking for a name, it looks for general traits (e.g., "blue hair", "glasses", "school uniform"). This setting decides <i>how many</i> of these general traits must match the character's profile in the database to successfully sort the image.<br>
        <span style='color: #888;'><i>(Recommended: 3 or 4 tags)</i></span></p>

        <p><b>3. Fallback: Tag Confidence Threshold</b><br>
        How sure the AI needs to be that it actually sees a specific generic trait (like "glasses") for it to count as a match. Generic traits usually score lower than full characters, so this bar should be set lower.<br>
        <span style='color: #888;'><i>(Recommended: 20% - 30%)</i></span></p>
        
        <hr>
        <p style='color: #E57373;'><i>Note: If an image fails both the Primary and Fallback checks, it is safely placed into the "Unknown" folder to prevent incorrect sorting.</i></p>
        """
        msg.setText(help_text)
        
        msg.setStyleSheet("""
            QMessageBox { background-color: #2D2D2D; }
            QLabel { color: #EEEEEE; font-size: 13px; min-width: 550px; }
            QPushButton { background-color: #3D3D3D; color: #EEEEEE; padding: 6px 15px; border-radius: 4px; border: 1px solid #555; }
            QPushButton:hover { background-color: #4D4D4D; }
        """)
        msg.exec()

    def show_best_settings_dialog(self):
        dialog = BestSettingsInfoDialog(self)
        dialog.exec()

    def start_known_txt_download(self):
        known_txt_url = self.known_txt_url 

        parent_app = self.parent()
        target_path = parent_app.config_file if (parent_app and hasattr(parent_app, 'config_file')) else os.path.abspath(os.path.join("appdata", "Known.txt"))
        target_dir = os.path.dirname(target_path)
        
        if os.path.exists(target_path):
            reply = QMessageBox.question(self, "Overwrite Known.txt?", 
                                         "A Known.txt file already exists in your app folder. Do you want to replace it with the developer's master list?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        self.tabs.setCurrentIndex(0) 
        self.group_box.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.update_fallback_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting Known.txt download...")
        
        files_to_download = [(known_txt_url, target_path, "Downloading Master Known List...")]
        
        self.worker = DownloadWorker(files_to_download, target_dir, self.model_path, self.csv_path, is_full_download=False)
        self.worker.status_signal.connect(self.status_label.setText)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        
        self.worker.finished_signal.connect(self._on_known_txt_finished)
        self.worker.start()

    def _on_known_txt_finished(self, success, error_msg, is_full_download):
        self.group_box.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.update_fallback_btn.setEnabled(True)
        self.progress_bar.hide()
        
        if success:
            self.settings.setValue("known_etag", self.latest_known_etag)
            self.known_status_label.setText("Status: Up to date ✅")
            self.known_status_label.setStyleSheet("color: #888;")
            self.update_master_btn.setText("📥 Download / Update Master List")
            self.update_master_btn.setStyleSheet("")
            
            self.status_label.setText("Known.txt updated successfully.")

            parent_app = self.parent()
            if parent_app and hasattr(parent_app, 'load_known_names_from_util'):
                parent_app.load_known_names_from_util()
            
            QMessageBox.information(self, "Success", "Master Known.txt has been downloaded and installed to your app folder!")

    def update_installed_status(self):
        text_basic = "Basic - Fast (~379MB)"
        text_balanced = "Balanced - Recommended (~440MB)"
        text_advanced = "Advanced - Best Accuracy (~1.26GB)"
        
        self.rb_basic.setText(text_basic)
        self.rb_balanced.setText(text_balanced)
        self.rb_advanced.setText(text_advanced)
        
        if os.path.exists(self.model_path) and os.path.exists(self.csv_path):
            installed_id = self.settings.value("installed_model", -1, type=int)
            if installed_id == 0:
                self.rb_basic.setText(text_basic + "  ✅ (Installed)")
            elif installed_id == 1:
                self.rb_balanced.setText(text_balanced + "  ✅ (Installed)")
            elif installed_id == 2:
                self.rb_advanced.setText(text_advanced + "  ✅ (Installed)")

    def setup_download_tab(self):
        tab = QWidget()
        tab.setObjectName("DownloadTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        explanation = QLabel("Visual Sort requires an AI model to classify characters.\nPlease select the model you wish to install:")
        explanation.setWordWrap(True)
        explanation.setStyleSheet("font-size: 13px; margin-bottom: 5px;")
        layout.addWidget(explanation)

        self.group_box = QGroupBox("Model Selection")
        group_layout = QVBoxLayout()
        group_layout.setSpacing(15)
        group_layout.setContentsMargins(15, 20, 15, 15)

        self.radio_group = QButtonGroup(self)
        
        self.rb_basic = QRadioButton()
        self.rb_basic.setToolTip("Recommended for quick sorting.\nDownloads faster and uses less system memory.")
        self.rb_balanced = QRadioButton()
        self.rb_balanced.setToolTip("A great middle-ground.\nOffers better accuracy for character recognition.")
        self.rb_advanced = QRadioButton()
        self.rb_advanced.setToolTip("The largest model.\nSlowest to download and process, but yields the highest recognition quality.")
        
        self.radio_group.addButton(self.rb_basic, 0)
        self.radio_group.addButton(self.rb_balanced, 1)
        self.radio_group.addButton(self.rb_advanced, 2)
        
        installed_id = self.settings.value("installed_model", 1, type=int)
        if os.path.exists(self.model_path):
            button = self.radio_group.button(installed_id)
            if button:
                button.setChecked(True)
        else:
            self.rb_balanced.setChecked(True)
            
        self.update_installed_status()
        
        group_layout.addWidget(self.rb_basic)
        group_layout.addWidget(self.rb_balanced)
        group_layout.addWidget(self.rb_advanced)
        self.group_box.setLayout(group_layout)
        layout.addWidget(self.group_box)

        self.fb_group = QGroupBox("Fallback Tags Database")
        fb_layout = QHBoxLayout()
        fb_layout.setContentsMargins(15, 15, 15, 15)

        self.fallback_status_label = QLabel("Checking for updates...")
        self.fallback_status_label.setStyleSheet("color: gray; font-style: italic;")
        fb_layout.addWidget(self.fallback_status_label)
        
        fb_layout.addStretch()

        self.update_fallback_btn = QPushButton("Update Tags Only")
        self.update_fallback_btn.setMinimumHeight(30)
        self.update_fallback_btn.setEnabled(False) 
        self.update_fallback_btn.clicked.connect(self.start_fallback_update)
        fb_layout.addWidget(self.update_fallback_btn)

        self.fb_group.setLayout(fb_layout)
        layout.addWidget(self.fb_group)

        self.status_label = QLabel("Ready to download.")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()

        self.download_btn = QPushButton("Download Selected Model")
        self.download_btn.setMinimumHeight(35) 
        self.download_btn.clicked.connect(self.start_download)
        layout.addWidget(self.download_btn)

        self.tabs.addTab(tab, "Download")

    def setup_settings_tab(self):
        tab = QWidget()
        tab.setObjectName("SettingsTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        settings_group = QGroupBox("Sorting Configuration")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(12)
        settings_layout.setContentsMargins(15, 20, 15, 15)

        threshold_label = QLabel("Primary Character Detection Threshold (%)")
        threshold_label.setStyleSheet("font-weight: bold;")
        settings_layout.addWidget(threshold_label)

        slider_layout = QHBoxLayout()
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(1, 100)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 100)
        self.threshold_spin.setSuffix("%")
        self.threshold_spin.setMinimumWidth(70)

        saved_threshold = self.settings.value("char_threshold", 50, type=int)
        self.threshold_slider.setValue(saved_threshold)
        self.threshold_spin.setValue(saved_threshold)

        self.threshold_slider.valueChanged.connect(self.threshold_spin.setValue)
        self.threshold_spin.valueChanged.connect(self.threshold_slider.setValue)

        slider_layout.addWidget(self.threshold_slider)
        slider_layout.addWidget(self.threshold_spin)
        settings_layout.addLayout(slider_layout)

        desc_label = QLabel("Minimum confidence required to sort based on the Character's name directly.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #888; font-style: italic; margin-bottom: 5px;")
        settings_layout.addWidget(desc_label)

        fallback_label = QLabel("Fallback: Required Tag Matches (1-5)")
        fallback_label.setStyleSheet("font-weight: bold;")
        settings_layout.addWidget(fallback_label)

        fallback_slider_layout = QHBoxLayout()
        self.fallback_slider = QSlider(Qt.Orientation.Horizontal)
        self.fallback_slider.setRange(1, 5)
        self.fallback_slider.setTickPosition(QSlider.TicksBelow)
        self.fallback_slider.setTickInterval(1)
        self.fallback_spin = QSpinBox()
        self.fallback_spin.setRange(1, 5)
        self.fallback_spin.setSuffix(" tags")
        self.fallback_spin.setMinimumWidth(70)

        saved_fallback_matches = self.settings.value("fallback_tag_matches", 3, type=int)
        self.fallback_slider.setValue(saved_fallback_matches)
        self.fallback_spin.setValue(saved_fallback_matches)

        self.fallback_slider.valueChanged.connect(self.fallback_spin.setValue)
        self.fallback_spin.valueChanged.connect(self.fallback_slider.setValue)

        fallback_slider_layout.addWidget(self.fallback_slider)
        fallback_slider_layout.addWidget(self.fallback_spin)
        settings_layout.addLayout(fallback_slider_layout)

        fb_desc_label = QLabel("How many visual tags from fallback.csv must match the image.")
        fb_desc_label.setWordWrap(True)
        fb_desc_label.setStyleSheet("color: #888; font-style: italic; margin-bottom: 5px;")
        settings_layout.addWidget(fb_desc_label)

        fb_thresh_label = QLabel("Fallback: Tag Confidence Threshold (%)")
        fb_thresh_label.setStyleSheet("font-weight: bold;")
        settings_layout.addWidget(fb_thresh_label)

        fb_thresh_layout = QHBoxLayout()
        self.fb_thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.fb_thresh_slider.setRange(1, 100)
        self.fb_thresh_spin = QSpinBox()
        self.fb_thresh_spin.setRange(1, 100)
        self.fb_thresh_spin.setSuffix("%")
        self.fb_thresh_spin.setMinimumWidth(70)

        saved_fb_thresh = self.settings.value("fallback_threshold", 30, type=int)
        self.fb_thresh_slider.setValue(saved_fb_thresh)
        self.fb_thresh_spin.setValue(saved_fb_thresh)

        self.fb_thresh_slider.valueChanged.connect(self.fb_thresh_spin.setValue)
        self.fb_thresh_spin.valueChanged.connect(self.fb_thresh_slider.setValue)

        fb_thresh_layout.addWidget(self.fb_thresh_slider)
        fb_thresh_layout.addWidget(self.fb_thresh_spin)
        settings_layout.addLayout(fb_thresh_layout)

        fb_thresh_desc = QLabel("How confident the AI needs to be for a single visual tag to count. General tags score lower than characters (Recommended: 20% - 35%).")
        fb_thresh_desc.setWordWrap(True)
        fb_thresh_desc.setStyleSheet("color: #888; font-style: italic;")
        settings_layout.addWidget(fb_thresh_desc)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        layout.addStretch()

        self.tabs.addTab(tab, "Settings")

    def check_for_fallback_updates(self):
        local_etag = self.latest_fallback_etag if os.path.exists(self.fallback_path) else ""
        self.checker = UpdateCheckerThread(self.fallback_url, local_etag)
        self.checker.update_available_signal.connect(self.on_update_check_result)
        self.checker.start()

    def on_update_check_result(self, has_update, new_etag):
        self.latest_fallback_etag = new_etag
        if has_update:
            self.fallback_status_label.setText("Status: Update Available 🟢")
            self.fallback_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.update_fallback_btn.setEnabled(True)
        else:
            self.fallback_status_label.setText("Status: Up to date ✅")
            self.fallback_status_label.setStyleSheet("color: #888;")
            self.update_fallback_btn.setEnabled(False)

    def apply_and_close(self):
        self.settings.setValue("char_threshold", self.threshold_spin.value())
        self.settings.setValue("fallback_tag_matches", self.fallback_spin.value())
        self.settings.setValue("fallback_threshold", self.fb_thresh_spin.value())
        parent_app = self.parent()
        if parent_app:
            parent_app.active_known_categories = self.get_selected_categories()
            if hasattr(parent_app, 'load_known_names_from_util'):
                parent_app.load_known_names_from_util()
        self.accept()

    def start_fallback_update(self):
        self.group_box.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.update_fallback_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        
        files_to_download = [
            (self.fallback_url, self.fallback_path, "Updating Fallback Tags...")
        ]
        
        self.worker = DownloadWorker(files_to_download, self.models_dir, self.model_path, self.csv_path, is_full_download=False)
        self.worker.status_signal.connect(self.status_label.setText)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        
        try: self.worker.finished_signal.disconnect() 
        except TypeError: pass
        self.worker.finished_signal.connect(self._on_download_finished)
        self.worker.start()

    def start_download(self):
        selected_id = self.radio_group.checkedId()
        installed_id = self.settings.value("installed_model", -1, type=int)

        if selected_id == installed_id and os.path.exists(self.model_path):
            reply = QMessageBox.question(self, "Model Already Installed", 
                                         "This model is already installed and active. Do you want to re-download and replace it?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        self.group_box.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.update_fallback_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        
        try:
            if os.path.exists(self.model_path): os.remove(self.model_path)
            if os.path.exists(self.csv_path): os.remove(self.csv_path)
            if os.path.exists(self.fallback_path): os.remove(self.fallback_path)
        except OSError as e:
            print(f"Warning: Could not delete old model files. Error: {e}")

        urls = self.model_urls[selected_id]
        
        files_to_download = [
            (urls["model"], self.model_path, "Downloading AI model..."),
            (urls["csv"], self.csv_path, "Downloading tag database..."),
            (self.fallback_url, self.fallback_path, "Downloading fallback tags...")
        ]
        
        self.worker = DownloadWorker(files_to_download, self.models_dir, self.model_path, self.csv_path, is_full_download=True)
        self.worker.status_signal.connect(self.status_label.setText)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        
        try: self.worker.finished_signal.disconnect() 
        except TypeError: pass
        self.worker.finished_signal.connect(self._on_download_finished)
        self.worker.start()

    def _on_download_finished(self, success, error_msg, is_full_download):
        self.group_box.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.progress_bar.hide()
        
        if success:
            self.settings.setValue("fallback_etag", self.latest_fallback_etag)
            self.fallback_status_label.setText("Status: Up to date ✅")
            self.fallback_status_label.setStyleSheet("color: #888;")
            
            if is_full_download:
                selected_id = self.radio_group.checkedId()
                self.settings.setValue("installed_model", selected_id)
                self.update_installed_status()
                self.status_label.setText("Model installed successfully.")
                QMessageBox.information(self, "Download Complete", "The AI model has been swapped and is ready to use.")
            else:
                self.status_label.setText("Fallback tags updated.")
                QMessageBox.information(self, "Update Complete", "The custom Fallback Tags database has been successfully updated.")
        else:
            QMessageBox.critical(self, "Download Error", f"Failed to setup Visual Sort:\n{error_msg}")
            self.progress_bar.setValue(0)
            self.status_label.setText("Download failed. Try again.")
            
            if not is_full_download:
                self.update_fallback_btn.setEnabled(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        super().closeEvent(event)

    def setup_known_tab(self):
        tab = QWidget()
        tab.setObjectName("KnownTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        master_group = QGroupBox("Master Known.txt Database")
        master_layout = QVBoxLayout(master_group)
        master_layout.setSpacing(10)

        master_desc = QLabel("Your core master list of character names and aliases.")
        master_desc.setWordWrap(True)
        master_desc.setStyleSheet("color: #888; font-style: italic;")
        master_layout.addWidget(master_desc)

        self.known_status_label = QLabel("Checking for updates...")
        self.known_status_label.setStyleSheet("color: gray; font-style: italic;")
        master_layout.addWidget(self.known_status_label)

        self.update_master_btn = QPushButton("📥 Download / Update Master List")
        self.update_master_btn.setMinimumHeight(35)
        self.update_master_btn.clicked.connect(self.start_known_txt_download)
        master_layout.addWidget(self.update_master_btn)

        layout.addWidget(master_group)

        series_group = QGroupBox("Series Expansion Packs")
        series_layout = QVBoxLayout(series_group)
        series_layout.setSpacing(10)

        series_desc = QLabel("Select which series to load. Unchecked series will be ignored.")
        series_desc.setWordWrap(True)
        series_desc.setStyleSheet("color: #888; font-style: italic;")
        series_layout.addWidget(series_desc)

        self.series_search_input = QLineEdit()
        self.series_search_input.setPlaceholderText("🔍 Search expansions...")
        self.series_search_input.setStyleSheet("QLineEdit { padding: 6px; border-radius: 4px; }")
        self.series_search_input.textChanged.connect(self.filter_series_checkboxes)
        series_layout.addWidget(self.series_search_input)

        scroll = QScrollArea()
       
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #444; background-color: #2D2D2D; border-radius: 4px; }")
        
        scroll_widget = QWidget()
        self.series_checkbox_layout = QVBoxLayout(scroll_widget)
        self.series_checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.series_checkboxes = []
        self.populate_series_checkboxes()

        scroll.setWidget(scroll_widget)
        series_layout.addWidget(scroll)
        layout.addWidget(series_group)
        layout.addStretch()

        self.tabs.addTab(tab, "Known.txt Settings")

    def populate_series_checkboxes(self):
        parent_app = self.parent()
        known_path = parent_app.config_file if (parent_app and hasattr(parent_app, 'config_file')) else os.path.abspath(os.path.join("appdata", "Known.txt"))
            
        categories = []
        
        if os.path.exists(known_path):
            with open(known_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("# ---") and line.endswith("---"):
                        cat_name = line.replace("# ---", "").replace("---", "").strip()
                        if cat_name and cat_name not in categories:
                            categories.append(cat_name)

        if not categories:
            no_files_label = QLabel("No '# --- Series Name ---' headers found in Known.txt.")
            no_files_label.setStyleSheet("color: #888888; font-style: italic;")
            self.series_checkbox_layout.addWidget(no_files_label)
            return

        active_cats = getattr(parent_app, 'active_known_categories', [])
        if active_cats is None:
            active_cats = []

        for cat in categories:
            cb = QCheckBox(cat)
            cb.setStyleSheet("QCheckBox { padding: 2px; }")
            
            cb.setChecked(cat in active_cats)
            
            self.series_checkbox_layout.addWidget(cb)
            self.series_checkboxes.append(cb)

    def get_selected_categories(self):
        return [cb.text() for cb in self.series_checkboxes if cb.isChecked()]

    def filter_series_checkboxes(self, text):
        """Hides checkboxes that don't match the search text."""
        search_query = text.lower()
        
        for cb in self.series_checkboxes:
            if not search_query or search_query in cb.text().lower():
                cb.setVisible(True)
            else:
                cb.setVisible(False)

    def check_for_known_updates(self):
        parent_app = self.parent()
        known_path = parent_app.config_file if (parent_app and hasattr(parent_app, 'config_file')) else os.path.abspath(os.path.join("appdata", "Known.txt"))
        
        local_etag = self.latest_known_etag if os.path.exists(known_path) else ""
        self.known_checker = UpdateCheckerThread(self.known_txt_url, local_etag)
        self.known_checker.update_available_signal.connect(self.on_known_update_check_result)
        self.known_checker.start()

    def on_known_update_check_result(self, has_update, new_etag):
        self.latest_known_etag = new_etag
        if has_update:
            self.known_status_label.setText("Status: Update Available 🟢")
            self.known_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.update_master_btn.setText("📥 Update Available - Download Master List")
            self.update_master_btn.setStyleSheet("QPushButton { background-color: #2E5A88; color: white; border: 1px solid #1c3d5a; } QPushButton:hover { background-color: #3a71a9; }")
        else:
            self.known_status_label.setText("Status: Up to date ✅")
            self.known_status_label.setStyleSheet("color: #888;")
            self.update_master_btn.setText("📥 Download / Update Master List")
            self.update_master_btn.setStyleSheet("")

    def set_custom_styles(self):
        qss = """
                background-color: #2D2D2D;
            }
            QTabWidget::pane {
                border-top: 1px solid #444;
                margin-top: -1px; 
                background-color: #2D2D2D;
            }
            QTabBar::tab {
                background-color: #3D3D3D;
                color: #BBBBBB;
                border: 1px solid #444;
                border-bottom: none; 
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2D2D2D; 
                color: #EEEEEE;
                border-bottom: 1px solid #2D2D2D; 
                margin-bottom: -1px; 
            }
            QTabBar::tab:!selected:hover {
                background-color: #4A4A4A;
            }
            QLabel, QRadioButton, QCheckBox, QGroupBox {
                color: #EEEEEE;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
            QPushButton {
                background-color: #3D3D3D;
                color: #EEEEEE;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #4D4D4D;
            }
            QPushButton:disabled {
                background-color: #2A2A2A;
                color: #666;
                border: 1px solid #333;
            }
        """
        self.setStyleSheet(qss)