"""LEF (Library Exchange Format) parser.

Parses LEF files used by OpenROAD and other physical design tools,
extracting layer definitions, via rules, macro (cell) geometries,
and site definitions for layout visualization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LEFLayerType(StrEnum):
    ROUTING = "ROUTING"
    CUT = "CUT"
    OVERLAP = "OVERLAP"
    MASTERSLICE = "MASTERSLICE"
    IMPLANT = "IMPLANT"


class LEFDirection(StrEnum):
    HORIZONTAL = "HORIZONTAL"
    VERTICAL = "VERTICAL"


class LEFMacroClass(StrEnum):
    CORE = "CORE"
    BLOCK = "BLOCK"
    PAD = "PAD"
    PAD_INPUT = "PAD INPUT"
    PAD_OUTPUT = "PAD OUTPUT"
    PAD_INOUT = "PAD INOUT"
    PAD_POWER = "PAD POWER"
    PAD_SPACER = "PAD SPACER"
    PAD_AREAIO = "PAD AREAIO"
    ENDCAP = "ENDCAP"
    COVER = "COVER"
    RING = "RING"


class LEFPinUse(StrEnum):
    SIGNAL = "SIGNAL"
    POWER = "POWER"
    GROUND = "GROUND"
    CLOCK = "CLOCK"
    ANALOG = "ANALOG"


class LEFPinDirection(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    INOUT = "INOUT"
    FEEDTHRU = "FEEDTHRU"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

Rect = tuple[float, float, float, float]  # (x0, y0, x1, y1)


@dataclass
class LEFLayer:
    """A technology layer definition."""

    name: str = ""
    type: str = ""
    direction: str = ""
    pitch: float = 0.0
    width: float = 0.0
    spacing: float = 0.0
    min_width: float = 0.0
    offset: float = 0.0
    resistance: float = 0.0
    capacitance: float = 0.0
    thickness: float = 0.0


@dataclass
class LEFViaLayer:
    """Geometry on one layer within a via definition."""

    layer_name: str = ""
    rects: list[Rect] = field(default_factory=list)


@dataclass
class LEFVia:
    """A via definition connecting two routing layers."""

    name: str = ""
    is_default: bool = False
    layers: list[LEFViaLayer] = field(default_factory=list)


@dataclass
class LEFPort:
    """A port geometry within a pin."""

    layer: str = ""
    rects: list[Rect] = field(default_factory=list)


@dataclass
class LEFPin:
    """A pin within a macro."""

    name: str = ""
    direction: str = ""
    use: str = "SIGNAL"
    shape: str = ""
    ports: list[LEFPort] = field(default_factory=list)


@dataclass
class LEFObs:
    """An obstruction layer within a macro."""

    layer: str = ""
    rects: list[Rect] = field(default_factory=list)


@dataclass
class LEFMacro:
    """A macro (standard cell or block) definition."""

    name: str = ""
    class_: str = ""
    size_width: float = 0.0
    size_height: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    symmetry: str = ""
    site: str = ""
    pins: list[LEFPin] = field(default_factory=list)
    obs: list[LEFObs] = field(default_factory=list)

    @property
    def size(self) -> tuple[float, float]:
        return (self.size_width, self.size_height)

    @property
    def origin(self) -> tuple[float, float]:
        return (self.origin_x, self.origin_y)

    def get_pin(self, name: str) -> LEFPin | None:
        """Find a pin by name."""
        for pin in self.pins:
            if pin.name == name:
                return pin
        return None


@dataclass
class LEFSite:
    """A placement site definition."""

    name: str = ""
    class_: str = ""
    size_width: float = 0.0
    size_height: float = 0.0
    symmetry: str = ""

    @property
    def size(self) -> tuple[float, float]:
        return (self.size_width, self.size_height)


@dataclass
class LEFData:
    """Top-level LEF file data."""

    version: str = ""
    database_microns: int = 1000
    bus_bit_chars: str = "[]"
    divider_char: str = "/"
    layers: list[LEFLayer] = field(default_factory=list)
    vias: list[LEFVia] = field(default_factory=list)
    macros: list[LEFMacro] = field(default_factory=list)
    sites: list[LEFSite] = field(default_factory=list)

    def get_layer(self, name: str) -> LEFLayer | None:
        """Find a layer by name."""
        for layer in self.layers:
            if layer.name == name:
                return layer
        return None

    def get_macro(self, name: str) -> LEFMacro | None:
        """Find a macro by name."""
        for macro in self.macros:
            if macro.name == name:
                return macro
        return None

    def routing_layers(self) -> list[LEFLayer]:
        """Return only routing layers."""
        return [l for l in self.layers if l.type == LEFLayerType.ROUTING]

    def cut_layers(self) -> list[LEFLayer]:
        """Return only cut (via) layers."""
        return [l for l in self.layers if l.type == LEFLayerType.CUT]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class LEFParser:
    """Parser for LEF (Library Exchange Format) files."""

    def parse(self, path: str | Path) -> LEFData:
        """Parse a LEF file and return LEFData."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"LEF file not found: {path}")

        data = LEFData()
        tokens = self._tokenize(path)
        idx = 0
        total = len(tokens)

        while idx < total:
            tok = tokens[idx].upper()

            if tok == "VERSION":
                idx += 1
                if idx < total:
                    data.version = tokens[idx].rstrip(";")
                idx += 1

            elif tok == "UNITS":
                idx = self._parse_units(tokens, idx + 1, total, data)

            elif tok == "BUSBITCHARS":
                idx += 1
                if idx < total:
                    data.bus_bit_chars = tokens[idx].strip('"').rstrip(";")
                idx += 1

            elif tok == "DIVIDERCHAR":
                idx += 1
                if idx < total:
                    data.divider_char = tokens[idx].strip('"').rstrip(";")
                idx += 1

            elif tok == "LAYER":
                idx += 1
                if idx < total:
                    layer = LEFLayer(name=tokens[idx])
                    idx = self._parse_layer(tokens, idx + 1, total, layer)
                    data.layers.append(layer)

            elif tok == "VIA":
                idx += 1
                if idx < total:
                    via = LEFVia(name=tokens[idx])
                    idx += 1
                    # Check for DEFAULT keyword
                    if idx < total and tokens[idx].upper() == "DEFAULT":
                        via.is_default = True
                        idx += 1
                    idx = self._parse_via(tokens, idx, total, via)
                    data.vias.append(via)

            elif tok == "SITE":
                idx += 1
                if idx < total:
                    site = LEFSite(name=tokens[idx])
                    idx = self._parse_site(tokens, idx + 1, total, site)
                    data.sites.append(site)

            elif tok == "MACRO":
                idx += 1
                if idx < total:
                    macro = LEFMacro(name=tokens[idx])
                    idx = self._parse_macro(tokens, idx + 1, total, macro)
                    data.macros.append(macro)

            elif tok in ("END", "PROPERTYDEFINITIONS", "SPACING",
                         "MAXVIASTACK", "NONDEFAULTRULE", "MANUFACTURINGGRID"):
                idx = self._skip_to_end(tokens, idx, total, tok)

            else:
                idx += 1

        return data

    # ---------------------------------------------------------------
    # Tokenizer
    # ---------------------------------------------------------------

    @staticmethod
    def _tokenize(path: Path) -> list[str]:
        """Tokenize a LEF file, stripping comments."""
        text = path.read_text(encoding="utf-8", errors="replace")
        # Remove comments
        text = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
        return text.split()

    # ---------------------------------------------------------------
    # Section parsers
    # ---------------------------------------------------------------

    @staticmethod
    def _parse_units(
        tokens: list[str], idx: int, total: int, data: LEFData,
    ) -> int:
        while idx < total:
            tok = tokens[idx].upper()
            if tok == "END" and idx + 1 < total and tokens[idx + 1].upper() == "UNITS":
                return idx + 2
            if tok == "DATABASE":
                idx += 1
                if idx < total and tokens[idx].upper() == "MICRONS":
                    idx += 1
                    if idx < total:
                        data.database_microns = int(
                            tokens[idx].rstrip(";")
                        )
            idx += 1
        return idx

    @staticmethod
    def _parse_layer(
        tokens: list[str], idx: int, total: int, layer: LEFLayer,
    ) -> int:
        while idx < total:
            tok = tokens[idx].upper()
            if tok == "END" and idx + 1 < total and tokens[idx + 1] == layer.name:
                return idx + 2
            if tok == "TYPE" and idx + 1 < total:
                layer.type = tokens[idx + 1].rstrip(";").upper()
                idx += 2
            elif tok == "DIRECTION" and idx + 1 < total:
                layer.direction = tokens[idx + 1].rstrip(";").upper()
                idx += 2
            elif tok == "PITCH" and idx + 1 < total:
                layer.pitch = _sf(tokens[idx + 1])
                idx += 2
            elif tok == "WIDTH" and idx + 1 < total:
                layer.width = _sf(tokens[idx + 1])
                idx += 2
            elif tok == "SPACING" and idx + 1 < total:
                layer.spacing = _sf(tokens[idx + 1])
                idx += 2
            elif tok == "MINWIDTH" and idx + 1 < total:
                layer.min_width = _sf(tokens[idx + 1])
                idx += 2
            elif tok == "OFFSET" and idx + 1 < total:
                layer.offset = _sf(tokens[idx + 1])
                idx += 2
            elif tok == "RESISTANCE" and idx + 2 < total:
                # RESISTANCE RPERSQ value ;
                layer.resistance = _sf(tokens[idx + 2])
                idx += 3
            elif tok == "CAPACITANCE" and idx + 2 < total:
                layer.capacitance = _sf(tokens[idx + 2])
                idx += 3
            elif tok == "THICKNESS" and idx + 1 < total:
                layer.thickness = _sf(tokens[idx + 1])
                idx += 2
            else:
                idx += 1
        return idx

    @staticmethod
    def _parse_via(
        tokens: list[str], idx: int, total: int, via: LEFVia,
    ) -> int:
        current_layer: LEFViaLayer | None = None
        while idx < total:
            tok = tokens[idx].upper()
            if tok == "END" and idx + 1 < total and tokens[idx + 1] == via.name:
                if current_layer:
                    via.layers.append(current_layer)
                return idx + 2
            if tok == "LAYER" and idx + 1 < total:
                if current_layer:
                    via.layers.append(current_layer)
                current_layer = LEFViaLayer(
                    layer_name=tokens[idx + 1].rstrip(";")
                )
                idx += 2
            elif tok == "RECT" and idx + 4 < total and current_layer is not None:
                x0 = _sf(tokens[idx + 1])
                y0 = _sf(tokens[idx + 2])
                x1 = _sf(tokens[idx + 3])
                y1 = _sf(tokens[idx + 4])
                current_layer.rects.append((x0, y0, x1, y1))
                idx += 5
            else:
                idx += 1
        if current_layer:
            via.layers.append(current_layer)
        return idx

    @staticmethod
    def _parse_site(
        tokens: list[str], idx: int, total: int, site: LEFSite,
    ) -> int:
        while idx < total:
            tok = tokens[idx].upper()
            if tok == "END" and idx + 1 < total and tokens[idx + 1] == site.name:
                return idx + 2
            if tok == "CLASS" and idx + 1 < total:
                site.class_ = tokens[idx + 1].rstrip(";")
                idx += 2
            elif tok == "SIZE" and idx + 3 < total:
                site.size_width = _sf(tokens[idx + 1])
                # tokens[idx+2] should be "BY"
                site.size_height = _sf(tokens[idx + 3])
                idx += 4
            elif tok == "SYMMETRY" and idx + 1 < total:
                parts: list[str] = []
                idx += 1
                while idx < total and tokens[idx].rstrip(";").upper() not in (
                    "END", "CLASS", "SIZE", "SYMMETRY",
                ):
                    val = tokens[idx].rstrip(";")
                    if val:
                        parts.append(val)
                    # Check if this token had a semicolon
                    if tokens[idx].endswith(";"):
                        break
                    idx += 1
                site.symmetry = " ".join(parts)
                idx += 1
            else:
                idx += 1
        return idx

    def _parse_macro(
        self,
        tokens: list[str],
        idx: int,
        total: int,
        macro: LEFMacro,
    ) -> int:
        while idx < total:
            tok = tokens[idx].upper()
            if tok == "END" and idx + 1 < total and tokens[idx + 1] == macro.name:
                return idx + 2

            if tok == "CLASS" and idx + 1 < total:
                # CLASS may be multi-word like "PAD INPUT"
                cls_parts: list[str] = []
                idx += 1
                while idx < total:
                    val = tokens[idx].rstrip(";")
                    if not val or val.upper() in (
                        "SIZE", "ORIGIN", "SYMMETRY", "SITE", "PIN", "OBS", "END",
                    ):
                        break
                    cls_parts.append(val)
                    if tokens[idx].endswith(";"):
                        idx += 1
                        break
                    idx += 1
                macro.class_ = " ".join(cls_parts).upper()

            elif tok == "SIZE" and idx + 3 < total:
                macro.size_width = _sf(tokens[idx + 1])
                macro.size_height = _sf(tokens[idx + 3])
                idx += 4

            elif tok == "ORIGIN" and idx + 2 < total:
                macro.origin_x = _sf(tokens[idx + 1])
                macro.origin_y = _sf(tokens[idx + 2])
                idx += 3

            elif tok == "SYMMETRY":
                parts: list[str] = []
                idx += 1
                while idx < total:
                    val = tokens[idx].rstrip(";")
                    if not val or val.upper() in (
                        "SIZE", "ORIGIN", "SYMMETRY", "SITE", "PIN", "OBS",
                        "END", "CLASS",
                    ):
                        break
                    parts.append(val)
                    if tokens[idx].endswith(";"):
                        idx += 1
                        break
                    idx += 1
                macro.symmetry = " ".join(parts)

            elif tok == "SITE" and idx + 1 < total:
                macro.site = tokens[idx + 1].rstrip(";")
                idx += 2

            elif tok == "PIN" and idx + 1 < total:
                pin = LEFPin(name=tokens[idx + 1])
                idx = self._parse_macro_pin(tokens, idx + 2, total, pin, macro.name)
                macro.pins.append(pin)

            elif tok == "OBS":
                idx = self._parse_obs(tokens, idx + 1, total, macro)

            else:
                idx += 1
        return idx

    @staticmethod
    def _parse_macro_pin(
        tokens: list[str],
        idx: int,
        total: int,
        pin: LEFPin,
        macro_name: str,
    ) -> int:
        current_port: LEFPort | None = None
        current_layer: str = ""
        in_port = False

        while idx < total:
            tok = tokens[idx].upper()

            if tok == "END" and idx + 1 < total and tokens[idx + 1] == pin.name:
                if current_port and (current_port.rects or current_port.layer):
                    pin.ports.append(current_port)
                return idx + 2

            if tok == "DIRECTION" and idx + 1 < total:
                pin.direction = tokens[idx + 1].rstrip(";").upper()
                idx += 2
            elif tok == "USE" and idx + 1 < total:
                pin.use = tokens[idx + 1].rstrip(";").upper()
                idx += 2
            elif tok == "SHAPE" and idx + 1 < total:
                pin.shape = tokens[idx + 1].rstrip(";").upper()
                idx += 2
            elif tok == "PORT":
                if current_port and (current_port.rects or current_port.layer):
                    pin.ports.append(current_port)
                current_port = LEFPort()
                in_port = True
                idx += 1
            elif tok == "LAYER" and in_port and idx + 1 < total:
                current_layer = tokens[idx + 1].rstrip(";")
                if current_port is not None:
                    current_port.layer = current_layer
                idx += 2
            elif tok == "RECT" and in_port and idx + 4 < total and current_port is not None:
                x0 = _sf(tokens[idx + 1])
                y0 = _sf(tokens[idx + 2])
                x1 = _sf(tokens[idx + 3])
                y1 = _sf(tokens[idx + 4])
                current_port.rects.append((x0, y0, x1, y1))
                idx += 5
            else:
                idx += 1

        if current_port and (current_port.rects or current_port.layer):
            pin.ports.append(current_port)
        return idx

    @staticmethod
    def _parse_obs(
        tokens: list[str], idx: int, total: int, macro: LEFMacro,
    ) -> int:
        current_obs: LEFObs | None = None

        while idx < total:
            tok = tokens[idx].upper()
            if tok == "END":
                if current_obs and current_obs.rects:
                    macro.obs.append(current_obs)
                return idx + 1

            if tok == "LAYER" and idx + 1 < total:
                if current_obs and current_obs.rects:
                    macro.obs.append(current_obs)
                current_obs = LEFObs(layer=tokens[idx + 1].rstrip(";"))
                idx += 2
            elif tok == "RECT" and idx + 4 < total and current_obs is not None:
                x0 = _sf(tokens[idx + 1])
                y0 = _sf(tokens[idx + 2])
                x1 = _sf(tokens[idx + 3])
                y1 = _sf(tokens[idx + 4])
                current_obs.rects.append((x0, y0, x1, y1))
                idx += 5
            else:
                idx += 1

        if current_obs and current_obs.rects:
            macro.obs.append(current_obs)
        return idx

    @staticmethod
    def _skip_to_end(
        tokens: list[str], idx: int, total: int, keyword: str,
    ) -> int:
        """Skip forward until we find END <keyword> or just END."""
        idx += 1
        while idx < total:
            if tokens[idx].upper() == "END":
                idx += 1
                if idx < total and tokens[idx].upper() == keyword:
                    return idx + 1
                # Might be a different END, keep going
                continue
            idx += 1
        return idx


def _sf(val: str, default: float = 0.0) -> float:
    """Safe float conversion, stripping trailing semicolons."""
    val = val.rstrip(";")
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
