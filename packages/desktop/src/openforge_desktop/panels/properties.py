"""Properties panel for inspecting signal/module attributes."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Catppuccin Mocha accent colours for section headers
_CLR_SECTION: Final[str] = "#89b4fa"   # blue
_CLR_KEY: Final[str] = "#a6adc8"       # subtext0
_CLR_VALUE: Final[str] = "#cdd6f4"     # text
_CLR_SECTION_BG: Final[str] = "#181825"  # mantle


def _section_item(text: str) -> QTableWidgetItem:
    """Create a bold, coloured section-header item spanning the row."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    font = QFont()
    font.setBold(True)
    item.setFont(font)
    item.setForeground(QColor(_CLR_SECTION))
    item.setBackground(QColor(_CLR_SECTION_BG))
    return item


def _key_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(_CLR_KEY))
    return item


def _value_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsEditable
    )
    item.setForeground(QColor(_CLR_VALUE))
    return item


class PropertiesPanel(QDockWidget):
    """Dock widget displaying properties for the currently selected object."""

    def __init__(self, title: str = "Properties", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title label showing what is selected
        self._title_label = QLabel("  No selection")
        self._title_label.setStyleSheet(
            "padding: 6px 8px; font-weight: bold; color: #cdd6f4; "
            "background-color: #181825; border-bottom: 1px solid #313244;"
        )
        layout.addWidget(self._title_label)

        # Property table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Property", "Value"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { alternate-background-color: #1a1a2e; }"
            "QTableWidget::item { padding: 2px 6px; }"
        )
        self._table.setShowGrid(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        self.setWidget(container)

    # ── Public API ─────────────────────────────────────────────────

    def show_signal_properties(
        self,
        name: str,
        width: int = 1,
        direction: str = "input",
        sig_type: str = "wire",
        value: str = "",
    ) -> None:
        """Populate the table with signal properties."""
        self._title_label.setText(f"  Signal: {name}")
        self._table.setRowCount(0)

        self._add_section("Signal Info")
        self._add_row("Name", name)
        self._add_row("Width", str(width))
        self._add_row("Direction", direction)
        self._add_row("Type", sig_type)
        if value:
            self._add_row("Value", value)

        self._add_section("Timing")
        self._add_row("Setup", "-")
        self._add_row("Hold", "-")
        self._add_row("Clock-to-Q", "-")

        self._add_section("Power")
        self._add_row("Toggle Rate", "-")
        self._add_row("Switching Power", "-")

    def show_module_properties(
        self,
        name: str,
        ports: list[dict[str, str]] | None = None,
        parameters: dict[str, str] | None = None,
    ) -> None:
        """Populate the table with module properties."""
        self._title_label.setText(f"  Module: {name}")
        self._table.setRowCount(0)

        self._add_section("Module Info")
        self._add_row("Name", name)
        self._add_row("Instance Count", "-")
        self._add_row("Cell Area", "-")

        if ports:
            self._add_section("Ports")
            for port in ports:
                port_name = port.get("name", "?")
                port_dir = port.get("direction", "?")
                port_width = port.get("width", "1")
                self._add_row(port_name, f"{port_dir} [{port_width}]")

        if parameters:
            self._add_section("Parameters")
            for pname, pval in parameters.items():
                self._add_row(pname, pval)

        self._add_section("Timing")
        self._add_row("Critical Path", "-")
        self._add_row("Max Frequency", "-")
        self._add_row("Slack", "-")

        self._add_section("Power")
        self._add_row("Dynamic Power", "-")
        self._add_row("Leakage Power", "-")
        self._add_row("Total Power", "-")

    def clear(self) -> None:
        """Reset the properties panel to its empty state."""
        self._title_label.setText("  No selection")
        self._table.setRowCount(0)

    # ── Internal helpers ───────────────────────────────────────────

    def _add_section(self, title: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        header = _section_item(title)
        blank = _section_item("")
        self._table.setItem(row, 0, header)
        self._table.setItem(row, 1, blank)
        self._table.setSpan(row, 0, 1, 2)

    def _add_row(self, key: str, value: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, _key_item(key))
        self._table.setItem(row, 1, _value_item(value))
