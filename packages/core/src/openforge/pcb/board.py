"""PCB board layout data model.

Physical board representation: copper layers, footprints, tracks,
vias, copper zones, and board outline. Units are millimeters
throughout unless noted otherwise.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class CopperLayer(Enum):
    """Canonical copper/technical layer names (KiCad-compatible)."""

    F_CU = "F.Cu"
    B_CU = "B.Cu"
    IN1_CU = "In1.Cu"
    IN2_CU = "In2.Cu"
    IN3_CU = "In3.Cu"
    IN4_CU = "In4.Cu"
    F_MASK = "F.Mask"
    B_MASK = "B.Mask"
    F_SILK = "F.SilkS"
    B_SILK = "B.SilkS"
    F_PASTE = "F.Paste"
    B_PASTE = "B.Paste"
    F_FAB = "F.Fab"
    B_FAB = "B.Fab"
    EDGE_CUTS = "Edge.Cuts"
    MARGIN = "Margin"
    DWGS_USER = "Dwgs.User"
    CMTS_USER = "Cmts.User"

    @classmethod
    def copper_layers(cls) -> list["CopperLayer"]:
        return [cls.F_CU, cls.IN1_CU, cls.IN2_CU, cls.IN3_CU, cls.IN4_CU, cls.B_CU]

    @classmethod
    def is_copper(cls, layer: "CopperLayer") -> bool:
        return layer in cls.copper_layers()


class PadShape(str, Enum):
    CIRCLE = "circle"
    RECT = "rect"
    ROUNDRECT = "roundrect"
    OVAL = "oval"
    TRAPEZOID = "trapezoid"


class PadType(str, Enum):
    SMD = "smd"
    THRU_HOLE = "thru_hole"
    CONNECT = "connect"
    NPTH = "np_thru_hole"


@dataclass
class Footprint:
    """A physical footprint definition."""

    name: str
    library: str
    pads: list[dict] = field(default_factory=list)
    courtyard: list[tuple[float, float]] = field(default_factory=list)
    silkscreen: list[dict] = field(default_factory=list)
    height_mm: float = 0.0
    description: str = ""
    tags: list[str] = field(default_factory=list)
    model_3d: str = ""

    def add_pad(
        self,
        number: str,
        pad_type: str,
        shape: str,
        x: float,
        y: float,
        w: float,
        h: float,
        drill: float = 0.0,
    ) -> None:
        self.pads.append(
            {
                "number": number,
                "type": pad_type,
                "shape": shape,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "drill": drill,
            }
        )

    def bounding_box(self) -> tuple[float, float, float, float]:
        if not self.pads:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p["x"] - p["w"] / 2 for p in self.pads] + [
            p["x"] + p["w"] / 2 for p in self.pads
        ]
        ys = [p["y"] - p["h"] / 2 for p in self.pads] + [
            p["y"] + p["h"] / 2 for p in self.pads
        ]
        return (min(xs), min(ys), max(xs), max(ys))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "library": self.library,
            "pads": list(self.pads),
            "courtyard": [list(p) for p in self.courtyard],
            "silkscreen": list(self.silkscreen),
            "height_mm": self.height_mm,
            "description": self.description,
            "tags": list(self.tags),
            "model_3d": self.model_3d,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Footprint":
        return cls(
            name=d["name"],
            library=d["library"],
            pads=list(d.get("pads", [])),
            courtyard=[tuple(p) for p in d.get("courtyard", [])],
            silkscreen=list(d.get("silkscreen", [])),
            height_mm=d.get("height_mm", 0.0),
            description=d.get("description", ""),
            tags=list(d.get("tags", [])),
            model_3d=d.get("model_3d", ""),
        )


@dataclass
class BoardComponent:
    """A footprint placed on the board."""

    refdes: str
    footprint: Footprint
    value: str
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: float = 0.0
    layer: CopperLayer = CopperLayer.F_CU
    locked: bool = False
    placed: bool = True

    def pad_position(self, pad_number: str) -> tuple[float, float] | None:
        for pad in self.footprint.pads:
            if pad["number"] == pad_number:
                theta = math.radians(self.rotation)
                px, py = pad["x"], pad["y"]
                rx = px * math.cos(theta) - py * math.sin(theta)
                ry = px * math.sin(theta) + py * math.cos(theta)
                return (self.x_mm + rx, self.y_mm + ry)
        return None

    def to_dict(self) -> dict:
        return {
            "refdes": self.refdes,
            "footprint": self.footprint.to_dict(),
            "value": self.value,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "rotation": self.rotation,
            "layer": self.layer.value,
            "locked": self.locked,
            "placed": self.placed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BoardComponent":
        return cls(
            refdes=d["refdes"],
            footprint=Footprint.from_dict(d["footprint"]),
            value=d["value"],
            x_mm=d.get("x_mm", 0.0),
            y_mm=d.get("y_mm", 0.0),
            rotation=d.get("rotation", 0.0),
            layer=CopperLayer(d.get("layer", CopperLayer.F_CU.value)),
            locked=d.get("locked", False),
            placed=d.get("placed", True),
        )


@dataclass
class Track:
    """A copper track segment or polyline."""

    net: str
    layer: CopperLayer
    width_mm: float
    points: list[tuple[float, float]] = field(default_factory=list)

    def length(self) -> float:
        total = 0.0
        for i in range(1, len(self.points)):
            ax, ay = self.points[i - 1]
            bx, by = self.points[i]
            total += math.hypot(bx - ax, by - ay)
        return total

    def to_dict(self) -> dict:
        return {
            "net": self.net,
            "layer": self.layer.value,
            "width_mm": self.width_mm,
            "points": [list(p) for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(
            net=d["net"],
            layer=CopperLayer(d["layer"]),
            width_mm=d["width_mm"],
            points=[tuple(p) for p in d.get("points", [])],
        )


@dataclass
class Via:
    net: str
    x_mm: float
    y_mm: float
    drill_mm: float
    diameter_mm: float
    layers: list[CopperLayer] = field(default_factory=list)
    tented: bool = True

    def to_dict(self) -> dict:
        return {
            "net": self.net,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "drill_mm": self.drill_mm,
            "diameter_mm": self.diameter_mm,
            "layers": [l.value for l in self.layers],
            "tented": self.tented,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Via":
        return cls(
            net=d["net"],
            x_mm=d["x_mm"],
            y_mm=d["y_mm"],
            drill_mm=d["drill_mm"],
            diameter_mm=d["diameter_mm"],
            layers=[CopperLayer(l) for l in d.get("layers", [])],
            tented=d.get("tented", True),
        )


@dataclass
class Zone:
    """Copper pour or ground plane."""

    net: str
    layer: CopperLayer
    polygon: list[tuple[float, float]] = field(default_factory=list)
    clearance_mm: float = 0.2
    min_thickness_mm: float = 0.25
    thermal_gap_mm: float = 0.5
    filled: bool = False

    def area(self) -> float:
        if len(self.polygon) < 3:
            return 0.0
        n = len(self.polygon)
        s = 0.0
        for i in range(n):
            x1, y1 = self.polygon[i]
            x2, y2 = self.polygon[(i + 1) % n]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    def to_dict(self) -> dict:
        return {
            "net": self.net,
            "layer": self.layer.value,
            "polygon": [list(p) for p in self.polygon],
            "clearance_mm": self.clearance_mm,
            "min_thickness_mm": self.min_thickness_mm,
            "thermal_gap_mm": self.thermal_gap_mm,
            "filled": self.filled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Zone":
        return cls(
            net=d["net"],
            layer=CopperLayer(d["layer"]),
            polygon=[tuple(p) for p in d.get("polygon", [])],
            clearance_mm=d.get("clearance_mm", 0.2),
            min_thickness_mm=d.get("min_thickness_mm", 0.25),
            thermal_gap_mm=d.get("thermal_gap_mm", 0.5),
            filled=d.get("filled", False),
        )


@dataclass
class DesignRules:
    min_track_width_mm: float = 0.15
    min_via_drill_mm: float = 0.3
    min_via_diameter_mm: float = 0.6
    min_clearance_mm: float = 0.15
    min_annular_ring_mm: float = 0.1


@dataclass
class Board:
    """A full PCB board layout."""

    name: str
    layers: list[CopperLayer] = field(default_factory=list)
    components: dict[str, BoardComponent] = field(default_factory=dict)
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    outline: list[tuple[float, float]] = field(default_factory=list)
    width_mm: float = 100.0
    height_mm: float = 100.0
    thickness_mm: float = 1.6
    design_rules: DesignRules = field(default_factory=DesignRules)
    title: str = ""
    revision: str = ""

    def __post_init__(self) -> None:
        if not self.layers:
            self.layers = [
                CopperLayer.F_CU,
                CopperLayer.B_CU,
                CopperLayer.F_MASK,
                CopperLayer.B_MASK,
                CopperLayer.F_SILK,
                CopperLayer.B_SILK,
                CopperLayer.EDGE_CUTS,
            ]
        if not self.outline:
            self.outline = [
                (0.0, 0.0),
                (self.width_mm, 0.0),
                (self.width_mm, self.height_mm),
                (0.0, self.height_mm),
            ]

    def add_component(self, comp: BoardComponent) -> None:
        if comp.refdes in self.components:
            raise ValueError(f"Component {comp.refdes} already on board")
        self.components[comp.refdes] = comp

    def remove_component(self, refdes: str) -> None:
        self.components.pop(refdes, None)

    def add_track(self, track: Track) -> None:
        self.tracks.append(track)

    def add_via(self, via: Via) -> None:
        self.vias.append(via)

    def add_zone(self, zone: Zone) -> None:
        self.zones.append(zone)

    def tracks_for_net(self, net: str) -> list[Track]:
        return [t for t in self.tracks if t.net == net]

    def nets(self) -> set[str]:
        nets: set[str] = set()
        for t in self.tracks:
            nets.add(t.net)
        for v in self.vias:
            nets.add(v.net)
        for z in self.zones:
            nets.add(z.net)
        return nets

    def total_track_length(self) -> float:
        return sum(t.length() for t in self.tracks)

    def bounding_box(self) -> tuple[float, float, float, float]:
        if not self.outline:
            return (0.0, 0.0, self.width_mm, self.height_mm)
        xs = [p[0] for p in self.outline]
        ys = [p[1] for p in self.outline]
        return (min(xs), min(ys), max(xs), max(ys))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "layers": [l.value for l in self.layers],
            "components": {r: c.to_dict() for r, c in self.components.items()},
            "tracks": [t.to_dict() for t in self.tracks],
            "vias": [v.to_dict() for v in self.vias],
            "zones": [z.to_dict() for z in self.zones],
            "outline": [list(p) for p in self.outline],
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "thickness_mm": self.thickness_mm,
            "design_rules": asdict(self.design_rules),
            "title": self.title,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Board":
        dr = DesignRules(**d.get("design_rules", {}))
        b = cls(
            name=d["name"],
            layers=[CopperLayer(l) for l in d.get("layers", [])],
            outline=[tuple(p) for p in d.get("outline", [])],
            width_mm=d.get("width_mm", 100.0),
            height_mm=d.get("height_mm", 100.0),
            thickness_mm=d.get("thickness_mm", 1.6),
            design_rules=dr,
            title=d.get("title", ""),
            revision=d.get("revision", ""),
        )
        for r, c in d.get("components", {}).items():
            b.components[r] = BoardComponent.from_dict(c)
        for t in d.get("tracks", []):
            b.tracks.append(Track.from_dict(t))
        for v in d.get("vias", []):
            b.vias.append(Via.from_dict(v))
        for z in d.get("zones", []):
            b.zones.append(Zone.from_dict(z))
        return b

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Board":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
