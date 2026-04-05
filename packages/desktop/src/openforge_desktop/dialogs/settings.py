"""Settings dialog for OpenForge EDA preferences."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def _tool_row(
    parent: QWidget,
    settings: QSettings,
    key: str,
    tool_name: str,
) -> tuple[QLineEdit, QPushButton, QPushButton]:
    """Create a row with path input, browse button, and auto-detect button."""
    edit = QLineEdit()
    edit.setPlaceholderText(f"Path to {tool_name}...")
    saved = settings.value(f"tools/{key}", "")
    if saved:
        edit.setText(str(saved))

    btn_browse = QPushButton("Browse...")
    btn_browse.setFixedWidth(80)
    btn_browse.clicked.connect(
        lambda: _browse_tool(parent, edit, tool_name)
    )

    btn_detect = QPushButton("Detect")
    btn_detect.setFixedWidth(60)
    btn_detect.clicked.connect(lambda: _auto_detect(edit, tool_name))

    return edit, btn_browse, btn_detect


def _browse_tool(parent: QWidget, edit: QLineEdit, tool_name: str) -> None:
    path, _ = QFileDialog.getOpenFileName(
        parent, f"Locate {tool_name}", "", "All Files (*)"
    )
    if path:
        edit.setText(path)


def _auto_detect(edit: QLineEdit, tool_name: str) -> None:
    found = shutil.which(tool_name)
    if found:
        edit.setText(found)
    else:
        edit.setPlaceholderText(f"{tool_name} not found in PATH")


class _GeneralTab(QWidget):
    """General settings tab."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        form = QFormLayout()
        form.setSpacing(8)

        # Default PDK
        self.pdk_combo = QComboBox()
        self.pdk_combo.addItems(["sky130", "gf180mcu", "asap7"])
        saved_pdk = settings.value("general/default_pdk", "sky130")
        idx = self.pdk_combo.findText(str(saved_pdk))
        if idx >= 0:
            self.pdk_combo.setCurrentIndex(idx)
        form.addRow("Default PDK:", self.pdk_combo)

        # Default simulator
        self.sim_combo = QComboBox()
        self.sim_combo.addItems(["verilator", "iverilog", "xcelium", "vcs"])
        saved_sim = settings.value("general/default_simulator", "verilator")
        idx = self.sim_combo.findText(str(saved_sim))
        if idx >= 0:
            self.sim_combo.setCurrentIndex(idx)
        form.addRow("Default Simulator:", self.sim_combo)

        # Project root
        root_row = QWidget()
        root_layout = QHBoxLayout(root_row)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(4)

        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Default project directory...")
        saved_root = settings.value("general/project_root", "")
        if saved_root:
            self.root_edit.setText(str(saved_root))
        root_layout.addWidget(self.root_edit)

        btn_browse = QPushButton("Browse...")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_root)
        root_layout.addWidget(btn_browse)

        form.addRow("Project Root:", root_row)

        layout.addLayout(form)
        layout.addStretch()

    def _browse_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select Project Root Directory", self.root_edit.text()
        )
        if directory:
            self.root_edit.setText(directory)

    def save(self) -> None:
        self._settings.setValue("general/default_pdk", self.pdk_combo.currentText())
        self._settings.setValue("general/default_simulator", self.sim_combo.currentText())
        self._settings.setValue("general/project_root", self.root_edit.text())


class _ToolsTab(QWidget):
    """Tool paths settings tab."""

    _TOOLS = [
        ("verilator", "verilator"),
        ("yosys", "yosys"),
        ("verible", "verible-verilog-lint"),
        ("symbiyosys", "sby"),
        ("opensta", "sta"),
    ]

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._edits: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        form = QFormLayout()
        form.setSpacing(8)

        labels = {
            "verilator": "Verilator:",
            "yosys": "Yosys:",
            "verible": "Verible:",
            "symbiyosys": "SymbiYosys:",
            "opensta": "OpenSTA:",
        }

        for key, tool_name in self._TOOLS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            edit, btn_browse, btn_detect = _tool_row(self, settings, key, tool_name)
            row_layout.addWidget(edit)
            row_layout.addWidget(btn_browse)
            row_layout.addWidget(btn_detect)

            form.addRow(labels[key], row)
            self._edits[key] = edit

        layout.addLayout(form)
        layout.addStretch()

    def save(self) -> None:
        for key, edit in self._edits.items():
            self._settings.setValue(f"tools/{key}", edit.text())


class _AppearanceTab(QWidget):
    """Appearance settings tab."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        form = QFormLayout()
        form.setSpacing(8)

        # Theme
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark (Catppuccin Mocha)", "Light"])
        saved_theme = settings.value("appearance/theme", "dark")
        if str(saved_theme) == "light":
            self.theme_combo.setCurrentIndex(1)
        form.addRow("Theme:", self.theme_combo)

        # Font size
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setSuffix(" px")
        saved_size = settings.value("appearance/font_size", 13)
        self.font_size_spin.setValue(int(saved_size))
        form.addRow("Font Size:", self.font_size_spin)

        # Editor font
        self.editor_font_combo = QComboBox()
        self.editor_font_combo.setEditable(True)
        self.editor_font_combo.addItems([
            "JetBrains Mono",
            "Cascadia Code",
            "Fira Code",
            "Consolas",
            "Source Code Pro",
            "Hack",
        ])
        saved_font = settings.value("appearance/editor_font", "JetBrains Mono")
        idx = self.editor_font_combo.findText(str(saved_font))
        if idx >= 0:
            self.editor_font_combo.setCurrentIndex(idx)
        else:
            self.editor_font_combo.setCurrentText(str(saved_font))
        form.addRow("Editor Font:", self.editor_font_combo)

        layout.addLayout(form)
        layout.addStretch()

    def save(self) -> None:
        theme = "dark" if self.theme_combo.currentIndex() == 0 else "light"
        self._settings.setValue("appearance/theme", theme)
        self._settings.setValue("appearance/font_size", self.font_size_spin.value())
        self._settings.setValue("appearance/editor_font", self.editor_font_combo.currentText())


class SettingsDialog(QDialog):
    """Application settings dialog with General, Tools, and Appearance tabs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(560, 420)
        self.setModal(True)

        self._settings = QSettings("Dyber", "OpenForge EDA")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Tab widget
        self._tabs = QTabWidget()

        self._general = _GeneralTab(self._settings)
        self._tabs.addTab(self._general, "General")

        self._tools = _ToolsTab(self._settings)
        self._tabs.addTab(self._tools, "Tools")

        self._appearance = _AppearanceTab(self._settings)
        self._tabs.addTab(self._appearance, "Appearance")

        layout.addWidget(self._tabs)

        # Button box
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        self._general.save()
        self._tools.save()
        self._appearance.save()
        self._settings.sync()
        self.accept()
