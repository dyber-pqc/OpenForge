"""PCB 3D viewer widget.

Tries Qt3D first; falls back to QOpenGLWidget; falls back to an
isometric 2D projection via QGraphicsView as a last resort. The
exposed API (`set_board`, `toggle_layer`, `reset_view`, `explode`,
`export_png`) is identical across backends.
"""
from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Backend detection
_HAS_QT3D = False
try:  # pragma: no cover - optional
    from PySide6.Qt3DCore import Qt3DCore  # noqa: F401
    from PySide6.Qt3DExtras import Qt3DExtras  # noqa: F401
    _HAS_QT3D = True
except Exception:  # pragma: no cover
    _HAS_QT3D = False

_HAS_GL = False
try:  # pragma: no cover - optional
    from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: F401
    _HAS_GL = True
except Exception:  # pragma: no cover
    _HAS_GL = False


# Layer colours (RGBA) used by all backends
LAYER_COLORS: dict[str, tuple[int, int, int, int]] = {
    "F.Cu": (184, 115, 51, 220),
    "B.Cu": (184, 115, 51, 220),
    "In1.Cu": (150, 90, 30, 180),
    "In2.Cu": (150, 90, 30, 180),
    "substrate": (0, 90, 40, 230),
    "F.Mask": (0, 80, 30, 120),
    "B.Mask": (0, 80, 30, 120),
    "F.SilkS": (240, 240, 240, 255),
    "B.SilkS": (240, 240, 240, 255),
    "via": (160, 100, 40, 255),
    "component": (30, 30, 30, 230),
    "outline": (255, 255, 255, 255),
}


# ---------------------------------------------------------------------------
class Pcb3dViewer(QWidget):
    """PCB 3D viewer with automatic backend selection.

    Public API:
      set_board(board)      -- attach an openforge.pcb.model.PcbBoard
      toggle_layer(name, visible)
      reset_view()
      explode(enabled: bool)
      export_png(path)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._board: Any = None
        self._exploded = False
        self._visible_layers: dict[str, bool] = {
            "F.Cu": True,
            "B.Cu": True,
            "In1.Cu": True,
            "In2.Cu": True,
            "substrate": True,
            "F.SilkS": True,
            "B.SilkS": True,
            "components": True,
            "vias": True,
        }
        self._rotation_x = 25.0
        self._rotation_z = -30.0
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._last_mouse: QPointF | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # Top controls
        controls = QHBoxLayout()
        self._reset_btn = QPushButton("Reset View")
        self._explode_btn = QPushButton("Explode")
        self._explode_btn.setCheckable(True)
        self._export_btn = QPushButton("Export PNG")
        controls.addWidget(self._reset_btn)
        controls.addWidget(self._explode_btn)
        controls.addWidget(self._export_btn)
        controls.addStretch(1)

        self._backend_label = QLabel()
        backend = "Qt3D" if _HAS_QT3D else ("OpenGL" if _HAS_GL else "Isometric 2D")
        self._backend_label.setText(f"Backend: {backend}")
        self._backend_label.setStyleSheet("color: #888;")
        controls.addWidget(self._backend_label)
        outer.addLayout(controls)

        # Layer toggles
        layers_row = QHBoxLayout()
        self._layer_checks: dict[str, QCheckBox] = {}
        for name in (
            "F.Cu",
            "B.Cu",
            "In1.Cu",
            "In2.Cu",
            "F.SilkS",
            "B.SilkS",
            "vias",
            "components",
        ):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.toggled.connect(
                lambda checked, n=name: self.toggle_layer(n, checked)
            )
            layers_row.addWidget(cb)
            self._layer_checks[name] = cb
        layers_row.addStretch(1)
        outer.addLayout(layers_row)

        # Canvas (isometric fallback — always works)
        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setRenderHint(QPainter.SmoothPixmapTransform)
        self._view.setBackgroundBrush(QBrush(QColor(18, 18, 24)))
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        outer.addWidget(self._view, 1)

        # Elevation slider (for explode)
        elev_row = QHBoxLayout()
        elev_row.addWidget(QLabel("Explode:"))
        self._elev_slider = QSlider(Qt.Horizontal)
        self._elev_slider.setRange(0, 40)
        self._elev_slider.setValue(0)
        elev_row.addWidget(self._elev_slider, 1)
        outer.addLayout(elev_row)

        self._reset_btn.clicked.connect(self.reset_view)
        self._explode_btn.toggled.connect(self._on_explode_toggled)
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._elev_slider.valueChanged.connect(lambda _: self._render())

    # ------------------------------------------------------------------
    def set_board(self, board: Any) -> None:
        self._board = board
        self._render()

    def toggle_layer(self, name: str, visible: bool) -> None:
        self._visible_layers[name] = visible
        self._render()

    def reset_view(self) -> None:
        self._rotation_x = 25.0
        self._rotation_z = -30.0
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._exploded = False
        self._explode_btn.setChecked(False)
        self._elev_slider.setValue(0)
        self._render()
        if self._scene.itemsBoundingRect().isValid():
            self._view.fitInView(
                self._scene.itemsBoundingRect(), Qt.KeepAspectRatio
            )

    def explode(self, enabled: bool) -> None:
        self._exploded = enabled
        self._explode_btn.setChecked(enabled)
        self._elev_slider.setValue(20 if enabled else 0)
        self._render()

    def _on_explode_toggled(self, checked: bool) -> None:
        self.explode(checked)

    def _on_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export 3D View", "pcb_3d.png", "PNG (*.png)"
        )
        if path:
            self.export_png(path)

    def export_png(self, path: str) -> str:
        rect = self._scene.itemsBoundingRect()
        if not rect.isValid():
            rect = QRectF(0, 0, 800, 600)
        img = QImage(
            max(int(rect.width() * 2), 800),
            max(int(rect.height() * 2), 600),
            QImage.Format_ARGB32,
        )
        img.fill(QColor(18, 18, 24))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter, QRectF(img.rect()), rect)
        painter.end()
        img.save(path)
        return path

    # ------------------------------------------------------------------
    # Isometric rendering
    # ------------------------------------------------------------------
    def _project(self, x: float, y: float, z: float) -> QPointF:
        """Simple isometric-ish projection."""
        rx = math.radians(self._rotation_x)
        rz = math.radians(self._rotation_z)
        # Rotate around Z
        x1 = x * math.cos(rz) - y * math.sin(rz)
        y1 = x * math.sin(rz) + y * math.cos(rz)
        # Apply X-rotation pitch
        y2 = y1 * math.cos(rx) - z * math.sin(rx)
        # Scale
        s = 3.0 * self._zoom
        return QPointF(x1 * s + self._pan.x(), -y2 * s + self._pan.y())

    def _polygon_from_rect(
        self, x0: float, y0: float, x1: float, y1: float, z: float
    ) -> QPolygonF:
        return QPolygonF(
            [
                self._project(x0, y0, z),
                self._project(x1, y0, z),
                self._project(x1, y1, z),
                self._project(x0, y1, z),
            ]
        )

    def _render(self) -> None:
        self._scene.clear()
        board = self._board
        if board is None:
            # Show placeholder
            self._scene.addText("No board loaded").setDefaultTextColor(
                QColor(200, 200, 200)
            )
            return

        outline = list(getattr(board, "outline", []) or [])
        if not outline:
            bx0, by0, bx1, by1 = board.bounding_box()
            outline = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]

        sep = float(self._elev_slider.value()) / 10.0  # mm separation

        # Substrate (FR-4)
        if self._visible_layers.get("substrate", True):
            poly = QPolygonF([self._project(x, y, 0.0) for x, y in outline])
            item = self._scene.addPolygon(
                poly,
                QPen(QColor(*LAYER_COLORS["outline"])),
                QBrush(QColor(*LAYER_COLORS["substrate"])),
            )
            item.setZValue(0)

        # Top copper layer — slab
        top_z = 0.8 + sep
        bot_z = -0.8 - sep

        # Tracks (F.Cu)
        for t in getattr(board, "tracks", []):
            if not self._visible_layers.get(t.layer, True):
                continue
            z = top_z if t.layer.startswith("F.") else bot_z
            color = QColor(*LAYER_COLORS.get(t.layer, (180, 110, 50, 220)))
            p1 = self._project(t.x1_mm, t.y1_mm, z)
            p2 = self._project(t.x2_mm, t.y2_mm, z)
            pen = QPen(color)
            pen.setWidthF(max(t.width_mm * 3.0 * self._zoom, 1.0))
            pen.setCapStyle(Qt.RoundCap)
            line = self._scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), pen)
            line.setZValue(5 if z > 0 else -5)

        # Vias
        if self._visible_layers.get("vias", True):
            for v in getattr(board, "vias", []):
                color = QColor(*LAYER_COLORS["via"])
                p = self._project(v.x_mm, v.y_mm, 0.0)
                r = v.diameter_mm * 3.0 * self._zoom / 2.0
                self._scene.addEllipse(
                    p.x() - r, p.y() - r, r * 2, r * 2,
                    QPen(QColor(40, 20, 0)),
                    QBrush(color),
                )

        # Pads + component bodies
        if self._visible_layers.get("components", True):
            for fp in getattr(board, "footprints", []):
                z = top_z if getattr(fp, "layer", "top") == "top" else bot_z
                # Body: courtyard box
                if fp.courtyard:
                    xs = [p[0] for p in fp.courtyard]
                    ys = [p[1] for p in fp.courtyard]
                    x0 = fp.x_mm + min(xs)
                    x1 = fp.x_mm + max(xs)
                    y0 = fp.y_mm + min(ys)
                    y1 = fp.y_mm + max(ys)
                else:
                    x0 = fp.x_mm - 1.5
                    x1 = fp.x_mm + 1.5
                    y0 = fp.y_mm - 1.0
                    y1 = fp.y_mm + 1.0
                body = self._polygon_from_rect(x0, y0, x1, y1, z + 0.5)
                self._scene.addPolygon(
                    body,
                    QPen(QColor(0, 0, 0)),
                    QBrush(QColor(*LAYER_COLORS["component"])),
                )
                # Pads
                for pad in fp.pads:
                    wx, wy = fp.pad_world_xy(pad)
                    p = self._project(wx, wy, z + 0.02)
                    w = pad.size_x_mm * 3.0 * self._zoom
                    h = pad.size_y_mm * 3.0 * self._zoom
                    self._scene.addRect(
                        p.x() - w / 2,
                        p.y() - h / 2,
                        w,
                        h,
                        QPen(QColor(80, 40, 0)),
                        QBrush(QColor(210, 140, 60, 255)),
                    )

        # Outline frame
        poly = QPolygonF([self._project(x, y, top_z) for x, y in outline])
        pen = QPen(QColor(*LAYER_COLORS["outline"]))
        pen.setWidth(2)
        self._scene.addPolygon(poly, pen, QBrush(Qt.NoBrush))

        # Fit
        rect = self._scene.itemsBoundingRect()
        if rect.isValid():
            self._view.setSceneRect(rect.adjusted(-50, -50, 50, 50))
            self._view.fitInView(rect, Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(640, 480)


__all__ = ["Pcb3dViewer"]
