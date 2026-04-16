"""Clock tree synthesis visualization panel with useful-skew display."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


@dataclass
class _SinkView:
    name: str
    x: float
    y: float
    skew_ps: float
    level: int = 0
    parent: Optional[str] = None


def _skew_color(skew_ps: float, max_abs: float) -> QColor:
    """Return a QColor for a sink skew value.

    Blue = early (negative skew), red = late (positive skew),
    white = zero. ``max_abs`` is the normalization value.
    """
    if max_abs <= 0:
        return QColor(240, 240, 240)
    t = max(-1.0, min(1.0, skew_ps / max_abs))
    if t >= 0:
        r = 255
        g = int(255 * (1.0 - t))
        b = int(255 * (1.0 - t))
    else:
        r = int(255 * (1.0 + t))
        g = int(255 * (1.0 + t))
        b = 255
    return QColor(r, g, b)


# ---------------------------------------------------------------------------
# Histogram widget
# ---------------------------------------------------------------------------


class _SkewHistogram(QWidget):
    """Very small histogram widget for sink skew values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self._values: list[float] = []
        self._bins = 20

    def set_values(self, values: list[float]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)
        painter.fillRect(self.rect(), QColor(20, 20, 20))
        if not self._values:
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignCenter, "(no data)"
            )
            return

        lo = min(self._values)
        hi = max(self._values)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        n = self._bins
        hist = [0] * n
        for v in self._values:
            idx = int((v - lo) / (hi - lo) * (n - 1))
            hist[max(0, min(n - 1, idx))] += 1
        peak = max(hist) or 1

        bar_w = rect.width() / n
        max_abs = max(abs(lo), abs(hi), 1.0)
        for i, h in enumerate(hist):
            bar_h = (h / peak) * rect.height()
            x = rect.left() + i * bar_w
            y = rect.bottom() - bar_h
            bin_center = lo + (i + 0.5) * (hi - lo) / n
            color = _skew_color(bin_center, max_abs)
            painter.fillRect(
                QRectF(x + 1, y, max(1.0, bar_w - 2), bar_h),
                QBrush(color),
            )
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f" min {lo:.1f} ps   max {hi:.1f} ps   n={len(self._values)}",
        )


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class CtsAdvancedPanel(QDockWidget):
    """Clock tree synthesis with useful-skew visualization.

    The panel displays the clock tree as either a hierarchical tree or a
    layout-accurate scatter plot. Sinks are coloured by their skew value.
    """

    run_cts_requested = Signal(dict)
    optimize_skew_requested = Signal()

    VIEW_TREE = "Tree"
    VIEW_LAYOUT = "Layout"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clock Tree")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._sinks: list[_SinkView] = []
        self._view_mode = self.VIEW_TREE
        self._result = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(4)

        root_layout.addWidget(self._build_toolbar())

        main_split = QSplitter(Qt.Orientation.Horizontal, root)
        main_split.addWidget(self._build_graphics_area())
        main_split.addWidget(self._build_sidebar())
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)
        root_layout.addWidget(main_split, 1)

        root_layout.addWidget(self._build_histogram_group())
        root_layout.addWidget(self._build_status_row())

        self.setWidget(root)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar("CTS Toolbar", self)
        tb.setIconSize(QSize(16, 16))
        self.run_button = QPushButton("Run CTS")
        self.run_button.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; "
            "padding: 4px 14px; font-weight: bold; border-radius: 4px; }"
        )
        self.run_button.clicked.connect(self._on_run_cts)
        tb.addWidget(self.run_button)

        self.optimize_button = QPushButton("Optimize Skew")
        self.optimize_button.clicked.connect(self.optimize_skew_requested.emit)
        tb.addWidget(self.optimize_button)

        tb.addSeparator()

        tb.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        self.view_combo.addItems([self.VIEW_TREE, self.VIEW_LAYOUT])
        self.view_combo.currentTextChanged.connect(self._on_view_changed)
        tb.addWidget(self.view_combo)

        tb.addSeparator()

        self.useful_skew_check = QCheckBox("Useful skew")
        self.useful_skew_check.setChecked(True)
        tb.addWidget(self.useful_skew_check)

        tb.addWidget(QLabel("  Target skew (ps):"))
        self.target_skew_spin = QDoubleSpinBox()
        self.target_skew_spin.setRange(1.0, 500.0)
        self.target_skew_spin.setValue(50.0)
        self.target_skew_spin.setSingleStep(5.0)
        tb.addWidget(self.target_skew_spin)

        tb.addWidget(QLabel("  Period (ns):"))
        self.period_spin = QDoubleSpinBox()
        self.period_spin.setRange(0.1, 100.0)
        self.period_spin.setValue(10.0)
        self.period_spin.setSingleStep(0.5)
        tb.addWidget(self.period_spin)
        return tb

    def _build_graphics_area(self) -> QWidget:
        container = QFrame(self)
        container.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scene = QGraphicsScene(container)
        self.scene.setBackgroundBrush(QBrush(QColor(25, 25, 35)))
        self.view = QGraphicsView(self.scene, container)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )
        self.view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.view)
        return container

    def _build_sidebar(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        stats = QGroupBox("Statistics", container)
        stats_form = QFormLayout(stats)
        self.stat_buffers = QLabel("0")
        self.stat_max_skew = QLabel("0.0 ps")
        self.stat_avg_skew = QLabel("0.0 ps")
        self.stat_wirelength = QLabel("0 um")
        self.stat_levels = QLabel("0")
        self.stat_savings = QLabel("0.0 ps")
        for widget in (
            self.stat_buffers,
            self.stat_max_skew,
            self.stat_avg_skew,
            self.stat_wirelength,
            self.stat_levels,
            self.stat_savings,
        ):
            f = widget.font()
            f.setBold(True)
            widget.setFont(f)
        stats_form.addRow("Buffers:", self.stat_buffers)
        stats_form.addRow("Max skew:", self.stat_max_skew)
        stats_form.addRow("Avg skew:", self.stat_avg_skew)
        stats_form.addRow("Wirelength:", self.stat_wirelength)
        stats_form.addRow("Tree levels:", self.stat_levels)
        stats_form.addRow("Useful-skew savings:", self.stat_savings)
        layout.addWidget(stats)

        sinks_group = QGroupBox("Sinks", container)
        sinks_layout = QVBoxLayout(sinks_group)
        self.sink_table = QTableWidget(0, 3, sinks_group)
        self.sink_table.setHorizontalHeaderLabels(
            ["Sink", "Skew (ps)", "Level"]
        )
        self.sink_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.sink_table.setAlternatingRowColors(True)
        self.sink_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.sink_table.itemSelectionChanged.connect(self._on_sink_selected)
        sinks_layout.addWidget(self.sink_table)
        layout.addWidget(sinks_group, 1)
        return container

    def _build_histogram_group(self) -> QGroupBox:
        group = QGroupBox("Skew distribution", self)
        layout = QVBoxLayout(group)
        self.histogram = _SkewHistogram(group)
        layout.addWidget(self.histogram)
        return group

    def _build_status_row(self) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("Ready", container)
        self.progress = QProgressBar(container)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.progress, 2)
        return container

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_run_cts(self) -> None:
        params = {
            "useful_skew": self.useful_skew_check.isChecked(),
            "target_skew_ps": float(self.target_skew_spin.value()),
            "period_ns": float(self.period_spin.value()),
        }
        self.progress.setRange(0, 0)
        self.status_label.setText("Running CTS...")
        self.run_cts_requested.emit(params)

    def _on_view_changed(self, text: str) -> None:
        self._view_mode = text
        self._redraw_scene()

    def _on_sink_selected(self) -> None:
        rows = {i.row() for i in self.sink_table.selectedItems()}
        if not rows:
            return
        row = next(iter(rows))
        if 0 <= row < len(self._sinks):
            sink = self._sinks[row]
            self.status_label.setText(
                f"{sink.name}: skew={sink.skew_ps:.2f} ps "
                f"level={sink.level}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_result(self, result) -> None:
        """Populate the panel from a CtsResult-like object."""
        self._result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.stat_buffers.setText(str(getattr(result, "num_buffers", 0)))
        self.stat_max_skew.setText(
            f"{getattr(result, 'max_skew_ps', 0.0):.1f} ps"
        )
        self.stat_avg_skew.setText(
            f"{getattr(result, 'avg_skew_ps', 0.0):.1f} ps"
        )
        self.stat_wirelength.setText(
            f"{getattr(result, 'wirelength_um', 0.0):.0f} um"
        )
        self.stat_levels.setText(str(getattr(result, "levels", 0)))
        self.stat_savings.setText(
            f"{getattr(result, 'skew_savings_ps', 0.0):.1f} ps"
        )

        sinks_raw = list(getattr(result, "sinks", []) or [])
        self._sinks = []
        for idx, s in enumerate(sinks_raw):
            self._sinks.append(
                _SinkView(
                    name=getattr(s, "full_name", str(s)),
                    x=float(getattr(s, "x_um", idx * 10.0)),
                    y=float(getattr(s, "y_um", 0.0)),
                    skew_ps=float(getattr(s, "applied_skew_ps", 0.0)),
                    level=max(1, idx % 4 + 1),
                )
            )
        self._populate_sink_table()
        self._update_histogram()
        self._redraw_scene()
        self.status_label.setText(getattr(result, "summary", "CTS done"))

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _populate_sink_table(self) -> None:
        self.sink_table.setRowCount(len(self._sinks))
        for row, sink in enumerate(self._sinks):
            self.sink_table.setItem(row, 0, QTableWidgetItem(sink.name))
            skew_item = QTableWidgetItem(f"{sink.skew_ps:.1f}")
            skew_item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
            max_abs = max(
                (abs(s.skew_ps) for s in self._sinks), default=1.0
            )
            skew_item.setBackground(_skew_color(sink.skew_ps, max_abs))
            self.sink_table.setItem(row, 1, skew_item)
            self.sink_table.setItem(row, 2, QTableWidgetItem(str(sink.level)))

    def _update_histogram(self) -> None:
        self.histogram.set_values([s.skew_ps for s in self._sinks])

    def _redraw_scene(self) -> None:
        self.scene.clear()
        if not self._sinks:
            item = self.scene.addText(
                "No clock tree loaded. Click 'Run CTS' to synthesize."
            )
            item.setDefaultTextColor(QColor(180, 180, 180))
            return
        if self._view_mode == self.VIEW_LAYOUT:
            self._draw_layout()
        else:
            self._draw_tree()

    def _draw_layout(self) -> None:
        max_abs = max((abs(s.skew_ps) for s in self._sinks), default=1.0)
        xs = [s.x for s in self._sinks] or [0.0]
        ys = [s.y for s in self._sinks] or [0.0]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        w = 600.0
        h = 400.0
        # Bounding rect
        self.scene.addRect(
            0, 0, w, h, QPen(QColor(80, 80, 120)), QBrush(QColor(15, 15, 25))
        )
        root_x = w / 2
        root_y = 20
        root = QGraphicsRectItem(root_x - 12, root_y - 8, 24, 16)
        root.setBrush(QBrush(QColor(255, 215, 0)))
        root.setPen(QPen(QColor(255, 255, 255)))
        self.scene.addItem(root)

        for sink in self._sinks:
            sx = 20 + (sink.x - min_x) / span_x * (w - 40)
            sy = 60 + (sink.y - min_y) / span_y * (h - 80)
            color = _skew_color(sink.skew_ps, max_abs)
            dot = QGraphicsEllipseItem(sx - 4, sy - 4, 8, 8)
            dot.setBrush(QBrush(color))
            dot.setPen(QPen(QColor(0, 0, 0)))
            dot.setToolTip(
                f"{sink.name}\nskew={sink.skew_ps:.2f} ps"
            )
            self.scene.addItem(dot)
            # Line from root to sink
            line = QGraphicsLineItem(root_x, root_y + 8, sx, sy)
            line.setPen(QPen(QColor(120, 120, 180), 0.5))
            self.scene.addItem(line)

        self.view.setSceneRect(-20, -20, w + 40, h + 40)
        self.view.fitInView(
            self.scene.itemsBoundingRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def _draw_tree(self) -> None:
        max_abs = max((abs(s.skew_ps) for s in self._sinks), default=1.0)
        n = len(self._sinks)
        # Rough H-tree: distribute sinks evenly across the bottom.
        w = max(600.0, 20.0 * n)
        h = 420.0
        self.scene.addRect(
            0, 0, w, h, QPen(QColor(80, 80, 120)), QBrush(QColor(15, 15, 25))
        )
        root_x = w / 2
        root_y = 20
        mid_y = h / 2
        bottom_y = h - 40

        # Root buffer
        root_rect = QGraphicsRectItem(root_x - 20, root_y - 10, 40, 20)
        root_rect.setBrush(QBrush(QColor(255, 215, 0)))
        root_rect.setPen(QPen(QColor(255, 255, 255)))
        self.scene.addItem(root_rect)
        root_label = QGraphicsTextItem("root")
        root_label.setDefaultTextColor(QColor(0, 0, 0))
        root_label.setPos(root_x - 14, root_y - 10)
        self.scene.addItem(root_label)

        # Intermediate buffers: 4 branches
        mid_positions: list[QPointF] = []
        for i in range(4):
            mx = (i + 0.5) * (w / 4)
            mid_positions.append(QPointF(mx, mid_y))
            mr = QGraphicsRectItem(mx - 10, mid_y - 6, 20, 12)
            mr.setBrush(QBrush(QColor(100, 150, 255)))
            mr.setPen(QPen(QColor(200, 200, 255)))
            self.scene.addItem(mr)
            line = QGraphicsLineItem(root_x, root_y + 10, mx, mid_y - 6)
            line.setPen(QPen(QColor(180, 180, 220), 1.0))
            self.scene.addItem(line)

        # Sinks on the bottom
        for i, sink in enumerate(self._sinks):
            sx = 20 + (i + 0.5) * ((w - 40) / max(1, n))
            parent = mid_positions[min(len(mid_positions) - 1, i * 4 // max(1, n))]
            color = _skew_color(sink.skew_ps, max_abs)
            dot = QGraphicsEllipseItem(sx - 5, bottom_y - 5, 10, 10)
            dot.setBrush(QBrush(color))
            dot.setPen(QPen(QColor(0, 0, 0)))
            dot.setToolTip(
                f"{sink.name}\nskew={sink.skew_ps:.2f} ps\nlevel={sink.level}"
            )
            self.scene.addItem(dot)
            line = QGraphicsLineItem(
                parent.x(), parent.y() + 6, sx, bottom_y - 5
            )
            line.setPen(QPen(QColor(140, 140, 180), 0.7))
            self.scene.addItem(line)

        self.view.setSceneRect(-20, -20, w + 40, h + 40)
        self.view.fitInView(
            self.scene.itemsBoundingRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(900, 720)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._sinks:
            self.view.fitInView(
                self.scene.itemsBoundingRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )


__all__ = ["CtsAdvancedPanel"]
