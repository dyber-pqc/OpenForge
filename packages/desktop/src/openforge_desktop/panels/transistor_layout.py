"""Transistor-level custom layout editor (Virtuoso Layout XL replacement).

A QGraphicsView-based custom layout editor aimed at analog and custom-digital
cell creation. Provides a layer palette, drawing tools (rect/poly/path/wire/
label), parametric NMOS/PMOS placement, hierarchy, snapping to a manufacturing
grid, copy/paste, undo/redo, mirror/rotate, and DRC overlay markers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QLineF,
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QUndoCommand,
    QUndoStack,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openforge.format.gds_writer import (
    GdsBoundary,
    GdsLibrary,
    GdsPath,
    GdsStructure,
    GdsText,
    sky130_layer,
    write_gds,
)

# ---------------------------------------------------------------------------
# Layer model
# ---------------------------------------------------------------------------


@dataclass
class Layer:
    name: str
    gds_layer: int
    gds_dtype: int
    color: QColor
    visible: bool = True
    selectable: bool = True
    pattern: Qt.BrushStyle = Qt.BrushStyle.SolidPattern
    opacity: float = 0.4

    def brush(self) -> QBrush:
        c = QColor(self.color)
        c.setAlphaF(self.opacity)
        return QBrush(c, self.pattern)

    def pen(self) -> QPen:
        c = QColor(self.color)
        c.setAlphaF(min(1.0, self.opacity + 0.4))
        return QPen(c, 0.0)


def default_layers() -> list[Layer]:
    return [
        Layer("nwell", 1, 0, QColor("#a0522d"), pattern=Qt.BrushStyle.BDiagPattern),
        Layer("pwell", 2, 0, QColor("#cd853f"), pattern=Qt.BrushStyle.FDiagPattern),
        Layer("ndiff", 3, 0, QColor("#00ff00"), pattern=Qt.BrushStyle.Dense6Pattern),
        Layer("pdiff", 4, 0, QColor("#ffa500"), pattern=Qt.BrushStyle.Dense6Pattern),
        Layer("poly", 5, 0, QColor("#ff0000"), pattern=Qt.BrushStyle.Dense4Pattern),
        Layer("contact", 6, 0, QColor("#000000"), pattern=Qt.BrushStyle.SolidPattern, opacity=0.8),
        Layer("met1", 7, 0, QColor("#4169e1"), pattern=Qt.BrushStyle.Dense5Pattern),
        Layer("via1", 8, 0, QColor("#1e90ff"), opacity=0.8),
        Layer("met2", 9, 0, QColor("#9370db"), pattern=Qt.BrushStyle.Dense5Pattern),
        Layer("via2", 10, 0, QColor("#ba55d3"), opacity=0.8),
        Layer("met3", 11, 0, QColor("#ff69b4"), pattern=Qt.BrushStyle.Dense5Pattern),
        Layer("via3", 12, 0, QColor("#ff1493"), opacity=0.8),
        Layer("met4", 13, 0, QColor("#ffb6c1"), pattern=Qt.BrushStyle.Dense5Pattern),
        Layer("via4", 14, 0, QColor("#dc143c"), opacity=0.8),
        Layer("met5", 15, 0, QColor("#ffd700"), pattern=Qt.BrushStyle.Dense5Pattern),
        Layer("text", 99, 0, QColor("#ffffff"), opacity=1.0),
    ]


# ---------------------------------------------------------------------------
# Scene items
# ---------------------------------------------------------------------------


class LayerRectItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, layer: Layer):
        super().__init__(rect)
        self.layer_name = layer.name
        self.setBrush(layer.brush())
        self.setPen(layer.pen())
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)


class LayerPolyItem(QGraphicsPolygonItem):
    def __init__(self, polygon: QPolygonF, layer: Layer):
        super().__init__(polygon)
        self.layer_name = layer.name
        self.setBrush(layer.brush())
        self.setPen(layer.pen())
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)


class LayerPathItem(QGraphicsPathItem):
    def __init__(self, path: QPainterPath, layer: Layer, width: float):
        super().__init__(path)
        self.layer_name = layer.name
        pen = QPen(layer.color, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.setPen(pen)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)


class LabelItem(QGraphicsSimpleTextItem):
    def __init__(self, text: str, layer: Layer):
        super().__init__(text)
        self.layer_name = layer.name
        self.setBrush(layer.color)
        font = QFont("Inter", 6)
        self.setFont(font)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)


class TransistorItem(QGraphicsItemGroup):
    """A parametric NMOS or PMOS device built from primitive layer rects."""

    def __init__(self, kind: str, width_um: float, length_um: float, layers: dict[str, Layer]):
        super().__init__()
        self.kind = kind  # "nmos" / "pmos"
        self.width_um = width_um
        self.length_um = length_um
        self._build(layers)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

    def _build(self, layers: dict[str, Layer]) -> None:
        # Coordinates are in microns; the scene uses 1 unit = 1 um.
        w = self.width_um
        l = self.length_um
        diff_layer = layers["ndiff" if self.kind == "nmos" else "pdiff"]
        poly_layer = layers["poly"]
        contact_layer = layers["contact"]
        met1_layer = layers["met1"]

        # Diffusion (active)
        diff_rect = QRectF(-l - 0.6, -w / 2, 2 * (l + 0.6), w)
        diff = LayerRectItem(diff_rect, diff_layer)
        diff.setParentItem(self)

        # Poly gate (vertical bar through the middle)
        poly_rect = QRectF(-l / 2, -w / 2 - 0.4, l, w + 0.8)
        poly = LayerRectItem(poly_rect, poly_layer)
        poly.setParentItem(self)

        # Source / drain contacts
        for cx in (-l - 0.3, l + 0.3):
            crect = QRectF(cx - 0.1, -0.1, 0.2, 0.2)
            c = LayerRectItem(crect, contact_layer)
            c.setParentItem(self)

        # Metal-1 source/drain straps
        for sx in (-l - 0.45, l + 0.05):
            mrect = QRectF(sx, -w / 2, 0.4, w)
            m = LayerRectItem(mrect, met1_layer)
            m.setParentItem(self)

        # If pmos, draw nwell behind diffusion
        if self.kind == "pmos":
            nwell_rect = diff_rect.adjusted(-0.3, -0.3, 0.3, 0.3)
            nw = LayerRectItem(nwell_rect, layers["nwell"])
            nw.setParentItem(self)
            nw.setZValue(-1)


class DrcMarkerItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, message: str):
        super().__init__(rect)
        self.message = message
        pen = QPen(QColor("#f38ba8"), 0.05)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setBrush(QColor(243, 139, 168, 60))
        self.setZValue(1000)


# ---------------------------------------------------------------------------
# Undo commands
# ---------------------------------------------------------------------------


class AddItemCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem, label: str = "Add item"):
        super().__init__(label)
        self.scene = scene
        self.item = item

    def redo(self) -> None:
        if self.item.scene() is None:
            self.scene.addItem(self.item)

    def undo(self) -> None:
        if self.item.scene() is self.scene:
            self.scene.removeItem(self.item)


class RemoveItemsCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, items: list[QGraphicsItem], label: str = "Delete"):
        super().__init__(label)
        self.scene = scene
        self.items = list(items)

    def redo(self) -> None:
        for it in self.items:
            if it.scene() is self.scene:
                self.scene.removeItem(it)

    def undo(self) -> None:
        for it in self.items:
            if it.scene() is None:
                self.scene.addItem(it)


# ---------------------------------------------------------------------------
# Canvas view
# ---------------------------------------------------------------------------


class LayoutCanvas(QGraphicsView):
    """QGraphicsView with manufacturing-grid snap and drawing modes."""

    cursor_moved = Signal(float, float)
    item_added = Signal(QGraphicsItem)

    MODE_SELECT = "select"
    MODE_RECT = "rect"
    MODE_POLY = "poly"
    MODE_PATH = "path"
    MODE_WIRE = "wire"
    MODE_LABEL = "label"

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#11111b"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(40, -40)  # 1 unit = 1um, flip Y
        self.setMinimumSize(QSize(400, 400))

        self.snap_grid = 0.005  # 5 nm manufacturing grid
        self.draw_grid = 0.05
        self.mode = self.MODE_SELECT
        self.active_layer: Layer | None = None
        self.layers: dict[str, Layer] = {}

        self._draft_start: QPointF | None = None
        self._draft_item: QGraphicsItem | None = None
        self._poly_points: list[QPointF] = []
        self.undo_stack = QUndoStack(self)

    # -- helpers ----------------------------------------------------------
    def set_layers(self, layers: dict[str, Layer]) -> None:
        self.layers = layers

    def set_active_layer(self, name: str) -> None:
        self.active_layer = self.layers.get(name)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._draft_start = None
        self._draft_item = None
        self._poly_points = []

    def snap(self, p: QPointF) -> QPointF:
        g = self.snap_grid
        return QPointF(round(p.x() / g) * g, round(p.y() / g) * g)

    # -- Qt overrides ----------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        # Draw the visible draw grid
        pen = QPen(QColor("#313244"), 0)
        painter.setPen(pen)
        g = self.draw_grid
        x = math.floor(rect.left() / g) * g
        while x < rect.right():
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
            x += g
        y = math.floor(rect.top() / g) * g
        while y < rect.bottom():
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += g
        # Origin axes
        pen2 = QPen(QColor("#585b70"), 0)
        painter.setPen(pen2)
        painter.drawLine(QLineF(rect.left(), 0, rect.right(), 0))
        painter.drawLine(QLineF(0, rect.top(), 0, rect.bottom()))

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        scene_pt = self.snap(self.mapToScene(event.pos()))
        self.cursor_moved.emit(scene_pt.x(), scene_pt.y())
        if self._draft_item and self._draft_start is not None:
            if isinstance(self._draft_item, QGraphicsRectItem):
                rect = QRectF(self._draft_start, scene_pt).normalized()
                self._draft_item.setRect(rect)
            elif isinstance(self._draft_item, QGraphicsLineItem):
                self._draft_item.setLine(QLineF(self._draft_start, scene_pt))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        scene_pt = self.snap(self.mapToScene(event.pos()))
        if self.mode == self.MODE_SELECT:
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if not self.active_layer:
            return

        if self.mode == self.MODE_RECT:
            self._draft_start = scene_pt
            self._draft_item = LayerRectItem(QRectF(scene_pt, scene_pt), self.active_layer)
            self.scene().addItem(self._draft_item)
            return
        if self.mode == self.MODE_WIRE:
            self._draft_start = scene_pt
            line = QGraphicsLineItem(QLineF(scene_pt, scene_pt))
            pen = QPen(self.active_layer.color, 0.1)
            line.setPen(pen)
            self.scene().addItem(line)
            self._draft_item = line
            return
        if self.mode == self.MODE_POLY:
            self._poly_points.append(scene_pt)
            return
        if self.mode == self.MODE_LABEL:
            text, ok = QInputDialog.getText(self, "Label", "Net name:")
            if ok and text:
                lbl = LabelItem(text, self.active_layer)
                lbl.setPos(scene_pt)
                self.undo_stack.push(AddItemCommand(self.scene(), lbl, "Add label"))
                self.item_added.emit(lbl)
            return

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.mode in (self.MODE_RECT, self.MODE_WIRE) and self._draft_item is not None:
            self.scene().removeItem(self._draft_item)
            committed = self._draft_item
            self._draft_item = None
            self._draft_start = None
            # Re-add via undo stack
            if isinstance(committed, QGraphicsRectItem) and committed.rect().isValid():
                self.undo_stack.push(AddItemCommand(self.scene(), committed, "Draw rect"))
                self.item_added.emit(committed)
            elif isinstance(committed, QGraphicsLineItem):
                self.undo_stack.push(AddItemCommand(self.scene(), committed, "Draw wire"))
                self.item_added.emit(committed)
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.mode == self.MODE_POLY and len(self._poly_points) >= 3 and self.active_layer:
            poly = QPolygonF(self._poly_points)
            item = LayerPolyItem(poly, self.active_layer)
            self.undo_stack.push(AddItemCommand(self.scene(), item, "Draw polygon"))
            self.item_added.emit(item)
            self._poly_points = []
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo_stack.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.undo_stack.redo()
            return
        if event.key() == Qt.Key.Key_Delete:
            items = self.scene().selectedItems()
            if items:
                self.undo_stack.push(RemoveItemsCommand(self.scene(), items))
            return
        if event.key() == Qt.Key.Key_R:
            for it in self.scene().selectedItems():
                it.setRotation(it.rotation() + 90)
            return
        if event.key() == Qt.Key.Key_M:
            for it in self.scene().selectedItems():
                tr = it.transform()
                tr.scale(-1, 1)
                it.setTransform(tr)
            return
        if event.key() == Qt.Key.Key_Escape:
            self._poly_points = []
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Side panels
# ---------------------------------------------------------------------------


class LayerPalette(QWidget):
    layer_selected = Signal(str)
    visibility_changed = Signal(str, bool)

    def __init__(self, layers: list[Layer], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemChanged.connect(self._on_changed)
        layout.addWidget(self.list)
        self._layers: dict[str, Layer] = {}
        for layer in layers:
            self.add_layer(layer)

    def add_layer(self, layer: Layer) -> None:
        self._layers[layer.name] = layer
        item = QListWidgetItem(layer.name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
        item.setBackground(layer.color)
        item.setForeground(QColor("#000"))
        self.list.addItem(item)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self.layer_selected.emit(item.text())

    def _on_changed(self, item: QListWidgetItem) -> None:
        vis = item.checkState() == Qt.CheckState.Checked
        self._layers[item.text()].visible = vis
        self.visibility_changed.emit(item.text(), vis)


class HierarchyTree(QTreeWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Cell"])
        root = QTreeWidgetItem(["TOP"])
        self.addTopLevelItem(root)


class TransistorPlacer(QGroupBox):
    place_requested = Signal(str, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Place transistor", parent)
        layout = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(["nmos", "pmos"])
        self.width = QDoubleSpinBox()
        self.width.setDecimals(3)
        self.width.setRange(0.1, 100.0)
        self.width.setValue(1.0)
        self.length = QDoubleSpinBox()
        self.length.setDecimals(3)
        self.length.setRange(0.05, 10.0)
        self.length.setValue(0.18)
        place = QPushButton("Place at origin")
        place.clicked.connect(
            lambda: self.place_requested.emit(
                self.kind.currentText(), self.width.value(), self.length.value()
            )
        )
        layout.addRow("Type:", self.kind)
        layout.addRow("W (um):", self.width)
        layout.addRow("L (um):", self.length)
        layout.addRow(place)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class TransistorLayoutPanel(QDockWidget):
    """Custom layout editor dock widget."""

    layout_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Layout")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        layers = default_layers()
        self.layers: dict[str, Layer] = {l.name: l for l in layers}
        self._clipboard: list[QGraphicsItem] = []

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # Toolbar
        tb = QToolBar(root)
        tb.setMovable(False)
        self._build_toolbar(tb)
        root_layout.addWidget(tb)

        # Splitter: layer list | canvas | hierarchy/tools
        splitter = QSplitter(Qt.Orientation.Horizontal, root)

        # Left: layer palette
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Layers"))
        self.palette = LayerPalette(layers)
        self.palette.layer_selected.connect(self._on_layer_selected)
        self.palette.visibility_changed.connect(self._on_layer_visibility)
        left_layout.addWidget(self.palette, 1)
        splitter.addWidget(left)

        # Middle: graphics scene
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(QRectF(-50, -50, 100, 100))
        self.canvas = LayoutCanvas(self.scene, root)
        self.canvas.set_layers(self.layers)
        self.canvas.set_active_layer("met1")
        self.canvas.cursor_moved.connect(self._on_cursor_moved)
        self.canvas.item_added.connect(lambda _: self.layout_changed.emit())
        splitter.addWidget(self.canvas)

        # Right: hierarchy + transistor placer + properties
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Hierarchy"))
        self.hierarchy = HierarchyTree()
        right_layout.addWidget(self.hierarchy, 1)
        self.placer = TransistorPlacer()
        self.placer.place_requested.connect(self._on_place_transistor)
        right_layout.addWidget(self.placer)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([160, 800, 220])
        root_layout.addWidget(splitter, 1)

        # Status bar
        self.status = QStatusBar(root)
        self._coord_label = QLabel("0.000, 0.000 um")
        self.status.addPermanentWidget(self._coord_label)
        root_layout.addWidget(self.status)

        self.setWidget(root)
        self._apply_theme()

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------
    def _build_toolbar(self, tb: QToolBar) -> None:
        # File
        tb.addAction(QAction("New", self, triggered=self._on_new))
        tb.addAction(QAction("Open", self, triggered=self._on_open))
        tb.addAction(QAction("Save", self, triggered=self._on_save))
        tb.addAction(QAction("Export GDS", self, triggered=self._on_export_gds))
        tb.addSeparator()

        # Edit
        undo_act = QAction("Undo", self)
        undo_act.setShortcut(QKeySequence.StandardKey.Undo)
        undo_act.triggered.connect(lambda: self.canvas.undo_stack.undo())
        tb.addAction(undo_act)
        redo_act = QAction("Redo", self)
        redo_act.setShortcut(QKeySequence.StandardKey.Redo)
        redo_act.triggered.connect(lambda: self.canvas.undo_stack.redo())
        tb.addAction(redo_act)

        copy_act = QAction("Copy", self)
        copy_act.setShortcut(QKeySequence.StandardKey.Copy)
        copy_act.triggered.connect(self._on_copy)
        tb.addAction(copy_act)

        paste_act = QAction("Paste", self)
        paste_act.setShortcut(QKeySequence.StandardKey.Paste)
        paste_act.triggered.connect(self._on_paste)
        tb.addAction(paste_act)
        tb.addSeparator()

        # Modes
        self.mode_group = QButtonGroup(self)
        for mode_name, label in [
            (LayoutCanvas.MODE_SELECT, "Select"),
            (LayoutCanvas.MODE_RECT, "Rect"),
            (LayoutCanvas.MODE_POLY, "Polygon"),
            (LayoutCanvas.MODE_PATH, "Path"),
            (LayoutCanvas.MODE_WIRE, "Wire"),
            (LayoutCanvas.MODE_LABEL, "Label"),
        ]:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            if mode_name == LayoutCanvas.MODE_SELECT:
                btn.setChecked(True)
            btn.clicked.connect(lambda _=False, m=mode_name: self.canvas.set_mode(m))
            tb.addWidget(btn)
            self.mode_group.addButton(btn)
        tb.addSeparator()

        # DRC
        tb.addAction(QAction("Run DRC", self, triggered=self._on_run_drc))
        tb.addAction(QAction("Clear DRC", self, triggered=self._on_clear_drc))

    # ------------------------------------------------------------------
    # File ops
    # ------------------------------------------------------------------
    def _on_new(self) -> None:
        self.scene.clear()
        self.layout_changed.emit()
        self.status.showMessage("New layout")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open layout", "", "Layout JSON (*.ofl);;All files (*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as e:
            QMessageBox.warning(self, "Open failed", str(e))
            return
        self.scene.clear()
        for shape in data.get("shapes", []):
            layer = self.layers.get(shape["layer"])
            if not layer:
                continue
            kind = shape["kind"]
            if kind == "rect":
                rect = QRectF(*shape["rect"])
                item = LayerRectItem(rect, layer)
                self.scene.addItem(item)
            elif kind == "poly":
                poly = QPolygonF([QPointF(x, y) for x, y in shape["points"]])
                self.scene.addItem(LayerPolyItem(poly, layer))
            elif kind == "label":
                lbl = LabelItem(shape["text"], layer)
                lbl.setPos(*shape["pos"])
                self.scene.addItem(lbl)
        self.status.showMessage(f"Opened {path}")
        self.layout_changed.emit()

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save layout", "layout.ofl", "Layout JSON (*.ofl)"
        )
        if not path:
            return
        shapes: list[dict[str, Any]] = []
        for item in self.scene.items():
            if isinstance(item, LayerRectItem):
                r = item.sceneBoundingRect()
                shapes.append(
                    {
                        "kind": "rect",
                        "layer": item.layer_name,
                        "rect": [r.x(), r.y(), r.width(), r.height()],
                    }
                )
            elif isinstance(item, LayerPolyItem):
                shapes.append(
                    {
                        "kind": "poly",
                        "layer": item.layer_name,
                        "points": [(p.x(), p.y()) for p in item.polygon()],
                    }
                )
            elif isinstance(item, LabelItem):
                shapes.append(
                    {
                        "kind": "label",
                        "layer": item.layer_name,
                        "text": item.text(),
                        "pos": [item.pos().x(), item.pos().y()],
                    }
                )
        Path(path).write_text(json.dumps({"shapes": shapes}, indent=2), encoding="utf-8")
        self.status.showMessage(f"Saved {path}")

    def _on_export_gds(self, path: Any = None) -> None:
        if not isinstance(path, str):
            path = None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Export GDS", "layout.gds", "GDS (*.gds)")
        if not path:
            return
        try:
            out = self._export_gds(Path(path))
        except Exception as exc:  # pragma: no cover - surfaced via UI
            QMessageBox.critical(self, "GDS export failed", f"Could not write GDSII file:\n{exc}")
            self.status.showMessage(f"GDS export failed: {exc}")
            return
        size = out.stat().st_size if out.exists() else 0
        self.status.showMessage(f"Wrote GDSII {out} ({size} bytes)")

    # ------------------------------------------------------------------
    # GDSII export
    # ------------------------------------------------------------------
    def _layer_gds_pair(self, layer_name: str) -> tuple[int, int]:
        """Resolve a friendly layer name to a (gds_layer, gds_datatype) pair.

        Prefers the explicit ``gds_layer``/``gds_dtype`` configured on the
        layer in the palette; falls back to the SKY130 canonical mapping for
        unknown layers so the resulting GDS opens correctly in KLayout/Magic.
        """
        layer = self.layers.get(layer_name)
        if layer is not None:
            return int(layer.gds_layer), int(layer.gds_dtype)
        return sky130_layer(layer_name)

    def _export_gds(self, output_path: Path) -> Path:
        """Export the current layout as a real GDSII binary file."""
        cell_name = "TOPCELL"
        lib = GdsLibrary(name=cell_name, user_units=1e-6, db_units=1e-9)
        cell = GdsStructure(name=cell_name)

        # Scene coordinates are in microns; GDS db units are nm => x1000.
        UM_TO_NM = 1000

        for item in self.scene.items():
            layer_name = getattr(item, "layer_name", None)
            if layer_name is None:
                continue
            try:
                gds_layer, gds_dtype = self._layer_gds_pair(layer_name)
            except Exception:
                continue

            if isinstance(item, LayerRectItem):
                rect = item.rect().translated(item.pos())
                x1 = int(round(rect.left() * UM_TO_NM))
                y1 = int(round(rect.top() * UM_TO_NM))
                x2 = int(round(rect.right() * UM_TO_NM))
                y2 = int(round(rect.bottom() * UM_TO_NM))
                if x1 == x2 or y1 == y2:
                    continue
                if x1 > x2:
                    x1, x2 = x2, x1
                if y1 > y2:
                    y1, y2 = y2, y1
                cell.boundaries.append(
                    GdsBoundary(
                        layer=gds_layer,
                        datatype=gds_dtype,
                        points=[(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                    )
                )

            elif isinstance(item, LayerPolyItem):
                poly = item.polygon()
                offset = item.pos()
                points: list[tuple[int, int]] = []
                for i in range(poly.size()):
                    p = poly.at(i) + offset
                    points.append(
                        (
                            int(round(p.x() * UM_TO_NM)),
                            int(round(p.y() * UM_TO_NM)),
                        )
                    )
                if len(points) >= 3:
                    cell.boundaries.append(
                        GdsBoundary(
                            layer=gds_layer,
                            datatype=gds_dtype,
                            points=points,
                        )
                    )

            elif isinstance(item, LayerPathItem):
                qpath = item.path()
                offset = item.pos()
                pts: list[tuple[int, int]] = []
                for i in range(qpath.elementCount()):
                    el = qpath.elementAt(i)
                    pts.append(
                        (
                            int(round((el.x + offset.x()) * UM_TO_NM)),
                            int(round((el.y + offset.y()) * UM_TO_NM)),
                        )
                    )
                if len(pts) >= 2:
                    width_um = float(item.pen().widthF()) or 0.1
                    cell.paths.append(
                        GdsPath(
                            layer=gds_layer,
                            datatype=gds_dtype,
                            width=int(round(width_um * UM_TO_NM)),
                            pathtype=0,
                            points=pts,
                        )
                    )

            elif isinstance(item, LabelItem):
                pos = item.pos()
                cell.texts.append(
                    GdsText(
                        layer=gds_layer,
                        texttype=0,
                        string=item.text(),
                        x=int(round(pos.x() * UM_TO_NM)),
                        y=int(round(pos.y() * UM_TO_NM)),
                        height=200,
                    )
                )

        lib.structures.append(cell)
        return write_gds(lib, output_path)

    # ------------------------------------------------------------------
    # Edit ops
    # ------------------------------------------------------------------
    def _on_copy(self) -> None:
        self._clipboard = list(self.scene.selectedItems())
        self.status.showMessage(f"Copied {len(self._clipboard)} item(s)")

    def _on_paste(self) -> None:
        for it in self._clipboard:
            if isinstance(it, LayerRectItem):
                clone = LayerRectItem(it.rect().translated(0.5, 0.5), self.layers[it.layer_name])
                self.canvas.undo_stack.push(AddItemCommand(self.scene, clone, "Paste rect"))
            elif isinstance(it, LayerPolyItem):
                poly = QPolygonF([QPointF(p.x() + 0.5, p.y() + 0.5) for p in it.polygon()])
                clone = LayerPolyItem(poly, self.layers[it.layer_name])
                self.canvas.undo_stack.push(AddItemCommand(self.scene, clone, "Paste poly"))
            elif isinstance(it, LabelItem):
                clone = LabelItem(it.text(), self.layers[it.layer_name])
                clone.setPos(it.pos() + QPointF(0.5, 0.5))
                self.canvas.undo_stack.push(AddItemCommand(self.scene, clone, "Paste label"))

    # ------------------------------------------------------------------
    # DRC stub
    # ------------------------------------------------------------------
    def _on_run_drc(self) -> None:
        self._on_clear_drc()
        # Trivial demo DRC: flag any rect smaller than 0.1um in either dim.
        n_violations = 0
        for it in self.scene.items():
            if isinstance(it, LayerRectItem):
                r = it.sceneBoundingRect()
                if r.width() < 0.1 or r.height() < 0.1:
                    marker = DrcMarkerItem(
                        r.adjusted(-0.05, -0.05, 0.05, 0.05), "min width violation"
                    )
                    self.scene.addItem(marker)
                    n_violations += 1
        self.status.showMessage(f"DRC: {n_violations} violations")

    def _on_clear_drc(self) -> None:
        for it in list(self.scene.items()):
            if isinstance(it, DrcMarkerItem):
                self.scene.removeItem(it)

    # ------------------------------------------------------------------
    # Layer / cursor
    # ------------------------------------------------------------------
    def _on_layer_selected(self, name: str) -> None:
        self.canvas.set_active_layer(name)
        self.status.showMessage(f"Active layer: {name}")

    def _on_layer_visibility(self, name: str, visible: bool) -> None:
        for item in self.scene.items():
            if getattr(item, "layer_name", None) == name:
                item.setVisible(visible)

    def _on_cursor_moved(self, x: float, y: float) -> None:
        self._coord_label.setText(f"{x:.3f}, {y:.3f} um")

    def _on_place_transistor(self, kind: str, w: float, l: float) -> None:
        item = TransistorItem(kind, w, l, self.layers)
        item.setPos(0, 0)
        self.canvas.undo_stack.push(AddItemCommand(self.scene, item, f"Place {kind} W={w} L={l}"))
        self.status.showMessage(f"Placed {kind} W={w}u L={l}u")

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QDockWidget { background: #1e1e2e; color: #cdd6f4; }
            QWidget { color: #cdd6f4; }
            QToolBar { background: #181825; border: none; spacing: 4px; }
            QToolButton { padding: 4px 8px; background: #313244;
                          border: 1px solid #45475a; border-radius: 4px; }
            QToolButton:checked { background: #cba6f7; color: #1e1e2e; }
            QTreeWidget, QListWidget { background: #181825;
                                       border: 1px solid #313244; }
            QGroupBox { border: 1px solid #45475a; border-radius: 6px;
                        margin-top: 10px; padding: 8px; background: #181825; }
            QStatusBar { background: #181825; color: #a6adc8; }
            QLabel { color: #cdd6f4; }
            QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {
                background: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 4px; padding: 3px;
            }
            QPushButton {
                background: #45475a; color: #cdd6f4;
                border: 1px solid #585b70; border-radius: 4px; padding: 4px 10px;
            }
            QPushButton:hover { background: #585b70; }
            """
        )
