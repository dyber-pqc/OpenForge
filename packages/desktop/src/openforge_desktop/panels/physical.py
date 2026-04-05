"""Physical design control and results panel with flow control, floorplan
configuration, statistics, and DRC/LVS checking.

All widgets use the Catppuccin Mocha dark theme for a professional EDA aesthetic.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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

# Physical design flow stages
_PD_STAGES: Final[list[str]] = [
    "Floorplan", "Placement", "CTS", "Routing", "Signoff",
]


# ── Shared helpers ──────────────────────────────────────────────────────────


def _text_item(text: str, color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    return item


def _numeric_item(value: float | int, fmt: str = "{:,.2f}", color: str = _TEXT) -> QTableWidgetItem:
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


def _configure_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(f"QTableWidget {{ alternate-background-color: {_ALT_ROW}; }}")
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)


# ── Pipeline Widget ─────────────────────────────────────────────────────────


class _FlowPipelineWidget(QWidget):
    """Visual pipeline: Floorplan -> Placement -> CTS -> Routing -> Signoff."""

    stage_run_requested = Signal(int)  # stage index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(60)
        self._statuses: list[str] = ["idle"] * len(_PD_STAGES)  # idle, running, done, error
        self._durations: list[str] = ["--"] * len(_PD_STAGES)

    def set_status(self, index: int, status: str, duration: str = "--") -> None:
        if 0 <= index < len(_PD_STAGES):
            self._statuses[index] = status
            self._durations[index] = duration
            self.update()

    def reset(self) -> None:
        self._statuses = ["idle"] * len(_PD_STAGES)
        self._durations = ["--"] * len(_PD_STAGES)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        n = len(_PD_STAGES)
        w = self.width()
        h = self.height()
        margin = 30
        span = w - 2 * margin
        step = span / max(n - 1, 1)
        node_r = 16
        cy = h / 2 - 4

        status_colors = {
            "idle": _SURFACE1,
            "running": _CLR_BLUE,
            "done": _CLR_GREEN,
            "error": _CLR_RED,
        }

        # Connecting lines
        for i in range(n - 1):
            x1 = margin + i * step
            x2 = margin + (i + 1) * step
            done = self._statuses[i] == "done"
            color = _CLR_GREEN if done else _SURFACE0
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(x1, cy), QPointF(x2, cy))

        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        for i, label in enumerate(_PD_STAGES):
            cx = margin + i * step
            status = self._statuses[i]
            color = QColor(status_colors.get(status, _SURFACE1))

            # Node
            painter.setPen(QPen(color, 2))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 80))
            painter.drawEllipse(QPointF(cx, cy), node_r, node_r)

            # Icon
            painter.setPen(QColor(_CRUST if status != "idle" else _SUBTEXT))
            if status == "done":
                painter.drawText(QRectF(cx - node_r, cy - node_r, 2 * node_r, 2 * node_r),
                                 Qt.AlignmentFlag.AlignCenter, "\u2713")
            elif status == "running":
                painter.drawText(QRectF(cx - node_r, cy - node_r, 2 * node_r, 2 * node_r),
                                 Qt.AlignmentFlag.AlignCenter, "\u25b6")
            elif status == "error":
                painter.drawText(QRectF(cx - node_r, cy - node_r, 2 * node_r, 2 * node_r),
                                 Qt.AlignmentFlag.AlignCenter, "\u2717")
            else:
                painter.drawText(QRectF(cx - node_r, cy - node_r, 2 * node_r, 2 * node_r),
                                 Qt.AlignmentFlag.AlignCenter, str(i + 1))

            # Label + duration
            font2 = QFont()
            font2.setPointSize(7)
            painter.setFont(font2)
            painter.setPen(QColor(_TEXT if status != "idle" else _SUBTEXT))
            painter.drawText(QRectF(cx - 35, cy + node_r + 2, 70, 12),
                             Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(QColor(_SUBTEXT))
            painter.drawText(QRectF(cx - 35, cy + node_r + 13, 70, 10),
                             Qt.AlignmentFlag.AlignCenter, self._durations[i])
            painter.setFont(font)


# ── Flow Control Tab ────────────────────────────────────────────────────────


class _FlowControlTab(QWidget):
    """Physical design flow control with per-stage run buttons and config."""

    run_stage_requested = Signal(int)    # stage index
    run_full_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Pipeline visualisation
        root.addWidget(_header_label("Implementation Flow"))
        self._pipeline = _FlowPipelineWidget()
        root.addWidget(self._pipeline)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("Idle")
        root.addWidget(self._progress)

        # Run buttons
        btn_row = QHBoxLayout()
        self._btn_full = QPushButton("Run Full Flow")
        self._btn_full.setStyleSheet(
            f"QPushButton {{ background-color: {_CLR_BLUE}; color: {_CRUST}; font-weight: bold; "
            f"border: none; border-radius: 4px; padding: 8px 20px; }}"
            f"QPushButton:hover {{ background-color: {_CLR_SAPPHIRE}; }}"
        )
        self._btn_full.clicked.connect(self.run_full_requested.emit)
        btn_row.addWidget(self._btn_full)
        btn_row.addStretch()

        for i, name in enumerate(_PD_STAGES):
            btn = QPushButton(f"Run {name}")
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, idx=i: self.run_stage_requested.emit(idx))
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        # Stage configuration
        config_group = QGroupBox("Stage Configuration")
        cfg_layout = QVBoxLayout(config_group)

        # Utilization
        util_row = QHBoxLayout()
        util_row.addWidget(QLabel("Target Utilization:"))
        self._util_spin = QSpinBox()
        self._util_spin.setRange(50, 95)
        self._util_spin.setValue(70)
        self._util_spin.setSuffix("%")
        util_row.addWidget(self._util_spin)
        util_row.addStretch()
        util_row.addWidget(QLabel("Aspect Ratio:"))
        self._aspect_spin = QDoubleSpinBox()
        self._aspect_spin.setRange(0.5, 2.0)
        self._aspect_spin.setValue(1.0)
        self._aspect_spin.setSingleStep(0.1)
        util_row.addWidget(self._aspect_spin)
        cfg_layout.addLayout(util_row)

        # Routing layers
        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("Routing Layers:"))
        self._route_combo = QComboBox()
        self._route_combo.addItems(["Metal1-Metal5", "Metal1-Metal7", "Metal1-Metal9"])
        route_row.addWidget(self._route_combo)
        route_row.addStretch()
        route_row.addWidget(QLabel("CTS Buffer:"))
        self._cts_combo = QComboBox()
        self._cts_combo.addItems(["CLKBUF_X2", "CLKBUF_X4", "CLKBUF_X8", "CLKBUF_X16"])
        route_row.addWidget(self._cts_combo)
        cfg_layout.addLayout(route_row)

        root.addWidget(config_group)

        # Log viewer
        root.addWidget(_header_label("Stage Log"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        self._log.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {_CRUST}; color: {_SUBTEXT}; "
            f"font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace; font-size: 11px; }}"
        )
        root.addWidget(self._log, 1)

    @property
    def pipeline(self) -> _FlowPipelineWidget:
        return self._pipeline

    @property
    def progress(self) -> QProgressBar:
        return self._progress

    def append_log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def clear_log(self) -> None:
        self._log.clear()


# ── Floorplan Tab ───────────────────────────────────────────────────────────


class _FloorplanTab(QWidget):
    """Floorplan configuration: die area, utilization, IO pins, power grid."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Die / Core area
        area_group = QGroupBox("Die / Core Area")
        ag_layout = QVBoxLayout(area_group)

        die_row = QHBoxLayout()
        die_row.addWidget(QLabel("Die Width (um):"))
        self._die_w = QDoubleSpinBox()
        self._die_w.setRange(100, 50000)
        self._die_w.setValue(2000)
        self._die_w.setDecimals(1)
        die_row.addWidget(self._die_w)
        die_row.addWidget(QLabel("Die Height (um):"))
        self._die_h = QDoubleSpinBox()
        self._die_h.setRange(100, 50000)
        self._die_h.setValue(2000)
        self._die_h.setDecimals(1)
        die_row.addWidget(self._die_h)
        ag_layout.addLayout(die_row)

        core_row = QHBoxLayout()
        core_row.addWidget(QLabel("Core Margin (um):"))
        self._core_margin = QDoubleSpinBox()
        self._core_margin.setRange(1, 500)
        self._core_margin.setValue(50)
        self._core_margin.setDecimals(1)
        core_row.addWidget(self._core_margin)

        self._area_label = QLabel("Die: 4.00 mm\u00b2  |  Core: 3.61 mm\u00b2")
        self._area_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        core_row.addStretch()
        core_row.addWidget(self._area_label)
        ag_layout.addLayout(core_row)

        # Connect for live updates
        self._die_w.valueChanged.connect(self._update_area_label)
        self._die_h.valueChanged.connect(self._update_area_label)
        self._core_margin.valueChanged.connect(self._update_area_label)

        root.addWidget(area_group)

        # Utilization slider
        util_group = QGroupBox("Utilization Target")
        ug_layout = QHBoxLayout(util_group)
        self._util_slider = QSlider(Qt.Orientation.Horizontal)
        self._util_slider.setRange(50, 90)
        self._util_slider.setValue(70)
        self._util_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._util_slider.setTickInterval(5)
        ug_layout.addWidget(self._util_slider)
        self._util_label = QLabel("70%")
        self._util_label.setStyleSheet(f"color: {_CLR_BLUE}; font-weight: bold; font-size: 14px;")
        self._util_label.setFixedWidth(50)
        self._util_slider.valueChanged.connect(
            lambda v: self._util_label.setText(f"{v}%")
        )
        ug_layout.addWidget(self._util_label)
        root.addWidget(util_group)

        # IO Pin placement
        io_group = QGroupBox("IO Pin Placement")
        io_layout = QVBoxLayout(io_group)
        io_row1 = QHBoxLayout()
        io_row1.addWidget(QLabel("Strategy:"))
        self._io_strategy = QComboBox()
        self._io_strategy.addItems(["Auto", "Manual", "From DEF", "From TCL Script"])
        io_row1.addWidget(self._io_strategy)
        io_row1.addStretch()
        io_row1.addWidget(QLabel("Pin Spacing (um):"))
        self._pin_spacing = QDoubleSpinBox()
        self._pin_spacing.setRange(0.5, 100)
        self._pin_spacing.setValue(5.0)
        self._pin_spacing.setDecimals(1)
        io_row1.addWidget(self._pin_spacing)
        io_layout.addLayout(io_row1)
        root.addWidget(io_group)

        # Power grid
        pwr_group = QGroupBox("Power Grid Configuration")
        pg_layout = QVBoxLayout(pwr_group)
        pwr_row = QHBoxLayout()
        pwr_row.addWidget(QLabel("Layer:"))
        self._pwr_layer = QComboBox()
        self._pwr_layer.addItems(["Metal5", "Metal6", "Metal7", "Metal8"])
        pwr_row.addWidget(self._pwr_layer)
        pwr_row.addWidget(QLabel("Width (um):"))
        self._pwr_width = QDoubleSpinBox()
        self._pwr_width.setRange(0.5, 50)
        self._pwr_width.setValue(3.0)
        self._pwr_width.setDecimals(1)
        pwr_row.addWidget(self._pwr_width)
        pwr_row.addWidget(QLabel("Pitch (um):"))
        self._pwr_pitch = QDoubleSpinBox()
        self._pwr_pitch.setRange(5, 500)
        self._pwr_pitch.setValue(50)
        self._pwr_pitch.setDecimals(1)
        pwr_row.addWidget(self._pwr_pitch)
        pg_layout.addLayout(pwr_row)
        root.addWidget(pwr_group)

        root.addStretch()

    def _update_area_label(self) -> None:
        dw = self._die_w.value()
        dh = self._die_h.value()
        margin = self._core_margin.value()
        die_area = dw * dh / 1e6  # mm^2
        core_w = max(0, dw - 2 * margin)
        core_h = max(0, dh - 2 * margin)
        core_area = core_w * core_h / 1e6
        self._area_label.setText(f"Die: {die_area:.2f} mm\u00b2  |  Core: {core_area:.2f} mm\u00b2")


# ── Statistics Tab ──────────────────────────────────────────────────────────


class _StatisticsTab(QWidget):
    """Area breakdown, wirelength, congestion, power, DRC summary."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)

        # Left column: tables
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        # Area breakdown
        ll.addWidget(_header_label("Area Breakdown"))
        self._area_table = QTableWidget(0, 3)
        self._area_table.setHorizontalHeaderLabels(["Category", "Area (um\u00b2)", "% of Total"])
        _configure_table(self._area_table)
        self._area_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._area_table.setMaximumHeight(160)
        ll.addWidget(self._area_table)

        # Wirelength / congestion
        ll.addWidget(_header_label("Routing Statistics"))
        self._route_table = QTableWidget(0, 2)
        self._route_table.setHorizontalHeaderLabels(["Metric", "Value"])
        _configure_table(self._route_table)
        self._route_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._route_table.setMaximumHeight(140)
        ll.addWidget(self._route_table)

        body.addWidget(left)

        # Right column: power + density
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        # Power estimate
        rl.addWidget(_header_label("Power Estimate"))
        self._power_table = QTableWidget(0, 2)
        self._power_table.setHorizontalHeaderLabels(["Component", "Power (mW)"])
        _configure_table(self._power_table)
        self._power_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._power_table.setMaximumHeight(140)
        rl.addWidget(self._power_table)

        # DRC summary
        rl.addWidget(_header_label("DRC Summary"))
        self._drc_summary = QLabel("No DRC results available")
        self._drc_summary.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        rl.addWidget(self._drc_summary)

        # Density heatmap placeholder
        rl.addWidget(_header_label("Cell Density Heatmap"))
        self._heatmap = _DensityHeatmap()
        rl.addWidget(self._heatmap, 1)

        body.addWidget(right)
        body.setSizes([400, 350])
        root.addWidget(body, 1)

    def set_area(self, categories: list[dict]) -> None:
        """Populate from dicts: name, area. Computes percentages."""
        self._area_table.setRowCount(0)
        total = sum(c.get("area", 0) for c in categories) or 1.0
        for c in categories:
            row = self._area_table.rowCount()
            self._area_table.insertRow(row)
            self._area_table.setItem(row, 0, _text_item(c.get("name", "")))
            area = c.get("area", 0.0)
            self._area_table.setItem(row, 1, _numeric_item(area, "{:,.1f}"))
            pct = area / total * 100
            pct_color = _CLR_RED if pct > 50 else (_CLR_YELLOW if pct > 25 else _CLR_GREEN)
            self._area_table.setItem(row, 2, _numeric_item(pct, "{:.1f}%", pct_color))

    def set_routing_stats(self, stats: list[dict]) -> None:
        """Populate from dicts: metric, value."""
        self._route_table.setRowCount(0)
        for s in stats:
            row = self._route_table.rowCount()
            self._route_table.insertRow(row)
            self._route_table.setItem(row, 0, _text_item(s.get("metric", "")))
            self._route_table.setItem(row, 1, _text_item(s.get("value", ""), _CLR_BLUE))

    def set_power(self, components: list[dict]) -> None:
        """Populate from dicts: name, power."""
        self._power_table.setRowCount(0)
        for c in components:
            row = self._power_table.rowCount()
            self._power_table.insertRow(row)
            self._power_table.setItem(row, 0, _text_item(c.get("name", "")))
            self._power_table.setItem(row, 1, _numeric_item(c.get("power", 0.0), "{:.2f}"))

    def set_drc_summary(self, total: int, critical: int) -> None:
        if total == 0:
            self._drc_summary.setText(
                f'<span style="color: {_CLR_GREEN}; font-weight: bold;">DRC Clean</span>'
                f'<span style="color: {_SUBTEXT};"> -- No violations found</span>'
            )
        else:
            self._drc_summary.setText(
                f'<span style="color: {_CLR_RED}; font-weight: bold;">{total} violations</span>'
                f'<span style="color: {_SUBTEXT};"> ({critical} critical)</span>'
            )

    def set_density(self, grid: list[list[float]]) -> None:
        self._heatmap.set_grid(grid)


class _DensityHeatmap(QWidget):
    """Simple cell density heatmap placeholder."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self._grid: list[list[float]] = []

    def set_grid(self, grid: list[list[float]]) -> None:
        self._grid = grid
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._grid:
            # Placeholder
            painter = QPainter(self)
            painter.setPen(QColor(_SUBTEXT))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Run placement to generate density map")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rows = len(self._grid)
        cols = len(self._grid[0]) if rows > 0 else 0
        if rows == 0 or cols == 0:
            return

        w = self.width()
        h = self.height()
        cell_w = w / cols
        cell_h = h / rows

        for r in range(rows):
            for c in range(cols):
                val = max(0.0, min(1.0, self._grid[r][c]))
                # Color gradient: dark blue -> green -> yellow -> red
                if val < 0.5:
                    t = val * 2
                    red = int(0 + t * 166)
                    green = int(50 + t * 177)
                    blue = int(180 - t * 30)
                else:
                    t = (val - 0.5) * 2
                    red = int(166 + t * 77)
                    green = int(227 - t * 127)
                    blue = int(150 - t * 150)

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(red, green, blue))
                painter.drawRect(QRectF(c * cell_w, r * cell_h, cell_w + 1, cell_h + 1))


# ── DRC/LVS Tab ────────────────────────────────────────────────────────────


class _DrcLvsTab(QWidget):
    """DRC and LVS checking results."""

    run_drc_requested = Signal()
    run_lvs_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Action buttons
        btn_row = QHBoxLayout()
        self._btn_drc = QPushButton("Run DRC")
        self._btn_drc.setFixedHeight(30)
        self._btn_drc.setStyleSheet(
            f"QPushButton {{ background-color: {_CLR_BLUE}; color: {_CRUST}; font-weight: bold; "
            f"border: none; border-radius: 4px; padding: 4px 16px; }}"
            f"QPushButton:hover {{ background-color: {_CLR_SAPPHIRE}; }}"
        )
        self._btn_drc.clicked.connect(self.run_drc_requested.emit)
        btn_row.addWidget(self._btn_drc)

        self._btn_lvs = QPushButton("Run LVS")
        self._btn_lvs.setFixedHeight(30)
        self._btn_lvs.setStyleSheet(
            f"QPushButton {{ background-color: {_CLR_MAUVE}; color: {_CRUST}; font-weight: bold; "
            f"border: none; border-radius: 4px; padding: 4px 16px; }}"
            f"QPushButton:hover {{ background-color: {_CLR_PINK}; }}"
        )
        self._btn_lvs.clicked.connect(self.run_lvs_requested.emit)
        btn_row.addWidget(self._btn_lvs)
        btn_row.addStretch()

        self._status_label = QLabel("No checks run yet")
        self._status_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        btn_row.addWidget(self._status_label)
        root.addLayout(btn_row)

        # DRC violations table
        root.addWidget(_header_label("DRC Violations"))
        self._drc_table = QTableWidget(0, 5)
        self._drc_table.setHorizontalHeaderLabels(["Rule", "Count", "Layer", "Severity", "Coordinates"])
        _configure_table(self._drc_table)
        self._drc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._drc_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._drc_table)

        # LVS results
        root.addWidget(_header_label("LVS Results"))
        self._lvs_table = QTableWidget(0, 3)
        self._lvs_table.setHorizontalHeaderLabels(["Check", "Status", "Details"])
        _configure_table(self._lvs_table)
        self._lvs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._lvs_table.setMaximumHeight(200)
        root.addWidget(self._lvs_table)

    def set_drc_violations(self, violations: list[dict]) -> None:
        """Populate from dicts: rule, count, layer, severity, x, y."""
        self._drc_table.setRowCount(0)
        total = 0
        for v in violations:
            row = self._drc_table.rowCount()
            self._drc_table.insertRow(row)
            self._drc_table.setItem(row, 0, _text_item(v.get("rule", "")))
            count = v.get("count", 0)
            total += count
            self._drc_table.setItem(row, 1, _numeric_item(count, "{:.0f}"))
            self._drc_table.setItem(row, 2, _text_item(v.get("layer", ""), _SUBTEXT))

            sev = v.get("severity", "warning")
            sev_item = _text_item(sev.upper(), _CLR_RED if sev == "critical" else _CLR_YELLOW)
            font = QFont()
            font.setBold(True)
            sev_item.setFont(font)
            self._drc_table.setItem(row, 3, sev_item)

            x, y = v.get("x", 0), v.get("y", 0)
            self._drc_table.setItem(row, 4, _text_item(f"({x}, {y})", _SUBTEXT))

        if total == 0:
            self._status_label.setText(
                f'<span style="color: {_CLR_GREEN}; font-weight: bold;">DRC Clean</span>'
            )
        else:
            self._status_label.setText(
                f'<span style="color: {_CLR_RED}; font-weight: bold;">{total} DRC violations</span>'
            )

    def set_lvs_results(self, results: list[dict]) -> None:
        """Populate from dicts: check, status, details."""
        self._lvs_table.setRowCount(0)
        for r in results:
            row = self._lvs_table.rowCount()
            self._lvs_table.insertRow(row)
            self._lvs_table.setItem(row, 0, _text_item(r.get("check", "")))

            status = r.get("status", "")
            status_lower = status.lower()
            if status_lower in ("pass", "match"):
                color = _CLR_GREEN
            elif status_lower in ("fail", "mismatch"):
                color = _CLR_RED
            else:
                color = _CLR_YELLOW
            status_item = _text_item(status.upper(), color)
            font = QFont()
            font.setBold(True)
            status_item.setFont(font)
            self._lvs_table.setItem(row, 1, status_item)

            self._lvs_table.setItem(row, 2, _text_item(r.get("details", ""), _SUBTEXT))


# ── Main PhysicalDesignPanel ────────────────────────────────────────────────


class PhysicalDesignPanel(QDockWidget):
    """Dock widget with tabbed physical design controls: Flow, Floorplan,
    Statistics, and DRC/LVS."""

    def __init__(self, title: str = "Physical Design", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._tabs = QTabWidget()
        self._flow = _FlowControlTab()
        self._floorplan = _FloorplanTab()
        self._stats = _StatisticsTab()
        self._drc_lvs = _DrcLvsTab()

        self._tabs.addTab(self._flow, "Flow Control")
        self._tabs.addTab(self._floorplan, "Floorplan")
        self._tabs.addTab(self._stats, "Statistics")
        self._tabs.addTab(self._drc_lvs, "DRC / LVS")

        self.setWidget(self._tabs)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def flow(self) -> _FlowControlTab:
        return self._flow

    @property
    def floorplan(self) -> _FloorplanTab:
        return self._floorplan

    @property
    def statistics(self) -> _StatisticsTab:
        return self._stats

    @property
    def drc_lvs(self) -> _DrcLvsTab:
        return self._drc_lvs

    def update_results(self, results: dict) -> None:
        """Populate all tabs from a physical design results dictionary.

        Expected keys:
            - ``stage_statuses``: list of (status, duration) tuples
            - ``area``: list of category dicts
            - ``routing_stats``: list of metric dicts
            - ``power``: list of power component dicts
            - ``drc_total``, ``drc_critical``: int
            - ``density_grid``: 2D list of floats
            - ``drc_violations``: list of violation dicts
            - ``lvs_results``: list of LVS check dicts
        """
        # Pipeline statuses
        for i, (status, dur) in enumerate(results.get("stage_statuses", [])):
            self._flow.pipeline.set_status(i, status, dur)

        # Statistics
        area = results.get("area", [])
        if area:
            self._stats.set_area(area)
        routing = results.get("routing_stats", [])
        if routing:
            self._stats.set_routing_stats(routing)
        power = results.get("power", [])
        if power:
            self._stats.set_power(power)

        drc_total = results.get("drc_total", -1)
        drc_critical = results.get("drc_critical", 0)
        if drc_total >= 0:
            self._stats.set_drc_summary(drc_total, drc_critical)

        density = results.get("density_grid")
        if density:
            self._stats.set_density(density)

        # DRC/LVS
        violations = results.get("drc_violations", [])
        if violations:
            self._drc_lvs.set_drc_violations(violations)
        lvs = results.get("lvs_results", [])
        if lvs:
            self._drc_lvs.set_lvs_results(lvs)

    def show_demo_data(self) -> None:
        """Load placeholder data for development/demo purposes."""
        import random
        random.seed(42)

        self.update_results({
            "stage_statuses": [
                ("done", "12.3s"),
                ("done", "45.8s"),
                ("done", "28.1s"),
                ("done", "1m 42s"),
                ("running", "..."),
            ],
            "area": [
                {"name": "Standard Cells", "area": 38400.0},
                {"name": "Macros / SRAM", "area": 8192.0},
                {"name": "Filler Cells", "area": 4800.0},
                {"name": "Clock Tree", "area": 2400.0},
                {"name": "Power Grid", "area": 1200.0},
            ],
            "routing_stats": [
                {"metric": "Total Wirelength", "value": "2,345,678 um"},
                {"metric": "Average Net Length", "value": "48.3 um"},
                {"metric": "Max Net Length", "value": "1,892 um"},
                {"metric": "Routing Overflow", "value": "0"},
                {"metric": "Congestion (H)", "value": "12.4%"},
                {"metric": "Congestion (V)", "value": "8.7%"},
            ],
            "power": [
                {"name": "Internal (Switching)", "power": 42.5},
                {"name": "Switching (Net)", "power": 18.3},
                {"name": "Leakage", "power": 3.8},
                {"name": "Total", "power": 64.6},
            ],
            "drc_total": 3,
            "drc_critical": 1,
            "density_grid": [
                [random.uniform(0.3, 0.9) for _ in range(16)] for _ in range(12)
            ],
            "drc_violations": [
                {"rule": "Metal1.MinSpace", "count": 2, "layer": "Metal1", "severity": "warning", "x": 245, "y": 1023},
                {"rule": "Via1.Enclosure", "count": 1, "layer": "Via1", "severity": "critical", "x": 890, "y": 456},
            ],
            "lvs_results": [
                {"check": "Device Count", "status": "Match", "details": "Layout: 8192, Schematic: 8192"},
                {"check": "Net Count", "status": "Match", "details": "Layout: 6543, Schematic: 6543"},
                {"check": "Floating Nets", "status": "Pass", "details": "No floating nets detected"},
                {"check": "Short Circuits", "status": "Pass", "details": "No shorts found"},
                {"check": "Open Circuits", "status": "Fail", "details": "2 open nets: VDD_core, net_1234"},
            ],
        })
