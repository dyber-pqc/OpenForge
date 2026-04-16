"""Parse Yosys JSON netlists into a clean Python data model for visualization.

Yosys writes a JSON netlist via ``write_json``. The structure is roughly::

    {
      "creator": "Yosys 0.36",
      "modules": {
        "<module_name>": {
          "attributes": {"top": 1, ...},
          "ports": {
            "<port>": {"direction": "input|output|inout", "bits": [...]}
          },
          "cells": {
            "<instance>": {
              "type": "<cell_type>",
              "parameters": {...},
              "connections": {"<pin>": [bit_id, ...]},
              "port_directions": {"<pin>": "input|output"}
            }
          },
          "netnames": {
            "<wire>": {"bits": [...], "signed": 0|1}
          }
        }
      }
    }

This module loads such a file and produces a strongly-typed graph that the
desktop schematic viewer (and any other consumer) can walk efficiently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class NetPort:
    """A top-level IO port on a module."""

    name: str
    direction: str  # input / output / inout
    width: int = 1
    bits: list[Any] = field(default_factory=list)

    @property
    def is_input(self) -> bool:
        return self.direction == "input"

    @property
    def is_output(self) -> bool:
        return self.direction == "output"

    @property
    def is_bus(self) -> bool:
        return self.width > 1

    def label(self) -> str:
        if self.is_bus:
            return f"{self.name}[{self.width - 1}:0]"
        return self.name


@dataclass
class NetCell:
    """A single cell instance inside a module."""

    name: str
    cell_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    connections: dict[str, list[Any]] = field(default_factory=dict)
    port_directions: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    is_sequential: bool = False
    is_buffer: bool = False
    is_constant: bool = False

    @property
    def kind(self) -> str:
        """Return the logical kind of this cell.

        Returns one of: ff, and, or, nand, nor, xor, xnor, inv, buf, mux,
        add, sub, gate.
        """
        ct = self.cell_type.lower()

        # Sequential first (DFF, latch, etc.)
        if any(s in ct for s in ("_dff", "$dff", "flop", "_ff_", "latch", "$sr")):
            return "ff"

        # Order matters: nand/nor/xnor must beat and/or/xor
        if "nand" in ct:
            return "nand"
        if "nor" in ct:
            return "nor"
        if "xnor" in ct:
            return "xnor"
        if "xor" in ct:
            return "xor"
        if "_and" in ct or ct.endswith("and") or "$and" in ct:
            return "and"
        if "_or" in ct or ct.endswith("or") or "$or" in ct:
            return "or"

        if "inv" in ct or "_not" in ct or "$not" in ct:
            return "inv"
        if "buf" in ct:
            return "buf"
        if "mux" in ct:
            return "mux"
        if "fa_" in ct or ct.startswith("$add") or "_add" in ct or "adder" in ct:
            return "add"
        if ct.startswith("$sub") or "_sub" in ct:
            return "sub"
        return "gate"

    @property
    def input_pins(self) -> list[str]:
        return [p for p, d in self.port_directions.items() if d == "input"]

    @property
    def output_pins(self) -> list[str]:
        return [p for p, d in self.port_directions.items() if d == "output"]

    def driven_bits(self) -> list[Any]:
        """Bits driven by this cell (output pin connections flattened)."""
        out: list[Any] = []
        for pin in self.output_pins:
            out.extend(self.connections.get(pin, []))
        return out

    def consumed_bits(self) -> list[Any]:
        """Bits consumed by this cell (input pin connections flattened)."""
        out: list[Any] = []
        for pin in self.input_pins:
            out.extend(self.connections.get(pin, []))
        return out


@dataclass
class NetWire:
    """A named wire / signal in a module."""

    name: str
    bits: list[Any]
    width: int = 1
    is_signed: bool = False
    hide_name: bool = False

    @property
    def is_bus(self) -> bool:
        return self.width > 1


@dataclass
class NetlistModule:
    """A single Verilog module."""

    name: str
    ports: dict[str, NetPort] = field(default_factory=dict)
    cells: dict[str, NetCell] = field(default_factory=dict)
    wires: dict[str, NetWire] = field(default_factory=dict)
    submodules: dict[str, str] = field(default_factory=dict)  # instance -> type
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def input_ports(self) -> list[NetPort]:
        return [p for p in self.ports.values() if p.direction == "input"]

    @property
    def output_ports(self) -> list[NetPort]:
        return [p for p in self.ports.values() if p.direction == "output"]

    @property
    def inout_ports(self) -> list[NetPort]:
        return [p for p in self.ports.values() if p.direction == "inout"]

    @property
    def is_leaf(self) -> bool:
        """A leaf module has cells but no submodule instances."""
        return len(self.cells) > 0 and len(self.submodules) == 0

    @property
    def is_top(self) -> bool:
        return self.attributes.get("top") == 1 or self.attributes.get("top") == "1"

    def get_cells_by_kind(self, kind: str) -> list[NetCell]:
        return [c for c in self.cells.values() if c.kind == kind]

    def find_cell(self, name: str) -> NetCell | None:
        return self.cells.get(name)

    def stats(self) -> dict[str, int]:
        """Return cell counts grouped by logical kind."""
        result: dict[str, int] = {
            "ff": 0,
            "and": 0,
            "or": 0,
            "nand": 0,
            "nor": 0,
            "xor": 0,
            "xnor": 0,
            "inv": 0,
            "buf": 0,
            "mux": 0,
            "add": 0,
            "sub": 0,
            "gate": 0,
        }
        for cell in self.cells.values():
            result[cell.kind] = result.get(cell.kind, 0) + 1
        return result

    def driver_map(self) -> dict[Any, str]:
        """Map each output bit id to the cell instance that drives it."""
        driver: dict[Any, str] = {}
        for cell_name, cell in self.cells.items():
            for bit in cell.driven_bits():
                driver[bit] = cell_name
        return driver

    def loads_map(self) -> dict[Any, list[str]]:
        """Map each bit id to the list of cells that consume it."""
        loads: dict[Any, list[str]] = {}
        for cell_name, cell in self.cells.items():
            for bit in cell.consumed_bits():
                loads.setdefault(bit, []).append(cell_name)
        return loads

    def fanout(self, cell_name: str) -> list[str]:
        """Return cells immediately downstream of ``cell_name``."""
        cell = self.cells.get(cell_name)
        if cell is None:
            return []
        loads = self.loads_map()
        result: list[str] = []
        for bit in cell.driven_bits():
            for load in loads.get(bit, []):
                if load not in result and load != cell_name:
                    result.append(load)
        return result

    def fanin(self, cell_name: str) -> list[str]:
        """Return cells immediately upstream of ``cell_name``."""
        cell = self.cells.get(cell_name)
        if cell is None:
            return []
        drivers = self.driver_map()
        result: list[str] = []
        for bit in cell.consumed_bits():
            drv = drivers.get(bit)
            if drv and drv != cell_name and drv not in result:
                result.append(drv)
        return result


@dataclass
class Netlist:
    """A complete parsed Yosys netlist."""

    creator: str = ""
    modules: dict[str, NetlistModule] = field(default_factory=dict)
    top_module: str = ""
    source_path: Path | None = None

    def get_top(self) -> NetlistModule | None:
        if self.top_module and self.top_module in self.modules:
            return self.modules[self.top_module]
        # Heuristic: top is the module not instantiated by any other module
        instantiated: set[str] = set()
        for mod in self.modules.values():
            instantiated.update(mod.submodules.values())
        candidates = [n for n in self.modules if n not in instantiated]
        if candidates:
            return self.modules[candidates[0]]
        if self.modules:
            return next(iter(self.modules.values()))
        return None

    def total_cells(self) -> int:
        return sum(len(m.cells) for m in self.modules.values())

    def total_stats(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for mod in self.modules.values():
            for k, v in mod.stats().items():
                total[k] = total.get(k, 0) + v
        return total


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _is_tech_cell_type(cell_type: str) -> bool:
    """Return True if ``cell_type`` looks like a technology / built-in cell.

    These are NOT submodules — they are leaf gates that should be drawn as
    primitive symbols rather than navigated into.
    """
    if not cell_type:
        return True
    if cell_type.startswith("$"):
        return True
    lower = cell_type.lower()
    tech_prefixes = (
        "sky130_",
        "gf180mcu_",
        "asap7_",
        "nangate_",
        "nand2_",
        "nor2_",
        "and2_",
        "or2_",
        "inv_",
        "buf_",
        "dff_",
    )
    return any(lower.startswith(p) for p in tech_prefixes)


def parse_yosys_json(json_path: Path | str) -> Netlist:
    """Parse a Yosys JSON netlist file into a :class:`Netlist`.

    Parameters
    ----------
    json_path:
        Filesystem path to a Yosys ``write_json`` output.

    Raises
    ------
    FileNotFoundError
        If ``json_path`` does not exist.
    ValueError
        If the file cannot be decoded as Yosys JSON.
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Netlist not found: {json_path}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Yosys JSON: {exc}") from exc

    netlist = Netlist(
        creator=str(data.get("creator", "Unknown")),
        source_path=json_path,
    )

    modules_data = data.get("modules") or {}
    for mod_name, mod_data in modules_data.items():
        attrs = mod_data.get("attributes", {}) or {}
        if attrs.get("top") in (1, "1", "00000000000000000000000000000001"):
            netlist.top_module = mod_name

        module = NetlistModule(name=mod_name, attributes=dict(attrs))

        # Ports
        for port_name, port_data in (mod_data.get("ports") or {}).items():
            bits = list(port_data.get("bits", []) or [])
            module.ports[port_name] = NetPort(
                name=port_name,
                direction=port_data.get("direction", "input"),
                width=len(bits),
                bits=bits,
            )

        # Cells
        for cell_name, cell_data in (mod_data.get("cells") or {}).items():
            cell_type = str(cell_data.get("type", ""))
            cell = NetCell(
                name=cell_name,
                cell_type=cell_type,
                parameters=dict(cell_data.get("parameters", {}) or {}),
                connections={
                    pin: list(bits or [])
                    for pin, bits in (cell_data.get("connections", {}) or {}).items()
                },
                port_directions=dict(cell_data.get("port_directions", {}) or {}),
                attributes=dict(cell_data.get("attributes", {}) or {}),
            )
            cell.is_sequential = cell.kind == "ff"
            cell.is_buffer = cell.kind == "buf"
            module.cells[cell_name] = cell

            if not _is_tech_cell_type(cell_type):
                module.submodules[cell_name] = cell_type

        # Wires (netnames)
        for wire_name, wire_data in (mod_data.get("netnames") or {}).items():
            bits = list(wire_data.get("bits", []) or [])
            module.wires[wire_name] = NetWire(
                name=wire_name,
                bits=bits,
                width=len(bits),
                is_signed=wire_data.get("signed", 0) == 1,
                hide_name=wire_data.get("hide_name", 0) == 1,
            )

        netlist.modules[mod_name] = module

    if not netlist.top_module and netlist.modules:
        top = netlist.get_top()
        if top:
            netlist.top_module = top.name

    return netlist


def parse_yosys_json_string(text: str) -> Netlist:
    """Parse a Yosys JSON netlist from an in-memory string."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Yosys JSON: {exc}") from exc

    # Reuse main parser by writing to a temp dict-like structure
    netlist = Netlist(creator=str(data.get("creator", "Unknown")))
    for mod_name, mod_data in (data.get("modules") or {}).items():
        attrs = mod_data.get("attributes", {}) or {}
        if attrs.get("top") in (1, "1"):
            netlist.top_module = mod_name
        module = NetlistModule(name=mod_name, attributes=dict(attrs))
        for port_name, port_data in (mod_data.get("ports") or {}).items():
            bits = list(port_data.get("bits", []) or [])
            module.ports[port_name] = NetPort(
                name=port_name,
                direction=port_data.get("direction", "input"),
                width=len(bits),
                bits=bits,
            )
        for cell_name, cell_data in (mod_data.get("cells") or {}).items():
            cell_type = str(cell_data.get("type", ""))
            cell = NetCell(
                name=cell_name,
                cell_type=cell_type,
                parameters=dict(cell_data.get("parameters", {}) or {}),
                connections={
                    pin: list(bits or [])
                    for pin, bits in (cell_data.get("connections", {}) or {}).items()
                },
                port_directions=dict(cell_data.get("port_directions", {}) or {}),
            )
            cell.is_sequential = cell.kind == "ff"
            module.cells[cell_name] = cell
            if not _is_tech_cell_type(cell_type):
                module.submodules[cell_name] = cell_type
        for wire_name, wire_data in (mod_data.get("netnames") or {}).items():
            bits = list(wire_data.get("bits", []) or [])
            module.wires[wire_name] = NetWire(
                name=wire_name,
                bits=bits,
                width=len(bits),
                is_signed=wire_data.get("signed", 0) == 1,
            )
        netlist.modules[mod_name] = module

    if not netlist.top_module and netlist.modules:
        top = netlist.get_top()
        if top:
            netlist.top_module = top.name
    return netlist


__all__ = [
    "NetPort",
    "NetCell",
    "NetWire",
    "NetlistModule",
    "Netlist",
    "parse_yosys_json",
    "parse_yosys_json_string",
]
