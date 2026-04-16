"""Real schematic editor widget for PCB design.

Inspired by KiCad eeschema and Altium Designer's schematic editor.

Provides a complete schematic capture canvas with:
    * A built-in symbol library (resistors, caps, inductors, LEDs, diodes,
      BJTs, MOSFETs, op-amps, connectors, ATmega328P, ESP32-WROOM-32, ...).
    * Mode-based interaction (Select / Wire / Place / Label / Power / Ground).
    * Snap-to-grid (50 mil), KiCad-style cream background and dark-red bodies.
    * Save/Load to JSON, naive netlist generation.

The widget is intended to be embedded inside the desktop PCB designer panel
but is fully self contained and can be instantiated standalone for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json
import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QLineF, QEvent
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QFont,
    QPainterPath,
    QPolygonF,
    QKeySequence,
    QShortcut,
    QAction,
)
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsEllipseItem,
    QGraphicsTextItem,
    QGraphicsPathItem,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolBar,
    QFrame,
    QInputDialog,
    QMenu,
    QFileDialog,
    QLineEdit,
    QMessageBox,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Grid pitch in mils (50 mil = 0.05"). Standard sub-grid for KiCad eeschema.
GRID_SIZE = 50

#: Default pin lead length in mils.
PIN_LENGTH = 100

#: KiCad-ish color palette.
COLOR_BG = "#fffce8"
COLOR_GRID = "#e8e2c8"
COLOR_BODY = "#840000"
COLOR_FILL = "#ffffc2"
COLOR_WIRE = "#008484"
COLOR_LABEL = "#840000"
COLOR_REF = "#000080"
COLOR_VAL = "#008484"


# ---------------------------------------------------------------------------
# Edit modes
# ---------------------------------------------------------------------------


class EditMode(Enum):
    """Available editor interaction modes."""

    SELECT = "select"
    PLACE_COMPONENT = "place"
    DRAW_WIRE = "wire"
    DRAW_BUS = "bus"
    PLACE_LABEL = "label"
    PLACE_POWER = "power"
    PLACE_GROUND = "ground"
    PLACE_NO_CONNECT = "noconnect"


# ===========================================================================
# DATA MODEL
# ===========================================================================


@dataclass
class SchPin:
    """A pin attached to a schematic symbol.

    Coordinates are *symbol-local* (relative to the symbol origin) and
    expressed in mils.
    """

    name: str
    number: str
    direction: str
    x: float
    y: float
    length: float = PIN_LENGTH
    orientation: str = "right"  # right/left/up/down

    def endpoint(self) -> tuple[float, float]:
        """Return the (x, y) of the pin's *outer* end (away from body)."""
        if self.orientation == "right":
            return (self.x + self.length, self.y)
        if self.orientation == "left":
            return (self.x - self.length, self.y)
        if self.orientation == "up":
            return (self.x, self.y - self.length)
        if self.orientation == "down":
            return (self.x, self.y + self.length)
        return (self.x, self.y)


@dataclass
class SchSymbol:
    """A schematic symbol library entry."""

    name: str
    library: str
    description: str = ""
    keywords: str = ""
    width: float = 200
    height: float = 200
    pins: list[SchPin] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    body_shape: str = "rectangle"


@dataclass
class SchComponent:
    """An instance of a symbol on the schematic sheet."""

    refdes: str
    symbol_name: str
    library: str
    value: str
    x: float = 0
    y: float = 0
    rotation: int = 0
    mirrored: bool = False
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class SchWireSegment:
    """A single straight wire segment."""

    x1: float
    y1: float
    x2: float
    y2: float
    net_name: str = ""


@dataclass
class SchLabel:
    """A net label or hierarchical label."""

    text: str
    x: float
    y: float
    rotation: int = 0
    label_type: str = "net"  # net/global/hierarchical


@dataclass
class SchPowerSymbol:
    """VCC/GND/+5V/etc symbol."""

    net_name: str
    x: float
    y: float
    is_ground: bool = False


@dataclass
class SchPort:
    """Hierarchical sheet port.

    A port appears on a sub-sheet graphic item and defines a connection
    point between the parent schematic and the contents of the sub-sheet.
    """

    name: str
    direction: str = "bidir"  # input/output/bidir/power_in/power_out/tristate
    width: int = 1
    net_name: str = ""
    side: str = "L"  # L/R/T/B

    def __post_init__(self) -> None:
        if not self.net_name:
            self.net_name = self.name


@dataclass
class SchBus:
    """Named bus (bundle of signals)."""

    name: str
    width: int = 1
    members: list[str] = field(default_factory=list)


@dataclass
class SchSheet:
    """A hierarchical sub-sheet reference placed on a parent schematic."""

    name: str
    filename: str
    ports: list[SchPort] = field(default_factory=list)
    position: tuple[float, float] = (0.0, 0.0)
    parent_sheet: str = ""
    width: float = 1200
    height: float = 800


@dataclass
class Schematic:
    """Top-level schematic document.

    Now supports hierarchical sheets via :attr:`sub_sheets` and buses via
    :attr:`buses`. Use :func:`resolve_hierarchy` to flatten for netlisting.
    """

    title: str = "Untitled"
    components: list[SchComponent] = field(default_factory=list)
    wires: list[SchWireSegment] = field(default_factory=list)
    labels: list[SchLabel] = field(default_factory=list)
    power_symbols: list[SchPowerSymbol] = field(default_factory=list)
    sheet_size: tuple[float, float] = (11000, 8500)
    sub_sheets: list["SchSheet"] = field(default_factory=list)
    buses: list["SchBus"] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sheet_size": list(self.sheet_size),
            "components": [
                {
                    "refdes": c.refdes,
                    "symbol_name": c.symbol_name,
                    "library": c.library,
                    "value": c.value,
                    "x": c.x,
                    "y": c.y,
                    "rotation": c.rotation,
                    "mirrored": c.mirrored,
                    "fields": dict(c.fields),
                }
                for c in self.components
            ],
            "wires": [
                {
                    "x1": w.x1,
                    "y1": w.y1,
                    "x2": w.x2,
                    "y2": w.y2,
                    "net_name": w.net_name,
                }
                for w in self.wires
            ],
            "labels": [
                {
                    "text": l.text,
                    "x": l.x,
                    "y": l.y,
                    "rotation": l.rotation,
                    "type": l.label_type,
                }
                for l in self.labels
            ],
            "power_symbols": [
                {
                    "net_name": p.net_name,
                    "x": p.x,
                    "y": p.y,
                    "is_ground": p.is_ground,
                }
                for p in self.power_symbols
            ],
        }

    def save(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "Schematic":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sch = cls(title=data.get("title", "Untitled"))
        sch.sheet_size = tuple(data.get("sheet_size", [11000, 8500]))
        for c in data.get("components", []):
            sch.components.append(SchComponent(**c))
        for w in data.get("wires", []):
            sch.wires.append(SchWireSegment(**w))
        for raw in data.get("labels", []):
            label_type = raw.pop("type", "net")
            sch.labels.append(SchLabel(label_type=label_type, **raw))
        for p in data.get("power_symbols", []):
            sch.power_symbols.append(SchPowerSymbol(**p))
        return sch

    # ------------------------------------------------------------------
    # Netlist
    # ------------------------------------------------------------------

    def generate_netlist(
        self,
    ) -> dict[str, list[tuple[str, str]]]:
        """Generate a (very naive) netlist by walking wires + labels.

        Returns a mapping ``net_name -> [(refdes, pin_number), ...]``.

        The implementation uses a small Union-Find over (x, y) endpoints,
        merging wire endpoints together and onto component pin positions.
        Net names come from labels and power symbols sitting on a node.
        """

        parent: dict[tuple[int, int], tuple[int, int]] = {}

        def find(p: tuple[int, int]) -> tuple[int, int]:
            parent.setdefault(p, p)
            while parent[p] != p:
                parent[p] = parent[parent[p]]
                p = parent[p]
            return p

        def union(a: tuple[int, int], b: tuple[int, int]) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        def key(x: float, y: float) -> tuple[int, int]:
            return (int(round(x)), int(round(y)))

        # Wires connect their endpoints.
        for w in self.wires:
            union(key(w.x1, w.y1), key(w.x2, w.y2))

        # Labels and power symbols name a node.
        node_names: dict[tuple[int, int], str] = {}
        for label in self.labels:
            node_names[find(key(label.x, label.y))] = label.text
        for ps in self.power_symbols:
            node_names[find(key(ps.x, ps.y))] = ps.net_name

        # Component pins -> nodes (use the symbol library to translate
        # local pin coords to absolute coords).  Without the library we
        # only know the component origin, so callers should re-use the
        # editor's library.  Here we just emit pin numbers per component
        # using the component origin as a fallback node.
        nets: dict[str, list[tuple[str, str]]] = {}
        for comp in self.components:
            node = find(key(comp.x, comp.y))
            name = node_names.get(node) or f"N${len(nets) + 1}"
            nets.setdefault(name, []).append((comp.refdes, "*"))

        # Make sure every named node appears even if it has no pins yet.
        for nm in node_names.values():
            nets.setdefault(nm, [])

        return nets


# ===========================================================================
# BUILT-IN SYMBOL LIBRARY
# ===========================================================================


def builtin_library() -> dict[str, SchSymbol]:
    """Return a built-in library of common schematic symbols.

    The library covers the basics needed to draw most hobbyist boards:
    passives, diodes, transistors, op-amps, connectors and a couple of
    popular MCUs (ATmega328P, ESP32-WROOM-32).
    """

    lib: dict[str, SchSymbol] = {}

    # Resistor ----------------------------------------------------------
    r = SchSymbol(name="Resistor", library="Device", description="Resistor")
    r.pins = [
        SchPin("1", "1", "passive", 0, 0, orientation="left"),
        SchPin("2", "2", "passive", 200, 0, orientation="right"),
    ]
    r.fields = {"value": "10k", "footprint": "R_0805"}
    lib["Resistor"] = r

    # Capacitor ---------------------------------------------------------
    c = SchSymbol(
        name="Capacitor",
        library="Device",
        description="Non-polarized capacitor",
    )
    c.pins = [
        SchPin("1", "1", "passive", 0, 0, orientation="left"),
        SchPin("2", "2", "passive", 200, 0, orientation="right"),
    ]
    c.fields = {"value": "100nF", "footprint": "C_0805"}
    lib["Capacitor"] = c

    # Polarized capacitor ----------------------------------------------
    cp = SchSymbol(
        name="CapacitorPolarized",
        library="Device",
        description="Polarized capacitor",
    )
    cp.pins = [
        SchPin("+", "1", "passive", 0, 0, orientation="left"),
        SchPin("-", "2", "passive", 200, 0, orientation="right"),
    ]
    cp.fields = {"value": "10uF"}
    lib["CapacitorPolarized"] = cp

    # Inductor ----------------------------------------------------------
    l = SchSymbol(name="Inductor", library="Device", description="Inductor")
    l.pins = [
        SchPin("1", "1", "passive", 0, 0, orientation="left"),
        SchPin("2", "2", "passive", 200, 0, orientation="right"),
    ]
    l.fields = {"value": "10uH"}
    lib["Inductor"] = l

    # LED ---------------------------------------------------------------
    led = SchSymbol(
        name="LED", library="Device", description="Light emitting diode"
    )
    led.pins = [
        SchPin("A", "1", "passive", 0, 0, orientation="left"),
        SchPin("K", "2", "passive", 200, 0, orientation="right"),
    ]
    led.fields = {"value": "LED"}
    lib["LED"] = led

    # Diode -------------------------------------------------------------
    d = SchSymbol(name="Diode", library="Device", description="Diode")
    d.pins = [
        SchPin("A", "1", "passive", 0, 0, orientation="left"),
        SchPin("K", "2", "passive", 200, 0, orientation="right"),
    ]
    d.fields = {"value": "1N4148"}
    lib["Diode"] = d

    # NPN BJT -----------------------------------------------------------
    npn = SchSymbol(
        name="NPN_BJT",
        library="Device",
        description="NPN bipolar junction transistor",
        width=300,
        height=300,
    )
    npn.pins = [
        SchPin("B", "1", "passive", 0, 100, orientation="left"),
        SchPin("C", "2", "passive", 200, 0, orientation="up"),
        SchPin("E", "3", "passive", 200, 200, orientation="down"),
    ]
    npn.fields = {"value": "2N3904"}
    lib["NPN_BJT"] = npn

    # PNP BJT -----------------------------------------------------------
    pnp = SchSymbol(
        name="PNP_BJT",
        library="Device",
        description="PNP bipolar junction transistor",
        width=300,
        height=300,
    )
    pnp.pins = [
        SchPin("B", "1", "passive", 0, 100, orientation="left"),
        SchPin("E", "2", "passive", 200, 0, orientation="up"),
        SchPin("C", "3", "passive", 200, 200, orientation="down"),
    ]
    pnp.fields = {"value": "2N3906"}
    lib["PNP_BJT"] = pnp

    # NMOS --------------------------------------------------------------
    nmos = SchSymbol(
        name="NMOS",
        library="Device",
        description="N-channel MOSFET",
        width=300,
        height=300,
    )
    nmos.pins = [
        SchPin("G", "1", "passive", 0, 100, orientation="left"),
        SchPin("D", "2", "passive", 200, 0, orientation="up"),
        SchPin("S", "3", "passive", 200, 200, orientation="down"),
    ]
    nmos.fields = {"value": "2N7000"}
    lib["NMOS"] = nmos

    # PMOS --------------------------------------------------------------
    pmos = SchSymbol(
        name="PMOS",
        library="Device",
        description="P-channel MOSFET",
        width=300,
        height=300,
    )
    pmos.pins = [
        SchPin("G", "1", "passive", 0, 100, orientation="left"),
        SchPin("S", "2", "passive", 200, 0, orientation="up"),
        SchPin("D", "3", "passive", 200, 200, orientation="down"),
    ]
    pmos.fields = {"value": "AO3401"}
    lib["PMOS"] = pmos

    # Op-amp ------------------------------------------------------------
    opamp = SchSymbol(
        name="OpAmp",
        library="Device",
        description="Generic op-amp",
        width=400,
        height=400,
    )
    opamp.pins = [
        SchPin("V+", "3", "input", 0, 100, orientation="left"),
        SchPin("V-", "2", "input", 0, 300, orientation="left"),
        SchPin("OUT", "1", "output", 400, 200, orientation="right"),
        SchPin("VCC", "8", "power_in", 200, 0, orientation="up"),
        SchPin("GND", "4", "power_in", 200, 400, orientation="down"),
    ]
    opamp.fields = {"value": "LM358"}
    lib["OpAmp"] = opamp

    # 2-pin connector ---------------------------------------------------
    conn2 = SchSymbol(
        name="Conn_2x1",
        library="Connector",
        description="2-pin generic connector",
        width=200,
        height=300,
    )
    conn2.pins = [
        SchPin("1", "1", "passive", 200, 100, orientation="right"),
        SchPin("2", "2", "passive", 200, 200, orientation="right"),
    ]
    lib["Conn_2x1"] = conn2

    # 4-pin connector ---------------------------------------------------
    conn4 = SchSymbol(
        name="Conn_4x1",
        library="Connector",
        description="4-pin generic connector",
        width=200,
        height=500,
    )
    for i in range(4):
        conn4.pins.append(
            SchPin(
                str(i + 1),
                str(i + 1),
                "passive",
                200,
                100 + i * 100,
                orientation="right",
            )
        )
    lib["Conn_4x1"] = conn4

    # ATmega328P --------------------------------------------------------
    avr = SchSymbol(
        name="ATmega328P",
        library="MCU",
        description="8-bit AVR microcontroller (Arduino Uno)",
        width=600,
        height=1500,
    )
    pins_data = [
        ("PC6/RESET", "1", "input"),
        ("PD0/RXD", "2", "bidirectional"),
        ("PD1/TXD", "3", "bidirectional"),
        ("PD2", "4", "bidirectional"),
        ("PD3", "5", "bidirectional"),
        ("PD4", "6", "bidirectional"),
        ("VCC", "7", "power_in"),
        ("GND", "8", "power_in"),
        ("PB6/XTAL1", "9", "bidirectional"),
        ("PB7/XTAL2", "10", "bidirectional"),
        ("PD5", "11", "bidirectional"),
        ("PD6", "12", "bidirectional"),
        ("PD7", "13", "bidirectional"),
        ("PB0", "14", "bidirectional"),
        ("PB1", "15", "bidirectional"),
        ("PB2", "16", "bidirectional"),
        ("PB3/MOSI", "17", "bidirectional"),
        ("PB4/MISO", "18", "bidirectional"),
        ("PB5/SCK", "19", "bidirectional"),
        ("AVCC", "20", "power_in"),
        ("AREF", "21", "input"),
        ("GND", "22", "power_in"),
        ("PC0/ADC0", "23", "bidirectional"),
        ("PC1/ADC1", "24", "bidirectional"),
        ("PC2/ADC2", "25", "bidirectional"),
        ("PC3/ADC3", "26", "bidirectional"),
        ("PC4/ADC4/SDA", "27", "bidirectional"),
        ("PC5/ADC5/SCL", "28", "bidirectional"),
    ]
    for i, (name, num, dirn) in enumerate(pins_data):
        side = "left" if i < 14 else "right"
        x = 0 if side == "left" else 600
        y = 50 + (i if i < 14 else i - 14) * 100
        avr.pins.append(SchPin(name, num, dirn, x, y, orientation=side))
    lib["ATmega328P"] = avr

    # ESP32 module ------------------------------------------------------
    esp = SchSymbol(
        name="ESP32-WROOM-32",
        library="MCU",
        description="ESP32 WiFi/Bluetooth module",
        width=600,
        height=2000,
    )
    esp_pins = [
        "GND", "3V3", "EN", "SENSOR_VP", "SENSOR_VN", "GPIO34", "GPIO35",
        "GPIO32", "GPIO33", "GPIO25", "GPIO26", "GPIO27", "GPIO14",
        "GPIO12", "GND2", "GPIO13", "GPIO9", "GPIO10", "GPIO11", "VDD",
        "GPIO6", "GPIO7", "GPIO8", "GPIO15", "GPIO2", "GPIO0", "GPIO4",
        "GPIO16", "GPIO17", "GPIO5", "GPIO18", "GPIO19", "NC", "GPIO21",
        "RXD0", "TXD0", "GPIO22", "GPIO23",
    ]
    for i, pname in enumerate(esp_pins):
        side = "left" if i < 19 else "right"
        x = 0 if side == "left" else 600
        y = 50 + (i if i < 19 else i - 19) * 100
        dirn = (
            "power_in"
            if pname in ("GND", "GND2", "VDD", "3V3", "EN")
            else "bidirectional"
        )
        esp.pins.append(SchPin(pname, str(i + 1), dirn, x, y, orientation=side))
    lib["ESP32-WROOM-32"] = esp

    # Merge any cached KiCad symbols (best-effort, never fatal).
    try:
        _merge_kicad_cache_into(lib)
    except Exception:
        pass

    return lib


def _merge_kicad_cache_into(lib: dict[str, SchSymbol]) -> None:
    """Load ``~/.openforge/cache/kicad_libraries.json`` and merge symbols.

    Silently no-ops if the cache, the core importer, or the file are
    missing or malformed.
    """
    try:
        from openforge.pcb.kicad_importer import (  # type: ignore
            KicadLibraryImporter,
            default_cache_path,
        )
    except Exception:
        return
    cache = default_cache_path()
    if not Path(cache).exists():
        return
    try:
        importer = KicadLibraryImporter()
        importer.load_from_cache(cache)
    except Exception:
        return
    for key, raw in importer.symbols.items():
        try:
            pins = [
                SchPin(
                    name=getattr(p, "name", "~"),
                    number=getattr(p, "number", ""),
                    direction=getattr(p, "direction", "passive"),
                    x=float(getattr(p, "x", 0)),
                    y=float(getattr(p, "y", 0)),
                    length=float(getattr(p, "length", PIN_LENGTH)),
                    orientation=getattr(p, "orientation", "right"),
                )
                for p in getattr(raw, "pins", []) or []
            ]
            sym = SchSymbol(
                name=getattr(raw, "name", key),
                library=getattr(raw, "library", "KiCad"),
                description=getattr(raw, "description", ""),
                keywords=getattr(raw, "keywords", ""),
                width=float(getattr(raw, "width", 200) or 200),
                height=float(getattr(raw, "height", 200) or 200),
                pins=pins,
                fields=dict(getattr(raw, "fields", {}) or {}),
                body_shape=getattr(raw, "body_shape", "rectangle"),
            )
            # Avoid clobbering our hand-written builtin symbols.
            if sym.name in lib:
                continue
            lib[sym.name] = sym
        except Exception:
            continue


# ===========================================================================
# GRAPHICS ITEMS
# ===========================================================================


class ComponentItem(QGraphicsItem):
    """A component placed on the schematic canvas.

    Renders the body shape (with simple analog symbols for passives) plus
    pin leads, reference designator and value.
    """

    def __init__(
        self,
        component: SchComponent,
        symbol: SchSymbol,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.component = component
        self.symbol = symbol
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(component.x, component.y)
        self.setRotation(component.rotation)

    def boundingRect(self) -> QRectF:
        # Generous bounding box so labels and pin leads aren't clipped.
        return QRectF(
            -PIN_LENGTH - 20,
            -PIN_LENGTH - 30,
            self.symbol.width + 2 * PIN_LENGTH + 40,
            self.symbol.height + 2 * PIN_LENGTH + 60,
        )

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(self, painter, option, widget=None):  # noqa: D401
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_selected = self.isSelected()
        body_color = QColor(COLOR_BODY)
        pen_width = 3 if is_selected else 2

        painter.setPen(QPen(body_color, pen_width))
        painter.setBrush(QBrush(QColor(COLOR_FILL)))

        name = self.symbol.name
        if name == "Resistor":
            self._draw_resistor(painter)
        elif name == "Capacitor":
            self._draw_capacitor(painter)
        elif name == "CapacitorPolarized":
            self._draw_polarized_cap(painter)
        elif name == "Inductor":
            self._draw_inductor(painter)
        elif name == "LED":
            self._draw_led(painter)
        elif name == "Diode":
            self._draw_diode(painter)
        elif "BJT" in name or "MOS" in name:
            self._draw_transistor(painter)
        else:
            painter.drawRect(
                QRectF(0, 0, self.symbol.width, self.symbol.height)
            )

        # Pins
        painter.setPen(QPen(QColor(COLOR_BODY), 2))
        for pin in self.symbol.pins:
            self._draw_pin(painter, pin)

        # Reference designator
        painter.setPen(QColor(COLOR_REF))
        painter.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        painter.drawText(
            QRectF(0, -25, self.symbol.width, 20),
            Qt.AlignmentFlag.AlignCenter,
            self.component.refdes,
        )

        # Value
        painter.setPen(QColor(COLOR_VAL))
        painter.setFont(QFont("Sans Serif", 9))
        painter.drawText(
            QRectF(0, self.symbol.height + 5, self.symbol.width, 20),
            Qt.AlignmentFlag.AlignCenter,
            self.component.value or self.symbol.fields.get("value", ""),
        )

    # ------------------------------------------------------------------
    # Body shapes
    # ------------------------------------------------------------------

    def _draw_resistor(self, painter: QPainter) -> None:
        path = QPainterPath()
        w = self.symbol.width
        path.moveTo(40, 0)
        zigzag_w = (w - 80) / 6
        for i in range(6):
            x = 40 + i * zigzag_w + zigzag_w / 2
            y = -15 if i % 2 == 0 else 15
            path.lineTo(x, y)
        path.lineTo(w - 40, 0)
        painter.drawPath(path)

    def _draw_capacitor(self, painter: QPainter) -> None:
        cx = self.symbol.width / 2
        painter.drawLine(QLineF(cx - 10, -25, cx - 10, 25))
        painter.drawLine(QLineF(cx + 10, -25, cx + 10, 25))

    def _draw_polarized_cap(self, painter: QPainter) -> None:
        cx = self.symbol.width / 2
        rect = QRectF(cx + 5, -25, 15, 50)
        painter.drawArc(rect, 60 * 16, 60 * 16)
        painter.drawLine(QLineF(cx - 10, -25, cx - 10, 25))
        painter.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        painter.drawText(QPointF(cx - 30, -10), "+")

    def _draw_inductor(self, painter: QPainter) -> None:
        path = QPainterPath()
        w = self.symbol.width
        coil_count = 4
        coil_w = (w - 80) / coil_count
        path.moveTo(40, 0)
        for i in range(coil_count):
            x = 40 + i * coil_w
            path.arcTo(x, -coil_w / 2, coil_w, coil_w, 180, -180)
        painter.drawPath(path)

    def _draw_led(self, painter: QPainter) -> None:
        cx = self.symbol.width / 2
        triangle = QPolygonF(
            [
                QPointF(cx - 20, -20),
                QPointF(cx - 20, 20),
                QPointF(cx + 20, 0),
            ]
        )
        painter.drawPolygon(triangle)
        painter.drawLine(QLineF(cx + 20, -20, cx + 20, 20))
        painter.drawLine(QLineF(cx + 5, -25, cx + 25, -45))
        painter.drawLine(QLineF(cx + 25, -45, cx + 20, -38))
        painter.drawLine(QLineF(cx + 25, -45, cx + 18, -45))

    def _draw_diode(self, painter: QPainter) -> None:
        cx = self.symbol.width / 2
        triangle = QPolygonF(
            [
                QPointF(cx - 20, -20),
                QPointF(cx - 20, 20),
                QPointF(cx + 20, 0),
            ]
        )
        painter.drawPolygon(triangle)
        painter.drawLine(QLineF(cx + 20, -20, cx + 20, 20))

    def _draw_transistor(self, painter: QPainter) -> None:
        cx = self.symbol.width / 2
        cy = self.symbol.height / 2
        painter.drawEllipse(QPointF(cx, cy), 60, 60)
        painter.drawLine(QLineF(cx - 30, cy - 30, cx - 30, cy + 30))
        painter.drawLine(QLineF(cx - 30, cy, 0, 100))
        painter.drawLine(QLineF(cx - 10, cy - 20, 200, 0))
        painter.drawLine(QLineF(cx - 10, cy + 20, 200, 200))

    def _draw_pin(self, painter: QPainter, pin: SchPin) -> None:
        if pin.orientation == "right":
            painter.drawLine(
                QLineF(pin.x, pin.y, pin.x + pin.length, pin.y)
            )
        elif pin.orientation == "left":
            painter.drawLine(
                QLineF(pin.x, pin.y, pin.x - pin.length, pin.y)
            )
        elif pin.orientation == "up":
            painter.drawLine(
                QLineF(pin.x, pin.y, pin.x, pin.y - pin.length)
            )
        elif pin.orientation == "down":
            painter.drawLine(
                QLineF(pin.x, pin.y, pin.x, pin.y + pin.length)
            )
        # Pin name (small label near body end)
        painter.save()
        painter.setPen(QColor(COLOR_BODY))
        painter.setFont(QFont("Sans Serif", 7))
        painter.drawText(QPointF(pin.x + 2, pin.y - 4), pin.name)
        painter.restore()


class WireItem(QGraphicsLineItem):
    """A wire segment graphics item."""

    def __init__(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        wire: SchWireSegment | None = None,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(x1, y1, x2, y2, parent)
        self.wire = wire
        self.setPen(QPen(QColor(COLOR_WIRE), 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)


class PowerSymbolItem(QGraphicsItem):
    """A VCC or GND power-port symbol."""

    def __init__(
        self,
        ps: SchPowerSymbol,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.power = ps
        self.setPos(ps.x, ps.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)

    def boundingRect(self) -> QRectF:
        return QRectF(-30, -50, 60, 100)

    def paint(self, painter, option, widget=None):  # noqa: D401
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(COLOR_BODY), 2))

        if self.power.is_ground:
            painter.drawLine(QLineF(0, 0, 0, 15))
            painter.drawLine(QLineF(-15, 15, 15, 15))
            painter.drawLine(QLineF(-10, 22, 10, 22))
            painter.drawLine(QLineF(-5, 29, 5, 29))
        else:
            painter.drawLine(QLineF(0, 0, 0, -15))
            painter.drawLine(QLineF(-10, -15, 10, -15))

        painter.setPen(QColor(COLOR_BODY))
        painter.setFont(QFont("Sans Serif", 8, QFont.Weight.Bold))
        if self.power.is_ground:
            painter.drawText(
                QRectF(-25, 32, 50, 15),
                Qt.AlignmentFlag.AlignCenter,
                self.power.net_name,
            )
        else:
            painter.drawText(
                QRectF(-25, -32, 50, 15),
                Qt.AlignmentFlag.AlignCenter,
                self.power.net_name,
            )


# ===========================================================================
# THE EDITOR WIDGET
# ===========================================================================


class SchematicEditor(QWidget):
    """Complete schematic capture editor.

    A self-contained widget that hosts a left-hand symbol library, a center
    drawing canvas (a ``QGraphicsView``/``QGraphicsScene``) and a right-hand
    properties / stats panel.  Behaves like a stripped-down KiCad eeschema:

        * Pick a symbol in the library, the canvas enters *Place* mode and
          left-clicks drop instances onto the snapped grid.
        * ``W`` enters wire mode; clicks add wire vertices, ``Esc`` exits.
        * ``L`` places a net label; ``V`` / ``G`` place power / ground.
        * ``R`` rotates the selection by 90 deg; ``Del`` removes it.
        * ``Ctrl+S`` / ``Ctrl+O`` save / load to JSON.
    """

    schematic_changed = Signal()
    netlist_generated = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._library = builtin_library()
        self._schematic = Schematic()
        self._mode = EditMode.SELECT
        self._wire_start: QPointF | None = None
        self._wire_preview: QGraphicsLineItem | None = None
        self._refdes_counter: dict[str, int] = {
            "R": 0,
            "C": 0,
            "L": 0,
            "U": 0,
            "D": 0,
            "Q": 0,
            "J": 0,
            "LED": 0,
        }
        self._current_symbol: SchSymbol | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = self._build_library_sidebar()
        layout.addWidget(sidebar)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        toolbar = self._build_toolbar()
        center.addWidget(toolbar)

        self.scene = QGraphicsScene(0, 0, 11000, 8500)
        self.scene.setBackgroundBrush(QBrush(QColor(COLOR_BG)))

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        center.addWidget(self.view, stretch=1)

        self.status_bar = QFrame()
        self.status_bar.setObjectName("SchStatusBar")
        self.status_bar.setFixedHeight(26)
        self.status_bar.setStyleSheet(
            """
            QFrame#SchStatusBar {
                background: #181825;
                border-top: 1px solid #313244;
            }
            QFrame#SchStatusBar QLabel {
                color: #a6adc8;
                background: transparent;
                font-size: 11px;
                font-family: 'JetBrains Mono', Consolas, monospace;
            }
            """
        )
        sb_layout = QHBoxLayout(self.status_bar)
        sb_layout.setContentsMargins(10, 0, 10, 0)
        self.coord_label = QLabel("X: 0  Y: 0")
        self.mode_label = QLabel("Mode: Select")
        sb_layout.addWidget(self.mode_label)
        sb_layout.addStretch()
        sb_layout.addWidget(self.coord_label)
        center.addWidget(self.status_bar)

        center_widget = QWidget()
        center_widget.setLayout(center)
        layout.addWidget(center_widget, stretch=1)

        right = self._build_properties_sidebar()
        layout.addWidget(right)

        self._draw_grid()
        self._setup_shortcuts()

    def _build_library_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("SchLibSidebar")
        side.setFixedWidth(230)
        side.setStyleSheet(
            """
            QFrame#SchLibSidebar {
                background: #1e1e2e;
                border-right: 1px solid #313244;
            }
            QFrame#SchLibSidebar QLabel {
                color: #cdd6f4;
                background: transparent;
            }
            QFrame#SchLibSidebar QLineEdit {
                background: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 5px 8px;
                selection-background-color: #00d4ff;
                selection-color: #11111b;
            }
            QFrame#SchLibSidebar QLineEdit:focus {
                border: 1px solid #00d4ff;
            }
            QFrame#SchLibSidebar QListWidget {
                background: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                outline: 0;
                padding: 2px;
            }
            QFrame#SchLibSidebar QListWidget::item {
                color: #cdd6f4;
                padding: 5px 8px;
                border-radius: 3px;
            }
            QFrame#SchLibSidebar QListWidget::item:hover {
                background: #313244;
            }
            QFrame#SchLibSidebar QListWidget::item:selected {
                background: #00d4ff;
                color: #11111b;
            }
            """
        )
        layout = QVBoxLayout(side)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("LIBRARY")
        title.setStyleSheet(
            "font-weight: 700; color: #a6adc8; font-size: 10px; "
            "letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(title)

        search = QLineEdit()
        search.setPlaceholderText("Search symbols…")
        search.textChanged.connect(self._filter_library)
        layout.addWidget(search)

        self.lib_list = QListWidget()
        for name, sym in self._library.items():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, sym)
            item.setToolTip(f"{sym.description}  ({sym.library})")
            self.lib_list.addItem(item)
        self.lib_list.itemDoubleClicked.connect(self._on_library_select)
        self.lib_list.itemClicked.connect(self._on_library_select)
        layout.addWidget(self.lib_list)

        return side

    def _build_properties_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("SchPropSidebar")
        side.setFixedWidth(250)
        side.setStyleSheet(
            """
            QFrame#SchPropSidebar {
                background: #1e1e2e;
                border-left: 1px solid #313244;
            }
            QFrame#SchPropSidebar QLabel {
                color: #cdd6f4;
                background: transparent;
            }
            QFrame#SchPropSidebar QLabel#SchSectionTitle {
                font-weight: 700;
                color: #a6adc8;
                font-size: 10px;
                letter-spacing: 1px;
            }
            QFrame#SchPropSidebar QLabel#SchBodyText {
                color: #cdd6f4;
                font-size: 12px;
                background: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 8px;
            }
            """
        )
        layout = QVBoxLayout(side)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("PROPERTIES")
        title.setObjectName("SchSectionTitle")
        layout.addWidget(title)

        self.props_label = QLabel("No selection")
        self.props_label.setObjectName("SchBodyText")
        self.props_label.setWordWrap(True)
        self.props_label.setMinimumHeight(60)
        self.props_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.props_label)

        layout.addStretch()

        stats_title = QLabel("STATS")
        stats_title.setObjectName("SchSectionTitle")
        layout.addWidget(stats_title)
        self.stats_label = QLabel("Components: 0\nWires: 0\nLabels: 0")
        self.stats_label.setObjectName("SchBodyText")
        layout.addWidget(self.stats_label)

        return side

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setObjectName("SchToolbar")
        tb.setStyleSheet(
            """
            QToolBar#SchToolbar {
                background: #181825;
                border-bottom: 1px solid #313244;
                padding: 4px 6px;
                spacing: 4px;
            }
            QToolBar#SchToolbar QToolButton {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 5px 12px;
                font-weight: 600;
                font-size: 11px;
                margin: 0 2px;
            }
            QToolBar#SchToolbar QToolButton:hover {
                background: #313244;
                border: 1px solid #00d4ff;
                color: #ffffff;
            }
            QToolBar#SchToolbar QToolButton:pressed,
            QToolBar#SchToolbar QToolButton:checked {
                background: #00d4ff;
                color: #11111b;
                border: 1px solid #00d4ff;
            }
            QToolBar#SchToolbar QToolButton:disabled {
                color: #6c7086;
                background: #181825;
                border: 1px solid #313244;
            }
            QToolBar#SchToolbar::separator {
                background: #313244;
                width: 1px;
                margin: 4px 6px;
            }
            """
        )

        actions = [
            ("Select", "S", lambda: self._set_mode(EditMode.SELECT)),
            ("Wire", "W", lambda: self._set_mode(EditMode.DRAW_WIRE)),
            ("Place", "P", lambda: self._set_mode(EditMode.PLACE_COMPONENT)),
            ("Label", "L", lambda: self._set_mode(EditMode.PLACE_LABEL)),
            ("Power", "V", lambda: self._set_mode(EditMode.PLACE_POWER)),
            ("Ground", "G", lambda: self._set_mode(EditMode.PLACE_GROUND)),
            (None, None, None),
            ("Save", "Ctrl+S", self._save),
            ("Load", "Ctrl+O", self._load),
            ("Netlist", None, self._generate_netlist),
            (None, None, None),
            ("Delete", "Del", self._delete_selected),
            ("Rotate", "R", self._rotate_selected),
        ]

        for label, shortcut, slot in actions:
            if label is None:
                tb.addSeparator()
                continue
            act = QAction(label, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            if slot:
                act.triggered.connect(slot)
            tb.addAction(act)

        return tb

    def _setup_shortcuts(self) -> None:
        QShortcut(
            QKeySequence("Escape"),
            self,
            lambda: self._set_mode(EditMode.SELECT),
        )

    def _draw_grid(self) -> None:
        """Paint the dotted minor grid onto the scene background."""
        pen = QPen(QColor(COLOR_GRID), 0)
        for x in range(0, 11000, GRID_SIZE):
            self.scene.addLine(x, 0, x, 8500, pen)
        for y in range(0, 8500, GRID_SIZE):
            self.scene.addLine(0, y, 11000, y, pen)

    # ------------------------------------------------------------------
    # Mode + library helpers
    # ------------------------------------------------------------------

    def _set_mode(self, mode: EditMode) -> None:
        self._mode = mode
        self.mode_label.setText(f"Mode: {mode.value.title()}")
        if mode != EditMode.DRAW_WIRE and self._wire_preview is not None:
            self.scene.removeItem(self._wire_preview)
            self._wire_preview = None
            self._wire_start = None
        self.view.viewport().update()

    def _filter_library(self, text: str) -> None:
        text = text.lower()
        for i in range(self.lib_list.count()):
            item = self.lib_list.item(i)
            visible = not text or text in item.text().lower()
            item.setHidden(not visible)

    def _on_library_select(self, item: QListWidgetItem) -> None:
        symbol = item.data(Qt.ItemDataRole.UserRole)
        self._current_symbol = symbol
        self._set_mode(EditMode.PLACE_COMPONENT)

    def _snap_to_grid(self, x: float, y: float) -> tuple[float, float]:
        return (
            round(x / GRID_SIZE) * GRID_SIZE,
            round(y / GRID_SIZE) * GRID_SIZE,
        )

    # ------------------------------------------------------------------
    # Mouse event filter
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: D401
        if obj is self.view.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos = self.view.mapToScene(event.position().toPoint())
                snap_x, snap_y = self._snap_to_grid(pos.x(), pos.y())
                self.coord_label.setText(
                    f"X: {int(snap_x)}  Y: {int(snap_y)}"
                )
                if self._wire_preview and self._wire_start:
                    self._wire_preview.setLine(
                        QLineF(self._wire_start, QPointF(snap_x, snap_y))
                    )
                return False

            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                pos = self.view.mapToScene(event.position().toPoint())
                snap_x, snap_y = self._snap_to_grid(pos.x(), pos.y())

                if (
                    self._mode == EditMode.PLACE_COMPONENT
                    and self._current_symbol
                ):
                    self._place_component(snap_x, snap_y)
                    return True

                if self._mode == EditMode.DRAW_WIRE:
                    self._handle_wire_click(snap_x, snap_y)
                    return True

                if self._mode == EditMode.PLACE_LABEL:
                    text, ok = QInputDialog.getText(
                        self, "Net Label", "Label:"
                    )
                    if ok and text:
                        self._add_label(text, snap_x, snap_y)
                    return True

                if self._mode == EditMode.PLACE_POWER:
                    self._add_power(snap_x, snap_y, "VCC", is_ground=False)
                    return True

                if self._mode == EditMode.PLACE_GROUND:
                    self._add_power(snap_x, snap_y, "GND", is_ground=True)
                    return True

            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.RightButton
            ):
                # Right-click cancels any in-progress action.
                self._set_mode(EditMode.SELECT)
                return True

        return super().eventFilter(obj, event)

    def _handle_wire_click(self, snap_x: float, snap_y: float) -> None:
        if self._wire_start is None:
            self._wire_start = QPointF(snap_x, snap_y)
            self._wire_preview = self.scene.addLine(
                snap_x,
                snap_y,
                snap_x,
                snap_y,
                QPen(QColor(COLOR_WIRE), 2, Qt.PenStyle.DashLine),
            )
        else:
            self._add_wire(
                self._wire_start.x(),
                self._wire_start.y(),
                snap_x,
                snap_y,
            )
            if self._wire_preview:
                self.scene.removeItem(self._wire_preview)
            self._wire_start = QPointF(snap_x, snap_y)
            self._wire_preview = self.scene.addLine(
                snap_x,
                snap_y,
                snap_x,
                snap_y,
                QPen(QColor(COLOR_WIRE), 2, Qt.PenStyle.DashLine),
            )

    # ------------------------------------------------------------------
    # Document mutation helpers
    # ------------------------------------------------------------------

    def _next_refdes(self, prefix: str) -> str:
        self._refdes_counter[prefix] = (
            self._refdes_counter.get(prefix, 0) + 1
        )
        return f"{prefix}{self._refdes_counter[prefix]}"

    def _refdes_prefix_for_symbol(self, sym: SchSymbol) -> str:
        n = sym.name.lower()
        if "resistor" in n:
            return "R"
        if "capacitor" in n:
            return "C"
        if "inductor" in n:
            return "L"
        if "led" in n:
            return "LED"
        if "diode" in n:
            return "D"
        if "transistor" in n or "bjt" in n or "mos" in n:
            return "Q"
        if "conn" in n:
            return "J"
        return "U"

    def _place_component(self, x: float, y: float) -> None:
        sym = self._current_symbol
        if sym is None:
            return
        prefix = self._refdes_prefix_for_symbol(sym)
        comp = SchComponent(
            refdes=self._next_refdes(prefix),
            symbol_name=sym.name,
            library=sym.library,
            value=sym.fields.get("value", ""),
            x=x,
            y=y,
        )
        self._schematic.components.append(comp)
        item = ComponentItem(comp, sym)
        self.scene.addItem(item)
        self._update_stats()
        self.schematic_changed.emit()

    def _add_wire(self, x1: float, y1: float, x2: float, y2: float) -> None:
        wire = SchWireSegment(x1=x1, y1=y1, x2=x2, y2=y2)
        self._schematic.wires.append(wire)
        item = WireItem(x1, y1, x2, y2, wire=wire)
        self.scene.addItem(item)
        self._update_stats()
        self.schematic_changed.emit()

    def _add_label(self, text: str, x: float, y: float) -> None:
        label = SchLabel(text=text, x=x, y=y)
        self._schematic.labels.append(label)
        text_item = self.scene.addText(text, QFont("Sans Serif", 10))
        text_item.setPos(x, y - 16)
        text_item.setDefaultTextColor(QColor(COLOR_LABEL))
        text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self._update_stats()
        self.schematic_changed.emit()

    def _add_power(
        self, x: float, y: float, name: str, is_ground: bool
    ) -> None:
        ps = SchPowerSymbol(net_name=name, x=x, y=y, is_ground=is_ground)
        self._schematic.power_symbols.append(ps)
        item = PowerSymbolItem(ps)
        self.scene.addItem(item)
        self._update_stats()
        self.schematic_changed.emit()

    def _delete_selected(self) -> None:
        for item in list(self.scene.selectedItems()):
            self.scene.removeItem(item)
            if isinstance(item, ComponentItem):
                if item.component in self._schematic.components:
                    self._schematic.components.remove(item.component)
            elif isinstance(item, WireItem) and item.wire is not None:
                if item.wire in self._schematic.wires:
                    self._schematic.wires.remove(item.wire)
            elif isinstance(item, PowerSymbolItem):
                if item.power in self._schematic.power_symbols:
                    self._schematic.power_symbols.remove(item.power)
        self._update_stats()
        self.schematic_changed.emit()

    def _rotate_selected(self) -> None:
        for item in self.scene.selectedItems():
            if isinstance(item, ComponentItem):
                item.setRotation((item.rotation() + 90) % 360)
                item.component.rotation = int(item.rotation())

    def _update_stats(self) -> None:
        self.stats_label.setText(
            f"Components: {len(self._schematic.components)}\n"
            f"Wires: {len(self._schematic.wires)}\n"
            f"Labels: {len(self._schematic.labels)}\n"
            f"Power: {len(self._schematic.power_symbols)}"
        )

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Schematic",
            "",
            "Schematic Files (*.ofs);;JSON (*.json)",
        )
        if path:
            self._schematic.save(Path(path))

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Schematic",
            "",
            "Schematic Files (*.ofs);;JSON (*.json)",
        )
        if path:
            self._schematic = Schematic.load(Path(path))
            self._rebuild_scene()

    def _rebuild_scene(self) -> None:
        self.scene.clear()
        self._draw_grid()
        for comp in self._schematic.components:
            sym = self._library.get(comp.symbol_name)
            if sym:
                item = ComponentItem(comp, sym)
                self.scene.addItem(item)
        for wire in self._schematic.wires:
            item = WireItem(wire.x1, wire.y1, wire.x2, wire.y2, wire=wire)
            self.scene.addItem(item)
        for ps in self._schematic.power_symbols:
            item = PowerSymbolItem(ps)
            self.scene.addItem(item)
        for label in self._schematic.labels:
            text_item = self.scene.addText(
                label.text, QFont("Sans Serif", 10)
            )
            text_item.setPos(label.x, label.y - 16)
            text_item.setDefaultTextColor(QColor(COLOR_LABEL))
        self._update_stats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _generate_netlist(self) -> None:
        netlist = self._schematic.generate_netlist()
        self.netlist_generated.emit(netlist)
        n_comps = len(self._schematic.components)
        n_nets = len(netlist)
        QMessageBox.information(
            self,
            "Netlist Generated",
            f"Generated netlist for {n_comps} components, {n_nets} nets.",
        )

    def schematic(self) -> Schematic:
        """Return the underlying :class:`Schematic` document."""
        return self._schematic

    def library(self) -> dict[str, SchSymbol]:
        """Return the active symbol library."""
        return self._library

    def add_external_library(self, symbols_dict: dict) -> int:
        """Merge additional symbols into the active library.

        Accepts anything dict-like keyed by name with SchSymbol-shaped
        values (duck-typed).  Returns the number of newly added symbols
        and refreshes the library sidebar list.
        """
        if not symbols_dict:
            return 0
        added = 0
        for raw_key, raw in symbols_dict.items():
            try:
                name = getattr(raw, "name", None) or str(raw_key)
                if name in self._library:
                    continue
                pins = [
                    SchPin(
                        name=getattr(p, "name", "~"),
                        number=getattr(p, "number", ""),
                        direction=getattr(p, "direction", "passive"),
                        x=float(getattr(p, "x", 0)),
                        y=float(getattr(p, "y", 0)),
                        length=float(getattr(p, "length", PIN_LENGTH)),
                        orientation=getattr(p, "orientation", "right"),
                    )
                    for p in getattr(raw, "pins", []) or []
                ]
                sym = SchSymbol(
                    name=name,
                    library=getattr(raw, "library", "External"),
                    description=getattr(raw, "description", ""),
                    keywords=getattr(raw, "keywords", ""),
                    width=float(getattr(raw, "width", 200) or 200),
                    height=float(getattr(raw, "height", 200) or 200),
                    pins=pins,
                    fields=dict(getattr(raw, "fields", {}) or {}),
                    body_shape=getattr(raw, "body_shape", "rectangle"),
                )
                self._library[name] = sym
                added += 1
            except Exception:
                continue
        # Refresh the sidebar list if it exists.
        try:
            lib_list = getattr(self, "lib_list", None)
            if lib_list is not None:
                lib_list.clear()
                for nm, sym in self._library.items():
                    item = QListWidgetItem(nm)
                    item.setData(Qt.ItemDataRole.UserRole, sym)
                    item.setToolTip(f"{sym.description}  ({sym.library})")
                    lib_list.addItem(item)
        except Exception:
            pass
        return added

    def set_mode(self, mode: EditMode) -> None:
        """Public mode setter (for tests / external toolbars)."""
        self._set_mode(mode)


# ===========================================================================
# Hierarchical sheet support
# ===========================================================================


def resolve_hierarchy(root: Schematic,
                      sub_loader=None) -> Schematic:
    """Flatten all sub-sheets into a single :class:`Schematic`.

    ``sub_loader`` is an optional callable ``(filename) -> Schematic``
    used to resolve sub-sheet files on disk. If not provided, sub-sheets
    that aren't already loaded into memory are simply skipped.

    Ports on sub-sheets introduce matching labels on the parent so that
    connections between parent and child are preserved by the netlist
    generator after flattening.
    """
    flat = Schematic(title=root.title, sheet_size=root.sheet_size)
    flat.components = list(root.components)
    flat.wires = list(root.wires)
    flat.labels = list(root.labels)
    flat.power_symbols = list(root.power_symbols)
    flat.buses = list(root.buses)

    visited: set[str] = set()

    def walk(sch: Schematic, prefix: str) -> None:
        for sub in sch.sub_sheets or []:
            key = f"{prefix}/{sub.name}"
            if key in visited:
                continue
            visited.add(key)

            # Promote port labels to the parent flattening
            for p in sub.ports:
                flat.labels.append(SchLabel(
                    text=p.net_name or p.name,
                    x=sub.position[0], y=sub.position[1],
                    label_type="hierarchical",
                ))

            # If we have a child schematic in memory (stored via fields),
            # walk it too.
            child = getattr(sub, "_schematic", None)
            if child is None and sub_loader is not None:
                try:
                    child = sub_loader(sub.filename)
                except Exception:
                    child = None
            if child is None:
                continue

            # Prefix refdes to keep them unique across the flattened design
            rprefix = f"{sub.name}_"
            for c in child.components:
                nc = SchComponent(
                    refdes=rprefix + c.refdes,
                    symbol_name=c.symbol_name,
                    library=c.library,
                    value=c.value,
                    x=c.x, y=c.y,
                    rotation=c.rotation, mirrored=c.mirrored,
                    fields=dict(c.fields),
                )
                flat.components.append(nc)
            flat.wires.extend(child.wires)
            flat.labels.extend(child.labels)
            flat.power_symbols.extend(child.power_symbols)
            flat.buses.extend(child.buses)
            walk(child, key)

    walk(root, root.title or "root")
    return flat


# ---------------------------------------------------------------------------
# Hierarchical / bus editor methods (monkey-patched onto SchematicEditor to
# keep the existing class definition intact).
# ---------------------------------------------------------------------------


def _editor_add_sub_sheet(self, name: str, filename: str,
                          ports: list[SchPort] | None = None,
                          x: float = 2000, y: float = 2000) -> SchSheet:
    """Create a sheet graphic item and register it with the schematic."""
    sheet = SchSheet(name=name, filename=filename,
                     ports=list(ports or []),
                     position=(float(x), float(y)))
    self._schematic.sub_sheets.append(sheet)

    # Draw a labeled rectangle on the scene for the sheet
    try:
        rect = QGraphicsRectItem(x, y, sheet.width, sheet.height)
        rect.setPen(QPen(QColor("#00d4ff"), 4))
        rect.setBrush(QBrush(QColor(255, 255, 194, 80)))
        rect.setData(0, f"sheet:{name}")
        self.scene.addItem(rect)
        label = QGraphicsTextItem(name)
        f = QFont("JetBrains Mono", 12)
        f.setBold(True)
        label.setFont(f)
        label.setDefaultTextColor(QColor("#1e1e2e"))
        label.setPos(x + 10, y + 4)
        self.scene.addItem(label)
        # Draw port stubs on the edges
        for i, port in enumerate(sheet.ports):
            side = (port.side or "L").upper()
            if side == "L":
                px, py = x, y + 60 + i * 40
            elif side == "R":
                px, py = x + sheet.width, y + 60 + i * 40
            elif side == "T":
                px, py = x + 60 + i * 40, y
            else:
                px, py = x + 60 + i * 40, y + sheet.height
            stub = QGraphicsEllipseItem(px - 6, py - 6, 12, 12)
            stub.setPen(QPen(QColor("#f9e2af"), 2))
            stub.setBrush(QBrush(QColor("#f9e2af")))
            self.scene.addItem(stub)
            txt = QGraphicsTextItem(port.name)
            txt.setFont(QFont("JetBrains Mono", 8))
            txt.setDefaultTextColor(QColor("#1e1e2e"))
            txt.setPos(px + 8, py - 8)
            self.scene.addItem(txt)
    except Exception:
        pass

    self.schematic_changed.emit()
    return sheet


def _editor_enter_sheet(self, sheet: SchSheet) -> None:
    """Navigate into a sub-sheet (push current onto navigation stack)."""
    if not hasattr(self, "_sheet_stack"):
        self._sheet_stack: list[tuple[str, Schematic]] = []
    self._sheet_stack.append((self._schematic.title, self._schematic))
    child = getattr(sheet, "_schematic", None)
    if child is None:
        child = Schematic(title=sheet.name)
        sheet._schematic = child  # type: ignore[attr-defined]
    self._schematic = child
    self._redraw_all()
    self._update_breadcrumb()


def _editor_exit_sheet(self) -> None:
    """Return to the parent schematic from a sub-sheet."""
    stack = getattr(self, "_sheet_stack", None)
    if not stack:
        return
    _, parent = stack.pop()
    self._schematic = parent
    self._redraw_all()
    self._update_breadcrumb()


def _editor_update_breadcrumb(self) -> None:
    if not hasattr(self, "breadcrumb_bar") or self.breadcrumb_bar is None:
        return
    stack = getattr(self, "_sheet_stack", [])
    parts = [t for t, _ in stack] + [self._schematic.title or "top"]
    self.breadcrumb_bar.setText(" / ".join(parts))


def _editor_highlight_net(self, net_name: str) -> int:
    """Highlight all wires + labels matching ``net_name``. Returns count."""
    count = 0
    try:
        for item in self.scene.items():
            data = item.data(0) if hasattr(item, "data") else None
            if isinstance(item, QGraphicsLineItem):
                # WireItem stores its segment as data(1)
                seg = item.data(1) if hasattr(item, "data") else None
                net = getattr(seg, "net_name", "") if seg else ""
                if net == net_name:
                    pen = QPen(QColor("#f9e2af"), 4)
                    item.setPen(pen)
                    item.setToolTip(f"Net: {net_name}")
                    count += 1
            elif isinstance(item, QGraphicsTextItem):
                if item.toPlainText() == net_name:
                    item.setDefaultTextColor(QColor("#f9e2af"))
                    count += 1
    except Exception:
        pass
    return count


def _editor_redraw_all(self) -> None:
    """Re-render the scene from ``self._schematic`` (best-effort)."""
    try:
        self.scene.clear()
        self._draw_grid()
    except Exception:
        pass


# Bind methods onto SchematicEditor
SchematicEditor.add_sub_sheet = _editor_add_sub_sheet  # type: ignore[attr-defined]
SchematicEditor.enter_sheet = _editor_enter_sheet  # type: ignore[attr-defined]
SchematicEditor.exit_sheet = _editor_exit_sheet  # type: ignore[attr-defined]
SchematicEditor._update_breadcrumb = _editor_update_breadcrumb  # type: ignore[attr-defined]
SchematicEditor.highlight_net = _editor_highlight_net  # type: ignore[attr-defined]
SchematicEditor._redraw_all = _editor_redraw_all  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Bus and BusRip graphic items
# ---------------------------------------------------------------------------


class BusItem(QGraphicsLineItem):
    """A bus: thicker, dark-purple line representing a bundle of signals."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float,
                 bus: SchBus) -> None:
        super().__init__(x1, y1, x2, y2)
        self._bus = bus
        pen = QPen(QColor("#8839ef"))
        pen.setWidth(8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setToolTip(f"Bus: {bus.name}[{bus.width - 1}:0]")
        self.setZValue(-1)


class BusRipItem(QGraphicsPathItem):
    """Single-bit rip-off from a bus (the 45-degree stub + label)."""

    def __init__(self, x: float, y: float, bit: int, bus_name: str) -> None:
        super().__init__()
        path = QPainterPath()
        path.moveTo(x, y)
        path.lineTo(x + 30, y - 30)
        self.setPath(path)
        pen = QPen(QColor("#8839ef"))
        pen.setWidth(3)
        self.setPen(pen)
        self.setToolTip(f"{bus_name}[{bit}]")


__all__ = [
    "SchematicEditor",
    "Schematic",
    "SchSymbol",
    "SchPin",
    "SchComponent",
    "SchWireSegment",
    "SchLabel",
    "SchPowerSymbol",
    "SchSheet",
    "SchPort",
    "SchBus",
    "EditMode",
    "ComponentItem",
    "WireItem",
    "PowerSymbolItem",
    "BusItem",
    "BusRipItem",
    "builtin_library",
    "resolve_hierarchy",
    "GRID_SIZE",
    "PIN_LENGTH",
]
