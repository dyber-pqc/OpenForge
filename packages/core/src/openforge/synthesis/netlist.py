"""Yosys JSON netlist parser and analysis utilities."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Port:
    """A module port (input, output, or inout)."""

    name: str
    direction: str  # "input", "output", "inout"
    bits: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Cell:
    """A cell instance inside a module."""

    name: str
    type: str
    connections: dict[str, list[int]] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Net:
    """A net connecting cells within a module."""

    name: str
    bits: list[int] = field(default_factory=list)
    driver: str | None = None
    loads: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Module:
    """A module in the synthesised netlist."""

    name: str
    cells: list[Cell] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)


# ---------------------------------------------------------------------------
# NetlistParser
# ---------------------------------------------------------------------------


class NetlistParser:
    """Parse and analyse Yosys JSON or gate-level Verilog netlists.

    Typical workflow::

        parser = NetlistParser()
        parser.load_json("synth_build/netlist.json")
        print(parser.modules)
        print(parser.get_hierarchy_stats())
    """

    def __init__(self) -> None:
        self._modules: list[Module] = []
        self._modules_by_name: dict[str, Module] = {}
        # bit -> (cell_name, port_name) for driver tracking
        self._bit_drivers: dict[int, tuple[str, str]] = {}
        # bit -> list[(cell_name, port_name)] for load tracking
        self._bit_loads: dict[int, list[tuple[str, str]]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def modules(self) -> list[Module]:
        """All parsed modules."""
        return self._modules

    @property
    def cells(self) -> list[Cell]:
        """All cells across every parsed module."""
        return [c for m in self._modules for c in m.cells]

    @property
    def nets(self) -> list[Net]:
        """All nets across every parsed module."""
        return [n for m in self._modules for n in m.nets]

    @property
    def ports(self) -> list[Port]:
        """All ports across every parsed module."""
        return [p for m in self._modules for p in m.ports]

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def load_json(self, json_path: str | PathLike[str]) -> None:
        """Parse a Yosys JSON netlist file.

        The Yosys JSON format (``write_json``) contains a ``modules``
        dict where each entry holds ``ports``, ``cells``, and
        ``netnames``.
        """
        path = Path(json_path)
        data = json.loads(path.read_text())

        self._modules.clear()
        self._modules_by_name.clear()
        self._bit_drivers.clear()
        self._bit_loads.clear()

        for mod_name, mod_data in data.get("modules", {}).items():
            module = self._parse_json_module(mod_name, mod_data)
            self._modules.append(module)
            self._modules_by_name[mod_name] = module

        # Build connectivity index
        self._build_connectivity_index()

    def _parse_json_module(self, name: str, data: dict[str, Any]) -> Module:
        """Parse a single module entry from the JSON."""
        ports: list[Port] = []
        for port_name, port_data in data.get("ports", {}).items():
            ports.append(Port(
                name=port_name,
                direction=port_data.get("direction", "input"),
                bits=port_data.get("bits", []),
            ))

        cells: list[Cell] = []
        for cell_name, cell_data in data.get("cells", {}).items():
            connections: dict[str, list[int]] = {}
            for conn_name, conn_bits in cell_data.get("connections", {}).items():
                connections[conn_name] = [
                    b for b in conn_bits if isinstance(b, int)
                ]

            cells.append(Cell(
                name=cell_name,
                type=cell_data.get("type", ""),
                connections=connections,
                parameters=cell_data.get("parameters", {}),
                attributes=cell_data.get("attributes", {}),
            ))

        nets: list[Net] = []
        for net_name, net_data in data.get("netnames", {}).items():
            nets.append(Net(
                name=net_name,
                bits=net_data.get("bits", []),
            ))

        return Module(name=name, cells=cells, nets=nets, ports=ports)

    def load_verilog(self, verilog_path: str | PathLike[str]) -> None:
        """Parse a gate-level Verilog netlist (basic).

        This is a lightweight parser that extracts module declarations,
        wire/port declarations, and cell instantiations.  It does not
        handle full Verilog syntax.
        """
        path = Path(verilog_path)
        text = path.read_text()

        self._modules.clear()
        self._modules_by_name.clear()
        self._bit_drivers.clear()
        self._bit_loads.clear()

        # Split on module declarations
        module_blocks = re.split(r"\bmodule\b", text)
        for block in module_blocks[1:]:  # skip preamble before first module
            module = self._parse_verilog_module(block)
            if module:
                self._modules.append(module)
                self._modules_by_name[module.name] = module

        self._build_connectivity_index()

    def _parse_verilog_module(self, block: str) -> Module | None:
        """Parse a single module block from gate-level Verilog."""
        # Module name
        name_match = re.match(r"\s*(\w+)", block)
        if not name_match:
            return None
        mod_name = name_match.group(1)

        ports: list[Port] = []
        cells: list[Cell] = []
        nets: list[Net] = []

        # Parse input/output/inout declarations
        for direction in ("input", "output", "inout"):
            for m in re.finditer(
                rf"\b{direction}\b\s+(?:\[[\d:]+\]\s+)?(\w+)",
                block,
            ):
                port_name = m.group(1)
                ports.append(Port(name=port_name, direction=direction))

        # Parse wire declarations
        for m in re.finditer(r"\bwire\b\s+(?:\[[\d:]+\]\s+)?(\w+)", block):
            nets.append(Net(name=m.group(1)))

        # Parse cell instances: <cell_type> <inst_name> ( ... );
        for m in re.finditer(
            r"(\w+)\s+(\w+)\s*\(([^)]*)\)\s*;",
            block,
        ):
            cell_type = m.group(1)
            cell_name = m.group(2)
            # Skip wire/reg/input/output/assign keywords
            if cell_type in (
                "wire", "reg", "input", "output", "inout",
                "assign", "endmodule", "module",
            ):
                continue
            connections: dict[str, list[int]] = {}
            conn_text = m.group(3)
            for cm in re.finditer(r"\.(\w+)\s*\(([^)]*)\)", conn_text):
                connections[cm.group(1)] = []  # bit-level tracking not available
            cells.append(Cell(
                name=cell_name,
                type=cell_type,
                connections=connections,
            ))

        return Module(name=mod_name, cells=cells, nets=nets, ports=ports)

    # ------------------------------------------------------------------
    # Connectivity index
    # ------------------------------------------------------------------

    def _build_connectivity_index(self) -> None:
        """Build bit-level driver/load maps for all modules."""
        self._bit_drivers.clear()
        self._bit_loads.clear()

        for module in self._modules:
            # Port drivers: output ports drive their bits
            for port in module.ports:
                if port.direction == "output":
                    for bit in port.bits:
                        if isinstance(bit, int):
                            self._bit_drivers[bit] = (f"port:{port.name}", "")

                if port.direction == "input":
                    for bit in port.bits:
                        if isinstance(bit, int):
                            self._bit_drivers[bit] = (f"port:{port.name}", "")

            # Cell connectivity
            for cell in module.cells:
                for conn_name, bits in cell.connections.items():
                    # Heuristic: output ports of cells are drivers
                    is_output = conn_name in ("Y", "Q", "Z", "X", "CO", "S", "SUM", "COUT")
                    for bit in bits:
                        if not isinstance(bit, int):
                            continue
                        if is_output:
                            self._bit_drivers[bit] = (cell.name, conn_name)
                        else:
                            self._bit_loads[bit].append((cell.name, conn_name))

            # Annotate nets with drivers and loads
            for net in module.nets:
                drivers: list[str] = []
                loads: list[str] = []
                for bit in net.bits:
                    if not isinstance(bit, int):
                        continue
                    if bit in self._bit_drivers:
                        drivers.append(self._bit_drivers[bit][0])
                    for cell_name, _ in self._bit_loads.get(bit, []):
                        loads.append(cell_name)
                net.driver = drivers[0] if drivers else None
                net.loads = list(dict.fromkeys(loads))  # deduplicate, preserve order

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_fanout(self, net_name: str) -> list[str]:
        """Return the list of cell names driven by *net_name*.

        Parameters
        ----------
        net_name:
            Name of the net to query.

        Returns
        -------
        list[str]
            Cell instance names that are loads of this net.
        """
        for module in self._modules:
            for net in module.nets:
                if net.name == net_name:
                    return list(net.loads)
        return []

    def get_fanin(self, cell_name: str) -> list[str]:
        """Return the list of net names that drive inputs of *cell_name*.

        Parameters
        ----------
        cell_name:
            Name of the cell instance to query.

        Returns
        -------
        list[str]
            Net names whose bits feed into this cell.
        """
        driving_nets: list[str] = []
        for module in self._modules:
            cell = next((c for c in module.cells if c.name == cell_name), None)
            if cell is None:
                continue
            input_bits: set[int] = set()
            for conn_name, bits in cell.connections.items():
                # Input pins
                if conn_name not in ("Y", "Q", "Z", "X", "CO", "S", "SUM", "COUT"):
                    input_bits.update(b for b in bits if isinstance(b, int))
            for net in module.nets:
                if any(b in input_bits for b in net.bits if isinstance(b, int)):
                    driving_nets.append(net.name)
        return driving_nets

    def get_critical_cone(self, output_port: str) -> list[Cell]:
        """Return the transitive fanin cone of cells driving *output_port*.

        Performs a backward BFS from the output port through the
        connectivity graph to collect all cells in the timing cone.

        Parameters
        ----------
        output_port:
            Name of the output port whose cone to trace.

        Returns
        -------
        list[Cell]
            All cells in the transitive fanin cone, in BFS order.
        """
        cone_cells: list[Cell] = []
        visited_cells: set[str] = set()

        # Find the output port bits
        target_bits: set[int] = set()
        for module in self._modules:
            for port in module.ports:
                if port.name == output_port and port.direction == "output":
                    target_bits.update(
                        b for b in port.bits if isinstance(b, int)
                    )

        if not target_bits:
            return []

        # BFS backwards through drivers
        queue_bits: list[int] = list(target_bits)
        visited_bits: set[int] = set(target_bits)

        while queue_bits:
            bit = queue_bits.pop(0)
            driver = self._bit_drivers.get(bit)
            if driver is None:
                continue
            cell_name, _ = driver
            if cell_name.startswith("port:") or cell_name in visited_cells:
                continue
            visited_cells.add(cell_name)

            # Find the cell object
            for module in self._modules:
                for cell in module.cells:
                    if cell.name == cell_name:
                        cone_cells.append(cell)
                        # Enqueue all input bits of this cell
                        for conn_name, bits in cell.connections.items():
                            if conn_name in ("Y", "Q", "Z", "X", "CO", "S", "SUM", "COUT"):
                                continue
                            for b in bits:
                                if isinstance(b, int) and b not in visited_bits:
                                    visited_bits.add(b)
                                    queue_bits.append(b)
                        break

        return cone_cells

    def get_hierarchy_stats(self) -> dict[str, Any]:
        """Return summary statistics about the parsed netlist.

        Returns
        -------
        dict
            Keys: ``cell_count_by_type``, ``total_cells``,
            ``flip_flop_count``, ``latch_count``,
            ``combinational_depth_estimate``, ``port_count``,
            ``net_count``.
        """
        cell_count_by_type: dict[str, int] = defaultdict(int)
        ff_count = 0
        latch_count = 0
        total_cells = 0

        for module in self._modules:
            for cell in module.cells:
                cell_count_by_type[cell.type] += 1
                total_cells += 1

                ctype = cell.type.lower()
                # Detect flip-flops
                if any(kw in ctype for kw in ("dff", "sdff", "adff", "dffs", "dffe", "flop")):
                    ff_count += 1
                # Detect latches
                elif any(kw in ctype for kw in ("dlatch", "latch", "adlatch")):
                    latch_count += 1

        # Estimate combinational depth: longest chain of non-FF cells
        # from any input port to any FF or output port.
        # Simple heuristic: count max number of combinational cells in
        # any critical cone.
        max_depth = 0
        for module in self._modules:
            for port in module.ports:
                if port.direction == "output":
                    cone = self.get_critical_cone(port.name)
                    comb_depth = sum(
                        1 for c in cone
                        if not any(
                            kw in c.type.lower()
                            for kw in ("dff", "sdff", "adff", "latch", "flop")
                        )
                    )
                    max_depth = max(max_depth, comb_depth)

        total_ports = sum(len(m.ports) for m in self._modules)
        total_nets = sum(len(m.nets) for m in self._modules)

        return {
            "cell_count_by_type": dict(cell_count_by_type),
            "total_cells": total_cells,
            "flip_flop_count": ff_count,
            "latch_count": latch_count,
            "combinational_depth_estimate": max_depth,
            "port_count": total_ports,
            "net_count": total_nets,
        }
