
import sys
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices

from ...utils.resolution import get_dark_theme
from ..assets import get_asset_path

class SupportDialog(QDialog):
    """
    A polished dialog showcasing support and community options in a
    clean, modern card-based layout.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent

        self.setWindowTitle("❤️ Support & Community")
        self.setMinimumWidth(560)

        self._init_ui()
        self._apply_theme()

    def _create_card_button(
        self, icon_path, title, subtitle, url,
        hover_color="#2E2E2E", min_height=110, icon_size=44
    ):
        """Reusable clickable card widget with icon, title, and subtitle."""
        button = QPushButton()
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setMinimumHeight(min_height)

        button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3A3A3A;
                border: 1px solid #555;
                border-radius: 10px;
                text-align: center;
                padding: 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border: 1px solid #777;
            }}
        """)

        layout = QVBoxLayout(button)
        layout.setSpacing(6)

        icon_label = QLabel()
        pixmap = QPixmap(icon_path)
        if not pixmap.isNull():
            scale = getattr(self.parent_app, 'scale_factor', 1.0)
            scaled_size = int(icon_size * scale)
            icon_label.setPixmap(
                pixmap.scaled(QSize(scaled_size, scaled_size), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        font = self.font()
        font.setPointSize(11)
        font.setBold(True)
        title_label.setFont(font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("background-color: transparent; border: none;")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet("color: #A8A8A8; background-color: transparent; border: none;")
            subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(subtitle_label)

        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return button

    def _create_section_title(self, text):
        """Stylized section heading."""
        label = QLabel(text)
        font = label.font()
        font.setPointSize(13)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("margin-top: 10px; margin-bottom: 5px;")
        return label

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(18)
        main_layout.setContentsMargins(20, 20, 20, 20)

        header_label = QLabel("Support the Project")
        font = header_label.font()
        font.setPointSize(17)
        font.setBold(True)
        header_label.setFont(font)
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)

        subtext = QLabel(
            "If you enjoy this application, consider supporting its development. "
            "Your help keeps the project alive and growing!"
        )
        subtext.setWordWrap(True)
        subtext.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(subtext)

        main_layout.addWidget(self._create_section_title("Contribute Financially"))
        donation_layout = QHBoxLayout()
        donation_layout.setSpacing(15)

        donation_layout.addWidget(self._create_card_button(
            get_asset_path("ko-fi.png"), "Ko-fi", "One-time ",
            "https://ko-fi.com/yuvi427183", "#2B2F36"
        ))
        donation_layout.addWidget(self._create_card_button(
            get_asset_path("patreon.png"), "Patreon", "Soon ",
            "https://www.patreon.com/Yuvi102", "#3A2E2B"
        ))
        donation_layout.addWidget(self._create_card_button(
            get_asset_path("buymeacoffee.png"), "Buy Me a Coffee", "One-time",
            "https://buymeacoffee.com/yuvi9587", "#403520"
        ))
        main_layout.addLayout(donation_layout)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        main_layout.addWidget(self._create_section_title("Get Help & Connect"))
        community_layout = QHBoxLayout()
        community_layout.setSpacing(15)

        community_layout.addWidget(self._create_card_button(
            get_asset_path("github.png"), "GitHub", "Report issues",
            "https://github.com/Yuvi9587/Kemono-Downloader", "#2E2E2E",
            min_height=100, icon_size=36
        ))
        community_layout.addWidget(self._create_card_button(
            get_asset_path("discord.png"), "Discord", "Join the server",
            "https://discord.gg/BqP64XTdJN", "#2C2F33",
            min_height=100, icon_size=36
        ))
        community_layout.addWidget(self._create_card_button(
            get_asset_path("instagram.png"), "Instagram", "Follow me",
            "https://www.instagram.com/uvi.arts/", "#3B2E40",
            min_height=100, icon_size=36
        ))
        main_layout.addLayout(community_layout)

        close_button = QPushButton("Close")
        close_button.setMinimumWidth(100)
        close_button.clicked.connect(self.accept)
        close_button.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                border-radius: 6px;
                background-color: #444;
                color: white;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)

    def _apply_theme(self):
        if self.parent_app and hasattr(self.parent_app, 'current_theme') and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")

