"""Interactive PCB layout editor (QGraphicsView based).

KiCad pcbnew-inspired dark green canvas with layer toggles, track/via
drawing, zones, measure tool, grid snap, and Gerber export.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.pcb.model import (
        PcbBoard,
        PcbFootprint,
        PcbPad,
        PcbTrack,
        PcbVia,
        PcbZone,
        PcbStackup,
    )
    from openforge.pcb.gerber import GerberExporter
    from openforge.pcb.footprints import FOOTPRINTS
    _HAS_MODEL = True
except Exception:  # pragma: no cover
    _HAS_MODEL = False


# ----------------------------------------------------------------------
# Layer colors (KiCad-ish)
LAYER_COLORS: dict[str, str] = {
    "F.Cu":     "#c83737",
    "B.Cu":     "#4d7fc4",
    "In1.Cu":   "#d4a017",
    "In2.Cu":   "#8a5cff",
    "In3.Cu":   "#00b8a9",
    "In4.Cu":   "#ffa040",
    "F.SilkS":  "#e0e0e0",
    "B.SilkS":  "#a0a0a0",
    "F.Mask":   "#6b4c9a",
    "B.Mask":   "#6b4c9a",
    "F.Paste":  "#909090",
    "B.Paste":  "#707070",
    "Edge.Cuts": "#f0e050",
}

CANVAS_BG = "#0a3d2c"      # dark PCB green
GRID_MINOR = "#0f4a35"
GRID_MAJOR = "#155a41"
HIGHLIGHT = "#ffffff"

# Scene uses pixels; PIX_PER_MM = scale.
PIX_PER_MM = 20.0


# ----------------------------------------------------------------------
class Tool:
    SELECT = "select"
    TRACK = "track"
    VIA = "via"
    PAD = "pad"
    ZONE = "zone"
    MEASURE = "measure"
    DELETE = "delete"
    ROTATE = "rotate"


# ----------------------------------------------------------------------
class PcbScene(QGraphicsScene):
    """QGraphicsScene hosting PCB geometry."""

    cursor_moved = Signal(float, float)  # x_mm, y_mm

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(CANVAS_BG)))
        self.setSceneRect(QRectF(-500, -500, 1000, 1000))
        self.grid_mm: float = 0.25
        self.snap: bool = True
        self.active_layer: str = "F.Cu"
        self.layer_visible: dict[str, bool] = {k: True for k in LAYER_COLORS}
        self.layer_opacity: dict[str, float] = {k: 1.0 for k in LAYER_COLORS}

    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        if self.grid_mm <= 0:
            return
        step = self.grid_mm * PIX_PER_MM
        if step < 3:
            return
        left = math.floor(rect.left() / step) * step
        top = math.floor(rect.top() / step) * step
        pen_minor = QPen(QColor(GRID_MINOR))
        pen_minor.setCosmetic(True)
        pen_major = QPen(QColor(GRID_MAJOR))
        pen_major.setCosmetic(True)
        painter.setPen(pen_minor)
        x = left
        i = 0
        while x < rect.right():
            painter.setPen(pen_major if i % 5 == 0 else pen_minor)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
            i += 1
        y = top
        i = 0
        while y < rect.bottom():
            painter.setPen(pen_major if i % 5 == 0 else pen_minor)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
            i += 1

    # ------------------------------------------------------------------
    def snap_point(self, p: QPointF) -> QPointF:
        if not self.snap or self.grid_mm <= 0:
            return p
        step = self.grid_mm * PIX_PER_MM
        return QPointF(round(p.x() / step) * step, round(p.y() / step) * step)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        p = event.scenePos()
        self.cursor_moved.emit(p.x() / PIX_PER_MM, p.y() / PIX_PER_MM)
        super().mouseMoveEvent(event)


# ----------------------------------------------------------------------
class PcbView(QGraphicsView):
    def __init__(self, scene: PcbScene) -> None:
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)


# ----------------------------------------------------------------------
class PcbLayoutEditor(QWidget):
    """Top-level PCB layout editor widget."""

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if not _HAS_MODEL:  # pragma: no cover
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("PCB model unavailable - install openforge.pcb"))
            return

        self.board: PcbBoard = PcbBoard(
            name="untitled",
            stackup=PcbStackup.two_layer(),
            outline=[(0.0, 0.0), (80.0, 0.0), (80.0, 60.0), (0.0, 60.0)],
        )
        self.board.nets = {0: "", 1: "GND", 2: "VCC", 3: "SIG1"}
        self._current_tool = Tool.SELECT
        self._track_width_mm = 0.25
        self._track_points: list[QPointF] = []
        self._zone_points: list[QPointF] = []
        self._measure_start: Optional[QPointF] = None
        self._temp_item: Optional[QGraphicsItem] = None
        self._active_net_id: int = 1

        self._build_ui()
        self._render_board()

    # ==================================================================
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        self._toolbar = QToolBar()
        self._toolbar.setIconSize(self._toolbar.iconSize())
        outer.addWidget(self._toolbar)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for label, tool in (
            ("Select", Tool.SELECT),
            ("Track", Tool.TRACK),
            ("Via", Tool.VIA),
            ("Pad", Tool.PAD),
            ("Zone", Tool.ZONE),
            ("Measure", Tool.MEASURE),
            ("Delete", Tool.DELETE),
            ("Rotate", Tool.ROTATE),
        ):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tool, btn=b: self._set_tool(t, btn))
            self._toolbar.addWidget(b)
            self._tool_group.addButton(b)
            if tool == Tool.SELECT:
                b.setChecked(True)

        self._toolbar.addSeparator()

        self._toolbar.addWidget(QLabel(" Grid: "))
        self._grid_combo = QComboBox()
        for g in ("off", "0.01", "0.05", "0.1", "0.25", "1.0"):
            self._grid_combo.addItem(g + " mm" if g != "off" else "off")
        self._grid_combo.setCurrentText("0.25 mm")
        self._grid_combo.currentTextChanged.connect(self._on_grid_changed)
        self._toolbar.addWidget(self._grid_combo)

        self._toolbar.addWidget(QLabel(" Width: "))
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.05, 10.0)
        self._width_spin.setDecimals(3)
        self._width_spin.setSingleStep(0.05)
        self._width_spin.setValue(0.25)
        self._width_spin.setSuffix(" mm")
        self._width_spin.valueChanged.connect(lambda v: setattr(self, "_track_width_mm", v))
        self._toolbar.addWidget(self._width_spin)

        self._toolbar.addWidget(QLabel(" Mode: "))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["45", "90", "Free"])
        self._toolbar.addWidget(self._mode_combo)

        self._toolbar.addSeparator()
        act_save = QAction("Save JSON", self)
        act_save.triggered.connect(self._save_json)
        self._toolbar.addAction(act_save)
        act_load = QAction("Load JSON", self)
        act_load.triggered.connect(self._load_json)
        self._toolbar.addAction(act_load)
        act_gbr = QAction("Export Gerber", self)
        act_gbr.triggered.connect(self._export_gerber)
        self._toolbar.addAction(act_gbr)

        # Body: layers | canvas | info
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # Layer panel
        layer_panel = QWidget()
        lp_lay = QVBoxLayout(layer_panel)
        lp_lay.setContentsMargins(6, 6, 6, 6)
        lp_lay.addWidget(QLabel("Layers"))
        self._layer_checks: dict[str, QCheckBox] = {}
        self._layer_radios: dict[str, QRadioButton] = {}
        self._layer_group = QButtonGroup(self)
        self._layer_group.setExclusive(True)
        for lname in LAYER_COLORS:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(4)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(f"background:{LAYER_COLORS[lname]}; border:1px solid #222;")
            rl.addWidget(swatch)
            cb = QCheckBox()
            cb.setChecked(True)
            cb.toggled.connect(lambda v, n=lname: self._on_layer_toggle(n, v))
            rl.addWidget(cb)
            rb = QRadioButton(lname)
            rb.toggled.connect(lambda v, n=lname: v and self._set_active_layer(n))
            if lname == "F.Cu":
                rb.setChecked(True)
            self._layer_group.addButton(rb)
            rl.addWidget(rb, 1)
            self._layer_checks[lname] = cb
            self._layer_radios[lname] = rb
            lp_lay.addWidget(row)
        lp_lay.addWidget(QLabel("Opacity"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        lp_lay.addWidget(self._opacity_slider)
        lp_lay.addStretch(1)
        splitter.addWidget(layer_panel)

        # Canvas
        self._scene = PcbScene(self)
        self._view = PcbView(self._scene)
        self._view.viewport().installEventFilter(self)
        self._scene.cursor_moved.connect(self._on_cursor_moved)
        splitter.addWidget(self._view)

        # Right: nets / properties
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)
        rl.addWidget(QLabel("Nets"))
        self._nets_list = QListWidget()
        self._refresh_nets_list()
        self._nets_list.itemClicked.connect(self._on_net_clicked)
        rl.addWidget(self._nets_list, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 8)
        splitter.setStretchFactor(2, 1)

        # Status bar
        self._status = QStatusBar()
        outer.addWidget(self._status)
        self._status.showMessage("Ready")

    # ==================================================================
    def _refresh_nets_list(self) -> None:
        self._nets_list.clear()
        for nid, name in sorted(self.board.nets.items()):
            if nid == 0:
                continue
            it = QListWidgetItem(f"{nid}: {name or '<unnamed>'}")
            it.setData(Qt.ItemDataRole.UserRole, nid)
            self._nets_list.addItem(it)

    def _on_net_clicked(self, item: QListWidgetItem) -> None:
        self._active_net_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._status.showMessage(
            f"Active net: {self._active_net_id} ({self.board.nets.get(self._active_net_id, '')})"
        )
        self._render_board()

    # ------------------------------------------------------------------
    def _set_tool(self, tool: str, btn) -> None:
        self._current_tool = tool
        self._track_points.clear()
        self._zone_points.clear()
        self._measure_start = None
        self._clear_temp()
        self._status.showMessage(f"Tool: {tool}")

    def _on_grid_changed(self, text: str) -> None:
        if text.startswith("off"):
            self._scene.grid_mm = 0.0
            self._scene.snap = False
        else:
            val = float(text.split()[0])
            self._scene.grid_mm = val
            self._scene.snap = True
        self._scene.update()

    def _set_active_layer(self, layer: str) -> None:
        if not hasattr(self, "_scene"):
            # Early signal from setChecked() during UI build — remember for later
            self._pending_active_layer = layer
            return
        self._scene.active_layer = layer
        if hasattr(self, "_status"):
            self._status.showMessage(f"Active layer: {layer}")

    def _on_layer_toggle(self, layer: str, visible: bool) -> None:
        self._scene.layer_visible[layer] = visible
        self._render_board()

    def _on_opacity_changed(self, value: int) -> None:
        for k in self._scene.layer_opacity:
            self._scene.layer_opacity[k] = value / 100.0
        self._render_board()

    def _on_cursor_moved(self, x_mm: float, y_mm: float) -> None:
        self._status.showMessage(
            f"X: {x_mm:7.3f} mm  Y: {y_mm:7.3f} mm  | Layer: {self._scene.active_layer}  | "
            f"Width: {self._track_width_mm:.3f} mm  | Net: {self._active_net_id}"
        )

    # ==================================================================
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        etype = event.type()
        if obj is self._view.viewport():
            from PySide6.QtCore import QEvent
            if etype == QEvent.Type.MouseButtonPress:
                self._on_canvas_click(event)
            elif etype == QEvent.Type.MouseMove:
                self._on_canvas_move(event)
            elif etype == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_V:
                    self._insert_via_at_last()
        return super().eventFilter(obj, event)

    def _view_to_scene(self, event) -> QPointF:
        return self._view.mapToScene(event.position().toPoint())

    def _on_canvas_click(self, event) -> None:
        sp = self._scene.snap_point(self._view_to_scene(event))
        if event.button() == Qt.MouseButton.RightButton:
            # Right click cancels current operation
            self._track_points.clear()
            self._zone_points.clear()
            self._clear_temp()
            return

        tool = self._current_tool
        if tool == Tool.TRACK:
            self._track_points.append(sp)
            if len(self._track_points) >= 2:
                a = self._track_points[-2]
                b = self._track_points[-1]
                self._add_track_segment(a, b)
        elif tool == Tool.VIA:
            self._add_via_at(sp)
        elif tool == Tool.ZONE:
            self._zone_points.append(sp)
        elif tool == Tool.MEASURE:
            if self._measure_start is None:
                self._measure_start = sp
            else:
                dx = (sp.x() - self._measure_start.x()) / PIX_PER_MM
                dy = (sp.y() - self._measure_start.y()) / PIX_PER_MM
                d = math.hypot(dx, dy)
                QMessageBox.information(self, "Measure",
                                        f"dx={dx:.3f} mm  dy={dy:.3f} mm  |  d={d:.3f} mm")
                self._measure_start = None

    def _on_canvas_move(self, event) -> None:
        pass  # future: rubber-band preview

    # ==================================================================
    def _add_track_segment(self, a: QPointF, b: QPointF) -> None:
        track = PcbTrack(
            layer=self._scene.active_layer,
            x1_mm=a.x() / PIX_PER_MM, y1_mm=a.y() / PIX_PER_MM,
            x2_mm=b.x() / PIX_PER_MM, y2_mm=b.y() / PIX_PER_MM,
            width_mm=self._track_width_mm,
            net=self._active_net_id,
        )
        self.board.tracks.append(track)
        self._render_board()

    def _add_via_at(self, p: QPointF) -> None:
        via = PcbVia(
            x_mm=p.x() / PIX_PER_MM, y_mm=p.y() / PIX_PER_MM,
            drill_mm=0.3, diameter_mm=0.6,
            layer_from="F.Cu", layer_to="B.Cu",
            net=self._active_net_id,
        )
        self.board.vias.append(via)
        self._render_board()

    def _insert_via_at_last(self) -> None:
        if self._track_points:
            self._add_via_at(self._track_points[-1])

    def _clear_temp(self) -> None:
        if self._temp_item is not None:
            self._scene.removeItem(self._temp_item)
            self._temp_item = None

    # ==================================================================
    def _render_board(self) -> None:
        self._scene.clear()

        # Board outline
        if self.board.outline:
            poly = QPolygonF([QPointF(x * PIX_PER_MM, y * PIX_PER_MM) for x, y in self.board.outline])
            pen = QPen(QColor(LAYER_COLORS["Edge.Cuts"]))
            pen.setWidthF(1.5)
            item = self._scene.addPolygon(poly, pen, QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(-10)

        # Footprints
        for fp in self.board.footprints:
            self._render_footprint(fp)

        # Zones
        for zone in self.board.zones:
            if not self._scene.layer_visible.get(zone.layer, True):
                continue
            if len(zone.polygon) >= 3:
                poly = QPolygonF([QPointF(x * PIX_PER_MM, y * PIX_PER_MM) for x, y in zone.polygon])
                color = QColor(LAYER_COLORS.get(zone.layer, "#888888"))
                color.setAlphaF(0.35 * self._scene.layer_opacity.get(zone.layer, 1.0))
                self._scene.addPolygon(poly, QPen(color), QBrush(color))

        # Tracks
        for tr in self.board.tracks:
            if not self._scene.layer_visible.get(tr.layer, True):
                continue
            color = QColor(LAYER_COLORS.get(tr.layer, "#cccccc"))
            color.setAlphaF(self._scene.layer_opacity.get(tr.layer, 1.0))
            if tr.net == self._active_net_id and tr.net > 0:
                color = QColor(HIGHLIGHT)
            pen = QPen(color)
            pen.setWidthF(max(tr.width_mm * PIX_PER_MM, 1.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            self._scene.addLine(
                tr.x1_mm * PIX_PER_MM, tr.y1_mm * PIX_PER_MM,
                tr.x2_mm * PIX_PER_MM, tr.y2_mm * PIX_PER_MM, pen,
            )

        # Vias
        for via in self.board.vias:
            d = via.diameter_mm * PIX_PER_MM
            drill = via.drill_mm * PIX_PER_MM
            color = QColor("#d0d0d0")
            self._scene.addEllipse(
                via.x_mm * PIX_PER_MM - d / 2, via.y_mm * PIX_PER_MM - d / 2,
                d, d, QPen(color), QBrush(color),
            )
            self._scene.addEllipse(
                via.x_mm * PIX_PER_MM - drill / 2, via.y_mm * PIX_PER_MM - drill / 2,
                drill, drill, QPen(QColor("#000000")), QBrush(QColor("#000000")),
            )

    def _render_footprint(self, fp: PcbFootprint) -> None:
        for pad in fp.pads:
            # which layer to use for color
            layer = "F.Cu"
            for l in pad.layers:
                if l.endswith(".Cu"):
                    layer = l
                    break
            if not self._scene.layer_visible.get(layer, True):
                continue
            color = QColor(LAYER_COLORS.get(layer, "#c83737"))
            color.setAlphaF(self._scene.layer_opacity.get(layer, 1.0))
            x, y = fp.pad_world_xy(pad)
            sx = pad.size_x_mm * PIX_PER_MM
            sy = pad.size_y_mm * PIX_PER_MM
            px = x * PIX_PER_MM - sx / 2
            py = y * PIX_PER_MM - sy / 2
            if pad.shape == "round":
                self._scene.addEllipse(px, py, sx, sy, QPen(color), QBrush(color))
            else:
                self._scene.addRect(px, py, sx, sy, QPen(color), QBrush(color))
            if pad.drill_mm > 0:
                dr = pad.drill_mm * PIX_PER_MM
                self._scene.addEllipse(
                    x * PIX_PER_MM - dr / 2, y * PIX_PER_MM - dr / 2, dr, dr,
                    QPen(QColor("#000000")), QBrush(QColor("#000000")),
                )
        # Silkscreen
        if self._scene.layer_visible.get("F.SilkS", True):
            silk = QColor(LAYER_COLORS["F.SilkS"])
            pen = QPen(silk)
            pen.setWidthF(2.0)
            rot = math.radians(fp.rotation_deg)
            cs, sn = math.cos(rot), math.sin(rot)
            for x1, y1, x2, y2 in fp.silkscreen:
                wx1 = (fp.x_mm + x1 * cs - y1 * sn) * PIX_PER_MM
                wy1 = (fp.y_mm + x1 * sn + y1 * cs) * PIX_PER_MM
                wx2 = (fp.x_mm + x2 * cs - y2 * sn) * PIX_PER_MM
                wy2 = (fp.y_mm + x2 * sn + y2 * cs) * PIX_PER_MM
                self._scene.addLine(wx1, wy1, wx2, wy2, pen)

    # ==================================================================
    def place_footprint(self, name: str, x_mm: float, y_mm: float,
                        ref: str = "", value: str = "") -> None:
        fp_template = FOOTPRINTS.get(name)
        if fp_template is None:
            return
        fp = fp_template.model_copy(deep=True)
        fp.x_mm = x_mm
        fp.y_mm = y_mm
        if ref:
            fp.ref = ref
        if value:
            fp.value = value
        self.board.footprints.append(fp)
        self._render_board()

    # ==================================================================
    def _save_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save PCB", "board.json",
                                              "PCB JSON (*.json)")
        if not path:
            return
        self.board.save_json(path)
        self._status.showMessage(f"Saved {path}")

    def _load_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load PCB", "",
                                              "PCB JSON (*.json)")
        if not path:
            return
        self.board = PcbBoard.load_json(path)
        self._render_board()
        self._refresh_nets_list()
        self._status.showMessage(f"Loaded {path}")

    def _export_gerber(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "Export Gerber to directory")
        if not out:
            return
        exp = GerberExporter(self.board)
        files = exp.export_all(Path(out))
        exp.export_drill(Path(out) / f"{self.board.name}.drl")
        self._status.showMessage(f"Exported {len(files)} Gerber layers to {out}")
        QMessageBox.information(self, "Gerber Export",
                                f"Exported {len(files)} layers and drill file to:\n{out}")
