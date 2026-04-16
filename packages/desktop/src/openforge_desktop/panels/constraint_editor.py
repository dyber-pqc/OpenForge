"""Vivado-style visual constraint editor for SDC/XDC timing constraints.

Provides tabbed interface for Clocks, I/O Timing, Pin Assignment, Timing
Exceptions, and Raw SDC editing.  Each GUI element maps bidirectionally to
SDC commands.  Includes clock waveform preview, port auto-population from
Verilog source, and SKY130 driving cell selection.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ._theme import panel_tab_qss

# ── Catppuccin Mocha palette ────────────────────────────────────────────────

_BG: Final[str] = "#1e1e2e"
_MANTLE: Final[str] = "#181825"
_CRUST: Final[str] = "#11111b"
_SURFACE0: Final[str] = "#313244"
_SURFACE1: Final[str] = "#45475a"
_SURFACE2: Final[str] = "#585b70"
_TEXT: Final[str] = "#cdd6f4"
_SUBTEXT: Final[str] = "#a6adc8"
_OVERLAY0: Final[str] = "#6c7086"
_BLUE: Final[str] = "#89b4fa"
_GREEN: Final[str] = "#a6e3a1"
_RED: Final[str] = "#f38ba8"
_YELLOW: Final[str] = "#f9e2af"
_MAUVE: Final[str] = "#cba6f7"
_PEACH: Final[str] = "#fab387"
_TEAL: Final[str] = "#94e2d5"
_PINK: Final[str] = "#f5c2e7"
_SAPPHIRE: Final[str] = "#74c7ec"

_ALT_ROW: Final[str] = "#1a1a2e"

# ── SKY130 driving cells ────────────────────────────────────────────────────

_SKY130_DRIVE_CELLS: Final[list[str]] = [
    "sky130_fd_sc_hd__buf_1",
    "sky130_fd_sc_hd__buf_2",
    "sky130_fd_sc_hd__buf_4",
    "sky130_fd_sc_hd__buf_8",
    "sky130_fd_sc_hd__buf_12",
    "sky130_fd_sc_hd__buf_16",
    "sky130_fd_sc_hd__inv_1",
    "sky130_fd_sc_hd__inv_2",
    "sky130_fd_sc_hd__inv_4",
    "sky130_fd_sc_hd__inv_8",
    "sky130_fd_sc_hd__clkbuf_1",
    "sky130_fd_sc_hd__clkbuf_2",
    "sky130_fd_sc_hd__clkbuf_4",
    "sky130_fd_sc_hd__clkbuf_8",
    "sky130_fd_sc_hd__clkbuf_16",
]

# ── IO standards ─────────────────────────────────────────────────────────────

_IO_STANDARDS: Final[list[str]] = [
    "LVCMOS33", "LVCMOS25", "LVCMOS18", "LVCMOS15", "LVCMOS12",
    "LVTTL", "HSTL_I", "HSTL_II", "SSTL135", "SSTL15",
    "DIFF_SSTL135", "DIFF_SSTL15", "LVDS_25",
]

# ── Verilog port parser ─────────────────────────────────────────────────────

_PORT_RE = re.compile(
    r"(input|output|inout)\s+(?:wire|reg|logic)?\s*(\[.*?\])?\s*(\w+)",
)


def _parse_ports(source: str) -> list[dict[str, str]]:
    """Extract ports from Verilog source."""
    ports: list[dict[str, str]] = []
    for m in _PORT_RE.finditer(source):
        ports.append({
            "direction": m.group(1),
            "width": m.group(2) or "",
            "name": m.group(3),
        })
    return ports


# ── SDC syntax highlighter ──────────────────────────────────────────────────

class _SDCSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for SDC/XDC constraint files."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []

        # SDC commands - blue
        cmd_fmt = QTextCharFormat()
        cmd_fmt.setForeground(QColor(_BLUE))
        cmd_fmt.setFontWeight(QFont.Weight.Bold)
        sdc_commands = [
            "create_clock", "create_generated_clock", "set_clock_uncertainty",
            "set_clock_latency", "set_input_delay", "set_output_delay",
            "set_false_path", "set_multicycle_path", "set_max_delay",
            "set_min_delay", "set_input_transition", "set_load",
            "set_driving_cell", "get_ports", "get_pins", "get_clocks",
            "get_nets", "get_cells", "all_inputs", "all_outputs",
            "set_property", "set_io_standard",
        ]
        for cmd in sdc_commands:
            self._rules.append((re.compile(rf"\b{cmd}\b"), cmd_fmt))

        # Flags - mauve
        flag_fmt = QTextCharFormat()
        flag_fmt.setForeground(QColor(_MAUVE))
        self._rules.append((re.compile(r"-\w+"), flag_fmt))

        # Numbers - peach
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor(_PEACH))
        self._rules.append((re.compile(r"\b\d+\.?\d*\b"), num_fmt))

        # Strings - green
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor(_GREEN))
        self._rules.append((re.compile(r'"[^"]*"'), str_fmt))
        self._rules.append((re.compile(r"\{[^}]*\}"), str_fmt))

        # Brackets - teal
        bracket_fmt = QTextCharFormat()
        bracket_fmt.setForeground(QColor(_TEAL))
        self._rules.append((re.compile(r"[\[\]]"), bracket_fmt))

        # Comments - overlay
        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor(_OVERLAY0))
        comment_fmt.setFontItalic(True)
        self._rules.append((re.compile(r"#.*$"), comment_fmt))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ── Clock waveform preview widget ───────────────────────────────────────────

class _ClockWaveformWidget(QWidget):
    """Draws a clock waveform showing period and duty cycle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        self._period_ns: float = 10.0
        self._duty: float = 50.0
        self._name: str = "clk"

    def set_waveform(self, name: str, period_ns: float, duty: float) -> None:
        self._name = name
        self._period_ns = max(period_ns, 0.1)
        self._duty = max(0.1, min(99.9, duty))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        margin = 10
        plot_w = w - 2 * margin
        plot_h = h - 2 * margin - 15

        # Background
        painter.fillRect(self.rect(), QColor(_CRUST))

        # Name label
        painter.setPen(QColor(_SUBTEXT))
        painter.setFont(QFont("Monospace", 8))
        painter.drawText(margin, margin + 8, self._name)

        # Draw waveform: 2 full periods
        high_y = margin + 15
        low_y = margin + 15 + plot_h
        pen = QPen(QColor(_GREEN), 2)
        painter.setPen(pen)

        num_cycles = 2
        cycle_w = plot_w / num_cycles
        high_frac = self._duty / 100.0

        x = margin
        for _ in range(num_cycles):
            # Rising edge
            painter.drawLine(int(x), int(low_y), int(x), int(high_y))
            # High period
            high_end = x + cycle_w * high_frac
            painter.drawLine(int(x), int(high_y), int(high_end), int(high_y))
            # Falling edge
            painter.drawLine(int(high_end), int(high_y), int(high_end), int(low_y))
            # Low period
            low_end = x + cycle_w
            painter.drawLine(int(high_end), int(low_y), int(low_end), int(low_y))
            x = low_end

        # Period annotation
        painter.setPen(QColor(_SUBTEXT))
        painter.setFont(QFont("Monospace", 7))
        arr_y = low_y + 10
        painter.drawLine(int(margin), int(arr_y), int(margin + cycle_w), int(arr_y))
        painter.drawText(int(margin + cycle_w / 2 - 20), int(arr_y + 10),
                         f"T = {self._period_ns:.2f} ns")
        painter.end()


# ── Add Clock Dialog ────────────────────────────────────────────────────────

class _AddClockDialog(QDialog):
    """Dialog for creating a new clock constraint."""

    def __init__(self, parent: QWidget | None = None, ports: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Clock")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)

        self.name_edit = QLineEdit("clk")
        layout.addRow("Clock Name:", self.name_edit)

        self.period_spin = QDoubleSpinBox()
        self.period_spin.setRange(0.1, 10000.0)
        self.period_spin.setValue(10.0)
        self.period_spin.setSuffix(" ns")
        self.period_spin.setDecimals(3)
        layout.addRow("Period:", self.period_spin)

        self.duty_spin = QDoubleSpinBox()
        self.duty_spin.setRange(0.1, 99.9)
        self.duty_spin.setValue(50.0)
        self.duty_spin.setSuffix(" %")
        layout.addRow("Duty Cycle:", self.duty_spin)

        self.source_combo = QComboBox()
        if ports:
            self.source_combo.addItems(ports)
        self.source_combo.setEditable(True)
        layout.addRow("Source Port/Pin:", self.source_combo)

        self._waveform = _ClockWaveformWidget()
        layout.addRow("Preview:", self._waveform)

        self.period_spin.valueChanged.connect(self._update_preview)
        self.duty_spin.valueChanged.connect(self._update_preview)
        self.name_edit.textChanged.connect(self._update_preview)
        self._update_preview()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _update_preview(self) -> None:
        self._waveform.set_waveform(
            self.name_edit.text(), self.period_spin.value(), self.duty_spin.value()
        )

    def get_data(self) -> dict[str, Any]:
        rise = 0.0
        fall = self.period_spin.value() * self.duty_spin.value() / 100.0
        return {
            "name": self.name_edit.text(),
            "period": self.period_spin.value(),
            "duty": self.duty_spin.value(),
            "waveform": f"{{{rise:.3f} {fall:.3f}}}",
            "source": self.source_combo.currentText(),
        }


# ── Add Generated Clock Dialog ──────────────────────────────────────────────

class _AddGenClockDialog(QDialog):
    """Dialog for creating a generated clock constraint."""

    def __init__(self, parent: QWidget | None = None, clocks: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Generated Clock")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)

        self.name_edit = QLineEdit("gen_clk")
        layout.addRow("Clock Name:", self.name_edit)

        self.source_combo = QComboBox()
        if clocks:
            self.source_combo.addItems(clocks)
        self.source_combo.setEditable(True)
        layout.addRow("Source Clock:", self.source_combo)

        self.divide_spin = QSpinBox()
        self.divide_spin.setRange(1, 1024)
        self.divide_spin.setValue(2)
        layout.addRow("Divide By:", self.divide_spin)

        self.multiply_spin = QSpinBox()
        self.multiply_spin.setRange(1, 1024)
        self.multiply_spin.setValue(1)
        layout.addRow("Multiply By:", self.multiply_spin)

        self.pin_edit = QLineEdit()
        layout.addRow("Output Pin:", self.pin_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict[str, Any]:
        return {
            "name": self.name_edit.text(),
            "source": self.source_combo.currentText(),
            "divide_by": self.divide_spin.value(),
            "multiply_by": self.multiply_spin.value(),
            "pin": self.pin_edit.text(),
        }


# ── Timing Exception Dialog ─────────────────────────────────────────────────

class _AddExceptionDialog(QDialog):
    """Dialog for adding timing exceptions."""

    def __init__(
        self,
        parent: QWidget | None = None,
        ports: list[str] | None = None,
        clocks: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Timing Exception")
        self.setMinimumWidth(450)
        layout = QFormLayout(self)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["false_path", "multicycle_path", "max_delay", "min_delay"])
        layout.addRow("Exception Type:", self.type_combo)

        self.from_combo = QComboBox()
        self.from_combo.setEditable(True)
        if ports:
            self.from_combo.addItems(ports)
        layout.addRow("From:", self.from_combo)

        self.through_edit = QLineEdit()
        self.through_edit.setPlaceholderText("Optional: through points (space separated)")
        layout.addRow("Through:", self.through_edit)

        self.to_combo = QComboBox()
        self.to_combo.setEditable(True)
        if ports:
            self.to_combo.addItems(ports)
        layout.addRow("To:", self.to_combo)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.0, 100000.0)
        self.value_spin.setValue(10.0)
        self.value_spin.setSuffix(" ns")
        layout.addRow("Value (for delay/multicycle):", self.value_spin)

        self.multiplier_spin = QSpinBox()
        self.multiplier_spin.setRange(1, 100)
        self.multiplier_spin.setValue(2)
        layout.addRow("Multiplier (multicycle):", self.multiplier_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict[str, Any]:
        return {
            "type": self.type_combo.currentText(),
            "from": self.from_combo.currentText(),
            "through": self.through_edit.text(),
            "to": self.to_combo.currentText(),
            "value": self.value_spin.value(),
            "multiplier": self.multiplier_spin.value(),
        }


# ── Pin Assignment Grid ─────────────────────────────────────────────────────

class _PinGridScene(QGraphicsScene):
    """Simplified FPGA package pin grid."""

    pin_dropped = Signal(str, str)  # (signal_name, pin_loc)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(_CRUST)))
        self._pins: dict[str, QGraphicsRectItem] = {}
        self._assignments: dict[str, str] = {}  # pin_loc -> signal_name
        self._build_grid()

    def _build_grid(self, rows: int = 12, cols: int = 12) -> None:
        self.clear()
        self._pins.clear()
        cell = 28
        margin = 20
        font = QFont("Monospace", 5)

        # Draw package outline
        pkg_w = cols * cell + margin * 2
        pkg_h = rows * cell + margin * 2
        pen = QPen(QColor(_SURFACE1), 2)
        self.addRect(QRectF(0, 0, pkg_w, pkg_h), pen, QBrush(QColor(_MANTLE)))

        # Pin dot marker for orientation
        dot_path = QPainterPath()
        dot_path.addEllipse(QPointF(margin / 2, margin / 2), 4, 4)
        self.addPath(dot_path, QPen(QColor(_BLUE)), QBrush(QColor(_BLUE)))

        for r in range(rows):
            for c in range(cols):
                # Only draw perimeter pins (BGA-style boundary)
                if 2 <= r < rows - 2 and 2 <= c < cols - 2:
                    continue
                x = margin + c * cell
                y = margin + r * cell
                pin_name = f"{chr(65 + r)}{c + 1}"
                rect = self.addRect(
                    QRectF(x + 2, y + 2, cell - 4, cell - 4),
                    QPen(QColor(_SURFACE1), 1),
                    QBrush(QColor(_SURFACE0)),
                )
                rect.setToolTip(pin_name)
                rect.setData(0, pin_name)
                rect.setAcceptDrops(True)
                self._pins[pin_name] = rect
                # Label
                lbl = self.addSimpleText(pin_name, font)
                lbl.setPos(x + 3, y + 3)
                lbl.setBrush(QBrush(QColor(_SUBTEXT)))

    def assign_pin(self, signal: str, pin_loc: str) -> None:
        # Unassign previous
        for loc, sig in list(self._assignments.items()):
            if sig == signal:
                if loc in self._pins:
                    self._pins[loc].setBrush(QBrush(QColor(_SURFACE0)))
                del self._assignments[loc]
                break
        if pin_loc in self._pins:
            self._pins[pin_loc].setBrush(QBrush(QColor(_BLUE)))
            self._pins[pin_loc].setToolTip(f"{pin_loc}: {signal}")
            self._assignments[pin_loc] = signal

    def get_assignments(self) -> dict[str, str]:
        return dict(self._assignments)


# ── Main Constraint Editor Panel ────────────────────────────────────────────

class ConstraintEditorPanel(QDockWidget):
    """Dock widget with tabbed constraint editor."""

    constraints_changed = Signal()

    def __init__(self, title: str = "Constraint Editor", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dark = True
        self._sdc_path: Path | None = None
        self._ports: list[dict[str, str]] = []
        self._clocks: list[dict[str, Any]] = []
        self._gen_clocks: list[dict[str, Any]] = []
        self._io_constraints: list[dict[str, Any]] = []
        self._pin_assignments: list[dict[str, Any]] = []
        self._exceptions: list[dict[str, Any]] = []
        self._syncing_sdc = False  # Guard against recursive sync

        # Main widget
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self._act_open = self._toolbar.addAction("Open SDC/XDC")
        self._act_open.triggered.connect(self._open_file)
        self._act_save = self._toolbar.addAction("Save")
        self._act_save.triggered.connect(self._save_file)
        self._act_save_as = self._toolbar.addAction("Save As...")
        self._act_save_as.triggered.connect(self._save_file_as)
        self._toolbar.addSeparator()
        self._act_load_verilog = self._toolbar.addAction("Load Verilog Ports")
        self._act_load_verilog.triggered.connect(self._load_verilog)
        main_layout.addWidget(self._toolbar)

        # Tabs
        self._tabs = QTabWidget()
        self._build_clocks_tab()
        self._build_io_tab()
        self._build_pin_tab()
        self._build_exceptions_tab()
        self._build_raw_sdc_tab()
        main_layout.addWidget(self._tabs)

        self.setWidget(main_widget)
        self._apply_theme()

    # ── Clocks Tab ───────────────────────────────────────────────────────

    def _build_clocks_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Clock")
        add_btn.clicked.connect(self._add_clock)
        btn_row.addWidget(add_btn)
        add_gen_btn = QPushButton("Add Generated Clock")
        add_gen_btn.clicked.connect(self._add_gen_clock)
        btn_row.addWidget(add_gen_btn)
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._delete_clock)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Clocks table
        self._clock_table = QTableWidget(0, 5)
        self._clock_table.setHorizontalHeaderLabels(
            ["Name", "Period (ns)", "Duty (%)", "Waveform", "Source"]
        )
        self._clock_table.horizontalHeader().setStretchLastSection(True)
        self._clock_table.setAlternatingRowColors(True)
        self._clock_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._clock_table.currentCellChanged.connect(self._on_clock_selected)
        layout.addWidget(self._clock_table, stretch=2)

        # Waveform preview
        self._clock_waveform = _ClockWaveformWidget()
        layout.addWidget(self._clock_waveform)

        self._tabs.addTab(tab, "Clocks")

    def _add_clock(self) -> None:
        port_names = [p["name"] for p in self._ports if p["direction"] == "input"]
        dlg = _AddClockDialog(self, port_names)
        dlg.setStyleSheet(self._dialog_qss())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            self._clocks.append(data)
            self._refresh_clock_table()
            self._sync_to_sdc()
            self.constraints_changed.emit()

    def _add_gen_clock(self) -> None:
        clock_names = [c["name"] for c in self._clocks]
        dlg = _AddGenClockDialog(self, clock_names)
        dlg.setStyleSheet(self._dialog_qss())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            self._gen_clocks.append(data)
            self._refresh_clock_table()
            self._sync_to_sdc()
            self.constraints_changed.emit()

    def _delete_clock(self) -> None:
        row = self._clock_table.currentRow()
        if row < 0:
            return
        if row < len(self._clocks):
            self._clocks.pop(row)
        else:
            gen_idx = row - len(self._clocks)
            if 0 <= gen_idx < len(self._gen_clocks):
                self._gen_clocks.pop(gen_idx)
        self._refresh_clock_table()
        self._sync_to_sdc()
        self.constraints_changed.emit()

    def _refresh_clock_table(self) -> None:
        self._clock_table.setRowCount(0)
        for c in self._clocks:
            row = self._clock_table.rowCount()
            self._clock_table.insertRow(row)
            self._clock_table.setItem(row, 0, QTableWidgetItem(c["name"]))
            self._clock_table.setItem(row, 1, QTableWidgetItem(f"{c['period']:.3f}"))
            self._clock_table.setItem(row, 2, QTableWidgetItem(f"{c['duty']:.1f}"))
            self._clock_table.setItem(row, 3, QTableWidgetItem(c.get("waveform", "")))
            self._clock_table.setItem(row, 4, QTableWidgetItem(c.get("source", "")))
        for gc in self._gen_clocks:
            row = self._clock_table.rowCount()
            self._clock_table.insertRow(row)
            name_item = QTableWidgetItem(f"{gc['name']} (gen)")
            name_item.setForeground(QColor(_TEAL))
            self._clock_table.setItem(row, 0, name_item)
            src_clk = gc.get("source", "")
            div = gc.get("divide_by", 1)
            mul = gc.get("multiply_by", 1)
            self._clock_table.setItem(row, 1, QTableWidgetItem(f"/{div} *{mul}"))
            self._clock_table.setItem(row, 2, QTableWidgetItem("50.0"))
            self._clock_table.setItem(row, 3, QTableWidgetItem(""))
            self._clock_table.setItem(row, 4, QTableWidgetItem(src_clk))

    def _on_clock_selected(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        if 0 <= row < len(self._clocks):
            c = self._clocks[row]
            self._clock_waveform.set_waveform(c["name"], c["period"], c["duty"])

    # ── I/O Timing Tab ───────────────────────────────────────────────────

    def _build_io_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        info = QLabel(
            "Edit input/output delay, driving cell, and load for each port. "
            "Load Verilog source to auto-populate ports."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {_SUBTEXT}; font-size: 10px; padding: 4px;")
        layout.addWidget(info)

        self._io_table = QTableWidget(0, 7)
        self._io_table.setHorizontalHeaderLabels([
            "Port", "Direction", "Clock Domain", "Input Delay (ns)",
            "Output Delay (ns)", "Driving Cell", "Load (pF)",
        ])
        self._io_table.horizontalHeader().setStretchLastSection(True)
        self._io_table.setAlternatingRowColors(True)
        self._io_table.cellChanged.connect(self._on_io_changed)
        layout.addWidget(self._io_table)

        self._tabs.addTab(tab, "I/O Timing")

    def _populate_io_table(self) -> None:
        self._io_table.blockSignals(True)
        self._io_table.setRowCount(0)
        for p in self._ports:
            row = self._io_table.rowCount()
            self._io_table.insertRow(row)
            name_item = QTableWidgetItem(p["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._io_table.setItem(row, 0, name_item)
            dir_item = QTableWidgetItem(p["direction"])
            dir_item.setFlags(dir_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if p["direction"] == "input":
                dir_item.setForeground(QColor(_GREEN))
            elif p["direction"] == "output":
                dir_item.setForeground(QColor(_PEACH))
            else:
                dir_item.setForeground(QColor(_YELLOW))
            self._io_table.setItem(row, 1, dir_item)

            # Clock domain combo
            clk_combo = QComboBox()
            clk_combo.addItem("")
            clk_combo.addItems([c["name"] for c in self._clocks])
            clk_combo.setEditable(True)
            self._io_table.setCellWidget(row, 2, clk_combo)

            self._io_table.setItem(row, 3, QTableWidgetItem("0.0"))
            self._io_table.setItem(row, 4, QTableWidgetItem("0.0"))

            # Driving cell combo
            drv_combo = QComboBox()
            drv_combo.addItem("")
            drv_combo.addItems(_SKY130_DRIVE_CELLS)
            drv_combo.setEditable(True)
            self._io_table.setCellWidget(row, 5, drv_combo)

            self._io_table.setItem(row, 6, QTableWidgetItem("0.0"))
        self._io_table.blockSignals(False)

    def _on_io_changed(self, row: int, col: int) -> None:
        self._sync_to_sdc()
        self.constraints_changed.emit()

    # ── Pin Assignment Tab ───────────────────────────────────────────────

    def _build_pin_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Signal list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Signals")
        lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {_BLUE};")
        ll.addWidget(lbl)
        self._signal_list = QTreeWidget()
        self._signal_list.setHeaderLabels(["Signal", "Direction"])
        self._signal_list.setAlternatingRowColors(True)
        ll.addWidget(self._signal_list)
        splitter.addWidget(left)

        # Pin grid
        self._pin_scene = _PinGridScene()
        self._pin_view = QGraphicsView(self._pin_scene)
        self._pin_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        splitter.addWidget(self._pin_view)

        # Pin assignment table
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl2 = QLabel("Pin Assignments")
        rl2.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        rl2.setStyleSheet(f"color: {_BLUE};")
        rl.addWidget(rl2)
        self._pin_table = QTableWidget(0, 4)
        self._pin_table.setHorizontalHeaderLabels(
            ["Signal", "Package Pin", "IO Standard", "Drive Strength"]
        )
        self._pin_table.horizontalHeader().setStretchLastSection(True)
        self._pin_table.setAlternatingRowColors(True)
        self._pin_table.cellChanged.connect(self._on_pin_changed)
        rl.addWidget(self._pin_table)

        assign_btn = QPushButton("Assign Selected Signal to Pin")
        assign_btn.clicked.connect(self._assign_pin_interactive)
        rl.addWidget(assign_btn)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        layout.addWidget(splitter)

        self._tabs.addTab(tab, "Pin Assignment")

    def _populate_signal_list(self) -> None:
        self._signal_list.clear()
        for p in self._ports:
            item = QTreeWidgetItem([p["name"], p["direction"]])
            if p["direction"] == "input":
                item.setForeground(1, QColor(_GREEN))
            elif p["direction"] == "output":
                item.setForeground(1, QColor(_PEACH))
            self._signal_list.addTopLevelItem(item)

    def _assign_pin_interactive(self) -> None:
        sig_item = self._signal_list.currentItem()
        if sig_item is None:
            return
        signal = sig_item.text(0)
        # Simple dialog for pin location
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Assign Pin for {signal}")
        fl = QFormLayout(dlg)
        pin_edit = QLineEdit()
        pin_edit.setPlaceholderText("e.g. A1, B3")
        fl.addRow("Package Pin:", pin_edit)
        io_combo = QComboBox()
        io_combo.addItems(_IO_STANDARDS)
        fl.addRow("IO Standard:", io_combo)
        drive_spin = QSpinBox()
        drive_spin.setRange(2, 24)
        drive_spin.setValue(8)
        drive_spin.setSuffix(" mA")
        fl.addRow("Drive Strength:", drive_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        fl.addRow(buttons)
        dlg.setStyleSheet(self._dialog_qss())

        if dlg.exec() == QDialog.DialogCode.Accepted:
            pin_loc = pin_edit.text().strip().upper()
            if pin_loc:
                self._pin_scene.assign_pin(signal, pin_loc)
                assignment = {
                    "signal": signal,
                    "pin": pin_loc,
                    "io_standard": io_combo.currentText(),
                    "drive": drive_spin.value(),
                }
                self._pin_assignments.append(assignment)
                self._refresh_pin_table()
                self._sync_to_sdc()
                self.constraints_changed.emit()

    def _refresh_pin_table(self) -> None:
        self._pin_table.blockSignals(True)
        self._pin_table.setRowCount(0)
        for a in self._pin_assignments:
            row = self._pin_table.rowCount()
            self._pin_table.insertRow(row)
            self._pin_table.setItem(row, 0, QTableWidgetItem(a["signal"]))
            self._pin_table.setItem(row, 1, QTableWidgetItem(a["pin"]))
            io_combo = QComboBox()
            io_combo.addItems(_IO_STANDARDS)
            idx = io_combo.findText(a.get("io_standard", "LVCMOS33"))
            if idx >= 0:
                io_combo.setCurrentIndex(idx)
            self._pin_table.setCellWidget(row, 2, io_combo)
            self._pin_table.setItem(row, 3, QTableWidgetItem(str(a.get("drive", 8))))
        self._pin_table.blockSignals(False)

    def _on_pin_changed(self, row: int, col: int) -> None:
        self._sync_to_sdc()
        self.constraints_changed.emit()

    # ── Timing Exceptions Tab ────────────────────────────────────────────

    def _build_exceptions_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Exception")
        add_btn.clicked.connect(self._add_exception)
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._delete_exception)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._exc_table = QTableWidget(0, 6)
        self._exc_table.setHorizontalHeaderLabels([
            "Type", "From", "Through", "To", "Value", "SDC Command",
        ])
        self._exc_table.horizontalHeader().setStretchLastSection(True)
        self._exc_table.setAlternatingRowColors(True)
        self._exc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._exc_table)

        self._tabs.addTab(tab, "Timing Exceptions")

    def _add_exception(self) -> None:
        port_names = [p["name"] for p in self._ports]
        clock_names = [c["name"] for c in self._clocks]
        all_names = port_names + clock_names
        dlg = _AddExceptionDialog(self, all_names, clock_names)
        dlg.setStyleSheet(self._dialog_qss())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            self._exceptions.append(data)
            self._refresh_exc_table()
            self._sync_to_sdc()
            self.constraints_changed.emit()

    def _delete_exception(self) -> None:
        row = self._exc_table.currentRow()
        if 0 <= row < len(self._exceptions):
            self._exceptions.pop(row)
            self._refresh_exc_table()
            self._sync_to_sdc()
            self.constraints_changed.emit()

    def _refresh_exc_table(self) -> None:
        self._exc_table.setRowCount(0)
        for e in self._exceptions:
            row = self._exc_table.rowCount()
            self._exc_table.insertRow(row)
            etype = e["type"]
            type_item = QTableWidgetItem(etype)
            color_map = {
                "false_path": _RED,
                "multicycle_path": _YELLOW,
                "max_delay": _PEACH,
                "min_delay": _TEAL,
            }
            type_item.setForeground(QColor(color_map.get(etype, _TEXT)))
            self._exc_table.setItem(row, 0, type_item)
            self._exc_table.setItem(row, 1, QTableWidgetItem(e.get("from", "")))
            self._exc_table.setItem(row, 2, QTableWidgetItem(e.get("through", "")))
            self._exc_table.setItem(row, 3, QTableWidgetItem(e.get("to", "")))
            val = ""
            if etype == "multicycle_path":
                val = str(e.get("multiplier", 2))
            elif etype in ("max_delay", "min_delay"):
                val = f"{e.get('value', 0):.3f} ns"
            self._exc_table.setItem(row, 4, QTableWidgetItem(val))
            self._exc_table.setItem(row, 5, QTableWidgetItem(self._exception_to_sdc(e)))

    def _exception_to_sdc(self, e: dict[str, Any]) -> str:
        etype = e["type"]
        from_spec = e.get("from", "")
        to_spec = e.get("to", "")
        through = e.get("through", "")
        parts: list[str] = []
        if etype == "false_path":
            parts.append("set_false_path")
        elif etype == "multicycle_path":
            parts.append(f"set_multicycle_path {e.get('multiplier', 2)}")
        elif etype == "max_delay":
            parts.append(f"set_max_delay {e.get('value', 0):.3f}")
        elif etype == "min_delay":
            parts.append(f"set_min_delay {e.get('value', 0):.3f}")
        if from_spec:
            parts.append(f"-from [get_ports {{{from_spec}}}]")
        if through:
            parts.append(f"-through [get_pins {{{through}}}]")
        if to_spec:
            parts.append(f"-to [get_ports {{{to_spec}}}]")
        return " ".join(parts)

    # ── Raw SDC Tab ──────────────────────────────────────────────────────

    def _build_raw_sdc_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        info = QLabel("Edit raw SDC commands. Changes here sync back to GUI tabs.")
        info.setStyleSheet(f"color: {_SUBTEXT}; font-size: 10px; padding: 4px;")
        layout.addWidget(info)

        self._sdc_editor = QPlainTextEdit()
        self._sdc_editor.setFont(QFont("Consolas", 10))
        self._sdc_editor.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {_CRUST}; color: {_TEXT}; "
            f"border: 1px solid {_SURFACE0}; selection-background-color: {_SURFACE1}; }}"
        )
        self._sdc_highlighter = _SDCSyntaxHighlighter(self._sdc_editor.document())
        self._sdc_editor.textChanged.connect(self._on_sdc_text_changed)
        layout.addWidget(self._sdc_editor)

        # Validation area
        self._validation_label = QLabel("")
        self._validation_label.setStyleSheet(
            f"color: {_GREEN}; font-size: 10px; padding: 4px;"
        )
        layout.addWidget(self._validation_label)

        self._tabs.addTab(tab, "Raw SDC")

    def _on_sdc_text_changed(self) -> None:
        if self._syncing_sdc:
            return
        text = self._sdc_editor.toPlainText()
        self._parse_sdc_text(text)
        self._validate_sdc(text)

    def _validate_sdc(self, text: str) -> None:
        errors: list[str] = []
        for i, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            valid_starts = [
                "create_clock", "create_generated_clock", "set_clock",
                "set_input_delay", "set_output_delay", "set_false_path",
                "set_multicycle_path", "set_max_delay", "set_min_delay",
                "set_input_transition", "set_load", "set_driving_cell",
                "set_property", "set_io_standard",
            ]
            if not any(line.startswith(vs) for vs in valid_starts):
                errors.append(f"Line {i}: Unknown command")
        if errors:
            self._validation_label.setStyleSheet(
                f"color: {_RED}; font-size: 10px; padding: 4px;"
            )
            self._validation_label.setText("; ".join(errors[:3]))
        else:
            self._validation_label.setStyleSheet(
                f"color: {_GREEN}; font-size: 10px; padding: 4px;"
            )
            self._validation_label.setText("SDC syntax OK")

    def _parse_sdc_text(self, text: str) -> None:
        """Parse raw SDC text and update internal state (simplified parser)."""
        new_clocks: list[dict[str, Any]] = []
        new_gen_clocks: list[dict[str, Any]] = []
        new_exceptions: list[dict[str, Any]] = []

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # create_clock
            m = re.match(
                r"create_clock\s+-name\s+(\w+)\s+-period\s+([\d.]+)(?:\s+-waveform\s+\{([\d.\s]+)\})?\s+(?:\[get_ports\s+\{?(\w+)\}?\]|(\w+))",
                line,
            )
            if m:
                period = float(m.group(2))
                duty = 50.0
                wf = m.group(3) or ""
                source = m.group(4) or m.group(5) or ""
                new_clocks.append({
                    "name": m.group(1),
                    "period": period,
                    "duty": duty,
                    "waveform": f"{{{wf}}}" if wf else "",
                    "source": source,
                })
                continue

            # create_generated_clock
            m = re.match(
                r"create_generated_clock\s+-name\s+(\w+)\s+-source\s+\[get_clocks\s+(\w+)\]\s+-divide_by\s+(\d+)",
                line,
            )
            if m:
                new_gen_clocks.append({
                    "name": m.group(1),
                    "source": m.group(2),
                    "divide_by": int(m.group(3)),
                    "multiply_by": 1,
                    "pin": "",
                })
                continue

            # set_false_path
            if line.startswith("set_false_path"):
                exc: dict[str, Any] = {"type": "false_path", "from": "", "through": "", "to": ""}
                fm = re.search(r"-from\s+\[get_ports?\s+\{?(\w+)\}?\]", line)
                if fm:
                    exc["from"] = fm.group(1)
                tm = re.search(r"-to\s+\[get_ports?\s+\{?(\w+)\}?\]", line)
                if tm:
                    exc["to"] = tm.group(1)
                new_exceptions.append(exc)
                continue

            # set_multicycle_path
            m2 = re.match(r"set_multicycle_path\s+(\d+)", line)
            if m2:
                exc2: dict[str, Any] = {"type": "multicycle_path", "multiplier": int(m2.group(1)),
                                         "from": "", "through": "", "to": "", "value": 0}
                fm2 = re.search(r"-from\s+\[get_ports?\s+\{?(\w+)\}?\]", line)
                if fm2:
                    exc2["from"] = fm2.group(1)
                tm2 = re.search(r"-to\s+\[get_ports?\s+\{?(\w+)\}?\]", line)
                if tm2:
                    exc2["to"] = tm2.group(1)
                new_exceptions.append(exc2)
                continue

        # Update state without re-syncing
        self._clocks = new_clocks
        self._gen_clocks = new_gen_clocks
        self._exceptions = new_exceptions
        self._refresh_clock_table()
        self._refresh_exc_table()

    # ── SDC generation ───────────────────────────────────────────────────

    def _generate_sdc(self) -> str:
        """Generate complete SDC text from GUI state."""
        lines: list[str] = []
        lines.append("# ── Clocks ──────────────────────────────────────────────")
        for c in self._clocks:
            wf = f" -waveform {c['waveform']}" if c.get("waveform") else ""
            src = c.get("source", "clk")
            lines.append(
                f"create_clock -name {c['name']} -period {c['period']:.3f}{wf} "
                f"[get_ports {{{src}}}]"
            )
        for gc in self._gen_clocks:
            parts = [f"create_generated_clock -name {gc['name']}"]
            parts.append(f"-source [get_clocks {gc['source']}]")
            if gc.get("divide_by", 1) > 1:
                parts.append(f"-divide_by {gc['divide_by']}")
            if gc.get("multiply_by", 1) > 1:
                parts.append(f"-multiply_by {gc['multiply_by']}")
            if gc.get("pin"):
                parts.append(f"[get_pins {{{gc['pin']}}}]")
            lines.append(" ".join(parts))

        # I/O timing from table
        lines.append("")
        lines.append("# ── I/O Timing ──────────────────────────────────────────")
        for row in range(self._io_table.rowCount()):
            name_item = self._io_table.item(row, 0)
            dir_item = self._io_table.item(row, 1)
            if not name_item or not dir_item:
                continue
            name = name_item.text()
            direction = dir_item.text()
            clk_widget = self._io_table.cellWidget(row, 2)
            clk_domain = clk_widget.currentText() if isinstance(clk_widget, QComboBox) else ""
            inp_delay = self._io_table.item(row, 3)
            out_delay = self._io_table.item(row, 4)
            drv_widget = self._io_table.cellWidget(row, 5)
            drv_cell = drv_widget.currentText() if isinstance(drv_widget, QComboBox) else ""
            load_item = self._io_table.item(row, 6)

            if direction == "input" and clk_domain:
                val = float(inp_delay.text()) if inp_delay else 0.0
                if val != 0.0:
                    lines.append(
                        f"set_input_delay -clock [get_clocks {{{clk_domain}}}] "
                        f"{val:.3f} [get_ports {{{name}}}]"
                    )
                if drv_cell:
                    lines.append(
                        f"set_driving_cell -lib_cell {drv_cell} [get_ports {{{name}}}]"
                    )
            elif direction == "output" and clk_domain:
                val = float(out_delay.text()) if out_delay else 0.0
                if val != 0.0:
                    lines.append(
                        f"set_output_delay -clock [get_clocks {{{clk_domain}}}] "
                        f"{val:.3f} [get_ports {{{name}}}]"
                    )
            if load_item:
                try:
                    load_val = float(load_item.text())
                    if load_val > 0:
                        lines.append(f"set_load {load_val:.3f} [get_ports {{{name}}}]")
                except ValueError:
                    pass

        # Pin assignments
        if self._pin_assignments:
            lines.append("")
            lines.append("# ── Pin Assignments ─────────────────────────────────────")
            for a in self._pin_assignments:
                lines.append(
                    f"set_property PACKAGE_PIN {a['pin']} [get_ports {{{a['signal']}}}]"
                )
                if a.get("io_standard"):
                    lines.append(
                        f"set_property IOSTANDARD {a['io_standard']} [get_ports {{{a['signal']}}}]"
                    )

        # Exceptions
        if self._exceptions:
            lines.append("")
            lines.append("# ── Timing Exceptions ───────────────────────────────────")
            for e in self._exceptions:
                lines.append(self._exception_to_sdc(e))

        return "\n".join(lines) + "\n"

    def _sync_to_sdc(self) -> None:
        """Sync GUI state to raw SDC editor."""
        self._syncing_sdc = True
        try:
            sdc_text = self._generate_sdc()
            self._sdc_editor.setPlainText(sdc_text)
            self._validate_sdc(sdc_text)
        finally:
            self._syncing_sdc = False

    # ── File operations ──────────────────────────────────────────────────

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Constraints", "",
            "SDC/XDC Files (*.sdc *.xdc);;All Files (*)",
        )
        if path:
            self.load_sdc(path)

    def load_sdc(self, filepath: str | Path) -> None:
        """Load an SDC/XDC constraint file."""
        self._sdc_path = Path(filepath)
        text = self._sdc_path.read_text(encoding="utf-8", errors="replace")
        self._syncing_sdc = True
        self._sdc_editor.setPlainText(text)
        self._syncing_sdc = False
        self._parse_sdc_text(text)
        self._validate_sdc(text)

    def _save_file(self) -> None:
        if self._sdc_path is None:
            self._save_file_as()
            return
        self._sdc_path.write_text(
            self._sdc_editor.toPlainText(), encoding="utf-8"
        )

    def _save_file_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Constraints", "constraints.sdc",
            "SDC Files (*.sdc);;XDC Files (*.xdc);;All Files (*)",
        )
        if path:
            self._sdc_path = Path(path)
            self._save_file()

    def _load_verilog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Verilog Source", "",
            "Verilog Files (*.v *.sv);;All Files (*)",
        )
        if path:
            self.load_ports_from_verilog(path)

    def load_ports_from_verilog(self, filepath: str | Path) -> None:
        """Parse a Verilog file and populate I/O tables with its ports."""
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
        self._ports = _parse_ports(text)
        self._populate_io_table()
        self._populate_signal_list()

    # ── Public API ───────────────────────────────────────────────────────

    def get_sdc_text(self) -> str:
        """Return current SDC text."""
        return self._sdc_editor.toPlainText()

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme()

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        bg = _BG if self._dark else "#f8f9fa"
        mantle = _MANTLE if self._dark else "#e9ecef"
        surface0 = _SURFACE0 if self._dark else "#dee2e6"
        text = _TEXT if self._dark else "#212529"
        subtext = _SUBTEXT if self._dark else "#495057"
        blue = _BLUE if self._dark else "#0d6efd"
        crust = _CRUST if self._dark else "#ffffff"

        base_qss = panel_tab_qss(self._dark)
        extra = f"""
            QDockWidget {{
                background-color: {bg};
                color: {text};
            }}
            QToolBar {{
                background: {mantle};
                border-bottom: 1px solid {surface0};
                spacing: 4px;
                padding: 2px;
            }}
            QToolButton {{
                color: {text};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 11px;
            }}
            QToolButton:hover {{
                background: {surface0};
                border-color: {surface0};
            }}
            QPlainTextEdit {{
                background-color: {crust};
                color: {text};
                border: 1px solid {surface0};
                font-family: Consolas, monospace;
                font-size: 11px;
            }}
        """
        self.setStyleSheet(base_qss + extra)

    def _dialog_qss(self) -> str:
        """Return QSS for dialog windows."""
        bg = _SURFACE0 if self._dark else "#f8f9fa"
        text = _TEXT if self._dark else "#212529"
        surface = _SURFACE1 if self._dark else "#dee2e6"
        return (
            f"QDialog {{ background-color: {bg}; color: {text}; }}"
            f"QLabel {{ color: {text}; }}"
            f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ "
            f"  background-color: {_CRUST if self._dark else '#ffffff'}; color: {text}; "
            f"  border: 1px solid {surface}; border-radius: 3px; padding: 3px 6px; }}"
            f"QPushButton {{ background-color: {surface}; color: {text}; "
            f"  border: 1px solid {surface}; border-radius: 4px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ border-color: {_BLUE if self._dark else '#0d6efd'}; }}"
        )

    # ── Context menu ─────────────────────────────────────────────────────

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {_SURFACE0}; color: {_TEXT}; border: 1px solid {_SURFACE1}; }}"
            f"QMenu::item:selected {{ background: {_SURFACE1}; }}"
        )
        menu.addAction("Open SDC/XDC...", self._open_file)
        menu.addAction("Save", self._save_file)
        menu.addAction("Save As...", self._save_file_as)
        menu.addSeparator()
        menu.addAction("Load Verilog Ports...", self._load_verilog)
        menu.addSeparator()
        menu.addAction("Add Clock...", self._add_clock)
        menu.addAction("Add Timing Exception...", self._add_exception)
        menu.exec(event.globalPos())
