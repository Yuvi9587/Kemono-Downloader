from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QDialogButtonBox, QButtonGroup, QLabel,
    QComboBox, QHBoxLayout, QCheckBox, QFrame, QWidget
)
from PySide6.QtCore import Qt, QPropertyAnimation, Property, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from ...utils.resolution import get_dark_theme


class SlideSwitch(QWidget):
    """
    A smooth animated toggle slide switch for switching between
    Radio Mode (Text/PDF only) and Checkbox Mode (Combined Download).
    """
    toggled = Signal(bool)

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self.setFixedSize(48, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)
        self._thumb_position = 26.0 if checked else 4.0
        self._anim = QPropertyAnimation(self, b"thumb_position", self)
        self._anim.setDuration(160)

    @Property(float)
    def thumb_position(self):
        return self._thumb_position

    @thumb_position.setter
    def thumb_position(self, pos):
        self._thumb_position = pos
        self.update()

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        checked = bool(checked)
        if self._checked != checked:
            self._checked = checked
            self._anim.stop()
            self._anim.setStartValue(self._thumb_position)
            self._anim.setEndValue(26.0 if checked else 4.0)
            self._anim.start()
            self.toggled.emit(checked)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track background
        track_color = QColor("#007ACC") if self._checked else QColor("#444444")
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 2, 48, 20, 10, 10)

        # Thumb
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(int(self._thumb_position), 4, 16, 16)
        painter.end()


class MoreOptionsDialog(QDialog):
    """
    A dialog for selecting a scope, export format, and single PDF option.
    Also supports a 'Combined Download' toggle that lets users download files AND
    generate a PDF description at the same time.
    """
    SCOPE_CONTENT = "content"
    SCOPE_COMMENTS = "comments"

    def __init__(self, parent=None, current_scope=None, current_format=None,
                 single_pdf_checked=False, add_info_checked=False, is_simpcity=False,
                 combined_mode_checked=False):
        super().__init__(parent)
        self.parent_app = parent
        self.is_simpcity = is_simpcity
        self.setWindowTitle("More Options")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Combined Download Section with Slide Switch ─────────────────────
        combined_card = QFrame()
        combined_card.setStyleSheet(
            "QFrame { background-color: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 6px; }"
        )
        combined_card_layout = QVBoxLayout(combined_card)
        combined_card_layout.setContentsMargins(10, 8, 10, 8)
        combined_card_layout.setSpacing(6)

        switch_row = QHBoxLayout()
        self.combined_mode_switch = SlideSwitch(self, checked=combined_mode_checked)
        self.combined_mode_checkbox = self.combined_mode_switch  # Backward-compatible alias

        switch_label = QLabel("<b>Combined Download</b>")
        switch_label.setStyleSheet("font-size: 13px; color: #FFFFFF;")

        self.mode_badge = QLabel("Checkbox Mode" if combined_mode_checked else "Radio Mode")
        self.mode_badge.setStyleSheet(
            "background-color: #007ACC; color: white; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: bold;"
            if combined_mode_checked else
            "background-color: #555555; color: #DDDDDD; padding: 2px 7px; border-radius: 4px; font-size: 11px;"
        )

        switch_row.addWidget(self.combined_mode_switch)
        switch_row.addWidget(switch_label)
        switch_row.addWidget(self.mode_badge)
        switch_row.addStretch()
        combined_card_layout.addLayout(switch_row)

        self.combined_description_label = QLabel(
            "⚡ Switches 'More' to a Checkbox button on the main window so you can select 'All' to download files and create PDF at the same time."
            if combined_mode_checked else
            "⚪ 'More' is a Radio button on the main window (Text/PDF extraction only)."
        )
        self.combined_description_label.setWordWrap(True)
        self.combined_description_label.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        combined_card_layout.addWidget(self.combined_description_label)

        layout.addWidget(combined_card)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── Scope section ───────────────────────────────────────────────────
        self.description_label = QLabel("Please choose the scope for the action:")
        layout.addWidget(self.description_label)

        self.radio_button_group = QButtonGroup(self)
        self.radio_content = QRadioButton("Description/Content")
        self.radio_comments = QRadioButton("Comments")
        self.radio_button_group.addButton(self.radio_content)
        self.radio_button_group.addButton(self.radio_comments)
        layout.addWidget(self.radio_content)
        layout.addWidget(self.radio_comments)

        if self.is_simpcity:
            self.radio_comments.setVisible(False)
            self.radio_content.setVisible(False)
            self.description_label.setText("Please choose the export format:")

        if current_scope == self.SCOPE_COMMENTS and not self.is_simpcity:
            self.radio_comments.setChecked(True)
        else:
            self.radio_content.setChecked(True)

        # ── Export format ───────────────────────────────────────────────────
        export_layout = QHBoxLayout()
        export_label = QLabel("Export as:")
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PDF", "DOCX", "TXT"])

        if current_format and current_format.upper() in ["PDF", "DOCX", "TXT"]:
            self.format_combo.setCurrentText(current_format.upper())
        else:
            self.format_combo.setCurrentText("PDF")

        export_layout.addWidget(export_label)
        export_layout.addWidget(self.format_combo)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        # ── PDF options ─────────────────────────────────────────────────────
        self.single_pdf_checkbox = QCheckBox("Single PDF")
        self.single_pdf_checkbox.setToolTip(
            "If checked, all text from matching posts will be compiled into one single PDF file."
        )
        self.single_pdf_checkbox.setChecked(single_pdf_checked)
        layout.addWidget(self.single_pdf_checkbox)

        self.add_info_checkbox = QCheckBox("Add info in PDF")
        self.add_info_checkbox.setToolTip(
            "If checked, adds a first page with post details (Title, Date, Link, Creator, Tags, etc.)."
        )
        self.add_info_checkbox.setChecked(add_info_checked)
        layout.addWidget(self.add_info_checkbox)

        if self.is_simpcity:
            self.add_info_checkbox.setVisible(False)

        # ── Wire signals ────────────────────────────────────────────────────
        self.format_combo.currentTextChanged.connect(self.update_checkbox_states)
        self.combined_mode_checkbox.toggled.connect(self._on_combined_mode_toggled)
        self.update_checkbox_states(self.format_combo.currentText())
        self._on_combined_mode_toggled(self.combined_mode_checkbox.isChecked())

        # ── Buttons ─────────────────────────────────────────────────────────
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)
        self._apply_theme()

    # ── Slots ───────────────────────────────────────────────────────────────

    def _on_combined_mode_toggled(self, enabled: bool):
        """When Combined Mode is on, disable Single PDF (not applicable)."""
        # In combined mode the PDF is always per-post, so Single PDF makes no sense.
        if hasattr(self, 'mode_badge'):
            self.mode_badge.setText("Checkbox Mode" if enabled else "Radio Mode")
            self.mode_badge.setStyleSheet(
                "background-color: #007ACC; color: white; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: bold;"
                if enabled else
                "background-color: #555555; color: #DDDDDD; padding: 2px 7px; border-radius: 4px; font-size: 11px;"
            )
        if hasattr(self, 'combined_description_label'):
            self.combined_description_label.setText(
                "⚡ Switches 'More' to a Checkbox button on the main window so you can select 'All' to download files and create PDF at the same time."
                if enabled else
                "⚪ 'More' is a Radio button on the main window (Text/PDF extraction only)."
            )

        if enabled:
            self.single_pdf_checkbox.setChecked(False)
            self.single_pdf_checkbox.setEnabled(False)
            self.radio_comments.setEnabled(False)
            self.radio_content.setChecked(True)
            self.description_label.setText(
                "PDF description will be saved inside each post's subfolder alongside downloaded files:"
            )
        else:
            self.description_label.setText("Please choose the scope for the action:")
            self.radio_comments.setEnabled(True)
            self.update_checkbox_states(self.format_combo.currentText())

    def update_checkbox_states(self, text):
        """Enable PDF-specific checkboxes only if the format is PDF."""
        is_pdf = (text.upper() == "PDF")
        combined_on = self.combined_mode_checkbox.isChecked()

        self.single_pdf_checkbox.setEnabled(is_pdf and not combined_on)
        self.add_info_checkbox.setEnabled(is_pdf and not self.is_simpcity)

        if not is_pdf:
            self.single_pdf_checkbox.setChecked(False)
            self.add_info_checkbox.setChecked(False)

    # ── Getters ─────────────────────────────────────────────────────────────

    def get_combined_mode_state(self) -> bool:
        """Returns True if Combined Mode (download + PDF) is active."""
        return self.combined_mode_checkbox.isChecked()

    def get_selected_scope(self):
        if self.is_simpcity:
            return self.SCOPE_CONTENT
        if self.radio_comments.isChecked():
            return self.SCOPE_COMMENTS
        return self.SCOPE_CONTENT

    def get_selected_format(self):
        return self.format_combo.currentText().lower()

    def get_single_pdf_state(self):
        """Returns the state of the Single PDF checkbox."""
        return self.single_pdf_checkbox.isChecked() and self.single_pdf_checkbox.isEnabled()

    def get_add_info_state(self):
        """Returns the state of the Add Info checkbox."""
        if self.is_simpcity:
            return False
        return self.add_info_checkbox.isChecked() and self.add_info_checkbox.isEnabled()

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and hasattr(self.parent_app, 'current_theme') and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")