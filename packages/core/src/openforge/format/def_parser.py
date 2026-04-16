"""Comprehensive DEF (Design Exchange Format) parser.

A self-contained, regex-based parser for the LEF/DEF reference format used
by OpenROAD, OpenLane, Innovus and other physical design tools. Handles all
the major sections needed by the OpenForge layout viewer:

- DESIGN / UNITS / DIEAREA header
- ROW (placement rows)
- TRACKS (routing track definitions)
- COMPONENTS (placed/fixed standard cells and macros)
- PINS (top-level I/O pins with optional layer/placement info)
- NETS (signal nets with full ROUTED segments and via stitching)
- SPECIALNETS (power/ground stripes)

The parser is intentionally tolerant: malformed records are skipped rather
than aborting the parse, so partial DEF dumps from interrupted P&R runs
still produce useful data for the viewer.

Usage
-----
    from openforge.format.def_parser import parse_def
    design = parse_def("counter_routed.def")
    print(design.stats())
    print(f"{len(design.components)} cells, {len(design.nets)} nets")

The returned :class:`DefDesign` is a plain dataclass tree with helper
methods for region queries, density heatmaps, and pin lookup. It contains
no Qt or rendering dependencies, so it can be used from CLI tools, the
REST API, or unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DefRect:
    """An axis-aligned rectangle in DEF database units."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2


@dataclass
class DefRow:
    """A placement row definition."""

    name: str
    site: str
    x: float  # in db units
    y: float
    orientation: str  # N/S/E/W/FN/FS/FE/FW
    num_x: int = 1
    num_y: int = 1
    step_x: float = 0
    step_y: float = 0

    @property
    def width(self) -> float:
        """Total width of the row in db units."""
        return self.num_x * self.step_x if self.step_x > 0 else 0

    @property
    def height(self) -> float:
        """Row height in db units (single site, vertical step)."""
        return self.step_y if self.step_y > 0 else 2720  # sky130 default


@dataclass
class DefTrack:
    """A routing track grid definition."""

    direction: str  # X (horizontal) or Y (vertical)
    start: float
    num: int
    step: float
    layers: list[str] = field(default_factory=list)


@dataclass
class DefComponent:
    """A placed instance referencing a LEF macro (cell)."""

    name: str  # instance name
    macro: str  # cell type / LEF macro name
    status: str = "UNPLACED"  # PLACED, FIXED, COVER, UNPLACED
    x: float = 0
    y: float = 0
    orientation: str = "N"
    source: str = ""  # NETLIST, DIST, USER, TIMING

    # Heuristic classifications based on the macro name. The categories are
    # specifically tuned for the SKY130 standard cell library names but cope
    # well with most cell libraries that follow similar conventions.

    @property
    def is_filler(self) -> bool:
        m = self.macro.lower()
        return "fill" in m or "decap" in m

    @property
    def is_tap(self) -> bool:
        return "tap" in self.macro.lower()

    @property
    def is_buffer(self) -> bool:
        m = self.macro.lower()
        return ("__buf" in m or "_buf_" in m or "clkbuf" in m
                or "__clkbuf" in m or "__clkdlybuf" in m)

    @property
    def is_inverter(self) -> bool:
        m = self.macro.lower()
        return "__inv" in m or "_inv_" in m or "clkinv" in m

    @property
    def is_flop(self) -> bool:
        m = self.macro.lower()
        return ("_dff" in m or "_ff_" in m or "_dfb" in m or "_dfx" in m
                or "_dfr" in m or "_dlrtp" in m or "_dlxtp" in m
                or "sdff" in m or "edff" in m)

    @property
    def is_latch(self) -> bool:
        m = self.macro.lower()
        return "latch" in m or "_dlatch" in m

    @property
    def is_clock_cell(self) -> bool:
        m = self.macro.lower()
        return "clkbuf" in m or "clkinv" in m or "clkmx" in m or "clkdlybuf" in m

    @property
    def is_macro(self) -> bool:
        """Heuristic: cell sized > 50 um wide is probably a hard macro."""
        m = self.macro.lower()
        return ("sram" in m or "ram_" in m or "rom_" in m or "pll" in m
                or "_macro" in m)

    @property
    def is_placed(self) -> bool:
        return self.status in ("PLACED", "FIXED", "COVER")


@dataclass
class DefPin:
    """A top-level I/O pin."""

    name: str
    net: str
    direction: str = "INOUT"  # INPUT/OUTPUT/INOUT/FEEDTHRU
    use: str = "SIGNAL"  # SIGNAL/CLOCK/POWER/GROUND/RESET/ANALOG
    layer: str = ""
    layer_rect: DefRect | None = None
    x: float = 0
    y: float = 0
    orientation: str = "N"
    placed: bool = False

    @property
    def is_clock(self) -> bool:
        return self.use == "CLOCK" or self.name.lower() in ("clk", "clock")

    @property
    def is_power(self) -> bool:
        return self.use in ("POWER", "GROUND")


@dataclass
class DefRouteSegment:
    """A single ROUTED / NEW segment within a net."""

    layer: str
    points: list[tuple[float, float, float]] = field(default_factory=list)
    # (x, y, ext) in db units
    via: str = ""  # via cell name if this segment ends in a via
    width: float = 0  # 0 = use default for layer
    style: int = 0   # SHAPE: 0 = default, others = STRIPE/IOWIRE/COREWIRE...
    shape: str = ""  # STRIPE / RING / FOLLOWPIN / IOWIRE / COREWIRE / BLOCKWIRE
    mask: int = 0
    is_via_only: bool = False

    @property
    def length_db(self) -> float:
        """Manhattan length of the segment in db units."""
        if len(self.points) < 2:
            return 0.0
        total = 0.0
        for i in range(len(self.points) - 1):
            x1, y1, _ = self.points[i]
            x2, y2, _ = self.points[i + 1]
            total += abs(x2 - x1) + abs(y2 - y1)
        return total


@dataclass
class DefNet:
    """A signal or special net."""

    name: str
    connections: list[tuple[str, str]] = field(default_factory=list)
    # (instance_name, pin_name) — instance == "PIN" for top-level pins
    use: str = "SIGNAL"
    routes: list[DefRouteSegment] = field(default_factory=list)
    is_special: bool = False
    source: str = ""
    weight: int = 0

    @property
    def fanout(self) -> int:
        """Number of pin connections (driver + sinks)."""
        return len(self.connections)

    @property
    def total_length_db(self) -> float:
        """Sum of all segment lengths."""
        return sum(seg.length_db for seg in self.routes)

    @property
    def layers_used(self) -> set[str]:
        return {seg.layer for seg in self.routes if seg.layer}

    @property
    def is_clock(self) -> bool:
        return self.use == "CLOCK"

    @property
    def is_power(self) -> bool:
        return self.use in ("POWER", "GROUND")


@dataclass
class DefDesign:
    """The full parsed contents of a DEF file."""

    name: str = ""
    version: str = ""
    divider_char: str = "/"
    bus_bit_chars: str = "[]"
    units_per_micron: int = 1000
    die_area: DefRect = field(default_factory=lambda: DefRect(0, 0, 0, 0))
    rows: list[DefRow] = field(default_factory=list)
    tracks: list[DefTrack] = field(default_factory=list)
    components: dict[str, DefComponent] = field(default_factory=dict)
    pins: dict[str, DefPin] = field(default_factory=dict)
    nets: dict[str, DefNet] = field(default_factory=dict)
    special_nets: dict[str, DefNet] = field(default_factory=dict)

    # ----- Geometry helpers ----------------------------------------------

    @property
    def width_db(self) -> float:
        return self.die_area.x2 - self.die_area.x1

    @property
    def height_db(self) -> float:
        return self.die_area.y2 - self.die_area.y1

    @property
    def width_um(self) -> float:
        return self.width_db / self.units_per_micron

    @property
    def height_um(self) -> float:
        return self.height_db / self.units_per_micron

    @property
    def area_um2(self) -> float:
        return self.width_um * self.height_um

    def to_um(self, db_value: float) -> float:
        return db_value / self.units_per_micron

    def from_um(self, um_value: float) -> float:
        return um_value * self.units_per_micron

    # ----- Statistics ----------------------------------------------------

    def stats(self) -> dict:
        """Return a flat dictionary of summary statistics for the design."""
        comps = list(self.components.values())
        n_total = len(comps)
        n_filler = sum(1 for c in comps if c.is_filler)
        n_tap = sum(1 for c in comps if c.is_tap)
        n_buf = sum(1 for c in comps if c.is_buffer)
        n_inv = sum(1 for c in comps if c.is_inverter)
        n_flop = sum(1 for c in comps if c.is_flop)
        n_latch = sum(1 for c in comps if c.is_latch)
        n_clk = sum(1 for c in comps if c.is_clock_cell)
        n_macro = sum(1 for c in comps if c.is_macro)
        n_logic = n_total - n_filler - n_tap

        n_in = sum(1 for p in self.pins.values() if p.direction == "INPUT")
        n_out = sum(1 for p in self.pins.values() if p.direction == "OUTPUT")
        n_inout = sum(1 for p in self.pins.values() if p.direction == "INOUT")
        n_clk_pins = sum(1 for p in self.pins.values() if p.is_clock)

        # Total routed wirelength
        total_wl_db = 0.0
        n_routes = 0
        layers_seen: set[str] = set()
        for net in self.nets.values():
            total_wl_db += net.total_length_db
            n_routes += len(net.routes)
            layers_seen |= net.layers_used

        return {
            "design_name": self.name,
            "total_cells": n_total,
            "logic_cells": n_logic,
            "filler_cells": n_filler,
            "tap_cells": n_tap,
            "flops": n_flop,
            "latches": n_latch,
            "buffers": n_buf,
            "inverters": n_inv,
            "clock_cells": n_clk,
            "macros": n_macro,
            "total_pins": len(self.pins),
            "input_pins": n_in,
            "output_pins": n_out,
            "inout_pins": n_inout,
            "clock_pins": n_clk_pins,
            "total_nets": len(self.nets),
            "special_nets": len(self.special_nets),
            "total_routes": n_routes,
            "layers_used": sorted(layers_seen),
            "wirelength_um": total_wl_db / self.units_per_micron if self.units_per_micron else 0.0,
            "die_width_um": self.width_um,
            "die_height_um": self.height_um,
            "die_area_um2": self.area_um2,
            "rows": len(self.rows),
            "tracks": len(self.tracks),
        }

    # ----- Region queries ------------------------------------------------

    def cells_in_region(
        self, x1: float, y1: float, x2: float, y2: float,
    ) -> list[DefComponent]:
        """Return all components whose origin is inside a rectangle (db units)."""
        return [
            c for c in self.components.values()
            if x1 <= c.x <= x2 and y1 <= c.y <= y2
        ]

    def find_cells_by_macro(self, macro_pattern: str) -> list[DefComponent]:
        """Return components whose macro name matches a substring."""
        m = macro_pattern.lower()
        return [c for c in self.components.values() if m in c.macro.lower()]

    def find_cells_by_name(self, name_pattern: str) -> list[DefComponent]:
        """Return components whose instance name matches a substring."""
        m = name_pattern.lower()
        return [c for c in self.components.values() if m in c.name.lower()]

    def get_pin(self, name: str) -> DefPin | None:
        return self.pins.get(name)

    def get_net(self, name: str) -> DefNet | None:
        return self.nets.get(name) or self.special_nets.get(name)

    def nets_for_cell(self, cell_name: str) -> list[DefNet]:
        """Return all nets connected to the given instance."""
        result: list[DefNet] = []
        for net in self.nets.values():
            for inst, _pin in net.connections:
                if inst == cell_name:
                    result.append(net)
                    break
        return result

    # ----- Density heatmap ----------------------------------------------

    def density_heatmap(
        self, grid_size_um: float = 5.0,
    ) -> tuple[list[list[float]], int, int]:
        """Compute placement density as a 2D grid normalised to 0..1.

        Returns ``(grid, n_cols, n_rows)`` where ``grid[row][col]`` is the
        normalised density of placed (non-filler) cells in that bin.
        """
        if self.width_um <= 0 or self.height_um <= 0:
            return [[0.0]], 1, 1

        n_cols = max(1, int(self.width_um / grid_size_um))
        n_rows = max(1, int(self.height_um / grid_size_um))
        grid = [[0.0] * n_cols for _ in range(n_rows)]

        for c in self.components.values():
            if c.is_filler or not c.is_placed:
                continue
            x_um = self.to_um(c.x - self.die_area.x1)
            y_um = self.to_um(c.y - self.die_area.y1)
            col = min(n_cols - 1, max(0, int(x_um / grid_size_um)))
            row = min(n_rows - 1, max(0, int(y_um / grid_size_um)))
            grid[row][col] += 1

        max_val = max((max(r) for r in grid), default=0.0)
        if max_val > 0:
            grid = [[v / max_val for v in r] for r in grid]
        return grid, n_cols, n_rows

    def congestion_heatmap(
        self, grid_size_um: float = 5.0,
    ) -> tuple[list[list[float]], int, int]:
        """Compute a routing congestion heatmap from the parsed routes.

        For each grid cell, sums the length of route segments that pass
        through it. Provides a rough proxy for routing congestion in
        designs that don't ship a separate congestion report.
        """
        if self.width_um <= 0 or self.height_um <= 0:
            return [[0.0]], 1, 1

        n_cols = max(1, int(self.width_um / grid_size_um))
        n_rows = max(1, int(self.height_um / grid_size_um))
        grid = [[0.0] * n_cols for _ in range(n_rows)]
        bin_db = grid_size_um * self.units_per_micron

        for net in self.nets.values():
            for seg in net.routes:
                if len(seg.points) < 2:
                    continue
                for i in range(len(seg.points) - 1):
                    x1, y1, _ = seg.points[i]
                    x2, y2, _ = seg.points[i + 1]
                    # midpoint binning is fast and good enough for a heatmap
                    cx = (x1 + x2) / 2 - self.die_area.x1
                    cy = (y1 + y2) / 2 - self.die_area.y1
                    col = min(n_cols - 1, max(0, int(cx / bin_db)))
                    row = min(n_rows - 1, max(0, int(cy / bin_db)))
                    grid[row][col] += abs(x2 - x1) + abs(y2 - y1)

        max_val = max((max(r) for r in grid), default=0.0)
        if max_val > 0:
            grid = [[v / max_val for v in r] for r in grid]
        return grid, n_cols, n_rows


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Pre-compiled patterns. Compiling once at module import time saves a few
# milliseconds per file and makes hot loops on multi-MB DEF dumps much faster.

_RE_DESIGN = re.compile(r'^\s*DESIGN\s+(\S+)\s*;', re.MULTILINE)
_RE_VERSION = re.compile(r'^\s*VERSION\s+(\S+)\s*;', re.MULTILINE)
_RE_DIVIDER = re.compile(r'^\s*DIVIDERCHAR\s+"([^"]+)"\s*;', re.MULTILINE)
_RE_BUSBIT = re.compile(r'^\s*BUSBITCHARS\s+"([^"]+)"\s*;', re.MULTILINE)
_RE_UNITS = re.compile(
    r'^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;', re.MULTILINE,
)
_RE_DIEAREA = re.compile(
    r'^\s*DIEAREA\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)',
    re.MULTILINE,
)
_RE_ROW = re.compile(
    r'ROW\s+(\S+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\w+)'
    r'(?:\s+DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(\d+)\s+(\d+))?\s*;'
)
_RE_TRACK = re.compile(
    r'TRACKS\s+(\w+)\s+(\d+)\s+DO\s+(\d+)\s+STEP\s+(\d+)\s+LAYER\s+([\w\s]+?)\s*;'
)
_RE_COMPONENTS_BLOCK = re.compile(
    r'COMPONENTS\s+\d+\s*;(.*?)END\s+COMPONENTS', re.DOTALL,
)
_RE_PINS_BLOCK = re.compile(r'PINS\s+\d+\s*;(.*?)END\s+PINS', re.DOTALL)
_RE_NETS_BLOCK = re.compile(
    r'^NETS\s+\d+\s*;(.*?)END\s+NETS', re.DOTALL | re.MULTILINE,
)
_RE_SPECNETS_BLOCK = re.compile(
    r'SPECIALNETS\s+\d+\s*;(.*?)END\s+SPECIALNETS', re.DOTALL,
)

# A component record is "- <inst> <macro> [+ STATUS ( x y ) orient] [+ SOURCE x] ;"
_RE_COMPONENT = re.compile(
    r'-\s+(\S+)\s+(\S+)'
    r'(?:.*?\+\s+(PLACED|FIXED|COVER|UNPLACED)'
    r'(?:\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+))?)?'
    r'(?:.*?\+\s+SOURCE\s+(\w+))?'
    r'\s*;',
    re.DOTALL,
)

# A pin record. The body of the pin (between "-" and ";") may span lines.
_RE_PIN = re.compile(
    r'-\s+(\S+)\s+\+\s+NET\s+(\S+)(.*?);',
    re.DOTALL,
)
_RE_PIN_DIR = re.compile(r'\+\s+DIRECTION\s+(\w+)')
_RE_PIN_USE = re.compile(r'\+\s+USE\s+(\w+)')
_RE_PIN_LAYER = re.compile(
    r'\+\s+LAYER\s+(\w+)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)'
)
_RE_PIN_PLACED = re.compile(
    r'\+\s+(?:PLACED|FIXED|COVER)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)'
)

# Net record.
_RE_NET = re.compile(r'-\s+(\S+)\s+(.*?);', re.DOTALL)
_RE_NET_CONN = re.compile(r'\(\s*(\S+)\s+(\S+)\s*\)')
_RE_NET_USE = re.compile(r'\+\s+USE\s+(\w+)')
_RE_NET_SOURCE = re.compile(r'\+\s+SOURCE\s+(\w+)')

# A ROUTED / NEW segment: layer + sequence of points and via tokens.
_RE_ROUTE = re.compile(
    r'(?:\+\s+ROUTED|\+\s+FIXED|NEW)\s+(\w+)'
    r'((?:\s+\(\s*[-*\d]+\s+[-*\d]+(?:\s+-?\d+)?\s*\)|\s+[a-zA-Z_]\w*)+)'
)
# Optional SHAPE keyword for SPECIALNETS routes.
_RE_ROUTE_SHAPE = re.compile(
    r'(?:\+\s+ROUTED|NEW)\s+(\w+)\s+(\d+)(?:\s+\+\s+SHAPE\s+(\w+))?'
    r'((?:\s+\(\s*[-*\d]+\s+[-*\d]+(?:\s+-?\d+)?\s*\)|\s+[a-zA-Z_]\w*)+)'
)
_RE_POINT = re.compile(
    r'\(\s*([-*\d]+)\s+([-*\d]+)(?:\s+(-?\d+))?\s*\)'
)


def _parse_route_points(
    pts_str: str, last_x: float = 0.0, last_y: float = 0.0,
) -> tuple[list[tuple[float, float, float]], str]:
    """Parse the point/via list of a ROUTED segment.

    DEF allows the special token ``*`` for "same as previous coordinate",
    so we have to track the running cursor as we walk the segment.
    Returns the list of points and any trailing via cell name.
    """
    points: list[tuple[float, float, float]] = []
    via = ""
    pos = 0
    while pos < len(pts_str):
        m = _RE_POINT.match(pts_str, pos)
        if m:
            xs, ys, ext = m.group(1), m.group(2), m.group(3)
            x = last_x if xs == "*" else float(xs)
            y = last_y if ys == "*" else float(ys)
            e = float(ext) if ext else 0.0
            points.append((x, y, e))
            last_x, last_y = x, y
            pos = m.end()
            # skip whitespace
            while pos < len(pts_str) and pts_str[pos].isspace():
                pos += 1
            continue
        # Otherwise it might be a via cell name (alphanumeric token)
        ws = pos
        while ws < len(pts_str) and not pts_str[ws].isspace() and pts_str[ws] != '(':
            ws += 1
        token = pts_str[pos:ws].strip()
        if token and token[0].isalpha():
            via = token
        pos = ws
        while pos < len(pts_str) and pts_str[pos].isspace():
            pos += 1
    return points, via


def parse_def(path: Path | str) -> DefDesign:
    """Parse a DEF file from disk and return a populated :class:`DefDesign`.

    Parameters
    ----------
    path:
        Path to a DEF file. Both ``str`` and ``pathlib.Path`` are accepted.

    Raises
    ------
    FileNotFoundError:
        If the file doesn't exist on disk.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"DEF file not found: {p}")

    # DEF files can be quite large (multi-MB) but read_text is still the
    # simplest, fastest approach. errors='replace' guards against the
    # occasional non-ASCII byte in vendor-supplied DEF.
    text = p.read_text(encoding="utf-8", errors="replace")
    return parse_def_text(text)


def parse_def_text(text: str) -> DefDesign:
    """Parse DEF content already loaded into memory."""
    design = DefDesign()

    _parse_header(text, design)
    _parse_rows(text, design)
    _parse_tracks(text, design)
    _parse_components(text, design)
    _parse_pins(text, design)
    _parse_nets(text, design)
    _parse_special_nets(text, design)

    return design


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_header(text: str, design: DefDesign) -> None:
    """Pull DESIGN, VERSION, UNITS, DIEAREA out of the file header."""
    m = _RE_DESIGN.search(text)
    if m:
        design.name = m.group(1)

    m = _RE_VERSION.search(text)
    if m:
        design.version = m.group(1)

    m = _RE_DIVIDER.search(text)
    if m:
        design.divider_char = m.group(1)

    m = _RE_BUSBIT.search(text)
    if m:
        design.bus_bit_chars = m.group(1)

    m = _RE_UNITS.search(text)
    if m:
        design.units_per_micron = int(m.group(1))

    m = _RE_DIEAREA.search(text)
    if m:
        design.die_area = DefRect(
            float(m.group(1)), float(m.group(2)),
            float(m.group(3)), float(m.group(4)),
        )


def _parse_rows(text: str, design: DefDesign) -> None:
    """Walk all ROW records in the file."""
    for m in _RE_ROW.finditer(text):
        try:
            row = DefRow(
                name=m.group(1),
                site=m.group(2),
                x=float(m.group(3)),
                y=float(m.group(4)),
                orientation=m.group(5),
                num_x=int(m.group(6)) if m.group(6) else 1,
                num_y=int(m.group(7)) if m.group(7) else 1,
                step_x=float(m.group(8)) if m.group(8) else 0,
                step_y=float(m.group(9)) if m.group(9) else 0,
            )
            design.rows.append(row)
        except (ValueError, TypeError):
            continue


def _parse_tracks(text: str, design: DefDesign) -> None:
    """Walk all TRACKS records."""
    for m in _RE_TRACK.finditer(text):
        try:
            track = DefTrack(
                direction=m.group(1),
                start=float(m.group(2)),
                num=int(m.group(3)),
                step=float(m.group(4)),
                layers=m.group(5).split(),
            )
            design.tracks.append(track)
        except (ValueError, TypeError):
            continue


def _parse_components(text: str, design: DefDesign) -> None:
    """Parse the COMPONENTS section."""
    block = _RE_COMPONENTS_BLOCK.search(text)
    if not block:
        return
    body = block.group(1)

    # Iterate by splitting on the leading "-" so multi-line component records
    # work even when they wrap. We re-add the dash before parsing.
    for chunk in re.split(r'(?m)^\s*-\s+', body):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Stop at the trailing semicolon
        end = chunk.find(';')
        if end < 0:
            continue
        record = '- ' + chunk[:end + 1]
        m = _RE_COMPONENT.match(record)
        if not m:
            continue
        comp = DefComponent(
            name=m.group(1),
            macro=m.group(2),
            status=m.group(3) or "UNPLACED",
            x=float(m.group(4)) if m.group(4) else 0,
            y=float(m.group(5)) if m.group(5) else 0,
            orientation=m.group(6) or "N",
            source=m.group(7) or "",
        )
        design.components[comp.name] = comp


def _parse_pins(text: str, design: DefDesign) -> None:
    """Parse the PINS section, including LAYER and PLACED metadata."""
    block = _RE_PINS_BLOCK.search(text)
    if not block:
        return
    body = block.group(1)

    for m in _RE_PIN.finditer(body):
        name = m.group(1)
        net = m.group(2)
        extras = m.group(3) or ""

        pin = DefPin(name=name, net=net)

        dir_m = _RE_PIN_DIR.search(extras)
        if dir_m:
            pin.direction = dir_m.group(1)

        use_m = _RE_PIN_USE.search(extras)
        if use_m:
            pin.use = use_m.group(1)

        layer_m = _RE_PIN_LAYER.search(extras)
        if layer_m:
            pin.layer = layer_m.group(1)
            pin.layer_rect = DefRect(
                float(layer_m.group(2)), float(layer_m.group(3)),
                float(layer_m.group(4)), float(layer_m.group(5)),
            )

        placed_m = _RE_PIN_PLACED.search(extras)
        if placed_m:
            pin.x = float(placed_m.group(1))
            pin.y = float(placed_m.group(2))
            pin.orientation = placed_m.group(3)
            pin.placed = True

        design.pins[pin.name] = pin


def _parse_nets(text: str, design: DefDesign) -> None:
    """Parse the NETS section, including all ROUTED segments."""
    block = _RE_NETS_BLOCK.search(text)
    if not block:
        return
    body = block.group(1)

    # Split on leading "- " at line start to grab one net record per chunk.
    for chunk in re.split(r'(?m)^\s*-\s+', body):
        chunk = chunk.strip()
        if not chunk:
            continue
        end = chunk.find(';')
        if end < 0:
            continue
        record = chunk[:end]
        # First token is the net name.
        first_ws = re.search(r'\s', record)
        if not first_ws:
            continue
        net_name = record[:first_ws.start()]
        rest = record[first_ws.end():]

        net = DefNet(name=net_name)

        # Connections.
        for c in _RE_NET_CONN.finditer(rest):
            net.connections.append((c.group(1), c.group(2)))

        # USE attribute.
        u = _RE_NET_USE.search(rest)
        if u:
            net.use = u.group(1)

        # SOURCE attribute.
        s = _RE_NET_SOURCE.search(rest)
        if s:
            net.source = s.group(1)

        # ROUTED / NEW segments.
        _parse_net_routes(rest, net)

        design.nets[net_name] = net


def _parse_net_routes(record: str, net: DefNet) -> None:
    """Walk every ROUTED / NEW segment of a net record."""
    for m in _RE_ROUTE.finditer(record):
        layer = m.group(1)
        pts_str = m.group(2)
        points, via = _parse_route_points(pts_str)
        if not points:
            # Pure via segment with no coordinates: still record it.
            net.routes.append(DefRouteSegment(
                layer=layer, via=via, is_via_only=True,
            ))
            continue
        net.routes.append(DefRouteSegment(
            layer=layer, points=points, via=via,
        ))


def _parse_special_nets(text: str, design: DefDesign) -> None:
    """Parse the SPECIALNETS section (power/ground)."""
    block = _RE_SPECNETS_BLOCK.search(text)
    if not block:
        return
    body = block.group(1)

    for chunk in re.split(r'(?m)^\s*-\s+', body):
        chunk = chunk.strip()
        if not chunk:
            continue
        end = chunk.find(';')
        if end < 0:
            continue
        record = chunk[:end]
        first_ws = re.search(r'\s', record)
        if not first_ws:
            continue
        net_name = record[:first_ws.start()]
        rest = record[first_ws.end():]

        net = DefNet(name=net_name, is_special=True)

        # Default USE: detect from raw text.
        if "POWER" in rest:
            net.use = "POWER"
        elif "GROUND" in rest:
            net.use = "GROUND"

        for c in _RE_NET_CONN.finditer(rest):
            net.connections.append((c.group(1), c.group(2)))

        # Special net routes carry an optional width and SHAPE keyword.
        for m in _RE_ROUTE_SHAPE.finditer(rest):
            layer = m.group(1)
            try:
                width = float(m.group(2))
            except (TypeError, ValueError):
                width = 0.0
            shape = m.group(3) or ""
            pts_str = m.group(4) or ""
            points, via = _parse_route_points(pts_str)
            net.routes.append(DefRouteSegment(
                layer=layer, points=points, via=via,
                width=width, shape=shape,
            ))

        design.special_nets[net_name] = net


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def summarise(design: DefDesign) -> str:
    """Return a short multi-line summary string useful for CLI output."""
    s = design.stats()
    lines = [
        f"Design: {s['design_name']}",
        f"  Die area:    {s['die_width_um']:.1f} x {s['die_height_um']:.1f} um "
        f"({s['die_area_um2']:,.1f} um^2)",
        f"  Cells:       {s['total_cells']:,} total, "
        f"{s['logic_cells']:,} logic, {s['filler_cells']:,} fillers",
        f"  Sequential:  {s['flops']:,} flops, {s['latches']:,} latches, "
        f"{s['clock_cells']:,} clock cells",
        f"  Pins:        {s['total_pins']:,} I/O ({s['input_pins']} in, "
        f"{s['output_pins']} out, {s['inout_pins']} inout)",
        f"  Nets:        {s['total_nets']:,} signal, {s['special_nets']} special",
        f"  Wirelength:  {s['wirelength_um']:,.1f} um",
        f"  Layers used: {', '.join(s['layers_used']) or '(none)'}",
    ]
    return "\n".join(lines)


__all__ = [
    "DefRect",
    "DefRow",
    "DefTrack",
    "DefComponent",
    "DefPin",
    "DefRouteSegment",
    "DefNet",
    "DefDesign",
    "parse_def",
    "parse_def_text",
    "summarise",
]
