"""Parasitic extraction - generate SPEF file from layout.

Calibre xRC equivalent. Extracts net resistances and capacitances
including coupling capacitances between adjacent nets. The implementation
operates on a parsed DEF + LEF view of the design and emits an industry
standard SPEF file consumable by static timing tools (OpenSTA, PrimeTime).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class NetParasitics:
    """Parasitics for a single net."""

    name: str
    total_capacitance_ff: float
    total_resistance_ohm: float
    distributed_segments: list[dict] = field(default_factory=list)
    coupling_caps: dict[str, float] = field(default_factory=dict)

    def add_segment(
        self,
        node1: str,
        node2: str,
        r_ohm: float,
        c_ff: float,
        layer: str = "",
    ) -> None:
        self.distributed_segments.append(
            {"n1": node1, "n2": node2, "r": r_ohm, "c": c_ff, "layer": layer}
        )

    def add_coupling(self, other: str, c_ff: float) -> None:
        self.coupling_caps[other] = self.coupling_caps.get(other, 0.0) + c_ff


@dataclass
class SpefData:
    """Complete SPEF model for a design."""

    design_name: str
    units_t: str = "PS"
    units_c: str = "FF"
    units_r: str = "OHM"
    units_l: str = "HENRY"
    nets: dict[str, NetParasitics] = field(default_factory=dict)

    def add_net(self, net: NetParasitics) -> None:
        self.nets[net.name] = net

    def total_capacitance_ff(self) -> float:
        return sum(n.total_capacitance_ff for n in self.nets.values())

    def total_resistance_ohm(self) -> float:
        return sum(n.total_resistance_ohm for n in self.nets.values())

    def num_nets(self) -> int:
        return len(self.nets)

    def num_coupling(self) -> int:
        return sum(len(n.coupling_caps) for n in self.nets.values())


# ----------------------------------------------------------------------
# DEF parsing helpers (a small, tolerant subset just for SPECIALNETS/NETS)
# ----------------------------------------------------------------------


@dataclass
class _Wire:
    layer: str
    points: list[tuple[float, float]]
    width_um: float = 0.14


def _parse_def_units(text: str) -> int:
    m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
    return int(m.group(1)) if m else 1000


def _parse_def_nets(text: str, units: int) -> dict[str, list[_Wire]]:
    """Parse DEF NETS section into a {net_name: [Wire, ...]} mapping."""
    nets: dict[str, list[_Wire]] = {}
    in_nets = False
    cur_net: str | None = None
    cur_layer = ""
    cur_pts: list[tuple[float, float]] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("NETS "):
            in_nets = True
            continue
        if s.startswith("END NETS"):
            in_nets = False
            cur_net = None
            continue
        if not in_nets:
            continue
        if s.startswith("- "):
            cur_net = s.split()[1]
            nets.setdefault(cur_net, [])
            continue
        if cur_net is None:
            continue
        # Routing tokens look like: + ROUTED met1 ( x y ) ( x y ) NEW met2 ( ... )
        if "ROUTED" in s or "NEW" in s:
            tokens = s.replace("(", " ( ").replace(")", " ) ").split()
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok in ("ROUTED", "NEW"):
                    if i + 1 < len(tokens):
                        cur_layer = tokens[i + 1]
                    cur_pts = []
                    i += 2
                    continue
                if tok == "(":
                    try:
                        x = float(tokens[i + 1]) / units
                        y = float(tokens[i + 2]) / units
                        cur_pts.append((x, y))
                        i += 4  # skip ( x y )
                        continue
                    except (ValueError, IndexError):
                        i += 1
                        continue
                i += 1
            if cur_layer and len(cur_pts) >= 2:
                nets[cur_net].append(_Wire(layer=cur_layer, points=cur_pts.copy()))
    return nets


# ----------------------------------------------------------------------
# Extractor
# ----------------------------------------------------------------------


class ParasiticExtractor:
    """Extract parasitics from a placed/routed layout."""

    def __init__(self, technology: str = "sky130", parent=None):
        self.tech = technology
        self._parent = parent
        # Per-layer sheet resistance (ohm/sq)
        self._sheet_r = {
            "li1": 12.8,
            "met1": 0.125,
            "met2": 0.125,
            "met3": 0.047,
            "met4": 0.047,
            "met5": 0.029,
        }
        # Per-layer area capacitance (fF/um^2)
        self._cap_per_um2 = {
            "li1": 0.085,
            "met1": 0.075,
            "met2": 0.075,
            "met3": 0.060,
            "met4": 0.060,
            "met5": 0.050,
        }
        # Per-layer fringe capacitance (fF/um)
        self._fringe = {
            "li1": 0.040,
            "met1": 0.040,
            "met2": 0.040,
            "met3": 0.035,
            "met4": 0.035,
            "met5": 0.030,
        }
        # Default wire widths (um) when not given by LEF.
        self._default_widths = {
            "li1": 0.17,
            "met1": 0.14,
            "met2": 0.14,
            "met3": 0.30,
            "met4": 0.30,
            "met5": 1.60,
        }
        self._coupling_threshold_um = 0.5
        self._epsilon_ox = 0.0345  # fF/um for fringe coupling

    # -------------------- public API --------------------

    def extract(
        self,
        def_path: Path,
        lef_path: Path,
        output_spef: Path,
        with_coupling: bool = True,
    ) -> SpefData:
        """Extract parasitics from DEF + LEF and write SPEF."""
        text = def_path.read_text(encoding="utf-8", errors="ignore")
        units = _parse_def_units(text)
        net_wires = _parse_def_nets(text, units)

        design = self._design_name(text) or def_path.stem
        data = SpefData(design_name=design)

        for net, wires in net_wires.items():
            np_obj = self._extract_net(net, wires)
            data.add_net(np_obj)

        if with_coupling:
            self._compute_all_coupling(data, net_wires)

        self.write_spef(data, output_spef)
        return data

    def _design_name(self, def_text: str) -> str | None:
        m = re.search(r"DESIGN\s+(\S+)", def_text)
        return m.group(1) if m else None

    def _extract_net(self, name: str, wires: list[_Wire]) -> NetParasitics:
        np_obj = NetParasitics(
            name=name,
            total_capacitance_ff=0.0,
            total_resistance_ohm=0.0,
        )
        node_idx = 0
        for w in wires:
            length = self._wire_length_um(w.points)
            if length <= 0:
                continue
            width = self._default_widths.get(w.layer, 0.14)
            r = self.compute_segment_resistance(w.layer, length, width)
            c = self.compute_segment_capacitance(w.layer, length, width)
            np_obj.total_resistance_ohm += r
            np_obj.total_capacitance_ff += c
            n1 = f"{name}:{node_idx}"
            n2 = f"{name}:{node_idx + 1}"
            np_obj.add_segment(n1, n2, r, c, w.layer)
            node_idx += 1
        return np_obj

    # -------------------- geometry / R / C --------------------

    @staticmethod
    def _wire_length_um(points: list[tuple[float, float]]) -> float:
        total = 0.0
        for i in range(len(points) - 1):
            dx = points[i + 1][0] - points[i][0]
            dy = points[i + 1][1] - points[i][1]
            total += math.sqrt(dx * dx + dy * dy)
        return total

    def compute_segment_resistance(
        self, layer: str, length_um: float, width_um: float
    ) -> float:
        sheet = self._sheet_r.get(layer, 0.1)
        if width_um <= 0:
            return 0.0
        return sheet * (length_um / width_um)

    def compute_segment_capacitance(
        self, layer: str, length_um: float, width_um: float
    ) -> float:
        area_c = self._cap_per_um2.get(layer, 0.07) * (length_um * width_um)
        fringe_c = self._fringe.get(layer, 0.04) * (2.0 * length_um)
        return area_c + fringe_c

    def compute_net_resistance(self, segments: list, layer_r: dict) -> float:
        total = 0.0
        for seg in segments:
            sheet = layer_r.get(seg.get("layer", ""), 0.1)
            length = seg.get("length", 0.0)
            width = seg.get("width", 0.14) or 0.14
            if width > 0:
                total += sheet * length / width
        return total

    def compute_self_capacitance(self, geometry: list) -> float:
        total = 0.0
        for seg in geometry:
            layer = seg.get("layer", "met1")
            length = seg.get("length", 0.0)
            width = seg.get("width", 0.14)
            total += self.compute_segment_capacitance(layer, length, width)
        return total

    def compute_coupling_capacitance(
        self, net_a, net_b, distance_um: float
    ) -> float:
        """Approximate coupling cap between two parallel wires."""
        if distance_um <= 0:
            distance_um = 0.05
        # Use the shorter total length as overlap proxy.
        overlap = 0.0
        try:
            la = sum(self._wire_length_um(w.points) for w in net_a)
            lb = sum(self._wire_length_um(w.points) for w in net_b)
            overlap = min(la, lb) * 0.25
        except Exception:
            overlap = 0.0
        return self._epsilon_ox * overlap / distance_um

    # -------------------- coupling extraction --------------------

    def _compute_all_coupling(
        self, data: SpefData, net_wires: dict[str, list[_Wire]]
    ) -> None:
        """O(N^2) approximate coupling extraction."""
        names = list(net_wires.keys())
        boxes: dict[str, tuple[float, float, float, float]] = {}
        for n in names:
            boxes[n] = self._bounding_box(net_wires[n])
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                dist = self._box_distance(boxes[a], boxes[b])
                if dist > self._coupling_threshold_um:
                    continue
                c = self.compute_coupling_capacitance(net_wires[a], net_wires[b], dist)
                if c <= 0:
                    continue
                data.nets[a].add_coupling(b, c)
                data.nets[b].add_coupling(a, c)

    @staticmethod
    def _bounding_box(
        wires: list[_Wire],
    ) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for w in wires:
            for x, y in w.points:
                xs.append(x)
                ys.append(y)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _box_distance(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        dx = max(0.0, max(bx1 - ax2, ax1 - bx2))
        dy = max(0.0, max(by1 - ay2, ay1 - by2))
        return math.sqrt(dx * dx + dy * dy)

    # -------------------- SPEF I/O --------------------

    def write_spef(self, data: SpefData, path: Path) -> None:
        """Write SpefData to a SPEF file (industry standard)."""
        lines: list[str] = []
        lines.append('*SPEF "IEEE 1481-1998"')
        lines.append(f'*DESIGN "{data.design_name}"')
        lines.append('*DATE "auto-generated"')
        lines.append('*VENDOR "OpenForge"')
        lines.append('*PROGRAM "openforge-xrc"')
        lines.append('*VERSION "1.0"')
        lines.append('*DESIGN_FLOW "EXTERNAL_LOADS" "EXTERNAL_SLEWS"')
        lines.append('*DIVIDER /')
        lines.append('*DELIMITER :')
        lines.append('*BUS_DELIMITER [ ]')
        lines.append(f"*T_UNIT 1 {data.units_t}")
        lines.append(f"*C_UNIT 1 {data.units_c}")
        lines.append(f"*R_UNIT 1 {data.units_r}")
        lines.append(f"*L_UNIT 1 {data.units_l}")
        lines.append("")
        for name, net in data.nets.items():
            lines.append(f"*D_NET {name} {net.total_capacitance_ff:.4f}")
            lines.append("*CONN")
            lines.append("*CAP")
            idx = 1
            for seg in net.distributed_segments:
                lines.append(f"{idx} {seg['n1']} {seg['c']:.4f}")
                idx += 1
            for other, c in net.coupling_caps.items():
                lines.append(f"{idx} {name}:0 {other}:0 {c:.4f}")
                idx += 1
            lines.append("*RES")
            idx = 1
            for seg in net.distributed_segments:
                lines.append(f"{idx} {seg['n1']} {seg['n2']} {seg['r']:.4f}")
                idx += 1
            lines.append("*END")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


def parse_spef(filepath: Path) -> SpefData:
    """Parse an existing SPEF file into a SpefData structure."""
    text = filepath.read_text(encoding="utf-8", errors="ignore")
    design_match = re.search(r'\*DESIGN\s+"([^"]+)"', text)
    design = design_match.group(1) if design_match else filepath.stem
    data = SpefData(design_name=design)

    cur_net: NetParasitics | None = None
    section: str = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("*D_NET"):
            parts = line.split()
            name = parts[1]
            tot = float(parts[2]) if len(parts) > 2 else 0.0
            cur_net = NetParasitics(
                name=name,
                total_capacitance_ff=tot,
                total_resistance_ohm=0.0,
            )
            data.add_net(cur_net)
            section = ""
            continue
        if line == "*END":
            cur_net = None
            section = ""
            continue
        if cur_net is None:
            continue
        if line.startswith("*CAP"):
            section = "cap"
            continue
        if line.startswith("*RES"):
            section = "res"
            continue
        if line.startswith("*CONN"):
            section = "conn"
            continue
        parts = line.split()
        if section == "cap" and len(parts) >= 3:
            try:
                if len(parts) == 3:
                    c = float(parts[2])
                    cur_net.add_segment(parts[1], parts[1], 0.0, c)
                elif len(parts) == 4:
                    other = parts[2].split(":")[0]
                    c = float(parts[3])
                    cur_net.add_coupling(other, c)
            except ValueError:
                pass
        elif section == "res" and len(parts) >= 4:
            try:
                r = float(parts[3])
                cur_net.add_segment(parts[1], parts[2], r, 0.0)
                cur_net.total_resistance_ohm += r
            except ValueError:
                pass
    return data
