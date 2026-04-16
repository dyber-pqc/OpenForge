"""Vivado IP Integrator-style block design editor with visual IP connection.

Provides a QGraphicsView canvas where users drag IP blocks from a palette,
connect ports with Manhattan-routed wires, edit parameters, validate
connections, and generate Verilog wrapper modules.  Supports undo/redo,
save/load as JSON, and cross-probing signals.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QUndoCommand,
    QUndoStack,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ._theme import panel_tab_qss

try:
    from openforge.block_design.generator import (
        IP_LIBRARY as _BD_IP_LIBRARY,
    )
    from openforge.block_design.generator import (
        BlockConnection as _BDConnection,
    )
    from openforge.block_design.generator import (
        BlockDesign as _BDDesign,
    )
    from openforge.block_design.generator import (
        BlockInstance as _BDInstance,
    )
    from openforge.block_design.generator import (
        BlockPort as _BDPort,
    )
    from openforge.block_design.generator import (
        generate_testbench as _bd_generate_testbench,
    )
    from openforge.block_design.generator import (
        generate_verilog as _bd_generate_verilog,
    )
    from openforge.block_design.generator import (
        validate as _bd_validate,
    )
    _BD_GENERATOR_AVAILABLE = True
except Exception:  # pragma: no cover - keep panel importable without core
    _BD_GENERATOR_AVAILABLE = False
    _BD_IP_LIBRARY = {}  # type: ignore[assignment]

try:
    from openforge.block_design.auto_connect import AutoConnector as _BDAutoConnector
    _BD_AUTO_OK = True
except Exception:  # pragma: no cover
    _BD_AUTO_OK = False

try:
    from openforge.block_design.address_map import (
        AddressMap as _BDAddressMap,
    )
    from openforge.block_design.address_map import (
        AddressRange as _BDAddressRange,
    )
    _BD_ADDRMAP_OK = True
except Exception:  # pragma: no cover
    _BD_ADDRMAP_OK = False

try:
    from openforge.verification.axi_monitors import (
        generate_axi4_full_monitor as _bd_gen_axi_full_mon,
    )
    from openforge.verification.axi_monitors import (
        generate_axi4_lite_monitor as _bd_gen_axi_lite_mon,
    )
    from openforge.verification.axi_monitors import (
        generate_axis_monitor as _bd_gen_axis_mon,
    )
    _BD_AXI_MON_OK = True
except Exception:  # pragma: no cover
    _BD_AXI_MON_OK = False

try:
    from openforge.ip.generators import IP_CATALOG as _BD_IP_CATALOG
    _BD_IP_CATALOG_OK = True
except Exception:  # pragma: no cover
    _BD_IP_CATALOG = {}  # type: ignore[assignment]
    _BD_IP_CATALOG_OK = False

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

_ALT_ROW: Final[str] = "#1a1a2e"
_ZOOM_FACTOR: Final[float] = 1.15
_GRID_SIZE: Final[float] = 20.0
_BLOCK_MIN_W: Final[float] = 200.0
_BLOCK_HEADER_H: Final[float] = 38.0
_PORT_RADIUS: Final[float] = 6.0
_PORT_SPACING: Final[float] = 28.0
_BLOCK_RADIUS: Final[float] = 8.0
_GRID_SNAP: Final[float] = 10.0
_MANDATORY_PORTS: Final[tuple[str, ...]] = ("clk", "clock", "rst", "rst_n", "reset", "reset_n")

# ── Category colours ────────────────────────────────────────────────────────

_CAT_COLORS: Final[dict[str, str]] = {
    "crypto": _BLUE,
    "Crypto": _BLUE,
    "comm": _GREEN,
    "Communication": _GREEN,
    "infrastructure": _YELLOW,
    "Infrastructure": _YELLOW,
    "primitive": _MAUVE,
    "Primitive": _MAUVE,
    "default": _SURFACE2,
}

# ── Wire colors by signal type ──────────────────────────────────────────────

_WIRE_COLORS: Final[dict[str, str]] = {
    "clock": _BLUE,
    "clk": _BLUE,
    "data": _GREEN,
    "control": _YELLOW,
    "reset": _RED,
    "rst": _RED,
    "default": _SUBTEXT,
}

# ── Port / block data model ─────────────────────────────────────────────────

_PORT_RE = re.compile(
    r"(input|output|inout)\s+(?:wire|reg|logic)?\s*(\[.*?\])?\s*(\w+)",
)

_WIDTH_RE = re.compile(r"\[(\d+):(\d+)\]")


@dataclass
class PortDef:
    name: str
    direction: str  # "input" | "output" | "inout"
    width: str = ""  # e.g. "[31:0]"

    @property
    def bit_width(self) -> int:
        m = _WIDTH_RE.match(self.width)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
        return 1

    @property
    def signal_type(self) -> str:
        n = self.name.lower()
        if "clk" in n or "clock" in n:
            return "clock"
        if "rst" in n or "reset" in n:
            return "reset"
        if any(x in n for x in ("valid", "ready", "enable", "start", "done", "busy")):
            return "control"
        return "data"


@dataclass
class ParamDef:
    name: str
    default: str
    value: str = ""  # user override


@dataclass
class IPBlockDef:
    """Definition of an IP block (template)."""
    name: str
    category: str = "default"
    description: str = ""
    ports: list[PortDef] = field(default_factory=list)
    parameters: list[ParamDef] = field(default_factory=list)
    top_module: str = ""

    @property
    def input_ports(self) -> list[PortDef]:
        return [p for p in self.ports if p.direction == "input"]

    @property
    def output_ports(self) -> list[PortDef]:
        return [p for p in self.ports if p.direction in ("output", "inout")]


@dataclass
class BlockInstance:
    """An instance of an IP block placed on the canvas."""
    instance_id: str
    block_def: IPBlockDef
    x: float = 0.0
    y: float = 0.0
    param_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class WireConnection:
    """A connection between two ports."""
    wire_id: str
    src_block: str  # instance_id
    src_port: str
    dst_block: str
    dst_port: str


# ── Built-in primitive definitions ──────────────────────────────────────────

_PRIMITIVES: list[IPBlockDef] = [
    IPBlockDef(
        name="Register",
        category="Primitive",
        description="D flip-flop register with enable",
        ports=[
            PortDef("clk", "input"),
            PortDef("rst_n", "input"),
            PortDef("en", "input"),
            PortDef("d", "input", "[31:0]"),
            PortDef("q", "output", "[31:0]"),
        ],
        parameters=[ParamDef("WIDTH", "32")],
    ),
    IPBlockDef(
        name="MUX2",
        category="Primitive",
        description="2-to-1 multiplexer",
        ports=[
            PortDef("sel", "input"),
            PortDef("a", "input", "[31:0]"),
            PortDef("b", "input", "[31:0]"),
            PortDef("y", "output", "[31:0]"),
        ],
        parameters=[ParamDef("WIDTH", "32")],
    ),
    IPBlockDef(
        name="AND_Gate",
        category="Primitive",
        description="Bitwise AND gate",
        ports=[
            PortDef("a", "input", "[31:0]"),
            PortDef("b", "input", "[31:0]"),
            PortDef("y", "output", "[31:0]"),
        ],
        parameters=[ParamDef("WIDTH", "32")],
    ),
    IPBlockDef(
        name="OR_Gate",
        category="Primitive",
        description="Bitwise OR gate",
        ports=[
            PortDef("a", "input", "[31:0]"),
            PortDef("b", "input", "[31:0]"),
            PortDef("y", "output", "[31:0]"),
        ],
        parameters=[ParamDef("WIDTH", "32")],
    ),
    IPBlockDef(
        name="XOR_Gate",
        category="Primitive",
        description="Bitwise XOR gate",
        ports=[
            PortDef("a", "input", "[31:0]"),
            PortDef("b", "input", "[31:0]"),
            PortDef("y", "output", "[31:0]"),
        ],
        parameters=[ParamDef("WIDTH", "32")],
    ),
    IPBlockDef(
        name="Constant",
        category="Primitive",
        description="Constant value source",
        ports=[
            PortDef("val", "output", "[31:0]"),
        ],
        parameters=[ParamDef("VALUE", "0"), ParamDef("WIDTH", "32")],
    ),
]


def _parse_verilog_ip(filepath: Path) -> IPBlockDef | None:
    """Parse a Verilog file to extract an IPBlockDef."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    mod_re = re.compile(
        r"module\s+(\w+)\s*(?:#\s*\((.*?)\))?\s*\((.*?)\)\s*;",
        re.DOTALL,
    )
    m = mod_re.search(text)
    if not m:
        return None
    name = m.group(1)
    params: list[ParamDef] = []
    if m.group(2):
        for pm in re.finditer(r"parameter\s+(?:\[.*?\]\s*)?(\w+)\s*=\s*([^,\)]+)", m.group(2)):
            params.append(ParamDef(pm.group(1), pm.group(2).strip()))
    ports: list[PortDef] = []
    for pm in _PORT_RE.finditer(text):
        width = pm.group(2) or ""
        ports.append(PortDef(pm.group(3), pm.group(1), width.strip()))
    return IPBlockDef(name=name, ports=ports, parameters=params, top_module=name)


def _load_ip_catalog(share_ip_dir: Path) -> list[IPBlockDef]:
    """Load IP catalog from share/ip/ directory."""
    blocks: list[IPBlockDef] = []
    # Try to load catalog.yaml
    catalog_path = share_ip_dir / "catalog.yaml"
    catalog_data: list[dict[str, Any]] = []
    if catalog_path.exists():
        try:
            import yaml
            with open(catalog_path) as f:
                raw = yaml.safe_load(f)
            catalog_data = raw.get("catalog", [])
        except Exception:
            pass

    cat_map: dict[str, str] = {}
    for entry in catalog_data:
        cat_map[entry.get("name", "")] = entry.get("category", "default")

    # Parse Verilog sources
    for ip_dir in sorted(share_ip_dir.iterdir()):
        if not ip_dir.is_dir():
            continue
        src_dir = ip_dir / "src"
        if not src_dir.exists():
            continue
        for vfile in sorted(src_dir.glob("*.v")):
            block = _parse_verilog_ip(vfile)
            if block:
                block.category = cat_map.get(block.name, cat_map.get(ip_dir.name, "default"))
                # Also find description from catalog
                for entry in catalog_data:
                    if entry.get("top_module") == block.name or entry.get("name") == ip_dir.name:
                        block.description = entry.get("description", "")
                        break
                blocks.append(block)
    return blocks


# ── Undo commands ────────────────────────────────────────────────────────────

class _AddBlockCommand(QUndoCommand):
    def __init__(self, editor: _BlockDesignCanvas, instance: BlockInstance) -> None:
        super().__init__(f"Add {instance.block_def.name}")
        self._editor = editor
        self._instance = instance

    def redo(self) -> None:
        self._editor._do_add_block(self._instance)

    def undo(self) -> None:
        self._editor._do_remove_block(self._instance.instance_id)


class _RemoveBlockCommand(QUndoCommand):
    def __init__(self, editor: _BlockDesignCanvas, instance_id: str) -> None:
        super().__init__(f"Remove {instance_id}")
        self._editor = editor
        self._instance_id = instance_id
        self._instance: BlockInstance | None = None
        self._removed_wires: list[WireConnection] = []

    def redo(self) -> None:
        self._instance = self._editor._blocks.get(self._instance_id)
        self._removed_wires = [
            w for w in self._editor._wires
            if w.src_block == self._instance_id or w.dst_block == self._instance_id
        ]
        for w in self._removed_wires:
            self._editor._do_remove_wire(w.wire_id)
        self._editor._do_remove_block(self._instance_id)

    def undo(self) -> None:
        if self._instance:
            self._editor._do_add_block(self._instance)
        for w in self._removed_wires:
            self._editor._do_add_wire(w)


class _AddWireCommand(QUndoCommand):
    def __init__(self, editor: _BlockDesignCanvas, wire: WireConnection) -> None:
        super().__init__(f"Connect {wire.src_block}.{wire.src_port} -> {wire.dst_block}.{wire.dst_port}")
        self._editor = editor
        self._wire = wire

    def redo(self) -> None:
        self._editor._do_add_wire(self._wire)

    def undo(self) -> None:
        self._editor._do_remove_wire(self._wire.wire_id)


class _RemoveWireCommand(QUndoCommand):
    def __init__(self, editor: _BlockDesignCanvas, wire_id: str) -> None:
        super().__init__(f"Disconnect {wire_id}")
        self._editor = editor
        self._wire_id = wire_id
        self._wire: WireConnection | None = None

    def redo(self) -> None:
        self._wire = next((w for w in self._editor._wires if w.wire_id == self._wire_id), None)
        self._editor._do_remove_wire(self._wire_id)

    def undo(self) -> None:
        if self._wire:
            self._editor._do_add_wire(self._wire)


class _MoveBlockCommand(QUndoCommand):
    def __init__(self, editor: _BlockDesignCanvas, instance_id: str,
                 old_pos: tuple[float, float], new_pos: tuple[float, float]) -> None:
        super().__init__(f"Move {instance_id}")
        self._editor = editor
        self._id = instance_id
        self._old = old_pos
        self._new = new_pos

    def redo(self) -> None:
        self._editor._do_move_block(self._id, self._new[0], self._new[1])

    def undo(self) -> None:
        self._editor._do_move_block(self._id, self._old[0], self._old[1])


# ── Block graphics item ─────────────────────────────────────────────────────

class _PortItem(QGraphicsEllipseItem):
    """Larger, brighter circle with hover glow representing a port on a block."""

    def __init__(
        self,
        port_def: PortDef,
        block_id: str,
        is_output: bool,
        parent: QGraphicsItem | None = None,
    ) -> None:
        r = _PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self.port_def = port_def
        self.block_id = block_id
        self.is_output = is_output
        self._connected = False
        self._base_color = QColor(_WIRE_COLORS.get(port_def.signal_type, _WIRE_COLORS["default"]))
        self.setAcceptHoverEvents(True)
        self.setBrush(QBrush(self._base_color))
        pen = QPen(QColor(_CRUST), 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setToolTip(
            f"{port_def.name} ({port_def.direction}) {port_def.width}\n"
            f"Type: {port_def.signal_type}"
        )
        self.setZValue(10)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def get_scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    def hoverEnterEvent(self, event):  # type: ignore[override]
        pen = QPen(QColor(_LAVENDER), 2.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):  # type: ignore[override]
        pen = QPen(QColor(_CRUST), 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        super().hoverLeaveEvent(event)


class _BlockItem(QGraphicsRectItem):
    """Visual representation of an IP block - polished, auto-sized, with shadow."""

    def __init__(self, instance: BlockInstance, parent: QGraphicsItem | None = None) -> None:
        self.instance = instance
        bd = instance.block_def
        n_in = len(bd.input_ports)
        n_out = len(bd.output_ports)
        n_ports = max(n_in, n_out, 1)

        # Compute size: tall for many ports, wider for long names
        port_label_font = QFont("Consolas", 8)
        fm_lbl = QFontMetrics(port_label_font)
        title_fm = QFontMetrics(QFont("Segoe UI", 10, QFont.Weight.Bold))
        inst_fm = QFontMetrics(QFont("Segoe UI", 8))
        max_in_lbl = max(
            (fm_lbl.horizontalAdvance(p.name + (p.width or "")) for p in bd.input_ports),
            default=0,
        )
        max_out_lbl = max(
            (fm_lbl.horizontalAdvance(p.name + (p.width or "")) for p in bd.output_ports),
            default=0,
        )
        title_w = max(
            title_fm.horizontalAdvance(bd.name),
            inst_fm.horizontalAdvance(instance.instance_id),
        )
        w = max(
            _BLOCK_MIN_W,
            max_in_lbl + max_out_lbl + 60,
            title_w + 40,
        )

        ports_h = n_ports * _PORT_SPACING + 12
        params_h = 0.0
        if bd.parameters:
            params_h = len(bd.parameters) * 15 + 16
        total_h = _BLOCK_HEADER_H + ports_h + params_h

        super().__init__(0, 0, w, total_h, parent)
        self.setPos(instance.x, instance.y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(5)
        self.setAcceptHoverEvents(True)

        self._w = w
        self._h = total_h
        self._cat_color = QColor(_CAT_COLORS.get(bd.category, _CAT_COLORS["default"]))
        self._hover = False

        # Make outer rect transparent — we draw rounded body in paint()
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setPen(QPen(Qt.PenStyle.NoPen))

        # Drop shadow
        try:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 160))
            self.setGraphicsEffect(shadow)
        except Exception:
            pass

        # Module type name (smaller, in header)
        type_text = QGraphicsSimpleTextItem(bd.name, self)
        type_text.setFont(QFont("Segoe UI", 8))
        type_text.setBrush(QBrush(QColor(_CRUST)))
        tw = type_text.boundingRect().width()
        type_text.setPos((w - tw) / 2, 4)

        # Instance name (larger, below module type)
        inst_text = QGraphicsSimpleTextItem(instance.instance_id, self)
        inst_text.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        inst_text.setBrush(QBrush(QColor(_CRUST)))
        iw = inst_text.boundingRect().width()
        inst_text.setPos((w - iw) / 2, 18)

        # Ports
        self.port_items: dict[str, _PortItem] = {}
        port_start_y = _BLOCK_HEADER_H + 14

        for i, p in enumerate(bd.input_ports):
            y = port_start_y + i * _PORT_SPACING
            pi = _PortItem(p, instance.instance_id, False, self)
            pi.setPos(0, y)
            self.port_items[p.name] = pi
            # Direction triangle (right-pointing for input)
            tri = QPolygonF([
                QPointF(_PORT_RADIUS + 2, y - 4),
                QPointF(_PORT_RADIUS + 8, y),
                QPointF(_PORT_RADIUS + 2, y + 4),
            ])
            tri_item = QGraphicsPathItem(self)
            path = QPainterPath()
            path.addPolygon(tri)
            tri_item.setPath(path)
            tri_item.setBrush(QBrush(QColor(_WIRE_COLORS.get(p.signal_type, _WIRE_COLORS["default"]))))
            tri_item.setPen(QPen(Qt.PenStyle.NoPen))
            # Label (inside block)
            lbl = QGraphicsSimpleTextItem(p.name, self)
            lbl.setFont(port_label_font)
            lbl.setBrush(QBrush(QColor(_TEXT)))
            lbl.setPos(_PORT_RADIUS + 12, y - 7)
            if p.width:
                wlbl = QGraphicsSimpleTextItem(p.width, self)
                wlbl.setFont(QFont("Consolas", 7))
                wlbl.setBrush(QBrush(QColor(_LAVENDER)))
                wlbl.setPos(_PORT_RADIUS + 12 + fm_lbl.horizontalAdvance(p.name) + 4, y - 6)

        for i, p in enumerate(bd.output_ports):
            y = port_start_y + i * _PORT_SPACING
            pi = _PortItem(p, instance.instance_id, True, self)
            pi.setPos(w, y)
            self.port_items[p.name] = pi
            # Direction triangle (right-pointing exit, drawn pointing right just inside)
            tri = QPolygonF([
                QPointF(w - _PORT_RADIUS - 8, y - 4),
                QPointF(w - _PORT_RADIUS - 2, y),
                QPointF(w - _PORT_RADIUS - 8, y + 4),
            ])
            tri_item = QGraphicsPathItem(self)
            path = QPainterPath()
            path.addPolygon(tri)
            tri_item.setPath(path)
            tri_item.setBrush(QBrush(QColor(_WIRE_COLORS.get(p.signal_type, _WIRE_COLORS["default"]))))
            tri_item.setPen(QPen(Qt.PenStyle.NoPen))
            # Label (right-aligned, inside)
            lbl = QGraphicsSimpleTextItem(p.name, self)
            lbl.setFont(port_label_font)
            lbl.setBrush(QBrush(QColor(_TEXT)))
            lw = lbl.boundingRect().width()
            lbl.setPos(w - _PORT_RADIUS - 12 - lw, y - 7)
            if p.width:
                wlbl = QGraphicsSimpleTextItem(p.width, self)
                wlbl.setFont(QFont("Consolas", 7))
                wlbl.setBrush(QBrush(QColor(_LAVENDER)))
                ww = wlbl.boundingRect().width()
                wlbl.setPos(w - _PORT_RADIUS - 12 - lw - ww - 4, y - 6)

        # Parameters in dedicated section at bottom
        if bd.parameters:
            param_y = _BLOCK_HEADER_H + ports_h + 4
            for j, param in enumerate(bd.parameters):
                val = instance.param_overrides.get(param.name, param.default)
                ptxt = QGraphicsSimpleTextItem(f"{param.name} = {val}", self)
                ptxt.setFont(QFont("Consolas", 7))
                ptxt.setBrush(QBrush(QColor(_PEACH)))
                ptxt.setPos(12, param_y + j * 15)

    # ── Custom paint: rounded body, header, parameter section ────────────
    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        w = self._w
        h = self._h
        r = _BLOCK_RADIUS

        # Body
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        painter.fillPath(body_path, QBrush(QColor(_MANTLE)))

        # Header (rounded top only)
        header_path = QPainterPath()
        header_path.addRoundedRect(QRectF(0, 0, w, _BLOCK_HEADER_H), r, r)
        # Square off bottom of header
        header_path.addRect(QRectF(0, _BLOCK_HEADER_H - r, w, r))
        painter.fillPath(header_path, QBrush(self._cat_color))

        # Param section background
        bd = self.instance.block_def
        if bd.parameters:
            params_h = len(bd.parameters) * 15 + 16
            ports_h = max(len(bd.input_ports), len(bd.output_ports), 1) * _PORT_SPACING + 12
            ps_y = _BLOCK_HEADER_H + ports_h
            ps_path = QPainterPath()
            ps_path.addRoundedRect(QRectF(0, ps_y, w, params_h), r, r)
            ps_path.addRect(QRectF(0, ps_y, w, r))
            painter.fillPath(ps_path, QBrush(QColor(_CRUST)))
            # Separator line
            sep_pen = QPen(QColor(_SURFACE1), 1)
            sep_pen.setCosmetic(True)
            painter.setPen(sep_pen)
            painter.drawLine(QLineF(8, ps_y, w - 8, ps_y))

        # Border
        if self.isSelected():
            border_pen = QPen(QColor(_LAVENDER), 3)
        elif self._hover:
            border_pen = QPen(QColor(_BLUE), 2)
        else:
            border_pen = QPen(self._cat_color, 1.5)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPath(body_path)

        # Validation indicators: ring around unconnected mandatory ports
        for port_name, pi in self.port_items.items():
            if pi._connected:
                continue
            is_mandatory = port_name.lower() in _MANDATORY_PORTS
            ring_color = QColor(_RED) if is_mandatory else QColor(_PEACH)
            ring_pen = QPen(ring_color, 1.5)
            ring_pen.setCosmetic(True)
            ring_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(ring_pen)
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            center = pi.pos()
            painter.drawEllipse(center, _PORT_RADIUS + 4, _PORT_RADIUS + 4)

    def hoverEnterEvent(self, event):  # type: ignore[override]
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):  # type: ignore[override]
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(value, QPointF):
            # Snap to grid
            snapped = QPointF(
                round(value.x() / _GRID_SNAP) * _GRID_SNAP,
                round(value.y() / _GRID_SNAP) * _GRID_SNAP,
            )
            return snapped
        return super().itemChange(change, value)

    def get_port_scene_pos(self, port_name: str) -> QPointF | None:
        pi = self.port_items.get(port_name)
        if pi:
            return pi.get_scene_center()
        return None

    def mark_port_connected(self, port_name: str, connected: bool = True) -> None:
        pi = self.port_items.get(port_name)
        if pi:
            pi.set_connected(connected)
            self.update()


# ── Wire graphics item (Manhattan routing) ───────────────────────────────────

class _WireItem(QGraphicsPathItem):
    """Manhattan-routed wire between two ports."""

    def __init__(self, wire: WireConnection, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.wire = wire
        self.setZValue(2)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label: QGraphicsSimpleTextItem | None = None

    def update_route(self, src: QPointF, dst: QPointF, signal_type: str = "data") -> None:
        color = QColor(_WIRE_COLORS.get(signal_type, _WIRE_COLORS["default"]))
        pen = QPen(color, 3)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)
        # Manhattan routing with bend
        path = QPainterPath()
        path.moveTo(src)
        mid_x = (src.x() + dst.x()) / 2
        path.lineTo(mid_x, src.y())
        path.lineTo(mid_x, dst.y())
        path.lineTo(dst)
        self.setPath(path)
        self.setToolTip(
            f"{self.wire.src_block}.{self.wire.src_port} -> "
            f"{self.wire.dst_block}.{self.wire.dst_port}"
        )
        # Midpoint label
        if self._label is None:
            self._label = QGraphicsSimpleTextItem(self.wire.src_port, self)
            self._label.setFont(QFont("Consolas", 7))
            self._label.setBrush(QBrush(QColor(_SUBTEXT)))
        else:
            self._label.setText(self.wire.src_port)
        mid_y = (src.y() + dst.y()) / 2
        self._label.setPos(mid_x + 4, mid_y - 8)


# ── Canvas scene ─────────────────────────────────────────────────────────────

class _BlockDesignScene(QGraphicsScene):
    """Scene with snap-to-grid background."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(_BG)))

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        view = self.views()[0] if self.views() else None
        if view is None:
            return
        t = view.transform()
        scale = math.sqrt(t.m11() ** 2 + t.m12() ** 2)
        pixel_spacing = _GRID_SIZE * scale
        if pixel_spacing < 8:
            return
        pen = QPen(QColor(_SURFACE0), 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        left = rect.left() - (rect.left() % _GRID_SIZE)
        top = rect.top() - (rect.top() % _GRID_SIZE)
        x = left
        while x <= rect.right():
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
            x += _GRID_SIZE
        y = top
        while y <= rect.bottom():
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += _GRID_SIZE


# ── Canvas view ──────────────────────────────────────────────────────────────

class _BlockDesignCanvas(QGraphicsView):
    """Main canvas for block design editing."""

    design_modified = Signal()
    block_clicked = Signal(str)

    def __init__(self, scene: _BlockDesignScene, parent: QWidget | None = None) -> None:
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
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pan_active = False
        self._pan_start = QPointF()

        self._undo_stack = QUndoStack(self)
        self._blocks: dict[str, BlockInstance] = {}
        self._block_items: dict[str, _BlockItem] = {}
        self._wires: list[WireConnection] = []
        self._wire_items: dict[str, _WireItem] = {}
        self._instance_counter: int = 0

        # Wire drawing state
        self._wiring = False
        self._wire_src_port: _PortItem | None = None
        self._wire_preview: QGraphicsPathItem | None = None

        # Block dragging state
        self._dragging_block: _BlockItem | None = None
        self._drag_start_pos: tuple[float, float] = (0, 0)

    @property
    def undo_stack(self) -> QUndoStack:
        return self._undo_stack

    # ── Block management (internal, called by undo commands) ─────────────

    def _do_add_block(self, instance: BlockInstance) -> None:
        self._blocks[instance.instance_id] = instance
        item = _BlockItem(instance)
        self.scene().addItem(item)
        self._block_items[instance.instance_id] = item
        self.design_modified.emit()

    def _do_remove_block(self, instance_id: str) -> None:
        item = self._block_items.pop(instance_id, None)
        if item:
            self.scene().removeItem(item)
        self._blocks.pop(instance_id, None)
        self.design_modified.emit()

    def _do_move_block(self, instance_id: str, x: float, y: float) -> None:
        inst = self._blocks.get(instance_id)
        if inst:
            inst.x = x
            inst.y = y
        item = self._block_items.get(instance_id)
        if item:
            item.setPos(x, y)
        self._refresh_all_wires()

    def _do_add_wire(self, wire: WireConnection) -> None:
        self._wires.append(wire)
        wi = _WireItem(wire)
        self.scene().addItem(wi)
        self._wire_items[wire.wire_id] = wi
        self._update_wire(wire.wire_id)
        # Mark connected ports
        sb = self._block_items.get(wire.src_block)
        db = self._block_items.get(wire.dst_block)
        if sb:
            sb.mark_port_connected(wire.src_port, True)
        if db:
            db.mark_port_connected(wire.dst_port, True)
        self.design_modified.emit()

    def _do_remove_wire(self, wire_id: str) -> None:
        wi = self._wire_items.pop(wire_id, None)
        if wi:
            self.scene().removeItem(wi)
        wire = next((w for w in self._wires if w.wire_id == wire_id), None)
        self._wires = [w for w in self._wires if w.wire_id != wire_id]
        if wire:
            # Recompute connection state for affected ports
            sb = self._block_items.get(wire.src_block)
            db = self._block_items.get(wire.dst_block)
            still_src = any(
                w.src_block == wire.src_block and w.src_port == wire.src_port
                or w.dst_block == wire.src_block and w.dst_port == wire.src_port
                for w in self._wires
            )
            still_dst = any(
                w.src_block == wire.dst_block and w.src_port == wire.dst_port
                or w.dst_block == wire.dst_block and w.dst_port == wire.dst_port
                for w in self._wires
            )
            if sb:
                sb.mark_port_connected(wire.src_port, still_src)
            if db:
                db.mark_port_connected(wire.dst_port, still_dst)
        self.design_modified.emit()

    def _update_wire(self, wire_id: str) -> None:
        wi = self._wire_items.get(wire_id)
        wire = next((w for w in self._wires if w.wire_id == wire_id), None)
        if not wi or not wire:
            return
        src_item = self._block_items.get(wire.src_block)
        dst_item = self._block_items.get(wire.dst_block)
        if not src_item or not dst_item:
            return
        src_pos = src_item.get_port_scene_pos(wire.src_port)
        dst_pos = dst_item.get_port_scene_pos(wire.dst_port)
        if not src_pos or not dst_pos:
            return
        # Determine signal type for wire colour
        src_port_def = next(
            (p for p in src_item.instance.block_def.ports if p.name == wire.src_port),
            None,
        )
        sig_type = src_port_def.signal_type if src_port_def else "data"
        wi.update_route(src_pos, dst_pos, sig_type)

    def _refresh_all_wires(self) -> None:
        for w in self._wires:
            self._update_wire(w.wire_id)

    # ── Public add block ─────────────────────────────────────────────────

    def add_block(self, block_def: IPBlockDef, x: float = 100, y: float = 100) -> str:
        """Add a new block instance to the design."""
        self._instance_counter += 1
        inst_id = f"u_{block_def.name}_{self._instance_counter}"
        # Snap to grid
        x = round(x / _GRID_SIZE) * _GRID_SIZE
        y = round(y / _GRID_SIZE) * _GRID_SIZE
        instance = BlockInstance(inst_id, block_def, x, y)
        cmd = _AddBlockCommand(self, instance)
        self._undo_stack.push(cmd)
        return inst_id

    def remove_selected(self) -> None:
        for item in self.scene().selectedItems():
            if isinstance(item, _BlockItem):
                cmd = _RemoveBlockCommand(self, item.instance.instance_id)
                self._undo_stack.push(cmd)
            elif isinstance(item, _WireItem):
                cmd = _RemoveWireCommand(self, item.wire.wire_id)
                self._undo_stack.push(cmd)

    # ── Validation ───────────────────────────────────────────────────────

    def validate(self) -> list[dict[str, Any]]:
        """Validate the design.  Returns list of issue dicts."""
        issues: list[dict[str, Any]] = []
        connected_ports: set[tuple[str, str]] = set()
        for w in self._wires:
            connected_ports.add((w.src_block, w.src_port))
            connected_ports.add((w.dst_block, w.dst_port))

        for inst_id, inst in self._blocks.items():
            for p in inst.block_def.ports:
                if (inst_id, p.name) not in connected_ports:
                    issues.append({
                        "type": "unconnected",
                        "severity": "warning",
                        "block": inst_id,
                        "port": p.name,
                        "message": f"Unconnected port: {inst_id}.{p.name}",
                    })
        # Width mismatches
        for w in self._wires:
            src_inst = self._blocks.get(w.src_block)
            dst_inst = self._blocks.get(w.dst_block)
            if not src_inst or not dst_inst:
                continue
            src_port = next((p for p in src_inst.block_def.ports if p.name == w.src_port), None)
            dst_port = next((p for p in dst_inst.block_def.ports if p.name == w.dst_port), None)
            if src_port and dst_port and src_port.bit_width != dst_port.bit_width:
                issues.append({
                    "type": "width_mismatch",
                    "severity": "error",
                    "block": w.src_block,
                    "port": w.src_port,
                    "message": (
                        f"Width mismatch: {w.src_block}.{w.src_port} "
                        f"({src_port.bit_width}b) -> {w.dst_block}.{w.dst_port} "
                        f"({dst_port.bit_width}b)"
                    ),
                })

        # Clock domain crossing detection
        clock_domains: dict[str, str] = {}
        for w in self._wires:
            src_inst = self._blocks.get(w.src_block)
            if not src_inst:
                continue
            src_port = next((p for p in src_inst.block_def.ports if p.name == w.src_port), None)
            if src_port and src_port.signal_type == "clock":
                clock_domains[w.dst_block] = f"{w.src_block}.{w.src_port}"

        # Highlight validation issues on canvas
        for item in self._block_items.values():
            cat_color = _CAT_COLORS.get(item.instance.block_def.category, _CAT_COLORS["default"])
            item.setPen(QPen(QColor(cat_color), 1.5))

        for issue in issues:
            block_id = issue["block"]
            bi = self._block_items.get(block_id)
            if not bi:
                continue
            if issue["type"] == "unconnected":
                port_name = issue["port"]
                pi = bi.port_items.get(port_name)
                if pi:
                    pi.setBrush(QBrush(QColor(_PEACH)))
            elif issue["type"] == "width_mismatch":
                bi.setPen(QPen(QColor(_RED), 2.5))

        return issues

    # ── Verilog generation ───────────────────────────────────────────────

    def generate_verilog(self) -> str:
        """Generate a Verilog wrapper module from the current design."""
        lines: list[str] = []
        lines.append("`timescale 1ns / 1ps")
        lines.append("// Auto-generated by OpenForge Block Design Editor")
        lines.append("// Do not edit manually")
        lines.append("")

        # Collect external ports (unconnected inputs become module inputs, etc.)
        connected_in: set[tuple[str, str]] = set()
        connected_out: set[tuple[str, str]] = set()
        for w in self._wires:
            connected_in.add((w.dst_block, w.dst_port))
            connected_out.add((w.src_block, w.src_port))

        ext_inputs: list[tuple[str, PortDef]] = []
        ext_outputs: list[tuple[str, PortDef]] = []
        for inst_id, inst in self._blocks.items():
            for p in inst.block_def.input_ports:
                if (inst_id, p.name) not in connected_in:
                    ext_inputs.append((inst_id, p))
            for p in inst.block_def.output_ports:
                if (inst_id, p.name) not in connected_out:
                    ext_outputs.append((inst_id, p))

        lines.append("module block_design (")
        port_lines: list[str] = []
        for inst_id, p in ext_inputs:
            wire_name = f"{inst_id}_{p.name}"
            w = f" {p.width}" if p.width else ""
            port_lines.append(f"    input  wire{w} {wire_name}")
        for inst_id, p in ext_outputs:
            wire_name = f"{inst_id}_{p.name}"
            w = f" {p.width}" if p.width else ""
            port_lines.append(f"    output wire{w} {wire_name}")
        lines.append(",\n".join(port_lines))
        lines.append(");")
        lines.append("")

        # Internal wires
        lines.append("// Internal wires")
        for w in self._wires:
            src_inst = self._blocks.get(w.src_block)
            if not src_inst:
                continue
            src_port = next((p for p in src_inst.block_def.ports if p.name == w.src_port), None)
            width_str = f" {src_port.width}" if src_port and src_port.width else ""
            wire_name = f"w_{w.src_block}_{w.src_port}_to_{w.dst_block}_{w.dst_port}"
            lines.append(f"wire{width_str} {wire_name};")
        lines.append("")

        # Instantiate each block
        for inst_id, inst in self._blocks.items():
            bd = inst.block_def
            mod_name = bd.top_module or bd.name

            # Parameters
            if bd.parameters:
                param_strs: list[str] = []
                for param in bd.parameters:
                    val = inst.param_overrides.get(param.name, param.default)
                    param_strs.append(f"    .{param.name}({val})")
                lines.append(f"{mod_name} #(")
                lines.append(",\n".join(param_strs))
                lines.append(f") {inst_id} (")
            else:
                lines.append(f"{mod_name} {inst_id} (")

            # Port connections
            port_conns: list[str] = []
            for p in bd.ports:
                # Check if connected by a wire
                wire = None
                for w in self._wires:
                    if w.dst_block == inst_id and w.dst_port == p.name:
                        wire = w
                        break
                    if w.src_block == inst_id and w.src_port == p.name:
                        wire = w
                        break
                if wire:
                    wire_name = f"w_{wire.src_block}_{wire.src_port}_to_{wire.dst_block}_{wire.dst_port}"
                    port_conns.append(f"    .{p.name}({wire_name})")
                else:
                    # External port
                    ext_name = f"{inst_id}_{p.name}"
                    port_conns.append(f"    .{p.name}({ext_name})")
            lines.append(",\n".join(port_conns))
            lines.append(");")
            lines.append("")

        lines.append("endmodule")
        return "\n".join(lines)

    # ── Event handling ───────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        anchor = self.mapToScene(event.position().toPoint())
        factor = _ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / _ZOOM_FACTOR
        self.scale(factor, factor)
        new_pos = self.mapToScene(event.position().toPoint())
        delta = new_pos - anchor
        self.translate(delta.x(), delta.y())

    def mousePressEvent(self, event):  # noqa: N802
        # Middle button OR Space+LeftClick OR Right button = pan
        if event.button() == Qt.MouseButton.MiddleButton or event.button() == Qt.MouseButton.RightButton:
            self._pan_active = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            items = self.scene().items(scene_pos)

            # Check for port click (start/finish wiring)
            for item in items:
                if isinstance(item, _PortItem):
                    if not self._wiring:
                        self._wiring = True
                        self._wire_src_port = item
                        # Create preview wire
                        pen = QPen(QColor(_SUBTEXT), 2, Qt.PenStyle.DashLine)
                        pen.setCosmetic(True)
                        path = QPainterPath()
                        path.moveTo(item.get_scene_center())
                        path.lineTo(scene_pos)
                        self._wire_preview = self.scene().addPath(path, pen)
                        return
                    else:
                        # Finish wiring
                        self._finish_wiring(item)
                        return

            # Check for block click
            block_clicked = False
            for item in items:
                if isinstance(item, _BlockItem):
                    self._dragging_block = item
                    self._drag_start_pos = (item.instance.x, item.instance.y)
                    self.block_clicked.emit(item.instance.instance_id)
                    block_clicked = True
                    break

            # Cancel wiring if clicking empty space
            if self._wiring:
                self._cancel_wiring()

            # If left-click on empty space, start panning (hand-grab mode)
            if not block_clicked:
                self._pan_active = True
                self._pan_start = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._pan_active:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.translate(delta.x() / self.transform().m11(),
                           delta.y() / self.transform().m22())
            return
        if self._wire_preview and self._wire_src_port:
            scene_pos = self.mapToScene(event.position().toPoint())
            path = QPainterPath()
            src = self._wire_src_port.get_scene_center()
            path.moveTo(src)
            mid_x = (src.x() + scene_pos.x()) / 2
            path.lineTo(mid_x, src.y())
            path.lineTo(mid_x, scene_pos.y())
            path.lineTo(scene_pos)
            self._wire_preview.setPath(path)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pan_active:
            self._pan_active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._dragging_block:
            # Snap to grid
            item = self._dragging_block
            new_x = round(item.pos().x() / _GRID_SIZE) * _GRID_SIZE
            new_y = round(item.pos().y() / _GRID_SIZE) * _GRID_SIZE
            if (new_x, new_y) != self._drag_start_pos:
                item.setPos(new_x, new_y)
                item.instance.x = new_x
                item.instance.y = new_y
                cmd = _MoveBlockCommand(
                    self, item.instance.instance_id,
                    self._drag_start_pos, (new_x, new_y),
                )
                self._undo_stack.push(cmd)
                self._refresh_all_wires()
            self._dragging_block = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
        elif event.key() == Qt.Key.Key_Escape:
            if self._wiring:
                self._cancel_wiring()
        else:
            super().keyPressEvent(event)

    def _finish_wiring(self, dst_port: _PortItem) -> None:
        src = self._wire_src_port
        if src is None:
            self._cancel_wiring()
            return
        # Validate: src should be output, dst should be input (or vice versa)
        if src.is_output == dst_port.is_output:
            # Both same direction -- try swapping
            if not src.is_output and dst_port.is_output:
                src, dst_port = dst_port, src
            else:
                self._cancel_wiring()
                return
        if src.is_output:
            src_block, src_port_name = src.block_id, src.port_def.name
            dst_block, dst_port_name = dst_port.block_id, dst_port.port_def.name
        else:
            src_block, src_port_name = dst_port.block_id, dst_port.port_def.name
            dst_block, dst_port_name = src.block_id, src.port_def.name

        wire_id = f"w_{src_block}_{src_port_name}_to_{dst_block}_{dst_port_name}"
        wire = WireConnection(wire_id, src_block, src_port_name, dst_block, dst_port_name)
        cmd = _AddWireCommand(self, wire)
        self._undo_stack.push(cmd)
        self._cancel_wiring()

    def _cancel_wiring(self) -> None:
        if self._wire_preview:
            self.scene().removeItem(self._wire_preview)
            self._wire_preview = None
        self._wire_src_port = None
        self._wiring = False

    # ── Save / Load ──────────────────────────────────────────────────────

    def to_json(self) -> dict[str, Any]:
        return {
            "blocks": [
                {
                    "instance_id": inst.instance_id,
                    "block_name": inst.block_def.name,
                    "x": inst.x,
                    "y": inst.y,
                    "param_overrides": inst.param_overrides,
                }
                for inst in self._blocks.values()
            ],
            "wires": [
                {
                    "wire_id": w.wire_id,
                    "src_block": w.src_block,
                    "src_port": w.src_port,
                    "dst_block": w.dst_block,
                    "dst_port": w.dst_port,
                }
                for w in self._wires
            ],
        }

    def zoom_fit(self) -> None:
        sr = self.scene().itemsBoundingRect()
        if sr.isEmpty():
            return
        sr.adjust(-40, -40, 40, 40)
        self.fitInView(sr, Qt.AspectRatioMode.KeepAspectRatio)


# ── IP Palette widget ────────────────────────────────────────────────────────

class _IPPaletteWidget(QWidget):
    """Left sidebar listing available IP blocks for drag onto canvas."""

    block_requested = Signal(object)  # emits IPBlockDef

    def __init__(self, ip_blocks: list[IPBlockDef], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        header = QLabel("IP Palette")
        header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {_BLUE};")
        layout.addWidget(header)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search IPs...")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["IP Block"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(14)
        self._tree.setIconSize(QSize(20, 20))
        self._tree.setStyleSheet(
            f"""
            QTreeWidget {{
                background-color: {_MANTLE};
                color: {_TEXT};
                border: 1px solid {_SURFACE0};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 6px 4px;
                border-radius: 4px;
            }}
            QTreeWidget::item:hover {{
                background-color: {_SURFACE0};
            }}
            QTreeWidget::item:selected {{
                background-color: {_SURFACE1};
                color: {_LAVENDER};
            }}
            """
        )
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

        self._ip_blocks = ip_blocks
        self._populate()

    def _populate(self) -> None:
        self._tree.clear()
        categories: dict[str, QTreeWidgetItem] = {}
        for block in self._ip_blocks:
            cat = block.category or "Other"
            if cat not in categories:
                cat_item = QTreeWidgetItem([cat])
                cat_item.setFont(0, QFont("Segoe UI", 9, QFont.Weight.Bold))
                cat_color = _CAT_COLORS.get(cat, _CAT_COLORS["default"])
                cat_item.setForeground(0, QColor(cat_color))
                self._tree.addTopLevelItem(cat_item)
                cat_item.setExpanded(True)
                categories[cat] = cat_item

            item = QTreeWidgetItem([block.name])
            item.setToolTip(
                0,
                f"{block.description or block.name}\n"
                f"Ports: {len(block.ports)}  Params: {len(block.parameters)}"
            )
            item.setData(0, Qt.ItemDataRole.UserRole, block)
            # Color swatch icon
            try:
                from PySide6.QtGui import QIcon, QPixmap
                cat_color = _CAT_COLORS.get(cat, _CAT_COLORS["default"])
                pix = QPixmap(20, 20)
                pix.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setBrush(QBrush(QColor(cat_color)))
                painter.setPen(QPen(QColor(_CRUST), 1))
                painter.drawRoundedRect(2, 2, 16, 16, 4, 4)
                painter.end()
                item.setIcon(0, QIcon(pix))
            except Exception:
                pass
            categories[cat].addChild(item)

    def _filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self._tree.topLevelItemCount()):
            cat_item = self._tree.topLevelItem(i)
            if cat_item is None:
                continue
            any_visible = False
            for j in range(cat_item.childCount()):
                child = cat_item.child(j)
                if child is None:
                    continue
                visible = text in child.text(0).lower()
                child.setHidden(not visible)
                if visible:
                    any_visible = True
            cat_item.setHidden(not any_visible)

    def _on_double_click(self, item: QTreeWidgetItem, col: int) -> None:
        block = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(block, IPBlockDef):
            self.block_requested.emit(block)


# ── Validation panel ─────────────────────────────────────────────────────────

class _ValidationWidget(QWidget):
    """Shows validation results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        header = QLabel("Validation")
        header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {_BLUE};")
        layout.addWidget(header)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Severity", "Block/Port", "Message"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

    def set_issues(self, issues: list[dict[str, Any]]) -> None:
        self._table.setRowCount(0)
        for issue in issues:
            row = self._table.rowCount()
            self._table.insertRow(row)
            sev = issue.get("severity", "info")
            sev_item = QTableWidgetItem(sev.upper())
            sev_color = {
                "error": _RED,
                "warning": _PEACH,
                "info": _BLUE,
            }.get(sev, _TEXT)
            sev_item.setForeground(QColor(sev_color))
            self._table.setItem(row, 0, sev_item)
            loc = f"{issue.get('block', '')}.{issue.get('port', '')}"
            self._table.setItem(row, 1, QTableWidgetItem(loc))
            self._table.setItem(row, 2, QTableWidgetItem(issue.get("message", "")))


# ── Parameter edit dialog ────────────────────────────────────────────────────

class _ParamEditDialog(QDialog):
    """Dialog for editing block instance parameters."""

    def __init__(self, instance: BlockInstance, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Parameters: {instance.instance_id}")
        self.setMinimumWidth(400)
        self._instance = instance
        layout = QFormLayout(self)
        self._edits: dict[str, QLineEdit] = {}
        for param in instance.block_def.parameters:
            val = instance.param_overrides.get(param.name, param.default)
            edit = QLineEdit(str(val))
            edit.setPlaceholderText(f"default: {param.default}")
            layout.addRow(f"{param.name}:", edit)
            self._edits[param.name] = edit
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_overrides(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, edit in self._edits.items():
            val = edit.text().strip()
            if val:
                result[name] = val
        return result


# ── Main Block Design Panel ─────────────────────────────────────────────────

class BlockDesignPanel(QDockWidget):
    """Dock widget hosting the block design editor."""

    design_changed = Signal()
    generate_requested = Signal(str)
    block_selected = Signal(str)

    def __init__(
        self,
        title: str = "Block Design",
        parent: QWidget | None = None,
        share_ip_dir: str | Path | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dark = True
        self._design_path: Path | None = None

        # Load IP catalog
        ip_blocks: list[IPBlockDef] = list(_PRIMITIVES)
        if share_ip_dir:
            ip_blocks.extend(_load_ip_catalog(Path(share_ip_dir)))
        self._ip_blocks = ip_blocks

        # Build UI
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self._act_new = self._toolbar.addAction("New")
        self._act_new.triggered.connect(self._new_design)
        self._act_open = self._toolbar.addAction("Open")
        self._act_open.triggered.connect(self._open_design)
        self._act_save = self._toolbar.addAction("Save")
        self._act_save.triggered.connect(self._save_design)
        self._act_save_as = self._toolbar.addAction("Save As")
        self._act_save_as.triggered.connect(self._save_design_as)
        self._toolbar.addSeparator()
        self._act_undo = self._toolbar.addAction("Undo")
        self._act_undo.triggered.connect(lambda: self._canvas.undo_stack.undo())
        self._act_redo = self._toolbar.addAction("Redo")
        self._act_redo.triggered.connect(lambda: self._canvas.undo_stack.redo())
        self._toolbar.addSeparator()
        self._act_validate = self._toolbar.addAction("Validate")
        self._act_validate.triggered.connect(self._run_validation)
        self._act_generate = self._toolbar.addAction("Generate Verilog")
        self._act_generate.triggered.connect(self._generate_verilog)
        self._toolbar.addSeparator()
        # Wave 2 - Phase 8 tooling
        self._act_smart_connect = self._toolbar.addAction("Smart Connect")
        self._act_smart_connect.triggered.connect(self._on_smart_connect)
        self._act_addr_editor = self._toolbar.addAction("Address Editor")
        self._act_addr_editor.triggered.connect(self._on_open_address_editor)
        self._act_axi_monitors = self._toolbar.addAction("Insert AXI Monitors")
        self._act_axi_monitors.triggered.connect(self._on_insert_axi_monitors)
        self._act_ip_catalog = self._toolbar.addAction("IP Catalog")
        self._act_ip_catalog.triggered.connect(self._on_open_ip_catalog)
        self._act_export_decoder = self._toolbar.addAction("Export Decoder")
        self._act_export_decoder.triggered.connect(self._on_export_decoder)
        self._act_export_dt = self._toolbar.addAction("Export DT")
        self._act_export_dt.triggered.connect(self._on_export_device_tree)
        self._toolbar.addSeparator()
        # Persistent address map (Phase 8)
        self._address_map: Any = None
        if _BD_ADDRMAP_OK:
            self._address_map = _BDAddressMap()
        self._act_zoom_fit = self._toolbar.addAction("Fit All")
        self._act_zoom_fit.triggered.connect(lambda: self._canvas.zoom_fit())
        main_layout.addWidget(self._toolbar)

        # Splitter: palette | canvas | validation
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # IP palette
        self._palette = _IPPaletteWidget(self._ip_blocks)
        self._palette.block_requested.connect(self._on_block_requested)
        self._palette.setFixedWidth(200)
        self._splitter.addWidget(self._palette)

        # Canvas
        self._scene = _BlockDesignScene()
        self._canvas = _BlockDesignCanvas(self._scene)
        self._canvas.design_modified.connect(self._on_design_modified)
        self._canvas.block_clicked.connect(self._on_block_clicked)
        self._splitter.addWidget(self._canvas)

        # Right panel: validation + properties
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self._validation_widget = _ValidationWidget()
        right_layout.addWidget(self._validation_widget, stretch=1)

        # Block properties
        prop_group = QGroupBox("Selected Block")
        prop_layout = QVBoxLayout(prop_group)
        self._prop_label = QLabel("No block selected")
        self._prop_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        prop_layout.addWidget(self._prop_label)
        self._edit_params_btn = QPushButton("Edit Parameters")
        self._edit_params_btn.clicked.connect(self._edit_selected_params)
        self._edit_params_btn.setEnabled(False)
        prop_layout.addWidget(self._edit_params_btn)
        right_layout.addWidget(prop_group)

        right_panel.setFixedWidth(220)
        self._splitter.addWidget(right_panel)

        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        main_layout.addWidget(self._splitter)

        self.setWidget(main_widget)
        self._selected_block_id: str | None = None
        self._apply_theme()

    # ── Public API ───────────────────────────────────────────────────────

    def add_block(self, block_def: IPBlockDef, x: float = 100, y: float = 100) -> str:
        return self._canvas.add_block(block_def, x, y)

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme()

    def load_design(self, filepath: str | Path) -> None:
        """Load a block design from JSON."""
        path = Path(filepath)
        data = json.loads(path.read_text(encoding="utf-8"))
        self._design_path = path
        self._clear_design()

        block_map: dict[str, IPBlockDef] = {b.name: b for b in self._ip_blocks}

        for bd in data.get("blocks", []):
            bdef = block_map.get(bd["block_name"])
            if not bdef:
                continue
            inst = BlockInstance(
                bd["instance_id"], bdef,
                bd.get("x", 0), bd.get("y", 0),
                bd.get("param_overrides", {}),
            )
            self._canvas._do_add_block(inst)
            self._canvas._instance_counter = max(
                self._canvas._instance_counter,
                int(re.search(r"_(\d+)$", bd["instance_id"]).group(1))
                if re.search(r"_(\d+)$", bd["instance_id"]) else 0
            )

        for wd in data.get("wires", []):
            wire = WireConnection(
                wd["wire_id"], wd["src_block"], wd["src_port"],
                wd["dst_block"], wd["dst_port"],
            )
            self._canvas._do_add_wire(wire)

        self._canvas.zoom_fit()

    def save_design(self, filepath: str | Path) -> None:
        """Save current block design to JSON."""
        path = Path(filepath)
        data = self._canvas.to_json()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._design_path = path

    # ── Slots ────────────────────────────────────────────────────────────

    def _on_block_requested(self, block_def: IPBlockDef) -> None:
        vp = self._canvas.viewport().rect()
        center = self._canvas.mapToScene(vp.center())
        self._canvas.add_block(block_def, center.x(), center.y())

    def _on_design_modified(self) -> None:
        self.design_changed.emit()

    def _on_block_clicked(self, instance_id: str) -> None:
        self._selected_block_id = instance_id
        inst = self._canvas._blocks.get(instance_id)
        if inst:
            self._prop_label.setText(
                f"Block: {inst.block_def.name}\n"
                f"Instance: {instance_id}\n"
                f"Category: {inst.block_def.category}\n"
                f"Ports: {len(inst.block_def.ports)}\n"
                f"Params: {len(inst.block_def.parameters)}"
            )
            self._edit_params_btn.setEnabled(bool(inst.block_def.parameters))
        self.block_selected.emit(instance_id)

    def _edit_selected_params(self) -> None:
        if not self._selected_block_id:
            return
        inst = self._canvas._blocks.get(self._selected_block_id)
        if not inst:
            return
        dlg = _ParamEditDialog(inst, self)
        dlg.setStyleSheet(self._dialog_qss())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            inst.param_overrides = dlg.get_overrides()
            # Rebuild the block item visually
            self._canvas._do_remove_block(inst.instance_id)
            self._canvas._do_add_block(inst)
            self._canvas._refresh_all_wires()

    def _run_validation(self) -> None:
        issues = self._canvas.validate()
        if _BD_GENERATOR_AVAILABLE:
            design = self._build_block_design()
            if design is not None:
                for msg in _bd_validate(design):
                    sev = "error" if ("mismatch" in msg or "direction" in msg
                                      or "cycle" in msg or "unknown" in msg
                                      or "slice" in msg or "duplicate" in msg) else "warning"
                    issues.append({
                        "type": "lint",
                        "severity": sev,
                        "block": "",
                        "port": "",
                        "message": msg,
                    })
        self._validation_widget.set_issues(issues)

    def _build_block_design(self):  # type: ignore[no-untyped-def]
        """Convert the canvas state into a core BlockDesign object."""
        if not _BD_GENERATOR_AVAILABLE:
            return None

        {i.instance_id for i in self._canvas._blocks.values()}

        def _to_port(p: PortDef) -> _BDPort:
            return _BDPort(name=p.name, direction=p.direction, width=max(1, p.bit_width))

        instances: list[_BDInstance] = []
        for inst in self._canvas._blocks.values():
            bd = inst.block_def
            params: dict[str, str | int] = {}
            for pr in bd.parameters:
                val = inst.param_overrides.get(pr.name, pr.default)
                params[pr.name] = val
            instances.append(
                _BDInstance(
                    name=inst.instance_id,
                    module=bd.top_module or bd.name,
                    params=params,
                    ports=[_to_port(p) for p in bd.ports],
                    description=bd.description,
                )
            )

        connections = [
            _BDConnection(
                from_inst=w.src_block, from_port=w.src_port,
                to_inst=w.dst_block, to_port=w.dst_port,
            )
            for w in self._canvas._wires
        ]

        # Any port that is not connected becomes a top-level port so the
        # generated module is self-contained.
        sunk: set[tuple[str, str]] = {(c.to_inst, c.to_port) for c in connections}
        driven: set[tuple[str, str]] = {(c.from_inst, c.from_port) for c in connections}
        top_ports: list[_BDPort] = []
        seen_top: set[str] = set()
        for inst in self._canvas._blocks.values():
            for p in inst.block_def.ports:
                key = (inst.instance_id, p.name)
                if p.direction == "output" and key in driven:
                    continue
                if p.direction != "output" and key in sunk:
                    continue
                top_name = f"{inst.instance_id}_{p.name}"
                if top_name in seen_top:
                    continue
                seen_top.add(top_name)
                top_ports.append(_BDPort(top_name, p.direction, max(1, p.bit_width)))

        design_name = (self._design_path.stem if self._design_path else "block_design")
        return _BDDesign(
            name=re.sub(r"[^A-Za-z0-9_]", "_", design_name) or "block_design",
            instances=instances,
            connections=connections,
            top_ports=top_ports,
            description="Generated from OpenForge block design editor",
        )

    def _show_verilog_preview(self, verilog: str, title: str = "Generated Verilog") -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(900, 700)
        dlg.setStyleSheet(self._dialog_qss())
        lay = QVBoxLayout(dlg)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(verilog)
        editor.setFont(QFont("Consolas", 10))
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {_CRUST}; color: {_TEXT};"
            f" border: 1px solid {_SURFACE1}; }}"
        )
        lay.addWidget(editor, stretch=1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                | QDialogButtonBox.StandardButton.Close)
        lay.addWidget(btns)

        def _save() -> None:
            path, _ = QFileDialog.getSaveFileName(
                dlg, "Save Generated Verilog", "block_design.v",
                "Verilog Files (*.v);;All Files (*)",
            )
            if path:
                Path(path).write_text(verilog, encoding="utf-8")

        btns.button(QDialogButtonBox.StandardButton.Save).clicked.connect(_save)
        btns.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.accept)
        dlg.exec()

    def _generate_verilog(self) -> None:
        if _BD_GENERATOR_AVAILABLE:
            design = self._build_block_design()
            if design is not None:
                verilog = _bd_generate_verilog(design)
                testbench = _bd_generate_testbench(design)
                combined = verilog + "\n\n" + testbench
                self.generate_requested.emit(verilog)
                self._show_verilog_preview(combined, f"Verilog: {design.name}")
                return
        # Fallback to legacy in-canvas generator
        verilog = self._canvas.generate_verilog()
        self.generate_requested.emit(verilog)
        self._show_verilog_preview(verilog, "Verilog")

    def _add_ip_from_library(self, factory_key: str) -> None:
        """Add an IP block to the canvas from the built-in library."""
        if not _BD_GENERATOR_AVAILABLE or factory_key not in _BD_IP_LIBRARY:
            return
        factory = _BD_IP_LIBRARY[factory_key]
        inst = factory()
        # Convert BlockInstance -> IPBlockDef + place on canvas
        ports = [PortDef(p.name, p.direction, f"[{p.width - 1}:0]" if p.width > 1 else "")
                 for p in inst.ports]
        params = [ParamDef(k, str(v)) for k, v in inst.params.items()]
        bdef = IPBlockDef(
            name=factory_key,
            category="Library",
            description=inst.description,
            ports=ports,
            parameters=params,
            top_module=inst.module,
        )
        vp = self._canvas.viewport().rect()
        center = self._canvas.mapToScene(vp.center())
        self._canvas.add_block(bdef, center.x(), center.y())

    def _new_design(self) -> None:
        self._clear_design()
        self._design_path = None

    def _clear_design(self) -> None:
        self._canvas._undo_stack.clear()
        for wid in list(self._canvas._wire_items.keys()):
            self._canvas._do_remove_wire(wid)
        for bid in list(self._canvas._block_items.keys()):
            self._canvas._do_remove_block(bid)
        self._canvas._instance_counter = 0

    def _open_design(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Block Design", "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.load_design(path)

    def _save_design(self) -> None:
        if self._design_path:
            self.save_design(self._design_path)
        else:
            self._save_design_as()

    def _save_design_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Block Design", "block_design.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.save_design(path)

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        bg = _BG if self._dark else "#f8f9fa"
        mantle = _MANTLE if self._dark else "#e9ecef"
        surface0 = _SURFACE0 if self._dark else "#dee2e6"
        text = _TEXT if self._dark else "#212529"

        self._scene.setBackgroundBrush(QBrush(QColor(bg)))
        base_qss = panel_tab_qss(self._dark)
        extra = f"""
            QDockWidget {{
                background-color: {bg};
                color: {text};
            }}
            QToolBar {{
                background: {mantle};
                border-bottom: 1px solid {surface0};
                spacing: 4px;
                padding: 2px;
            }}
            QToolButton {{
                color: {text};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 11px;
            }}
            QToolButton:hover {{
                background: {surface0};
                border-color: {surface0};
            }}
            QSplitter::handle {{
                background-color: {surface0};
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
            }}
        """
        self.setStyleSheet(base_qss + extra)

    def _dialog_qss(self) -> str:
        bg = _SURFACE0 if self._dark else "#f8f9fa"
        text = _TEXT if self._dark else "#212529"
        surface = _SURFACE1 if self._dark else "#dee2e6"
        crust = _CRUST if self._dark else "#ffffff"
        blue = _BLUE if self._dark else "#0d6efd"
        return (
            f"QDialog {{ background-color: {bg}; color: {text}; }}"
            f"QLabel {{ color: {text}; }}"
            f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ "
            f"  background-color: {crust}; color: {text}; "
            f"  border: 1px solid {surface}; border-radius: 3px; padding: 3px 6px; }}"
            f"QPushButton {{ background-color: {surface}; color: {text}; "
            f"  border: 1px solid {surface}; border-radius: 4px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ border-color: {blue}; }}"
        )

    # ── Context menu ─────────────────────────────────────────────────────

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {_SURFACE0}; color: {_TEXT}; border: 1px solid {_SURFACE1}; }}"
            f"QMenu::item:selected {{ background: {_SURFACE1}; }}"
        )
        menu.addAction("New Design", self._new_design)
        menu.addAction("Open Design...", self._open_design)
        menu.addAction("Save Design", self._save_design)
        menu.addAction("Save Design As...", self._save_design_as)
        menu.addSeparator()
        menu.addAction("Undo", lambda: self._canvas.undo_stack.undo())
        menu.addAction("Redo", lambda: self._canvas.undo_stack.redo())
        menu.addSeparator()
        menu.addAction("Delete Selected", self._canvas.remove_selected)
        menu.addSeparator()
        menu.addAction("Validate Design", self._run_validation)
        menu.addAction("Generate Verilog...", self._generate_verilog)
        menu.addSeparator()
        menu.addAction("Fit All", lambda: self._canvas.zoom_fit())

        # Add IP submenu
        add_menu = menu.addMenu("Add IP Block")
        for block in self._ip_blocks:
            add_menu.addAction(
                block.name,
                lambda b=block: self._on_block_requested(b),
            )

        if _BD_GENERATOR_AVAILABLE and _BD_IP_LIBRARY:
            lib_menu = menu.addMenu("Add IP (Built-in Library)")
            for key in sorted(_BD_IP_LIBRARY.keys()):
                lib_menu.addAction(key, lambda k=key: self._add_ip_from_library(k))

        menu.exec(event.globalPos())

    # ── Phase 8: smart connect ───────────────────────────────────────────
    def _on_smart_connect(self) -> None:
        if not (_BD_GENERATOR_AVAILABLE and _BD_AUTO_OK):
            self._show_info("Smart Connect unavailable", "openforge core not importable")
            return
        design = self._build_block_design()
        if design is None:
            return
        try:
            ac = _BDAutoConnector(design)
            wires = ac.run_all()
        except Exception as exc:
            self._show_info("Smart Connect failed", str(exc))
            return
        if not wires:
            self._show_info("Smart Connect", "No missing connections detected.")
            return
        # Preview the proposed wires and let user accept/reject
        dlg = QDialog(self)
        dlg.setWindowTitle("Smart Connect Preview")
        dlg.setStyleSheet(self._dialog_qss())
        dlg.resize(640, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Proposed connections ({len(wires)}):"))
        table = QTableWidget(len(wires), 4)
        table.setHorizontalHeaderLabels(["From Inst", "From Port", "To Inst", "To Port"])
        for r, w in enumerate(wires):
            table.setItem(r, 0, QTableWidgetItem(w.from_inst))
            table.setItem(r, 1, QTableWidgetItem(w.from_port))
            table.setItem(r, 2, QTableWidgetItem(w.to_inst))
            table.setItem(r, 3, QTableWidgetItem(w.to_port))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(table, stretch=1)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        lay.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Commit: create canvas wires when both sides exist as visible blocks
        added = 0
        for w in wires:
            if w.from_inst == "__top__":
                continue
            src_block = self._canvas._blocks.get(w.from_inst)
            dst_block = self._canvas._blocks.get(w.to_inst)
            if src_block is None or dst_block is None:
                continue
            wire_id = f"auto_{added}_{w.from_inst}_{w.from_port}_{w.to_inst}_{w.to_port}"
            wc = WireConnection(
                wire_id,
                w.from_inst, w.from_port,
                w.to_inst, w.to_port,
            )
            try:
                self._canvas._do_add_wire(wc)
                added += 1
            except Exception:
                continue
        self._show_info("Smart Connect", f"Added {added} connection(s).")

    # ── Phase 8: address editor ──────────────────────────────────────────
    def _on_open_address_editor(self) -> None:
        if not _BD_ADDRMAP_OK:
            self._show_info("Address Editor", "address_map module unavailable")
            return
        dlg = _AddressMapDialog(self._address_map, self)
        dlg.setStyleSheet(self._dialog_qss())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._address_map = dlg.result_map()

    def _on_insert_axi_monitors(self) -> None:
        if not (_BD_GENERATOR_AVAILABLE and _BD_AUTO_OK and _BD_AXI_MON_OK):
            self._show_info("AXI Monitors", "required modules not importable")
            return
        design = self._build_block_design()
        if design is None:
            return
        ac = _BDAutoConnector(design)
        ifaces = ac.detect_axi_interfaces()
        generated: list[str] = []
        for _inst, group in ifaces.items():
            for ifc in group:
                prefix = ifc["prefix"].upper()
                kind = ifc["kind"]
                if kind == "lite":
                    generated.append(_bd_gen_axi_lite_mon(prefix))
                elif kind == "full":
                    generated.append(_bd_gen_axi_full_mon(prefix))
                elif kind == "stream":
                    generated.append(_bd_gen_axis_mon(prefix))
        if not generated:
            self._show_info("AXI Monitors", "no AXI interfaces detected")
            return
        self._show_verilog_preview("\n\n".join(generated), "AXI Protocol Monitors")

    def _on_open_ip_catalog(self) -> None:
        if not _BD_IP_CATALOG_OK:
            self._show_info("IP Catalog", "ip.generators module unavailable")
            return
        dlg = _IPCatalogDialog(_BD_IP_CATALOG, self)
        dlg.setStyleSheet(self._dialog_qss())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            info = dlg.result()
            if info is None:
                return
            verilog = info["verilog"]
            inst = info["instance"]
            # Save verilog to a file next to the design
            try:
                target_dir = (self._design_path.parent if self._design_path
                              else Path.cwd())
                out = target_dir / f"{inst.module}.v"
                out.write_text(verilog, encoding="utf-8")
            except Exception:
                pass
            # Convert to an IPBlockDef and drop on canvas
            ports = [
                PortDef(p.name, p.direction,
                        f"[{p.width - 1}:0]" if p.width > 1 else "")
                for p in inst.ports
            ]
            params = [ParamDef(k, str(v)) for k, v in inst.params.items()]
            bdef = IPBlockDef(
                name=inst.module,
                category="Generated",
                description=inst.description,
                ports=ports,
                parameters=params,
                top_module=inst.module,
            )
            vp = self._canvas.viewport().rect()
            center = self._canvas.mapToScene(vp.center())
            self._canvas.add_block(bdef, center.x(), center.y())

    def _on_export_decoder(self) -> None:
        if not _BD_ADDRMAP_OK or self._address_map is None:
            self._show_info("Export Decoder", "no address map")
            return
        if not getattr(self._address_map, "ranges", None):
            self._show_info("Export Decoder", "address map has no ranges; open Address Editor first")
            return
        verilog = self._address_map.to_verilog_decoder("bd_addr_decoder")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Address Decoder", "bd_addr_decoder.v",
            "Verilog Files (*.v);;All Files (*)",
        )
        if path:
            Path(path).write_text(verilog, encoding="utf-8")

    def _on_export_device_tree(self) -> None:
        if not _BD_ADDRMAP_OK or self._address_map is None:
            self._show_info("Export DT", "no address map")
            return
        if not getattr(self._address_map, "ranges", None):
            self._show_info("Export DT", "address map has no ranges")
            return
        dts = self._address_map.to_device_tree()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Device Tree Fragment", "bd.dtsi",
            "Device Tree (*.dtsi *.dts);;All Files (*)",
        )
        if path:
            Path(path).write_text(dts, encoding="utf-8")

    def _show_info(self, title: str, message: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setStyleSheet(self._dialog_qss())
        lay = QVBoxLayout(dlg)
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()


# ── Phase 8: Address Map Dialog ─────────────────────────────────────────

class _AddressMapDialog(QDialog):
    """Editor for an :class:`AddressMap` with overlap detection."""

    def __init__(self, addr_map: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Address Editor")
        self.resize(780, 480)
        self._map = addr_map
        lay = QVBoxLayout(self)

        tool_row = QHBoxLayout()
        self._btn_add = QPushButton("Add Range")
        self._btn_remove = QPushButton("Remove")
        self._btn_auto = QPushButton("Auto Assign")
        self._btn_check = QPushButton("Check Overlaps")
        for b in (self._btn_add, self._btn_remove, self._btn_auto, self._btn_check):
            tool_row.addWidget(b)
        tool_row.addStretch(1)
        lay.addLayout(tool_row)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Master", "Slave", "Interface", "Base", "Size", "Locked", "Name"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._table, stretch=1)

        self._map_label = QLabel("")
        self._map_label.setFont(QFont("Consolas", 9))
        lay.addWidget(self._map_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._btn_add.clicked.connect(self._add_row)
        self._btn_remove.clicked.connect(self._remove_row)
        self._btn_auto.clicked.connect(self._auto_assign)
        self._btn_check.clicked.connect(self._refresh_overlaps)

        if addr_map is not None:
            for r in getattr(addr_map, "ranges", []) or []:
                self._append_row(r)
        self._refresh_overlaps()

    def _append_row(self, r: Any) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(str(r.master)))
        self._table.setItem(row, 1, QTableWidgetItem(str(r.slave)))
        self._table.setItem(row, 2, QTableWidgetItem(str(r.interface)))
        self._table.setItem(row, 3, QTableWidgetItem(f"0x{r.base_addr:08X}"))
        self._table.setItem(row, 4, QTableWidgetItem(f"0x{r.range_size:08X}"))
        self._table.setItem(row, 5, QTableWidgetItem("yes" if r.locked else "no"))
        self._table.setItem(row, 6, QTableWidgetItem(str(r.name)))

    def _add_row(self) -> None:
        if not _BD_ADDRMAP_OK:
            return
        new = _BDAddressRange(
            master="M_AXI", slave=f"slave{self._table.rowCount()}",
            interface="S_AXI", base_addr=0x4000_0000 + self._table.rowCount() * 0x1000,
            range_size=0x1000, locked=False,
            name=f"slave{self._table.rowCount()}_reg",
        )
        self._append_row(new)

    def _remove_row(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedItems()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self._refresh_overlaps()

    def _auto_assign(self) -> None:
        if not _BD_ADDRMAP_OK:
            return
        # Gather current entries as slaves
        slaves: list[dict] = []
        masters: list[str] = []
        for r in range(self._table.rowCount()):
            masters.append(self._table.item(r, 0).text())
            slaves.append({
                "name": self._table.item(r, 1).text(),
                "interface": self._table.item(r, 2).text(),
                "size": _parse_hex(self._table.item(r, 4).text(), 0x1000),
            })
        uniq_masters = list(dict.fromkeys(masters)) or ["M_AXI"]
        m = _BDAddressMap()
        m.auto_assign(uniq_masters, slaves)
        self._table.setRowCount(0)
        for r in m.ranges:
            self._append_row(r)
        self._map = m
        self._refresh_overlaps()

    def result_map(self) -> Any:
        if not _BD_ADDRMAP_OK:
            return None
        m = _BDAddressMap()
        ranges = []
        for r in range(self._table.rowCount()):
            ranges.append(_BDAddressRange(
                master=self._table.item(r, 0).text(),
                slave=self._table.item(r, 1).text(),
                interface=self._table.item(r, 2).text(),
                base_addr=_parse_hex(self._table.item(r, 3).text(), 0),
                range_size=_parse_hex(self._table.item(r, 4).text(), 0x1000),
                locked=(self._table.item(r, 5).text().lower() in ("yes", "true", "1")),
                name=self._table.item(r, 6).text(),
            ))
        m.ranges = ranges
        return m

    def _refresh_overlaps(self) -> None:
        if not _BD_ADDRMAP_OK:
            return
        m = self.result_map()
        if m is None:
            return
        conflicts = m.overlaps()
        ids: set[int] = set()
        for a, b in conflicts:
            for r in range(self._table.rowCount()):
                nm = self._table.item(r, 1).text()
                if nm == a.slave or nm == b.slave:
                    ids.add(r)
        for r in range(self._table.rowCount()):
            for c in range(self._table.columnCount()):
                it = self._table.item(r, c)
                if it is None:
                    continue
                if r in ids:
                    it.setBackground(QBrush(QColor(_RED)))
                else:
                    it.setBackground(QBrush(QColor(0, 0, 0, 0)))
        self._map_label.setText(m.memory_map_diagram())


def _parse_hex(text: str, fallback: int) -> int:
    try:
        t = text.strip().lower()
        if t.startswith("0x"):
            return int(t, 16)
        return int(t, 0)
    except Exception:
        return fallback


# ── Phase 8: IP catalog dialog ──────────────────────────────────────────


class _IPCatalogDialog(QDialog):
    """Browse parametric IPs and instantiate them."""

    def __init__(self, catalog: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("IP Catalog")
        self.resize(620, 460)
        self._catalog = catalog
        self._result: dict[str, Any] | None = None
        lay = QHBoxLayout(self)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["IP"])
        groups: dict[str, QTreeWidgetItem] = {}
        for name, info in sorted(catalog.items()):
            cat = info.get("category", "Other")
            if cat not in groups:
                groups[cat] = QTreeWidgetItem([cat])
                self._tree.addTopLevelItem(groups[cat])
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            groups[cat].addChild(item)
        for g in groups.values():
            g.setExpanded(True)
        self._tree.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self._tree, stretch=1)

        right = QWidget()
        rlay = QVBoxLayout(right)
        self._desc = QLabel("Select an IP")
        self._desc.setWordWrap(True)
        rlay.addWidget(self._desc)
        self._form = QFormLayout()
        self._form_container = QWidget()
        self._form_container.setLayout(self._form)
        rlay.addWidget(self._form_container, stretch=1)
        self._btn_generate = QPushButton("Generate")
        self._btn_generate.clicked.connect(self._generate)
        rlay.addWidget(self._btn_generate)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        rlay.addWidget(btns)
        lay.addWidget(right, stretch=1)

        self._current_key: str | None = None
        self._param_widgets: dict[str, QWidget] = {}

    def _clear_form(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._param_widgets = {}

    def _on_select(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        key = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not key or key not in self._catalog:
            return
        self._current_key = key
        info = self._catalog[key]
        self._desc.setText(f"<b>{key}</b> ({info.get('category', '')})")
        self._clear_form()
        for pname, pdefault in info["params"].items():
            edit = QLineEdit(str(pdefault) if not isinstance(pdefault, list) else ",".join(str(x) for x in pdefault))
            self._param_widgets[pname] = edit
            self._form.addRow(pname, edit)

    def _coerce(self, default: Any, text: str) -> Any:
        if isinstance(default, bool):
            return text.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            try: return int(text, 0)
            except Exception: return default
        if isinstance(default, float):
            try: return float(text)
            except Exception: return default
        if isinstance(default, list):
            out = []
            for part in text.split(","):
                p = part.strip()
                if not p: continue
                try: out.append(float(p))
                except Exception: out.append(p)
            return out
        return text

    def _generate(self) -> None:
        if self._current_key is None:
            return
        info = self._catalog[self._current_key]
        factory = info["factory"]
        kwargs = {}
        for pname, default in info["params"].items():
            w = self._param_widgets.get(pname)
            if isinstance(w, QLineEdit):
                kwargs[pname] = self._coerce(default, w.text())
            else:
                kwargs[pname] = default
        try:
            verilog, instance = factory(**kwargs)
        except Exception as exc:
            self._desc.setText(f"Generation failed: {exc}")
            return
        self._result = {"verilog": verilog, "instance": instance, "key": self._current_key}
        self.accept()

    def result(self) -> dict[str, Any] | None:
        return self._result
