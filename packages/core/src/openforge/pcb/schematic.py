"""PCB schematic data model.

Provides core schematic capture data structures: pins, symbols,
components, nets and full schematic sheets. Designed to be the
in-memory representation that the desktop schematic editor and
BOM/netlist generators operate on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class PinDirection(str, Enum):
    """Logical direction of a schematic pin."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIR = "bidir"
    POWER = "power"
    GROUND = "ground"
    PASSIVE = "passive"
    TRISTATE = "tristate"
    OPEN_COLLECTOR = "open_collector"
    NC = "no_connect"


@dataclass
class Pin:
    """A single pin on a schematic symbol.

    Attributes:
        number: Pin number as a string ("1", "A1", "VCC").
        name: Human-readable name.
        direction: Logical role (input/output/power/ground/passive).
        x: X-offset from symbol origin (schematic units).
        y: Y-offset from symbol origin.
    """

    number: str
    name: str
    direction: str = PinDirection.PASSIVE.value
    x: float = 0.0
    y: float = 0.0
    length: float = 10.0
    visible: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Pin":
        return cls(**d)


@dataclass
class SchSymbol:
    """A schematic symbol definition (reusable graphic)."""

    name: str
    library: str
    pins: list[Pin] = field(default_factory=list)
    drawing: str = ""  # SVG path for symbol body
    width: float = 100.0
    height: float = 60.0
    reference_prefix: str = "U"
    description: str = ""
    keywords: list[str] = field(default_factory=list)

    def add_pin(self, pin: Pin) -> None:
        self.pins.append(pin)

    def get_pin(self, number: str) -> Pin | None:
        for p in self.pins:
            if p.number == number:
                return p
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "library": self.library,
            "pins": [p.to_dict() for p in self.pins],
            "drawing": self.drawing,
            "width": self.width,
            "height": self.height,
            "reference_prefix": self.reference_prefix,
            "description": self.description,
            "keywords": list(self.keywords),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SchSymbol":
        return cls(
            name=d["name"],
            library=d["library"],
            pins=[Pin.from_dict(p) for p in d.get("pins", [])],
            drawing=d.get("drawing", ""),
            width=d.get("width", 100.0),
            height=d.get("height", 60.0),
            reference_prefix=d.get("reference_prefix", "U"),
            description=d.get("description", ""),
            keywords=list(d.get("keywords", [])),
        )


@dataclass
class SchComponent:
    """An instance of a symbol placed on a schematic sheet."""

    refdes: str  # R1, C2, U3
    symbol: SchSymbol
    value: str
    footprint: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    mirror: bool = False
    parameters: dict[str, str] = field(default_factory=dict)
    mpn: str = ""
    manufacturer: str = ""
    do_not_populate: bool = False

    def pin_position(self, pin_number: str) -> tuple[float, float] | None:
        pin = self.symbol.get_pin(pin_number)
        if pin is None:
            return None
        import math

        theta = math.radians(self.rotation)
        px, py = pin.x, pin.y
        if self.mirror:
            px = -px
        rx = px * math.cos(theta) - py * math.sin(theta)
        ry = px * math.sin(theta) + py * math.cos(theta)
        return (self.x + rx, self.y + ry)

    def to_dict(self) -> dict:
        return {
            "refdes": self.refdes,
            "symbol": self.symbol.to_dict(),
            "value": self.value,
            "footprint": self.footprint,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "mirror": self.mirror,
            "parameters": dict(self.parameters),
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "do_not_populate": self.do_not_populate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SchComponent":
        return cls(
            refdes=d["refdes"],
            symbol=SchSymbol.from_dict(d["symbol"]),
            value=d["value"],
            footprint=d.get("footprint", ""),
            x=d.get("x", 0.0),
            y=d.get("y", 0.0),
            rotation=d.get("rotation", 0.0),
            mirror=d.get("mirror", False),
            parameters=dict(d.get("parameters", {})),
            mpn=d.get("mpn", ""),
            manufacturer=d.get("manufacturer", ""),
            do_not_populate=d.get("do_not_populate", False),
        )


@dataclass
class SchNet:
    """A logical net connecting multiple pins on a schematic."""

    name: str
    points: list[tuple[float, float]] = field(default_factory=list)
    connections: list[tuple[str, str]] = field(default_factory=list)
    is_power: bool = False
    is_ground: bool = False
    net_class: str = "default"

    def add_connection(self, refdes: str, pin: str) -> None:
        conn = (refdes, pin)
        if conn not in self.connections:
            self.connections.append(conn)

    def add_point(self, x: float, y: float) -> None:
        self.points.append((x, y))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "points": [list(p) for p in self.points],
            "connections": [list(c) for c in self.connections],
            "is_power": self.is_power,
            "is_ground": self.is_ground,
            "net_class": self.net_class,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SchNet":
        return cls(
            name=d["name"],
            points=[tuple(p) for p in d.get("points", [])],
            connections=[tuple(c) for c in d.get("connections", [])],
            is_power=d.get("is_power", False),
            is_ground=d.get("is_ground", False),
            net_class=d.get("net_class", "default"),
        )


@dataclass
class Schematic:
    """A full schematic sheet."""

    name: str
    title: str = ""
    revision: str = ""
    author: str = ""
    company: str = ""
    components: dict[str, SchComponent] = field(default_factory=dict)
    nets: dict[str, SchNet] = field(default_factory=dict)
    sheet_width: float = 11.0
    sheet_height: float = 8.5
    notes: list[str] = field(default_factory=list)

    def add_component(self, comp: SchComponent) -> None:
        if comp.refdes in self.components:
            raise ValueError(f"Component {comp.refdes} already exists")
        self.components[comp.refdes] = comp

    def remove_component(self, refdes: str) -> None:
        self.components.pop(refdes, None)
        for net in self.nets.values():
            net.connections = [c for c in net.connections if c[0] != refdes]

    def add_net(self, net: SchNet) -> None:
        if net.name in self.nets:
            existing = self.nets[net.name]
            for c in net.connections:
                if c not in existing.connections:
                    existing.connections.append(c)
            existing.points.extend(net.points)
        else:
            self.nets[net.name] = net

    def connect(self, net_name: str, refdes: str, pin: str) -> None:
        if net_name not in self.nets:
            self.nets[net_name] = SchNet(name=net_name)
        self.nets[net_name].add_connection(refdes, pin)

    def get_netlist(self) -> dict[str, list[tuple[str, str]]]:
        """Return the flattened netlist as {net_name: [(refdes, pin), ...]}."""
        return {name: list(net.connections) for name, net in self.nets.items()}

    def get_component_count(self) -> int:
        return len(self.components)

    def get_net_count(self) -> int:
        return len(self.nets)

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen = set()
        for refdes, comp in self.components.items():
            if refdes in seen:
                errors.append(f"Duplicate refdes: {refdes}")
            seen.add(refdes)
            if not comp.value:
                errors.append(f"Component {refdes} has empty value")
        for name, net in self.nets.items():
            if len(net.connections) < 2 and not (net.is_power or net.is_ground):
                errors.append(f"Net {name} has fewer than 2 connections")
            for refdes, pin in net.connections:
                if refdes not in self.components:
                    errors.append(
                        f"Net {name} refers to missing component {refdes}"
                    )
        return errors

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "revision": self.revision,
            "author": self.author,
            "company": self.company,
            "components": {r: c.to_dict() for r, c in self.components.items()},
            "nets": {n: net.to_dict() for n, net in self.nets.items()},
            "sheet_width": self.sheet_width,
            "sheet_height": self.sheet_height,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Schematic":
        sch = cls(
            name=d["name"],
            title=d.get("title", ""),
            revision=d.get("revision", ""),
            author=d.get("author", ""),
            company=d.get("company", ""),
            sheet_width=d.get("sheet_width", 11.0),
            sheet_height=d.get("sheet_height", 8.5),
            notes=list(d.get("notes", [])),
        )
        for refdes, c in d.get("components", {}).items():
            sch.components[refdes] = SchComponent.from_dict(c)
        for name, n in d.get("nets", {}).items():
            sch.nets[name] = SchNet.from_dict(n)
        return sch

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Schematic":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
