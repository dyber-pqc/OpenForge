"""PCB data model (Phase 3).

A real, hierarchical PCB data model built on Pydantic v2 suitable for
round-tripping through a layout editor and exporting to Gerber/ODB++.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


LayerKind = Literal["signal", "plane", "mask", "silk", "paste", "mech", "edge"]
PadShape = Literal["round", "rect", "oval", "roundrect"]
FpSide = Literal["top", "bottom"]


class PcbLayer(BaseModel):
    name: str
    kind: LayerKind = "signal"
    thickness_mm: float = 0.035
    copper_oz: float = 1.0


class PcbStackup(BaseModel):
    layers: list[PcbLayer] = Field(default_factory=list)

    @classmethod
    def two_layer(cls) -> "PcbStackup":
        return cls(
            layers=[
                PcbLayer(name="F.Paste", kind="paste", thickness_mm=0.0),
                PcbLayer(name="F.Mask", kind="mask", thickness_mm=0.015),
                PcbLayer(name="F.SilkS", kind="silk", thickness_mm=0.012),
                PcbLayer(name="F.Cu", kind="signal", thickness_mm=0.035, copper_oz=1.0),
                PcbLayer(name="Dielectric1", kind="mech", thickness_mm=1.51),
                PcbLayer(name="B.Cu", kind="signal", thickness_mm=0.035, copper_oz=1.0),
                PcbLayer(name="B.SilkS", kind="silk", thickness_mm=0.012),
                PcbLayer(name="B.Mask", kind="mask", thickness_mm=0.015),
                PcbLayer(name="B.Paste", kind="paste", thickness_mm=0.0),
                PcbLayer(name="Edge.Cuts", kind="edge", thickness_mm=0.0),
            ]
        )

    @classmethod
    def four_layer(cls) -> "PcbStackup":
        return cls(
            layers=[
                PcbLayer(name="F.Paste", kind="paste"),
                PcbLayer(name="F.Mask", kind="mask", thickness_mm=0.015),
                PcbLayer(name="F.SilkS", kind="silk", thickness_mm=0.012),
                PcbLayer(name="F.Cu", kind="signal", thickness_mm=0.035),
                PcbLayer(name="Prepreg1", kind="mech", thickness_mm=0.20),
                PcbLayer(name="In1.Cu", kind="plane", thickness_mm=0.035),
                PcbLayer(name="Core1", kind="mech", thickness_mm=1.065),
                PcbLayer(name="In2.Cu", kind="plane", thickness_mm=0.035),
                PcbLayer(name="Prepreg2", kind="mech", thickness_mm=0.20),
                PcbLayer(name="B.Cu", kind="signal", thickness_mm=0.035),
                PcbLayer(name="B.SilkS", kind="silk", thickness_mm=0.012),
                PcbLayer(name="B.Mask", kind="mask", thickness_mm=0.015),
                PcbLayer(name="B.Paste", kind="paste"),
                PcbLayer(name="Edge.Cuts", kind="edge"),
            ]
        )

    @classmethod
    def six_layer(cls) -> "PcbStackup":
        layers = [
            PcbLayer(name="F.Paste", kind="paste"),
            PcbLayer(name="F.Mask", kind="mask", thickness_mm=0.015),
            PcbLayer(name="F.SilkS", kind="silk", thickness_mm=0.012),
            PcbLayer(name="F.Cu", kind="signal", thickness_mm=0.035),
            PcbLayer(name="Prepreg1", kind="mech", thickness_mm=0.15),
            PcbLayer(name="In1.Cu", kind="plane", thickness_mm=0.035),
            PcbLayer(name="Core1", kind="mech", thickness_mm=0.30),
            PcbLayer(name="In2.Cu", kind="signal", thickness_mm=0.035),
            PcbLayer(name="Prepreg2", kind="mech", thickness_mm=0.40),
            PcbLayer(name="In3.Cu", kind="signal", thickness_mm=0.035),
            PcbLayer(name="Core2", kind="mech", thickness_mm=0.30),
            PcbLayer(name="In4.Cu", kind="plane", thickness_mm=0.035),
            PcbLayer(name="Prepreg3", kind="mech", thickness_mm=0.15),
            PcbLayer(name="B.Cu", kind="signal", thickness_mm=0.035),
            PcbLayer(name="B.SilkS", kind="silk", thickness_mm=0.012),
            PcbLayer(name="B.Mask", kind="mask", thickness_mm=0.015),
            PcbLayer(name="B.Paste", kind="paste"),
            PcbLayer(name="Edge.Cuts", kind="edge"),
        ]
        return cls(layers=layers)

    def signal_layers(self) -> list[PcbLayer]:
        return [l for l in self.layers if l.kind == "signal"]

    def copper_layers(self) -> list[PcbLayer]:
        return [l for l in self.layers if l.kind in ("signal", "plane")]


class PcbPad(BaseModel):
    name: str
    x_mm: float
    y_mm: float
    shape: PadShape = "round"
    size_x_mm: float = 1.0
    size_y_mm: float = 1.0
    drill_mm: float = 0.0  # 0 = SMD
    layers: list[str] = Field(default_factory=lambda: ["F.Cu", "F.Mask", "F.Paste"])
    net: int = 0
    corner_radius_mm: float = 0.0  # for roundrect

    @property
    def is_tht(self) -> bool:
        return self.drill_mm > 0.0


class PcbFootprint(BaseModel):
    name: str
    library: str = "openforge"
    ref: str = "U?"
    value: str = ""
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation_deg: float = 0.0
    layer: FpSide = "top"
    pads: list[PcbPad] = Field(default_factory=list)
    courtyard: list[tuple[float, float]] = Field(default_factory=list)
    silkscreen: list[tuple[float, float, float, float]] = Field(default_factory=list)
    fab: list[tuple[float, float, float, float]] = Field(default_factory=list)
    description: str = ""

    def pad_world_xy(self, pad: PcbPad) -> tuple[float, float]:
        import math
        rot = math.radians(self.rotation_deg)
        cx, sx = math.cos(rot), math.sin(rot)
        xw = self.x_mm + pad.x_mm * cx - pad.y_mm * sx
        yw = self.y_mm + pad.x_mm * sx + pad.y_mm * cx
        return (xw, yw)


class PcbTrack(BaseModel):
    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float = 0.25
    net: int = 0

    def length_mm(self) -> float:
        return ((self.x2_mm - self.x1_mm) ** 2 + (self.y2_mm - self.y1_mm) ** 2) ** 0.5


class PcbVia(BaseModel):
    x_mm: float
    y_mm: float
    drill_mm: float = 0.3
    diameter_mm: float = 0.6
    layer_from: str = "F.Cu"
    layer_to: str = "B.Cu"
    net: int = 0


class PcbZone(BaseModel):
    layer: str
    polygon: list[tuple[float, float]] = Field(default_factory=list)
    net: int = 0
    clearance_mm: float = 0.2
    min_thickness_mm: float = 0.25
    fill_polygons: list[list[tuple[float, float]]] = Field(default_factory=list)


class PcbBoard(BaseModel):
    name: str = "board"
    stackup: PcbStackup = Field(default_factory=PcbStackup.two_layer)
    outline: list[tuple[float, float]] = Field(default_factory=list)
    footprints: list[PcbFootprint] = Field(default_factory=list)
    tracks: list[PcbTrack] = Field(default_factory=list)
    vias: list[PcbVia] = Field(default_factory=list)
    zones: list[PcbZone] = Field(default_factory=list)
    nets: dict[int, str] = Field(default_factory=lambda: {0: ""})
    drc_rules: dict = Field(default_factory=dict)

    def bounding_box(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        if self.outline:
            xs.extend(p[0] for p in self.outline)
            ys.extend(p[1] for p in self.outline)
        for fp in self.footprints:
            for pad in fp.pads:
                x, y = fp.pad_world_xy(pad)
                xs.append(x - pad.size_x_mm / 2)
                xs.append(x + pad.size_x_mm / 2)
                ys.append(y - pad.size_y_mm / 2)
                ys.append(y + pad.size_y_mm / 2)
        for t in self.tracks:
            xs.extend([t.x1_mm, t.x2_mm])
            ys.extend([t.y1_mm, t.y2_mm])
        for v in self.vias:
            xs.extend([v.x_mm - v.diameter_mm / 2, v.x_mm + v.diameter_mm / 2])
            ys.extend([v.y_mm - v.diameter_mm / 2, v.y_mm + v.diameter_mm / 2])
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def net_name(self, net_id: int) -> str:
        return self.nets.get(net_id, "")

    def add_net(self, name: str) -> int:
        for nid, nm in self.nets.items():
            if nm == name:
                return nid
        nid = max(self.nets.keys(), default=0) + 1
        self.nets[nid] = name
        return nid

    def save_json(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2))
        return p

    @classmethod
    def load_json(cls, path: str | Path) -> "PcbBoard":
        data = json.loads(Path(path).read_text())
        return cls.model_validate(data)
