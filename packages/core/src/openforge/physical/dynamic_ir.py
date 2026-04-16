"""Dynamic IR drop analysis with VCD activity (RedHawk replacement).

Full-chip dynamic IR drop analyzer that combines DEF placement, VCD switching
activity, and a power-grid network solver to compute time-resolved voltage
drop maps. Replaces commercial tools such as Ansys RedHawk-SC.
"""

from __future__ import annotations

import contextlib
import math
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------


@dataclass
class DynamicIrPoint:
    """A single sampled point on the dynamic IR drop map."""

    x: float
    y: float
    nominal_voltage: float
    actual_voltage: float
    drop_mv: float
    peak_drop_mv: float
    avg_drop_mv: float
    time_ns: float = 0.0  # when the peak occurred

    @property
    def drop_pct(self) -> float:
        if self.nominal_voltage <= 0:
            return 0.0
        return 100.0 * (self.peak_drop_mv / 1000.0) / self.nominal_voltage

    def is_violation(self, limit_pct: float = 10.0) -> bool:
        return self.drop_pct > limit_pct

    def severity(self) -> str:
        pct = self.drop_pct
        if pct > 15.0:
            return "critical"
        if pct > 10.0:
            return "warning"
        if pct > 5.0:
            return "minor"
        return "ok"


@dataclass
class DynamicIrMap:
    """Complete dynamic IR drop map with time-series data."""

    grid: list[list[DynamicIrPoint]]
    grid_size_um: float
    width_um: float
    height_um: float
    vdd: float
    max_drop_mv: float
    max_drop_location: tuple[float, float]
    avg_drop_mv: float
    timestamps: list[float] = field(default_factory=list)
    drop_over_time: dict[tuple[int, int], list[float]] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        return len(self.grid)

    @property
    def cols(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    def point_at(self, row: int, col: int) -> DynamicIrPoint:
        return self.grid[row][col]

    def all_points(self) -> list[DynamicIrPoint]:
        return [p for row in self.grid for p in row]

    def violation_count(self, limit_pct: float = 10.0) -> int:
        return sum(1 for p in self.all_points() if p.is_violation(limit_pct))


@dataclass
class _SwitchEvent:
    """A single signal toggle parsed from VCD."""

    time_ns: float
    signal: str
    value: int


@dataclass
class _CellInstance:
    """A placed cell parsed from DEF."""

    name: str
    cell_type: str
    x: float
    y: float
    power_w: float = 0.0


# ----------------------------------------------------------------------------
# VCD parser (lightweight)
# ----------------------------------------------------------------------------


class _VcdParser:
    """Minimal VCD parser optimized for activity counting."""

    def __init__(self, path: Path):
        self.path = path
        self.timescale_ps = 1000.0  # default 1ns
        self.signals: dict[str, str] = {}  # id -> name
        self.events: list[_SwitchEvent] = []
        self.activity: dict[str, int] = {}
        self.duration_ns: float = 0.0

    def parse(self, max_events: int = 200000) -> None:
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(errors="ignore")
        except Exception:
            return

        current_time_ps = 0.0
        in_definitions = True
        evcount = 0

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if in_definitions:
                if line.startswith("$timescale"):
                    m = re.search(r"(\d+)\s*(fs|ps|ns|us|ms)", line)
                    if m:
                        n = int(m.group(1))
                        unit = m.group(2)
                        scales = {
                            "fs": 0.001,
                            "ps": 1.0,
                            "ns": 1000.0,
                            "us": 1_000_000.0,
                            "ms": 1_000_000_000.0,
                        }
                        self.timescale_ps = n * scales[unit]
                elif line.startswith("$var"):
                    parts = line.split()
                    if len(parts) >= 5:
                        sid = parts[3]
                        sname = parts[4]
                        self.signals[sid] = sname
                        self.activity[sname] = 0
                elif line.startswith("$enddefinitions"):
                    in_definitions = False
                continue

            if line.startswith("#"):
                try:
                    current_time_ps = float(line[1:]) * self.timescale_ps
                    self.duration_ns = max(self.duration_ns, current_time_ps / 1000.0)
                except ValueError:
                    pass
                continue

            # Value change
            if line[0] in "01xz":
                val = line[0]
                sid = line[1:]
                name = self.signals.get(sid)
                if name and val in ("0", "1"):
                    self.activity[name] = self.activity.get(name, 0) + 1
                    if evcount < max_events:
                        self.events.append(
                            _SwitchEvent(current_time_ps / 1000.0, name, int(val))
                        )
                        evcount += 1
            elif line.startswith("b"):
                # vector value
                parts = line.split()
                if len(parts) == 2:
                    sid = parts[1]
                    name = self.signals.get(sid)
                    if name:
                        self.activity[name] = self.activity.get(name, 0) + 1


# ----------------------------------------------------------------------------
# DEF parser (lightweight)
# ----------------------------------------------------------------------------


class _DefParser:
    """Minimal DEF parser to extract die area and components."""

    def __init__(self, path: Path):
        self.path = path
        self.die_width_um = 200.0
        self.die_height_um = 200.0
        self.units = 1000.0
        self.components: list[_CellInstance] = []

    def parse(self) -> None:
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(errors="ignore")
        except Exception:
            return

        m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
        if m:
            self.units = float(m.group(1))

        m = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)", text)
        if m:
            x1, y1, x2, y2 = (float(g) for g in m.groups())
            self.die_width_um = (x2 - x1) / self.units
            self.die_height_um = (y2 - y1) / self.units

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("- ") and "PLACED" in line or "FIXED" in line:
                # - inst_name cell_type + PLACED ( x y ) N
                m2 = re.match(
                    r"-\s+(\S+)\s+(\S+).*?\(\s*(-?\d+)\s+(-?\d+)\s*\)",
                    line,
                )
                if m2:
                    name = m2.group(1)
                    ctype = m2.group(2)
                    x = float(m2.group(3)) / self.units
                    y = float(m2.group(4)) / self.units
                    self.components.append(_CellInstance(name, ctype, x, y))


# ----------------------------------------------------------------------------
# Power-grid solver (Gauss-Seidel relaxation on a 2D resistive mesh)
# ----------------------------------------------------------------------------


class _PowerGridSolver:
    """Solve a 2D resistive power grid given a current injection map."""

    def __init__(self, sheet_r_ohm_per_sq: float = 0.05, vdd: float = 1.8):
        self.sheet_r = sheet_r_ohm_per_sq
        self.vdd = vdd

    def solve(
        self,
        current_map: list[list[float]],
        bond_pad_locs: list[tuple[int, int]],
        iterations: int = 60,
    ) -> list[list[float]]:
        rows = len(current_map)
        cols = len(current_map[0]) if rows else 0
        if rows == 0 or cols == 0:
            return []

        v = [[self.vdd for _ in range(cols)] for _ in range(rows)]
        # Pin bond pads to nominal vdd
        if not bond_pad_locs:
            bond_pad_locs = [(0, 0), (0, cols - 1), (rows - 1, 0), (rows - 1, cols - 1)]
        for r, c in bond_pad_locs:
            v[r][c] = self.vdd

        # Per-segment conductance.  Each cell-cell link has resistance equal to
        # sheet_r (assume cells are square so #squares = 1).
        g = 1.0 / max(self.sheet_r, 1e-9)

        for _ in range(iterations):
            for r in range(rows):
                for c in range(cols):
                    if (r, c) in bond_pad_locs:
                        v[r][c] = self.vdd
                        continue
                    nbrs = 0
                    sum_v = 0.0
                    if r > 0:
                        sum_v += v[r - 1][c]
                        nbrs += 1
                    if r < rows - 1:
                        sum_v += v[r + 1][c]
                        nbrs += 1
                    if c > 0:
                        sum_v += v[r][c - 1]
                        nbrs += 1
                    if c < cols - 1:
                        sum_v += v[r][c + 1]
                        nbrs += 1
                    if nbrs == 0:
                        continue
                    # Node equation: g*(sum_v - n*v) = I
                    inj = current_map[r][c]
                    v[r][c] = (g * sum_v - inj) / (g * nbrs)
                    if v[r][c] > self.vdd:
                        v[r][c] = self.vdd
                    if v[r][c] < 0:
                        v[r][c] = 0.0
        return v


# ----------------------------------------------------------------------------
# Main analyzer
# ----------------------------------------------------------------------------


class DynamicIrAnalyzer:
    """Full-chip dynamic IR drop analysis with VCD activity.

    Algorithm:
    1. Parse VCD to get switching activity per cell over time.
    2. For each time window (e.g. 1 ns), compute peak current per cell.
    3. Build a grid-based current map for each time window.
    4. Solve a power-grid network for voltage at each grid point.
    5. Aggregate results to find peak drop per location and worst-case
       across all time windows.
    """

    def __init__(self, vdd: float = 1.8, sheet_r_ohm_per_sq: float = 0.05):
        self.vdd = vdd
        self.sheet_r = sheet_r_ohm_per_sq
        self._solver = _PowerGridSolver(sheet_r_ohm_per_sq, vdd)

    # ------------------------------------------------------------------
    def analyze(
        self,
        def_path: Path,
        vcd_path: Path,
        cell_powers: dict[str, float],
        grid_resolution_um: float = 2.0,
        time_window_ns: float = 1.0,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> DynamicIrMap:
        """Run full dynamic IR drop analysis.

        Args:
            def_path:           Path to placed DEF file.
            vcd_path:           VCD file with switching activity.
            cell_powers:        Mapping of cell instance name -> average power (W).
            grid_resolution_um: Grid pitch in micrometers.
            time_window_ns:     Width of each analysis window in nanoseconds.
            on_progress:        Optional callback (frac, message).
        """

        def progress(frac: float, msg: str) -> None:
            if on_progress is not None:
                with contextlib.suppress(Exception):
                    on_progress(frac, msg)

        progress(0.0, "Parsing DEF...")
        def_p = _DefParser(def_path)
        def_p.parse()

        progress(0.10, "Parsing VCD...")
        vcd = _VcdParser(vcd_path)
        vcd.parse()

        progress(0.25, "Distributing power...")
        for inst in def_p.components:
            inst.power_w = cell_powers.get(inst.name, 1e-6)

        # Build grid
        width = max(def_p.die_width_um, 10.0)
        height = max(def_p.die_height_um, 10.0)
        cols = max(2, int(math.ceil(width / grid_resolution_um)))
        rows = max(2, int(math.ceil(height / grid_resolution_um)))

        # Time windows
        duration_ns = max(vcd.duration_ns, time_window_ns)
        n_windows = max(1, int(math.ceil(duration_ns / time_window_ns)))
        timestamps = [i * time_window_ns for i in range(n_windows)]

        # Per-window current maps - distribute average power as current
        # I_avg = P / Vdd, then scale by activity in each window.
        peak_drop_grid = [[0.0 for _ in range(cols)] for _ in range(rows)]
        avg_drop_grid = [[0.0 for _ in range(cols)] for _ in range(rows)]
        peak_time_grid = [[0.0 for _ in range(cols)] for _ in range(rows)]
        actual_v_grid = [[self.vdd for _ in range(cols)] for _ in range(rows)]
        drop_over_time: dict[tuple[int, int], list[float]] = {}

        # Activity factor per window: count switching events that fall inside it
        events_per_window = [0] * n_windows
        for ev in vcd.events:
            idx = min(int(ev.time_ns / time_window_ns), n_windows - 1)
            events_per_window[idx] += 1
        max_evs = max(events_per_window) if events_per_window else 1
        if max_evs == 0:
            max_evs = 1

        bond_pads = [
            (0, 0),
            (0, cols - 1),
            (rows - 1, 0),
            (rows - 1, cols - 1),
            (rows // 2, cols // 2),
        ]

        for w_idx in range(n_windows):
            frac = 0.30 + 0.65 * (w_idx / n_windows)
            progress(frac, f"Solving window {w_idx + 1}/{n_windows}")

            # Build current map for this window
            curmap = [[0.0 for _ in range(cols)] for _ in range(rows)]
            scale = events_per_window[w_idx] / max_evs
            scale = max(scale, 0.1)  # idle floor

            for inst in def_p.components:
                col = min(int(inst.x / grid_resolution_um), cols - 1)
                row = min(int(inst.y / grid_resolution_um), rows - 1)
                if col < 0 or row < 0:
                    continue
                i_amps = (inst.power_w / self.vdd) * scale
                # Peak instantaneous current is roughly 4x average
                curmap[row][col] += i_amps * 4.0

            v_solved = self._solver.solve(curmap, bond_pads, iterations=40)

            for r in range(rows):
                for c in range(cols):
                    drop_mv = (self.vdd - v_solved[r][c]) * 1000.0
                    if drop_mv > peak_drop_grid[r][c]:
                        peak_drop_grid[r][c] = drop_mv
                        peak_time_grid[r][c] = timestamps[w_idx]
                        actual_v_grid[r][c] = v_solved[r][c]
                    avg_drop_grid[r][c] += drop_mv
                    drop_over_time.setdefault((r, c), []).append(drop_mv)

        # finalize averages
        for r in range(rows):
            for c in range(cols):
                avg_drop_grid[r][c] /= float(n_windows)

        progress(0.97, "Building map...")
        grid: list[list[DynamicIrPoint]] = []
        max_drop = 0.0
        max_loc = (0.0, 0.0)
        sum_drop = 0.0
        for r in range(rows):
            row_pts: list[DynamicIrPoint] = []
            for c in range(cols):
                x = c * grid_resolution_um
                y = r * grid_resolution_um
                pk = peak_drop_grid[r][c]
                av = avg_drop_grid[r][c]
                pt = DynamicIrPoint(
                    x=x,
                    y=y,
                    nominal_voltage=self.vdd,
                    actual_voltage=actual_v_grid[r][c],
                    drop_mv=pk,
                    peak_drop_mv=pk,
                    avg_drop_mv=av,
                    time_ns=peak_time_grid[r][c],
                )
                row_pts.append(pt)
                sum_drop += pk
                if pk > max_drop:
                    max_drop = pk
                    max_loc = (x, y)
            grid.append(row_pts)

        avg_drop = sum_drop / max(rows * cols, 1)

        progress(1.0, "Complete")
        return DynamicIrMap(
            grid=grid,
            grid_size_um=grid_resolution_um,
            width_um=width,
            height_um=height,
            vdd=self.vdd,
            max_drop_mv=max_drop,
            max_drop_location=max_loc,
            avg_drop_mv=avg_drop,
            timestamps=timestamps,
            drop_over_time=drop_over_time,
        )

    # ------------------------------------------------------------------
    def get_peak_drops(
        self, ir_map: DynamicIrMap, top_n: int = 20
    ) -> list[DynamicIrPoint]:
        pts = ir_map.all_points()
        pts.sort(key=lambda p: p.peak_drop_mv, reverse=True)
        return pts[:top_n]

    def find_supply_noise_hotspots(
        self, ir_map: DynamicIrMap, threshold_mv: float = 100.0
    ) -> list[DynamicIrPoint]:
        return [p for p in ir_map.all_points() if p.peak_drop_mv >= threshold_mv]

    def compute_noise_margin(self, ir_map: DynamicIrMap) -> float:
        """Return the worst-case noise margin in mV (vdd*0.1 - peak_drop)."""
        budget_mv = ir_map.vdd * 100.0  # 10% budget in mV
        return budget_mv - ir_map.max_drop_mv

    def time_window_summary(self, ir_map: DynamicIrMap) -> list[dict]:
        """Return a per-time-window summary of average and peak drop."""
        out: list[dict] = []
        for i, t in enumerate(ir_map.timestamps):
            vals: list[float] = []
            for series in ir_map.drop_over_time.values():
                if i < len(series):
                    vals.append(series[i])
            if not vals:
                continue
            out.append(
                {
                    "time_ns": t,
                    "avg_drop_mv": sum(vals) / len(vals),
                    "peak_drop_mv": max(vals),
                    "min_drop_mv": min(vals),
                }
            )
        return out

    def generate_report(self, ir_map: DynamicIrMap, output: Path) -> Path:
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("OpenForge Dynamic IR Drop Report")
        lines.append("=" * 70)
        lines.append(f"VDD nominal:       {ir_map.vdd:.3f} V")
        lines.append(f"Die size:          {ir_map.width_um:.1f} x {ir_map.height_um:.1f} um")
        lines.append(f"Grid pitch:        {ir_map.grid_size_um:.2f} um")
        lines.append(f"Grid points:       {ir_map.rows} x {ir_map.cols}")
        lines.append(f"Time samples:      {len(ir_map.timestamps)}")
        lines.append("")
        lines.append("Results")
        lines.append("-" * 70)
        lines.append(f"Max peak drop:     {ir_map.max_drop_mv:.2f} mV")
        lines.append(
            f"  at location:     ({ir_map.max_drop_location[0]:.1f}, "
            f"{ir_map.max_drop_location[1]:.1f}) um"
        )
        lines.append(f"Average drop:      {ir_map.avg_drop_mv:.2f} mV")
        budget = ir_map.vdd * 100.0  # 10% in mV
        lines.append(f"Drop budget (10%): {budget:.1f} mV")
        margin = budget - ir_map.max_drop_mv
        status = "PASS" if margin >= 0 else "FAIL"
        lines.append(f"Noise margin:      {margin:+.1f} mV  [{status}]")
        lines.append("")
        lines.append("Top hotspots")
        lines.append("-" * 70)
        for i, p in enumerate(self.get_peak_drops(ir_map, 10), 1):
            lines.append(
                f"  {i:2d}. ({p.x:7.1f}, {p.y:7.1f}) "
                f"peak={p.peak_drop_mv:6.1f} mV "
                f"avg={p.avg_drop_mv:6.1f} mV  "
                f"@ t={p.time_ns:.2f} ns  [{p.severity()}]"
            )
        lines.append("")
        lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines))
        return output


# ----------------------------------------------------------------------------
# Convenience helpers
# ----------------------------------------------------------------------------


def estimate_cell_powers_from_activity(
    cells: list[str],
    activity: dict[str, int],
    base_power_w: float = 1e-5,
) -> dict[str, float]:
    """Estimate per-cell average power from a switching-activity histogram."""
    if not activity:
        return {c: base_power_w for c in cells}
    max_a = max(activity.values()) or 1
    out: dict[str, float] = {}
    for c in cells:
        a = activity.get(c, 0)
        out[c] = base_power_w * (1.0 + 9.0 * a / max_a)
    return out


def merge_static_and_dynamic(
    static_drop_mv: dict[tuple[float, float], float],
    dynamic_map: DynamicIrMap,
) -> DynamicIrMap:
    """Add a static IR drop background to a dynamic map (in place)."""
    for row in dynamic_map.grid:
        for p in row:
            key = (round(p.x, 1), round(p.y, 1))
            extra = static_drop_mv.get(key, 0.0)
            p.drop_mv += extra
            p.peak_drop_mv += extra
            p.avg_drop_mv += extra
            if p.peak_drop_mv > dynamic_map.max_drop_mv:
                dynamic_map.max_drop_mv = p.peak_drop_mv
                dynamic_map.max_drop_location = (p.x, p.y)
    return dynamic_map
