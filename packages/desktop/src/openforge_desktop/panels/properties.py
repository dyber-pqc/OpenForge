"""Properties panel for inspecting signal/module attributes."""

from __future__ import annotations

from typing import Any, Final

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
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        container = QWidget()
        container.setStyleSheet(f"""
            QHeaderView::section {{
                background-color: {_CLR_SECTION_BG};
                color: #a6adc8;
                border: none;
                border-right: 1px solid #313244;
                border-bottom: 1px solid #313244;
                padding: 4px 6px;
                font-size: 11px;
                font-weight: bold;
            }}
            QTableWidget {{
                background-color: #1e1e2e;
                alternate-background-color: #1a1a2e;
                color: {_CLR_VALUE};
                gridline-color: #313244;
                border: none;
                font-size: 11px;
            }}
            QTableWidget::item {{
                padding: 2px 6px;
            }}
            QTableWidget::item:selected {{
                background-color: #313244;
            }}
        """)
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

    def show_from_netlist_cell(
        self,
        cell_name: str,
        netlist_data: "Any",
    ) -> None:
        """Display properties for a cell from a Yosys/gate-level netlist.

        Parameters
        ----------
        cell_name:
            Instance name of the cell to display.
        netlist_data:
            A ``NetlistParser`` (``packages/core/src/openforge/synthesis/netlist.py``)
            or any object whose ``.cells`` attribute is iterable over
            objects with ``name``, ``type``, ``connections``, and ``parameters``.
        """
        self._title_label.setText(f"  Cell: {cell_name}")
        self._table.setRowCount(0)

        # Find the cell across all modules
        target = None
        for cell in netlist_data.cells:
            if cell.name == cell_name:
                target = cell
                break

        if target is None:
            self._add_section("Cell Info")
            self._add_row("Name", cell_name)
            self._add_row("Status", "Not found in netlist")
            return

        self._add_section("Cell Info")
        self._add_row("Instance", target.name)
        self._add_row("Cell Type", target.type)

        # Port connections
        if target.connections:
            self._add_section("Port Connections")
            for port_name, bits in target.connections.items():
                bit_str = ", ".join(str(b) for b in bits) if bits else "-"
                self._add_row(port_name, bit_str)

        # Parameters
        if target.parameters:
            self._add_section("Parameters")
            for pname, pval in target.parameters.items():
                self._add_row(pname, str(pval))

        # Attributes (may contain timing info)
        if hasattr(target, "attributes") and target.attributes:
            self._add_section("Attributes")
            for aname, aval in target.attributes.items():
                self._add_row(aname, str(aval))

    def show_from_vcd_signal(
        self,
        signal_name: str,
        waveform_data: "Any",
    ) -> None:
        """Display properties for a signal from loaded VCD waveform data.

        Parameters
        ----------
        signal_name:
            Full hierarchical name of the signal.
        waveform_data:
            A ``WaveformData`` object from ``openforge.waveform.loader``.
        """
        self._title_label.setText(f"  Signal: {signal_name}")
        self._table.setRowCount(0)

        sig = waveform_data.get_signal(signal_name)
        if sig is None:
            self._add_section("Signal Info")
            self._add_row("Name", signal_name)
            self._add_row("Status", "Not found in waveform data")
            return

        self._add_section("Signal Info")
        self._add_row("Name", sig.full_name)
        self._add_row("Width", str(sig.width))
        self._add_row("Type", sig.signal_type.value)
        self._add_row("Scope", sig.scope if sig.scope else "(top)")

        # Current value (last recorded)
        if sig.changes:
            self._add_row("Last Value", sig.changes[-1].value)

        # Toggle count: number of value changes
        toggle_count = max(len(sig.changes) - 1, 0)
        self._add_section("Activity")
        self._add_row("Toggle Count", str(toggle_count))

        if sig.changes:
            first_t = sig.changes[0].time
            last_t = sig.changes[-1].time
            ts_mag = waveform_data.timescale_magnitude
            ts_unit = waveform_data.timescale_unit.value
            self._add_row(
                "First Transition",
                f"{first_t * ts_mag} {ts_unit}",
            )
            self._add_row(
                "Last Transition",
                f"{last_t * ts_mag} {ts_unit}",
            )

    def show_layout_cell_properties(
        self,
        name: str,
        cell_type: str,
        x_microns: float,
        y_microns: float,
        orientation: str = "N",
        connected_nets: list[str] | None = None,
        area: float = 0.0,
    ) -> None:
        """Populate the table with placed cell properties from layout viewer."""
        self._title_label.setText(f"  Cell: {name}")
        self._table.setRowCount(0)

        self._add_section("Cell Info")
        self._add_row("Instance Name", name)
        self._add_row("Cell Type", cell_type)
        self._add_row("Position X", f"{x_microns:.2f} um")
        self._add_row("Position Y", f"{y_microns:.2f} um")
        self._add_row("Orientation", orientation)
        if area > 0:
            self._add_row("Area", f"{area:.2f} um^2")

        if connected_nets:
            self._add_section("Connected Nets")
            for net_name in connected_nets[:20]:  # limit display
                self._add_row("Net", net_name)
            if len(connected_nets) > 20:
                self._add_row("...", f"+{len(connected_nets) - 20} more")

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
