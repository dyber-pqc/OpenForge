"""PCB net classes.

Net classes group nets sharing design rules (width, clearance, via sizes,
impedance targets, length matching, differential-pair geometry, topology).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Topology = Literal["free", "daisy_chain", "star", "t", "fly_by"]


class NetClass(BaseModel):
    """Design rules and attributes for a group of related nets."""

    name: str
    width_mm: float = 0.2
    clearance_mm: float = 0.2
    via_drill_mm: float = 0.3
    via_diameter_mm: float = 0.6
    track_min_mm: float = 0.15
    track_max_mm: float = 2.0
    impedance_target_ohm: float | None = None
    diff_pair_gap_mm: float | None = None
    diff_pair_width_mm: float | None = None
    length_target_mm: float | None = None
    length_tolerance_mm: float | None = None
    topology: Topology = "free"
    nets: list[str] = Field(default_factory=list)
    layer_restriction: list[str] | None = None
    description: str = ""

    def applies_to(self, net: str) -> bool:
        return net in self.nets


class NetClassRegistry(BaseModel):
    """Registry of net classes with net -> class assignment."""

    classes: dict[str, NetClass] = Field(default_factory=dict)
    default: str = "default"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if self.default not in self.classes:
            self.classes[self.default] = NetClass(name=self.default)

    def add(self, klass: NetClass) -> None:
        self.classes[klass.name] = klass

    def remove(self, name: str) -> None:
        if name == self.default:
            raise ValueError("cannot remove default class")
        self.classes.pop(name, None)

    def assign(self, net: str, klass: str) -> None:
        """Assign a net to a class; removes it from any others."""
        if klass not in self.classes:
            raise KeyError(f"unknown net class: {klass}")
        for c in self.classes.values():
            if net in c.nets and c.name != klass:
                c.nets.remove(net)
        if net not in self.classes[klass].nets:
            self.classes[klass].nets.append(net)

    def get_for_net(self, net: str) -> NetClass:
        for c in self.classes.values():
            if c.name == self.default:
                continue
            if net in c.nets:
                return c
        return self.classes[self.default]

    def nets_in(self, klass: str) -> list[str]:
        return list(self.classes.get(klass, NetClass(name=klass)).nets)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, d: dict) -> "NetClassRegistry":
        return cls.model_validate(d)

    @classmethod
    def with_defaults(cls) -> "NetClassRegistry":
        reg = cls(classes={}, default="default")
        for c in DEFAULT_CLASSES.values():
            reg.add(c.model_copy(deep=True))
        return reg


# Real, production-reasonable defaults. Values chosen for a typical
# 1.6 mm FR-4 two/four layer board with 1oz copper.
DEFAULT_CLASSES: dict[str, NetClass] = {
    "default": NetClass(
        name="default",
        width_mm=0.2,
        clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        track_min_mm=0.15,
        track_max_mm=2.0,
        description="Default signal class",
    ),
    "power": NetClass(
        name="power",
        width_mm=0.5,
        clearance_mm=0.25,
        via_drill_mm=0.4,
        via_diameter_mm=0.8,
        track_min_mm=0.3,
        track_max_mm=4.0,
        description="Power rails",
    ),
    "ground": NetClass(
        name="ground",
        width_mm=0.5,
        clearance_mm=0.25,
        via_drill_mm=0.4,
        via_diameter_mm=0.8,
        track_min_mm=0.3,
        track_max_mm=8.0,
        description="Ground nets (usually poured)",
    ),
    "high_speed": NetClass(
        name="high_speed",
        width_mm=0.15,
        clearance_mm=0.2,
        via_drill_mm=0.25,
        via_diameter_mm=0.5,
        track_min_mm=0.1,
        track_max_mm=0.3,
        impedance_target_ohm=50.0,
        description="Single-ended 50 ohm",
    ),
    "diff_50": NetClass(
        name="diff_50",
        width_mm=0.15,
        clearance_mm=0.2,
        via_drill_mm=0.25,
        via_diameter_mm=0.5,
        diff_pair_width_mm=0.15,
        diff_pair_gap_mm=0.15,
        impedance_target_ohm=100.0,
        description="Generic 100 ohm differential",
    ),
    "diff_90": NetClass(
        name="diff_90",
        width_mm=0.14,
        clearance_mm=0.2,
        diff_pair_width_mm=0.14,
        diff_pair_gap_mm=0.13,
        impedance_target_ohm=90.0,
        description="USB 2.0 (90 ohm differential)",
    ),
    "diff_100": NetClass(
        name="diff_100",
        width_mm=0.15,
        clearance_mm=0.2,
        diff_pair_width_mm=0.15,
        diff_pair_gap_mm=0.2,
        impedance_target_ohm=100.0,
        description="LVDS / Ethernet (100 ohm differential)",
    ),
    "ddr_addr": NetClass(
        name="ddr_addr",
        width_mm=0.125,
        clearance_mm=0.2,
        impedance_target_ohm=50.0,
        length_target_mm=50.0,
        length_tolerance_mm=0.5,
        topology="fly_by",
        description="DDR address/command (fly-by)",
    ),
    "ddr_data": NetClass(
        name="ddr_data",
        width_mm=0.125,
        clearance_mm=0.2,
        impedance_target_ohm=50.0,
        length_target_mm=50.0,
        length_tolerance_mm=0.25,
        topology="daisy_chain",
        description="DDR data bytelane",
    ),
    "ddr_clk": NetClass(
        name="ddr_clk",
        width_mm=0.125,
        clearance_mm=0.25,
        diff_pair_width_mm=0.125,
        diff_pair_gap_mm=0.2,
        impedance_target_ohm=100.0,
        length_target_mm=50.0,
        length_tolerance_mm=0.1,
        topology="fly_by",
        description="DDR differential clock",
    ),
}


__all__ = [
    "NetClass",
    "NetClassRegistry",
    "DEFAULT_CLASSES",
    "Topology",
]
