"""IR drop overlay dock widget.

Renders an IrDropMap (from openforge.physical.ir_drop) as a colored heatmap
inside a QLabel/QPainter, with hotspot detection, hover tooltips, and a
sidebar showing statistics and clickable hotspots.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Color scales
# ---------------------------------------------------------------------------


def _scale_jet(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    if t < 0.25:
        f = t / 0.25
        return (0, int(255 * f), 255)
    if t < 0.5:
        f = (t - 0.25) / 0.25
        return (0, 255, int(255 * (1 - f)))
    if t < 0.75:
        f = (t - 0.5) / 0.25
        return (int(255 * f), 255, 0)
    f = (t - 0.75) / 0.25
    return (255, int(255 * (1 - f)), 0)


def _scale_inferno(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    r = int(255 * (t**0.6))
    g = int(255 * (t**2.2) * 0.7)
    b = int(255 * max(0.0, 0.3 - t * 0.3))
    return (r, g, b)


def _scale_grayscale(t: float) -> tuple[int, int, int]:
    v = int(255 * max(0.0, min(1.0, t)))
    return (v, v, v)


_COLOR_SCALES = {
    "Jet (Blue-Red)": _scale_jet,
    "Inferno": _scale_inferno,
    "Grayscale": _scale_grayscale,
}


# ---------------------------------------------------------------------------
# Heatmap canvas
# ---------------------------------------------------------------------------


class _HeatmapCanvas(QFrame):
    """Renders the IR drop heatmap and emits hover/click events."""

    point_hovered = Signal(float, float, float)  # x_um, y_um, drop_mv
    point_clicked = Signal(float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)

        self._ir_map = None
        self._scale_name = "Jet (Blue-Red)"
        self._threshold_mv = 50.0
        self._show_hotspots = True
        self._dark = True
        self._pixmap: QPixmap | None = None

    # -- API ---------------------------------------------------------------

    def set_map(self, ir_map) -> None:
        self._ir_map = ir_map
        self._rebuild_pixmap()
        self.update()

    def set_color_scale(self, name: str) -> None:
        if name in _COLOR_SCALES:
            self._scale_name = name
            self._rebuild_pixmap()
            self.update()

    def set_threshold(self, mv: float) -> None:
        self._threshold_mv = float(mv)
        self.update()

    def set_show_hotspots(self, show: bool) -> None:
        self._show_hotspots = bool(show)
        self.update()

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def export_png(self, path: str) -> bool:
        if self._pixmap is None:
            return False
        return self._pixmap.save(path, "PNG")

    # -- Rendering ---------------------------------------------------------

    def _rebuild_pixmap(self) -> None:
        if self._ir_map is None or not self._ir_map.grid:
            self._pixmap = None
            return

        rows = self._ir_map.num_rows
        cols = self._ir_map.num_cols
        if rows == 0 or cols == 0:
            self._pixmap = None
            return

        max_drop = max(1.0, self._ir_map.max_drop_mv)
        scale_fn = _COLOR_SCALES.get(self._scale_name, _scale_jet)

        img = QImage(cols, rows, QImage.Format.Format_RGB32)
        for r in range(rows):
            row = self._ir_map.grid[r]
            for c in range(cols):
                t = row[c] / max_drop
                rr, gg, bb = scale_fn(t)
                img.setPixelColor(c, rows - 1 - r, QColor(rr, gg, bb))
        self._pixmap = QPixmap.fromImage(img)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        bg = QColor("#1a1a1a") if self._dark else QColor("#fafafa")
        painter.fillRect(self.rect(), bg)

        if self._pixmap is None or self._ir_map is None:
            painter.setPen(QPen(QColor("#888")))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No IR drop map loaded",
            )
            return

        target = self._image_rect()
        painter.drawPixmap(target, self._pixmap, self._pixmap.rect())

        # Border
        painter.setPen(QPen(QColor("#666"), 1))
        painter.drawRect(target)

        # Hotspots
        if self._show_hotspots:
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            for hp in self._ir_map.hotspots:
                if hp.drop_mv < self._threshold_mv:
                    continue
                px = self._um_to_px(hp.x, hp.y)
                if px is None:
                    continue
                painter.drawEllipse(px, 4, 4)

        # Axis labels
        painter.setPen(QPen(QColor("#bbb")))
        f = QFont()
        f.setPointSize(8)
        painter.setFont(f)
        painter.drawText(
            target.left(),
            target.bottom() + 14,
            "0 um",
        )
        painter.drawText(
            target.right() - 60,
            target.bottom() + 14,
            f"{self._ir_map.width_um:.0f} um",
        )
        painter.drawText(
            4,
            target.top() + 10,
            f"{self._ir_map.height_um:.0f} um",
        )

    def _image_rect(self) -> QRect:
        if self._ir_map is None:
            return self.rect()
        margin = 24
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        die_w = self._ir_map.width_um
        die_h = self._ir_map.height_um
        if die_w <= 0 or die_h <= 0:
            return self.rect()
        scale = min(avail_w / die_w, avail_h / die_h)
        w = int(die_w * scale)
        h = int(die_h * scale)
        x = margin + (avail_w - w) // 2
        y = margin + (avail_h - h) // 2
        return QRect(x, y, w, h)

    def _um_to_px(self, x_um: float, y_um: float) -> QPoint | None:
        if self._ir_map is None:
            return None
        rect = self._image_rect()
        if self._ir_map.width_um <= 0 or self._ir_map.height_um <= 0:
            return None
        px = rect.left() + int((x_um / self._ir_map.width_um) * rect.width())
        py = rect.bottom() - int((y_um / self._ir_map.height_um) * rect.height())
        return QPoint(px, py)

    def _px_to_um(self, px: int, py: int) -> tuple[float, float] | None:
        if self._ir_map is None:
            return None
        rect = self._image_rect()
        if not rect.contains(px, py):
            return None
        if rect.width() == 0 or rect.height() == 0:
            return None
        x_um = (px - rect.left()) / rect.width() * self._ir_map.width_um
        y_um = (rect.bottom() - py) / rect.height() * self._ir_map.height_um
        return (x_um, y_um)

    # -- Events ------------------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ir_map is None:
            return
        pos = event.position().toPoint()
        coord = self._px_to_um(pos.x(), pos.y())
        if coord is None:
            self.setToolTip("")
            return
        x_um, y_um = coord
        drop = self._ir_map.get_drop_at(x_um, y_um)
        v = self._ir_map.vdd - drop / 1000.0
        self.setToolTip(f"x={x_um:.1f}um  y={y_um:.1f}um\ndrop={drop:.2f} mV\nV={v:.4f} V")
        self.point_hovered.emit(x_um, y_um, drop)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ir_map is None:
            return
        pos = event.position().toPoint()
        coord = self._px_to_um(pos.x(), pos.y())
        if coord is None:
            return
        x_um, y_um = coord
        drop = self._ir_map.get_drop_at(x_um, y_um)
        self.point_clicked.emit(x_um, y_um, drop)


# ---------------------------------------------------------------------------
# Color legend
# ---------------------------------------------------------------------------


class _ColorLegend(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(40)
        self.setMaximumHeight(50)
        self._scale_name = "Jet (Blue-Red)"
        self._max_mv = 100.0

    def set_scale(self, name: str) -> None:
        self._scale_name = name
        self.update()

    def set_max(self, mv: float) -> None:
        self._max_mv = max(1.0, mv)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect().adjusted(8, 8, -8, -8)
        scale_fn = _COLOR_SCALES.get(self._scale_name, _scale_jet)
        for x in range(rect.width()):
            t = x / max(1, rect.width() - 1)
            r, g, b = scale_fn(t)
            painter.setPen(QPen(QColor(r, g, b)))
            painter.drawLine(rect.left() + x, rect.top(), rect.left() + x, rect.bottom() - 12)
        painter.setPen(QPen(QColor("#bbb")))
        f = QFont()
        f.setPointSize(8)
        painter.setFont(f)
        painter.drawText(rect.left(), rect.bottom(), "0 mV")
        painter.drawText(
            rect.right() - 60,
            rect.bottom(),
            f"{self._max_mv:.0f} mV",
        )


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class IrDropOverlayPanel(QDockWidget):
    """Dock widget that displays an IR drop heatmap overlay."""

    hotspot_clicked = Signal(float, float)  # x, y in um

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("IR Drop")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._ir_map = None
        self._dark = True
        self._build_ui()
        self._wire()
        self.set_theme(True)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # Toolbar
        self._toolbar = QToolBar("IR Drop Tools")
        self._toolbar.addWidget(QLabel("Color Scale:"))
        self.color_combo = QComboBox()
        self.color_combo.addItems(list(_COLOR_SCALES.keys()))
        self._toolbar.addWidget(self.color_combo)

        self._toolbar.addSeparator()
        self._toolbar.addWidget(QLabel("Hotspot Threshold:"))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 500)
        self.threshold_slider.setValue(50)
        self.threshold_slider.setMaximumWidth(180)
        self._toolbar.addWidget(self.threshold_slider)

        self.threshold_label = QLabel("50 mV")
        self.threshold_label.setMinimumWidth(60)
        self._toolbar.addWidget(self.threshold_label)

        self._toolbar.addSeparator()
        self.show_hot_check = QCheckBox("Show hotspots")
        self.show_hot_check.setChecked(True)
        self._toolbar.addWidget(self.show_hot_check)

        root_layout.addWidget(self._toolbar)

        # Splitter: canvas | sidebar
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Canvas
        canvas_wrap = QWidget()
        cw_layout = QVBoxLayout(canvas_wrap)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.setSpacing(2)
        self.canvas = _HeatmapCanvas()
        cw_layout.addWidget(self.canvas, 1)
        self.legend = _ColorLegend()
        cw_layout.addWidget(self.legend)
        splitter.addWidget(canvas_wrap)

        # Sidebar
        sidebar = QWidget()
        sidebar.setMaximumWidth(280)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(8, 8, 8, 8)
        sb.setSpacing(8)

        title = QLabel("Statistics")
        f = QFont()
        f.setBold(True)
        title.setFont(f)
        sb.addWidget(title)

        self.stats_max = QLabel("Max drop: -")
        self.stats_avg = QLabel("Avg drop: -")
        self.stats_min_v = QLabel("Min voltage: -")
        self.stats_hot_count = QLabel("Hotspots: 0")
        self.stats_pct = QLabel("Cells > thresh: 0.0%")
        for w in (
            self.stats_max,
            self.stats_avg,
            self.stats_min_v,
            self.stats_hot_count,
            self.stats_pct,
        ):
            sb.addWidget(w)

        sb.addSpacing(6)
        hot_title = QLabel("Hotspots")
        hot_title.setFont(f)
        sb.addWidget(hot_title)
        self.hotspot_list = QListWidget()
        self.hotspot_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        sb.addWidget(self.hotspot_list, 1)

        # Hover info
        sb.addSpacing(4)
        self.hover_label = QLabel("Hover over the map for details")
        self.hover_label.setWordWrap(True)
        sb.addWidget(self.hover_label)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_export = QPushButton("Export PNG")
        self.btn_refresh = QPushButton("Refresh")
        btn_row.addWidget(self.btn_export)
        btn_row.addWidget(self.btn_refresh)
        sb.addLayout(btn_row)

        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([800, 280])

        root_layout.addWidget(splitter, 1)
        self.setWidget(root)

    def _wire(self) -> None:
        self.color_combo.currentTextChanged.connect(self._on_color_change)
        self.threshold_slider.valueChanged.connect(self._on_threshold_change)
        self.show_hot_check.toggled.connect(self.canvas.set_show_hotspots)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_refresh.clicked.connect(self._refresh_stats)
        self.canvas.point_hovered.connect(self._on_hover)
        self.canvas.point_clicked.connect(self._on_canvas_click)
        self.hotspot_list.itemDoubleClicked.connect(self._on_hotspot_double_click)

    # -- Public API -------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self.canvas.set_theme(dark)
        if dark:
            style = """
                QDockWidget { color: #ddd; }
                QWidget { color: #ddd; }
                QFrame { background: #1e1e1e; color: #ddd; border: 1px solid #333; }
                QLabel { color: #ddd; background: transparent; border: none; }
                QListWidget { background: #1e1e1e; color: #ddd; border: 1px solid #333;
                              alternate-background-color: #252525; }
                QListWidget::item:selected { background: #094771; }
                QToolBar { background: #2a2a2a; border: none; spacing: 4px; }
                QPushButton { background: #333; color: #ddd; border: 1px solid #555;
                              padding: 4px 10px; border-radius: 3px; }
                QPushButton:hover { background: #3d3d3d; }
                QComboBox { background: #2a2a2a; color: #ddd; border: 1px solid #444;
                            padding: 2px 4px; }
                QSlider::groove:horizontal { background: #333; height: 6px; border-radius: 3px; }
                QSlider::handle:horizontal { background: #5dade2; width: 14px; margin: -4px 0;
                                             border-radius: 7px; }
                QCheckBox { color: #ddd; }
            """
        else:
            style = """
                QFrame { background: #fafafa; border: 1px solid #ccc; }
            """
        self.setStyleSheet(style)

    def load_ir_map(self, ir_map) -> None:
        """Load and display an IrDropMap."""
        self._ir_map = ir_map
        self.canvas.set_map(ir_map)
        if ir_map is not None:
            self.legend.set_max(ir_map.max_drop_mv)
            self.threshold_slider.setMaximum(max(100, int(ir_map.max_drop_mv) + 10))
        self._refresh_stats()
        self._populate_hotspots()

    # -- Slots ------------------------------------------------------------

    def _on_color_change(self, name: str) -> None:
        self.canvas.set_color_scale(name)
        self.legend.set_scale(name)

    def _on_threshold_change(self, val: int) -> None:
        self.threshold_label.setText(f"{val} mV")
        self.canvas.set_threshold(float(val))
        self._refresh_stats()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export IR Drop PNG",
            "ir_drop.png",
            "PNG Images (*.png)",
        )
        if path:
            self.canvas.export_png(path)

    def _on_hover(self, x: float, y: float, drop: float) -> None:
        if self._ir_map is None:
            return
        v = self._ir_map.vdd - drop / 1000.0
        self.hover_label.setText(
            f"Position: ({x:.1f}, {y:.1f}) um\nDrop: {drop:.2f} mV\nVoltage: {v:.4f} V"
        )

    def _on_canvas_click(self, x: float, y: float, drop: float) -> None:
        self.hotspot_clicked.emit(x, y)

    def _on_hotspot_double_click(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            x, y = data
            self.hotspot_clicked.emit(float(x), float(y))

    # -- Helpers ----------------------------------------------------------

    def _refresh_stats(self) -> None:
        if self._ir_map is None:
            self.stats_max.setText("Max drop: -")
            self.stats_avg.setText("Avg drop: -")
            self.stats_min_v.setText("Min voltage: -")
            self.stats_hot_count.setText("Hotspots: 0")
            self.stats_pct.setText("Cells > thresh: 0.0%")
            return
        threshold = float(self.threshold_slider.value())
        self.stats_max.setText(f"Max drop: {self._ir_map.max_drop_mv:.2f} mV")
        self.stats_avg.setText(f"Avg drop: {self._ir_map.avg_drop_mv:.2f} mV")
        min_v = self._ir_map.vdd - self._ir_map.max_drop_mv / 1000.0
        self.stats_min_v.setText(f"Min voltage: {min_v:.4f} V")
        self.stats_hot_count.setText(f"Hotspots: {len(self._ir_map.hotspots)}")
        pct = self._ir_map.percent_above(threshold)
        self.stats_pct.setText(f"Cells > {threshold:.0f} mV: {pct:.1f}%")

    def _populate_hotspots(self) -> None:
        self.hotspot_list.clear()
        if self._ir_map is None:
            return
        for hp in self._ir_map.hotspots[:100]:
            item = QListWidgetItem(f"({hp.x:7.1f}, {hp.y:7.1f}) um   {hp.drop_mv:6.2f} mV")
            item.setData(Qt.ItemDataRole.UserRole, (hp.x, hp.y))
            color = QColor("#e74c3c") if hp.drop_mv > 100 else QColor("#f39c12")
            item.setForeground(color)
            self.hotspot_list.addItem(item)


__all__ = ["IrDropOverlayPanel"]
