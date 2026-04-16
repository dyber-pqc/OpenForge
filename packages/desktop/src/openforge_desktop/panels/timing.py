"""Vivado-quality timing analysis panel with slack histogram, path browser,
path detail view, and SDC constraint summary.

All widgets use the Catppuccin Mocha dark theme for a professional EDA aesthetic.
"""

from __future__ import annotations

import math
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from openforge.physical.sta_parser import StaReport

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

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

# Vivado timing colors
_CLR_VIOLATED: Final[str] = "#f38ba8"   # red -- negative slack
_CLR_NEAR_CRIT: Final[str] = "#f9e2af"  # yellow -- <10% margin
_CLR_MET: Final[str] = "#a6e3a1"        # green -- met
_CLR_BLUE: Final[str] = "#89b4fa"
_CLR_MAUVE: Final[str] = "#cba6f7"
_CLR_PEACH: Final[str] = "#fab387"
_CLR_TEAL: Final[str] = "#94e2d5"

_ALT_ROW: Final[str] = "#1a1a2e"


# ── Shared helpers ──────────────────────────────────────────────────────────


def _text_item(text: str, color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    return item


def _numeric_item(value: float | int, fmt: str = "{:.3f}", color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(fmt.format(value))
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item.setData(Qt.ItemDataRole.UserRole, value)
    return item


def _slack_color(slack: float, period: float = 5.0) -> str:
    """Return colour string based on slack value."""
    if slack < 0:
        return _CLR_VIOLATED
    margin = slack / period if period > 0 else 1.0
    return _CLR_NEAR_CRIT if margin < 0.1 else _CLR_MET


def _header_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_CLR_BLUE}; font-weight: bold; font-size: 13px; padding: 4px 0px;")
    return lbl


def _configure_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(f"QTableWidget {{ alternate-background-color: {_ALT_ROW}; }}")
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)


# ── Big Number Display ──────────────────────────────────────────────────────


class _BigNumberWidget(QWidget):
    """Large coloured number display for WNS / TNS."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(150)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px; font-weight: bold;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._value = QLabel("--")
        self._value.setStyleSheet(f"color: {_CLR_MET}; font-size: 22px; font-weight: bold;")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value)

        self._unit = QLabel("ns")
        self._unit.setStyleSheet(f"color: {_SUBTEXT}; font-size: 10px;")
        self._unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._unit)

    def set_value(self, value: float, unit: str = "ns") -> None:
        color = _slack_color(value)
        sign = "+" if value >= 0 else ""
        self._value.setText(f"{sign}{value:.3f}")
        self._value.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
        self._unit.setText(unit)


# ── Slack Histogram Widget ──────────────────────────────────────────────────


class _SlackHistogram(QWidget):
    """Custom QPainter histogram: X = slack bins, Y = endpoint count."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._bins: list[tuple[float, float, int]] = []  # (bin_start, bin_end, count)

    def set_data(self, bins: list[tuple[float, float, int]]) -> None:
        self._bins = bins
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._bins:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_l, margin_r, margin_t, margin_b = 50, 10, 10, 30
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b

        max_count = max(c for _, _, c in self._bins) or 1
        n = len(self._bins)
        bar_w = max(2, plot_w / n - 1)

        # Axes
        axis_pen = QPen(QColor(_SURFACE1), 1)
        painter.setPen(axis_pen)
        painter.drawLine(margin_l, margin_t, margin_l, h - margin_b)
        painter.drawLine(margin_l, h - margin_b, w - margin_r, h - margin_b)

        # Zero line
        if self._bins and self._bins[0][0] < 0 and self._bins[-1][1] > 0:
            # Find zero position
            min_val = self._bins[0][0]
            max_val = self._bins[-1][1]
            zero_x = margin_l + (-min_val) / (max_val - min_val) * plot_w
            pen = QPen(QColor(_OVERLAY0), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(zero_x), margin_t, int(zero_x), h - margin_b)

        # Bars
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        for i, (bin_start, bin_end, count) in enumerate(self._bins):
            x = margin_l + i * (plot_w / n)
            bar_h = int(count / max_count * plot_h) if max_count > 0 else 0
            y = h - margin_b - bar_h

            mid = (bin_start + bin_end) / 2
            color = QColor(_CLR_VIOLATED if mid < 0 else (_CLR_NEAR_CRIT if mid < 0.5 else _CLR_MET))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(x + 1, y, bar_w, bar_h))

            # X-axis label (every few bins)
            if i % max(1, n // 8) == 0 or i == n - 1:
                painter.setPen(QColor(_SUBTEXT))
                painter.drawText(QRectF(x - 10, h - margin_b + 2, 40, 16),
                                 Qt.AlignmentFlag.AlignCenter, f"{bin_start:.1f}")

        # Y-axis labels
        painter.setPen(QColor(_SUBTEXT))
        for frac in (0, 0.5, 1.0):
            yy = h - margin_b - int(frac * plot_h)
            val = int(frac * max_count)
            painter.drawText(QRectF(0, yy - 8, margin_l - 4, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             str(val))

        # Title
        painter.setPen(QColor(_SUBTEXT))
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(margin_l, margin_t - 2, plot_w, 14),
                         Qt.AlignmentFlag.AlignCenter, "Slack Distribution (ns)")


# ── Summary Tab ─────────────────────────────────────────────────────────────


class _SummaryTab(QWidget):
    """Timing summary: WNS/TNS, clock domains, slack histogram."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # WNS / TNS big numbers
        numbers_row = QHBoxLayout()
        self._wns_setup = _BigNumberWidget("WNS (Setup)")
        self._tns_setup = _BigNumberWidget("TNS (Setup)")
        self._wns_hold = _BigNumberWidget("WNS (Hold)")
        self._tns_hold = _BigNumberWidget("TNS (Hold)")
        for w in (self._wns_setup, self._tns_setup, self._wns_hold, self._tns_hold):
            numbers_row.addWidget(w)
        root.addLayout(numbers_row)

        # Clock domain table
        root.addWidget(_header_label("Clock Domains"))
        self._clock_table = QTableWidget(0, 6)
        self._clock_table.setHorizontalHeaderLabels([
            "Clock", "Period (ns)", "Frequency (MHz)", "WNS (ns)", "TNS (ns)", "Endpoints",
        ])
        _configure_table(self._clock_table)
        self._clock_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._clock_table.setMaximumHeight(160)
        root.addWidget(self._clock_table)

        # Slack histogram
        root.addWidget(_header_label("Slack Histogram"))
        self._histogram = _SlackHistogram()
        root.addWidget(self._histogram, 1)

    def set_summary(
        self,
        wns_setup: float,
        tns_setup: float,
        wns_hold: float,
        tns_hold: float,
    ) -> None:
        self._wns_setup.set_value(wns_setup)
        self._tns_setup.set_value(tns_setup)
        self._wns_hold.set_value(wns_hold)
        self._tns_hold.set_value(tns_hold)

    def set_clocks(self, clocks: list[dict]) -> None:
        """Populate from list of dicts: name, period, frequency, wns, tns, endpoints."""
        self._clock_table.setRowCount(0)
        for c in clocks:
            row = self._clock_table.rowCount()
            self._clock_table.insertRow(row)
            self._clock_table.setItem(row, 0, _text_item(c.get("name", "")))
            period = c.get("period", 0.0)
            self._clock_table.setItem(row, 1, _numeric_item(period, "{:.2f}"))
            self._clock_table.setItem(row, 2, _numeric_item(c.get("frequency", 0.0), "{:.1f}"))
            wns = c.get("wns", 0.0)
            self._clock_table.setItem(row, 3, _numeric_item(wns, "{:.3f}", _slack_color(wns, period)))
            tns = c.get("tns", 0.0)
            tns_color = _CLR_VIOLATED if tns < 0 else _CLR_MET
            self._clock_table.setItem(row, 4, _numeric_item(tns, "{:.3f}", tns_color))
            self._clock_table.setItem(row, 5, _numeric_item(c.get("endpoints", 0), "{:.0f}"))

    def set_histogram(self, bins: list[tuple[float, float, int]]) -> None:
        self._histogram.set_data(bins)


# ── Paths Tab ───────────────────────────────────────────────────────────────


class _PathsTab(QWidget):
    """Timing paths tree sorted by slack."""

    path_selected = Signal(dict)  # emitted when user clicks a path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        # Filter bar
        filter_row = QHBoxLayout()

        self._btn_violated = QPushButton("Violated Only")
        self._btn_violated.setCheckable(True)
        self._btn_violated.setFixedHeight(26)
        self._btn_violated.clicked.connect(self._repopulate)
        filter_row.addWidget(self._btn_violated)

        filter_row.addWidget(QLabel("Top N:"))
        self._spin_top = QSpinBox()
        self._spin_top.setRange(1, 10000)
        self._spin_top.setValue(100)
        self._spin_top.setFixedWidth(80)
        self._spin_top.valueChanged.connect(self._repopulate)
        filter_row.addWidget(self._spin_top)

        filter_row.addWidget(QLabel("Clock:"))
        self._clock_combo = QComboBox()
        self._clock_combo.addItem("All Clocks")
        self._clock_combo.currentTextChanged.connect(self._repopulate)
        filter_row.addWidget(self._clock_combo)

        filter_row.addStretch()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search cell/net...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._repopulate)
        filter_row.addWidget(self._search)

        root.addLayout(filter_row)

        # Path tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["#", "Slack (ns)", "Start Point", "End Point",
                                     "Path Delay (ns)", "Levels", "Clock"])
        self._tree.setColumnCount(7)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"QTreeWidget {{ alternate-background-color: {_ALT_ROW}; }}")
        self._tree.setAnimated(True)
        self._tree.setIndentation(20)
        self._tree.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self._tree)

        self._paths: list[dict] = []

    def set_paths(self, paths: list[dict], clocks: list[str] | None = None) -> None:
        """Populate from list of dicts: slack, start, end, delay, levels, clock, stages."""
        self._paths = paths
        if clocks:
            self._clock_combo.clear()
            self._clock_combo.addItem("All Clocks")
            for c in clocks:
                self._clock_combo.addItem(c)
        self._repopulate()

    def _repopulate(self) -> None:
        self._tree.clear()
        violated_only = self._btn_violated.isChecked()
        top_n = self._spin_top.value()
        clock_filter = self._clock_combo.currentText()
        search_text = self._search.text().lower()

        filtered = self._paths
        if violated_only:
            filtered = [p for p in filtered if p.get("slack", 0) < 0]
        if clock_filter != "All Clocks":
            filtered = [p for p in filtered if p.get("clock", "") == clock_filter]
        if search_text:
            filtered = [p for p in filtered if
                        search_text in p.get("start", "").lower() or
                        search_text in p.get("end", "").lower()]
        filtered = filtered[:top_n]

        for i, path in enumerate(filtered):
            slack = path.get("slack", 0.0)
            color = QColor(_slack_color(slack))

            item = QTreeWidgetItem()
            item.setText(0, str(i + 1))
            item.setText(1, f"{slack:.3f}")
            item.setForeground(1, color)
            font = QFont()
            font.setBold(True)
            item.setFont(1, font)
            item.setText(2, path.get("start", ""))
            item.setText(3, path.get("end", ""))
            item.setText(4, f"{path.get('delay', 0.0):.3f}")
            item.setText(5, str(path.get("levels", 0)))
            item.setText(6, path.get("clock", ""))
            item.setData(0, Qt.ItemDataRole.UserRole, path)

            # Add stages as children
            for stage in path.get("stages", []):
                child = QTreeWidgetItem()
                child.setText(0, "")
                child.setText(1, "")
                child.setText(2, stage.get("cell", ""))
                child.setText(3, stage.get("type", ""))
                child.setText(4, f"{stage.get('delay', 0.0):.3f}")
                child.setText(5, f"{stage.get('arrival', 0.0):.3f}")
                child.setText(6, stage.get("transition", ""))
                child.setForeground(2, QColor(_SUBTEXT))
                child.setForeground(3, QColor(_SUBTEXT))
                item.addChild(child)

            self._tree.addTopLevelItem(item)

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        path_data = item.data(0, Qt.ItemDataRole.UserRole)
        if path_data:
            self.path_selected.emit(path_data)


# ── Path Detail Tab ─────────────────────────────────────────────────────────


class _PathDetailTab(QWidget):
    """Detailed view for a selected timing path."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Header
        self._header = QLabel("Select a timing path to view details")
        self._header.setStyleSheet(f"color: {_SUBTEXT}; font-size: 14px;")
        self._header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._header)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)

        # Left: path breakdown table
        table_container = QWidget()
        tc_layout = QVBoxLayout(table_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.addWidget(_header_label("Path Breakdown"))

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Cell", "Type", "Delay (ns)", "Arrival (ns)", "Transition"])
        _configure_table(self._table)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tc_layout.addWidget(self._table)
        body.addWidget(table_container)

        # Right: delay breakdown pie and path diagram
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(_header_label("Delay Breakdown"))
        self._delay_pie = _DelayPieChart()
        rl.addWidget(self._delay_pie)
        rl.addWidget(_header_label("Path Diagram"))
        self._path_diagram = _PathDiagram()
        rl.addWidget(self._path_diagram, 1)
        body.addWidget(right)

        body.setSizes([400, 300])
        root.addWidget(body, 1)

    def show_path(self, path: dict) -> None:
        slack = path.get("slack", 0.0)
        color = _slack_color(slack)
        start = path.get("start", "?")
        end = path.get("end", "?")
        self._header.setText(
            f'<span style="color:{_TEXT};">{start}</span>'
            f' <span style="color:{_SUBTEXT};">\u2192</span> '
            f'<span style="color:{_TEXT};">{end}</span>'
            f'  <span style="color:{color}; font-weight:bold;">({slack:+.3f} ns)</span>'
        )

        # Populate table
        self._table.setRowCount(0)
        stages = path.get("stages", [])
        total_cell_delay = 0.0
        total_wire_delay = 0.0
        cell_names: list[str] = []

        for stage in stages:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, _text_item(stage.get("cell", "")))
            stype = stage.get("type", "")
            self._table.setItem(row, 1, _text_item(stype, _SUBTEXT))
            delay = stage.get("delay", 0.0)
            self._table.setItem(row, 2, _numeric_item(delay, "{:.3f}"))
            self._table.setItem(row, 3, _numeric_item(stage.get("arrival", 0.0), "{:.3f}"))
            self._table.setItem(row, 4, _text_item(stage.get("transition", ""), _SUBTEXT))

            if "wire" in stype.lower() or "net" in stype.lower():
                total_wire_delay += delay
            else:
                total_cell_delay += delay
            cell_names.append(stage.get("cell", ""))

        # Pie chart
        self._delay_pie.set_data(total_cell_delay, total_wire_delay)

        # Path diagram
        self._path_diagram.set_cells(cell_names)


class _DelayPieChart(QWidget):
    """Simple two-segment pie: cell delay vs wire delay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(120)
        self._cell_delay = 0.0
        self._wire_delay = 0.0

    def set_data(self, cell_delay: float, wire_delay: float) -> None:
        self._cell_delay = cell_delay
        self._wire_delay = wire_delay
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        total = self._cell_delay + self._wire_delay
        if total <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = self.height()
        size = h - 20
        rect = QRectF(10, 10, size, size)

        # Cell delay slice
        cell_span = int(self._cell_delay / total * 360 * 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_CLR_BLUE))
        painter.drawPie(rect, 90 * 16, cell_span)

        # Wire delay slice
        painter.setBrush(QColor(_CLR_PEACH))
        painter.drawPie(rect, 90 * 16 + cell_span, 360 * 16 - cell_span)

        # Legend
        lx = size + 30
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)

        painter.setBrush(QColor(_CLR_BLUE))
        painter.drawRect(QRectF(lx, 20, 12, 12))
        painter.setPen(QColor(_TEXT))
        cell_pct = self._cell_delay / total * 100
        painter.drawText(QPointF(lx + 18, 31), f"Cell: {self._cell_delay:.3f} ns ({cell_pct:.0f}%)")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_CLR_PEACH))
        painter.drawRect(QRectF(lx, 44, 12, 12))
        painter.setPen(QColor(_TEXT))
        wire_pct = self._wire_delay / total * 100
        painter.drawText(QPointF(lx + 18, 55), f"Wire: {self._wire_delay:.3f} ns ({wire_pct:.0f}%)")

        painter.setPen(QColor(_SUBTEXT))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QPointF(lx, 80), f"Total: {total:.3f} ns")


class _PathDiagram(QWidget):
    """Simplified schematic showing cells in the timing path as a chain."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(60)
        self._cells: list[str] = []

    def set_cells(self, cells: list[str]) -> None:
        self._cells = [c for c in cells if c]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._cells:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        n = len(self._cells)
        w = self.width()
        h = self.height()
        margin = 20
        cell_w = min(80, (w - 2 * margin) / max(n, 1) * 0.7)
        cell_h = 30
        gap = (w - 2 * margin - n * cell_w) / max(n - 1, 1) if n > 1 else 0
        y = (h - cell_h) / 2

        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        for i, name in enumerate(self._cells):
            x = margin + i * (cell_w + gap)

            # Box
            color = QColor(_CLR_BLUE)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 40)))
            painter.drawRoundedRect(QRectF(x, y, cell_w, cell_h), 4, 4)

            # Label (truncated)
            painter.setPen(QColor(_TEXT))
            short = name if len(name) <= 10 else name[:8] + ".."
            painter.drawText(QRectF(x, y, cell_w, cell_h),
                             Qt.AlignmentFlag.AlignCenter, short)

            # Arrow to next
            if i < n - 1:
                ax1 = x + cell_w
                ax2 = margin + (i + 1) * (cell_w + gap)
                ay = y + cell_h / 2
                painter.setPen(QPen(QColor(_OVERLAY0), 1))
                painter.drawLine(QPointF(ax1, ay), QPointF(ax2, ay))
                # Arrowhead
                painter.drawLine(QPointF(ax2 - 5, ay - 3), QPointF(ax2, ay))
                painter.drawLine(QPointF(ax2 - 5, ay + 3), QPointF(ax2, ay))


# ── Constraints Tab ─────────────────────────────────────────────────────────


class _ConstraintsTab(QWidget):
    """SDC constraint summary and coverage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Coverage bar
        cov_group = QGroupBox("Constraint Coverage")
        cov_layout = QHBoxLayout(cov_group)
        self._cov_bar = QProgressBar()
        self._cov_bar.setRange(0, 100)
        self._cov_bar.setValue(0)
        self._cov_bar.setFormat("%v%")
        cov_layout.addWidget(self._cov_bar)
        self._cov_label = QLabel("0 / 0 endpoints constrained")
        self._cov_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        cov_layout.addWidget(self._cov_label)
        root.addWidget(cov_group)

        # Clock definitions
        root.addWidget(_header_label("Clock Definitions"))
        self._clock_table = QTableWidget(0, 4)
        self._clock_table.setHorizontalHeaderLabels(["Clock Name", "Source", "Period (ns)", "Waveform"])
        _configure_table(self._clock_table)
        self._clock_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._clock_table.setMaximumHeight(120)
        root.addWidget(self._clock_table)

        # I/O delay constraints
        root.addWidget(_header_label("I/O Delay Constraints"))
        self._io_table = QTableWidget(0, 4)
        self._io_table.setHorizontalHeaderLabels(["Port", "Direction", "Delay (ns)", "Clock"])
        _configure_table(self._io_table)
        self._io_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._io_table.setMaximumHeight(120)
        root.addWidget(self._io_table)

        # Exceptions
        root.addWidget(_header_label("Timing Exceptions"))
        self._exc_table = QTableWidget(0, 3)
        self._exc_table.setHorizontalHeaderLabels(["Type", "From", "To"])
        _configure_table(self._exc_table)
        self._exc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._exc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._exc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._exc_table)

    def set_coverage(self, covered: int, total: int) -> None:
        pct = int(covered / total * 100) if total > 0 else 0
        self._cov_bar.setValue(pct)
        self._cov_label.setText(f"{covered:,} / {total:,} endpoints constrained")

    def set_clocks(self, clocks: list[dict]) -> None:
        """Populate from dicts: name, source, period, waveform."""
        self._clock_table.setRowCount(0)
        for c in clocks:
            row = self._clock_table.rowCount()
            self._clock_table.insertRow(row)
            self._clock_table.setItem(row, 0, _text_item(c.get("name", "")))
            self._clock_table.setItem(row, 1, _text_item(c.get("source", ""), _SUBTEXT))
            self._clock_table.setItem(row, 2, _numeric_item(c.get("period", 0.0), "{:.2f}"))
            self._clock_table.setItem(row, 3, _text_item(c.get("waveform", ""), _SUBTEXT))

    def set_io_delays(self, delays: list[dict]) -> None:
        self._io_table.setRowCount(0)
        for d in delays:
            row = self._io_table.rowCount()
            self._io_table.insertRow(row)
            self._io_table.setItem(row, 0, _text_item(d.get("port", "")))
            self._io_table.setItem(row, 1, _text_item(d.get("direction", ""), _SUBTEXT))
            self._io_table.setItem(row, 2, _numeric_item(d.get("delay", 0.0), "{:.2f}"))
            self._io_table.setItem(row, 3, _text_item(d.get("clock", ""), _SUBTEXT))

    def set_exceptions(self, exceptions: list[dict]) -> None:
        self._exc_table.setRowCount(0)
        for e in exceptions:
            row = self._exc_table.rowCount()
            self._exc_table.insertRow(row)
            etype = e.get("type", "")
            color = _CLR_MAUVE if "false" in etype.lower() else _CLR_PEACH
            self._exc_table.setItem(row, 0, _text_item(etype, color))
            self._exc_table.setItem(row, 1, _text_item(e.get("from", "")))
            self._exc_table.setItem(row, 2, _text_item(e.get("to", "")))


# ── Main TimingPanel ────────────────────────────────────────────────────────


class TimingPanel(QDockWidget):
    """Dock widget with tabbed timing analysis: Summary, Paths, Detail, Constraints."""

    def __init__(self, title: str = "Timing Analysis", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {_BG};
            }}
            QTabBar::tab {{
                background-color: {_SURFACE0};
                color: {_SUBTEXT};
                border: none;
                padding: 6px 16px;
                font-size: 11px;
                margin-right: 1px;
                min-width: 60px;
            }}
            QTabBar::tab:selected {{
                background-color: {_BG};
                color: {_TEXT};
                border-bottom: 2px solid {_CLR_BLUE};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {_SURFACE1};
                color: {_TEXT};
            }}
            QGroupBox {{
                background-color: {_MANTLE};
                border: 1px solid {_SURFACE0};
                border-radius: 4px;
                margin-top: 14px;
                padding: 10px 8px 8px 8px;
                font-size: 11px;
                font-weight: bold;
                color: {_CLR_BLUE};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
            }}
            QPushButton {{
                background-color: {_SURFACE0};
                color: {_TEXT};
                border: 1px solid {_SURFACE1};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {_SURFACE1};
                border-color: {_CLR_BLUE};
            }}
            QPushButton:pressed {{
                background-color: {_SURFACE2};
            }}
            QPushButton:checked {{
                background-color: {_CLR_BLUE};
                color: {_CRUST};
                border-color: {_CLR_BLUE};
            }}
            QLineEdit, QComboBox, QSpinBox {{
                background-color: {_SURFACE0};
                color: {_TEXT};
                border: 1px solid {_SURFACE1};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 11px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border-color: {_CLR_BLUE};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {_SURFACE0};
                color: {_TEXT};
                selection-background-color: {_SURFACE1};
                border: 1px solid {_SURFACE1};
            }}
            QLabel {{
                color: {_TEXT};
                font-size: 11px;
            }}
            QProgressBar {{
                background-color: {_SURFACE0};
                border: none;
                border-radius: 3px;
                text-align: center;
                color: {_TEXT};
                font-size: 10px;
                max-height: 18px;
            }}
            QProgressBar::chunk {{
                background-color: {_CLR_BLUE};
                border-radius: 3px;
            }}
            QSplitter::handle {{
                background-color: {_SURFACE0};
                height: 2px;
                width: 2px;
            }}
            QHeaderView::section {{
                background-color: {_MANTLE};
                color: {_SUBTEXT};
                border: none;
                border-right: 1px solid {_SURFACE0};
                border-bottom: 1px solid {_SURFACE0};
                padding: 4px 6px;
                font-size: 11px;
                font-weight: bold;
            }}
        """)
        self._summary_tab = _SummaryTab()
        self._paths_tab = _PathsTab()
        self._detail_tab = _PathDetailTab()
        self._constraints_tab = _ConstraintsTab()

        # Wrap each tab in a scroll area so content scrolls when dock is short
        from PySide6.QtWidgets import QScrollArea
        def _scrollable(widget: QWidget) -> QScrollArea:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setWidget(widget)
            return scroll

        self._tabs.addTab(_scrollable(self._summary_tab), "Summary")
        self._tabs.addTab(_scrollable(self._paths_tab), "Paths")
        self._tabs.addTab(_scrollable(self._detail_tab), "Path Detail")
        self._tabs.addTab(_scrollable(self._constraints_tab), "Constraints")

        self.setWidget(self._tabs)

        # Wire path selection to detail tab
        self._paths_tab.path_selected.connect(self._on_path_selected)

    def _on_path_selected(self, path: dict) -> None:
        self._detail_tab.show_path(path)
        self._tabs.setCurrentWidget(self._detail_tab)

    # ── Public API ────────────────────────────────────────────────────

    def set_theme(self, dark: bool) -> None:
        """Switch panel QSS between dark and light themes."""
        from openforge_desktop.panels._theme import panel_tab_qss
        self._tabs.setStyleSheet(panel_tab_qss(dark))

    @property
    def summary(self) -> _SummaryTab:
        return self._summary_tab

    @property
    def paths(self) -> _PathsTab:
        return self._paths_tab

    @property
    def detail(self) -> _PathDetailTab:
        return self._detail_tab

    @property
    def constraints(self) -> _ConstraintsTab:
        return self._constraints_tab

    def update_results(self, results: dict) -> None:
        """Populate all tabs from a timing results dictionary.

        Expected keys:
            - ``wns_setup``, ``tns_setup``, ``wns_hold``, ``tns_hold``: float
            - ``clocks``: list of dicts for clock domain table
            - ``histogram``: list of (bin_start, bin_end, count) tuples
            - ``paths``: list of path dicts
            - ``clock_names``: list of clock name strings
            - ``coverage``: dict with ``covered`` and ``total``
            - ``sdc_clocks``: list of SDC clock dicts
            - ``io_delays``: list of I/O delay dicts
            - ``exceptions``: list of timing exception dicts
        """
        # Summary
        self._summary_tab.set_summary(
            results.get("wns_setup", 0),
            results.get("tns_setup", 0),
            results.get("wns_hold", 0),
            results.get("tns_hold", 0),
        )
        clocks = results.get("clocks", [])
        if clocks:
            self._summary_tab.set_clocks(clocks)
        histogram = results.get("histogram", [])
        if histogram:
            self._summary_tab.set_histogram(histogram)

        # Paths
        paths = results.get("paths", [])
        clock_names = results.get("clock_names")
        if paths:
            self._paths_tab.set_paths(paths, clock_names)

        # Constraints
        cov = results.get("coverage", {})
        if cov:
            self._constraints_tab.set_coverage(cov.get("covered", 0), cov.get("total", 0))
        sdc_clocks = results.get("sdc_clocks", [])
        if sdc_clocks:
            self._constraints_tab.set_clocks(sdc_clocks)
        io_delays = results.get("io_delays", [])
        if io_delays:
            self._constraints_tab.set_io_delays(io_delays)
        exceptions = results.get("exceptions", [])
        if exceptions:
            self._constraints_tab.set_exceptions(exceptions)

    def update_from_timing_result(self, result: "TimingResult") -> None:
        """Convert a core ``TimingResult`` to the panel display format.

        Parameters
        ----------
        result:
            A ``TimingResult`` from ``openforge.physical.timing``.
        """
        # Build path dicts from TimingPath objects
        paths = []
        for p in result.paths:
            stages = [
                {
                    "cell": s.cell_name,
                    "type": s.cell_type,
                    "delay": s.delay_ns,
                    "arrival": s.arrival_ns,
                    "transition": "",
                }
                for s in p.stages
            ]
            paths.append({
                "slack": p.slack_ns,
                "start": p.start_point,
                "end": p.end_point,
                "delay": p.delay_ns,
                "levels": len(p.stages),
                "clock": "",
                "stages": stages,
            })

        # Build clock domain list from clocks dict
        clocks = []
        clock_names = []
        for clk_name, clk_info in result.clocks.items():
            clock_names.append(clk_name)
            period = clk_info.get("period", 0.0)
            freq = 1000.0 / period if period > 0 else 0.0
            clocks.append({
                "name": clk_name,
                "period": period,
                "frequency": freq,
                "wns": clk_info.get("wns", 0.0),
                "tns": clk_info.get("tns", 0.0),
                "endpoints": int(clk_info.get("endpoints", 0)),
            })

        # Build histogram from path slacks
        if paths:
            slack_values = [p["slack"] for p in paths]
            min_s = min(slack_values)
            max_s = max(slack_values)
            bin_width = max((max_s - min_s) / 12.0, 0.1)
            histogram = []
            for i in range(12):
                lo = min_s + i * bin_width
                hi = lo + bin_width
                count = sum(1 for s in slack_values if lo <= s < hi)
                histogram.append((lo, hi, count))
        else:
            histogram = []

        # Separate setup/hold WNS/TNS (TimingResult stores aggregate)
        data = {
            "wns_setup": result.wns,
            "tns_setup": result.tns,
            "wns_hold": 0.0,
            "tns_hold": 0.0,
            "clocks": clocks,
            "clock_names": clock_names,
            "histogram": histogram,
            "paths": paths,
            "coverage": {
                "covered": result.num_endpoints,
                "total": result.num_endpoints,
            },
        }
        self.update_results(data)

    def update_from_sta_report(self, report: "StaReport") -> None:
        """Update all displays from a real :class:`StaReport`.

        This is the preferred entry point now that ``sta_parser`` produces
        structured timing data. It populates the summary tiles, the per-clock
        table, the slack histogram, and the paths tab from the parsed report.
        """
        # ----- summary tiles ---------------------------------------------
        self._summary_tab.set_summary(
            wns_setup=report.wns,
            tns_setup=report.tns,
            wns_hold=report.whs,
            tns_hold=report.ths,
        )

        # ----- per-clock table -------------------------------------------
        clock_rows: list[dict] = []
        clock_names: list[str] = []
        for clock_name, paths in report.paths_by_clock().items():
            setups = [p for p in paths if p.path_type == "max"]
            worst_setup = min((p.slack_ns for p in setups), default=0.0)
            tns = sum(p.slack_ns for p in setups if p.slack_ns < 0)
            clock_info = report.get_clock(clock_name)
            period = clock_info.period_ns if clock_info else 10.0
            freq = 1000.0 / period if period > 0 else 0.0
            clock_rows.append(
                {
                    "name": clock_name,
                    "period": period,
                    "frequency": freq,
                    "wns": worst_setup,
                    "tns": tns,
                    "endpoints": len({p.endpoint for p in paths if p.endpoint}),
                }
            )
            clock_names.append(clock_name)
        if clock_rows:
            self._summary_tab.set_clocks(clock_rows)

        # ----- slack histogram -------------------------------------------
        bins: list[tuple[float, float, int]] = []
        if report.paths:
            slacks = [p.slack_ns for p in report.paths]
            s_min, s_max = min(slacks), max(slacks)
            n_bins = 20
            if s_max <= s_min:
                bins = [(s_min - 0.5, s_max + 0.5, len(slacks))]
            else:
                bin_w = (s_max - s_min) / n_bins
                for i in range(n_bins):
                    lo = s_min + i * bin_w
                    hi = lo + bin_w
                    if i == n_bins - 1:
                        count = sum(1 for s in slacks if lo <= s <= hi)
                    else:
                        count = sum(1 for s in slacks if lo <= s < hi)
                    bins.append((lo, hi, count))
        self._summary_tab.set_histogram(bins)

        # ----- detail paths tab (top 50 worst) ---------------------------
        worst_paths = sorted(report.paths, key=lambda p: p.slack_ns)[:50]
        paths_data: list[dict] = []
        for p in worst_paths:
            stages_data: list[dict] = []
            for s in p.data_path:
                stages_data.append(
                    {
                        "cell": s.cell_instance or s.pin_name,
                        "type": s.cell_type,
                        "pin": s.pin_name,
                        "delay": s.delay_ns,
                        "arrival": s.cumulative_ns,
                        "cumulative": s.cumulative_ns,
                        "transition": s.edge,
                    }
                )
            paths_data.append(
                {
                    "startpoint": p.startpoint,
                    "endpoint": p.endpoint,
                    "start": p.startpoint,
                    "end": p.endpoint,
                    "slack": p.slack_ns,
                    "delay": p.data_arrival_ns,
                    "arrival": p.data_arrival_ns,
                    "required": p.data_required_ns,
                    "stages": stages_data,
                    "levels": p.num_levels,
                    "clock": p.endpoint_clock or p.startpoint_clock or "",
                }
            )
        if paths_data:
            self._paths_tab.set_paths(paths_data, clock_names or None)

        # ----- forward to optional path browser dock ---------------------
        browser = getattr(self, "_path_browser", None)
        if browser is not None:
            try:
                browser.load_sta_report(report)
            except Exception:
                pass

    def attach_path_browser(self, browser) -> None:
        """Register a :class:`PathBrowserPanel` to mirror STA reports into."""
        self._path_browser = browser

    def show_demo_data(self) -> None:
        """Load placeholder data for development/demo purposes."""
        self.update_results({
            "wns_setup": 0.342,
            "tns_setup": 0.0,
            "wns_hold": 0.085,
            "tns_hold": 0.0,
            "clocks": [
                {"name": "sys_clk", "period": 5.0, "frequency": 200.0, "wns": 0.342, "tns": 0.0, "endpoints": 4256},
                {"name": "pci_clk", "period": 8.0, "frequency": 125.0, "wns": 1.204, "tns": 0.0, "endpoints": 512},
                {"name": "ddr_clk", "period": 2.5, "frequency": 400.0, "wns": -0.112, "tns": -3.45, "endpoints": 1024},
            ],
            "histogram": [
                (-2.0, -1.5, 2), (-1.5, -1.0, 5), (-1.0, -0.5, 12), (-0.5, 0.0, 28),
                (0.0, 0.5, 156), (0.5, 1.0, 342), (1.0, 1.5, 512), (1.5, 2.0, 420),
                (2.0, 2.5, 280), (2.5, 3.0, 180), (3.0, 3.5, 90), (3.5, 4.0, 45),
            ],
            "clock_names": ["sys_clk", "pci_clk", "ddr_clk"],
            "paths": [
                {
                    "slack": -0.112, "start": "ddr_ctrl/addr_reg[0]/Q",
                    "end": "ddr_phy/data_out_reg[7]/D", "delay": 2.612, "levels": 8,
                    "clock": "ddr_clk",
                    "stages": [
                        {"cell": "addr_reg[0]", "type": "DFF (CK->Q)", "delay": 0.180, "arrival": 0.180, "transition": "rise"},
                        {"cell": "addr_decode", "type": "Cell", "delay": 0.245, "arrival": 0.425, "transition": "fall"},
                        {"cell": "net_42", "type": "Wire", "delay": 0.082, "arrival": 0.507, "transition": ""},
                        {"cell": "mux_bank", "type": "Cell", "delay": 0.312, "arrival": 0.819, "transition": "rise"},
                        {"cell": "net_89", "type": "Wire", "delay": 0.145, "arrival": 0.964, "transition": ""},
                        {"cell": "data_align", "type": "Cell", "delay": 0.398, "arrival": 1.362, "transition": "fall"},
                        {"cell": "net_112", "type": "Wire", "delay": 0.095, "arrival": 1.457, "transition": ""},
                        {"cell": "data_out_reg[7]", "type": "DFF (D)", "delay": 0.043, "arrival": 1.500, "transition": "rise"},
                    ],
                },
                {
                    "slack": 0.342, "start": "cpu/alu/op_reg[3]/Q",
                    "end": "cpu/wb/result_reg[31]/D", "delay": 4.658, "levels": 12,
                    "clock": "sys_clk",
                    "stages": [
                        {"cell": "op_reg[3]", "type": "DFF (CK->Q)", "delay": 0.195, "arrival": 0.195, "transition": "rise"},
                        {"cell": "adder_0", "type": "Cell", "delay": 0.520, "arrival": 0.715, "transition": "rise"},
                        {"cell": "net_201", "type": "Wire", "delay": 0.110, "arrival": 0.825, "transition": ""},
                        {"cell": "shifter", "type": "Cell", "delay": 0.685, "arrival": 1.510, "transition": "fall"},
                        {"cell": "result_mux", "type": "Cell", "delay": 0.340, "arrival": 1.850, "transition": "rise"},
                        {"cell": "result_reg[31]", "type": "DFF (D)", "delay": 0.045, "arrival": 1.895, "transition": "rise"},
                    ],
                },
                {
                    "slack": 1.204, "start": "pci/cfg_reg[0]/Q",
                    "end": "pci/bar_reg[31]/D", "delay": 6.796, "levels": 6,
                    "clock": "pci_clk",
                    "stages": [
                        {"cell": "cfg_reg[0]", "type": "DFF (CK->Q)", "delay": 0.210, "arrival": 0.210, "transition": "rise"},
                        {"cell": "cfg_decode", "type": "Cell", "delay": 0.380, "arrival": 0.590, "transition": "fall"},
                        {"cell": "bar_reg[31]", "type": "DFF (D)", "delay": 0.050, "arrival": 0.640, "transition": "rise"},
                    ],
                },
            ],
            "coverage": {"covered": 5280, "total": 5792},
            "sdc_clocks": [
                {"name": "sys_clk", "source": "get_ports clk", "period": 5.0, "waveform": "{0 2.5}"},
                {"name": "pci_clk", "source": "get_ports pci_clk", "period": 8.0, "waveform": "{0 4.0}"},
                {"name": "ddr_clk", "source": "get_pins pll/clk_out", "period": 2.5, "waveform": "{0 1.25}"},
            ],
            "io_delays": [
                {"port": "data_in[7:0]", "direction": "Input", "delay": 1.5, "clock": "sys_clk"},
                {"port": "data_out[7:0]", "direction": "Output", "delay": 2.0, "clock": "sys_clk"},
                {"port": "addr[15:0]", "direction": "Input", "delay": 1.2, "clock": "sys_clk"},
                {"port": "pci_ad[31:0]", "direction": "Inout", "delay": 3.0, "clock": "pci_clk"},
            ],
            "exceptions": [
                {"type": "False Path", "from": "cpu/debug_reg[*]", "to": "pci/cfg_reg[*]"},
                {"type": "Multicycle Path (2)", "from": "cpu/mul/result[*]", "to": "cpu/wb/result_reg[*]"},
                {"type": "False Path", "from": "reset_sync/q_reg", "to": "*"},
                {"type": "Max Delay (3.0 ns)", "from": "ddr_ctrl/addr_reg[*]", "to": "ddr_phy/data_out_reg[*]"},
            ],
        })
