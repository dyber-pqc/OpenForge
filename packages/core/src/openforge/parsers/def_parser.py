"""DEF (Design Exchange Format) parser.

Parses DEF files produced by place-and-route tools such as OpenROAD,
extracting component placements, pin definitions, nets with routing,
rows, tracks, and die area for layout visualization.

Designed for efficiency with large DEF files (100K+ components) using
line-by-line streaming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Orientation(StrEnum):
    N = "N"
    S = "S"
    E = "E"
    W = "W"
    FN = "FN"
    FS = "FS"
    FE = "FE"
    FW = "FW"


class ComponentSource(StrEnum):
    NETLIST = "NETLIST"
    DIST = "DIST"
    USER = "USER"
    TIMING = "TIMING"


class PinDirection(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    INOUT = "INOUT"
    FEEDTHRU = "FEEDTHRU"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DEFComponent:
    """A placed component (cell instance) in the design."""

    name: str = ""
    cell_type: str = ""
    placed: bool = False
    fixed: bool = False
    x: int = 0
    y: int = 0
    orientation: str = "N"
    source: str = "NETLIST"
    weight: int = 0


@dataclass
class DEFPin:
    """An external pin of the design."""

    name: str = ""
    net: str = ""
    direction: str = ""
    use: str = ""
    layer: str = ""
    placed: bool = False
    fixed: bool = False
    x: int = 0
    y: int = 0
    orientation: str = "N"


@dataclass
class DEFRouteSegment:
    """A segment of a routed net."""

    layer: str = ""
    width: int = 0
    points: list[tuple[int, int]] = field(default_factory=list)
    via: str | None = None


@dataclass
class DEFNet:
    """A signal net connecting component pins."""

    name: str = ""
    connections: list[tuple[str, str]] = field(default_factory=list)
    routed_segments: list[DEFRouteSegment] = field(default_factory=list)
    weight: int = 0
    use: str = ""


@dataclass
class DEFRow:
    """A placement row definition."""

    name: str = ""
    site: str = ""
    origin_x: int = 0
    origin_y: int = 0
    orientation: str = "N"
    num_x: int = 1
    num_y: int = 1
    step_x: int = 0
    step_y: int = 0


@dataclass
class DEFTrack:
    """A routing track definition."""

    direction: str = ""  # X or Y
    start: int = 0
    num_tracks: int = 0
    step: int = 0
    layer: str = ""


@dataclass
class DEFBlockage:
    """A placement or routing blockage."""

    type: str = ""  # PLACEMENT or ROUTING
    layer: str = ""
    rects: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class DEFData:
    """Top-level DEF file data."""

    version: str = ""
    design_name: str = ""
    units: int = 1000
    die_area: tuple[int, int, int, int] = (0, 0, 0, 0)
    components: list[DEFComponent] = field(default_factory=list)
    pins: list[DEFPin] = field(default_factory=list)
    nets: list[DEFNet] = field(default_factory=list)
    special_nets: list[DEFNet] = field(default_factory=list)
    rows: list[DEFRow] = field(default_factory=list)
    tracks: list[DEFTrack] = field(default_factory=list)
    blockages: list[DEFBlockage] = field(default_factory=list)

    # Lookup caches (built lazily)
    _comp_index: dict[str, DEFComponent] = field(
        default_factory=dict, repr=False,
    )
    _net_index: dict[str, DEFNet] = field(
        default_factory=dict, repr=False,
    )

    def get_component(self, name: str) -> DEFComponent | None:
        """Find a component by instance name."""
        if not self._comp_index and self.components:
            self._comp_index = {c.name: c for c in self.components}
        return self._comp_index.get(name)

    def get_net(self, name: str) -> DEFNet | None:
        """Find a net by name."""
        if not self._net_index and self.nets:
            self._net_index = {n.name: n for n in self.nets}
        return self._net_index.get(name)

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        """Return the die area bounding box (x0, y0, x1, y1)."""
        return self.die_area

    def get_utilization(self) -> float:
        """Return placed-area / die-area ratio."""
        x0, y0, x1, y1 = self.die_area
        die_w = abs(x1 - x0)
        die_h = abs(y1 - y0)
        die_area = die_w * die_h
        if die_area == 0:
            return 0.0
        placed_count = sum(1 for c in self.components if c.placed or c.fixed)
        # Without LEF macro sizes we approximate by count ratio
        # A proper calculation requires cross-referencing with LEF data
        total = len(self.components)
        return placed_count / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_RE_SEMICOLON = re.compile(r"\s*;\s*$")


class DEFParser:
    """Line-by-line streaming parser for DEF files."""

    def parse(self, path: str | Path) -> DEFData:
        """Parse a DEF file and return DEFData."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"DEF file not found: {path}")

        data = DEFData()

        with open(path, encoding="utf-8", errors="replace") as f:
            buf = ""
            for raw_line in f:
                # Strip comments
                line = raw_line.split("#")[0].strip()
                if not line:
                    continue

                buf += " " + line if buf else line

                # Accumulate until we see a semicolon or section keyword
                if not (buf.endswith(";") or self._is_section_start(buf)):
                    continue

                self._dispatch(buf.strip(), data, f)
                buf = ""

            # Handle leftover
            if buf.strip():
                self._dispatch(buf.strip(), data, f)

        return data

    @staticmethod
    def _is_section_start(line: str) -> bool:
        upper = line.split()[0].upper() if line.split() else ""
        return upper in (
            "COMPONENTS", "PINS", "NETS", "SPECIALNETS",
            "BLOCKAGES", "END",
        )

    def _dispatch(self, stmt: str, data: DEFData, f) -> None:
        """Route a statement to the appropriate handler."""
        tokens = stmt.split()
        if not tokens:
            return
        kw = tokens[0].upper()

        if kw == "VERSION" and len(tokens) >= 2:
            data.version = tokens[1].rstrip(";")

        elif kw == "DESIGN" and len(tokens) >= 2:
            data.design_name = tokens[1].rstrip(";")

        elif kw == "UNITS" and "MICRONS" in stmt.upper():
            m = re.search(r"MICRONS\s+(\d+)", stmt, re.IGNORECASE)
            if m:
                data.units = int(m.group(1))

        elif kw == "DIEAREA":
            nums = re.findall(r"-?\d+", stmt)
            if len(nums) >= 4:
                data.die_area = (
                    int(nums[0]), int(nums[1]),
                    int(nums[2]), int(nums[3]),
                )

        elif kw == "ROW":
            row = self._parse_row(tokens)
            if row:
                data.rows.append(row)

        elif kw == "TRACKS":
            track = self._parse_track(tokens)
            if track:
                data.tracks.append(track)

        elif kw == "COMPONENTS":
            self._parse_components_section(f, data)

        elif kw == "PINS":
            self._parse_pins_section(f, data)

        elif kw == "NETS":
            self._parse_nets_section(f, data, is_special=False)

        elif kw == "SPECIALNETS":
            self._parse_nets_section(f, data, is_special=True)

        elif kw == "BLOCKAGES":
            self._parse_blockages_section(f, data)

    # ---------------------------------------------------------------
    # Section parsers
    # ---------------------------------------------------------------

    def _parse_components_section(self, f, data: DEFData) -> None:
        """Parse the COMPONENTS ... END COMPONENTS section."""
        buf = ""
        for raw_line in f:
            line = raw_line.split("#")[0].strip()
            if not line:
                continue

            if line.upper().startswith("END COMPONENTS"):
                break

            buf += " " + line if buf else line
            if not buf.endswith(";"):
                continue

            comp = self._parse_component_stmt(buf.strip())
            if comp:
                data.components.append(comp)
            buf = ""

    @staticmethod
    def _parse_component_stmt(stmt: str) -> DEFComponent | None:
        stmt = stmt.rstrip(";").strip()
        if not stmt.startswith("-"):
            return None
        tokens = stmt.split()
        if len(tokens) < 3:
            return None

        comp = DEFComponent(name=tokens[1], cell_type=tokens[2])
        i = 3
        while i < len(tokens):
            tok = tokens[i].upper()
            if tok == "+":
                i += 1
                continue
            if tok in ("PLACED", "FIXED", "COVER") and i + 4 < len(tokens):
                if tok == "FIXED":
                    comp.fixed = True
                    comp.placed = True
                elif tok == "COVER":
                    comp.fixed = True
                    comp.placed = True
                else:
                    comp.placed = True
                # ( x y ) orient
                if tokens[i + 1] == "(":
                    try:
                        comp.x = int(tokens[i + 2])
                        comp.y = int(tokens[i + 3])
                    except (ValueError, IndexError):
                        pass
                    # Find closing paren
                    j = i + 2
                    while j < len(tokens) and tokens[j] != ")":
                        j += 1
                    if j + 1 < len(tokens):
                        comp.orientation = tokens[j + 1]
                    i = j + 2
                else:
                    i += 1
            elif tok == "UNPLACED":
                comp.placed = False
                i += 1
            elif tok == "SOURCE" and i + 1 < len(tokens):
                comp.source = tokens[i + 1].upper()
                i += 2
            elif tok == "WEIGHT" and i + 1 < len(tokens):
                try:
                    comp.weight = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                i += 1

        return comp

    def _parse_pins_section(self, f, data: DEFData) -> None:
        """Parse the PINS ... END PINS section."""
        buf = ""
        for raw_line in f:
            line = raw_line.split("#")[0].strip()
            if not line:
                continue
            if line.upper().startswith("END PINS"):
                break
            buf += " " + line if buf else line
            if not buf.endswith(";"):
                continue
            pin = self._parse_pin_stmt(buf.strip())
            if pin:
                data.pins.append(pin)
            buf = ""

    @staticmethod
    def _parse_pin_stmt(stmt: str) -> DEFPin | None:
        stmt = stmt.rstrip(";").strip()
        if not stmt.startswith("-"):
            return None
        tokens = stmt.split()
        if len(tokens) < 2:
            return None

        pin = DEFPin(name=tokens[1])
        i = 2
        while i < len(tokens):
            tok = tokens[i].upper()
            if tok == "+":
                i += 1
                continue
            if tok == "NET" and i + 1 < len(tokens):
                pin.net = tokens[i + 1]
                i += 2
            elif tok == "DIRECTION" and i + 1 < len(tokens):
                pin.direction = tokens[i + 1].upper()
                i += 2
            elif tok == "USE" and i + 1 < len(tokens):
                pin.use = tokens[i + 1].upper()
                i += 2
            elif tok == "LAYER" and i + 1 < len(tokens):
                pin.layer = tokens[i + 1]
                i += 2
            elif tok in ("PLACED", "FIXED") and i + 1 < len(tokens):
                pin.placed = True
                if tok == "FIXED":
                    pin.fixed = True
                if tokens[i + 1] == "(":
                    try:
                        pin.x = int(tokens[i + 2])
                        pin.y = int(tokens[i + 3])
                    except (ValueError, IndexError):
                        pass
                    j = i + 2
                    while j < len(tokens) and tokens[j] != ")":
                        j += 1
                    if j + 1 < len(tokens):
                        pin.orientation = tokens[j + 1]
                    i = j + 2
                else:
                    i += 1
            else:
                i += 1

        return pin

    def _parse_nets_section(
        self, f, data: DEFData, *, is_special: bool,
    ) -> None:
        """Parse NETS or SPECIALNETS section."""
        end_kw = "END SPECIALNETS" if is_special else "END NETS"
        buf = ""
        for raw_line in f:
            line = raw_line.split("#")[0].strip()
            if not line:
                continue
            if line.upper().startswith(end_kw):
                break
            buf += " " + line if buf else line
            if not buf.endswith(";"):
                continue
            net = self._parse_net_stmt(buf.strip())
            if net:
                if is_special:
                    data.special_nets.append(net)
                else:
                    data.nets.append(net)
            buf = ""

    @staticmethod
    def _parse_net_stmt(stmt: str) -> DEFNet | None:
        stmt = stmt.rstrip(";").strip()
        if not stmt.startswith("-"):
            return None
        tokens = stmt.split()
        if len(tokens) < 2:
            return None

        net = DEFNet(name=tokens[1])
        i = 2

        # Parse connections: ( comp pin ) ( comp pin ) ...
        while i < len(tokens):
            if tokens[i] == "(":
                if i + 2 < len(tokens):
                    comp = tokens[i + 1]
                    pin_name = tokens[i + 2]
                    net.connections.append((comp, pin_name))
                j = i + 1
                while j < len(tokens) and tokens[j] != ")":
                    j += 1
                i = j + 1
            elif tokens[i] == "+":
                i += 1
                break
            else:
                i += 1

        # Parse properties and routing after '+'
        while i < len(tokens):
            tok = tokens[i].upper()
            if tok == "+":
                i += 1
                continue
            if tok == "USE" and i + 1 < len(tokens):
                net.use = tokens[i + 1].upper()
                i += 2
            elif tok == "WEIGHT" and i + 1 < len(tokens):
                try:
                    net.weight = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif tok in ("ROUTED", "NEW", "FIXED", "COVER", "NOSHIELD"):
                i += 1
                seg = DEFRouteSegment()
                # Next token should be layer name
                if i < len(tokens) and not tokens[i].startswith("("):
                    seg.layer = tokens[i]
                    i += 1
                # Parse route points
                while i < len(tokens):
                    if tokens[i] == "(":
                        pts: list[str] = []
                        i += 1
                        while i < len(tokens) and tokens[i] != ")":
                            pts.append(tokens[i])
                            i += 1
                        i += 1  # skip )
                        if len(pts) >= 2:
                            try:
                                px = int(pts[0]) if pts[0] != "*" else seg.points[-1][0] if seg.points else 0
                                py = int(pts[1]) if pts[1] != "*" else seg.points[-1][1] if seg.points else 0
                                seg.points.append((px, py))
                            except (ValueError, IndexError):
                                pass
                    elif tokens[i].upper() == "NEW" or tokens[i] == "+":
                        break
                    elif not tokens[i].startswith("(") and tokens[i] not in ("+",):
                        # Could be a via name
                        seg.via = tokens[i]
                        i += 1
                    else:
                        i += 1
                if seg.layer or seg.points:
                    net.routed_segments.append(seg)
            else:
                i += 1

        return net

    def _parse_blockages_section(self, f, data: DEFData) -> None:
        """Parse the BLOCKAGES section."""
        buf = ""
        for raw_line in f:
            line = raw_line.split("#")[0].strip()
            if not line:
                continue
            if line.upper().startswith("END BLOCKAGES"):
                break
            buf += " " + line if buf else line
            if not buf.endswith(";"):
                continue
            blk = self._parse_blockage_stmt(buf.strip())
            if blk:
                data.blockages.append(blk)
            buf = ""

    @staticmethod
    def _parse_blockage_stmt(stmt: str) -> DEFBlockage | None:
        stmt = stmt.rstrip(";").strip()
        if not stmt.startswith("-"):
            return None
        tokens = stmt.split()
        blk = DEFBlockage()
        i = 1
        while i < len(tokens):
            tok = tokens[i].upper()
            if tok == "+":
                i += 1
                continue
            if tok in ("PLACEMENT", "ROUTING"):
                blk.type = tok
                i += 1
            elif tok == "LAYER" and i + 1 < len(tokens):
                blk.layer = tokens[i + 1]
                i += 2
            elif tok == "RECT" and i + 4 < len(tokens):
                try:
                    r = (
                        int(tokens[i + 1]),
                        int(tokens[i + 2]),
                        int(tokens[i + 3]),
                        int(tokens[i + 4]),
                    )
                    blk.rects.append(r)
                except ValueError:
                    pass
                i += 5
            else:
                i += 1
        return blk if blk.type else None

    # ---------------------------------------------------------------
    # Single-statement parsers
    # ---------------------------------------------------------------

    @staticmethod
    def _parse_row(tokens: list[str]) -> DEFRow | None:
        """Parse a ROW statement."""
        # ROW name site origX origY orient DO numX BY numY STEP stepX stepY ;
        if len(tokens) < 8:
            return None
        row = DEFRow(name=tokens[1], site=tokens[2])
        try:
            row.origin_x = int(tokens[3])
            row.origin_y = int(tokens[4])
            row.orientation = tokens[5]
        except (ValueError, IndexError):
            return None

        # Look for DO ... BY ... STEP ...
        i = 6
        while i < len(tokens):
            tok = tokens[i].upper().rstrip(";")
            if tok == "DO" and i + 1 < len(tokens):
                try:
                    row.num_x = int(tokens[i + 1].rstrip(";"))
                except ValueError:
                    pass
                i += 2
            elif tok == "BY" and i + 1 < len(tokens):
                try:
                    row.num_y = int(tokens[i + 1].rstrip(";"))
                except ValueError:
                    pass
                i += 2
            elif tok == "STEP" and i + 2 < len(tokens):
                try:
                    row.step_x = int(tokens[i + 1].rstrip(";"))
                    row.step_y = int(tokens[i + 2].rstrip(";"))
                except ValueError:
                    pass
                i += 3
            else:
                i += 1

        return row

    @staticmethod
    def _parse_track(tokens: list[str]) -> DEFTrack | None:
        """Parse a TRACKS statement."""
        # TRACKS X|Y start DO numTracks STEP step LAYER layerName ;
        if len(tokens) < 8:
            return None
        track = DEFTrack(direction=tokens[1].upper())
        try:
            track.start = int(tokens[2])
        except ValueError:
            return None

        i = 3
        while i < len(tokens):
            tok = tokens[i].upper().rstrip(";")
            if tok == "DO" and i + 1 < len(tokens):
                try:
                    track.num_tracks = int(tokens[i + 1].rstrip(";"))
                except ValueError:
                    pass
                i += 2
            elif tok == "STEP" and i + 1 < len(tokens):
                try:
                    track.step = int(tokens[i + 1].rstrip(";"))
                except ValueError:
                    pass
                i += 2
            elif tok == "LAYER" and i + 1 < len(tokens):
                track.layer = tokens[i + 1].rstrip(";")
                i += 2
            else:
                i += 1

        return track
