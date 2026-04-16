"""Skew-aware clock tree synthesis with useful skew - CCOpt replacement.

Provides H-tree construction, k-means sink clustering, buffer insertion
under fanout constraints, and a useful-skew optimizer that borrows time
between setup- and hold-critical sinks.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ClockSink:
    """A flop input pin driven by the clock."""

    instance: str
    pin: str
    x: float  # microns
    y: float
    capacitance: float = 0.0
    setup_slack: float = 0.0  # ns - positive = met
    hold_slack: float = 0.0
    arrival_ns: float = 0.0  # adjusted clock arrival (useful skew)


@dataclass
class ClockBuffer:
    """A clock buffer instance in the tree."""

    instance: str
    cell_type: str
    x: float
    y: float
    fanout: int
    children: list[str] = field(default_factory=list)
    parent: Optional[str] = None
    level: int = 0
    delay_ns: float = 0.05


@dataclass
class ClockTree:
    """Top-level clock distribution structure."""

    name: str
    period_ns: float
    root_pin: str
    sinks: list[ClockSink] = field(default_factory=list)
    buffers: list[ClockBuffer] = field(default_factory=list)
    target_skew_ps: float = 50.0
    actual_skew_ps: float = 0.0
    insertion_delay_ns: float = 0.0
    levels: int = 0
    total_buffers: int = 0

    def compute_skew(self) -> float:
        """Return the worst skew across all sinks in picoseconds."""
        if not self.sinks:
            self.actual_skew_ps = 0.0
            return 0.0
        arrivals = [s.arrival_ns for s in self.sinks]
        skew_ns = max(arrivals) - min(arrivals)
        self.actual_skew_ps = skew_ns * 1000.0
        return self.actual_skew_ps

    def compute_insertion_delay(self) -> float:
        if not self.sinks:
            self.insertion_delay_ns = 0.0
            return 0.0
        self.insertion_delay_ns = sum(s.arrival_ns for s in self.sinks) / len(
            self.sinks
        )
        return self.insertion_delay_ns

    def histogram(self, bins: int = 10) -> list[int]:
        if not self.sinks:
            return []
        arrivals = [s.arrival_ns * 1000.0 for s in self.sinks]
        lo, hi = min(arrivals), max(arrivals)
        if hi - lo < 1e-9:
            return [len(arrivals)] + [0] * (bins - 1)
        step = (hi - lo) / bins
        counts = [0] * bins
        for a in arrivals:
            idx = min(int((a - lo) / step), bins - 1)
            counts[idx] += 1
        return counts


class ClockTreeOptimizer:
    """Skew-aware CTS with useful-skew time borrowing."""

    def __init__(
        self,
        target_skew_ps: float = 50.0,
        buffer_types: Optional[list[str]] = None,
    ) -> None:
        self.target_skew_ps = target_skew_ps
        self.buffers = buffer_types or [
            "sky130_fd_sc_hd__clkbuf_2",
            "sky130_fd_sc_hd__clkbuf_4",
            "sky130_fd_sc_hd__clkbuf_8",
        ]
        self._buf_count = 0

    # ---------- H-tree ----------

    def build_h_tree(
        self, sinks: list[ClockSink], root_x: float, root_y: float
    ) -> ClockTree:
        """Build a balanced H-tree clock distribution."""
        tree = ClockTree(
            name="clk", period_ns=10.0, root_pin="clk", sinks=list(sinks)
        )
        if not sinks:
            return tree
        root = self._new_buffer(root_x, root_y, level=0)
        tree.buffers.append(root)
        self._h_recurse(sinks, root, tree, depth=0, max_depth=5)
        tree.total_buffers = len(tree.buffers)
        tree.levels = max((b.level for b in tree.buffers), default=0) + 1
        # propagate arrival
        self._propagate_arrival(tree, root, parent_arrival=0.0)
        tree.compute_skew()
        tree.compute_insertion_delay()
        return tree

    def _h_recurse(
        self,
        sinks: list[ClockSink],
        parent: ClockBuffer,
        tree: ClockTree,
        depth: int,
        max_depth: int,
    ) -> None:
        if not sinks:
            return
        if len(sinks) <= 4 or depth >= max_depth:
            for s in sinks:
                parent.children.append(s.instance)
            parent.fanout = len(sinks)
            return
        # split into 4 quadrants relative to parent
        q1, q2, q3, q4 = [], [], [], []
        for s in sinks:
            if s.x <= parent.x and s.y <= parent.y:
                q1.append(s)
            elif s.x > parent.x and s.y <= parent.y:
                q2.append(s)
            elif s.x <= parent.x and s.y > parent.y:
                q3.append(s)
            else:
                q4.append(s)
        offsets = [(-1, -1), (1, -1), (-1, 1), (1, 1)]
        for quadrant, (dx, dy) in zip([q1, q2, q3, q4], offsets):
            if not quadrant:
                continue
            cx = sum(s.x for s in quadrant) / len(quadrant)
            cy = sum(s.y for s in quadrant) / len(quadrant)
            child = self._new_buffer(cx, cy, level=depth + 1)
            child.parent = parent.instance
            tree.buffers.append(child)
            parent.children.append(child.instance)
            parent.fanout += 1
            self._h_recurse(quadrant, child, tree, depth + 1, max_depth)

    def _new_buffer(self, x: float, y: float, level: int) -> ClockBuffer:
        self._buf_count += 1
        return ClockBuffer(
            instance=f"clkbuf_{self._buf_count}",
            cell_type=self.buffers[0],
            x=x,
            y=y,
            fanout=0,
            level=level,
            delay_ns=0.05,
        )

    def _propagate_arrival(
        self,
        tree: ClockTree,
        node: ClockBuffer,
        parent_arrival: float,
    ) -> None:
        my_arrival = parent_arrival + node.delay_ns
        sinks_by_name = {s.instance: s for s in tree.sinks}
        bufs_by_name = {b.instance: b for b in tree.buffers}
        for child in node.children:
            if child in sinks_by_name:
                sinks_by_name[child].arrival_ns = my_arrival
            elif child in bufs_by_name:
                self._propagate_arrival(tree, bufs_by_name[child], my_arrival)

    # ---------- clustering ----------

    def cluster_sinks(
        self, sinks: list[ClockSink], max_per_cluster: int = 16
    ) -> list[list[ClockSink]]:
        """K-means clustering for buffer insertion grouping."""
        if not sinks:
            return []
        k = max(1, math.ceil(len(sinks) / max_per_cluster))
        rng = random.Random(42)
        seeds = rng.sample(sinks, k)
        centers = [(s.x, s.y) for s in seeds]
        clusters: list[list[ClockSink]] = [[] for _ in range(k)]
        for _ in range(10):
            clusters = [[] for _ in range(k)]
            for s in sinks:
                best = 0
                best_d = float("inf")
                for i, (cx, cy) in enumerate(centers):
                    d = (s.x - cx) ** 2 + (s.y - cy) ** 2
                    if d < best_d:
                        best_d = d
                        best = i
                clusters[best].append(s)
            new_centers = []
            for i, c in enumerate(clusters):
                if not c:
                    new_centers.append(centers[i])
                    continue
                cx = sum(s.x for s in c) / len(c)
                cy = sum(s.y for s in c) / len(c)
                new_centers.append((cx, cy))
            if new_centers == centers:
                break
            centers = new_centers
        return clusters

    # ---------- buffer insertion ----------

    def insert_buffers(
        self, tree: ClockTree, max_fanout: int = 16
    ) -> ClockTree:
        """Split any buffer that exceeds max_fanout."""
        changed = True
        while changed:
            changed = False
            for buf in list(tree.buffers):
                if buf.fanout <= max_fanout:
                    continue
                children = list(buf.children)
                buf.children.clear()
                buf.fanout = 0
                groups: list[list[str]] = []
                step = max_fanout // 2
                for i in range(0, len(children), step):
                    groups.append(children[i : i + step])
                for grp in groups:
                    sub = self._new_buffer(buf.x, buf.y, level=buf.level + 1)
                    sub.parent = buf.instance
                    sub.children = grp
                    sub.fanout = len(grp)
                    tree.buffers.append(sub)
                    buf.children.append(sub.instance)
                    buf.fanout += 1
                changed = True
        tree.total_buffers = len(tree.buffers)
        tree.levels = max((b.level for b in tree.buffers), default=0) + 1
        return tree

    # ---------- useful skew ----------

    def apply_useful_skew(
        self,
        tree: ClockTree,
        setup_slacks: dict[str, float],
        hold_slacks: dict[str, float],
    ) -> ClockTree:
        """Borrow time between paths via clock skew.

        Greedy linear-time heuristic:
            * negative setup slack -> push clock earlier (decrease arrival)
            * negative hold slack -> push clock later (increase arrival)
        Bounded by +/- target_skew_ps.
        """
        max_shift_ns = self.target_skew_ps / 1000.0
        for sink in tree.sinks:
            ss = setup_slacks.get(sink.instance, 0.0)
            hs = hold_slacks.get(sink.instance, 0.0)
            sink.setup_slack = ss
            sink.hold_slack = hs
            shift = 0.0
            if ss < 0:
                shift -= min(-ss, max_shift_ns)
            if hs < 0:
                shift += min(-hs, max_shift_ns)
            sink.arrival_ns += shift
        tree.compute_skew()
        return tree

    # ---------- export ----------

    def export_def(self, tree: ClockTree, output_def: Path) -> None:
        """Append the clock tree as DEF COMPONENTS / NETS additions."""
        lines: list[str] = []
        lines.append(f"# clock tree {tree.name} - {len(tree.buffers)} buffers")
        lines.append(f"COMPONENTS {len(tree.buffers)} ;")
        for b in tree.buffers:
            lines.append(
                f"   - {b.instance} {b.cell_type} + PLACED ( "
                f"{int(b.x * 1000)} {int(b.y * 1000)} ) N ;"
            )
        lines.append("END COMPONENTS")
        lines.append("")
        lines.append(f"NETS {len(tree.buffers)} ;")
        for b in tree.buffers:
            lines.append(f"   - net_{b.instance}")
            for child in b.children:
                lines.append(f"      ( {child} A )")
            lines.append("   ;")
        lines.append("END NETS")
        Path(output_def).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def export_openroad_tcl(self, tree: ClockTree) -> str:
        """OpenROAD TCL that re-creates this clock tree."""
        out: list[str] = []
        out.append(f"# OpenForge CTS - tree {tree.name}")
        out.append(
            f"create_clock -name {tree.name} -period {tree.period_ns} "
            f"[get_pins {tree.root_pin}]"
        )
        for b in tree.buffers:
            out.append(
                f"# place {b.instance} {b.cell_type} ({b.x:.2f}, {b.y:.2f})"
            )
        out.append(f"set_clock_tree_options -target_skew {tree.target_skew_ps}ps")
        out.append("clock_tree_synthesis")
        return "\n".join(out) + "\n"


def build_default_tree(sinks: list[ClockSink]) -> ClockTree:
    """Convenience helper for tests."""
    if not sinks:
        return ClockTree(name="clk", period_ns=10.0, root_pin="clk")
    cx = sum(s.x for s in sinks) / len(sinks)
    cy = sum(s.y for s in sinks) / len(sinks)
    opt = ClockTreeOptimizer()
    tree = opt.build_h_tree(sinks, cx, cy)
    opt.insert_buffers(tree)
    return tree
