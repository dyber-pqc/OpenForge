"""Gate-level Verilog netlist parser.

Parses synthesized gate-level Verilog netlists for schematic viewing,
extracting module definitions, port/wire declarations, and cell
instances with named port connections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PortDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class NetlistPort:
    """A port declaration in a module."""

    name: str = ""
    direction: str = "input"
    width: int = 1
    msb: int = 0
    lsb: int = 0


@dataclass
class NetlistWire:
    """A wire declaration in a module."""

    name: str = ""
    width: int = 1
    msb: int = 0
    lsb: int = 0


@dataclass
class CellInstance:
    """An instantiated cell in the netlist."""

    name: str = ""
    cell_type: str = ""
    port_connections: dict[str, str] = field(default_factory=dict)


@dataclass
class NetlistModule:
    """A module in the gate-level netlist."""

    name: str = ""
    ports: list[NetlistPort] = field(default_factory=list)
    wires: list[NetlistWire] = field(default_factory=list)
    instances: list[CellInstance] = field(default_factory=list)

    def get_instance(self, name: str) -> CellInstance | None:
        """Find a cell instance by name."""
        for inst in self.instances:
            if inst.name == name:
                return inst
        return None

    def get_instances_of_type(self, cell_type: str) -> list[CellInstance]:
        """Return all instances of a given cell type."""
        return [i for i in self.instances if i.cell_type == cell_type]

    def cell_types_used(self) -> list[str]:
        """Return sorted list of unique cell types."""
        return sorted({i.cell_type for i in self.instances})

    def input_ports(self) -> list[NetlistPort]:
        """Return all input ports."""
        return [p for p in self.ports if p.direction == PortDirection.INPUT]

    def output_ports(self) -> list[NetlistPort]:
        """Return all output ports."""
        return [p for p in self.ports if p.direction == PortDirection.OUTPUT]


@dataclass
class NetlistData:
    """Top-level netlist data, may contain multiple modules."""

    modules: list[NetlistModule] = field(default_factory=list)

    def get_module(self, name: str) -> NetlistModule | None:
        """Find a module by name."""
        for mod in self.modules:
            if mod.name == name:
                return mod
        return None

    def top_module(self) -> NetlistModule | None:
        """Return the last module (typically the top-level in synthesis output)."""
        return self.modules[-1] if self.modules else None

    def module_names(self) -> list[str]:
        """Return sorted list of module names."""
        return sorted(m.name for m in self.modules)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_RE_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_COMMENT_LINE = re.compile(r"//.*$", re.MULTILINE)
_RE_BUS_RANGE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
_RE_MODULE = re.compile(r"module\s+(\w+)")
_RE_PORT_CONN = re.compile(r"\.(\w+)\s*\(([^)]*)\)")


class VerilogNetlistParser:
    """Parser for gate-level (synthesized) Verilog netlists."""

    def parse(self, path: str | Path) -> NetlistData:
        """Parse a gate-level Verilog file and return NetlistData."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Verilog netlist not found: {path}")

        text = path.read_text(encoding="utf-8", errors="replace")
        text = _RE_COMMENT_BLOCK.sub("", text)
        text = _RE_COMMENT_LINE.sub("", text)

        data = NetlistData()

        # Split into statements by semicolons, but keep module/endmodule structure
        # First, split text into module blocks
        module_blocks = self._split_modules(text)

        for mod_name, mod_body in module_blocks:
            module = NetlistModule(name=mod_name)
            self._parse_module_body(mod_body, module)
            data.modules.append(module)

        return data

    @staticmethod
    def _split_modules(text: str) -> list[tuple[str, str]]:
        """Split text into (module_name, module_body) pairs."""
        results: list[tuple[str, str]] = []
        pos = 0
        while pos < len(text):
            m = _RE_MODULE.search(text, pos)
            if not m:
                break
            mod_name = m.group(1)
            # Find matching endmodule
            start = m.end()
            end_pos = text.find("endmodule", start)
            if end_pos < 0:
                end_pos = len(text)
            body = text[start:end_pos]
            results.append((mod_name, body))
            pos = end_pos + len("endmodule")
        return results

    def _parse_module_body(self, body: str, module: NetlistModule) -> None:
        """Parse the contents between module ... endmodule."""
        # Remove module port list from the beginning: (...);
        body = re.sub(r"^\s*\([^;]*;\s*", "", body, count=1)

        # Split into statements
        statements = self._split_statements(body)

        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue

            # Port declarations
            dir_m = re.match(
                r"(input|output|inout)\s+(.*)",
                stmt,
                re.DOTALL,
            )
            if dir_m:
                direction = dir_m.group(1)
                rest = dir_m.group(2).strip()
                self._parse_port_decl(direction, rest, module)
                continue

            # Wire declarations
            wire_m = re.match(r"wire\s+(.*)", stmt, re.DOTALL)
            if wire_m:
                rest = wire_m.group(1).strip()
                self._parse_wire_decl(rest, module)
                continue

            # Assign statements (skip)
            if stmt.startswith("assign"):
                continue

            # Cell instantiation: CellType InstanceName ( .port(net), ... )
            inst = self._try_parse_instance(stmt)
            if inst:
                module.instances.append(inst)

    @staticmethod
    def _split_statements(body: str) -> list[str]:
        """Split body text into semicolon-delimited statements."""
        parts = body.split(";")
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _parse_port_decl(
        direction: str,
        rest: str,
        module: NetlistModule,
    ) -> None:
        """Parse a port declaration like 'input [7:0] data, clk'."""
        # Check for bus range
        msb, lsb, width = 0, 0, 1
        range_m = _RE_BUS_RANGE.search(rest)
        if range_m:
            msb = int(range_m.group(1))
            lsb = int(range_m.group(2))
            width = abs(msb - lsb) + 1
            rest = rest[: range_m.start()] + rest[range_m.end() :]

        # Check for optional 'wire' or 'reg' keyword
        rest = re.sub(r"\b(wire|reg)\b", "", rest).strip()

        # Split comma-separated names
        for name in rest.split(","):
            name = name.strip()
            if not name:
                continue
            # Individual port might have its own range
            pm = _RE_BUS_RANGE.search(name)
            p_msb, p_lsb, p_width = msb, lsb, width
            if pm:
                p_msb = int(pm.group(1))
                p_lsb = int(pm.group(2))
                p_width = abs(p_msb - p_lsb) + 1
                name = name[: pm.start()].strip() + name[pm.end() :].strip()
            name = name.strip()
            if name and re.match(r"^\w+$", name):
                module.ports.append(
                    NetlistPort(
                        name=name,
                        direction=direction,
                        width=p_width,
                        msb=p_msb,
                        lsb=p_lsb,
                    )
                )

    @staticmethod
    def _parse_wire_decl(rest: str, module: NetlistModule) -> None:
        """Parse a wire declaration like 'wire [3:0] w1, w2'."""
        msb, lsb, width = 0, 0, 1
        range_m = _RE_BUS_RANGE.search(rest)
        if range_m:
            msb = int(range_m.group(1))
            lsb = int(range_m.group(2))
            width = abs(msb - lsb) + 1
            rest = rest[: range_m.start()] + rest[range_m.end() :]

        for name in rest.split(","):
            name = name.strip()
            if not name:
                continue
            wm = _RE_BUS_RANGE.search(name)
            w_msb, w_lsb, w_width = msb, lsb, width
            if wm:
                w_msb = int(wm.group(1))
                w_lsb = int(wm.group(2))
                w_width = abs(w_msb - w_lsb) + 1
                name = name[: wm.start()].strip() + name[wm.end() :].strip()
            name = name.strip()
            if name and re.match(r"^\w+$", name):
                module.wires.append(
                    NetlistWire(
                        name=name,
                        width=w_width,
                        msb=w_msb,
                        lsb=w_lsb,
                    )
                )

    @staticmethod
    def _try_parse_instance(stmt: str) -> CellInstance | None:
        """Try to parse a cell instantiation statement."""
        # Pattern: CellType [#(...)] InstanceName ( .port(net), ... )
        # We need at least a cell type, instance name, and port connections

        # Find the parenthesized port connection block
        paren_start = stmt.find("(")
        if paren_start < 0:
            return None

        prefix = stmt[:paren_start].strip()
        tokens = prefix.split()
        if len(tokens) < 2:
            return None

        cell_type = tokens[0]

        # Skip parameter overrides: #(...)
        if len(tokens) >= 2 and tokens[1].startswith("#"):
            # Find the instance name after parameter block
            # Re-parse after the parameter block
            param_end = stmt.find(")", stmt.find("#("))
            if param_end < 0:
                return None
            rest = stmt[param_end + 1 :].strip()
            inst_paren = rest.find("(")
            if inst_paren < 0:
                return None
            inst_name = rest[:inst_paren].strip()
            port_block = rest[inst_paren:]
        else:
            inst_name = tokens[-1]
            port_block = stmt[paren_start:]

        # Skip keywords that aren't cell types
        if cell_type in (
            "module",
            "endmodule",
            "input",
            "output",
            "inout",
            "wire",
            "reg",
            "assign",
            "always",
            "initial",
            "parameter",
            "localparam",
            "generate",
            "genvar",
        ):
            return None

        # Parse named port connections: .port(net)
        connections = dict(_RE_PORT_CONN.findall(port_block))

        if not connections and not port_block.strip("() \t\n"):
            # Empty port list is valid
            pass

        return CellInstance(
            name=inst_name,
            cell_type=cell_type,
            port_connections=connections,
        )
