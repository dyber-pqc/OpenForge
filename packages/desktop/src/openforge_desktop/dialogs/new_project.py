"""New Project dialog for creating an OpenForge project."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$")


class NewProjectDialog(QDialog):
    """Dialog for creating a new OpenForge EDA project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Form
        form = QFormLayout()
        form.setSpacing(8)

        # Project name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("my-project")
        self._name_edit.textChanged.connect(self._validate)
        form.addRow("Project Name:", self._name_edit)

        # Error label for name validation
        self._name_error = QLabel("")
        self._name_error.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self._name_error.setVisible(False)
        form.addRow("", self._name_error)

        # Location
        loc_row = QWidget()
        loc_layout = QHBoxLayout(loc_row)
        loc_layout.setContentsMargins(0, 0, 0, 0)
        loc_layout.setSpacing(4)

        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText("Select project directory...")
        loc_layout.addWidget(self._location_edit)

        btn_browse = QPushButton("Browse...")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_location)
        loc_layout.addWidget(btn_browse)

        form.addRow("Location:", loc_row)

        # Template
        self._template_combo = QComboBox()
        self._template_combo.addItems([
            "empty",
            "simple-counter",
            "crypto-accelerator",
        ])
        form.addRow("Template:", self._template_combo)

        # Target PDK
        self._pdk_combo = QComboBox()
        self._pdk_combo.addItems([
            "sky130",
            "gf180mcu",
            "asap7",
        ])
        form.addRow("Target PDK:", self._pdk_combo)

        layout.addLayout(form)

        # Button box
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        # Initial validation
        self._validate()

    # ── Public API ─────────────────────────────────────────────────

    def result_data(self) -> tuple[str, str, str, str]:
        """Return (name, path, template, pdk) from the dialog."""
        return (
            self._name_edit.text().strip(),
            self._location_edit.text().strip(),
            self._template_combo.currentText(),
            self._pdk_combo.currentText(),
        )

    # ── Internal ───────────────────────────────────────────────────

    def _browse_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select Project Location", ""
        )
        if directory:
            self._location_edit.setText(directory)

    def _validate(self) -> None:
        name = self._name_edit.text().strip()
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)

        if not name:
            self._name_error.setText("Project name is required")
            self._name_error.setVisible(True)
            ok_btn.setEnabled(False)
            return

        if not _NAME_PATTERN.match(name):
            self._name_error.setText(
                "Only letters, digits, and hyphens allowed (must start with alphanumeric)"
            )
            self._name_error.setVisible(True)
            ok_btn.setEnabled(False)
            return

        self._name_error.setVisible(False)
        ok_btn.setEnabled(True)

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        location = self._location_edit.text().strip()

        if not name or not _NAME_PATTERN.match(name):
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid project name.")
            return

        if not location:
            QMessageBox.warning(self, "No Location", "Please select a project location.")
            return

        if not Path(location).is_dir():
            QMessageBox.warning(
                self, "Invalid Location", "The selected location does not exist."
            )
            return

        self.accept()
