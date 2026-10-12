from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QDialogButtonBox, QButtonGroup, QLabel,
    QComboBox, QHBoxLayout, QCheckBox, QFrame, QWidget
)
from PySide6.QtCore import Qt, QPropertyAnimation, Property, Signal, QEvent
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
        self.setFixedSize(40, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)
        self._thumb_position = 22.0 if checked else 3.0
        self._anim = QPropertyAnimation(self, b"thumb_position", self)
        self._anim.setDuration(150)

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
            self._anim.setEndValue(22.0 if checked else 3.0)
            self._anim.start()
            self.toggled.emit(checked)
        self.update()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ForbiddenCursor)
            self.update()
        super().changeEvent(event)

    def mousePressEvent(self, event):
        if not self.isEnabled():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_enabled = self.isEnabled()
        if not is_enabled:
            track_color = QColor("#2A2A2A")
            thumb_color = QColor("#555555")
        elif self._checked:
            track_color = QColor("#007ACC")
            thumb_color = QColor("#FFFFFF")
        else:
            track_color = QColor("#444444")
            thumb_color = QColor("#FFFFFF")

        # Track background
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 1, 40, 18, 9, 9)

        # Thumb
        painter.setBrush(QBrush(thumb_color))
        painter.drawEllipse(int(self._thumb_position), 3, 14, 14)
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
        self.setFixedWidth(310)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 10, 14, 10)

        # ── Scope section (Compact side-by-side) ────────────────────────────
        scope_layout = QHBoxLayout()
        scope_layout.setSpacing(10)
        self.description_label = QLabel("Scope:")
        self.description_label.setStyleSheet("font-weight: bold;")
        scope_layout.addWidget(self.description_label)

        self.radio_button_group = QButtonGroup(self)
        self.radio_content = QRadioButton("Description")
        self.radio_comments = QRadioButton("Comments")
        self.radio_button_group.addButton(self.radio_content)
        self.radio_button_group.addButton(self.radio_comments)
        scope_layout.addWidget(self.radio_content)
        scope_layout.addWidget(self.radio_comments)
        scope_layout.addStretch()
        layout.addLayout(scope_layout)

        if self.is_simpcity:
            self.radio_comments.setVisible(False)
            self.radio_content.setVisible(False)
            self.description_label.setText("Format:")

        if current_scope == self.SCOPE_COMMENTS and not self.is_simpcity:
            self.radio_comments.setChecked(True)
        else:
            self.radio_content.setChecked(True)

        # ── Export format ───────────────────────────────────────────────────
        export_layout = QHBoxLayout()
        export_layout.setSpacing(8)
        export_label = QLabel("Export as:")
        export_label.setStyleSheet("font-weight: bold;")
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PDF", "DOCX", "TXT"])
        self.format_combo.setFixedWidth(80)

        if current_format and current_format.upper() in ["PDF", "DOCX", "TXT"]:
            self.format_combo.setCurrentText(current_format.upper())
        else:
            self.format_combo.setCurrentText("PDF")

        export_layout.addWidget(export_label)
        export_layout.addWidget(self.format_combo)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        # ── PDF options (Compact side-by-side) ───────────────────────────────
        pdf_options_layout = QHBoxLayout()
        pdf_options_layout.setSpacing(12)

        self.single_pdf_checkbox = QCheckBox("Single PDF")
        self.single_pdf_checkbox.setToolTip(
            "If checked, all text from matching posts will be compiled into one single PDF file."
        )
        self.single_pdf_checkbox.setChecked(single_pdf_checked)
        pdf_options_layout.addWidget(self.single_pdf_checkbox)

        self.add_info_checkbox = QCheckBox("Add Info Page")
        self.add_info_checkbox.setToolTip(
            "If checked, adds a first page with post details (Title, Date, Link, Creator, Tags, etc.)."
        )
        self.add_info_checkbox.setChecked(add_info_checked)
        pdf_options_layout.addWidget(self.add_info_checkbox)
        pdf_options_layout.addStretch()
        layout.addLayout(pdf_options_layout)

        if self.is_simpcity:
            self.add_info_checkbox.setVisible(False)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── Combined Download Toggle (Simple & clean) ───────────────────────
        switch_row = QHBoxLayout()
        switch_row.setSpacing(8)
        self.combined_mode_switch = SlideSwitch(self, checked=combined_mode_checked)
        self.combined_mode_checkbox = self.combined_mode_switch  # Backward-compatible alias

        self.switch_label = QLabel("Combined Download")
        self.switch_label.setStyleSheet("font-size: 12px; color: #E0E0E0;")

        switch_row.addWidget(self.combined_mode_switch)
        switch_row.addWidget(self.switch_label)
        switch_row.addStretch()
        layout.addLayout(switch_row)

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
        if enabled:
            self.single_pdf_checkbox.setChecked(False)
            self.single_pdf_checkbox.setEnabled(False)
            self.radio_comments.setEnabled(False)
            self.radio_content.setChecked(True)
        else:
            self.radio_comments.setEnabled(True)
            is_pdf = (self.format_combo.currentText().upper() == "PDF")
            self.single_pdf_checkbox.setEnabled(is_pdf)

    def update_checkbox_states(self, text):
        """Enable PDF-specific checkboxes and combined mode only if the format is PDF."""
        is_pdf = (text.upper() == "PDF")

        # Turn off and lock Combined Download if format is not PDF
        if hasattr(self, 'combined_mode_switch'):
            if not is_pdf:
                if self.combined_mode_switch.isChecked():
                    self.combined_mode_switch.setChecked(False)
                self.combined_mode_switch.setEnabled(False)
                self.combined_mode_switch.setToolTip(
                    "Combined Download is only available for PDF format."
                )
            else:
                self.combined_mode_switch.setEnabled(True)
                self.combined_mode_switch.setToolTip(
                    "Enable to download files and generate documents simultaneously (switches 'More' to checkbox mode)."
                )

        if hasattr(self, 'switch_label'):
            self.switch_label.setEnabled(is_pdf)
            if is_pdf:
                self.switch_label.setStyleSheet("font-size: 12px; color: #E0E0E0;")
                self.switch_label.setToolTip(
                    "Enable to download files and generate documents simultaneously (switches 'More' to checkbox mode)."
                )
            else:
                self.switch_label.setStyleSheet("font-size: 12px; color: #666666;")
                self.switch_label.setToolTip(
                    "Combined Download is only available for PDF format."
                )

        combined_on = self.combined_mode_checkbox.isChecked() if hasattr(self, 'combined_mode_checkbox') else False

        self.single_pdf_checkbox.setEnabled(is_pdf and not combined_on)
        self.add_info_checkbox.setEnabled(is_pdf and not self.is_simpcity)

        if not is_pdf:
            self.single_pdf_checkbox.setChecked(False)
            self.add_info_checkbox.setChecked(False)

    # ── Getters ─────────────────────────────────────────────────────────────

    def get_combined_mode_state(self) -> bool:
        """Returns True if Combined Mode (download + PDF) is active."""
        return self.combined_mode_checkbox.isChecked() and self.combined_mode_checkbox.isEnabled()

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