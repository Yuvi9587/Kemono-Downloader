import os
import sys
from PySide6.QtCore import Signal, Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QStackedWidget, QScrollArea, QFrame, QWidget, QCheckBox
)
from ...i18n.translator import get_translation
from ..assets import get_app_icon_object  # canonical location, avoids circular import via main_window
from ...utils.resolution import get_dark_theme
from ...config.constants import CONFIG_ORGANIZATION_NAME



class TourStepWidget(QWidget):
    """
    A custom widget for a single tour page, with improved styling for titles and content.
    """
    def __init__(self, title_text, content_text, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(15)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        title_label = QLabel(title_text)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #E0E0E0; padding-bottom: 10px;")
        layout.addWidget(title_label)

        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        content_layout = QVBoxLayout(content_frame)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        content_label = QLabel(content_text)
        content_label.setWordWrap(True)
        content_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setOpenExternalLinks(True)
        content_label.setStyleSheet("font-size: 11pt; color: #C8C8C8; padding-left: 5px; padding-right: 5px;")
        
        scroll_area.setWidget(content_label)
        content_layout.addWidget(scroll_area)
        layout.addWidget(content_frame, 1)


class TourDialog(QDialog):
    """
    A redesigned, multi-page tour dialog with a visual progress indicator.
    """
    tour_finished_normally = Signal()
    tour_skipped = Signal()
    CONFIG_APP_NAME_TOUR = "ApplicationTour"
    TOUR_SHOWN_KEY = "neverShowTourAgainV20"
    CONFIG_ORGANIZATION_NAME = CONFIG_ORGANIZATION_NAME

    def __init__(self, parent_app, parent=None):
        super().__init__(parent)
        self.settings = QSettings(self.CONFIG_ORGANIZATION_NAME, self.CONFIG_APP_NAME_TOUR)
        self.current_step = 0
        self.parent_app = parent_app
        self.progress_dots = []

        self.setWindowIcon(get_app_icon_object())
        self.setModal(True)
        self.setFixedSize(680, 650)
        
        self._init_ui()
        self._apply_theme()
        self._center_on_screen()

    def _tr(self, key, default_text=""):
        if callable(get_translation) and self.parent_app:
            return get_translation(self.parent_app.current_selected_language, key, default_text)
        return default_text

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget, 1)

        steps_content = [
            ("tour_dialog_step1_title", "tour_dialog_step1_content"),
            ("tour_dialog_step2_title", "tour_dialog_step2_content"),
            ("tour_dialog_step3_title", "tour_dialog_step3_content"),
            ("tour_dialog_step4_title", "tour_dialog_step4_content"),
            ("tour_dialog_step5_title", "tour_dialog_step5_content"),
            ("tour_dialog_step6_title", "tour_dialog_step6_content"),
            ("tour_dialog_step7_title", "tour_dialog_step7_content"),
            ("tour_dialog_step8_title", "tour_dialog_step8_content"),
        ]

        for title_key, content_key in steps_content:
            title = self._tr(title_key, title_key)
            content = self._tr(content_key, "Content not found.")
            step_widget = TourStepWidget(title, content)
            self.stacked_widget.addWidget(step_widget)

        self.setWindowTitle(self._tr("tour_dialog_title", "Welcome to Kemono Downloader!"))
        
        bottom_frame = QFrame()
        bottom_frame.setObjectName("bottomFrame")
        main_layout.addWidget(bottom_frame)

        bottom_controls_layout = QVBoxLayout(bottom_frame)
        bottom_controls_layout.setContentsMargins(20, 15, 20, 20)
        bottom_controls_layout.setSpacing(15)

        progress_layout = QHBoxLayout()
        progress_layout.addStretch()
        for i in range(len(steps_content)):
            dot = QLabel()
            dot.setObjectName("progressDot")
            dot.setFixedSize(12, 12)
            self.progress_dots.append(dot)
            progress_layout.addWidget(dot)
        progress_layout.addStretch()
        bottom_controls_layout.addLayout(progress_layout)

        buttons_and_check_layout = QHBoxLayout()
        self.never_show_again_checkbox = QCheckBox(self._tr("tour_dialog_never_show_checkbox", "Never show this again"))
        buttons_and_check_layout.addWidget(self.never_show_again_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        buttons_and_check_layout.addStretch()

        self.skip_button = QPushButton(self._tr("tour_dialog_skip_button", "Skip"))
        self.skip_button.clicked.connect(self._skip_tour_action)
        self.back_button = QPushButton(self._tr("tour_dialog_back_button", "Back"))
        self.back_button.clicked.connect(self._previous_step)
        self.next_button = QPushButton(self._tr("tour_dialog_next_button", "Next"))
        self.next_button.clicked.connect(self._next_step_action)
        self.next_button.setDefault(True)
        self.next_button.setObjectName("nextButton")

        buttons_and_check_layout.addWidget(self.skip_button)
        buttons_and_check_layout.addWidget(self.back_button)
        buttons_and_check_layout.addWidget(self.next_button)
        bottom_controls_layout.addLayout(buttons_and_check_layout)

        self._update_ui_states()

    def _apply_theme(self):
        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            dark_theme_base = get_dark_theme(scale)
            tour_styles = """
                QDialog {
                    background-color: #2D2D30;
                }
                QFrame#bottomFrame {
                    background-color: #252526;
                    border-top: 1px solid #3E3E42;
                }
                QFrame#contentFrame {
                    border: 1px solid #3E3E42;
                    border-radius: 5px;
                }
                QScrollArea {
                    background-color: transparent;
                    border: none;
                }
                QPushButton {
                    background-color: #555;
                    border-radius: 6px;
                    border: 1px solid #4F4F4F;
                }
                QPushButton:hover {
                    background-color: #007ACC;
                    border: 1px solid #005A9E;
                }
                QPushButton#nextButton {
                    background-color: #007ACC;
                    border: 1px solid #005A9E;
                    padding: 8px 18px;
                    font-weight: bold;
                }
                QPushButton#nextButton:hover {
                    background-color: #1E90FF;
                }
                QPushButton:disabled {
                    background-color: #444;
                    border-color: #555;
                }
            """
            self.setStyleSheet(dark_theme_base + tour_styles)
        else:
            self.setStyleSheet("QDialog { background-color: #f0f0f0; }")


    def _center_on_screen(self):
        try:
            screen_geo = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geo.center() - self.rect().center())
        except Exception as e:
            print(f"[TourDialog] Error centering dialog: {e}")

    def _next_step_action(self):
        if self.current_step < self.stacked_widget.count() - 1:
            self.current_step += 1
            self.stacked_widget.setCurrentIndex(self.current_step)
        else:
            self._finish_tour_action()
        self._update_ui_states()

    def _previous_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.stacked_widget.setCurrentIndex(self.current_step)
        self._update_ui_states()

    def _update_ui_states(self):
        is_last_step = self.current_step == self.stacked_widget.count() - 1
        self.next_button.setText(self._tr("tour_dialog_finish_button", "Finish") if is_last_step else self._tr("tour_dialog_next_button", "Next"))
        self.back_button.setEnabled(self.current_step > 0)
        self.skip_button.setVisible(not is_last_step)

        for i, dot in enumerate(self.progress_dots):
            dot.setProperty("active", i == self.current_step)
            dot.style().polish(dot)

    def _skip_tour_action(self):
        self._save_settings_if_checked()
        self.tour_skipped.emit()
        self.reject()

    def _finish_tour_action(self):
        self._save_settings_if_checked()
        self.tour_finished_normally.emit()
        self.accept()

    def _save_settings_if_checked(self):
        self.settings.setValue(self.TOUR_SHOWN_KEY, self.never_show_again_checkbox.isChecked())
        self.settings.sync()

    @staticmethod
    def should_show_tour():
        settings = QSettings(TourDialog.CONFIG_ORGANIZATION_NAME, TourDialog.CONFIG_APP_NAME_TOUR)
        never_show = settings.value(TourDialog.TOUR_SHOWN_KEY, False, type=bool)
        return not never_show

    def closeEvent(self, event):
        self._skip_tour_action()
        super().closeEvent(event)