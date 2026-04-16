"""Real schematic viewer that renders Yosys JSON netlists with logic symbols.

This widget consumes a :class:`openforge.synthesis.netlist_parser.Netlist`
and draws it as a true schematic in the spirit of Vivado's RTL elaboration
view: real gate symbols (AND/OR/NAND/NOR/XOR/XNOR/INV/BUF/MUX/FF), Manhattan
wire routing, IO pads, topological auto-layout, pan + zoom, click-to-select,
hover tooltips, search, filter, hierarchical drill-in, and PNG/SVG export.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from openforge.synthesis.netlist_parser import (
    NetCell,
    Netlist,
    NetlistModule,
    NetPort,
    parse_yosys_json,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------

BG = "#1e1e2e"
MANTLE = "#181825"
SURFACE = "#313244"
SURFACE1 = "#45475a"
TEXT = "#cdd6f4"
SUBTEXT = "#a6adc8"
OVERLAY = "#6c7086"
BLUE = "#89b4fa"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"
MAUVE = "#cba6f7"
PEACH = "#fab387"
TEAL = "#94e2d5"
LAVENDER = "#b4befe"
SAPPHIRE = "#74c7ec"


GATE_COLORS = {
    "ff": MAUVE,
    "and": GREEN,
    "or": TEAL,
    "nand": GREEN,
    "nor": TEAL,
    "xor": PEACH,
    "xnor": PEACH,
    "inv": YELLOW,
    "buf": YELLOW,
    "mux": BLUE,
    "add": RED,
    "sub": RED,
    "gate": SUBTEXT,
}

KIND_LABELS = [
    "all",
    "ff",
    "and",
    "or",
    "nand",
    "nor",
    "xor",
    "xnor",
    "inv",
    "buf",
    "mux",
    "add",
    "sub",
    "gate",
]


# ---------------------------------------------------------------------------
# Symbol drawer
# ---------------------------------------------------------------------------


class SymbolDrawer:
    """Static methods that draw IEEE/ANSI logic gate symbols on a QPainter.

    All symbols are drawn at coordinate ``(x, y)`` with the requested width
    and height. Pen and brush are expected to be configured by the caller.
    """

    @staticmethod
    def draw_and(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        """AND gate: D-shape with flat back and curved front."""
        path = QPainterPath()
        path.moveTo(x, y)
        path.lineTo(x + w / 2, y)
        path.arcTo(x, y, w, h, 90, -180)
        path.lineTo(x, y + h)
        path.closeSubpath()
        painter.drawPath(path)

    @staticmethod
    def draw_or(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        """OR gate: curved back with pointed front."""
        path = QPainterPath()
        path.moveTo(x, y)
        path.quadTo(x + w * 0.4, y + h / 2, x, y + h)
        path.quadTo(x + w * 0.7, y + h, x + w, y + h / 2)
        path.quadTo(x + w * 0.7, y, x, y)
        path.closeSubpath()
        painter.drawPath(path)

    @staticmethod
    def draw_nand(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        SymbolDrawer.draw_and(painter, x, y, w - 8, h)
        painter.drawEllipse(QRectF(x + w - 10, y + h / 2 - 4, 8, 8))

    @staticmethod
    def draw_nor(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        SymbolDrawer.draw_or(painter, x, y, w - 8, h)
        painter.drawEllipse(QRectF(x + w - 10, y + h / 2 - 4, 8, 8))

    @staticmethod
    def draw_xor(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        SymbolDrawer.draw_or(painter, x + 5, y, w - 5, h)
        path = QPainterPath()
        path.moveTo(x, y)
        path.quadTo(x + 5, y + h / 2, x, y + h)
        painter.drawPath(path)

    @staticmethod
    def draw_xnor(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        SymbolDrawer.draw_xor(painter, x, y, w - 8, h)
        painter.drawEllipse(QRectF(x + w - 10, y + h / 2 - 4, 8, 8))

    @staticmethod
    def draw_inv(painter: QPainter, x: float, y: float, w: float = 50, h: float = 40) -> None:
        triangle = QPolygonF(
            [
                QPointF(x, y),
                QPointF(x, y + h),
                QPointF(x + w - 8, y + h / 2),
            ]
        )
        painter.drawPolygon(triangle)
        painter.drawEllipse(QRectF(x + w - 8, y + h / 2 - 4, 8, 8))

    @staticmethod
    def draw_buf(painter: QPainter, x: float, y: float, w: float = 50, h: float = 40) -> None:
        triangle = QPolygonF(
            [
                QPointF(x, y),
                QPointF(x, y + h),
                QPointF(x + w, y + h / 2),
            ]
        )
        painter.drawPolygon(triangle)

    @staticmethod
    def draw_ff(painter: QPainter, x: float, y: float, w: float = 70, h: float = 60) -> None:
        """D flip-flop: rectangle with clock triangle marker."""
        painter.drawRect(QRectF(x, y, w, h))
        path = QPainterPath()
        path.moveTo(x, y + h - 14)
        path.lineTo(x + 9, y + h - 7)
        path.lineTo(x, y + h)
        painter.drawPath(path)
        # Pin labels
        painter.save()
        small = QFont("JetBrains Mono", 6)
        painter.setFont(small)
        painter.drawText(QRectF(x + 2, y + 2, 14, 12), Qt.AlignmentFlag.AlignLeft, "D")
        painter.drawText(QRectF(x + w - 14, y + 2, 12, 12), Qt.AlignmentFlag.AlignRight, "Q")
        painter.restore()

    @staticmethod
    def draw_mux(painter: QPainter, x: float, y: float, w: float = 50, h: float = 70) -> None:
        polygon = QPolygonF(
            [
                QPointF(x, y),
                QPointF(x + w, y + 12),
                QPointF(x + w, y + h - 12),
                QPointF(x, y + h),
            ]
        )
        painter.drawPolygon(polygon)
        painter.save()
        small = QFont("JetBrains Mono", 6)
        painter.setFont(small)
        painter.drawText(QRectF(x + 2, y + h / 2 - 6, 14, 12), Qt.AlignmentFlag.AlignLeft, "M")
        painter.restore()

    @staticmethod
    def draw_add(painter: QPainter, x: float, y: float, w: float = 60, h: float = 50) -> None:
        painter.drawRect(QRectF(x, y, w, h))
        painter.save()
        f = QFont("JetBrains Mono", 14, QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, "+")
        painter.restore()

    @staticmethod
    def draw_sub(painter: QPainter, x: float, y: float, w: float = 60, h: float = 50) -> None:
        painter.drawRect(QRectF(x, y, w, h))
        painter.save()
        f = QFont("JetBrains Mono", 14, QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, "−")
        painter.restore()

    @staticmethod
    def draw_generic(painter: QPainter, x: float, y: float, w: float = 60, h: float = 40) -> None:
        painter.drawRoundedRect(QRectF(x, y, w, h), 4, 4)


# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------


class CellGraphicsItem(QGraphicsItem):
    """A schematic cell rendered as a logic gate symbol."""

    def __init__(self, cell: NetCell, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.cell = cell
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setAcceptHoverEvents(True)
        self._w, self._h = self._size_for_kind()
        self._is_submodule = not cell.cell_type.startswith("$") and not any(
            cell.cell_type.lower().startswith(p) for p in ("sky130_", "gf180", "asap7", "nangate")
        )

    def _size_for_kind(self) -> tuple[float, float]:
        kind = self.cell.kind
        if kind == "ff":
            return (74, 60)
        if kind == "mux":
            return (50, 70)
        if kind in ("add", "sub"):
            return (60, 50)
        return (60, 40)

    @property
    def width(self) -> float:
        return self._w

    @property
    def height(self) -> float:
        return self._h

    def input_anchor(self) -> QPointF:
        return self.mapToScene(QPointF(0, self._h / 2))

    def output_anchor(self) -> QPointF:
        return self.mapToScene(QPointF(self._w, self._h / 2))

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -14, self._w + 12, self._h + 28)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(GATE_COLORS.get(self.cell.kind, SUBTEXT))
        pen = QPen(QColor(LAVENDER), 2.5) if self.isSelected() else QPen(color, 1.6)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(MANTLE)))

        kind = self.cell.kind
        draw_map = {
            "and": SymbolDrawer.draw_and,
            "or": SymbolDrawer.draw_or,
            "nand": SymbolDrawer.draw_nand,
            "nor": SymbolDrawer.draw_nor,
            "xor": SymbolDrawer.draw_xor,
            "xnor": SymbolDrawer.draw_xnor,
            "inv": SymbolDrawer.draw_inv,
            "buf": SymbolDrawer.draw_buf,
            "ff": SymbolDrawer.draw_ff,
            "mux": SymbolDrawer.draw_mux,
            "add": SymbolDrawer.draw_add,
            "sub": SymbolDrawer.draw_sub,
        }
        drawer = draw_map.get(kind, SymbolDrawer.draw_generic)
        drawer(painter, 0, 0, self._w, self._h)

        # Pin stubs
        stub_pen = QPen(QColor(OVERLAY), 1.0)
        stub_pen.setCosmetic(True)
        painter.setPen(stub_pen)
        painter.drawLine(QPointF(-6, self._h / 2), QPointF(0, self._h / 2))
        painter.drawLine(QPointF(self._w, self._h / 2), QPointF(self._w + 6, self._h / 2))

        # Cell name label
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("JetBrains Mono", 7))
        label = self.cell.name
        if len(label) > 16:
            label = label[:14] + ".."
        painter.drawText(
            QRectF(-10, self._h + 2, self._w + 20, 12),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )

        # Submodule indicator
        if self._is_submodule:
            painter.setPen(QColor(LAVENDER))
            painter.setFont(QFont("JetBrains Mono", 6, QFont.Weight.Bold))
            painter.drawText(
                QRectF(-10, -12, self._w + 20, 10),
                Qt.AlignmentFlag.AlignCenter,
                f"⌂ {self.cell.cell_type}",
            )

    def hoverEnterEvent(self, event) -> None:
        kind_label = self.cell.kind.upper()
        params_str = ", ".join(f"{k}={v}" for k, v in list(self.cell.parameters.items())[:4])
        tooltip_lines = [
            f"<b>{self.cell.name}</b>",
            f"Type: <code>{self.cell.cell_type}</code>",
            f"Kind: {kind_label}",
        ]
        if self.cell.input_pins:
            tooltip_lines.append(f"Inputs: {', '.join(self.cell.input_pins)}")
        if self.cell.output_pins:
            tooltip_lines.append(f"Outputs: {', '.join(self.cell.output_pins)}")
        if params_str:
            tooltip_lines.append(f"Params: {params_str}")
        if self._is_submodule:
            tooltip_lines.append("<i>Double-click to drill in</i>")
        self.setToolTip("<br>".join(tooltip_lines))
        super().hoverEnterEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._is_submodule:
            scene = self.scene()
            if scene is not None:
                view = scene.views()[0] if scene.views() else None
                if view is not None:
                    parent = view.parent()
                    if isinstance(parent, SchematicView):
                        parent.drill_into(self.cell.cell_type)
                        return
        super().mouseDoubleClickEvent(event)


class PortGraphicsItem(QGraphicsItem):
    """An IO port rendered as a colored arrow / pad."""

    def __init__(self, port: NetPort, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.port = port
        self.setAcceptHoverEvents(True)
        self._w = 56
        self._h = 22

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -14, self._w + 12, self._h + 28)

    def anchor(self) -> QPointF:
        if self.port.is_input:
            return self.mapToScene(QPointF(self._w, self._h / 2))
        return self.mapToScene(QPointF(0, self._h / 2))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_input = self.port.is_input
        color = QColor(BLUE if is_input else GREEN)
        pen = QPen(color, 1.6)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(MANTLE)))

        if is_input:
            polygon = QPolygonF(
                [
                    QPointF(0, 0),
                    QPointF(self._w - 10, 0),
                    QPointF(self._w, self._h / 2),
                    QPointF(self._w - 10, self._h),
                    QPointF(0, self._h),
                ]
            )
        else:
            polygon = QPolygonF(
                [
                    QPointF(0, self._h / 2),
                    QPointF(10, 0),
                    QPointF(self._w, 0),
                    QPointF(self._w, self._h),
                    QPointF(10, self._h),
                ]
            )
        painter.drawPolygon(polygon)

        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("JetBrains Mono", 7))
        painter.drawText(
            QRectF(0, 0, self._w, self._h),
            Qt.AlignmentFlag.AlignCenter,
            self.port.label(),
        )

    def hoverEnterEvent(self, event) -> None:
        self.setToolTip(
            f"<b>{self.port.name}</b><br>"
            f"Direction: {self.port.direction}<br>"
            f"Width: {self.port.width}"
        )
        super().hoverEnterEvent(event)


# ---------------------------------------------------------------------------
# Custom QGraphicsView with wheel zoom
# ---------------------------------------------------------------------------


class _ZoomGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.18 if event.angleDelta().y() > 0 else 1.0 / 1.18
        self.scale(factor, factor)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------


class SchematicView(QWidget):
    """Reusable schematic viewer widget for Yosys netlists.

    Signals
    -------
    cell_selected(str):
        Emitted with the cell instance name whenever the user selects a cell.
    module_changed(str):
        Emitted when the displayed module changes (e.g. via drill-in).
    """

    cell_selected = Signal(str)
    module_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._netlist: Netlist | None = None
        self._current_module: NetlistModule | None = None
        self._cell_items: dict[str, CellGraphicsItem] = {}
        self._port_items: dict[tuple[str, str], PortGraphicsItem] = {}
        self._wire_items: list[Any] = []
        self._history: list[str] = []
        self._build_ui()

    # ----- UI scaffolding -------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setStyleSheet(f"background: {SURFACE}; border-bottom: 1px solid {SURFACE1};")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(6)

        self.back_btn = QPushButton("◀")
        self.back_btn.setMaximumWidth(28)
        self.back_btn.setToolTip("Back to parent module")
        self.back_btn.clicked.connect(self._on_back)
        self.back_btn.setEnabled(False)
        toolbar_layout.addWidget(self.back_btn)

        toolbar_layout.addWidget(QLabel("Module:"))
        self.module_combo = QComboBox()
        self.module_combo.setMinimumWidth(160)
        self.module_combo.currentTextChanged.connect(self._on_module_changed)
        toolbar_layout.addWidget(self.module_combo)

        toolbar_layout.addSpacing(12)

        toolbar_layout.addWidget(QLabel("Filter:"))
        self.kind_combo = QComboBox()
        for k in KIND_LABELS:
            self.kind_combo.addItem(k.upper())
        self.kind_combo.currentTextChanged.connect(self._on_filter_changed)
        toolbar_layout.addWidget(self.kind_combo)

        toolbar_layout.addSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search cells...")
        self.search.setMaximumWidth(200)
        self.search.textChanged.connect(self._on_search)
        toolbar_layout.addWidget(self.search)

        toolbar_layout.addSpacing(8)

        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setMaximumWidth(40)
        self.fit_btn.clicked.connect(self._fit_view)
        toolbar_layout.addWidget(self.fit_btn)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setMaximumWidth(28)
        self.zoom_in_btn.clicked.connect(lambda: self._zoom(1.25))
        toolbar_layout.addWidget(self.zoom_in_btn)

        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setMaximumWidth(28)
        self.zoom_out_btn.clicked.connect(lambda: self._zoom(0.8))
        toolbar_layout.addWidget(self.zoom_out_btn)

        self.png_btn = QPushButton("PNG")
        self.png_btn.setMaximumWidth(46)
        self.png_btn.clicked.connect(self._export_png)
        toolbar_layout.addWidget(self.png_btn)

        self.svg_btn = QPushButton("SVG")
        self.svg_btn.setMaximumWidth(46)
        self.svg_btn.clicked.connect(self._export_svg)
        toolbar_layout.addWidget(self.svg_btn)

        toolbar_layout.addStretch()

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        toolbar_layout.addWidget(self.stats_label)

        layout.addWidget(toolbar)

        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor(BG)))
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.view = _ZoomGraphicsView(self.scene, self)
        layout.addWidget(self.view, stretch=1)

        self._show_empty_state()

    # ----- Public API -----------------------------------------------------

    def load_netlist(self, json_path: Path | str) -> None:
        """Load a Yosys JSON netlist file and render its top module."""
        try:
            self._netlist = parse_yosys_json(json_path)
        except Exception as exc:
            self._show_error(str(exc))
            return

        self.module_combo.blockSignals(True)
        self.module_combo.clear()
        for name in self._netlist.modules:
            self.module_combo.addItem(name)
        self.module_combo.blockSignals(False)

        target = self._netlist.top_module or (
            next(iter(self._netlist.modules)) if self._netlist.modules else ""
        )
        if target:
            self._history.clear()
            self.module_combo.setCurrentText(target)

    def set_netlist(self, netlist: Netlist) -> None:
        """Use an already-parsed Netlist object."""
        self._netlist = netlist
        self.module_combo.blockSignals(True)
        self.module_combo.clear()
        for name in netlist.modules:
            self.module_combo.addItem(name)
        self.module_combo.blockSignals(False)
        target = netlist.top_module or (next(iter(netlist.modules)) if netlist.modules else "")
        if target:
            self._history.clear()
            self.module_combo.setCurrentText(target)

    def drill_into(self, module_name: str) -> None:
        """Navigate into a sub-module."""
        if not self._netlist or module_name not in self._netlist.modules:
            return
        if self._current_module is not None:
            self._history.append(self._current_module.name)
        self.module_combo.setCurrentText(module_name)
        self.back_btn.setEnabled(bool(self._history))

    def current_module_name(self) -> str:
        return self._current_module.name if self._current_module else ""

    # ----- Empty / error states -------------------------------------------

    def _show_empty_state(self) -> None:
        self.scene.clear()
        self._cell_items.clear()
        self._port_items.clear()
        self._wire_items.clear()
        text = self.scene.addText(
            "No netlist loaded\n\nRun synthesis and the schematic\nwill appear here.",
            QFont("Inter", 12),
        )
        text.setDefaultTextColor(QColor(SUBTEXT))
        text.setPos(20, 20)
        self.stats_label.setText("")

    def _show_error(self, msg: str) -> None:
        self.scene.clear()
        err = self.scene.addText(f"Error loading netlist:\n{msg}", QFont("Inter", 11))
        err.setDefaultTextColor(QColor(RED))
        err.setPos(20, 20)
        self.stats_label.setText("")

    # ----- Module switching / rendering -----------------------------------

    def _on_back(self) -> None:
        if not self._history:
            return
        prev = self._history.pop()
        self.module_combo.setCurrentText(prev)
        self.back_btn.setEnabled(bool(self._history))

    def _on_module_changed(self, name: str) -> None:
        if not self._netlist or not name:
            return
        module = self._netlist.modules.get(name)
        if module is None:
            return
        self._current_module = module
        self._render_module(module)
        self.module_changed.emit(name)

    def _render_module(self, module: NetlistModule) -> None:
        self.scene.clear()
        self._cell_items.clear()
        self._port_items.clear()
        self._wire_items.clear()

        ports_in = module.input_ports
        ports_out = module.output_ports

        levels = self._topological_levels(module)
        max_level = max(levels.values(), default=0)

        x_spacing = 130
        y_spacing = 90
        margin_y = 30

        # Place input ports on the left at level 0
        for i, port in enumerate(ports_in):
            item = PortGraphicsItem(port)
            item.setPos(0, margin_y + i * 50)
            self.scene.addItem(item)
            self._port_items[("in", port.name)] = item

        # Group cells by level
        cells_by_level: dict[int, list[NetCell]] = {}
        for cell_name, level in levels.items():
            cells_by_level.setdefault(level, []).append(module.cells[cell_name])

        # Sort each level deterministically
        for level in cells_by_level:
            cells_by_level[level].sort(key=lambda c: c.name)

        for level in range(1, max_level + 1):
            level_cells = cells_by_level.get(level, [])
            for i, cell in enumerate(level_cells):
                item = CellGraphicsItem(cell)
                x = 100 + level * x_spacing
                y = margin_y + i * y_spacing
                item.setPos(x, y)
                self.scene.addItem(item)
                self._cell_items[cell.name] = item

        # Output ports on the right
        right_x = 100 + (max_level + 1) * x_spacing + 40
        for i, port in enumerate(ports_out):
            item = PortGraphicsItem(port)
            item.setPos(right_x, margin_y + i * 50)
            self.scene.addItem(item)
            self._port_items[("out", port.name)] = item

        self._draw_wires(module)
        self._update_stats(module)
        self._fit_view()

    def _draw_wires(self, module: NetlistModule) -> None:
        """Route Manhattan wires between cell pins and IO ports."""
        wire_pen = QPen(QColor(OVERLAY), 1.2)
        wire_pen.setCosmetic(True)

        # Bit -> source point
        sources: dict[Any, QPointF] = {}

        # Input ports drive their bits
        for port in module.input_ports:
            item = self._port_items.get(("in", port.name))
            if item is None:
                continue
            anchor = item.anchor()
            for bit in port.bits:
                sources.setdefault(bit, anchor)

        # Cells drive their output bits
        for cell_name, cell in module.cells.items():
            item = self._cell_items.get(cell_name)
            if item is None:
                continue
            out_anchor = item.output_anchor()
            for bit in cell.driven_bits():
                sources.setdefault(bit, out_anchor)

        # Now draw wires from each consumer back to the bit's driver
        for cell_name, cell in module.cells.items():
            item = self._cell_items.get(cell_name)
            if item is None:
                continue
            in_anchor = item.input_anchor()
            consumed = cell.consumed_bits()
            if not consumed:
                continue
            # Use the first non-constant bit for routing
            for bit in consumed:
                src = sources.get(bit)
                if src is None:
                    continue
                self._draw_manhattan(src, in_anchor, wire_pen)
                break

        # Output ports
        for port in module.output_ports:
            item = self._port_items.get(("out", port.name))
            if item is None or not port.bits:
                continue
            dest = item.anchor()
            for bit in port.bits:
                src = sources.get(bit)
                if src is None:
                    continue
                self._draw_manhattan(src, dest, wire_pen)
                break

    def _draw_manhattan(self, src: QPointF, dst: QPointF, pen: QPen) -> None:
        """Draw a 3-segment Manhattan path from src to dst."""
        mid_x = (src.x() + dst.x()) / 2
        path = QPainterPath(src)
        path.lineTo(QPointF(mid_x, src.y()))
        path.lineTo(QPointF(mid_x, dst.y()))
        path.lineTo(dst)
        item = self.scene.addPath(path, pen)
        self._wire_items.append(item)

    def _update_stats(self, module: NetlistModule) -> None:
        stats = module.stats()
        non_zero = {k: v for k, v in stats.items() if v > 0}
        stats_str = " | ".join(f"{k.upper()}: {v}" for k, v in sorted(non_zero.items()))
        self.stats_label.setText(
            f"{module.name} — {len(module.cells)} cells, "
            f"{len(module.input_ports)}I {len(module.output_ports)}O   {stats_str}"
        )

    # ----- Topological levelization ---------------------------------------

    def _topological_levels(self, module: NetlistModule) -> dict[str, int]:
        bit_to_driver: dict[Any, str] = {}
        for cell_name, cell in module.cells.items():
            for bit in cell.driven_bits():
                bit_to_driver[bit] = cell_name

        levels: dict[str, int] = {}
        for cell_name in module.cells:
            self._compute_level(cell_name, module, bit_to_driver, levels, set())
        return levels

    def _compute_level(
        self,
        cell_name: str,
        module: NetlistModule,
        bit_to_driver: dict[Any, str],
        levels: dict[str, int],
        visiting: set[str],
    ) -> int:
        if cell_name in levels:
            return levels[cell_name]
        if cell_name in visiting:
            return 1
        visiting.add(cell_name)

        cell = module.cells[cell_name]
        max_input_level = 0
        # Sequential cells break combinational chains for layout depth
        if cell.kind == "ff":
            max_input_level = 0
        else:
            for bit in cell.consumed_bits():
                driver = bit_to_driver.get(bit)
                if driver and driver != cell_name:
                    lvl = self._compute_level(driver, module, bit_to_driver, levels, visiting)
                    if lvl > max_input_level:
                        max_input_level = lvl

        levels[cell_name] = max_input_level + 1
        visiting.discard(cell_name)
        return levels[cell_name]

    # ----- Search / filter / selection ------------------------------------

    def _on_search(self, text: str) -> None:
        text = text.lower()
        for name, item in self._cell_items.items():
            visible = (
                not text
                or text in name.lower()
                or text in item.cell.cell_type.lower()
                or text in item.cell.kind
            )
            item.setOpacity(1.0 if visible else 0.2)

    def _on_filter_changed(self, kind: str) -> None:
        kind = kind.lower()
        for item in self._cell_items.values():
            if kind == "all":
                item.setOpacity(1.0)
            else:
                item.setOpacity(1.0 if item.cell.kind == kind else 0.18)

    def _on_selection_changed(self) -> None:
        for item in self.scene.selectedItems():
            if isinstance(item, CellGraphicsItem):
                self.cell_selected.emit(item.cell.name)
                return

    # ----- Zoom / fit / export --------------------------------------------

    def _zoom(self, factor: float) -> None:
        self.view.scale(factor, factor)

    def _fit_view(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isNull():
            return
        self.view.fitInView(
            rect.adjusted(-30, -30, 30, 30),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def _export_png(self) -> None:
        from PySide6.QtGui import QPixmap

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Schematic as PNG", "schematic.png", "PNG Files (*.png)"
        )
        if not path:
            return
        rect = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        pixmap = QPixmap(int(rect.width()) + 40, int(rect.height()) + 40)
        pixmap.fill(QColor(BG))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.scene.render(painter, QRectF(pixmap.rect()), rect)
        painter.end()
        pixmap.save(path, "PNG")

    def _export_svg(self) -> None:
        try:
            from PySide6.QtSvg import QSvgGenerator
        except ImportError:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Schematic as SVG", "schematic.svg", "SVG Files (*.svg)"
        )
        if not path:
            return
        rect = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(rect.size().toSize())
        gen.setViewBox(rect)
        gen.setTitle("OpenForge Schematic")
        painter = QPainter(gen)
        self.scene.render(painter, QRectF(rect), rect)
        painter.end()


__all__ = [
    "SchematicView",
    "CellGraphicsItem",
    "PortGraphicsItem",
    "SymbolDrawer",
]
