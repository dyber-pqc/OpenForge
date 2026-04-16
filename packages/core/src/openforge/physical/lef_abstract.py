"""LEF abstract generation for hierarchical P&R.

Given a finished block (DEF) and the technology / cell LEF, this
module extracts a minimal ``MACRO`` definition that describes the
block's outline, its pin geometry on the top metal layer, and the
routing obstructions on lower metal layers. The resulting file is
syntactically valid LEF and can be loaded by OpenROAD via
``read_lef block.abstract.lef``.

The extraction here is deliberately conservative: we prefer emitting
a slightly-larger blockage that over-approximates the real routed
area rather than miss a wire. That's the correct behaviour for a
hierarchical flow where the top level must not re-route over
internal nets.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class LefPin(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    direction: str = "INOUT"  # INPUT | OUTPUT | INOUT
    use: str = "SIGNAL"  # SIGNAL | CLOCK | POWER | GROUND
    layer: str = "met4"
    rects: list[tuple[float, float, float, float]] = Field(default_factory=list)


class LefObs(BaseModel):
    model_config = ConfigDict(extra="allow")

    layer: str
    rects: list[tuple[float, float, float, float]] = Field(default_factory=list)


class LefAbstract(BaseModel):
    """In-memory representation of a LEF MACRO abstract."""

    model_config = ConfigDict(extra="allow")

    macro_name: str
    width_um: float
    height_um: float
    site: str = "unithd"
    pins: list[LefPin] = Field(default_factory=list)
    obs: list[LefObs] = Field(default_factory=list)
    origin: tuple[float, float] = (0.0, 0.0)

    # ---- rendering ------------------------------------------------------

    def to_lef(self) -> str:
        lines: list[str] = []
        lines.append("VERSION 5.8 ;")
        lines.append('BUSBITCHARS "[]" ;')
        lines.append('DIVIDERCHAR "/" ;')
        lines.append("")
        lines.append(f"MACRO {self.macro_name}")
        lines.append("  CLASS BLOCK ;")
        lines.append(f"  ORIGIN {self.origin[0]:.3f} {self.origin[1]:.3f} ;")
        lines.append(f"  FOREIGN {self.macro_name} {self.origin[0]:.3f} {self.origin[1]:.3f} ;")
        lines.append(f"  SIZE {self.width_um:.3f} BY {self.height_um:.3f} ;")
        lines.append(f"  SITE {self.site} ;")
        lines.append("  SYMMETRY X Y R90 ;")
        for pin in self.pins:
            lines.append(f"  PIN {pin.name}")
            lines.append(f"    DIRECTION {pin.direction} ;")
            lines.append(f"    USE {pin.use} ;")
            lines.append("    PORT")
            lines.append(f"      LAYER {pin.layer} ;")
            for r in pin.rects:
                lines.append("      RECT {:.3f} {:.3f} {:.3f} {:.3f} ;".format(*r))
            lines.append("    END")
            lines.append(f"  END {pin.name}")
        if self.obs:
            lines.append("  OBS")
            for ob in self.obs:
                lines.append(f"    LAYER {ob.layer} ;")
                for r in ob.rects:
                    lines.append("    RECT {:.3f} {:.3f} {:.3f} {:.3f} ;".format(*r))
            lines.append("  END")
        lines.append(f"END {self.macro_name}")
        lines.append("")
        lines.append("END LIBRARY")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# DEF parsing
# ---------------------------------------------------------------------------


_DESIGN_RE = re.compile(r"^\s*DESIGN\s+(\S+)\s*;")
_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
_DIEAREA_RE = re.compile(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)")
_PINS_BEGIN_RE = re.compile(r"^\s*PINS\s+(\d+)\s*;")
_PINS_END_RE = re.compile(r"^\s*END\s+PINS")
_PIN_LINE_RE = re.compile(r"^\s*-\s*(\S+)\s*\+\s*NET\s+(\S+)")
_DIR_RE = re.compile(r"DIRECTION\s+(INPUT|OUTPUT|INOUT)")
_USE_RE = re.compile(r"USE\s+(\w+)")
_LAYER_RE = re.compile(r"LAYER\s+(\S+)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)")
_PLACED_RE = re.compile(r"PLACED\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)")
_NETS_BEGIN_RE = re.compile(r"^\s*(SPECIALNETS|NETS)\s+(\d+)\s*;")
_NETS_END_RE = re.compile(r"^\s*END\s+(SPECIALNETS|NETS)")
_ROUTED_LAYER_RE = re.compile(r"\b(met\d+|metal\d+|M\d+|li\d+)\b")


class _DefData:
    def __init__(self) -> None:
        self.design: str = "block"
        self.units: int = 1000  # DBU per micron
        self.diearea: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.pins: list[dict] = []
        self.routing_layers: set[str] = set()


def _parse_def(def_path: Path) -> _DefData:
    data = _DefData()
    try:
        text = def_path.read_text(errors="ignore")
    except OSError:
        return data

    lines = text.splitlines()
    i = 0
    n = len(lines)
    in_pins = False
    in_nets = False
    current_pin: dict | None = None

    while i < n:
        line = lines[i]
        if not in_pins and not in_nets:
            m = _DESIGN_RE.match(line)
            if m:
                data.design = m.group(1)
            m = _UNITS_RE.match(line)
            if m:
                data.units = int(m.group(1))
            m = _DIEAREA_RE.search(line)
            if m:
                data.diearea = (
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                )
            if _PINS_BEGIN_RE.match(line):
                in_pins = True
                i += 1
                continue
            if _NETS_BEGIN_RE.match(line):
                in_nets = True
                i += 1
                continue
        elif in_pins:
            if _PINS_END_RE.match(line):
                if current_pin:
                    data.pins.append(current_pin)
                    current_pin = None
                in_pins = False
                i += 1
                continue
            m = _PIN_LINE_RE.match(line)
            if m:
                if current_pin:
                    data.pins.append(current_pin)
                current_pin = {
                    "name": m.group(1),
                    "net": m.group(2),
                    "direction": "INOUT",
                    "use": "SIGNAL",
                    "layer": "met4",
                    "rect": (0, 0, 0, 0),
                    "placed": (0, 0),
                    "orient": "N",
                }
            if current_pin is not None:
                m = _DIR_RE.search(line)
                if m:
                    current_pin["direction"] = m.group(1)
                m = _USE_RE.search(line)
                if m:
                    current_pin["use"] = m.group(1)
                m = _LAYER_RE.search(line)
                if m:
                    current_pin["layer"] = m.group(1)
                    current_pin["rect"] = (
                        int(m.group(2)),
                        int(m.group(3)),
                        int(m.group(4)),
                        int(m.group(5)),
                    )
                m = _PLACED_RE.search(line)
                if m:
                    current_pin["placed"] = (int(m.group(1)), int(m.group(2)))
                    current_pin["orient"] = m.group(3)
        elif in_nets:
            if _NETS_END_RE.match(line):
                in_nets = False
                i += 1
                continue
            for m in _ROUTED_LAYER_RE.finditer(line):
                data.routing_layers.add(m.group(1))
        i += 1
    return data


def _dbu_to_um(value: int, units: int) -> float:
    if units <= 0:
        return float(value)
    return value / units


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_abstract_lef(def_path: Path, lef_path: Path, output: Path) -> LefAbstract:
    """Build a LEF abstract for a finished block DEF.

    ``lef_path`` is the cell LEF the block was placed against; we don't
    parse its full content but note its location so future enrichment
    (e.g. tracking track grids) has a hook.
    """
    def_data = _parse_def(Path(def_path))
    llx, lly, urx, ury = def_data.diearea
    width = _dbu_to_um(urx - llx, def_data.units)
    height = _dbu_to_um(ury - lly, def_data.units)
    if width <= 0:
        width = 100.0
    if height <= 0:
        height = 100.0

    pins: list[LefPin] = []
    for pin in def_data.pins:
        px, py = pin["placed"]
        rx1, ry1, rx2, ry2 = pin["rect"]
        abs_rect = (
            _dbu_to_um(px + rx1 - llx, def_data.units),
            _dbu_to_um(py + ry1 - lly, def_data.units),
            _dbu_to_um(px + rx2 - llx, def_data.units),
            _dbu_to_um(py + ry2 - lly, def_data.units),
        )
        # Normalise zero-area pins to a minimum square
        x1, y1, x2, y2 = abs_rect
        if x2 <= x1:
            x2 = x1 + 0.2
        if y2 <= y1:
            y2 = y1 + 0.2
        pins.append(
            LefPin(
                name=pin["name"],
                direction=pin["direction"],
                use=pin["use"],
                layer=pin["layer"],
                rects=[(x1, y1, x2, y2)],
            )
        )

    # Obstructions: one large rectangle per routing layer that was
    # actually used. This is a conservative abstraction that guarantees
    # the top-level router will not reroute over internal nets.
    obs: list[LefObs] = []
    layers = (
        sorted(def_data.routing_layers)
        if def_data.routing_layers
        else [
            "met1",
            "met2",
            "met3",
        ]
    )
    for layer in layers:
        obs.append(
            LefObs(
                layer=layer,
                rects=[(0.0, 0.0, width, height)],
            )
        )

    macro = LefAbstract(
        macro_name=def_data.design,
        width_um=width,
        height_um=height,
        pins=pins,
        obs=obs,
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(macro.to_lef())
    return macro


# ---- reader ---------------------------------------------------------------


_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)")
_SIZE_RE = re.compile(r"^\s*SIZE\s+([-\d.]+)\s+BY\s+([-\d.]+)")
_SITE2_RE = re.compile(r"^\s*SITE\s+(\S+)")
_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)")
_DIRECTION2_RE = re.compile(r"^\s*DIRECTION\s+(\w+)")
_USE2_RE = re.compile(r"^\s*USE\s+(\w+)")
_LAYER2_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;")
_RECT_RE = re.compile(r"^\s*RECT\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)")
_END_PIN_RE = re.compile(r"^\s*END\s+(\S+)\s*$")
_OBS_BEGIN_RE = re.compile(r"^\s*OBS\s*$")
_OBS_END_RE = re.compile(r"^\s*END\s*$")
_END_MACRO_RE = re.compile(r"^\s*END\s+(\S+)\s*$")


def read_abstract_lef(path: Path) -> LefAbstract:
    """Load a LEF abstract previously written by :func:`generate_abstract_lef`.

    This is not a general-purpose LEF parser — it covers exactly the
    subset we emit here. It is tolerant of extra whitespace but will
    raise :class:`ValueError` if the header MACRO line cannot be found.
    """
    text = Path(path).read_text(errors="ignore")
    lines = text.splitlines()
    name = ""
    width = height = 0.0
    site = "unithd"
    pins: list[LefPin] = []
    obs: list[LefObs] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _MACRO_RE.match(line)
        if m:
            name = m.group(1)
            i += 1
            continue
        m = _SIZE_RE.match(line)
        if m:
            width = float(m.group(1))
            height = float(m.group(2))
            i += 1
            continue
        m = _SITE2_RE.match(line)
        if m:
            site = m.group(1)
            i += 1
            continue
        m = _PIN_RE.match(line)
        if m:
            pin_name = m.group(1)
            pin = LefPin(name=pin_name)
            i += 1
            while i < n:
                sub = lines[i]
                em = _END_PIN_RE.match(sub)
                if em and em.group(1) == pin_name:
                    i += 1
                    break
                dm = _DIRECTION2_RE.match(sub)
                if dm:
                    pin.direction = dm.group(1)
                um = _USE2_RE.match(sub)
                if um:
                    pin.use = um.group(1)
                lm = _LAYER2_RE.match(sub)
                if lm:
                    pin.layer = lm.group(1)
                rm = _RECT_RE.match(sub)
                if rm:
                    pin.rects.append(
                        (
                            float(rm.group(1)),
                            float(rm.group(2)),
                            float(rm.group(3)),
                            float(rm.group(4)),
                        )
                    )
                i += 1
            pins.append(pin)
            continue
        if _OBS_BEGIN_RE.match(line):
            i += 1
            current_layer: str | None = None
            current: LefObs | None = None
            while i < n and not _END_MACRO_RE.match(lines[i]):
                sub = lines[i]
                lm = _LAYER2_RE.match(sub)
                if lm:
                    if current is not None:
                        obs.append(current)
                    current_layer = lm.group(1)
                    current = LefObs(layer=current_layer)
                rm = _RECT_RE.match(sub)
                if rm and current is not None:
                    current.rects.append(
                        (
                            float(rm.group(1)),
                            float(rm.group(2)),
                            float(rm.group(3)),
                            float(rm.group(4)),
                        )
                    )
                if _OBS_END_RE.match(sub) and current_layer is None:
                    i += 1
                    break
                i += 1
            if current is not None:
                obs.append(current)
            continue
        i += 1
    if not name:
        raise ValueError(f"no MACRO found in {path}")
    return LefAbstract(
        macro_name=name,
        width_um=width,
        height_um=height,
        site=site,
        pins=pins,
        obs=obs,
    )


# ---- composition ----------------------------------------------------------


def merge_blocks_to_top(top_def: Path, blocks: dict[str, LefAbstract], output: Path) -> None:
    """Compose block abstracts into a top-level placement DEF.

    Places blocks in a simple shelf layout: left-to-right, wrapping to
    a new row whenever the running width would exceed four times the
    widest block. The result is a syntactically valid DEF that can be
    read by OpenROAD and then refined with proper floorplanning.
    """
    names = list(blocks.keys())
    if not names:
        widths = [100.0]
    else:
        widths = [blocks[n].width_um for n in names]
        [blocks[n].height_um for n in names]
    max_width = max(widths) if widths else 100.0
    shelf_limit = max(max_width * 4.0, max_width + 1.0)

    placements: list[tuple[str, float, float]] = []
    cursor_x = 10.0
    cursor_y = 10.0
    row_h = 0.0
    total_w = cursor_x
    total_h = cursor_y
    for name in names:
        w = blocks[name].width_um
        h = blocks[name].height_um
        if cursor_x + w > shelf_limit and cursor_x > 10.0:
            cursor_x = 10.0
            cursor_y += row_h + 10.0
            row_h = 0.0
        placements.append((name, cursor_x, cursor_y))
        cursor_x += w + 10.0
        row_h = max(row_h, h)
        total_w = max(total_w, cursor_x)
        total_h = max(total_h, cursor_y + h + 10.0)

    units = 1000
    llx = 0
    lly = 0
    urx = int(max(total_w + 10.0, 100.0) * units)
    ury = int(max(total_h + 10.0, 100.0) * units)

    design = Path(top_def).stem.replace(".top", "") or "top"
    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"DESIGN {design} ;",
        f"UNITS DISTANCE MICRONS {units} ;",
        f"DIEAREA ( {llx} {lly} ) ( {urx} {ury} ) ;",
        "",
        f"COMPONENTS {len(placements)} ;",
    ]
    for name, x, y in placements:
        dbu_x = int(x * units)
        dbu_y = int(y * units)
        lines.append(f"    - u_{name} {name} + PLACED ( {dbu_x} {dbu_y} ) N ;")
    lines.append("END COMPONENTS")
    lines.append("")
    lines.append("END DESIGN")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(lines) + "\n")


__all__ = [
    "LefAbstract",
    "LefPin",
    "LefObs",
    "generate_abstract_lef",
    "read_abstract_lef",
    "merge_blocks_to_top",
]
