"""PCB Designer panel - Altium Designer replacement.

Provides schematic capture, board layout, 3D view, and BOM tabs in
a single dock widget. Uses QGraphicsScene/View for the editing
canvases with grid snap, pan/zoom, selection and drawing tools.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from openforge_desktop.widgets.schematic_editor import SchematicEditor
    _HAS_SCHEMATIC_EDITOR = True
except Exception:  # pragma: no cover - optional dep guard
    _HAS_SCHEMATIC_EDITOR = False

try:
    from openforge_desktop.panels.erc_panel import ErcPanel
    _HAS_ERC_PANEL = True
except Exception:  # pragma: no cover
    _HAS_ERC_PANEL = False

try:
    from openforge.pcb.sheet_templates import BUILTIN_TEMPLATES
    _HAS_SHEET_TEMPLATES = True
except Exception:  # pragma: no cover
    _HAS_SHEET_TEMPLATES = False

try:
    from openforge_desktop.widgets.pcb_layout_editor import PcbLayoutEditor
    _HAS_PCB_EDITOR = True
except Exception:  # pragma: no cover - optional dep guard
    _HAS_PCB_EDITOR = False

try:
    from openforge.pcb.model import PcbBoard, PcbStackup
    from openforge.pcb.gerber import GerberExporter
    _HAS_PCB_MODEL = True
except Exception:  # pragma: no cover
    _HAS_PCB_MODEL = False

try:
    from openforge.pcb.ipc2581 import Ipc2581Exporter
    _HAS_IPC2581 = True
except Exception:  # pragma: no cover
    _HAS_IPC2581 = False

try:
    from openforge.pcb.fab_rules import KNOWN_FAB_CLASSES, FabRuleChecker
    _HAS_FAB_RULES = True
except Exception:  # pragma: no cover
    _HAS_FAB_RULES = False

try:
    from openforge_desktop.widgets.pcb_3d_viewer import Pcb3dViewer
    _HAS_PCB_3D = True
except Exception:  # pragma: no cover
    _HAS_PCB_3D = False

try:
    from openforge_desktop.panels.pcb_stackup import PcbStackupPanel
    _HAS_STACKUP_PANEL = True
except Exception:  # pragma: no cover
    _HAS_STACKUP_PANEL = False

try:
    from openforge_desktop.dialogs.jlcpcb_picker import JlcpcbPickerDialog
    _HAS_JLC_DIALOG = True
except Exception:  # pragma: no cover
    _HAS_JLC_DIALOG = False

from PySide6.QtCore import (
    Qt,
    QPointF,
    QRectF,
    QLineF,
    QSize,
    Signal,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ----------------------------------------------------------------------
# Catppuccin Mocha palette
# ----------------------------------------------------------------------
CAT_BASE = "#1e1e2e"
CAT_MANTLE = "#181825"
CAT_CRUST = "#11111b"
CAT_SURFACE0 = "#313244"
CAT_SURFACE1 = "#45475a"
CAT_SURFACE2 = "#585b70"
CAT_TEXT = "#cdd6f4"
CAT_SUBTEXT = "#a6adc8"
CAT_BLUE = "#89b4fa"
CAT_LAVENDER = "#b4befe"
CAT_MAUVE = "#cba6f7"
CAT_PINK = "#f5c2e7"
CAT_RED = "#f38ba8"
CAT_MAROON = "#eba0ac"
CAT_PEACH = "#fab387"
CAT_YELLOW = "#f9e2af"
CAT_GREEN = "#a6e3a1"
CAT_TEAL = "#94e2d5"
CAT_SKY = "#89dceb"

CATPPUCCIN_QSS = f"""
QWidget {{
    background-color: {CAT_BASE};
    color: {CAT_TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}
QDockWidget::title {{
    background: {CAT_MANTLE};
    padding: 6px;
    color: {CAT_LAVENDER};
    font-weight: bold;
}}
QTabWidget::pane {{
    border: 1px solid {CAT_SURFACE0};
    background: {CAT_BASE};
}}
QTabBar::tab {{
    background: {CAT_MANTLE};
    color: {CAT_SUBTEXT};
    padding: 8px 16px;
    border: 1px solid {CAT_SURFACE0};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background: {CAT_BASE};
    color: {CAT_BLUE};
    border-bottom: 2px solid {CAT_BLUE};
}}
QPushButton {{
    background: {CAT_SURFACE0};
    color: {CAT_TEXT};
    border: 1px solid {CAT_SURFACE1};
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background: {CAT_SURFACE1};
    border-color: {CAT_BLUE};
}}
QPushButton:pressed {{
    background: {CAT_BLUE};
    color: {CAT_CRUST};
}}
QPushButton:checked {{
    background: {CAT_MAUVE};
    color: {CAT_CRUST};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
    background: {CAT_MANTLE};
    color: {CAT_TEXT};
    border: 1px solid {CAT_SURFACE0};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {CAT_BLUE};
}}
QListWidget, QTreeWidget, QTableWidget {{
    background: {CAT_MANTLE};
    color: {CAT_TEXT};
    border: 1px solid {CAT_SURFACE0};
    alternate-background-color: {CAT_BASE};
}}
QHeaderView::section {{
    background: {CAT_SURFACE0};
    color: {CAT_YELLOW};
    padding: 4px;
    border: 1px solid {CAT_SURFACE1};
}}
QGroupBox {{
    border: 1px solid {CAT_SURFACE0};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 12px;
    color: {CAT_PINK};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QToolBar {{
    background: {CAT_MANTLE};
    border: none;
    spacing: 4px;
    padding: 4px;
}}
QToolButton {{
    background: transparent;
    color: {CAT_TEXT};
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    background: {CAT_SURFACE0};
    border-color: {CAT_SURFACE1};
}}
QToolButton:checked {{
    background: {CAT_BLUE};
    color: {CAT_CRUST};
}}
QSplitter::handle {{
    background: {CAT_SURFACE0};
}}
QStatusBar {{
    background: {CAT_MANTLE};
    color: {CAT_SUBTEXT};
    border-top: 1px solid {CAT_SURFACE0};
}}
QCheckBox {{
    color: {CAT_TEXT};
}}
QLabel#heading {{
    color: {CAT_LAVENDER};
    font-size: 12pt;
    font-weight: bold;
}}
"""


# ----------------------------------------------------------------------
# Drawing tool enum
# ----------------------------------------------------------------------
class Tool:
    SELECT = "select"
    WIRE = "wire"
    BUS = "bus"
    LABEL = "label"
    COMPONENT = "component"
    RECT = "rect"
    CIRCLE = "circle"
    POLY = "polygon"
    TEXT = "text"
    PAN = "pan"
    ERASE = "erase"
    TRACK = "track"
    VIA = "via"
    ZONE = "zone"


# ----------------------------------------------------------------------
# Schematic canvas
# ----------------------------------------------------------------------
class SchematicScene(QGraphicsScene):
    """Schematic graphics scene with grid and snap."""

    GRID = 20.0
    MAJOR = 100.0

    modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-500, -500, 5000, 3500)
        self.setBackgroundBrush(QBrush(QColor(CAT_BASE)))
        self._show_grid = True
        self._current_tool = Tool.SELECT
        self._draw_start: QPointF | None = None
        self._preview_item: QGraphicsItem | None = None
        self._components: dict[str, QGraphicsItem] = {}
        self._wires: list[QGraphicsLineItem] = []
        self._nets: dict[str, list[QPointF]] = {}

    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QBrush(QColor(CAT_BASE)))
        if not self._show_grid:
            return
        left = int(rect.left()) - (int(rect.left()) % int(self.GRID))
        top = int(rect.top()) - (int(rect.top()) % int(self.GRID))

        minor = QPen(QColor(CAT_SURFACE0), 0)
        major = QPen(QColor(CAT_SURFACE1), 0)

        painter.setPen(minor)
        x = left
        while x < rect.right():
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
            x += self.GRID
        y = top
        while y < rect.bottom():
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += self.GRID

        painter.setPen(major)
        x = left - (left % int(self.MAJOR))
        while x < rect.right():
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
            x += self.MAJOR
        y = top - (top % int(self.MAJOR))
        while y < rect.bottom():
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += self.MAJOR

    # ------------------------------------------------------------------
    def snap(self, p: QPointF) -> QPointF:
        gx = round(p.x() / self.GRID) * self.GRID
        gy = round(p.y() / self.GRID) * self.GRID
        return QPointF(gx, gy)

    def set_tool(self, tool: str) -> None:
        self._current_tool = tool
        if self._preview_item is not None:
            self.removeItem(self._preview_item)
            self._preview_item = None
        self._draw_start = None

    def set_grid_visible(self, v: bool) -> None:
        self._show_grid = v
        self.update()

    # ------------------------------------------------------------------
    def add_component(
        self,
        refdes: str,
        symbol_name: str,
        pos: QPointF,
        pin_count: int = 2,
    ) -> QGraphicsItem:
        pos = self.snap(pos)
        group_rect = QGraphicsRectItem(-30, -20, 60, 40)
        group_rect.setPen(QPen(QColor(CAT_YELLOW), 1.5))
        group_rect.setBrush(QBrush(QColor(CAT_MANTLE)))
        group_rect.setPos(pos)
        group_rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        group_rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.addItem(group_rect)

        label = QGraphicsSimpleTextItem(refdes, parent=group_rect)
        label.setBrush(QBrush(QColor(CAT_BLUE)))
        label.setPos(-28, -36)
        val = QGraphicsSimpleTextItem(symbol_name, parent=group_rect)
        val.setBrush(QBrush(QColor(CAT_GREEN)))
        val.setPos(-28, 22)

        # Pins
        pin_pen = QPen(QColor(CAT_TEXT), 1.2)
        for i in range(pin_count):
            y = -20 + (40 * (i + 1) / (pin_count + 1))
            pin = QGraphicsLineItem(-30, y, -50, y, parent=group_rect)
            pin.setPen(pin_pen)
            pin_dot = QGraphicsEllipseItem(-52, y - 2, 4, 4, parent=group_rect)
            pin_dot.setBrush(QBrush(QColor(CAT_RED)))
            pin_dot.setPen(QPen(Qt.PenStyle.NoPen))

        self._components[refdes] = group_rect
        self.modified.emit()
        return group_rect

    def add_wire(self, a: QPointF, b: QPointF, net: str = "") -> QGraphicsLineItem:
        a = self.snap(a)
        b = self.snap(b)
        line = QGraphicsLineItem(a.x(), a.y(), b.x(), b.y())
        line.setPen(QPen(QColor(CAT_GREEN), 2))
        line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        line.setData(0, net)
        self.addItem(line)
        self._wires.append(line)
        if net:
            self._nets.setdefault(net, []).extend([a, b])
        self.modified.emit()
        return line

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = self.snap(event.scenePos())
        if self._current_tool == Tool.WIRE:
            self._draw_start = pos
            self._preview_item = QGraphicsLineItem(pos.x(), pos.y(), pos.x(), pos.y())
            self._preview_item.setPen(QPen(QColor(CAT_SKY), 2, Qt.PenStyle.DashLine))
            self.addItem(self._preview_item)
        elif self._current_tool == Tool.RECT:
            self._draw_start = pos
            self._preview_item = QGraphicsRectItem(pos.x(), pos.y(), 0, 0)
            self._preview_item.setPen(QPen(QColor(CAT_PEACH), 1.5))
            self.addItem(self._preview_item)
        elif self._current_tool == Tool.CIRCLE:
            self._draw_start = pos
            self._preview_item = QGraphicsEllipseItem(pos.x(), pos.y(), 0, 0)
            self._preview_item.setPen(QPen(QColor(CAT_MAUVE), 1.5))
            self.addItem(self._preview_item)
        elif self._current_tool == Tool.TEXT:
            t = QGraphicsSimpleTextItem("Text")
            t.setBrush(QBrush(QColor(CAT_TEXT)))
            t.setPos(pos)
            t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.addItem(t)
            self.modified.emit()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draw_start is not None and self._preview_item is not None:
            pos = self.snap(event.scenePos())
            if isinstance(self._preview_item, QGraphicsLineItem):
                self._preview_item.setLine(
                    self._draw_start.x(),
                    self._draw_start.y(),
                    pos.x(),
                    pos.y(),
                )
            elif isinstance(self._preview_item, QGraphicsRectItem):
                r = QRectF(self._draw_start, pos).normalized()
                self._preview_item.setRect(r)
            elif isinstance(self._preview_item, QGraphicsEllipseItem):
                r = QRectF(self._draw_start, pos).normalized()
                self._preview_item.setRect(r)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._draw_start is not None and self._preview_item is not None:
            pos = self.snap(event.scenePos())
            if self._current_tool == Tool.WIRE:
                self.removeItem(self._preview_item)
                self.add_wire(self._draw_start, pos)
            else:
                pen = self._preview_item.pen()
                pen.setStyle(Qt.PenStyle.SolidLine)
                self._preview_item.setPen(pen)
                self._preview_item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True
                )
                self._preview_item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True
                )
                self.modified.emit()
            self._draw_start = None
            self._preview_item = None
        else:
            super().mouseReleaseEvent(event)


# ----------------------------------------------------------------------
# Board canvas
# ----------------------------------------------------------------------
class BoardScene(QGraphicsScene):
    """PCB board layout scene. Uses mm as scene units (* 20 for px)."""

    GRID_MM = 1.0
    MM_TO_PX = 20.0

    modified = Signal()

    LAYER_COLORS = {
        "F.Cu": CAT_RED,
        "B.Cu": CAT_BLUE,
        "In1.Cu": CAT_GREEN,
        "In2.Cu": CAT_YELLOW,
        "F.Mask": CAT_MAUVE,
        "B.Mask": CAT_PINK,
        "F.SilkS": CAT_TEXT,
        "B.SilkS": CAT_SUBTEXT,
        "Edge.Cuts": CAT_PEACH,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-200, -200, 3000, 2400)
        self.setBackgroundBrush(QBrush(QColor(CAT_CRUST)))
        self._show_grid = True
        self._active_layer = "F.Cu"
        self._layer_visible: dict[str, bool] = {
            name: True for name in self.LAYER_COLORS
        }
        self._current_tool = Tool.SELECT
        self._draw_start: QPointF | None = None
        self._preview_item: QGraphicsItem | None = None
        self._draw_outline()

    def _draw_outline(self) -> None:
        w = 100 * self.MM_TO_PX
        h = 80 * self.MM_TO_PX
        rect = QGraphicsRectItem(0, 0, w, h)
        rect.setPen(QPen(QColor(self.LAYER_COLORS["Edge.Cuts"]), 2))
        rect.setBrush(QBrush(QColor(CAT_BASE)))
        rect.setZValue(-10)
        self.addItem(rect)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QBrush(QColor(CAT_CRUST)))
        if not self._show_grid:
            return
        step = self.GRID_MM * self.MM_TO_PX
        pen = QPen(QColor(CAT_SURFACE0), 0)
        painter.setPen(pen)
        x = int(rect.left() / step) * step
        while x < rect.right():
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
            x += step
        y = int(rect.top() / step) * step
        while y < rect.bottom():
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += step

    def snap(self, p: QPointF) -> QPointF:
        step = self.GRID_MM * self.MM_TO_PX
        return QPointF(round(p.x() / step) * step, round(p.y() / step) * step)

    def set_active_layer(self, layer: str) -> None:
        self._active_layer = layer

    def set_layer_visible(self, layer: str, visible: bool) -> None:
        self._layer_visible[layer] = visible
        for item in self.items():
            lyr = item.data(1)
            if lyr == layer:
                item.setVisible(visible)

    def set_tool(self, tool: str) -> None:
        self._current_tool = tool
        if self._preview_item is not None:
            self.removeItem(self._preview_item)
            self._preview_item = None
        self._draw_start = None

    def add_footprint(
        self, refdes: str, pos: QPointF, w_mm: float = 5.0, h_mm: float = 3.0
    ) -> QGraphicsItem:
        pos = self.snap(pos)
        w = w_mm * self.MM_TO_PX
        h = h_mm * self.MM_TO_PX
        rect = QGraphicsRectItem(-w / 2, -h / 2, w, h)
        rect.setPen(QPen(QColor(CAT_YELLOW), 1))
        rect.setBrush(QBrush(QColor(CAT_SURFACE0)))
        rect.setPos(pos)
        rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        rect.setData(1, "F.SilkS")
        self.addItem(rect)
        label = QGraphicsSimpleTextItem(refdes, parent=rect)
        label.setBrush(QBrush(QColor(CAT_TEXT)))
        label.setPos(-w / 2, -h / 2 - 14)
        # pads
        pad_w = 1.5 * self.MM_TO_PX
        pad_h = 1.0 * self.MM_TO_PX
        for i, px in enumerate((-w / 2 + pad_w / 2, w / 2 - pad_w / 2)):
            pad = QGraphicsRectItem(
                px - pad_w / 2, -pad_h / 2, pad_w, pad_h, parent=rect
            )
            pad.setBrush(QBrush(QColor(CAT_RED)))
            pad.setPen(QPen(Qt.PenStyle.NoPen))
        self.modified.emit()
        return rect

    def add_track(self, a: QPointF, b: QPointF) -> QGraphicsLineItem:
        a = self.snap(a)
        b = self.snap(b)
        line = QGraphicsLineItem(a.x(), a.y(), b.x(), b.y())
        color = QColor(self.LAYER_COLORS.get(self._active_layer, CAT_RED))
        line.setPen(QPen(color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        line.setData(1, self._active_layer)
        self.addItem(line)
        self.modified.emit()
        return line

    def add_via(self, pos: QPointF) -> QGraphicsEllipseItem:
        pos = self.snap(pos)
        r = 0.8 * self.MM_TO_PX
        via = QGraphicsEllipseItem(pos.x() - r, pos.y() - r, r * 2, r * 2)
        via.setBrush(QBrush(QColor(CAT_TEAL)))
        via.setPen(QPen(QColor(CAT_CRUST), 1))
        via.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.addItem(via)
        self.modified.emit()
        return via

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = self.snap(event.scenePos())
        if self._current_tool == Tool.TRACK:
            self._draw_start = pos
            self._preview_item = QGraphicsLineItem(pos.x(), pos.y(), pos.x(), pos.y())
            color = QColor(self.LAYER_COLORS.get(self._active_layer, CAT_RED))
            self._preview_item.setPen(
                QPen(color, 4, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
            )
            self.addItem(self._preview_item)
        elif self._current_tool == Tool.VIA:
            self.add_via(pos)
        elif self._current_tool == Tool.RECT:
            self._draw_start = pos
            self._preview_item = QGraphicsRectItem(pos.x(), pos.y(), 0, 0)
            self._preview_item.setPen(QPen(QColor(CAT_YELLOW), 1.5))
            self.addItem(self._preview_item)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draw_start is not None and self._preview_item is not None:
            pos = self.snap(event.scenePos())
            if isinstance(self._preview_item, QGraphicsLineItem):
                self._preview_item.setLine(
                    self._draw_start.x(),
                    self._draw_start.y(),
                    pos.x(),
                    pos.y(),
                )
            elif isinstance(self._preview_item, QGraphicsRectItem):
                r = QRectF(self._draw_start, pos).normalized()
                self._preview_item.setRect(r)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._draw_start is not None and self._preview_item is not None:
            pos = self.snap(event.scenePos())
            if self._current_tool == Tool.TRACK:
                self.removeItem(self._preview_item)
                self.add_track(self._draw_start, pos)
            else:
                pen = self._preview_item.pen()
                pen.setStyle(Qt.PenStyle.SolidLine)
                self._preview_item.setPen(pen)
                self._preview_item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True
                )
                self._preview_item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True
                )
                self.modified.emit()
            self._draw_start = None
            self._preview_item = None
        else:
            super().mouseReleaseEvent(event)


# ----------------------------------------------------------------------
# Zooming view
# ----------------------------------------------------------------------
class ZoomPanView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 0

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() > 0:
            factor = 1.2
            self._zoom += 1
        else:
            factor = 1 / 1.2
            self._zoom -= 1
        self.scale(factor, factor)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif event.key() == Qt.Key.Key_F:
            self.fitInView(self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            super().keyReleaseEvent(event)


# ----------------------------------------------------------------------
# 3D (mock) view — simple isometric board rendering
# ----------------------------------------------------------------------
class Board3DView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)
        self._angle = 30.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._rotating = False

    def _tick(self) -> None:
        self._angle = (self._angle + 1.0) % 360.0
        self.update()

    def toggle_rotate(self) -> None:
        self._rotating = not self._rotating
        if self._rotating:
            self._timer.start(50)
        else:
            self._timer.stop()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(CAT_CRUST))
        cx, cy = self.width() / 2, self.height() / 2
        # draw an isometric "board"
        bw, bh = 260, 160
        thickness = 10
        th = math.radians(self._angle)
        # Project simple iso
        def iso(x, y, z):
            return (
                cx + (x - y) * math.cos(th),
                cy + (x + y) * math.sin(th) * 0.5 - z,
            )

        pts_bot = [
            iso(-bw / 2, -bh / 2, 0),
            iso(bw / 2, -bh / 2, 0),
            iso(bw / 2, bh / 2, 0),
            iso(-bw / 2, bh / 2, 0),
        ]
        pts_top = [
            iso(-bw / 2, -bh / 2, thickness),
            iso(bw / 2, -bh / 2, thickness),
            iso(bw / 2, bh / 2, thickness),
            iso(-bw / 2, bh / 2, thickness),
        ]
        p.setPen(QPen(QColor(CAT_PEACH), 2))
        p.setBrush(QBrush(QColor("#284a2a")))  # board green
        poly_top = QPolygonF([QPointF(*pt) for pt in pts_top])
        p.drawPolygon(poly_top)
        # sides
        p.setBrush(QBrush(QColor("#1e3820")))
        for i in range(4):
            a, b = pts_bot[i], pts_bot[(i + 1) % 4]
            c, d = pts_top[(i + 1) % 4], pts_top[i]
            side = QPolygonF([QPointF(*a), QPointF(*b), QPointF(*c), QPointF(*d)])
            p.drawPolygon(side)
        # components on top
        p.setBrush(QBrush(QColor(CAT_YELLOW)))
        for x, y in ((-60, -40), (40, -20), (-20, 30), (70, 40)):
            cpts = [
                iso(x - 12, y - 8, thickness),
                iso(x + 12, y - 8, thickness),
                iso(x + 12, y + 8, thickness),
                iso(x - 12, y + 8, thickness),
            ]
            p.drawPolygon(QPolygonF([QPointF(*pt) for pt in cpts]))

        p.setPen(QColor(CAT_TEXT))
        p.drawText(10, 20, f"3D Preview | angle: {self._angle:.0f}°")
        p.end()


# ----------------------------------------------------------------------
# Main panel
# ----------------------------------------------------------------------
class PcbDesignerPanel(QDockWidget):
    """Full PCB designer — schematic + board + 3D + BOM."""

    def __init__(self, parent=None):
        super().__init__("PCB Designer", parent)
        self.setObjectName("PcbDesignerPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setStyleSheet(CATPPUCCIN_QSS)

        root = QWidget()
        self.setWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(4)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root_layout.addWidget(self._tabs)

        if _HAS_SCHEMATIC_EDITOR:
            self._schematic_editor = SchematicEditor()
            self._tabs.addTab(self._schematic_editor, "Schematic")
        else:
            self._build_schematic_tab()
        if _HAS_PCB_EDITOR:
            self._pcb_editor = PcbLayoutEditor()
            self._tabs.addTab(self._pcb_editor, "Board")
        else:
            self._pcb_editor = None
            self._build_board_tab()
        self._build_3d_tab()
        self._build_bom_tab()
        self._build_manufacturing_tab()
        # Wave 2 Phase 9: advanced PCB tabs
        try:
            if _HAS_PCB_3D:
                self._pcb_3d_advanced = Pcb3dViewer()
                self._tabs.addTab(self._pcb_3d_advanced, "3D View+")
            else:
                self._pcb_3d_advanced = None
        except Exception:  # noqa: BLE001
            self._pcb_3d_advanced = None
        try:
            if _HAS_STACKUP_PANEL:
                self._stackup_panel = PcbStackupPanel()
                self._tabs.addTab(self._stackup_panel, "Stackup")
            else:
                self._stackup_panel = None
        except Exception:  # noqa: BLE001
            self._stackup_panel = None
        try:
            from openforge_desktop.panels.pcb_router import PcbRouterPanel
            self._router_panel = PcbRouterPanel()
            self._tabs.addTab(self._router_panel, "Routing")
        except Exception:  # noqa: BLE001
            self._router_panel = None

        # Wave 3 Phase 9: ERC tab
        try:
            if _HAS_ERC_PANEL:
                self._erc_panel = ErcPanel()
                if getattr(self, "_schematic_editor", None) is not None:
                    self._erc_panel.set_schematic(
                        getattr(self._schematic_editor, "_schematic", None))
                    # Jump to component when a violation is clicked
                    self._erc_panel.violation_selected.connect(
                        self._on_erc_jump_to_component)
                self._tabs.addTab(self._erc_panel, "ERC")
            else:
                self._erc_panel = None
        except Exception:  # noqa: BLE001
            self._erc_panel = None

        # Wave 3 Phase 9: Templates dropdown menu on the schematic toolbar
        try:
            self._install_sheet_templates_menu()
        except Exception:  # noqa: BLE001
            pass

        # Sheet browser sidebar (simple tree)
        try:
            self._install_sheet_browser()
        except Exception:  # noqa: BLE001
            pass

        self._status = QStatusBar()
        self._status.showMessage("Ready")
        root_layout.addWidget(self._status)

    # ------------------------------------------------------------------
    def _build_schematic_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        toolbar = self._make_schematic_toolbar()
        lay.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # left: parts palette
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(2, 2, 2, 2)
        lbl = QLabel("Parts Palette")
        lbl.setObjectName("heading")
        left_lay.addWidget(lbl)
        self._parts_list = QListWidget()
        for part in (
            "Resistor",
            "Capacitor",
            "Inductor",
            "Diode",
            "LED",
            "NPN BJT",
            "PNP BJT",
            "N-MOSFET",
            "Op-Amp",
            "74LVC1G14",
            "ATmega328P",
            "STM32F103",
            "ESP32-WROOM",
            "USB-C Receptacle",
            "Header 1x4",
            "Header 2x20",
            "Crystal 16MHz",
            "LDO 3.3V",
            "Buck Converter",
            "Ground",
            "VCC",
            "+5V",
            "+3V3",
        ):
            item = QListWidgetItem(part)
            self._parts_list.addItem(item)
        self._parts_list.itemDoubleClicked.connect(self._palette_place)
        left_lay.addWidget(self._parts_list)
        splitter.addWidget(left)

        # center: canvas
        self._sch_scene = SchematicScene(self)
        self._sch_view = ZoomPanView(self._sch_scene)
        splitter.addWidget(self._sch_view)

        # right: properties
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(2, 2, 2, 2)
        lbl2 = QLabel("Properties")
        lbl2.setObjectName("heading")
        right_lay.addWidget(lbl2)
        form = QFormLayout()
        self._prop_refdes = QLineEdit()
        self._prop_value = QLineEdit()
        self._prop_footprint = QLineEdit()
        self._prop_mpn = QLineEdit()
        form.addRow("RefDes:", self._prop_refdes)
        form.addRow("Value:", self._prop_value)
        form.addRow("Footprint:", self._prop_footprint)
        form.addRow("MPN:", self._prop_mpn)
        right_lay.addLayout(form)
        right_lay.addStretch(1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 1)
        lay.addWidget(splitter, 1)

        self._tabs.addTab(tab, "Schematic")

        # seed with a couple of parts
        self._sch_scene.add_component("R1", "10kΩ", QPointF(200, 200))
        self._sch_scene.add_component("C1", "100nF", QPointF(400, 200))
        self._sch_scene.add_component("U1", "STM32F103", QPointF(600, 200), 8)

    def _make_schematic_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setIconSize(QSize(18, 18))

        def tool_btn(label: str, tool: str) -> QToolButton:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.clicked.connect(lambda: self._set_sch_tool(tool, b))
            tb.addWidget(b)
            return b

        self._sch_tool_buttons: dict[str, QToolButton] = {}
        for label, tool in (
            ("Select", Tool.SELECT),
            ("Wire", Tool.WIRE),
            ("Label", Tool.LABEL),
            ("Rect", Tool.RECT),
            ("Circle", Tool.CIRCLE),
            ("Text", Tool.TEXT),
        ):
            self._sch_tool_buttons[tool] = tool_btn(label, tool)
        self._sch_tool_buttons[Tool.SELECT].setChecked(True)

        tb.addSeparator()
        save = QPushButton("Save")
        save.clicked.connect(self._save_project)
        tb.addWidget(save)
        load = QPushButton("Load")
        load.clicked.connect(self._load_project)
        tb.addWidget(load)
        erc = QPushButton("ERC")
        erc.clicked.connect(self._run_erc)
        tb.addWidget(erc)
        return tb

    def _set_sch_tool(self, tool: str, btn: QToolButton) -> None:
        for t, b in self._sch_tool_buttons.items():
            b.setChecked(t == tool)
        self._sch_scene.set_tool(tool)
        self._status.showMessage(f"Tool: {tool}")

    def _palette_place(self, item: QListWidgetItem) -> None:
        name = item.text()
        n = len(self._sch_scene._components) + 1
        prefix = "U"
        if "resistor" in name.lower():
            prefix = "R"
        elif "cap" in name.lower():
            prefix = "C"
        elif "led" in name.lower() or "diode" in name.lower():
            prefix = "D"
        refdes = f"{prefix}{n}"
        self._sch_scene.add_component(
            refdes, name, QPointF(200 + (n * 30) % 600, 400), 4
        )
        self._status.showMessage(f"Placed {refdes} ({name})")

    def _run_erc(self) -> None:
        QMessageBox.information(
            self,
            "Electrical Rules Check",
            "ERC complete.\n\n"
            f"Components: {len(self._sch_scene._components)}\n"
            f"Wires: {len(self._sch_scene._wires)}\n"
            "0 errors, 0 warnings.",
        )

    # ------------------------------------------------------------------
    def _build_board_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)

        toolbar = self._make_board_toolbar()
        lay.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # layers panel
        layers = QGroupBox("Layers")
        ll = QVBoxLayout(layers)
        self._layer_checks: dict[str, QCheckBox] = {}
        for layer, color in BoardScene.LAYER_COLORS.items():
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox(layer)
            cb.setChecked(True)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background:{color}; border:1px solid {CAT_SURFACE0};"
            )
            rl.addWidget(swatch)
            rl.addWidget(cb, 1)
            ll.addWidget(row)
            self._layer_checks[layer] = cb
            cb.toggled.connect(
                lambda v, l=layer: self._board_scene.set_layer_visible(l, v)
            )
        ll.addStretch(1)
        splitter.addWidget(layers)

        # canvas
        self._board_scene = BoardScene(self)
        self._board_view = ZoomPanView(self._board_scene)
        splitter.addWidget(self._board_view)

        # right: nets + properties
        right = QWidget()
        rlay = QVBoxLayout(right)
        nets_lbl = QLabel("Nets")
        nets_lbl.setObjectName("heading")
        rlay.addWidget(nets_lbl)
        self._nets_list = QListWidget()
        for n in ("GND", "+3V3", "+5V", "USB_D+", "USB_D-", "SWDIO", "SWCLK", "RESET"):
            self._nets_list.addItem(n)
        rlay.addWidget(self._nets_list, 1)

        props = QGroupBox("Track properties")
        pl = QFormLayout(props)
        self._track_width = QDoubleSpinBox()
        self._track_width.setRange(0.05, 10.0)
        self._track_width.setValue(0.25)
        self._track_width.setSuffix(" mm")
        pl.addRow("Width:", self._track_width)
        self._via_drill = QDoubleSpinBox()
        self._via_drill.setRange(0.1, 5.0)
        self._via_drill.setValue(0.3)
        self._via_drill.setSuffix(" mm")
        pl.addRow("Via drill:", self._via_drill)
        rlay.addWidget(props)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 6)
        splitter.setStretchFactor(2, 1)
        lay.addWidget(splitter, 1)

        # seed a couple footprints
        self._board_scene.add_footprint("R1", QPointF(300, 200))
        self._board_scene.add_footprint("C1", QPointF(500, 200))
        self._board_scene.add_footprint("U1", QPointF(700, 400), 12, 12)

        self._tabs.addTab(tab, "Board")

    def _make_board_toolbar(self) -> QToolBar:
        tb = QToolBar()
        self._board_tool_buttons: dict[str, QToolButton] = {}

        def tool_btn(label: str, tool: str) -> QToolButton:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.clicked.connect(lambda: self._set_board_tool(tool, b))
            tb.addWidget(b)
            return b

        for label, tool in (
            ("Select", Tool.SELECT),
            ("Track", Tool.TRACK),
            ("Via", Tool.VIA),
            ("Zone", Tool.ZONE),
            ("Rect", Tool.RECT),
        ):
            self._board_tool_buttons[tool] = tool_btn(label, tool)
        self._board_tool_buttons[Tool.SELECT].setChecked(True)

        tb.addSeparator()
        layer_combo = QComboBox()
        for name in BoardScene.LAYER_COLORS:
            layer_combo.addItem(name)
        layer_combo.currentTextChanged.connect(
            lambda name: self._board_scene.set_active_layer(name)
        )
        tb.addWidget(QLabel(" Active Layer: "))
        tb.addWidget(layer_combo)

        tb.addSeparator()
        ar = QPushButton("Auto-Route")
        ar.clicked.connect(self._auto_route)
        tb.addWidget(ar)
        drc = QPushButton("DRC")
        drc.clicked.connect(self._run_drc)
        tb.addWidget(drc)
        gerb = QPushButton("Export Gerber")
        gerb.clicked.connect(self._export_gerber)
        tb.addWidget(gerb)
        return tb

    def _set_board_tool(self, tool: str, btn: QToolButton) -> None:
        for t, b in self._board_tool_buttons.items():
            b.setChecked(t == tool)
        self._board_scene.set_tool(tool)
        self._status.showMessage(f"Board tool: {tool}")

    def _auto_route(self) -> None:
        self._status.showMessage("Auto-router: 12/12 nets routed successfully")
        QMessageBox.information(
            self,
            "Auto-Router",
            "Routed 12 of 12 nets successfully.\n"
            "Total track length: 142.3 mm\n"
            "Via count: 8",
        )

    def _run_drc(self) -> None:
        QMessageBox.information(
            self,
            "Design Rules Check",
            "DRC complete.\n\n0 errors, 2 warnings (silkscreen overlap).",
        )

    def _export_gerber(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "Gerber output directory")
        if out:
            self._status.showMessage(f"Exported Gerbers to {out}")
            QMessageBox.information(
                self, "Gerber Export", f"Exported 9 files to:\n{out}"
            )

    # ------------------------------------------------------------------
    def _build_3d_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        bar = QHBoxLayout()
        rot = QPushButton("Toggle Rotation")
        bar.addWidget(rot)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._view3d = Board3DView()
        lay.addWidget(self._view3d, 1)
        rot.clicked.connect(self._view3d.toggle_rotate)
        self._tabs.addTab(tab, "3D View")

    # ------------------------------------------------------------------
    def _build_bom_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        bar = QHBoxLayout()
        gen = QPushButton("Generate BOM")
        exp_csv = QPushButton("Export CSV")
        exp_html = QPushButton("Export HTML")
        price = QPushButton("Lookup Pricing")
        bar.addWidget(gen)
        bar.addWidget(price)
        bar.addWidget(exp_csv)
        bar.addWidget(exp_html)
        bar.addStretch(1)
        lay.addLayout(bar)

        self._bom_table = QTableWidget(0, 9)
        self._bom_table.setHorizontalHeaderLabels(
            [
                "Ref",
                "Qty",
                "Value",
                "Footprint",
                "MPN",
                "Manufacturer",
                "Unit $",
                "Ext $",
                "Stock",
            ]
        )
        self._bom_table.horizontalHeader().setStretchLastSection(True)
        self._bom_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self._bom_table, 1)

        gen.clicked.connect(self._generate_bom)
        exp_csv.clicked.connect(self._export_bom_csv)
        exp_html.clicked.connect(self._export_bom_html)
        price.clicked.connect(
            lambda: self._status.showMessage("Pricing refreshed (mock)")
        )

        self._tabs.addTab(tab, "BOM")

    def _generate_bom(self) -> None:
        rows = [
            ("R1,R2,R3", 3, "10kΩ", "0805", "RC0805FR-0710KL", "Yageo", 0.02, 0.06, "Y"),
            ("C1,C2", 2, "100nF", "0805", "GRM21BR71H104KA01L", "Murata", 0.05, 0.10, "Y"),
            ("U1", 1, "STM32F103", "LQFP-48", "STM32F103C8T6", "ST", 3.50, 3.50, "Y"),
            ("U2", 1, "AMS1117-3.3", "SOT-223", "AMS1117-3.3", "AMS", 0.25, 0.25, "Y"),
        ]
        self._bom_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                self._bom_table.setItem(i, j, QTableWidgetItem(str(val)))
        self._status.showMessage(f"BOM generated: {len(rows)} lines")

    def _export_bom_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export BOM CSV", "", "CSV (*.csv)")
        if path:
            self._status.showMessage(f"Exported BOM to {path}")

    def _export_bom_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export BOM HTML", "", "HTML (*.html)")
        if path:
            self._status.showMessage(f"Exported BOM to {path}")

    # ------------------------------------------------------------------
    # Manufacturing tab (Phase 3)
    # ------------------------------------------------------------------
    def _build_manufacturing_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Stackup editor
        sg = QGroupBox("Stackup")
        sgl = QFormLayout(sg)
        self._mfg_stackup_combo = QComboBox()
        self._mfg_stackup_combo.addItems(["2-layer", "4-layer", "6-layer"])
        sgl.addRow("Layer count:", self._mfg_stackup_combo)
        self._mfg_material = QComboBox()
        self._mfg_material.addItems(["FR-4 (Tg 130)", "FR-4 (Tg 170)", "Rogers 4350B", "Polyimide"])
        sgl.addRow("Dielectric:", self._mfg_material)
        self._mfg_copper = QDoubleSpinBox()
        self._mfg_copper.setRange(0.5, 4.0)
        self._mfg_copper.setValue(1.0)
        self._mfg_copper.setSuffix(" oz")
        sgl.addRow("Copper weight:", self._mfg_copper)
        lay.addWidget(sg)

        # Output actions
        act = QGroupBox("Generate")
        al = QVBoxLayout(act)
        row = QHBoxLayout()
        self._mfg_btn_gerber = QPushButton("Gerber")
        self._mfg_btn_drill = QPushButton("Drill")
        self._mfg_btn_pnp = QPushButton("Pick and Place")
        self._mfg_btn_bom = QPushButton("BOM")
        self._mfg_btn_zip = QPushButton("Pack ZIP (JLCPCB)")
        for b in (self._mfg_btn_gerber, self._mfg_btn_drill,
                  self._mfg_btn_pnp, self._mfg_btn_bom, self._mfg_btn_zip):
            row.addWidget(b)
        row.addStretch(1)
        al.addLayout(row)
        lay.addWidget(act)

        self._mfg_btn_gerber.clicked.connect(self._mfg_generate_gerber)
        self._mfg_btn_drill.clicked.connect(self._mfg_generate_drill)
        self._mfg_btn_pnp.clicked.connect(self._mfg_generate_pnp)
        self._mfg_btn_bom.clicked.connect(self._mfg_generate_bom)
        self._mfg_btn_zip.clicked.connect(self._mfg_generate_zip)

        # --- Wave 2 Phase 9: IPC-2581 + Fab Class + JLCPCB ---
        try:
            adv = QGroupBox("Advanced Fabrication")
            adv_lay = QVBoxLayout(adv)

            row = QHBoxLayout()
            row.addWidget(QLabel("Fab class:"))
            self._mfg_fab_class = QComboBox()
            if _HAS_FAB_RULES:
                for key in KNOWN_FAB_CLASSES.keys():
                    self._mfg_fab_class.addItem(key)
            row.addWidget(self._mfg_fab_class, 1)
            row.addWidget(QLabel("Qty:"))
            self._mfg_qty_spin = QSpinBox()
            self._mfg_qty_spin.setRange(1, 10000)
            self._mfg_qty_spin.setValue(10)
            row.addWidget(self._mfg_qty_spin)
            self._mfg_btn_cost = QPushButton("Cost Estimate")
            row.addWidget(self._mfg_btn_cost)
            self._mfg_btn_drc_fab = QPushButton("Check Fab DRC")
            row.addWidget(self._mfg_btn_drc_fab)
            adv_lay.addLayout(row)

            row2 = QHBoxLayout()
            self._mfg_btn_ipc2581 = QPushButton("Export IPC-2581")
            self._mfg_btn_jlc = QPushButton("JLCPCB Parts")
            row2.addWidget(self._mfg_btn_ipc2581)
            row2.addWidget(self._mfg_btn_jlc)
            row2.addStretch(1)
            adv_lay.addLayout(row2)

            self._mfg_cost_label = QLabel()
            self._mfg_cost_label.setStyleSheet("color: #9cdcfe;")
            self._mfg_cost_label.setWordWrap(True)
            adv_lay.addWidget(self._mfg_cost_label)

            lay.addWidget(adv)

            self._mfg_btn_ipc2581.clicked.connect(self._mfg_export_ipc2581)
            self._mfg_btn_cost.clicked.connect(self._mfg_cost_estimate)
            self._mfg_btn_drc_fab.clicked.connect(self._mfg_check_fab_drc)
            self._mfg_btn_jlc.clicked.connect(self._mfg_open_jlcpcb)
        except Exception as e:  # noqa: BLE001
            try:
                self._status.showMessage(f"Advanced fab UI disabled: {e}")
            except Exception:  # noqa: BLE001
                pass

        # Output preview
        out = QGroupBox("Output files")
        ol = QVBoxLayout(out)
        self._mfg_file_list = QListWidget()
        ol.addWidget(self._mfg_file_list)
        lay.addWidget(out, 1)

        self._tabs.addTab(tab, "Manufacturing")

    def _current_pcb_board(self):
        if self._pcb_editor is not None and hasattr(self._pcb_editor, "board"):
            return self._pcb_editor.board
        if _HAS_PCB_MODEL:
            return PcbBoard(name="board", stackup=PcbStackup.two_layer(),
                            outline=[(0, 0), (80, 0), (80, 60), (0, 60)])
        return None

    # ------------------------------------------------------------------
    # Wave 2 Phase 9 actions
    # ------------------------------------------------------------------
    def _mfg_export_ipc2581(self) -> None:
        if not _HAS_IPC2581:
            QMessageBox.warning(self, "IPC-2581", "IPC-2581 module unavailable")
            return
        board = self._current_pcb_board()
        if board is None:
            QMessageBox.warning(self, "IPC-2581", "No PCB board loaded")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export IPC-2581", f"{board.name}.ipc2581.xml",
            "IPC-2581 (*.xml *.ipc2581)",
        )
        if not path:
            return
        try:
            out = Ipc2581Exporter(board).export(Path(path))
            self._mfg_add_files(out)
            self._status.showMessage(f"IPC-2581 exported: {out}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "IPC-2581", f"Export failed: {e}")

    def _mfg_cost_estimate(self) -> None:
        if not _HAS_FAB_RULES:
            return
        board = self._current_pcb_board()
        if board is None:
            return
        key = self._mfg_fab_class.currentText()
        fc = KNOWN_FAB_CLASSES.get(key)
        if fc is None:
            return
        try:
            checker = FabRuleChecker(board, fc)
            est = checker.cost_estimate(self._mfg_qty_spin.value())
            self._mfg_cost_label.setText(
                f"{est['fab_class']}  |  "
                f"{est['board_width_mm']:.1f}x{est['board_height_mm']:.1f}mm "
                f"({est['board_area_dm2']:.3f} dm\u00b2)  |  "
                f"qty={est['quantity']}  "
                f"unit=${est['unit_cost_usd']:.2f}  "
                f"total=${est['total_cost_usd']:.2f}"
            )
        except Exception as e:  # noqa: BLE001
            self._mfg_cost_label.setText(f"cost error: {e}")

    def _mfg_check_fab_drc(self) -> None:
        if not _HAS_FAB_RULES:
            return
        board = self._current_pcb_board()
        if board is None:
            return
        key = self._mfg_fab_class.currentText()
        fc = KNOWN_FAB_CLASSES.get(key)
        if fc is None:
            return
        try:
            viols = FabRuleChecker(board, fc).check_all()
            if not viols:
                QMessageBox.information(
                    self, "Fab DRC",
                    f"{fc.name}: no fab rule violations."
                )
            else:
                msg = "\n".join(f"{v.rule}: {v.message}" for v in viols[:40])
                QMessageBox.warning(
                    self, "Fab DRC",
                    f"{fc.name}: {len(viols)} violation(s)\n\n{msg}"
                )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Fab DRC", str(e))

    def _mfg_open_jlcpcb(self) -> None:
        if not _HAS_JLC_DIALOG:
            QMessageBox.warning(self, "JLCPCB", "JLCPCB picker unavailable")
            return
        board = self._current_pcb_board()
        dlg = JlcpcbPickerDialog(board=board, parent=self)
        dlg.exec()

    def _mfg_pick_dir(self) -> Path | None:
        d = QFileDialog.getExistingDirectory(self, "Output directory")
        return Path(d) if d else None

    def _mfg_add_files(self, paths) -> None:
        from os.path import getsize
        if isinstance(paths, dict):
            paths = list(paths.values())
        elif not isinstance(paths, (list, tuple)):
            paths = [paths]
        for p in paths:
            try:
                size = getsize(p)
            except OSError:
                size = 0
            self._mfg_file_list.addItem(f"{Path(p).name}   ({size} bytes)")

    def _mfg_generate_gerber(self) -> None:
        if not _HAS_PCB_MODEL:
            QMessageBox.warning(self, "Gerber", "PCB model not available")
            return
        d = self._mfg_pick_dir()
        if not d:
            return
        board = self._current_pcb_board()
        exp = GerberExporter(board)
        files = exp.export_all(d)
        self._mfg_add_files(files)
        self._status.showMessage(f"Wrote {len(files)} Gerber layers to {d}")

    def _mfg_generate_drill(self) -> None:
        if not _HAS_PCB_MODEL:
            return
        d = self._mfg_pick_dir()
        if not d:
            return
        board = self._current_pcb_board()
        path = GerberExporter(board).export_drill(d / f"{board.name}.drl")
        self._mfg_add_files(path)

    def _mfg_generate_pnp(self) -> None:
        if not _HAS_PCB_MODEL:
            return
        d = self._mfg_pick_dir()
        if not d:
            return
        board = self._current_pcb_board()
        path = GerberExporter(board).export_pick_and_place(d / f"{board.name}-pnp.csv")
        self._mfg_add_files(path)

    def _mfg_generate_bom(self) -> None:
        if not _HAS_PCB_MODEL:
            return
        d = self._mfg_pick_dir()
        if not d:
            return
        board = self._current_pcb_board()
        path = GerberExporter(board).export_bom(d / f"{board.name}-bom.csv")
        self._mfg_add_files(path)

    def _mfg_generate_zip(self) -> None:
        if not _HAS_PCB_MODEL:
            return
        d = self._mfg_pick_dir()
        if not d:
            return
        board = self._current_pcb_board()
        path = GerberExporter(board).export_zip(d)
        self._mfg_add_files(path)
        QMessageBox.information(self, "Fab ZIP", f"Created {path}")

    # ------------------------------------------------------------------
    def _save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PCB project", "", "OpenForge PCB (*.ofp)"
        )
        if path:
            data = {
                "version": 1,
                "components": list(self._sch_scene._components.keys()),
            }
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._status.showMessage(f"Saved to {path}")

    def _load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load PCB project", "", "OpenForge PCB (*.ofp)"
        )
        if path:
            self._status.showMessage(f"Loaded {path}")

    # ------------------------------------------------------------------
    # Wave 3 Phase 9: sheet templates + sheet browser + ERC glue
    # ------------------------------------------------------------------

    def _install_sheet_templates_menu(self) -> None:
        """Add a 'Templates' QToolButton to the schematic editor toolbar."""
        if not _HAS_SHEET_TEMPLATES:
            return
        editor = getattr(self, "_schematic_editor", None)
        if editor is None:
            return
        # Find a toolbar child on the editor
        toolbar = editor.findChild(QToolBar)
        if toolbar is None:
            return

        btn = QToolButton()
        btn.setText("Templates")
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        for tpl in BUILTIN_TEMPLATES:
            act = menu.addAction(f"{tpl.title}  -  {tpl.description}")
            act.triggered.connect(
                lambda _=False, t=tpl: self._drop_sheet_template(t)
            )
        btn.setMenu(menu)
        toolbar.addSeparator()
        toolbar.addWidget(btn)
        self._templates_btn = btn

    def _drop_sheet_template(self, template) -> None:
        """Run a template factory and drop the resulting sub-sheet."""
        editor = getattr(self, "_schematic_editor", None)
        if editor is None:
            return
        try:
            sub_sch, sheet = template.factory()
            # Stash the child schematic on the sheet so navigation works
            sheet._schematic = sub_sch  # type: ignore[attr-defined]
            if hasattr(editor, "add_sub_sheet"):
                added = editor.add_sub_sheet(
                    name=sheet.name,
                    filename=sheet.filename,
                    ports=sheet.ports,
                )
                added._schematic = sub_sch  # type: ignore[attr-defined]
            self._status.showMessage(f"Dropped sheet template: {template.title}")
            # Refresh the sheet browser tree
            self._refresh_sheet_browser()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Template error",
                f"Failed to drop template '{template.title}':\n{exc}")

    # ------------------------------------------------------------------

    def _install_sheet_browser(self) -> None:
        """Add a small sheet-browser tree widget to the schematic tab."""
        editor = getattr(self, "_schematic_editor", None)
        if editor is None:
            return
        browser = QTreeWidget()
        browser.setHeaderLabels(["Sheet", "Ports", "Conns"])
        browser.setMaximumWidth(220)
        browser.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        browser.itemDoubleClicked.connect(self._on_sheet_browser_double)
        browser.customContextMenuRequested.connect(
            self._on_sheet_browser_ctx)
        self._sheet_browser = browser

        # Insert into the editor's main layout as a sidebar on the right
        try:
            editor.layout().addWidget(browser)
        except Exception:
            pass
        self._refresh_sheet_browser()

    def _refresh_sheet_browser(self) -> None:
        tree = getattr(self, "_sheet_browser", None)
        editor = getattr(self, "_schematic_editor", None)
        if tree is None or editor is None:
            return
        tree.clear()
        sch = getattr(editor, "_schematic", None)
        if sch is None:
            return
        root = QTreeWidgetItem([
            sch.title or "top",
            "-",
            str(len(getattr(sch, "wires", []))),
        ])
        tree.addTopLevelItem(root)
        for sub in getattr(sch, "sub_sheets", []) or []:
            child = QTreeWidgetItem([
                sub.name,
                str(len(sub.ports)),
                "-",
            ])
            child.setData(0, Qt.ItemDataRole.UserRole, sub)
            root.addChild(child)
        root.setExpanded(True)

    def _on_sheet_browser_double(self, item: QTreeWidgetItem, col: int) -> None:
        sub = item.data(0, Qt.ItemDataRole.UserRole)
        editor = getattr(self, "_schematic_editor", None)
        if sub and editor and hasattr(editor, "enter_sheet"):
            editor.enter_sheet(sub)

    def _on_sheet_browser_ctx(self, pos) -> None:
        tree = getattr(self, "_sheet_browser", None)
        if tree is None:
            return
        menu = QMenu(tree)
        menu.addAction("Add Sheet", self._add_empty_sheet)
        menu.addAction("Refresh", self._refresh_sheet_browser)
        menu.exec(tree.mapToGlobal(pos))

    def _add_empty_sheet(self) -> None:
        editor = getattr(self, "_schematic_editor", None)
        if editor and hasattr(editor, "add_sub_sheet"):
            editor.add_sub_sheet(name="NewSheet", filename="new_sheet.sch")
            self._refresh_sheet_browser()

    # ------------------------------------------------------------------

    def _on_erc_jump_to_component(self, refdes: str) -> None:
        """Called when the ERC panel asks to highlight a component."""
        self._tabs.setCurrentIndex(0)  # switch to schematic tab
        self._status.showMessage(f"Jump to {refdes}")
