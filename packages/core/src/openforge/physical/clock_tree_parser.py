"""Clock tree parser.

Parses clock tree structures from:
  * OpenROAD ``report_clock_tree`` / ``report_cts`` output
  * DEF + SDF (Standard Delay Format) file pairs
  * Cadence Innovus ``report_clock_timing`` output

The parsed :class:`CtsTree` is the single source of truth used by the
clock-tree viewer panel and by downstream analyses (useful-skew,
insertion-delay histograms, etc.).
"""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CtsNode(BaseModel):
    """A node (buffer / inverter / root driver) in the clock tree."""

    name: str
    cell_type: str = ""
    x_um: float = 0.0
    y_um: float = 0.0
    level: int = 0
    parent: str | None = None
    children: list[str] = Field(default_factory=list)
    insertion_delay_ns: float = 0.0
    transition_ns: float = 0.0


class CtsSink(BaseModel):
    """A clock sink -- a flip-flop clock pin."""

    instance: str
    pin: str = "CLK"
    level: int = 0
    arrival_ns: float = 0.0
    transition_ns: float = 0.0
    x_um: float = 0.0
    y_um: float = 0.0


class CtsTree(BaseModel):
    """Parsed clock tree for a single clock domain."""

    clock_name: str
    root: CtsNode
    sinks: list[CtsSink] = Field(default_factory=list)
    nodes: dict[str, CtsNode] = Field(default_factory=dict)

    # ----- summary properties -------------------------------------------

    @property
    def num_buffers(self) -> int:
        return sum(
            1
            for n in self.nodes.values()
            if "buf" in n.cell_type.lower() and "inv" not in n.cell_type.lower()
        )

    @property
    def num_inverters(self) -> int:
        return sum(1 for n in self.nodes.values() if "inv" in n.cell_type.lower())

    @property
    def num_levels(self) -> int:
        if not self.nodes and not self.sinks:
            return 0
        node_max = max((n.level for n in self.nodes.values()), default=0)
        sink_max = max((s.level for s in self.sinks), default=0)
        return max(node_max, sink_max)

    @property
    def max_skew_ns(self) -> float:
        if not self.sinks:
            return 0.0
        arrivals = [s.arrival_ns for s in self.sinks]
        return max(arrivals) - min(arrivals)

    @property
    def mean_insertion_ns(self) -> float:
        if not self.sinks:
            return 0.0
        return statistics.fmean(s.arrival_ns for s in self.sinks)

    @property
    def max_insertion_ns(self) -> float:
        if not self.sinks:
            return 0.0
        return max(s.arrival_ns for s in self.sinks)

    @property
    def std_insertion_ns(self) -> float:
        if len(self.sinks) < 2:
            return 0.0
        return statistics.pstdev(s.arrival_ns for s in self.sinks)

    # ----- queries ------------------------------------------------------

    def histogram(self, bins: int = 20) -> tuple[list[float], list[int]]:
        """Return (bin_edges, counts) for insertion-delay distribution.

        ``bin_edges`` has length ``bins + 1`` (leading + trailing edges).
        """
        if not self.sinks:
            return ([0.0], [0])
        arrivals = [s.arrival_ns for s in self.sinks]
        lo, hi = min(arrivals), max(arrivals)
        if math.isclose(lo, hi):
            # degenerate: all arrivals equal
            return ([lo, lo + 1e-6], [len(arrivals)])
        width = (hi - lo) / bins
        edges = [lo + i * width for i in range(bins + 1)]
        counts = [0] * bins
        for a in arrivals:
            idx = int((a - lo) / width)
            if idx >= bins:
                idx = bins - 1
            counts[idx] += 1
        return (edges, counts)

    def critical_paths(self, n: int = 10) -> list[CtsSink]:
        """Return the ``n`` sinks with the largest insertion delay."""
        return sorted(self.sinks, key=lambda s: s.arrival_ns, reverse=True)[:n]

    def path_to_root(self, sink_instance: str) -> list[str]:
        """Walk parent links for a sink and return [root, ..., sink] node names."""
        # Find the nearest node whose name is a prefix/ancestor of the sink.
        # SDF / OpenROAD typically name leaf buffers ``<inst>/clkbuf_leaf``
        # or the sink's driver is recorded as its parent. For a best-effort
        # lookup we first try direct children, then fall back to the root.
        for node in self.nodes.values():
            if sink_instance in node.children:
                chain: list[str] = []
                cur: str | None = node.name
                while cur is not None:
                    chain.append(cur)
                    parent = self.nodes.get(cur).parent if cur in self.nodes else None
                    cur = parent
                chain.reverse()
                chain.append(sink_instance)
                return chain
        return [self.root.name, sink_instance]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_NUM = r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


class CtsParser:
    """Parse clock trees from various EDA tool output formats."""

    # ------------------------------------------------------------------
    # OpenROAD ``report_clock_tree``
    # ------------------------------------------------------------------

    @staticmethod
    def from_openroad_report(text: str) -> CtsTree:
        """Parse OpenROAD ``report_clock_tree`` output.

        Expected form (OpenROAD TritonCTS)::

            Clock net "clk"
              Number of Buffers: 42
              Number of Inverters: 0
              Number of Levels: 5
              Max skew: 0.120 ns
              Sinks:
                u_core/u_ff_data_reg_0_/CK level=5 arrival=0.742 trans=0.082
                  x=123.4 y=456.7
                ...
              Nodes:
                clkbuf_0 level=0 cell=sky130_fd_sc_hd__clkbuf_4 x=100 y=200 ins=0.045
                clkbuf_1_0 level=1 parent=clkbuf_0 cell=sky130_fd_sc_hd__clkbuf_2 ...
        """
        clock_name = "clk"
        m = re.search(r'Clock\s+net\s+"([^"]+)"', text)
        if m:
            clock_name = m.group(1)
        else:
            m = re.search(r"Clock\s+(\S+)", text)
            if m:
                clock_name = m.group(1)

        nodes: dict[str, CtsNode] = {}
        sinks: list[CtsSink] = []

        # Node lines
        node_re = re.compile(
            r"^\s*(\S+)\s+level=(\d+)"
            r"(?:\s+parent=(\S+))?"
            r"(?:\s+cell=(\S+))?"
            r"(?:\s+x=" + _NUM + r")?"
            r"(?:\s+y=" + _NUM + r")?"
            r"(?:\s+ins=" + _NUM + r")?"
            r"(?:\s+trans=" + _NUM + r")?",
            re.MULTILINE,
        )

        in_nodes = False
        in_sinks = False
        last_sink: CtsSink | None = None

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                continue
            low = line.strip().lower()
            if low.startswith("nodes:"):
                in_nodes, in_sinks = True, False
                continue
            if low.startswith("sinks:"):
                in_sinks, in_nodes = True, False
                continue
            if low.startswith("clock ") or low.startswith("number of"):
                in_nodes = in_sinks = False
                continue

            if in_sinks:
                sm = re.match(
                    r"\s*(\S+?)/(\S+?)\s+level=(\d+)\s+arrival="
                    + _NUM
                    + r"(?:\s+trans="
                    + _NUM
                    + r")?",
                    line,
                )
                if sm:
                    last_sink = CtsSink(
                        instance=sm.group(1),
                        pin=sm.group(2),
                        level=int(sm.group(3)),
                        arrival_ns=float(sm.group(4)),
                        transition_ns=float(sm.group(5)) if sm.group(5) else 0.0,
                    )
                    sinks.append(last_sink)
                    continue
                cm = re.match(r"\s*x=" + _NUM + r"\s+y=" + _NUM, line)
                if cm and last_sink is not None:
                    last_sink.x_um = float(cm.group(1))
                    last_sink.y_um = float(cm.group(2))
                    continue

            if in_nodes:
                nm = node_re.match(line)
                if nm:
                    name = nm.group(1)
                    node = CtsNode(
                        name=name,
                        level=int(nm.group(2)),
                        parent=nm.group(3),
                        cell_type=nm.group(4) or "",
                        x_um=float(nm.group(5)) if nm.group(5) else 0.0,
                        y_um=float(nm.group(6)) if nm.group(6) else 0.0,
                        insertion_delay_ns=float(nm.group(7)) if nm.group(7) else 0.0,
                        transition_ns=float(nm.group(8)) if nm.group(8) else 0.0,
                    )
                    nodes[name] = node

        # Wire children from parent links
        for name, node in nodes.items():
            if node.parent and node.parent in nodes:
                nodes[node.parent].children.append(name)

        root = _pick_root(nodes, clock_name)

        # Any sink whose level is implied but not set, attach as leaf child
        for s in sinks:
            # find nearest node by level-1 that has coordinates close by
            candidates = [n for n in nodes.values() if n.level == s.level - 1]
            if candidates:
                nearest = min(
                    candidates,
                    key=lambda n: (n.x_um - s.x_um) ** 2 + (n.y_um - s.y_um) ** 2,
                )
                if s.instance not in nearest.children:
                    nearest.children.append(s.instance)

        return CtsTree(clock_name=clock_name, root=root, sinks=sinks, nodes=nodes)

    # ------------------------------------------------------------------
    # DEF + SDF
    # ------------------------------------------------------------------

    @staticmethod
    def from_def_and_sdf(
        def_path: str | Path,
        sdf_path: str | Path,
        clock_name: str = "clk",
    ) -> CtsTree:
        """Build a clock tree by combining component placement from DEF with
        arrival-time annotation from SDF.

        The DEF file gives us x/y coordinates and cell types for every
        instance. The SDF file gives us per-pin arrival / transition times
        on clock buffers and flip-flop clock pins.
        """
        def_text = Path(def_path).read_text(errors="ignore")
        sdf_text = Path(sdf_path).read_text(errors="ignore")

        placements = _parse_def_components(def_text)
        delays = _parse_sdf_arrivals(sdf_text)

        nodes: dict[str, CtsNode] = {}
        sinks: list[CtsSink] = []

        for inst, (cell_type, x, y) in placements.items():
            cell_low = cell_type.lower()
            if any(tok in cell_low for tok in ("clkbuf", "clkinv", "clkbuf_")):
                arrival, trans = delays.get(inst, (0.0, 0.0))
                nodes[inst] = CtsNode(
                    name=inst,
                    cell_type=cell_type,
                    x_um=x,
                    y_um=y,
                    insertion_delay_ns=arrival,
                    transition_ns=trans,
                )
            elif "dff" in cell_low or "sdff" in cell_low or "latch" in cell_low:
                arrival, trans = delays.get(inst, (0.0, 0.0))
                sinks.append(
                    CtsSink(
                        instance=inst,
                        pin="CLK",
                        level=0,
                        arrival_ns=arrival,
                        transition_ns=trans,
                        x_um=x,
                        y_um=y,
                    )
                )

        # Build a simple hierarchy: level 0 = the one with lowest arrival,
        # others bucketed by arrival delta.
        if nodes:
            sorted_nodes = sorted(nodes.values(), key=lambda n: n.insertion_delay_ns)
            base = sorted_nodes[0].insertion_delay_ns
            step = max(
                (sorted_nodes[-1].insertion_delay_ns - base) / 4.0,
                1e-3,
            )
            for n in sorted_nodes:
                n.level = int(round((n.insertion_delay_ns - base) / step))
            root = sorted_nodes[0]
        else:
            root = CtsNode(name=f"{clock_name}_root", cell_type="")
            nodes[root.name] = root

        # Put sinks at level = max_node_level + 1
        leaf_level = (max((n.level for n in nodes.values()), default=0)) + 1
        for s in sinks:
            s.level = leaf_level

        return CtsTree(clock_name=clock_name, root=root, sinks=sinks, nodes=nodes)

    # ------------------------------------------------------------------
    # Cadence Innovus
    # ------------------------------------------------------------------

    @staticmethod
    def from_innovus_clock_report(text: str) -> CtsTree:
        """Parse Cadence Innovus ``report_clock_timing`` output.

        Expected form::

            Clock: clk  Period: 10.00 ns
            +-------------------+--------+----------+----------+---------+
            | Instance          | Cell   | Level    | Ins (ns) | Tran    |
            +-------------------+--------+----------+----------+---------+
            | clkbuf_00         | CKBD1  |    0     | 0.045    | 0.082   |
            | clkbuf_01         | CKBD2  |    1     | 0.098    | 0.071   |
            ...
            Sinks:
              u_core/ff_0/CP  level=5 arrival=0.742 trans=0.085
              ...
        """
        clock_name = "clk"
        m = re.search(r"Clock:\s+(\S+)", text)
        if m:
            clock_name = m.group(1)

        nodes: dict[str, CtsNode] = {}
        sinks: list[CtsSink] = []

        row_re = re.compile(
            r"\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\d+)\s*\|\s*" + _NUM + r"\s*\|\s*" + _NUM + r"\s*\|"
        )
        for line in text.splitlines():
            rm = row_re.search(line)
            if rm:
                name = rm.group(1)
                nodes[name] = CtsNode(
                    name=name,
                    cell_type=rm.group(2),
                    level=int(rm.group(3)),
                    insertion_delay_ns=float(rm.group(4)),
                    transition_ns=float(rm.group(5)),
                )

        sink_re = re.compile(
            r"^\s*(\S+)/(\S+)\s+level=(\d+)\s+arrival=" + _NUM + r"(?:\s+trans=" + _NUM + r")?"
        )
        in_sinks = False
        for line in text.splitlines():
            if line.strip().lower().startswith("sinks"):
                in_sinks = True
                continue
            if in_sinks:
                sm = sink_re.match(line)
                if sm:
                    sinks.append(
                        CtsSink(
                            instance=sm.group(1),
                            pin=sm.group(2),
                            level=int(sm.group(3)),
                            arrival_ns=float(sm.group(4)),
                            transition_ns=float(sm.group(5)) if sm.group(5) else 0.0,
                        )
                    )

        root = _pick_root(nodes, clock_name)
        return CtsTree(clock_name=clock_name, root=root, sinks=sinks, nodes=nodes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_root(nodes: dict[str, CtsNode], clock_name: str) -> CtsNode:
    """Return the tree root: the level-0 node, or a synthetic one if none."""
    level0 = [n for n in nodes.values() if n.level == 0 and n.parent is None]
    if level0:
        return level0[0]
    if nodes:
        return min(nodes.values(), key=lambda n: n.level)
    root = CtsNode(name=f"{clock_name}_root", cell_type="")
    nodes[root.name] = root
    return root


_DEF_COMPONENT_RE = re.compile(
    r"-\s+(\S+)\s+(\S+)\s+.*?\(\s*(-?\d+)\s+(-?\d+)\s*\)",
    re.DOTALL,
)


def _parse_def_components(
    def_text: str,
) -> dict[str, tuple[str, float, float]]:
    """Return ``{instance_name: (cell_type, x_um, y_um)}`` from DEF.

    DEF coordinates are in database units (typically 1000/um). We scale
    by the ``UNITS DISTANCE MICRONS`` value if present.
    """
    scale = 1000.0
    um_match = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    if um_match:
        scale = float(um_match.group(1))

    # Locate the COMPONENTS ... END COMPONENTS block
    comp_match = re.search(
        r"COMPONENTS\s+\d+\s*;(.+?)END\s+COMPONENTS",
        def_text,
        re.DOTALL,
    )
    if not comp_match:
        return {}
    block = comp_match.group(1)

    out: dict[str, tuple[str, float, float]] = {}
    for m in _DEF_COMPONENT_RE.finditer(block):
        inst, cell, x, y = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        out[inst] = (cell, x / scale, y / scale)
    return out


def _parse_sdf_arrivals(sdf_text: str) -> dict[str, tuple[float, float]]:
    """Return ``{instance: (arrival_ns, transition_ns)}`` from SDF.

    We walk ``(CELL ... (INSTANCE <path>) (DELAY ...) )`` records and
    extract the typical (mid) value from ``IOPATH`` delay triples.
    SDF timing is already in nanoseconds.
    """
    out: dict[str, tuple[float, float]] = {}

    re.compile(r"\(CELL\s+(.*?)\)\s*\)\s*\)\s*\)", re.DOTALL)
    re.compile(r"\(INSTANCE\s+([^)]+)\)")
    iopath_re = re.compile(
        r"\(IOPATH\s+\S+\s+\S+\s+\(\s*" + _NUM + r":" + _NUM + r":" + _NUM + r"\s*\)"
    )
    trans_re = re.compile(
        r"\(ABSOLUTE\s+\(PORT\s+\S+\s+\(\s*" + _NUM + r":" + _NUM + r":" + _NUM + r"\s*\)"
    )

    depth = 0
    # Split by top-level ``(CELL ...)`` records
    cells: list[str] = []
    buf: list[str] = []
    for ch in sdf_text:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
            if depth == 0:
                cells.append("".join(buf))
                buf = []
        else:
            buf.append(ch)

    # Simpler fallback: scan by instance headers
    instance_chunks = re.split(r"\(INSTANCE\s+", sdf_text)
    for chunk in instance_chunks[1:]:
        name_match = re.match(r"([^\s)]+)", chunk)
        if not name_match:
            continue
        inst_name = name_match.group(1)
        arrival = 0.0
        trans = 0.0
        iopaths = iopath_re.findall(chunk)
        if iopaths:
            vals = [float(t[1]) for t in iopaths]  # typ values
            arrival = sum(vals)
        tr = trans_re.search(chunk)
        if tr:
            trans = float(tr.group(2))
        out[inst_name] = (arrival, trans)
    return out
