"""Layout viewer panel for physical design (DEF/LEF) visualisation."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# Layer colour mapping (Catppuccin Mocha accent-friendly)
LAYER_COLORS: Final[dict[str, str]] = {
    "Metal1": "#89b4fa",   # blue
    "Metal2": "#f38ba8",   # red
    "Metal3": "#a6e3a1",   # green
    "Metal4": "#cba6f7",   # mauve
    "Metal5": "#fab387",   # peach
    "Via1": "#f9e2af",     # yellow
    "Via2": "#94e2d5",     # teal
    "Via3": "#f5c2e7",     # pink
    "Poly": "#eba0ac",     # maroon
    "Diffusion": "#74c7ec",  # sapphire
    "NWell": "#585b70",    # overlay0
    "PWell": "#45475a",    # surface1
    "placement": "#b4befe",  # lavender -- placed cells
}

_GRID_COLOR: Final[str] = "#313244"
_BG_COLOR: Final[str] = "#1e1e2e"

_ZOOM_FACTOR: Final[float] = 1.15


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
    """Graphics view with mouse-wheel zoom and middle-button pan."""

    def __init__(self, scene: _LayoutScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._panning: bool = False

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = _ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / _ZOOM_FACTOR
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
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
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class LayoutPanel(QDockWidget):
    """Dock widget hosting a physical layout viewer."""

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

        # Grid toggle
        self._grid_check = QCheckBox("Grid")
        self._grid_check.setChecked(True)
        self._grid_check.toggled.connect(self._toggle_grid)
        toolbar.addWidget(self._grid_check)

        toolbar.addSeparator()

        # Layer visibility toggles
        self._layer_checks: dict[str, QCheckBox] = {}
        for layer_name in ("Metal1", "Metal2", "Metal3", "Via1", "Poly"):
            cb = QCheckBox(layer_name)
            cb.setChecked(True)
            color = LAYER_COLORS.get(layer_name, "#cdd6f4")
            cb.setStyleSheet(f"QCheckBox {{ color: {color}; }}")
            cb.toggled.connect(lambda checked, ln=layer_name: self._toggle_layer(ln, checked))
            toolbar.addWidget(cb)
            self._layer_checks[layer_name] = cb

        layout.addWidget(toolbar)

        # Scene and view
        self._scene = _LayoutScene()
        self._scene.setSceneRect(-500, -500, 2000, 2000)
        self._view = _LayoutView(self._scene)
        layout.addWidget(self._view)

        self.setWidget(container)

        # Track items by layer for visibility toggling
        self._layer_items: dict[str, list[QGraphicsItem]] = {}

    # ── Public API ─────────────────────────────────────────────────

    def load_def(self, def_file: str) -> None:
        """Load a DEF file and render its physical design contents."""
        from openforge.parsers.def_parser import DEFParser
        from pathlib import Path

        parser = DEFParser()
        data = parser.parse(Path(def_file))

        self.clear()

        # Scale from DEF units to scene coordinates
        scale = 1.0 / max(data.units / 100, 1)

        # Draw die area
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

        # Draw placed components
        for comp in data.components:
            if comp.placed or comp.fixed:
                self.add_cell(
                    comp.name,
                    comp.x * scale, comp.y * scale,
                    10, 10,
                    "placement",
                )

        # Draw routed nets
        for net in data.nets:
            for seg in net.routed_segments:
                if len(seg.points) >= 2:
                    points = [(p[0] * scale, p[1] * scale) for p in seg.points]
                    layer = seg.layer if seg.layer else "Metal1"
                    self.add_net(points, layer)

        self._zoom_fit()

    def add_cell(
        self,
        name: str,
        x: float,
        y: float,
        w: float,
        h: float,
        layer: str = "Metal1",
    ) -> QGraphicsRectItem:
        """Add a rectangular cell to the layout."""
        color = QColor(LAYER_COLORS.get(layer, "#cdd6f4"))
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 60))
        pen = QPen(color, 1.0)
        pen.setCosmetic(True)

        rect = self._scene.addRect(QRectF(x, y, w, h), pen, brush)
        rect.setToolTip(f"{name} ({layer})")
        rect.setData(0, layer)

        self._layer_items.setdefault(layer, []).append(rect)
        return rect

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
            line.setData(0, layer)
            self._layer_items.setdefault(layer, []).append(line)
            lines.append(line)
        return lines

    def clear(self) -> None:
        """Remove all layout items from the scene."""
        self._scene.clear()
        self._layer_items.clear()

    # ── Internal ───────────────────────────────────────────────────

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
