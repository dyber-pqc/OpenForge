"""Vivado-quality synthesis results panel with resource utilisation, hierarchy,
cell usage, schematic viewer, and message browser.

All widgets use the Catppuccin Mocha dark theme for a professional EDA aesthetic.
"""

from __future__ import annotations

import math
from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
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

_CLR_BLUE: Final[str] = "#89b4fa"
_CLR_GREEN: Final[str] = "#a6e3a1"
_CLR_RED: Final[str] = "#f38ba8"
_CLR_YELLOW: Final[str] = "#f9e2af"
_CLR_MAUVE: Final[str] = "#cba6f7"
_CLR_PEACH: Final[str] = "#fab387"
_CLR_TEAL: Final[str] = "#94e2d5"
_CLR_PINK: Final[str] = "#f5c2e7"
_CLR_SAPPHIRE: Final[str] = "#74c7ec"

_ALT_ROW: Final[str] = "#1a1a2e"

# Synthesis progress stages
_SYNTH_STAGES: Final[list[str]] = [
    "Read", "Elaborate", "Map", "Optimize", "Write",
]

# ── Shared helpers ──────────────────────────────────────────────────────────


def _text_item(text: str, color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    return item


def _numeric_item(value: float | int, fmt: str = "{:,.0f}", color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(fmt.format(value))
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item.setData(Qt.ItemDataRole.UserRole, value)
    return item


def _header_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_CLR_BLUE}; font-weight: bold; font-size: 13px; padding: 4px 0px;")
    return lbl


def _dim_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
    return lbl


def _configure_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(f"QTableWidget {{ alternate-background-color: {_ALT_ROW}; }}")
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)


# ── Pie Chart Widget ────────────────────────────────────────────────────────


class _PieChartWidget(QWidget):
    """Small donut pie chart for area breakdown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(180, 180)
        self.setMaximumSize(220, 220)
        self._slices: list[tuple[str, float, str]] = []  # (label, value, color)

    def set_data(self, slices: list[tuple[str, float, str]]) -> None:
        self._slices = slices
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._slices:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total = sum(v for _, v, _ in self._slices)
        if total <= 0:
            return

        w, h = self.width(), self.height()
        size = min(w, h) - 20
        outer = QRectF((w - size) / 2, 10, size, size)
        inner_size = size * 0.55
        inner = QRectF((w - inner_size) / 2, 10 + (size - inner_size) / 2, inner_size, inner_size)

        start = 90 * 16  # start at top
        for label, value, color in self._slices:
            span = int(value / total * 360 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPie(outer, start, span)
            start += span

        # Donut hole
        painter.setBrush(QColor(_BG))
        painter.drawEllipse(inner)

        # Total label in center
        painter.setPen(QColor(_TEXT))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, f"{total:,.0f}\num\u00b2")

        # Legend below
        legend_y = 10 + size + 6
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        x = 6
        for label, value, color in self._slices:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(x, legend_y, 8, 8))
            painter.setPen(QColor(_SUBTEXT))
            pct = value / total * 100 if total else 0
            painter.drawText(QPointF(x + 12, legend_y + 8), f"{label} ({pct:.0f}%)")
            x += QFontMetrics(font).horizontalAdvance(f"{label} ({pct:.0f}%)") + 22


# ── Bar Column Delegate (inline bar in table) ──────────────────────────────


class _BarColumnWidget(QWidget):
    """Horizontal bar for use in a table cell."""

    def __init__(self, value: float, max_value: float, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = value
        self._max = max_value
        self._color = color
        self.setFixedHeight(20)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width() - 4
        h = self.height() - 6
        ratio = min(self._value / self._max, 1.0) if self._max > 0 else 0
        bar_w = int(w * ratio)

        # Background track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_SURFACE0))
        painter.drawRoundedRect(QRectF(2, 3, w, h), 3, 3)

        # Fill bar
        painter.setBrush(QColor(self._color))
        painter.drawRoundedRect(QRectF(2, 3, bar_w, h), 3, 3)


# ── Progress Pipeline Widget ────────────────────────────────────────────────


class _SynthProgressWidget(QWidget):
    """Pipeline progress indicator: Read -> Elaborate -> Map -> Optimize -> Write."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(50)
        self._current_stage: int = -1  # -1 = not started
        self._completed: set[int] = set()

    def set_stage(self, stage_index: int) -> None:
        for i in range(stage_index):
            self._completed.add(i)
        self._current_stage = stage_index
        self.update()

    def set_all_complete(self) -> None:
        self._completed = set(range(len(_SYNTH_STAGES)))
        self._current_stage = len(_SYNTH_STAGES)
        self.update()

    def reset(self) -> None:
        self._current_stage = -1
        self._completed.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(_SYNTH_STAGES)
        w = self.width()
        h = self.height()
        node_r = 14
        margin = 40
        span = w - 2 * margin
        step = span / max(n - 1, 1)

        # Draw connecting lines
        for i in range(n - 1):
            x1 = margin + i * step
            x2 = margin + (i + 1) * step
            color = _CLR_GREEN if i in self._completed else _SURFACE1
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(x1, h / 2), QPointF(x2, h / 2))

        # Draw nodes
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        for i, label in enumerate(_SYNTH_STAGES):
            cx = margin + i * step
            cy = h / 2

            if i in self._completed:
                painter.setBrush(QColor(_CLR_GREEN))
                painter.setPen(QPen(QColor(_CLR_GREEN), 2))
            elif i == self._current_stage:
                painter.setBrush(QColor(_CLR_BLUE))
                painter.setPen(QPen(QColor(_CLR_BLUE), 2))
            else:
                painter.setBrush(QColor(_SURFACE0))
                painter.setPen(QPen(QColor(_SURFACE1), 2))

            painter.drawEllipse(QPointF(cx, cy), node_r, node_r)

            # Checkmark or number
            painter.setPen(QColor(_CRUST))
            if i in self._completed:
                painter.drawText(QRectF(cx - node_r, cy - node_r, 2 * node_r, 2 * node_r),
                                 Qt.AlignmentFlag.AlignCenter, "\u2713")
            else:
                painter.drawText(QRectF(cx - node_r, cy - node_r, 2 * node_r, 2 * node_r),
                                 Qt.AlignmentFlag.AlignCenter, str(i + 1))

            # Label below
            painter.setPen(QColor(_SUBTEXT if i != self._current_stage else _TEXT))
            font2 = QFont()
            font2.setPointSize(7)
            painter.setFont(font2)
            painter.drawText(QRectF(cx - 30, cy + node_r + 2, 60, 16),
                             Qt.AlignmentFlag.AlignCenter, label)
            painter.setFont(font)


# ── Summary Tab ─────────────────────────────────────────────────────────────


class _SummaryTab(QWidget):
    """Resource utilisation summary with tables, bar chart column, and pie chart."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Progress pipeline
        root.addWidget(_header_label("Synthesis Progress"))
        self._progress = _SynthProgressWidget()
        root.addWidget(self._progress)

        # Timing estimate
        timing_group = QGroupBox("Timing Estimate")
        tg_layout = QHBoxLayout(timing_group)
        self._lbl_target = QLabel("Target: --")
        self._lbl_target.setStyleSheet(f"color: {_TEXT}; font-size: 13px;")
        self._lbl_wns = QLabel("WNS: --")
        self._lbl_wns.setStyleSheet(f"color: {_CLR_GREEN}; font-weight: bold; font-size: 14px;")
        tg_layout.addWidget(self._lbl_target)
        tg_layout.addStretch()
        tg_layout.addWidget(self._lbl_wns)
        root.addWidget(timing_group)

        # Resource table + pie chart
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)

        # Left: resource table
        table_container = QWidget()
        tc_layout = QVBoxLayout(table_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.addWidget(_header_label("Resource Utilisation"))

        self._res_table = QTableWidget(0, 4)
        self._res_table.setHorizontalHeaderLabels(["Cell Type", "Count", "Area (um\u00b2)", ""])
        _configure_table(self._res_table)
        self._res_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._res_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._res_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._res_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._res_table.setColumnWidth(3, 120)
        tc_layout.addWidget(self._res_table)

        body.addWidget(table_container)

        # Right: pie chart
        pie_container = QWidget()
        pc_layout = QVBoxLayout(pie_container)
        pc_layout.setContentsMargins(0, 0, 0, 0)
        pc_layout.addWidget(_header_label("Area Breakdown"))
        self._pie = _PieChartWidget()
        pc_layout.addWidget(self._pie, alignment=Qt.AlignmentFlag.AlignCenter)
        pc_layout.addStretch()
        body.addWidget(pie_container)

        body.setSizes([500, 250])
        root.addWidget(body, 1)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def progress(self) -> _SynthProgressWidget:
        return self._progress

    def set_timing(self, target_mhz: float, wns_ns: float) -> None:
        self._lbl_target.setText(f"Target: {target_mhz:.1f} MHz ({1000.0 / target_mhz:.2f} ns)")
        color = _CLR_GREEN if wns_ns >= 0 else _CLR_RED
        sign = "+" if wns_ns >= 0 else ""
        self._lbl_wns.setText(f"WNS: {sign}{wns_ns:.3f} ns")
        self._lbl_wns.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")

    def set_resources(self, resources: list[dict]) -> None:
        """Populate from list of dicts with keys: type, count, area, color."""
        self._res_table.setRowCount(0)
        max_count = max((r.get("count", 0) for r in resources), default=1) or 1
        pie_data: list[tuple[str, float, str]] = []

        for r in resources:
            row = self._res_table.rowCount()
            self._res_table.insertRow(row)
            cell_type = r.get("type", "")
            count = r.get("count", 0)
            area = r.get("area", 0.0)
            color = r.get("color", _CLR_BLUE)

            self._res_table.setItem(row, 0, _text_item(cell_type))
            self._res_table.setItem(row, 1, _numeric_item(count))
            self._res_table.setItem(row, 2, _numeric_item(area, "{:,.1f}"))
            bar = _BarColumnWidget(count, max_count, color)
            self._res_table.setCellWidget(row, 3, bar)
            if area > 0:
                pie_data.append((cell_type, area, color))

        self._pie.set_data(pie_data)


# ── Cell Usage Tab ──────────────────────────────────────────────────────────


class _CellUsageTab(QWidget):
    """Searchable/filterable cell usage table with Liberty cell info."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Search bar
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by cell name...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Sort by Count", "Sort by Area", "Sort by Name"])
        self._sort_combo.currentIndexChanged.connect(self._apply_sort)
        search_row.addWidget(self._sort_combo)
        root.addLayout(search_row)

        # Bar chart area (horizontal bars)
        self._bar_chart = _CellBarChart()
        root.addWidget(self._bar_chart)

        # Detail table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Cell Name", "Count", "Area (um\u00b2)", "Leakage (nW)", "Function", "Library",
        ])
        _configure_table(self._table)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table)

    def set_cells(self, cells: list[dict]) -> None:
        """Populate from list of dicts: name, count, area, leakage, function, library."""
        self._cells = cells
        self._populate(cells)

    def _populate(self, cells: list[dict]) -> None:
        self._table.setRowCount(0)
        bar_data: list[tuple[str, int, str]] = []
        for c in cells:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, _text_item(c.get("name", "")))
            self._table.setItem(row, 1, _numeric_item(c.get("count", 0)))
            self._table.setItem(row, 2, _numeric_item(c.get("area", 0.0), "{:,.2f}"))
            self._table.setItem(row, 3, _numeric_item(c.get("leakage", 0.0), "{:,.3f}"))
            self._table.setItem(row, 4, _text_item(c.get("function", ""), _SUBTEXT))
            self._table.setItem(row, 5, _text_item(c.get("library", ""), _SUBTEXT))
            bar_data.append((c.get("name", ""), c.get("count", 0), _CLR_BLUE))
        self._bar_chart.set_data(bar_data[:20])  # top 20

    def _apply_filter(self, text: str) -> None:
        if not hasattr(self, "_cells"):
            return
        filt = text.lower()
        filtered = [c for c in self._cells if filt in c.get("name", "").lower()]
        self._populate(filtered)

    def _apply_sort(self, index: int) -> None:
        if not hasattr(self, "_cells"):
            return
        key_map = {0: "count", 1: "area", 2: "name"}
        key = key_map.get(index, "count")
        reverse = key != "name"
        self._cells.sort(key=lambda c: c.get(key, 0), reverse=reverse)
        self._populate(self._cells)


class _CellBarChart(QWidget):
    """Horizontal bar chart for top cell types."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(200)
        self._data: list[tuple[str, int, str]] = []

    def set_data(self, data: list[tuple[str, int, str]]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        max_val = max(v for _, v, _ in self._data) or 1
        n = len(self._data)
        w = self.width()
        h = self.height()
        label_w = 100
        bar_area = w - label_w - 20
        row_h = min(18, (h - 10) / max(n, 1))

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        for i, (name, count, color) in enumerate(self._data):
            y = 4 + i * row_h
            # Label
            painter.setPen(QColor(_SUBTEXT))
            painter.drawText(QRectF(2, y, label_w - 4, row_h),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             name[:14])
            # Bar
            ratio = count / max_val
            bar_w = int(bar_area * ratio)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(label_w, y + 2, bar_w, row_h - 4), 2, 2)
            # Count label
            painter.setPen(QColor(_TEXT))
            painter.drawText(QRectF(label_w + bar_w + 4, y, 60, row_h),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{count:,}")


# ── Hierarchy Tab ───────────────────────────────────────────────────────────


class _HierarchyTab(QWidget):
    """Module hierarchy tree showing per-module resource usage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        root.addWidget(_header_label("Design Hierarchy"))

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Module", "Cells", "FFs", "Area (um\u00b2)", "% of Total"])
        self._tree.setColumnCount(5)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self._tree.header().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"QTreeWidget {{ alternate-background-color: {_ALT_ROW}; }}")
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.setAnimated(True)
        self._tree.setIndentation(20)
        root.addWidget(self._tree)

    def set_hierarchy(self, modules: list[dict], total_area: float = 0.0) -> None:
        """Populate from list of dicts: name, cells, ffs, area, children (recursive)."""
        self._tree.clear()
        self._total_area = total_area if total_area > 0 else 1.0
        for m in modules:
            item = self._make_item(m)
            self._tree.addTopLevelItem(item)
        self._tree.expandToDepth(1)

    def _make_item(self, m: dict) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, m.get("name", ""))
        item.setText(1, f"{m.get('cells', 0):,}")
        item.setText(2, f"{m.get('ffs', 0):,}")
        area = m.get("area", 0.0)
        item.setText(3, f"{area:,.1f}")
        pct = area / self._total_area * 100 if self._total_area > 0 else 0
        item.setText(4, f"{pct:.1f}%")

        # Color the percentage column
        if pct > 50:
            item.setForeground(4, QColor(_CLR_RED))
        elif pct > 20:
            item.setForeground(4, QColor(_CLR_YELLOW))
        else:
            item.setForeground(4, QColor(_CLR_GREEN))

        for child in m.get("children", []):
            item.addChild(self._make_item(child))
        return item

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("View Netlist", lambda: None)
        menu.addAction("Flatten", lambda: None)
        menu.addAction("Keep Hierarchy", lambda: None)
        menu.addSeparator()
        menu.addAction("Set as Top Module", lambda: None)
        menu.exec(self._tree.viewport().mapToGlobal(pos))


# ── Messages Tab ────────────────────────────────────────────────────────────


class _MessagesTab(QWidget):
    """Warning/error message list with filtering and search."""

    source_requested = Signal(str, int)  # file path, line number

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        # Filter bar
        filter_row = QHBoxLayout()
        self._btn_all = QPushButton("All")
        self._btn_errors = QPushButton("Errors")
        self._btn_warnings = QPushButton("Warnings")
        for btn in (self._btn_all, self._btn_errors, self._btn_warnings):
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            filter_row.addWidget(btn)
        self._btn_all.setChecked(True)
        self._btn_all.clicked.connect(lambda: self._set_filter("all"))
        self._btn_errors.clicked.connect(lambda: self._set_filter("error"))
        self._btn_warnings.clicked.connect(lambda: self._set_filter("warning"))

        filter_row.addStretch()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search messages...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search)

        # Counts
        self._lbl_errors = QLabel("0 errors")
        self._lbl_errors.setStyleSheet(f"color: {_CLR_RED}; font-weight: bold; font-size: 12px;")
        self._lbl_warnings = QLabel("0 warnings")
        self._lbl_warnings.setStyleSheet(f"color: {_CLR_YELLOW}; font-weight: bold; font-size: 12px;")
        filter_row.addWidget(self._lbl_errors)
        filter_row.addWidget(self._lbl_warnings)

        root.addLayout(filter_row)

        # Message table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Severity", "Code", "Message", "Location"])
        _configure_table(self._table)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._table)

        self._messages: list[dict] = []
        self._current_filter = "all"

    def set_messages(self, messages: list[dict]) -> None:
        """Populate from list of dicts: severity, code, message, file, line."""
        self._messages = messages
        n_err = sum(1 for m in messages if m.get("severity", "").lower() == "error")
        n_warn = sum(1 for m in messages if m.get("severity", "").lower() == "warning")
        self._lbl_errors.setText(f"{n_err} error{'s' if n_err != 1 else ''}")
        self._lbl_warnings.setText(f"{n_warn} warning{'s' if n_warn != 1 else ''}")
        self._repopulate()

    def _set_filter(self, filt: str) -> None:
        self._current_filter = filt
        self._btn_all.setChecked(filt == "all")
        self._btn_errors.setChecked(filt == "error")
        self._btn_warnings.setChecked(filt == "warning")
        self._repopulate()

    def _apply_filter(self, text: str) -> None:
        self._repopulate()

    def _repopulate(self) -> None:
        self._table.setRowCount(0)
        search_text = self._search.text().lower()
        for msg in self._messages:
            sev = msg.get("severity", "").lower()
            if self._current_filter == "error" and sev != "error":
                continue
            if self._current_filter == "warning" and sev != "warning":
                continue
            text = msg.get("message", "")
            if search_text and search_text not in text.lower():
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)

            # Severity with icon/color
            sev_item = QTableWidgetItem(sev.upper())
            sev_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if sev == "error":
                sev_item.setForeground(QColor(_CLR_RED))
            elif sev == "warning":
                sev_item.setForeground(QColor(_CLR_YELLOW))
            else:
                sev_item.setForeground(QColor(_CLR_BLUE))
            font = QFont()
            font.setBold(True)
            sev_item.setFont(font)
            self._table.setItem(row, 0, sev_item)

            self._table.setItem(row, 1, _text_item(msg.get("code", ""), _SUBTEXT))
            self._table.setItem(row, 2, _text_item(text))
            loc = msg.get("file", "")
            line = msg.get("line", 0)
            if loc:
                loc_str = f"{loc}:{line}" if line else loc
            else:
                loc_str = ""
            self._table.setItem(row, 3, _text_item(loc_str, _SUBTEXT))

    def _on_double_click(self, index) -> None:
        row = index.row()
        if row < 0:
            return
        loc_item = self._table.item(row, 3)
        if loc_item is None:
            return
        loc = loc_item.text()
        if ":" in loc:
            parts = loc.rsplit(":", 1)
            try:
                self.source_requested.emit(parts[0], int(parts[1]))
            except (ValueError, IndexError):
                pass


# ── Schematic Viewer Tab ────────────────────────────────────────────────────


_CELL_COLORS: Final[dict[str, str]] = {
    "AND": _CLR_BLUE,
    "OR": _CLR_GREEN,
    "NOT": _CLR_RED,
    "XOR": _CLR_MAUVE,
    "MUX": _CLR_PEACH,
    "FF": _CLR_TEAL,
    "DFF": _CLR_TEAL,
    "LATCH": _CLR_PINK,
    "BUF": _CLR_SAPPHIRE,
    "INPUT": _CLR_YELLOW,
    "OUTPUT": _CLR_YELLOW,
}


class _SchematicScene(QGraphicsScene):
    """Scene for rendering a simple netlist schematic."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(_BG)))

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        # Subtle grid
        pen = QPen(QColor(_SURFACE0), 0.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        spacing = 40
        left = int(rect.left() / spacing) * spacing
        top = int(rect.top() / spacing) * spacing
        x = left
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += spacing
        y = top
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += spacing


class _SchematicView(QGraphicsView):
    """Zoom/pan schematic view."""

    def __init__(self, scene: _SchematicScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


class _SchematicTab(QWidget):
    """Basic netlist schematic viewer using QGraphicsView."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        btn_fit = QPushButton("Fit")
        btn_fit.setFixedSize(40, 26)
        btn_fit.clicked.connect(self._zoom_fit)
        toolbar.addWidget(btn_fit)
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(28, 26)
        btn_zoom_in.clicked.connect(lambda: self._view.scale(1.2, 1.2))
        toolbar.addWidget(btn_zoom_in)
        btn_zoom_out = QPushButton("\u2013")
        btn_zoom_out.setFixedSize(28, 26)
        btn_zoom_out.clicked.connect(lambda: self._view.scale(1 / 1.2, 1 / 1.2))
        toolbar.addWidget(btn_zoom_out)
        toolbar.addStretch()

        # Legend
        self._legend_label = QLabel()
        self._legend_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        toolbar.addWidget(self._legend_label)

        root.addLayout(toolbar)

        # Scene + View
        self._scene = _SchematicScene()
        self._view = _SchematicView(self._scene)
        root.addWidget(self._view)

        self._cell_items: dict[str, QGraphicsRectItem] = {}
        self._net_items: list[QGraphicsLineItem] = []
        self._update_legend()

    def load_netlist(self, netlist: dict) -> None:
        """Load from JSON: {cells: [{name, type, x, y, w, h, ports}], nets: [{from, to}]}."""
        self._scene.clear()
        self._cell_items.clear()
        self._net_items.clear()

        cells = netlist.get("cells", [])
        nets = netlist.get("nets", [])

        # Draw cells
        for cell in cells:
            name = cell.get("name", "")
            ctype = cell.get("type", "BUF").upper()
            x = cell.get("x", 0)
            y = cell.get("y", 0)
            w = cell.get("w", 80)
            h = cell.get("h", 50)

            color = QColor(_CELL_COLORS.get(ctype, _CLR_BLUE))
            brush = QBrush(QColor(color.red(), color.green(), color.blue(), 50))
            pen = QPen(color, 1.5)
            pen.setCosmetic(True)

            rect = self._scene.addRect(QRectF(x, y, w, h), pen, brush)
            rect.setToolTip(f"{name} ({ctype})")
            rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._cell_items[name] = rect

            # Cell label
            label = self._scene.addSimpleText(name)
            label.setFont(QFont("Segoe UI", 7))
            label.setBrush(QColor(_TEXT))
            label_rect = label.boundingRect()
            label.setPos(x + (w - label_rect.width()) / 2, y + (h - label_rect.height()) / 2)

            # Type label above
            type_label = self._scene.addSimpleText(ctype)
            type_label.setFont(QFont("Segoe UI", 6, QFont.Weight.Bold))
            type_label.setBrush(color)
            type_label.setPos(x + 2, y - 12)

        # Draw nets
        for net in nets:
            src = net.get("from", "")
            dst = net.get("to", "")
            src_rect = self._cell_items.get(src)
            dst_rect = self._cell_items.get(dst)
            if src_rect is None or dst_rect is None:
                continue
            sr = src_rect.rect()
            dr = dst_rect.rect()
            x1 = sr.right()
            y1 = sr.center().y()
            x2 = dr.left()
            y2 = dr.center().y()
            mid_x = (x1 + x2) / 2

            pen = QPen(QColor(_OVERLAY0), 1.0)
            pen.setCosmetic(True)
            line1 = self._scene.addLine(x1, y1, mid_x, y1, pen)
            line2 = self._scene.addLine(mid_x, y1, mid_x, y2, pen)
            line3 = self._scene.addLine(mid_x, y2, x2, y2, pen)
            self._net_items.extend([line1, line2, line3])

        self._zoom_fit()

    def highlight_cone(self, output_cell: str) -> None:
        """Highlight cone of influence for a given output cell."""
        # Reset all
        for name, rect in self._cell_items.items():
            color = QColor(_CLR_BLUE)
            rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 50)))
        # Highlight selected
        target = self._cell_items.get(output_cell)
        if target is not None:
            color = QColor(_CLR_YELLOW)
            target.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 100)))

    def _zoom_fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return
        self._view.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)

    def _update_legend(self) -> None:
        parts = []
        for ctype, color in list(_CELL_COLORS.items())[:6]:
            parts.append(f'<span style="color:{color};">\u25a0</span> {ctype}')
        self._legend_label.setText("  ".join(parts))


# ── Main SynthesisPanel ─────────────────────────────────────────────────────


class SynthesisPanel(QDockWidget):
    """Dock widget with tabbed synthesis results: Summary, Cells, Hierarchy,
    Messages, and Schematic viewer."""

    def __init__(self, title: str = "Synthesis", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._tabs = QTabWidget()
        self._summary = _SummaryTab()
        self._cells = _CellUsageTab()
        self._hierarchy = _HierarchyTab()
        self._messages = _MessagesTab()
        self._schematic = _SchematicTab()

        self._tabs.addTab(self._summary, "Summary")
        self._tabs.addTab(self._cells, "Cell Usage")
        self._tabs.addTab(self._hierarchy, "Hierarchy")
        self._tabs.addTab(self._messages, "Messages")
        self._tabs.addTab(self._schematic, "Schematic")

        self.setWidget(self._tabs)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def summary(self) -> _SummaryTab:
        return self._summary

    @property
    def cells(self) -> _CellUsageTab:
        return self._cells

    @property
    def hierarchy(self) -> _HierarchyTab:
        return self._hierarchy

    @property
    def messages(self) -> _MessagesTab:
        return self._messages

    @property
    def schematic(self) -> _SchematicTab:
        return self._schematic

    def update_results(self, results: dict) -> None:
        """Populate all tabs from a synthesis results dictionary.

        Expected keys:
            - ``resources``: list of dicts with type, count, area, color
            - ``target_mhz``: float
            - ``wns_ns``: float
            - ``stage``: int (0-4) or ``"complete"``
            - ``cells``: list of dicts with name, count, area, leakage, function, library
            - ``hierarchy``: list of module dicts (recursive)
            - ``total_area``: float
            - ``messages``: list of dicts with severity, code, message, file, line
            - ``netlist``: dict with cells and nets for schematic
        """
        # Summary
        resources = results.get("resources", [])
        if resources:
            self._summary.set_resources(resources)

        target = results.get("target_mhz", 0)
        wns = results.get("wns_ns", 0)
        if target:
            self._summary.set_timing(target, wns)

        stage = results.get("stage")
        if stage == "complete":
            self._summary.progress.set_all_complete()
        elif isinstance(stage, int):
            self._summary.progress.set_stage(stage)

        # Cells
        cells = results.get("cells", [])
        if cells:
            self._cells.set_cells(cells)

        # Hierarchy
        hierarchy = results.get("hierarchy", [])
        total_area = results.get("total_area", 0.0)
        if hierarchy:
            self._hierarchy.set_hierarchy(hierarchy, total_area)

        # Messages
        messages = results.get("messages", [])
        if messages:
            self._messages.set_messages(messages)

        # Schematic
        netlist = results.get("netlist")
        if netlist:
            self._schematic.load_netlist(netlist)

    def show_demo_data(self) -> None:
        """Load placeholder data for development/demo purposes."""
        self.update_results({
            "target_mhz": 200.0,
            "wns_ns": 0.342,
            "stage": "complete",
            "resources": [
                {"type": "Flip-Flops", "count": 4256, "area": 12768.0, "color": _CLR_TEAL},
                {"type": "LUTs / Gates", "count": 8192, "area": 24576.0, "color": _CLR_BLUE},
                {"type": "Memory Bits", "count": 32768, "area": 8192.0, "color": _CLR_MAUVE},
                {"type": "DSP Blocks", "count": 16, "area": 4800.0, "color": _CLR_PEACH},
                {"type": "I/O Pads", "count": 128, "area": 3840.0, "color": _CLR_GREEN},
            ],
            "cells": [
                {"name": "sky130_fd_sc_hd__inv_1", "count": 1024, "area": 1.44, "leakage": 0.12, "function": "Y=!A", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__nand2_1", "count": 892, "area": 2.88, "leakage": 0.18, "function": "Y=!(A&B)", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__dfxtp_1", "count": 768, "area": 7.20, "leakage": 0.42, "function": "DFF", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__nor2_1", "count": 645, "area": 2.88, "leakage": 0.15, "function": "Y=!(A|B)", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__mux2_1", "count": 512, "area": 5.76, "leakage": 0.28, "function": "MUX", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__buf_2", "count": 384, "area": 2.88, "leakage": 0.10, "function": "Y=A", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__and2_1", "count": 256, "area": 2.88, "leakage": 0.16, "function": "Y=A&B", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__or2_1", "count": 198, "area": 2.88, "leakage": 0.14, "function": "Y=A|B", "library": "sky130"},
                {"name": "sky130_fd_sc_hd__xor2_1", "count": 128, "area": 5.76, "leakage": 0.32, "function": "Y=A^B", "library": "sky130"},
            ],
            "hierarchy": [
                {"name": "top", "cells": 8192, "ffs": 4256, "area": 54176.0, "children": [
                    {"name": "cpu_core", "cells": 4096, "ffs": 2048, "area": 28800.0, "children": [
                        {"name": "alu", "cells": 1024, "ffs": 128, "area": 7200.0, "children": []},
                        {"name": "register_file", "cells": 1536, "ffs": 1024, "area": 10800.0, "children": []},
                        {"name": "control", "cells": 512, "ffs": 256, "area": 3600.0, "children": []},
                        {"name": "decoder", "cells": 1024, "ffs": 640, "area": 7200.0, "children": []},
                    ]},
                    {"name": "cache", "cells": 2048, "ffs": 1024, "area": 14400.0, "children": [
                        {"name": "tag_ram", "cells": 512, "ffs": 256, "area": 3600.0, "children": []},
                        {"name": "data_ram", "cells": 1536, "ffs": 768, "area": 10800.0, "children": []},
                    ]},
                    {"name": "bus_interface", "cells": 2048, "ffs": 1184, "area": 10976.0, "children": []},
                ]},
            ],
            "total_area": 54176.0,
            "messages": [
                {"severity": "warning", "code": "SYNTH-4", "message": "Signal 'data_in[7:0]' is unconnected.", "file": "cpu_core.v", "line": 42},
                {"severity": "warning", "code": "SYNTH-6", "message": "Latch inferred for 'state_reg'.", "file": "control.v", "line": 87},
                {"severity": "error", "code": "SYNTH-1", "message": "Multi-driven net 'clk_div' detected.", "file": "top.v", "line": 15},
                {"severity": "info", "code": "SYNTH-99", "message": "Synthesis completed in 4.2 seconds.", "file": "", "line": 0},
                {"severity": "warning", "code": "SYNTH-12", "message": "Black-box module 'pll' has no definition.", "file": "top.v", "line": 8},
            ],
            "netlist": {
                "cells": [
                    {"name": "clk_buf", "type": "BUF", "x": 0, "y": 60, "w": 70, "h": 40},
                    {"name": "and_0", "type": "AND", "x": 120, "y": 0, "w": 70, "h": 40},
                    {"name": "or_0", "type": "OR", "x": 120, "y": 80, "w": 70, "h": 40},
                    {"name": "mux_0", "type": "MUX", "x": 240, "y": 40, "w": 70, "h": 50},
                    {"name": "ff_0", "type": "DFF", "x": 360, "y": 45, "w": 70, "h": 40},
                    {"name": "out", "type": "OUTPUT", "x": 480, "y": 50, "w": 60, "h": 30},
                ],
                "nets": [
                    {"from": "clk_buf", "to": "and_0"},
                    {"from": "clk_buf", "to": "or_0"},
                    {"from": "and_0", "to": "mux_0"},
                    {"from": "or_0", "to": "mux_0"},
                    {"from": "mux_0", "to": "ff_0"},
                    {"from": "ff_0", "to": "out"},
                ],
            },
        })
