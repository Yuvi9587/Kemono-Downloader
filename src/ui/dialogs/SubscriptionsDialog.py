import json
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, 
    QLabel, QLineEdit, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Qt
from ..assets import get_asset_path

class SubscriptionsDialog(QDialog):
    def __init__(self, parent=None, app_base_dir=""):
        super().__init__(parent)
        self.setWindowTitle("Local Subscriptions Manager (Auto-Sync)")
        self.setMinimumSize(500, 400)
        self.app_base_dir = app_base_dir
        self.subscriptions_file = os.path.join(self.app_base_dir, "appdata", "subscriptions.json")
        self.subscriptions = self.load_subscriptions()
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        icon_label = QLabel(f"<img src='{get_asset_path('assets/Svg/star.svg')}' width='20' height='20'>")
        title_label = QLabel("<b>Set and Forget: Auto-Sync Subscriptions</b>")
        header_layout.addWidget(icon_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        desc_label = QLabel("Add creator URLs here. The Auto-Sync daemon will quietly download new posts in the background.\nSupported sites: Kemono, Coomer, Pawchive, Rule34.xxx")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Input Area
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste creator URL here (e.g. https://kemono.su/patreon/user/1234)")
        self.add_btn = QPushButton("Subscribe")
        self.add_btn.clicked.connect(self.add_subscription)
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.add_btn)
        layout.addLayout(input_layout)

        # List Area
        self.sub_list = QListWidget()
        layout.addWidget(self.sub_list)
        
        # Remove button
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_subscription)
        layout.addWidget(self.remove_btn)
        
        self.refresh_list()

    def load_subscriptions(self):
        if os.path.exists(self.subscriptions_file):
            try:
                with open(self.subscriptions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_subscriptions(self):
        os.makedirs(os.path.dirname(self.subscriptions_file), exist_ok=True)
        with open(self.subscriptions_file, "w", encoding="utf-8") as f:
            json.dump(self.subscriptions, f, indent=4)

    def add_subscription(self):
        url = self.url_input.text().strip()
        if not url:
            return
        
        # Validation for supported sites
        supported = ["kemono.", "coomer.", "pawchive.", "rule34.xxx"]
        if not any(s in url.lower() for s in supported):
            QMessageBox.warning(self, "Unsupported URL", "This URL does not appear to be from a supported auto-sync site (Kemono, Coomer, Pawchive, Rule34).")
            return
            
        if url in self.subscriptions:
            QMessageBox.information(self, "Already Subscribed", "You are already subscribed to this URL.")
            return
            
        self.subscriptions.append(url)
        self.save_subscriptions()
        self.url_input.clear()
        self.refresh_list()

    def remove_subscription(self):
        selected = self.sub_list.selectedItems()
        if not selected:
            return
            
        for item in selected:
            url = item.text()
            if url in self.subscriptions:
                self.subscriptions.remove(url)
                
        self.save_subscriptions()
        self.refresh_list()

    def refresh_list(self):
        self.sub_list.clear()
        for url in self.subscriptions:
            self.sub_list.addItem(url)
