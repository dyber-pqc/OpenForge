"""Layout viewer panel for physical design (DEF/LEF) visualisation.

Displays placed/routed designs from DEF files with cell coloring,
interactive selection, tooltips, legend, and layer visibility controls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStatusBar,
    QToolBar,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QImage, QPixmap

# Layer colour mapping -- SKY130 layer names plus legacy aliases used by the
# older DEF parser so both vocabularies render consistently in the viewer.
LAYER_COLORS: Final[dict[str, str]] = {
    # SKY130 real metal layers
    "li1":  "#7c3aed",   # purple
    "met1": "#3993dd",   # blue
    "met2": "#a1c659",   # green
    "met3": "#e1b73a",   # yellow
    "met4": "#e07b3a",   # orange
    "met5": "#c93c5b",   # red
    # Legacy / alternate names
    "Metal1": "#3993dd",
    "Metal2": "#a1c659",
    "Metal3": "#e1b73a",
    "Metal4": "#e07b3a",
    "Metal5": "#c93c5b",
    "Via1": "#f9e2af",     # yellow
    "Via2": "#94e2d5",     # teal
    "Via3": "#f5c2e7",     # pink
    "Poly": "#eba0ac",     # maroon
    "Diffusion": "#74c7ec",  # sapphire
    "NWell": "#585b70",    # overlay0
    "PWell": "#45475a",    # surface1
    "placement": "#b4befe",  # lavender -- placed cells
    "power":  "#f38ba8",     # red -- VPWR stripes
    "ground": "#89b4fa",     # blue -- VGND stripes
    "pin":    "#f9e2af",     # yellow -- I/O pin markers
}

# Cell type color coding
CELL_TYPE_COLORS: Final[dict[str, tuple[str, str]]] = {
    # (fill_color, label)
    "flipflop": ("#89b4fa", "Flip-Flop"),       # blue
    "combinational": ("#a6e3a1", "Combinational"),  # green
    "complex": ("#f9e2af", "Complex Gate"),       # yellow
    "other": ("#6c7086", "Other"),                # gray/overlay0
}

# Patterns for cell type classification
_FF_PATTERNS = re.compile(
    r"(dfrtp|dfxtp|dfsbp|dfstp|dfbbp|dfbbn|sdfrtp|sdfxtp|"
    r"dlrtp|dlxtp|dlrbn|"
    r"dff|dlatch|latch|flop)",
    re.IGNORECASE,
)
_COMB_PATTERNS = re.compile(
    r"(__and|__or|__nand|__nor|__inv|__xor|__xnor|__mux|__buf|"
    r"and\d|or\d|nand\d|nor\d|inv_|xor\d|xnor\d|mux\d|buf_|buf\d|"
    r"clkbuf|clkinv)",
    re.IGNORECASE,
)
_COMPLEX_PATTERNS = re.compile(
    r"(a2(1|2)(o|oi)|a3(1|2)(o|oi)|o2(1|2)(a|ai)|o3(1|2)(a|ai)|"
    r"a211o|a221o|a311o|a41o|maj3|"
    r"fa_|ha_)",
    re.IGNORECASE,
)

_GRID_COLOR: Final[str] = "#313244"
_BG_COLOR: Final[str] = "#1e1e2e"
_ROW_COLOR: Final[str] = "#313244"

_ZOOM_FACTOR: Final[float] = 1.15

# Custom data roles on QGraphicsItems
_ROLE_LAYER = 0
_ROLE_CELL_NAME = 1
_ROLE_CELL_TYPE = 2
_ROLE_CELL_X = 3
_ROLE_CELL_Y = 4
_ROLE_CELL_ORIENT = 5


def _classify_cell(cell_type: str) -> str:
    """Classify a cell type string into a category."""
    if _FF_PATTERNS.search(cell_type):
        return "flipflop"
    if _COMB_PATTERNS.search(cell_type):
        return "combinational"
    if _COMPLEX_PATTERNS.search(cell_type):
        return "complex"
    return "other"


class _LayoutScene(QGraphicsScene):
    """Custom graphics scene with a grid background."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(_BG_COLOR)))
        self._grid_spacing: float = 50.0
        self._grid_visible: bool = True

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self._grid_visible:
            return

        pen = QPen(QColor(_GRID_COLOR), 0.5)
        pen.setCosmetic(True)
        painter.setPen(pen)

        spacing = self._grid_spacing
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


class _LayoutView(QGraphicsView):
    """Graphics view with mouse-wheel zoom, middle-button pan, and ruler mode."""

    # Signal emitted when ruler measurement completes: distance in microns
    ruler_measured = None  # set by parent if needed

    def __init__(self, scene: _LayoutScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMouseTracking(True)
        self._panning: bool = False
        # Ruler / measurement mode
        self._ruler_mode: bool = False
        self._ruler_start: QPointF | None = None
        self._ruler_line: QGraphicsLineItem | None = None
        self._ruler_text: QGraphicsSimpleTextItem | None = None
        # Scale factor and units (set by parent LayoutPanel)
        self._scale: float = 1.0
        self._units: int = 1000

    def set_ruler_mode(self, enabled: bool) -> None:
        self._ruler_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._clear_ruler()

    def _clear_ruler(self) -> None:
        if self._ruler_line is not None:
            self.scene().removeItem(self._ruler_line)
            self._ruler_line = None
        if self._ruler_text is not None:
            self.scene().removeItem(self._ruler_text)
            self._ruler_text = None
        self._ruler_start = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = _ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / _ZOOM_FACTOR
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        if self._ruler_mode and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._ruler_start is None:
                self._ruler_start = scene_pos
                self._clear_ruler()
            else:
                # Complete measurement
                end = scene_pos
                start = self._ruler_start
                # Calculate distance in microns
                dx_scene = end.x() - start.x()
                dy_scene = end.y() - start.y()
                dist_scene = (dx_scene**2 + dy_scene**2) ** 0.5
                # Convert from scene coords to microns
                dist_um = dist_scene / self._scale * (1.0 / self._units) if self._scale > 0 else 0
                # If scale already divided by units, just invert it
                dist_um = dist_scene / self._scale / (self._units / 1000000.0) if self._scale > 0 else 0
                # Simpler: scene coord / scale = DEF units; DEF units / self._units = microns
                dist_um = dist_scene / self._scale / self._units if self._scale > 0 else 0

                pen = QPen(QColor("#f9e2af"), 2.0)
                pen.setCosmetic(True)
                pen.setStyle(Qt.PenStyle.DashLine)
                self._ruler_line = self.scene().addLine(
                    start.x(), start.y(), end.x(), end.y(), pen
                )
                font = QFont("Segoe UI", 8)
                self._ruler_text = self.scene().addSimpleText(f"{dist_um:.2f} um", font)
                self._ruler_text.setBrush(QColor("#f9e2af"))
                mid_x = (start.x() + end.x()) / 2
                mid_y = (start.y() + end.y()) / 2
                self._ruler_text.setPos(mid_x + 4, mid_y - 12)
                self._ruler_start = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._pan_start = event.position().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
        else:
            # Cell hover tooltip
            scene_pos = self.mapToScene(event.position().toPoint())
            items = self.scene().items(scene_pos)
            for item in items:
                if isinstance(item, QGraphicsRectItem):
                    cell_name = item.data(_ROLE_CELL_NAME)
                    if cell_name:
                        # Tooltip is already set on the item via setToolTip
                        break
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            if self._ruler_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class _LegendWidget(QWidget):
    """Color-coded legend for cell types."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setStyleSheet("background-color: #181825;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        fm = QFontMetrics(font)

        x = 8
        y = (self.height() - 10) // 2
        for cat_key, (color, label) in CELL_TYPE_COLORS.items():
            # Color swatch
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, y, 10, 10), 2, 2)
            x += 14

            # Label
            painter.setPen(QColor("#a6adc8"))
            painter.drawText(QPointF(x, y + 9), label)
            x += fm.horizontalAdvance(label) + 16


class LayoutPanel(QDockWidget):
    """Dock widget hosting a physical layout viewer."""

    # Signal emitted when a cell is clicked: (name, cell_type, x_microns, y_microns)
    cell_selected = Signal(str, str, float, float)

    def __init__(self, title: str = "Layout Viewer", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.AllDockWidgetAreas
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            "QToolBar { background-color: #181825; border-bottom: 1px solid #313244; padding: 2px; }"
        )

        # Zoom controls
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setToolTip("Zoom In")
        btn_zoom_in.setFixedSize(28, 28)
        btn_zoom_in.clicked.connect(self._zoom_in)
        toolbar.addWidget(btn_zoom_in)

        btn_zoom_out = QPushButton("\u2013")  # en-dash as minus
        btn_zoom_out.setToolTip("Zoom Out")
        btn_zoom_out.setFixedSize(28, 28)
        btn_zoom_out.clicked.connect(self._zoom_out)
        toolbar.addWidget(btn_zoom_out)

        btn_fit = QPushButton("Fit")
        btn_fit.setToolTip("Fit to View")
        btn_fit.setFixedSize(40, 28)
        btn_fit.clicked.connect(self._zoom_fit)
        toolbar.addWidget(btn_fit)

        toolbar.addSeparator()

        # Toggle: Show Cell Names
        self._names_check = QCheckBox("Names")
        self._names_check.setChecked(False)
        self._names_check.setToolTip("Show cell instance names")
        self._names_check.toggled.connect(self._toggle_cell_names)
        toolbar.addWidget(self._names_check)

        # Toggle: Show Grid
        self._grid_check = QCheckBox("Grid")
        self._grid_check.setChecked(True)
        self._grid_check.toggled.connect(self._toggle_grid)
        toolbar.addWidget(self._grid_check)

        # Toggle: Show Rows
        self._rows_check = QCheckBox("Rows")
        self._rows_check.setChecked(True)
        self._rows_check.setToolTip("Show placement rows")
        self._rows_check.toggled.connect(self._toggle_rows)
        toolbar.addWidget(self._rows_check)

        toolbar.addSeparator()

        # Layer visibility toggles (Metal1-Metal5)
        self._layer_checks: dict[str, QCheckBox] = {}
        for layer_name in ("Metal1", "Metal2", "Metal3", "Metal4", "Metal5"):
            cb = QCheckBox(layer_name)
            cb.setChecked(True)
            color = LAYER_COLORS.get(layer_name, "#cdd6f4")
            cb.setStyleSheet(f"QCheckBox {{ color: {color}; }}")
            cb.toggled.connect(lambda checked, ln=layer_name: self._toggle_layer(ln, checked))
            toolbar.addWidget(cb)
            self._layer_checks[layer_name] = cb

        toolbar.addSeparator()

        # Additional layer toggles (via, poly, diffusion) -- Magic-style
        for layer_name in ("Via1", "Via2", "Via3", "Via4", "Poly", "Diffusion"):
            cb = QCheckBox(layer_name)
            cb.setChecked(True)
            color = LAYER_COLORS.get(layer_name, "#cdd6f4")
            cb.setStyleSheet(f"QCheckBox {{ color: {color}; }}")
            cb.toggled.connect(lambda checked, ln=layer_name: self._toggle_layer(ln, checked))
            toolbar.addWidget(cb)
            self._layer_checks[layer_name] = cb

        toolbar.addSeparator()

        # Ruler / measurement tool
        self._ruler_btn = QPushButton("Ruler")
        self._ruler_btn.setToolTip("Measure distance between two points (click start, click end)")
        self._ruler_btn.setFixedHeight(28)
        self._ruler_btn.setCheckable(True)
        self._ruler_btn.toggled.connect(self._toggle_ruler_mode)
        toolbar.addWidget(self._ruler_btn)

        toolbar.addSeparator()

        # Density heatmap toggle
        self._density_btn = QPushButton("Density")
        self._density_btn.setToolTip("Show placement density heatmap overlay")
        self._density_btn.setFixedHeight(28)
        self._density_btn.setCheckable(True)
        self._density_btn.toggled.connect(self._toggle_density_overlay)
        toolbar.addWidget(self._density_btn)

        # Congestion overlay toggle
        self._congestion_btn = QPushButton("Congestion")
        self._congestion_btn.setToolTip("Show routing congestion heatmap")
        self._congestion_btn.setFixedHeight(28)
        self._congestion_btn.setCheckable(True)
        self._congestion_btn.toggled.connect(self._toggle_congestion_overlay)
        toolbar.addWidget(self._congestion_btn)

        toolbar.addSeparator()

        # Search box -- find cells by name
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Find cell...")
        self._search_edit.setFixedWidth(160)
        self._search_edit.setFixedHeight(26)
        self._search_edit.returnPressed.connect(self._on_search)
        toolbar.addWidget(self._search_edit)

        # Cell type filter
        self._type_filter = QComboBox()
        self._type_filter.addItems(
            ["All cells", "Flip-flops", "Buffers", "Fillers", "Logic only"]
        )
        self._type_filter.setFixedHeight(26)
        self._type_filter.currentTextChanged.connect(self._on_type_filter)
        toolbar.addWidget(self._type_filter)

        toolbar.addSeparator()

        # Load DEF button
        btn_load = QPushButton("Load DEF...")
        btn_load.setToolTip("Open a DEF file")
        btn_load.setFixedHeight(28)
        btn_load.clicked.connect(self._on_load_def_dialog)
        toolbar.addWidget(btn_load)

        layout.addWidget(toolbar)

        # Scene and view
        self._scene = _LayoutScene()
        self._scene.setSceneRect(-500, -500, 2000, 2000)
        self._view = _LayoutView(self._scene)
        layout.addWidget(self._view)

        # Legend
        self._legend = _LegendWidget()
        layout.addWidget(self._legend)

        # Status bar showing cursor coordinates in microns
        self._status = QLabel("  ready")
        self._status.setStyleSheet(
            "background-color: #181825; color: #a6adc8; padding: 2px 8px;"
            "border-top: 1px solid #313244; font-family: Consolas, monospace;"
        )
        self._status.setFixedHeight(20)
        layout.addWidget(self._status)

        self.setWidget(container)

        # Track items by layer for visibility toggling
        self._layer_items: dict[str, list[QGraphicsItem]] = {}
        # Track cell name text items
        self._cell_name_items: list[QGraphicsSimpleTextItem] = []
        # Track row items
        self._row_items: list[QGraphicsItem] = []
        # Track cell rectangles for click selection
        self._cell_rects: list[QGraphicsRectItem] = []
        # DEF data cache for net lookups
        self._def_data: Any = None
        # Parsed DefDesign (from new format.def_parser), if available
        self._design: Any = None
        # Density / congestion overlay graphics items
        self._density_item: QGraphicsPixmapItem | None = None
        self._congestion_item: QGraphicsPixmapItem | None = None
        # Pin markers and special-net items (tracked for layer toggles)
        self._pin_items: list[QGraphicsItem] = []
        # Scale factor from DEF units to scene coords
        self._scale: float = 1.0
        # DEF units per micron
        self._units: int = 1000
        # Wire up cursor tracking for the status bar
        self._view.mouseMoveEvent = self._wrap_view_move(  # type: ignore[assignment]
            self._view.mouseMoveEvent
        )

    # ── Public API ─────────────────────────────────────────────────

    def load_def(self, def_file: str) -> None:
        """Load a DEF file and render its physical design contents."""
        from openforge.parsers.def_parser import DEFParser

        parser = DEFParser()
        data = parser.parse(Path(def_file))
        self._def_data = data
        self._units = data.units

        self.clear()

        # Scale from DEF units to scene coordinates.
        # DEF coordinates are in database units (usually 1000 per micron).
        # We scale down so the layout fits nicely in the viewer.
        scale = 1.0 / max(data.units / 100, 1)
        self._scale = scale

        # Draw die area boundary
        if data.die_area and data.die_area != (0, 0, 0, 0):
            x0, y0, x1, y1 = data.die_area
            die_color = QColor("#585b70")  # surface2
            die_pen = QPen(die_color, 2.0)
            die_pen.setCosmetic(True)
            die_brush = QBrush(QColor(88, 91, 112, 20))
            self._scene.addRect(
                QRectF(
                    x0 * scale, y0 * scale,
                    (x1 - x0) * scale, (y1 - y0) * scale,
                ),
                die_pen, die_brush,
            )
            # Adjust scene rect to die area with margin
            margin = max((x1 - x0), (y1 - y0)) * scale * 0.05
            self._scene.setSceneRect(
                x0 * scale - margin, y0 * scale - margin,
                (x1 - x0) * scale + 2 * margin,
                (y1 - y0) * scale + 2 * margin,
            )

        # Draw placement rows
        for row in data.rows:
            self._draw_row(row, scale)

        # Attempt to load LEF for macro sizes
        macro_sizes = self._try_load_lef_sizes(def_file)

        # Draw placed components with color coding
        for comp in data.components:
            if comp.placed or comp.fixed:
                category = _classify_cell(comp.cell_type)
                fill_color = CELL_TYPE_COLORS[category][0]

                # Determine cell size from LEF macros if available
                w, h = 10.0, 10.0  # default size in scene coords
                macro_size = macro_sizes.get(comp.cell_type)
                if macro_size:
                    # macro_size is in microns, convert to DEF units then scale
                    w = macro_size[0] * data.units * scale
                    h = macro_size[1] * data.units * scale
                else:
                    # Estimate size based on cell name heuristic
                    w = 10.0
                    h = 10.0

                self._add_placed_cell(
                    comp.name, comp.cell_type,
                    comp.x * scale, comp.y * scale,
                    w, h,
                    fill_color,
                    comp.orientation,
                    comp.x / data.units, comp.y / data.units,
                )

        # Draw routed nets
        for net in data.nets:
            for seg in net.routed_segments:
                if len(seg.points) >= 2:
                    points = [(p[0] * scale, p[1] * scale) for p in seg.points]
                    layer = seg.layer if seg.layer else "Metal1"
                    self.add_net(points, layer)

        # Set ruler scale info
        self._view._scale = scale
        self._view._units = data.units

        # Hide cell names by default
        self._toggle_cell_names(self._names_check.isChecked())
        # Show/hide rows based on checkbox
        self._toggle_rows(self._rows_check.isChecked())

        # Also parse with the comprehensive format.def_parser so we can
        # drive density/congestion overlays, pin markers, and power stripes.
        try:
            from openforge.format.def_parser import parse_def as _parse_def_full
            self._design = _parse_def_full(def_file)
            self._draw_pin_markers()
            self._draw_special_nets()
        except Exception:
            self._design = None

        self._status.setText(
            f"  {Path(def_file).name}   die: "
            f"{(data.die_area[2] - data.die_area[0]) / data.units:.1f} x "
            f"{(data.die_area[3] - data.die_area[1]) / data.units:.1f} um   "
            f"cells: {len(data.components)}"
        )

        self._zoom_fit()

    def add_net(
        self, points: list[tuple[float, float]], layer: str = "Metal1"
    ) -> list[QGraphicsLineItem]:
        """Add a net (polyline) to the layout."""
        color = QColor(LAYER_COLORS.get(layer, "#cdd6f4"))
        pen = QPen(color, 1.5)
        pen.setCosmetic(True)

        lines: list[QGraphicsLineItem] = []
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            line = self._scene.addLine(x1, y1, x2, y2, pen)
            line.setToolTip(f"net ({layer})")
            line.setData(_ROLE_LAYER, layer)
            self._layer_items.setdefault(layer, []).append(line)
            lines.append(line)
        return lines

    def clear(self) -> None:
        """Remove all layout items from the scene."""
        self._scene.clear()
        self._layer_items.clear()
        self._cell_name_items.clear()
        self._row_items.clear()
        self._cell_rects.clear()
        self._def_data = None

    # ── Internal ───────────────────────────────────────────────────

    def _try_load_lef_sizes(self, def_file: str) -> dict[str, tuple[float, float]]:
        """Try to find and parse a LEF file to get macro sizes."""
        sizes: dict[str, tuple[float, float]] = {}
        try:
            from openforge.parsers.lef import LEFParser

            def_path = Path(def_file)
            # Look for LEF files in common locations
            search_dirs = [
                def_path.parent,
                def_path.parent.parent,
                def_path.parent.parent / "share" / "pdk" / "sky130" / "lef",
                Path(__file__).resolve().parents[4] / "share" / "pdk" / "sky130" / "lef",
            ]

            lef_files: list[Path] = []
            for d in search_dirs:
                if d.exists():
                    lef_files.extend(d.glob("*.lef"))
                    lef_files.extend(d.glob("*.tlef"))

            parser = LEFParser()
            for lef_file in lef_files[:5]:  # limit to avoid long load times
                try:
                    lef_data = parser.parse(lef_file)
                    for macro in lef_data.macros:
                        if macro.size_width > 0 and macro.size_height > 0:
                            sizes[macro.name] = (macro.size_width, macro.size_height)
                except Exception:
                    continue
        except ImportError:
            pass
        return sizes

    def _add_placed_cell(
        self,
        name: str,
        cell_type: str,
        x: float,
        y: float,
        w: float,
        h: float,
        fill_color: str,
        orientation: str,
        x_microns: float,
        y_microns: float,
    ) -> QGraphicsRectItem:
        """Add a placed cell rectangle with color coding and metadata."""
        color = QColor(fill_color)
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 60))
        pen = QPen(color, 1.0)
        pen.setCosmetic(True)

        rect = self._scene.addRect(QRectF(x, y, w, h), pen, brush)
        category = _classify_cell(cell_type)
        cat_label = CELL_TYPE_COLORS[category][1]
        rect.setToolTip(
            f"{name}\n"
            f"Type: {cell_type}\n"
            f"Category: {cat_label}\n"
            f"Position: ({x_microns:.2f}, {y_microns:.2f}) um\n"
            f"Orientation: {orientation}"
        )
        rect.setData(_ROLE_LAYER, "placement")
        rect.setData(_ROLE_CELL_NAME, name)
        rect.setData(_ROLE_CELL_TYPE, cell_type)
        rect.setData(_ROLE_CELL_X, x_microns)
        rect.setData(_ROLE_CELL_Y, y_microns)
        rect.setData(_ROLE_CELL_ORIENT, orientation)
        rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        rect.setCursor(Qt.CursorShape.PointingHandCursor)

        self._layer_items.setdefault("placement", []).append(rect)
        self._cell_rects.append(rect)

        # Cell name label (hidden by default, toggled via toolbar)
        font = QFont("Segoe UI", 5)
        label = self._scene.addSimpleText(name, font)
        label.setBrush(QColor("#cdd6f4"))
        label.setPos(x + 1, y + 1)
        label.setVisible(False)
        label.setData(_ROLE_LAYER, "placement")
        self._cell_name_items.append(label)

        return rect

    def _draw_row(self, row: Any, scale: float) -> None:
        """Draw a placement row as a thin horizontal rectangle."""
        from openforge.parsers.def_parser import DEFRow

        if not isinstance(row, DEFRow):
            return

        x = row.origin_x * scale
        y = row.origin_y * scale
        w = row.num_x * row.step_x * scale if row.step_x > 0 else 100 * scale
        h = row.step_y * scale if row.step_y > 0 else 5 * scale
        # If step_y is 0, use a reasonable default row height
        if h <= 0:
            h = 2.0

        color = QColor(_ROW_COLOR)
        pen = QPen(color, 0.5)
        pen.setCosmetic(True)
        brush = QBrush(QColor(49, 50, 68, 15))  # very faint fill

        rect = self._scene.addRect(QRectF(x, y, w, h), pen, brush)
        rect.setToolTip(f"Row: {row.name} (site: {row.site})")
        rect.setZValue(-1)  # behind cells
        self._row_items.append(rect)

    def _on_load_def_dialog(self) -> None:
        """Open file dialog to select a DEF file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DEF File", "",
            "DEF Files (*.def);;All Files (*)",
        )
        if path:
            self.load_def(path)

    def _zoom_in(self) -> None:
        self._view.scale(_ZOOM_FACTOR, _ZOOM_FACTOR)

    def _zoom_out(self) -> None:
        self._view.scale(1.0 / _ZOOM_FACTOR, 1.0 / _ZOOM_FACTOR)

    def _zoom_fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return
        self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _toggle_grid(self, visible: bool) -> None:
        self._scene.set_grid_visible(visible)

    def _toggle_layer(self, layer: str, visible: bool) -> None:
        for item in self._layer_items.get(layer, []):
            item.setVisible(visible)

    def _toggle_cell_names(self, visible: bool) -> None:
        for item in self._cell_name_items:
            item.setVisible(visible)

    def _toggle_rows(self, visible: bool) -> None:
        for item in self._row_items:
            item.setVisible(visible)

    def mousePressEvent(self, event) -> None:
        """Handle cell selection on click."""
        super().mousePressEvent(event)
        # Check if a cell rect was clicked
        view_pos = self._view.mapFromParent(event.pos())
        scene_pos = self._view.mapToScene(view_pos)
        items = self._scene.items(scene_pos)
        for item in items:
            if isinstance(item, QGraphicsRectItem):
                cell_name = item.data(_ROLE_CELL_NAME)
                cell_type = item.data(_ROLE_CELL_TYPE)
                if cell_name and cell_type:
                    x_um = item.data(_ROLE_CELL_X) or 0.0
                    y_um = item.data(_ROLE_CELL_Y) or 0.0
                    # Highlight selected cell
                    self._highlight_cell(item)
                    # Emit signal for Properties panel
                    self.cell_selected.emit(cell_name, cell_type, float(x_um), float(y_um))
                    break

    def _highlight_cell(self, selected: QGraphicsRectItem) -> None:
        """Highlight the selected cell, dim others."""
        for rect in self._cell_rects:
            cell_type = rect.data(_ROLE_CELL_TYPE) or ""
            category = _classify_cell(cell_type)
            fill_color = CELL_TYPE_COLORS[category][0]
            color = QColor(fill_color)
            if rect is selected:
                # Bright highlight
                brush = QBrush(QColor(color.red(), color.green(), color.blue(), 150))
                pen = QPen(QColor("#cdd6f4"), 2.0)
                pen.setCosmetic(True)
            else:
                brush = QBrush(QColor(color.red(), color.green(), color.blue(), 60))
                pen = QPen(color, 1.0)
                pen.setCosmetic(True)
            rect.setBrush(brush)
            rect.setPen(pen)

    def _toggle_ruler_mode(self, enabled: bool) -> None:
        """Toggle ruler measurement mode."""
        self._view.set_ruler_mode(enabled)

    # ── DRC Violation Overlay (Task 3.1) ──────────────────────────────

    def show_drc_violations(self, violations: list[dict]) -> None:
        """Draw red markers/boxes at DRC violation locations on the layout.

        Each violation dict has: {x, y, width, height, layer, rule, message}
        """
        # Remove previous DRC markers
        self._clear_drc_markers()
        scale = self._scale
        for v in violations:
            x = v.get("x", 0) * scale
            y = v.get("y", 0) * scale
            w = v.get("width", 10) * scale
            h = v.get("height", 10) * scale
            rule = v.get("rule", "DRC")
            msg = v.get("message", "")

            # Red semi-transparent box
            pen = QPen(QColor("#f38ba8"), 2.0)
            pen.setCosmetic(True)
            brush = QBrush(QColor(243, 139, 168, 40))
            rect = self._scene.addRect(QRectF(x, y, max(w, 5), max(h, 5)), pen, brush)
            rect.setToolTip(f"DRC: {rule}\n{msg}")
            rect.setZValue(100)  # above everything
            rect.setData(_ROLE_LAYER, "_drc_marker")
            self._layer_items.setdefault("_drc_marker", []).append(rect)

            # Small X marker at center
            cx, cy = x + w / 2, y + h / 2
            marker_pen = QPen(QColor("#f38ba8"), 1.5)
            marker_pen.setCosmetic(True)
            sz = max(3.0, min(w, h) * 0.3)
            l1 = self._scene.addLine(cx - sz, cy - sz, cx + sz, cy + sz, marker_pen)
            l2 = self._scene.addLine(cx - sz, cy + sz, cx + sz, cy - sz, marker_pen)
            l1.setZValue(101)
            l2.setZValue(101)
            l1.setData(_ROLE_LAYER, "_drc_marker")
            l2.setData(_ROLE_LAYER, "_drc_marker")
            self._layer_items.setdefault("_drc_marker", []).append(l1)
            self._layer_items.setdefault("_drc_marker", []).append(l2)

    def _clear_drc_markers(self) -> None:
        """Remove all DRC violation overlay items."""
        for item in self._layer_items.get("_drc_marker", []):
            self._scene.removeItem(item)
        self._layer_items["_drc_marker"] = []

    # ── Parasitic Extraction Display (Task 3.2) ──────────────────────

    def show_parasitics(self, rc_data: dict) -> None:
        """Color-code nets by RC delay. Green=fast, yellow=medium, red=slow.

        rc_data: {net_name: delay_ns}
        """
        if not rc_data:
            return
        max_delay = max(rc_data.values()) if rc_data.values() else 1.0
        if max_delay <= 0:
            max_delay = 1.0

        # Re-color existing net lines based on delay
        for layer_name, items in self._layer_items.items():
            if layer_name.startswith("Metal") or layer_name.startswith("Via"):
                for item in items:
                    if isinstance(item, QGraphicsLineItem):
                        tooltip = item.toolTip()
                        # Extract net name from tooltip if present
                        for net_name, delay in rc_data.items():
                            if net_name in tooltip:
                                ratio = delay / max_delay
                                if ratio < 0.33:
                                    color = QColor("#a6e3a1")  # green
                                elif ratio < 0.66:
                                    color = QColor("#f9e2af")  # yellow
                                else:
                                    color = QColor("#f38ba8")  # red
                                pen = QPen(color, 2.0)
                                pen.setCosmetic(True)
                                item.setPen(pen)
                                item.setToolTip(f"{tooltip}\nRC delay: {delay:.3f} ns")
                                break

    # ── Cell info on hover is handled by QGraphicsItem tooltips set in _add_placed_cell

    # ── New overlays and search (Task 3) ─────────────────────────────

    def _wrap_view_move(self, original):
        """Wrap the view's mouseMoveEvent to also update the status bar."""
        def handler(event):  # type: ignore[no-untyped-def]
            original(event)
            try:
                sp = self._view.mapToScene(event.position().toPoint())
                if self._scale > 0 and self._units > 0:
                    x_um = sp.x() / self._scale / self._units
                    y_um = sp.y() / self._scale / self._units
                    self._status.setText(
                        f"  x = {x_um:9.3f} um    y = {y_um:9.3f} um"
                    )
            except Exception:
                pass
        return handler

    def _draw_pin_markers(self) -> None:
        """Draw a small diamond at every top-level I/O pin location."""
        if self._design is None:
            return
        scale = self._scale
        color = QColor(LAYER_COLORS["pin"])
        pen = QPen(color, 1.0)
        pen.setCosmetic(True)
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 180))
        for pin in self._design.pins.values():
            if not pin.placed:
                continue
            cx = pin.x * scale
            cy = pin.y * scale
            s = 6.0
            poly = QPolygonF([
                QPointF(cx, cy - s),
                QPointF(cx + s, cy),
                QPointF(cx, cy + s),
                QPointF(cx - s, cy),
            ])
            item = self._scene.addPolygon(poly, pen, brush)
            item.setToolTip(
                f"Pin: {pin.name}\n"
                f"Net: {pin.net}\n"
                f"Direction: {pin.direction}\n"
                f"Use: {pin.use}"
            )
            item.setZValue(50)
            item.setData(_ROLE_LAYER, "pin")
            self._layer_items.setdefault("pin", []).append(item)
            self._pin_items.append(item)

    def _draw_special_nets(self) -> None:
        """Render power/ground special nets as coloured stripes."""
        if self._design is None:
            return
        scale = self._scale
        for snet in self._design.special_nets.values():
            if snet.is_power:
                layer_key = "power"
            else:
                layer_key = "ground"
            color = QColor(LAYER_COLORS[layer_key])
            pen = QPen(color, 2.0)
            pen.setCosmetic(True)
            for seg in snet.routes:
                if len(seg.points) < 2:
                    continue
                w = seg.width * scale if seg.width > 0 else 3.0
                pen.setWidthF(max(2.0, w))
                for i in range(len(seg.points) - 1):
                    x1, y1, _ = seg.points[i]
                    x2, y2, _ = seg.points[i + 1]
                    line = self._scene.addLine(
                        x1 * scale, y1 * scale, x2 * scale, y2 * scale, pen,
                    )
                    line.setToolTip(f"{snet.name} ({snet.use}) -- {seg.layer}")
                    line.setZValue(-5)
                    line.setData(_ROLE_LAYER, layer_key)
                    self._layer_items.setdefault(layer_key, []).append(line)

    def _toggle_density_overlay(self, enabled: bool) -> None:
        """Show or hide the placement density heatmap over the layout."""
        if self._density_item is not None:
            self._scene.removeItem(self._density_item)
            self._density_item = None
        if not enabled or self._design is None:
            return
        grid, n_cols, n_rows = self._design.density_heatmap(grid_size_um=5.0)
        pix = self._heatmap_pixmap(grid, n_cols, n_rows, base_hue=(247, 118, 142))
        if pix is None:
            return
        w = self._design.width_db * self._scale
        h = self._design.height_db * self._scale
        item = self._scene.addPixmap(pix)
        item.setPos(
            self._design.die_area.x1 * self._scale,
            self._design.die_area.y1 * self._scale,
        )
        item.setScale(min(w / pix.width(), h / pix.height()) if pix.width() and pix.height() else 1.0)
        item.setOpacity(0.45)
        item.setZValue(5)
        self._density_item = item

    def _toggle_congestion_overlay(self, enabled: bool) -> None:
        """Show or hide the routing congestion heatmap."""
        if self._congestion_item is not None:
            self._scene.removeItem(self._congestion_item)
            self._congestion_item = None
        if not enabled or self._design is None:
            return
        grid, n_cols, n_rows = self._design.congestion_heatmap(grid_size_um=5.0)
        pix = self._heatmap_pixmap(grid, n_cols, n_rows, base_hue=(255, 180, 60))
        if pix is None:
            return
        w = self._design.width_db * self._scale
        h = self._design.height_db * self._scale
        item = self._scene.addPixmap(pix)
        item.setPos(
            self._design.die_area.x1 * self._scale,
            self._design.die_area.y1 * self._scale,
        )
        item.setScale(min(w / pix.width(), h / pix.height()) if pix.width() and pix.height() else 1.0)
        item.setOpacity(0.4)
        item.setZValue(6)
        self._congestion_item = item

    @staticmethod
    def _heatmap_pixmap(
        grid: list[list[float]],
        n_cols: int,
        n_rows: int,
        base_hue: tuple[int, int, int] = (247, 118, 142),
    ) -> QPixmap | None:
        """Turn a normalised 2D grid into a QPixmap for overlay drawing."""
        if n_cols <= 0 or n_rows <= 0:
            return None
        img = QImage(n_cols, n_rows, QImage.Format.Format_ARGB32)
        img.fill(0)
        r0, g0, b0 = base_hue
        for row in range(n_rows):
            # Y-flip: scene origin is top-left after fitInView
            src_row = n_rows - 1 - row
            for col in range(n_cols):
                try:
                    v = grid[src_row][col]
                except IndexError:
                    v = 0.0
                if v <= 0:
                    continue
                alpha = int(60 + 180 * v)
                # Blend from dim to bright along the given hue.
                r = int(r0 * v)
                g = int(g0 * v)
                b = int(b0 * v)
                img.setPixel(col, row, (alpha << 24) | (r << 16) | (g << 8) | b)
        return QPixmap.fromImage(img)

    def _on_search(self) -> None:
        """Find a cell by name substring and centre the view on it."""
        query = self._search_edit.text().strip()
        if not query:
            return
        match: QGraphicsRectItem | None = None
        for rect in self._cell_rects:
            name = rect.data(_ROLE_CELL_NAME) or ""
            if query.lower() in name.lower():
                match = rect
                break
        if match is None:
            self._status.setText(f"  no cell matching '{query}'")
            return
        self._highlight_cell(match)
        self._view.centerOn(match)
        name = match.data(_ROLE_CELL_NAME) or ""
        self._status.setText(f"  selected: {name}")

    def _on_type_filter(self, label: str) -> None:
        """Filter visible cells by coarse type category."""
        for rect in self._cell_rects:
            cell_type = rect.data(_ROLE_CELL_TYPE) or ""
            cat = _classify_cell(cell_type)
            ct_lower = cell_type.lower()
            show = True
            if label == "Flip-flops":
                show = cat == "flipflop"
            elif label == "Buffers":
                show = "buf" in ct_lower or "clkbuf" in ct_lower
            elif label == "Fillers":
                show = "fill" in ct_lower or "decap" in ct_lower
            elif label == "Logic only":
                show = not ("fill" in ct_lower or "decap" in ct_lower or "tap" in ct_lower)
            rect.setVisible(show)

    def get_connected_nets(self, cell_name: str) -> list[str]:
        """Return net names connected to a given cell instance."""
        if self._def_data is None:
            return []
        nets: list[str] = []
        for net in self._def_data.nets:
            for comp, pin in net.connections:
                if comp == cell_name:
                    nets.append(net.name)
                    break
        return nets
