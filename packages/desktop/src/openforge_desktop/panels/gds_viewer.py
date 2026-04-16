"""Native GDSII layout viewer with interactive rendering in QGraphicsView.

Parses GDSII binary stream format and renders BOUNDARY (polygons), PATH
(wires), SREF (cell references), and TEXT (labels) elements directly in a
Qt graphics scene.  Provides layer visibility control, cursor-position
readout, measurement ruler, cell hierarchy tree, selection with property
display, DRC violation overlay, and cross-probing signals.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QDockWidget,
    QFileDialog,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ._theme import panel_tab_qss

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
_BLUE: Final[str] = "#89b4fa"
_GREEN: Final[str] = "#a6e3a1"
_RED: Final[str] = "#f38ba8"
_YELLOW: Final[str] = "#f9e2af"
_MAUVE: Final[str] = "#cba6f7"
_PEACH: Final[str] = "#fab387"
_TEAL: Final[str] = "#94e2d5"
_PINK: Final[str] = "#f5c2e7"
_SAPPHIRE: Final[str] = "#74c7ec"
_LAVENDER: Final[str] = "#b4befe"
_FLAMINGO: Final[str] = "#f2cdcd"
_ROSEWATER: Final[str] = "#f5e0dc"

_ALT_ROW: Final[str] = "#1a1a2e"

_ZOOM_FACTOR: Final[float] = 1.15

# ── Default layer colours (Catppuccin-inspired) ─────────────────────────────

_DEFAULT_LAYER_COLORS: Final[list[str]] = [
    _BLUE,
    _RED,
    _GREEN,
    _MAUVE,
    _PEACH,
    _YELLOW,
    _TEAL,
    _PINK,
    _SAPPHIRE,
    _LAVENDER,
    _FLAMINGO,
    _ROSEWATER,
    _SUBTEXT,
    _OVERLAY0,
    "#89dceb",
    "#94e2d5",
    "#a6e3a1",
    "#f9e2af",
    "#fab387",
    "#f38ba8",
    "#eba0ac",
    "#cba6f7",
    "#b4befe",
    "#74c7ec",
]

# ── GDSII record types (subset) ─────────────────────────────────────────────

_HEADER = 0x0002
_BGNLIB = 0x0102
_LIBNAME = 0x0206
_UNITS = 0x0305
_ENDLIB = 0x0400
_BGNSTR = 0x0502
_STRNAME = 0x0606
_ENDSTR = 0x0700
_BOUNDARY = 0x0800
_PATH = 0x0900
_SREF = 0x0A00
_AREF = 0x0B00
_TEXT = 0x0C00
_LAYER = 0x0D02
_DATATYPE = 0x0E02
_WIDTH = 0x0F03
_XY = 0x1003
_ENDEL = 0x1100
_SNAME = 0x1206
_COLROW = 0x1302
_TEXTTYPE = 0x1602
_STRING = 0x1906
_STRANS = 0x1A01
_MAG = 0x1B05
_ANGLE = 0x1C05
_PATHTYPE = 0x2102
_PROPATTR = 0x2B02
_PROPVALUE = 0x2C06


# ── GDS data model ──────────────────────────────────────────────────────────


@dataclass
class GDSBoundary:
    layer: int = 0
    datatype: int = 0
    points: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class GDSPath:
    layer: int = 0
    datatype: int = 0
    width: int = 0
    pathtype: int = 0
    points: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class GDSSRef:
    struct_name: str = ""
    origin: tuple[int, int] = (0, 0)
    strans: int = 0
    mag: float = 1.0
    angle: float = 0.0


@dataclass
class GDSARef:
    struct_name: str = ""
    origin: tuple[int, int] = (0, 0)
    strans: int = 0
    mag: float = 1.0
    angle: float = 0.0
    cols: int = 1
    rows: int = 1
    col_vec: tuple[int, int] = (0, 0)
    row_vec: tuple[int, int] = (0, 0)


@dataclass
class GDSText:
    layer: int = 0
    texttype: int = 0
    string: str = ""
    origin: tuple[int, int] = (0, 0)
    strans: int = 0
    mag: float = 1.0
    angle: float = 0.0


@dataclass
class GDSStructure:
    name: str = ""
    boundaries: list[GDSBoundary] = field(default_factory=list)
    paths: list[GDSPath] = field(default_factory=list)
    srefs: list[GDSSRef] = field(default_factory=list)
    arefs: list[GDSARef] = field(default_factory=list)
    texts: list[GDSText] = field(default_factory=list)


@dataclass
class GDSLibrary:
    name: str = ""
    units_user: float = 1e-6
    units_db: float = 1e-9
    structures: dict[str, GDSStructure] = field(default_factory=dict)


# ── GDS binary parser ───────────────────────────────────────────────────────


def _read_record(data: bytes, offset: int) -> tuple[int, int, bytes, int]:
    """Read one GDSII record.  Returns (full_record_code, data_type, payload, new_offset).

    The full_record_code is the 16-bit value (record_type << 8) | data_type, matching
    the constants like _BGNSTR = 0x0502.
    """
    if offset + 4 > len(data):
        return (0, 0, b"", len(data))
    length = struct.unpack(">H", data[offset : offset + 2])[0]
    if length < 4:
        # Avoid infinite loop on corrupt records
        return (0, 0, b"", len(data))
    rec_raw = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
    data_type = rec_raw & 0x00FF
    # Return the full 16-bit code so it matches the constants
    payload = data[offset + 4 : offset + length] if length > 4 else b""
    return (rec_raw, data_type, payload, offset + length)


def _decode_int16(payload: bytes) -> list[int]:
    count = len(payload) // 2
    return list(struct.unpack(f">{count}h", payload[: count * 2]))


def _decode_int32(payload: bytes) -> list[int]:
    count = len(payload) // 4
    return list(struct.unpack(f">{count}i", payload[: count * 4]))


def _decode_real8(payload: bytes) -> list[float]:
    """Decode GDSII 8-byte real (excess-64 exponent, 56-bit mantissa)."""
    results: list[float] = []
    for i in range(0, len(payload), 8):
        b = payload[i : i + 8]
        if len(b) < 8:
            break
        sign = (b[0] >> 7) & 1
        exp = (b[0] & 0x7F) - 64
        mantissa = 0
        for j in range(1, 8):
            mantissa = (mantissa << 8) | b[j]
        value = mantissa / (2.0**56) * (16.0**exp)
        if sign:
            value = -value
        results.append(value)
    return results


def _decode_string(payload: bytes) -> str:
    return payload.rstrip(b"\x00").decode("ascii", errors="replace")


def _decode_xy(payload: bytes) -> list[tuple[int, int]]:
    vals = _decode_int32(payload)
    pairs: list[tuple[int, int]] = []
    for i in range(0, len(vals) - 1, 2):
        pairs.append((vals[i], vals[i + 1]))
    return pairs


def parse_gds(filepath: str | Path) -> GDSLibrary:
    """Parse a GDSII binary file and return a GDSLibrary."""
    data = Path(filepath).read_bytes()
    lib = GDSLibrary()
    offset = 0
    current_struct: GDSStructure | None = None
    current_element: Any = None

    while offset < len(data):
        rec_type, dtype, payload, offset = _read_record(data, offset)
        if rec_type == 0 and offset >= len(data):
            break

        if rec_type == _LIBNAME:
            lib.name = _decode_string(payload)
        elif rec_type == _UNITS:
            reals = _decode_real8(payload)
            if len(reals) >= 2:
                lib.units_user = reals[0]
                lib.units_db = reals[1]
        elif rec_type == _BGNSTR:
            current_struct = GDSStructure()
        elif rec_type == _STRNAME:
            if current_struct is not None:
                current_struct.name = _decode_string(payload)
        elif rec_type == _ENDSTR:
            if current_struct is not None and current_struct.name:
                lib.structures[current_struct.name] = current_struct
            current_struct = None
        elif rec_type == _BOUNDARY:
            current_element = GDSBoundary()
        elif rec_type == _PATH:
            current_element = GDSPath()
        elif rec_type == _SREF:
            current_element = GDSSRef()
        elif rec_type == _AREF:
            current_element = GDSARef()
        elif rec_type == _TEXT:
            current_element = GDSText()
        elif rec_type == _LAYER:
            vals = _decode_int16(payload)
            if vals and current_element is not None and hasattr(current_element, "layer"):
                current_element.layer = vals[0]
        elif rec_type == _DATATYPE:
            vals = _decode_int16(payload)
            if vals and current_element is not None and hasattr(current_element, "datatype"):
                current_element.datatype = vals[0]
        elif rec_type == _TEXTTYPE:
            vals = _decode_int16(payload)
            if vals and isinstance(current_element, GDSText):
                current_element.texttype = vals[0]
        elif rec_type == _WIDTH:
            vals = _decode_int32(payload)
            if vals and isinstance(current_element, GDSPath):
                current_element.width = vals[0]
        elif rec_type == _PATHTYPE:
            vals = _decode_int16(payload)
            if vals and isinstance(current_element, GDSPath):
                current_element.pathtype = vals[0]
        elif rec_type == _XY:
            pts = _decode_xy(payload)
            if isinstance(current_element, (GDSBoundary, GDSPath)):
                current_element.points = pts
            elif isinstance(current_element, GDSSRef):
                if pts:
                    current_element.origin = pts[0]
            elif isinstance(current_element, GDSARef):
                if len(pts) >= 3:
                    current_element.origin = pts[0]
                    current_element.col_vec = pts[1]
                    current_element.row_vec = pts[2]
            elif isinstance(current_element, GDSText) and pts:
                current_element.origin = pts[0]
        elif rec_type == _SNAME:
            name = _decode_string(payload)
            if isinstance(current_element, (GDSSRef, GDSARef)):
                current_element.struct_name = name
        elif rec_type == _COLROW:
            vals = _decode_int16(payload)
            if len(vals) >= 2 and isinstance(current_element, GDSARef):
                current_element.cols = vals[0]
                current_element.rows = vals[1]
        elif rec_type == _STRING:
            if isinstance(current_element, GDSText):
                current_element.string = _decode_string(payload)
        elif rec_type == _STRANS:
            vals = _decode_int16(payload)
            if vals and hasattr(current_element, "strans"):
                current_element.strans = vals[0]
        elif rec_type == _MAG:
            reals = _decode_real8(payload)
            if reals and hasattr(current_element, "mag"):
                current_element.mag = reals[0]
        elif rec_type == _ANGLE:
            reals = _decode_real8(payload)
            if reals and hasattr(current_element, "angle"):
                current_element.angle = reals[0]
        elif rec_type == _ENDEL:
            if current_struct is not None and current_element is not None:
                if isinstance(current_element, GDSBoundary):
                    current_struct.boundaries.append(current_element)
                elif isinstance(current_element, GDSPath):
                    current_struct.paths.append(current_element)
                elif isinstance(current_element, GDSSRef):
                    current_struct.srefs.append(current_element)
                elif isinstance(current_element, GDSARef):
                    current_struct.arefs.append(current_element)
                elif isinstance(current_element, GDSText):
                    current_struct.texts.append(current_element)
            current_element = None
        elif rec_type == _ENDLIB:
            break
    return lib


# ── Custom QGraphicsView for GDS rendering ──────────────────────────────────

_ROLE_LAYER = 0
_ROLE_DATATYPE = 1
_ROLE_ELEMENT_TYPE = 2

_RULER_MODE = "ruler"
_SELECT_MODE = "select"


class _GDSScene(QGraphicsScene):
    """Scene with configurable grid background."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(_BG)))
        self._grid_spacing: float = 1.0  # in um
        self._grid_visible: bool = True

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self._grid_visible:
            return
        # Only draw grid when zoomed in enough
        view = self.views()[0] if self.views() else None
        if view is None:
            return
        t = view.transform()
        scale = math.sqrt(t.m11() ** 2 + t.m12() ** 2)
        pixel_spacing = self._grid_spacing * scale
        if pixel_spacing < 10:
            return  # Too dense, skip
        pen = QPen(QColor(_SURFACE0), 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        left = rect.left() - (rect.left() % self._grid_spacing)
        top = rect.top() - (rect.top() % self._grid_spacing)
        x = left
        while x <= rect.right():
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
            x += self._grid_spacing
        y = top
        while y <= rect.bottom():
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += self._grid_spacing


class _GDSView(QGraphicsView):
    """View with scroll-zoom and pan."""

    coordinate_moved = Signal(float, float)
    item_clicked = Signal(object)

    def __init__(self, scene: _GDSScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self._pan_active = False
        self._pan_start = QPointF()
        self._mode = _SELECT_MODE
        self._ruler_start: QPointF | None = None
        self._ruler_line: QGraphicsLineItem | None = None

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Zoom centred on cursor."""
        anchor = self.mapToScene(event.position().toPoint())
        factor = _ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / _ZOOM_FACTOR
        self.scale(factor, factor)
        new_pos = self.mapToScene(event.position().toPoint())
        delta = new_pos - anchor
        self.translate(delta.x(), delta.y())

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._mode == _RULER_MODE:
                scene_pos = self.mapToScene(event.position().toPoint())
                if self._ruler_start is None:
                    self._ruler_start = scene_pos
                    pen = QPen(QColor(_YELLOW), 2)
                    pen.setCosmetic(True)
                    self._ruler_line = self.scene().addLine(QLineF(scene_pos, scene_pos), pen)
                else:
                    # Finish ruler measurement
                    self._ruler_start = None
                    self._ruler_line = None
                return
            # Selection mode
            scene_pos = self.mapToScene(event.position().toPoint())
            items = self.scene().items(scene_pos)
            for item in items:
                if isinstance(item, (QGraphicsPathItem, QGraphicsSimpleTextItem)):
                    self.item_clicked.emit(item)
                    break
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._pan_active:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.translate(delta.x() / self.transform().m11(), delta.y() / self.transform().m22())
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        self.coordinate_moved.emit(scene_pos.x(), scene_pos.y())
        if self._ruler_line is not None and self._ruler_start is not None:
            self._ruler_line.setLine(QLineF(self._ruler_start, scene_pos))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().mouseReleaseEvent(event)


# ── Minimap widget ──────────────────────────────────────────────────────────


class _MinimapWidget(QWidget):
    """Small overview widget showing the full layout extent."""

    navigate_to = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(180, 140)
        self._image: QImage | None = None
        self._viewport_rect: QRectF = QRectF()
        self._scene_rect: QRectF = QRectF()

    def update_minimap(self, scene: QGraphicsScene, view: QGraphicsView) -> None:
        sr = scene.sceneRect()
        if sr.isEmpty():
            return
        self._scene_rect = sr
        img = QImage(self.width(), self.height(), QImage.Format.Format_ARGB32)
        img.fill(QColor(_CRUST))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(painter, QRectF(0, 0, self.width(), self.height()), sr)
        painter.end()
        self._image = img
        # Map viewport rect
        vp_scene = view.mapToScene(view.viewport().rect())
        if vp_scene.count() >= 2:
            self._viewport_rect = QRectF(vp_scene.boundingRect())
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        if self._image:
            painter.drawImage(0, 0, self._image)
        if not self._scene_rect.isEmpty() and not self._viewport_rect.isEmpty():
            sx = self.width() / self._scene_rect.width()
            sy = self.height() / self._scene_rect.height()
            vr = QRectF(
                (self._viewport_rect.x() - self._scene_rect.x()) * sx,
                (self._viewport_rect.y() - self._scene_rect.y()) * sy,
                self._viewport_rect.width() * sx,
                self._viewport_rect.height() * sy,
            )
            pen = QPen(QColor(_BLUE), 1.5)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(137, 180, 250, 30)))
            painter.drawRect(vr)
        painter.end()

    def mousePressEvent(self, event):  # noqa: N802
        if not self._scene_rect.isEmpty() and self._image:
            sx = self._scene_rect.width() / self.width()
            sy = self._scene_rect.height() / self.height()
            scene_x = event.position().x() * sx + self._scene_rect.x()
            scene_y = event.position().y() * sy + self._scene_rect.y()
            self.navigate_to.emit(scene_x, scene_y)


# ── Layer panel ─────────────────────────────────────────────────────────────


class _LayerPanelWidget(QWidget):
    """Layer list with visibility checkboxes and colour indicators."""

    visibility_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)
        self._header = QLabel("Layers")
        self._header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._header.setStyleSheet(f"color: {_BLUE};")
        self._layout.addWidget(self._header)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(1)
        self._scroll.setWidget(self._scroll_content)
        self._layout.addWidget(self._scroll)
        self._checkboxes: dict[int, QCheckBox] = {}
        self._colors: dict[int, str] = {}

    def set_layers(self, layers: set[int], colors: dict[int, str]) -> None:
        # Clear existing
        while self._scroll_layout.count():
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()
        self._colors = dict(colors)
        for layer_num in sorted(layers):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 0, 2, 0)
            rl.setSpacing(4)
            cb = QCheckBox()
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_visibility_change)
            self._checkboxes[layer_num] = cb
            rl.addWidget(cb)
            color_lbl = QLabel("  ")
            c = colors.get(layer_num, _OVERLAY0)
            color_lbl.setFixedSize(16, 12)
            color_lbl.setStyleSheet(
                f"background-color: {c}; border: 1px solid {_SURFACE1}; border-radius: 2px;"
            )
            color_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            color_lbl.mousePressEvent = lambda e, ln=layer_num, lb=color_lbl: self._pick_color(
                ln, lb
            )
            rl.addWidget(color_lbl)
            name_lbl = QLabel(f"Layer {layer_num}")
            name_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 11px;")
            rl.addWidget(name_lbl)
            rl.addStretch()
            self._scroll_layout.addWidget(row)
        self._scroll_layout.addStretch()

    def _pick_color(self, layer_num: int, label: QLabel) -> None:
        color = QColorDialog.getColor(QColor(self._colors.get(layer_num, _OVERLAY0)), self)
        if color.isValid():
            self._colors[layer_num] = color.name()
            label.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid {_SURFACE1}; border-radius: 2px;"
            )
            self.visibility_changed.emit()

    def _on_visibility_change(self) -> None:
        self.visibility_changed.emit()

    def get_visible_layers(self) -> set[int]:
        return {ln for ln, cb in self._checkboxes.items() if cb.isChecked()}

    def get_layer_colors(self) -> dict[int, str]:
        return dict(self._colors)


# ── Cell hierarchy tree ─────────────────────────────────────────────────────


class _CellTreeWidget(QTreeWidget):
    """Tree showing cell hierarchy with instance counts."""

    cell_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Cell", "Instances"])
        self.setAlternatingRowColors(True)
        self.setColumnCount(2)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.itemDoubleClicked.connect(self._on_double_click)

    def populate(self, lib: GDSLibrary, top_cell: str | None = None) -> None:
        self.clear()
        if not lib.structures:
            return
        # Find top cell (not referenced by others)
        referenced: set[str] = set()
        for st in lib.structures.values():
            for sr in st.srefs:
                referenced.add(sr.struct_name)
            for ar in st.arefs:
                referenced.add(ar.struct_name)
        top_cells = [n for n in lib.structures if n not in referenced]
        if top_cell and top_cell in lib.structures:
            top_cells = [top_cell]
        elif not top_cells:
            top_cells = list(lib.structures.keys())[:1]

        for tc in top_cells:
            root = QTreeWidgetItem([tc, "top"])
            root.setData(0, Qt.ItemDataRole.UserRole, tc)
            self.addTopLevelItem(root)
            self._add_children(root, tc, lib)
            root.setExpanded(True)

    def _add_children(self, parent_item: QTreeWidgetItem, cell_name: str, lib: GDSLibrary) -> None:
        st = lib.structures.get(cell_name)
        if st is None:
            return
        # Count instances per child cell
        counts: dict[str, int] = {}
        for sr in st.srefs:
            counts[sr.struct_name] = counts.get(sr.struct_name, 0) + 1
        for ar in st.arefs:
            total = ar.cols * ar.rows
            counts[ar.struct_name] = counts.get(ar.struct_name, 0) + total
        for child_name, count in sorted(counts.items()):
            child_item = QTreeWidgetItem([child_name, str(count)])
            child_item.setData(0, Qt.ItemDataRole.UserRole, child_name)
            parent_item.addChild(child_item)
            self._add_children(child_item, child_name, lib)

    def _on_double_click(self, item: QTreeWidgetItem, col: int) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self.cell_activated.emit(name)


# ── Main GDS Viewer Panel ───────────────────────────────────────────────────


class GDSViewerPanel(QDockWidget):
    """Dock widget hosting a native GDSII layout viewer."""

    cell_selected = Signal(str)
    coordinate_clicked = Signal(float, float)

    def __init__(self, title: str = "GDS Viewer", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dark = True
        self._lib: GDSLibrary | None = None
        self._top_cell: str | None = None
        self._layer_colors: dict[int, str] = {}
        self._all_layers: set[int] = set()
        self._drc_items: list[QGraphicsItem] = []
        self._selected_item: QGraphicsPathItem | None = None

        # Build UI
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(self._toolbar.iconSize())
        self._toolbar.setStyleSheet(
            f"QToolBar {{ background: {_MANTLE}; border-bottom: 1px solid {_SURFACE0}; spacing: 4px; padding: 2px; }}"
        )
        self._act_open = self._toolbar.addAction("Open GDS")
        self._act_open.triggered.connect(self._open_file)
        self._toolbar.addSeparator()
        self._act_zoom_fit = self._toolbar.addAction("Fit")
        self._act_zoom_fit.triggered.connect(self._zoom_fit)
        self._act_zoom_in = self._toolbar.addAction("Zoom +")
        self._act_zoom_in.triggered.connect(lambda: self._view.scale(_ZOOM_FACTOR, _ZOOM_FACTOR))
        self._act_zoom_out = self._toolbar.addAction("Zoom -")
        self._act_zoom_out.triggered.connect(
            lambda: self._view.scale(1 / _ZOOM_FACTOR, 1 / _ZOOM_FACTOR)
        )
        self._toolbar.addSeparator()
        self._act_ruler = self._toolbar.addAction("Ruler")
        self._act_ruler.setCheckable(True)
        self._act_ruler.toggled.connect(self._toggle_ruler)
        self._act_select = self._toolbar.addAction("Select")
        self._act_select.setCheckable(True)
        self._act_select.setChecked(True)
        self._act_select.toggled.connect(self._toggle_select)
        self._toolbar.addSeparator()
        self._act_screenshot = self._toolbar.addAction("Screenshot")
        self._act_screenshot.triggered.connect(self._export_png)
        self._act_svg = self._toolbar.addAction("SVG")
        self._act_svg.triggered.connect(self._export_svg)
        main_layout.addWidget(self._toolbar)

        # Splitter: left sidebar | graphics view | right sidebar
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left sidebar: layers + hierarchy
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        self._layer_panel = _LayerPanelWidget()
        self._layer_panel.visibility_changed.connect(self._refresh_visibility)
        left_layout.addWidget(self._layer_panel, stretch=1)

        self._cell_tree = _CellTreeWidget()
        self._cell_tree.cell_activated.connect(self._on_cell_activated)
        left_layout.addWidget(self._cell_tree, stretch=1)
        left_panel.setFixedWidth(200)

        # Graphics view
        self._scene = _GDSScene()
        self._view = _GDSView(self._scene)
        self._view.coordinate_moved.connect(self._update_coords)
        self._view.item_clicked.connect(self._on_item_clicked)

        # Right sidebar: properties + minimap
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        prop_label = QLabel("Properties")
        prop_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        prop_label.setStyleSheet(f"color: {_BLUE};")
        right_layout.addWidget(prop_label)

        self._prop_table = QTableWidget(0, 2)
        self._prop_table.setHorizontalHeaderLabels(["Property", "Value"])
        self._prop_table.horizontalHeader().setStretchLastSection(True)
        self._prop_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._prop_table.setAlternatingRowColors(True)
        self._prop_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self._prop_table, stretch=1)

        minimap_label = QLabel("Overview")
        minimap_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        minimap_label.setStyleSheet(f"color: {_BLUE};")
        right_layout.addWidget(minimap_label)

        self._minimap = _MinimapWidget()
        self._minimap.navigate_to.connect(self._navigate_to)
        right_layout.addWidget(self._minimap)
        right_panel.setFixedWidth(200)

        self._splitter.addWidget(left_panel)
        self._splitter.addWidget(self._view)
        self._splitter.addWidget(right_panel)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        main_layout.addWidget(self._splitter, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self._status.setStyleSheet(
            f"QStatusBar {{ background: {_MANTLE}; color: {_SUBTEXT}; font-size: 11px; "
            f"border-top: 1px solid {_SURFACE0}; }}"
        )
        self._coord_label = QLabel("X: 0.000 um  Y: 0.000 um")
        self._ruler_label = QLabel("")
        self._status.addWidget(self._coord_label)
        self._status.addPermanentWidget(self._ruler_label)
        main_layout.addWidget(self._status)

        self.setWidget(main_widget)
        self._apply_theme()

    # ── Public API ───────────────────────────────────────────────────────

    def load_gds(self, filepath: str | Path, top_cell: str | None = None) -> None:
        """Load and render a GDSII file."""
        self._lib = parse_gds(filepath)
        self._top_cell = top_cell
        self._discover_layers()
        self._render()
        self._cell_tree.populate(self._lib, top_cell)
        self._zoom_fit()

    def load_drc_results(self, violations: list[dict[str, Any]]) -> None:
        """Overlay DRC violation markers.

        Each violation dict should have 'x', 'y' (in um) and optionally
        'message' and 'rule'.
        """
        self._clear_drc()
        if self._lib is None:
            return
        for v in violations:
            x = float(v.get("x", 0))
            y = float(v.get("y", 0))
            msg = v.get("message", "DRC violation")
            # Draw red X marker
            size = 2.0
            path = QPainterPath()
            path.moveTo(x - size, y - size)
            path.lineTo(x + size, y + size)
            path.moveTo(x + size, y - size)
            path.lineTo(x - size, y + size)
            pen = QPen(QColor(_RED), 0.5)
            pen.setCosmetic(True)
            item = self._scene.addPath(path, pen)
            item.setToolTip(msg)
            item.setZValue(1000)
            self._drc_items.append(item)
            # Red circle around violation
            circle = QPainterPath()
            circle.addEllipse(QPointF(x, y), size * 1.2, size * 1.2)
            ci = self._scene.addPath(circle, pen, QBrush(QColor(243, 139, 168, 40)))
            ci.setToolTip(msg)
            ci.setZValue(999)
            self._drc_items.append(ci)

    def set_theme(self, dark: bool) -> None:
        """Switch between dark and light theme."""
        self._dark = dark
        self._apply_theme()
        if self._lib:
            self._render()

    # ── Signals / cross-probing ──────────────────────────────────────────

    def _on_cell_activated(self, name: str) -> None:
        self.cell_selected.emit(name)
        if self._lib and name in self._lib.structures:
            self._top_cell = name
            self._render()
            self._zoom_fit()

    def _on_item_clicked(self, item: QGraphicsItem) -> None:
        # Deselect previous
        if self._selected_item is not None:
            layer = self._selected_item.data(_ROLE_LAYER)
            if layer is not None:
                c = QColor(self._layer_colors.get(layer, _OVERLAY0))
                pen = QPen(c, 0)
                pen.setCosmetic(True)
                self._selected_item.setPen(pen)
                self._selected_item.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), 80)))

        if isinstance(item, QGraphicsPathItem):
            self._selected_item = item
            pen = QPen(QColor(_TEXT), 2)
            pen.setCosmetic(True)
            item.setPen(pen)
            self._show_properties(item)
        scene_pos = item.boundingRect().center()
        self.coordinate_clicked.emit(scene_pos.x(), scene_pos.y())

    def _show_properties(self, item: QGraphicsPathItem) -> None:
        self._prop_table.setRowCount(0)
        props: list[tuple[str, str]] = []
        el_type = item.data(_ROLE_ELEMENT_TYPE) or "unknown"
        props.append(("Type", str(el_type)))
        layer = item.data(_ROLE_LAYER)
        if layer is not None:
            props.append(("Layer", str(layer)))
        dt = item.data(_ROLE_DATATYPE)
        if dt is not None:
            props.append(("Datatype", str(dt)))
        br = item.boundingRect()
        props.append(("X", f"{br.x():.3f} um"))
        props.append(("Y", f"{br.y():.3f} um"))
        props.append(("Width", f"{br.width():.3f} um"))
        props.append(("Height", f"{br.height():.3f} um"))
        area = br.width() * br.height()
        props.append(("Bbox Area", f"{area:.3f} um^2"))

        self._prop_table.setRowCount(len(props))
        for i, (k, v) in enumerate(props):
            ki = QTableWidgetItem(k)
            ki.setForeground(QColor(_SUBTEXT))
            self._prop_table.setItem(i, 0, ki)
            vi = QTableWidgetItem(v)
            vi.setForeground(QColor(_TEXT))
            self._prop_table.setItem(i, 1, vi)

    # ── Layer discovery + rendering ──────────────────────────────────────

    def _discover_layers(self) -> None:
        if self._lib is None:
            return
        self._all_layers.clear()
        for st in self._lib.structures.values():
            for b in st.boundaries:
                self._all_layers.add(b.layer)
            for p in st.paths:
                self._all_layers.add(p.layer)
            for t in st.texts:
                self._all_layers.add(t.layer)
        # Assign colours
        self._layer_colors.clear()
        for i, ln in enumerate(sorted(self._all_layers)):
            self._layer_colors[ln] = _DEFAULT_LAYER_COLORS[i % len(_DEFAULT_LAYER_COLORS)]
        self._layer_panel.set_layers(self._all_layers, self._layer_colors)

    def _render(self) -> None:
        """Render the loaded GDS into the scene."""
        self._scene.clear()
        self._drc_items.clear()
        self._selected_item = None
        if self._lib is None:
            return

        visible = self._layer_panel.get_visible_layers()
        self._layer_colors = self._layer_panel.get_layer_colors()
        scale = self._lib.units_user / 1e-6 if self._lib.units_user else 1.0

        # Determine top cell
        top_name = self._top_cell
        if top_name is None or top_name not in self._lib.structures:
            referenced: set[str] = set()
            for st in self._lib.structures.values():
                for sr in st.srefs:
                    referenced.add(sr.struct_name)
                for ar in st.arefs:
                    referenced.add(ar.struct_name)
            unreferenced = [n for n in self._lib.structures if n not in referenced]
            top_name = unreferenced[0] if unreferenced else next(iter(self._lib.structures), None)

        if top_name is None:
            return

        self._render_structure(top_name, 0.0, 0.0, scale, visible, depth=0)

    def _render_structure(
        self,
        name: str,
        ox: float,
        oy: float,
        scale: float,
        visible: set[int],
        depth: int,
    ) -> None:
        if self._lib is None or depth > 50:
            return
        st = self._lib.structures.get(name)
        if st is None:
            return

        # Render boundaries (polygons)
        for b in st.boundaries:
            if b.layer not in visible:
                continue
            if len(b.points) < 3:
                continue
            color = QColor(self._layer_colors.get(b.layer, _OVERLAY0))
            path = QPainterPath()
            pts = [(ox + p[0] * scale, oy + p[1] * scale) for p in b.points]
            path.moveTo(pts[0][0], pts[0][1])
            for px, py in pts[1:]:
                path.lineTo(px, py)
            path.closeSubpath()
            pen = QPen(color, 0)
            pen.setCosmetic(True)
            fill = QColor(color.red(), color.green(), color.blue(), 80)
            item = self._scene.addPath(path, pen, QBrush(fill))
            item.setData(_ROLE_LAYER, b.layer)
            item.setData(_ROLE_DATATYPE, b.datatype)
            item.setData(_ROLE_ELEMENT_TYPE, "boundary")

        # Render paths (wires)
        for p in st.paths:
            if p.layer not in visible:
                continue
            if len(p.points) < 2:
                continue
            color = QColor(self._layer_colors.get(p.layer, _OVERLAY0))
            width_um = abs(p.width) * scale if p.width else 0.1
            path = QPainterPath()
            pts = [(ox + pt[0] * scale, oy + pt[1] * scale) for pt in p.points]
            # Build thick path by offsetting
            if width_um > 0:
                for i in range(len(pts) - 1):
                    x1, y1 = pts[i]
                    x2, y2 = pts[i + 1]
                    dx = x2 - x1
                    dy = y2 - y1
                    length = math.sqrt(dx * dx + dy * dy)
                    if length < 1e-9:
                        continue
                    nx = -dy / length * width_um / 2
                    ny = dx / length * width_um / 2
                    seg = QPainterPath()
                    seg.moveTo(x1 + nx, y1 + ny)
                    seg.lineTo(x2 + nx, y2 + ny)
                    seg.lineTo(x2 - nx, y2 - ny)
                    seg.lineTo(x1 - nx, y1 - ny)
                    seg.closeSubpath()
                    path.addPath(seg)
            else:
                path.moveTo(pts[0][0], pts[0][1])
                for px, py in pts[1:]:
                    path.lineTo(px, py)

            pen = QPen(color, 0)
            pen.setCosmetic(True)
            fill = QColor(color.red(), color.green(), color.blue(), 60)
            item = self._scene.addPath(path, pen, QBrush(fill))
            item.setData(_ROLE_LAYER, p.layer)
            item.setData(_ROLE_DATATYPE, p.datatype)
            item.setData(_ROLE_ELEMENT_TYPE, "path")

        # Render text labels
        for t in st.texts:
            if t.layer not in visible:
                continue
            tx = ox + t.origin[0] * scale
            ty = oy + t.origin[1] * scale
            color = QColor(self._layer_colors.get(t.layer, _TEXT))
            text_item = self._scene.addSimpleText(t.string)
            text_item.setPos(tx, ty)
            text_item.setBrush(QBrush(color))
            font = QFont("Monospace", 1)
            text_item.setFont(font)
            text_item.setData(_ROLE_LAYER, t.layer)
            text_item.setData(_ROLE_ELEMENT_TYPE, "text")

        # Render SREFs (cell instances)
        for sr in st.srefs:
            child_ox = ox + sr.origin[0] * scale
            child_oy = oy + sr.origin[1] * scale
            self._render_structure(sr.struct_name, child_ox, child_oy, scale, visible, depth + 1)

        # Render AREFs (arrayed cell instances)
        for ar in st.arefs:
            if ar.cols <= 0 or ar.rows <= 0:
                continue
            col_dx = (ar.col_vec[0] - ar.origin[0]) * scale / ar.cols if ar.cols > 0 else 0
            col_dy = (ar.col_vec[1] - ar.origin[1]) * scale / ar.cols if ar.cols > 0 else 0
            row_dx = (ar.row_vec[0] - ar.origin[0]) * scale / ar.rows if ar.rows > 0 else 0
            row_dy = (ar.row_vec[1] - ar.origin[1]) * scale / ar.rows if ar.rows > 0 else 0
            for c in range(min(ar.cols, 20)):  # Limit for performance
                for r in range(min(ar.rows, 20)):
                    cx = ox + ar.origin[0] * scale + c * col_dx + r * row_dx
                    cy = oy + ar.origin[1] * scale + c * col_dy + r * row_dy
                    self._render_structure(ar.struct_name, cx, cy, scale, visible, depth + 1)

    def _refresh_visibility(self) -> None:
        if self._lib:
            self._render()

    # ── Navigation ───────────────────────────────────────────────────────

    def _zoom_fit(self) -> None:
        sr = self._scene.itemsBoundingRect()
        if sr.isEmpty():
            return
        sr.adjust(-10, -10, 10, 10)
        self._view.fitInView(sr, Qt.AspectRatioMode.KeepAspectRatio)
        self._update_minimap()

    def _navigate_to(self, x: float, y: float) -> None:
        self._view.centerOn(x, y)

    def _update_coords(self, x: float, y: float) -> None:
        self._coord_label.setText(f"X: {x:.3f} um  Y: {y:.3f} um")
        if self._view._ruler_start is not None:
            dx = x - self._view._ruler_start.x()
            dy = y - self._view._ruler_start.y()
            dist = math.sqrt(dx * dx + dy * dy)
            self._ruler_label.setText(f"Ruler: {dist:.3f} um")
        self._update_minimap()

    def _update_minimap(self) -> None:
        self._minimap.update_minimap(self._scene, self._view)

    # ── Tool modes ───────────────────────────────────────────────────────

    def _toggle_ruler(self, checked: bool) -> None:
        if checked:
            self._act_select.setChecked(False)
            self._view.set_mode(_RULER_MODE)
            self._view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._view.set_mode(_SELECT_MODE)
            self._view.setCursor(Qt.CursorShape.ArrowCursor)
            self._ruler_label.setText("")

    def _toggle_select(self, checked: bool) -> None:
        if checked:
            self._act_ruler.setChecked(False)
            self._view.set_mode(_SELECT_MODE)
            self._view.setCursor(Qt.CursorShape.ArrowCursor)

    # ── File operations ──────────────────────────────────────────────────

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GDSII File", "", "GDSII Files (*.gds *.gds2 *.gdsii);;All Files (*)"
        )
        if path:
            self.load_gds(path)

    def _export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Screenshot", "layout.png", "PNG Images (*.png)"
        )
        if not path:
            return
        rect = self._scene.sceneRect()
        image = QImage(int(rect.width() * 4), int(rect.height() * 4), QImage.Format.Format_ARGB32)
        image.fill(QColor(_BG))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._scene.render(painter, QRectF(image.rect()), rect)
        painter.end()
        image.save(path)

    def _export_svg(self) -> None:
        try:
            from PySide6.QtSvg import QSvgGenerator
        except ImportError:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export SVG", "layout.svg", "SVG Files (*.svg)")
        if not path:
            return
        rect = self._scene.sceneRect()
        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(rect.size().toSize())
        generator.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
        painter = QPainter(generator)
        self._scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), rect)
        painter.end()

    # ── DRC helpers ──────────────────────────────────────────────────────

    def _clear_drc(self) -> None:
        for item in self._drc_items:
            self._scene.removeItem(item)
        self._drc_items.clear()

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        p = {True: _BG, False: "#f8f9fa"}
        bg = p[self._dark]
        mantle = _MANTLE if self._dark else "#e9ecef"
        surface0 = _SURFACE0 if self._dark else "#dee2e6"
        text = _TEXT if self._dark else "#212529"
        subtext = _SUBTEXT if self._dark else "#495057"
        blue = _BLUE if self._dark else "#0d6efd"

        self._scene.setBackgroundBrush(QBrush(QColor(bg)))
        base_qss = panel_tab_qss(self._dark)
        extra = f"""
            QDockWidget {{
                background-color: {bg};
                color: {text};
            }}
            QSplitter::handle {{
                background-color: {surface0};
            }}
            QToolBar {{
                background: {mantle};
                border-bottom: 1px solid {surface0};
            }}
            QScrollArea {{
                background: {bg};
                border: none;
            }}
            QTreeWidget {{
                background-color: {bg};
                color: {text};
                border: none;
                font-size: 11px;
            }}
            QTableWidget {{
                background-color: {bg};
                color: {text};
                border: none;
                font-size: 11px;
                gridline-color: {surface0};
            }}
        """
        self.setStyleSheet(base_qss + extra)
        self._toolbar.setStyleSheet(
            f"QToolBar {{ background: {mantle}; border-bottom: 1px solid {surface0}; spacing: 4px; padding: 2px; }}"
            f"QToolButton {{ color: {text}; background: transparent; border: 1px solid transparent; "
            f"border-radius: 3px; padding: 3px 8px; font-size: 11px; }}"
            f"QToolButton:hover {{ background: {surface0}; border-color: {surface0}; }}"
            f"QToolButton:checked {{ background: {blue}; color: {mantle}; }}"
        )
        self._status.setStyleSheet(
            f"QStatusBar {{ background: {mantle}; color: {subtext}; font-size: 11px; "
            f"border-top: 1px solid {surface0}; }}"
        )

    # ── Context menu ─────────────────────────────────────────────────────

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {_SURFACE0}; color: {_TEXT}; border: 1px solid {_SURFACE1}; }}"
            f"QMenu::item:selected {{ background: {_SURFACE1}; }}"
        )
        menu.addAction("Open GDS...", self._open_file)
        menu.addSeparator()
        menu.addAction("Zoom to Fit", self._zoom_fit)
        menu.addAction("Export PNG...", self._export_png)
        menu.addAction("Export SVG...", self._export_svg)
        menu.addSeparator()
        menu.addAction("Clear DRC Markers", self._clear_drc)
        if self._lib:
            cells_menu = menu.addMenu("Navigate to Cell")
            for name in sorted(self._lib.structures.keys()):
                cells_menu.addAction(name, lambda n=name: self._on_cell_activated(n))
        menu.exec(event.globalPos())
