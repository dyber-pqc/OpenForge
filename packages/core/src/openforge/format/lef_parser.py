"""LEF (Library Exchange Format) parser.

A light-weight LEF parser focused on the information the OpenForge layout
viewer and physical design panel actually need:

* Macro cell sizes (width and height in microns), so placed instances can
  be rendered at the correct physical footprint instead of 10x10 squares.
* Macro pin names, so the properties pane can list a cell's connections.
* Site definitions (row height, pitch) to size placement rows correctly.
* Layer names and pitches, so the layout viewer knows which layers to
  offer in its layer toggle panel.

This parser intentionally skips the detailed port geometry, OBS regions,
antenna data, and extraction properties that live inside LEF — those are
irrelevant for interactive visualisation and make the parser an order of
magnitude slower.

Usage
-----

    from openforge.format.lef_parser import parse_lef
    lib = parse_lef("sky130_fd_sc_hd_merged.lef")
    cell = lib.macros["sky130_fd_sc_hd__nand2_1"]
    print(cell.width, cell.height)  # in microns

If you have multiple LEF files (e.g. a tech LEF plus a cell LEF), call
:func:`parse_lef` on each and merge the resulting libraries with
:meth:`LefLibrary.merge`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LefPin:
    """A pin on a LEF MACRO."""

    name: str
    direction: str = ""  # INPUT / OUTPUT / INOUT
    use: str = "SIGNAL"  # SIGNAL / POWER / GROUND / CLOCK / ANALOG

    @property
    def is_power(self) -> bool:
        return self.use in ("POWER", "GROUND")

    @property
    def is_clock(self) -> bool:
        return self.use == "CLOCK"


@dataclass
class LefMacro:
    """A standard cell or hard macro definition."""

    name: str
    class_type: str = ""  # CORE, PAD, BLOCK, COVER, RING
    foreign: str = ""
    width: float = 0.0   # in microns
    height: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    site: str = ""
    symmetry: list[str] = field(default_factory=list)
    pins: list[LefPin] = field(default_factory=list)

    @property
    def area(self) -> float:
        """Cell area in um^2."""
        return self.width * self.height

    @property
    def pin_names(self) -> list[str]:
        return [p.name for p in self.pins]

    def signal_pins(self) -> list[LefPin]:
        return [p for p in self.pins if not p.is_power]

    def power_pins(self) -> list[LefPin]:
        return [p for p in self.pins if p.is_power]

    @property
    def is_filler(self) -> bool:
        n = self.name.lower()
        return "fill" in n or "decap" in n

    @property
    def is_tap(self) -> bool:
        return "tap" in self.name.lower()

    @property
    def is_flop(self) -> bool:
        n = self.name.lower()
        return "_dff" in n or "_dfb" in n or "_dfx" in n or "_dfr" in n


@dataclass
class LefSite:
    """A placement site (row unit)."""

    name: str
    class_type: str = ""  # CORE, PAD, CORNER
    width: float = 0.0   # in microns
    height: float = 0.0
    symmetry: list[str] = field(default_factory=list)


@dataclass
class LefLayer:
    """A routing or cut layer definition (minimal fields only)."""

    name: str
    layer_type: str = ""  # ROUTING / CUT / MASTERSLICE / OVERLAP / IMPLANT
    direction: str = ""   # HORIZONTAL / VERTICAL
    pitch_x: float = 0.0
    pitch_y: float = 0.0
    width: float = 0.0
    spacing: float = 0.0


@dataclass
class LefLibrary:
    """The top-level parsed LEF library."""

    version: str = ""
    units_per_micron: float = 1.0
    macros: dict[str, LefMacro] = field(default_factory=dict)
    sites: dict[str, LefSite] = field(default_factory=dict)
    layers: dict[str, LefLayer] = field(default_factory=dict)
    manufacturing_grid: float = 0.0

    def merge(self, other: "LefLibrary") -> None:
        """Merge macros, sites and layers from another library into this one.

        Useful when you have a separate tech LEF and cell LEF.
        """
        self.macros.update(other.macros)
        self.sites.update(other.sites)
        self.layers.update(other.layers)
        if other.manufacturing_grid and not self.manufacturing_grid:
            self.manufacturing_grid = other.manufacturing_grid

    def cell_size(self, macro_name: str) -> tuple[float, float]:
        """Return (width_um, height_um) for a macro, or (0, 0) if unknown."""
        m = self.macros.get(macro_name)
        if m is None:
            return (0.0, 0.0)
        return (m.width, m.height)

    def routing_layers(self) -> list[LefLayer]:
        """Return layers with type ROUTING, in the order they were parsed."""
        return [l for l in self.layers.values() if l.layer_type == "ROUTING"]

    def stats(self) -> dict:
        """Return a quick summary dictionary."""
        return {
            "macros": len(self.macros),
            "filler_macros": sum(1 for m in self.macros.values() if m.is_filler),
            "flop_macros": sum(1 for m in self.macros.values() if m.is_flop),
            "sites": len(self.sites),
            "layers": len(self.layers),
            "routing_layers": len(self.routing_layers()),
            "total_cell_area_um2": sum(m.area for m in self.macros.values()),
        }


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_VERSION = re.compile(r'^\s*VERSION\s+(\S+)\s*;', re.MULTILINE)
_RE_UNITS_DB = re.compile(
    r'UNITS\s*.*?DATABASE\s+MICRONS\s+([\d.]+)\s*;', re.DOTALL,
)
_RE_MFG_GRID = re.compile(r'^\s*MANUFACTURINGGRID\s+([\d.]+)\s*;', re.MULTILINE)

# Layer block: LAYER <name> ... END <name>
_RE_LAYER = re.compile(
    r'^\s*LAYER\s+(\S+)\s+(.*?)END\s+\1',
    re.DOTALL | re.MULTILINE,
)
_RE_LAYER_TYPE = re.compile(r'TYPE\s+(\w+)\s*;')
_RE_LAYER_DIR = re.compile(r'DIRECTION\s+(\w+)\s*;')
_RE_LAYER_PITCH = re.compile(r'PITCH\s+([\d.]+)(?:\s+([\d.]+))?\s*;')
_RE_LAYER_WIDTH = re.compile(r'\bWIDTH\s+([\d.]+)\s*;')
_RE_LAYER_SPACING = re.compile(r'\bSPACING\s+([\d.]+)\s*;')

# Site block: SITE <name> ... END <name>
_RE_SITE = re.compile(
    r'^\s*SITE\s+(\S+)\s+(.*?)END\s+\1',
    re.DOTALL | re.MULTILINE,
)
_RE_SITE_CLASS = re.compile(r'CLASS\s+(\w+)\s*;')
_RE_SITE_SIZE = re.compile(r'SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;')
_RE_SITE_SYM = re.compile(r'SYMMETRY\s+([\w\s]+?)\s*;')

# Macro block: MACRO <name> ... END <name>
_RE_MACRO = re.compile(
    r'^\s*MACRO\s+(\S+)\s+(.*?)END\s+\1',
    re.DOTALL | re.MULTILINE,
)
_RE_MACRO_CLASS = re.compile(r'CLASS\s+([\w\s]+?)\s*;')
_RE_MACRO_FOREIGN = re.compile(r'FOREIGN\s+(\S+)')
_RE_MACRO_ORIGIN = re.compile(r'ORIGIN\s+([-\d.]+)\s+([-\d.]+)\s*;')
_RE_MACRO_SIZE = re.compile(r'SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;')
_RE_MACRO_SITE = re.compile(r'SITE\s+(\S+)\s*;')
_RE_MACRO_SYM = re.compile(r'SYMMETRY\s+([\w\s]+?)\s*;')

# Pins inside a MACRO body.
_RE_PIN_BLOCK = re.compile(
    r'PIN\s+(\S+)\s+(.*?)END\s+\1',
    re.DOTALL,
)
_RE_PIN_DIR = re.compile(r'DIRECTION\s+(\w+)\s*;')
_RE_PIN_USE = re.compile(r'USE\s+(\w+)\s*;')


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------


def parse_lef(path: Path | str) -> LefLibrary:
    """Parse a LEF file from disk.

    Parameters
    ----------
    path:
        Path to a LEF file (tech LEF or cell LEF, merged or separate).

    Returns
    -------
    LefLibrary
        A populated library object.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"LEF file not found: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return parse_lef_text(text)


def parse_lef_text(text: str) -> LefLibrary:
    """Parse LEF content already loaded into memory."""
    lib = LefLibrary()

    _parse_header(text, lib)
    _parse_layers(text, lib)
    _parse_sites(text, lib)
    _parse_macros(text, lib)

    return lib


def parse_lef_directory(directory: Path | str) -> LefLibrary:
    """Parse every ``*.lef`` / ``*.tlef`` file in a directory and merge.

    Convenience helper for projects that ship the tech LEF and cell LEFs
    as separate files. Order is deterministic (sorted by name), so later
    files override earlier macros with the same name.
    """
    d = Path(directory)
    if not d.exists():
        raise FileNotFoundError(f"LEF directory not found: {d}")

    merged = LefLibrary()
    files: list[Path] = sorted(
        list(d.glob("*.lef")) + list(d.glob("*.tlef"))
    )
    for f in files:
        try:
            lib = parse_lef(f)
            merged.merge(lib)
        except Exception:
            # Skip broken files — the layout viewer should degrade
            # gracefully if one LEF in a library is malformed.
            continue
    return merged


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_header(text: str, lib: LefLibrary) -> None:
    m = _RE_VERSION.search(text)
    if m:
        lib.version = m.group(1)
    m = _RE_UNITS_DB.search(text)
    if m:
        try:
            lib.units_per_micron = float(m.group(1))
        except ValueError:
            pass
    m = _RE_MFG_GRID.search(text)
    if m:
        try:
            lib.manufacturing_grid = float(m.group(1))
        except ValueError:
            pass


def _parse_layers(text: str, lib: LefLibrary) -> None:
    """Walk all LAYER blocks and extract routing metadata."""
    for m in _RE_LAYER.finditer(text):
        name = m.group(1)
        body = m.group(2)
        layer = LefLayer(name=name)

        tm = _RE_LAYER_TYPE.search(body)
        if tm:
            layer.layer_type = tm.group(1)

        dm = _RE_LAYER_DIR.search(body)
        if dm:
            layer.direction = dm.group(1)

        pm = _RE_LAYER_PITCH.search(body)
        if pm:
            try:
                layer.pitch_x = float(pm.group(1))
                layer.pitch_y = float(pm.group(2)) if pm.group(2) else layer.pitch_x
            except ValueError:
                pass

        wm = _RE_LAYER_WIDTH.search(body)
        if wm:
            try:
                layer.width = float(wm.group(1))
            except ValueError:
                pass

        sm = _RE_LAYER_SPACING.search(body)
        if sm:
            try:
                layer.spacing = float(sm.group(1))
            except ValueError:
                pass

        lib.layers[name] = layer


def _parse_sites(text: str, lib: LefLibrary) -> None:
    """Walk all SITE blocks."""
    for m in _RE_SITE.finditer(text):
        name = m.group(1)
        body = m.group(2)
        site = LefSite(name=name)

        cm = _RE_SITE_CLASS.search(body)
        if cm:
            site.class_type = cm.group(1)

        sm = _RE_SITE_SIZE.search(body)
        if sm:
            try:
                site.width = float(sm.group(1))
                site.height = float(sm.group(2))
            except ValueError:
                pass

        ym = _RE_SITE_SYM.search(body)
        if ym:
            site.symmetry = ym.group(1).split()

        lib.sites[name] = site


def _parse_macros(text: str, lib: LefLibrary) -> None:
    """Walk all MACRO blocks and extract the fields we need.

    For each macro we record the physical size, the site it targets, and
    a flat list of pins with direction/use. Detailed pin geometry (PORT,
    LAYER, RECT) is skipped because the viewer only needs to know the
    pin exists and its role (signal / power / clock).
    """
    for m in _RE_MACRO.finditer(text):
        name = m.group(1)
        body = m.group(2)
        macro = LefMacro(name=name)

        cm = _RE_MACRO_CLASS.search(body)
        if cm:
            macro.class_type = cm.group(1).strip()

        fm = _RE_MACRO_FOREIGN.search(body)
        if fm:
            macro.foreign = fm.group(1)

        om = _RE_MACRO_ORIGIN.search(body)
        if om:
            try:
                macro.origin_x = float(om.group(1))
                macro.origin_y = float(om.group(2))
            except ValueError:
                pass

        sm = _RE_MACRO_SIZE.search(body)
        if sm:
            try:
                macro.width = float(sm.group(1))
                macro.height = float(sm.group(2))
            except ValueError:
                pass

        stm = _RE_MACRO_SITE.search(body)
        if stm:
            macro.site = stm.group(1)

        ym = _RE_MACRO_SYM.search(body)
        if ym:
            macro.symmetry = ym.group(1).split()

        # Pins.
        for pm in _RE_PIN_BLOCK.finditer(body):
            pin = LefPin(name=pm.group(1))
            pbody = pm.group(2)

            dm = _RE_PIN_DIR.search(pbody)
            if dm:
                pin.direction = dm.group(1)

            um = _RE_PIN_USE.search(pbody)
            if um:
                pin.use = um.group(1)

            macro.pins.append(pin)

        lib.macros[name] = macro


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def build_macro_size_map(lib: LefLibrary) -> dict[str, tuple[float, float]]:
    """Flatten a library to a ``{macro_name: (width, height)}`` dict.

    The layout viewer uses this map to size placed cells at the correct
    physical footprint.
    """
    return {name: (m.width, m.height) for name, m in lib.macros.items()}


def find_lef_files(search_dirs: list[Path]) -> list[Path]:
    """Return all LEF files found in the given search directories.

    Used by the layout viewer to auto-discover library LEFs next to a DEF.
    """
    found: list[Path] = []
    for d in search_dirs:
        if not d.exists():
            continue
        for pat in ("*.lef", "*.tlef"):
            found.extend(d.glob(pat))
    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in found:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(f)
    return unique


__all__ = [
    "LefPin",
    "LefMacro",
    "LefSite",
    "LefLayer",
    "LefLibrary",
    "parse_lef",
    "parse_lef_text",
    "parse_lef_directory",
    "build_macro_size_map",
    "find_lef_files",
]
