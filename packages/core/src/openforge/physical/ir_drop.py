"""IR drop estimation across the power grid.

This is a simplified estimator that:
  1. Parses cell positions from a DEF file.
  2. Builds a 2D current density grid by depositing each cell's current
     (I = P / VDD) into its grid bucket.
  3. Computes a voltage drop at each grid node by integrating current along
     the (Manhattan) path to the nearest power pin, scaled by the sheet
     resistance of the metal stack.
  4. Returns an IrDropMap suitable for visualization in the desktop UI.

For a real signoff IR drop tool you would solve a sparse linear system on the
full RC mesh of the power grid, but this estimator is fast, dependency-free,
and gives qualitatively correct heatmaps for the OpenForge UI.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class IrDropPoint:
    """A single IR drop sample point."""

    x: float  # microns
    y: float
    voltage: float  # actual voltage at this point (V)
    drop_mv: float  # millivolts dropped from VDD

    def __str__(self) -> str:  # pragma: no cover
        return f"({self.x:.1f},{self.y:.1f}) drop={self.drop_mv:.1f}mV"


@dataclass
class IrDropMap:
    """A 2D map of voltage drops across the die."""

    grid: list[list[float]]  # 2D grid of voltage drops in mV [row][col]
    grid_size_um: float  # grid cell size in microns
    width_um: float  # die width
    height_um: float  # die height
    vdd: float  # nominal supply voltage
    max_drop_mv: float = 0.0
    avg_drop_mv: float = 0.0
    hotspots: list[IrDropPoint] = field(default_factory=list)

    @property
    def num_rows(self) -> int:
        return len(self.grid)

    @property
    def num_cols(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    def get_drop_at(self, x: float, y: float) -> float:
        """Return the voltage drop in mV at die coordinate (x, y)."""
        if self.grid_size_um <= 0 or not self.grid:
            return 0.0
        col = int(x / self.grid_size_um)
        row = int(y / self.grid_size_um)
        if row < 0 or row >= self.num_rows:
            return 0.0
        if col < 0 or col >= self.num_cols:
            return 0.0
        return self.grid[row][col]

    def get_voltage_at(self, x: float, y: float) -> float:
        return self.vdd - (self.get_drop_at(x, y) / 1000.0)

    def percent_above(self, threshold_mv: float) -> float:
        if not self.grid:
            return 0.0
        total = self.num_rows * self.num_cols
        bad = sum(1 for row in self.grid for v in row if v > threshold_mv)
        return 100.0 * bad / total if total else 0.0

    def stats(self) -> dict:
        return {
            "max_drop_mv": self.max_drop_mv,
            "avg_drop_mv": self.avg_drop_mv,
            "min_voltage_v": self.vdd - self.max_drop_mv / 1000.0,
            "num_hotspots": len(self.hotspots),
            "grid_size_um": self.grid_size_um,
            "width_um": self.width_um,
            "height_um": self.height_um,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
        }


# ---------------------------------------------------------------------------
# DEF parsing helpers
# ---------------------------------------------------------------------------


@dataclass
class _DefCell:
    name: str
    macro: str
    x_um: float
    y_um: float


@dataclass
class _DefInfo:
    width_um: float
    height_um: float
    units_per_um: float
    cells: list[_DefCell] = field(default_factory=list)
    power_pins: list[tuple[float, float]] = field(default_factory=list)


def _parse_def(def_path: Path) -> _DefInfo:
    """Very small DEF parser - just enough to extract die area and components."""
    text = Path(def_path).read_text(encoding="utf-8", errors="replace")

    units_m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
    units_per_um = float(units_m.group(1)) if units_m else 1000.0

    die_m = re.search(
        r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
        text,
    )
    if die_m:
        x1 = float(die_m.group(1)) / units_per_um
        y1 = float(die_m.group(2)) / units_per_um
        x2 = float(die_m.group(3)) / units_per_um
        y2 = float(die_m.group(4)) / units_per_um
        width = x2 - x1
        height = y2 - y1
    else:
        width = 100.0
        height = 100.0

    info = _DefInfo(width_um=width, height_um=height, units_per_um=units_per_um)

    # COMPONENTS section
    comp_section = re.search(
        r"COMPONENTS\s+\d+\s*;(.*?)END\s+COMPONENTS",
        text,
        re.DOTALL,
    )
    if comp_section:
        block = comp_section.group(1)
        # "- name macro ... + PLACED ( x y ) orient ;"
        for m in re.finditer(
            r"-\s*(\S+)\s+(\S+)[^;]*?\+\s*(?:PLACED|FIXED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
            block,
        ):
            name = m.group(1)
            macro = m.group(2)
            x = float(m.group(3)) / units_per_um
            y = float(m.group(4)) / units_per_um
            info.cells.append(_DefCell(name=name, macro=macro, x_um=x, y_um=y))

    # PINS section - look for VDD/VSS power pins
    pins_section = re.search(
        r"PINS\s+\d+\s*;(.*?)END\s+PINS",
        text,
        re.DOTALL,
    )
    if pins_section:
        for m in re.finditer(
            r"-\s*(\S+)\s+\+\s*NET\s+(\S+).*?\+\s*(?:PLACED|FIXED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
            pins_section.group(1),
            re.DOTALL,
        ):
            net = m.group(2).upper()
            if "VDD" in net or "VCC" in net or "POWER" in net:
                x = float(m.group(3)) / units_per_um
                y = float(m.group(4)) / units_per_um
                info.power_pins.append((x, y))

    if not info.power_pins:
        # Default: corners of the die
        info.power_pins = [
            (0.0, 0.0),
            (width, 0.0),
            (0.0, height),
            (width, height),
            (width / 2.0, height / 2.0),
        ]

    return info


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------


class IrDropEstimator:
    """Estimates IR drop across the power grid.

    Algorithm (simplified):
        - Parse DEF for cell positions and power pin locations.
        - Build a 2D grid at the requested resolution.
        - For each cell, deposit current = power / vdd into its bucket.
        - For each grid cell, compute drop as integral of current along the
          Manhattan path to the nearest power pin, multiplied by sheet R.
        - Identify hotspots above a threshold.
    """

    def __init__(
        self,
        vdd: float = 1.8,
        sheet_resistance_ohm_per_sq: float = 0.1,
    ) -> None:
        self.vdd = vdd
        self.sheet_r = sheet_resistance_ohm_per_sq

    # -- main entry --------------------------------------------------------

    def estimate(
        self,
        def_path: Path,
        cell_powers: dict[str, float],
        grid_resolution_um: float = 1.0,
    ) -> IrDropMap:
        """Estimate IR drop across the entire die."""
        info = _parse_def(Path(def_path))
        return self.estimate_from_info(info, cell_powers, grid_resolution_um)

    def estimate_from_info(
        self,
        info: _DefInfo,
        cell_powers: dict[str, float],
        grid_resolution_um: float,
    ) -> IrDropMap:
        if grid_resolution_um <= 0:
            raise ValueError("grid_resolution_um must be > 0")

        num_cols = max(1, int(math.ceil(info.width_um / grid_resolution_um)))
        num_rows = max(1, int(math.ceil(info.height_um / grid_resolution_um)))

        # Step 1: deposit current per cell into the grid
        current_grid = [[0.0 for _ in range(num_cols)] for _ in range(num_rows)]
        default_power = 1e-6  # 1 uW default per cell when not specified
        for cell in info.cells:
            power = cell_powers.get(cell.name, default_power)
            current_a = power / self.vdd if self.vdd > 0 else 0.0
            col = min(num_cols - 1, max(0, int(cell.x_um / grid_resolution_um)))
            row = min(num_rows - 1, max(0, int(cell.y_um / grid_resolution_um)))
            current_grid[row][col] += current_a

        # Step 2: compute drop per grid node based on distance to nearest pin.
        # Drop ~= I_total_within_radius * sheet_R * distance_in_squares.
        drop_grid = [[0.0 for _ in range(num_cols)] for _ in range(num_rows)]
        max_drop = 0.0
        total_drop = 0.0
        count = 0

        # Precompute total current for normalization
        total_current = sum(sum(row) for row in current_grid)

        for r in range(num_rows):
            cy = (r + 0.5) * grid_resolution_um
            for c in range(num_cols):
                cx = (c + 0.5) * grid_resolution_um
                # Distance to nearest power pin
                d_min = min(
                    abs(cx - px) + abs(cy - py)
                    for (px, py) in info.power_pins
                )
                squares = max(1.0, d_min / max(grid_resolution_um, 0.1))
                # Local current contribution: this cell + neighbors weighted by distance
                local_current = current_grid[r][c]
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < num_rows and 0 <= cc < num_cols:
                            local_current += current_grid[rr][cc] * 0.25
                # Add a global average term so even empty regions show some drop
                global_term = 0.0
                if total_current > 0 and (num_rows * num_cols) > 0:
                    global_term = total_current / (num_rows * num_cols) * 0.1

                drop_v = (local_current + global_term) * self.sheet_r * squares
                drop_mv = drop_v * 1000.0
                drop_grid[r][c] = drop_mv
                if drop_mv > max_drop:
                    max_drop = drop_mv
                total_drop += drop_mv
                count += 1

        avg_drop = total_drop / count if count else 0.0

        ir_map = IrDropMap(
            grid=drop_grid,
            grid_size_um=grid_resolution_um,
            width_um=info.width_um,
            height_um=info.height_um,
            vdd=self.vdd,
            max_drop_mv=max_drop,
            avg_drop_mv=avg_drop,
        )
        ir_map.hotspots = self.find_hotspots(ir_map, threshold_mv=max(50.0, max_drop * 0.8))
        return ir_map

    # -- hotspots ----------------------------------------------------------

    def find_hotspots(
        self,
        ir_map: IrDropMap,
        threshold_mv: float = 50.0,
    ) -> list[IrDropPoint]:
        """Find regions where drop exceeds threshold."""
        hotspots: list[IrDropPoint] = []
        if not ir_map.grid:
            return hotspots
        gs = ir_map.grid_size_um
        for r, row in enumerate(ir_map.grid):
            for c, drop_mv in enumerate(row):
                if drop_mv >= threshold_mv:
                    hotspots.append(
                        IrDropPoint(
                            x=(c + 0.5) * gs,
                            y=(r + 0.5) * gs,
                            voltage=ir_map.vdd - drop_mv / 1000.0,
                            drop_mv=drop_mv,
                        )
                    )
        # Sort worst first
        hotspots.sort(key=lambda p: -p.drop_mv)
        return hotspots[:200]


def colorize_drop(drop_mv: float, max_drop_mv: float) -> tuple[int, int, int]:
    """Map an IR drop value to an (r, g, b) color (blue->green->yellow->red)."""
    if max_drop_mv <= 0:
        return (0, 0, 255)
    t = min(1.0, max(0.0, drop_mv / max_drop_mv))
    if t < 0.25:
        # blue -> cyan
        f = t / 0.25
        return (0, int(255 * f), 255)
    elif t < 0.5:
        # cyan -> green
        f = (t - 0.25) / 0.25
        return (0, 255, int(255 * (1 - f)))
    elif t < 0.75:
        # green -> yellow
        f = (t - 0.5) / 0.25
        return (int(255 * f), 255, 0)
    else:
        # yellow -> red
        f = (t - 0.75) / 0.25
        return (255, int(255 * (1 - f)), 0)


# ---------------------------------------------------------------------------
# Export / reporting helpers
# ---------------------------------------------------------------------------


def export_csv(ir_map: IrDropMap, path: Path) -> None:
    """Write the IR drop grid to a CSV file (one row per grid row)."""
    path = Path(path)
    lines: list[str] = []
    lines.append("# IR drop map (mV)")
    lines.append(f"# vdd={ir_map.vdd} grid_size_um={ir_map.grid_size_um}")
    lines.append(f"# width_um={ir_map.width_um} height_um={ir_map.height_um}")
    lines.append(f"# max_drop_mv={ir_map.max_drop_mv:.3f}")
    lines.append(f"# avg_drop_mv={ir_map.avg_drop_mv:.3f}")
    for row in ir_map.grid:
        lines.append(",".join(f"{v:.3f}" for v in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_hotspot_report(ir_map: IrDropMap, path: Path) -> None:
    """Write a textual report of all hotspots to a file."""
    path = Path(path)
    lines: list[str] = []
    lines.append("OpenForge IR Drop Hotspot Report")
    lines.append("=" * 60)
    lines.append(f"VDD nominal:    {ir_map.vdd:.4f} V")
    lines.append(f"Die area:       {ir_map.width_um:.1f} x {ir_map.height_um:.1f} um")
    lines.append(f"Grid:           {ir_map.num_cols} x {ir_map.num_rows}")
    lines.append(f"Resolution:     {ir_map.grid_size_um:.2f} um")
    lines.append(f"Max drop:       {ir_map.max_drop_mv:.3f} mV")
    lines.append(f"Avg drop:       {ir_map.avg_drop_mv:.3f} mV")
    lines.append(f"Min voltage:    {ir_map.vdd - ir_map.max_drop_mv/1000:.4f} V")
    lines.append(f"Hotspot count:  {len(ir_map.hotspots)}")
    lines.append("")
    lines.append(f"{'#':>4}  {'X (um)':>10}  {'Y (um)':>10}  "
                 f"{'Drop (mV)':>10}  {'V (V)':>10}")
    lines.append("-" * 60)
    for i, hp in enumerate(ir_map.hotspots, 1):
        lines.append(
            f"{i:>4}  {hp.x:>10.2f}  {hp.y:>10.2f}  "
            f"{hp.drop_mv:>10.3f}  {hp.voltage:>10.5f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compute_voltage_grid(ir_map: IrDropMap) -> list[list[float]]:
    """Convert the drop grid to an absolute voltage grid (V)."""
    return [
        [ir_map.vdd - drop / 1000.0 for drop in row]
        for row in ir_map.grid
    ]


def merge_drop_maps(maps: list[IrDropMap]) -> IrDropMap | None:
    """Worst-case merge of several IrDropMaps (must share dimensions)."""
    if not maps:
        return None
    base = maps[0]
    rows, cols = base.num_rows, base.num_cols
    out = [[0.0 for _ in range(cols)] for _ in range(rows)]
    for m in maps:
        if m.num_rows != rows or m.num_cols != cols:
            raise ValueError("All maps must have identical dimensions to merge")
        for r in range(rows):
            for c in range(cols):
                if m.grid[r][c] > out[r][c]:
                    out[r][c] = m.grid[r][c]

    max_drop = max(v for row in out for v in row) if out else 0.0
    total = sum(v for row in out for v in row)
    count = rows * cols
    avg = total / count if count else 0.0

    merged = IrDropMap(
        grid=out,
        grid_size_um=base.grid_size_um,
        width_um=base.width_um,
        height_um=base.height_um,
        vdd=base.vdd,
        max_drop_mv=max_drop,
        avg_drop_mv=avg,
    )
    estimator = IrDropEstimator(vdd=base.vdd)
    merged.hotspots = estimator.find_hotspots(merged, threshold_mv=max(50.0, max_drop * 0.8))
    return merged


# ---------------------------------------------------------------------------
# Dynamic IR drop analyser (time-stepped PDN solve)
# ---------------------------------------------------------------------------


try:
    import numpy as _np
except ImportError:  # pragma: no cover - numpy is a hard dep but guard anyway
    _np = None  # type: ignore[assignment]


class DynamicIrSample:
    """Voltage grid sample at a single time point."""

    def __init__(
        self,
        time_ns: float,
        grid: object,
        max_drop_v: float,
        average_drop_v: float,
    ) -> None:
        self.time_ns = float(time_ns)
        self.grid = grid
        self.max_drop_v = float(max_drop_v)
        self.average_drop_v = float(average_drop_v)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DynamicIrSample(t={self.time_ns:.3f}ns, "
            f"max={self.max_drop_v*1000:.1f}mV)"
        )


class DynamicIrResult:
    def __init__(
        self,
        samples: list[DynamicIrSample],
        peak_drop_v: float,
        peak_drop_time_ns: float,
        average_drop_v: float,
        violations: list[dict] | None = None,
    ) -> None:
        self.samples = list(samples)
        self.peak_drop_v = float(peak_drop_v)
        self.peak_drop_time_ns = float(peak_drop_time_ns)
        self.average_drop_v = float(average_drop_v)
        self.violations = list(violations or [])

    def stats(self) -> dict:
        return {
            "num_samples": len(self.samples),
            "peak_drop_mv": self.peak_drop_v * 1000.0,
            "peak_drop_time_ns": self.peak_drop_time_ns,
            "average_drop_mv": self.average_drop_v * 1000.0,
            "num_violations": len(self.violations),
        }


class DynamicIrAnalyzer:
    """Time-stepped PDN solver.

    Without a VCD the analyser assumes a uniform activity factor per cell
    (α=0.2, f_clk=1 GHz).  When a VCD is supplied, per-cell toggle rates
    are scaled by each cell's observed activity across the simulation.
    """

    def __init__(
        self,
        def_path: str | Path,
        lef_path: str | Path,
        vcd_path: Path | None = None,
        vdd: float = 1.8,
        grid_size_um: float = 10.0,
    ) -> None:
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)
        self.vcd_path = Path(vcd_path) if vcd_path else None
        self.vdd = float(vdd)
        self.grid_size_um = float(grid_size_um)
        self._design = None
        self._lib = None

    # ------------------------------------------------------------------ util

    def _load(self) -> tuple[object, object]:
        if self._design is None:
            from openforge.format.def_parser import parse_def

            self._design = parse_def(self.def_path)
        if self._lib is None:
            from openforge.format.lef_parser import parse_lef

            self._lib = parse_lef(self.lef_path)
        return self._design, self._lib

    def extract_pdn(self) -> dict:
        """Return a coarse summary of the power grid from SPECIALNETS."""
        design, _ = self._load()
        vdd_nets = [
            n for n in design.special_nets.values() if n.use in ("POWER", "SIGNAL")
        ]
        gnd_nets = [n for n in design.special_nets.values() if n.use == "GROUND"]
        stripes = sum(len(n.routes) for n in (*vdd_nets, *gnd_nets))
        return {
            "vdd_nets": [n.name for n in vdd_nets],
            "gnd_nets": [n.name for n in gnd_nets],
            "stripe_count": stripes,
        }

    # ------------------------------------------------------------------ api

    def compute_per_cell_currents(
        self, vcd_path: Path | None = None
    ) -> dict[str, list[tuple[float, float]]]:
        """Per-cell (t, I) waveform list.  Without a VCD, returns a single
        point with the static average current."""
        design, lib = self._load()
        out: dict[str, list[tuple[float, float]]] = {}
        vcd_file = vcd_path or self.vcd_path
        alpha = 0.2
        f_clk_hz = 1.0e9
        c_avg_ff = 4.0  # average switched capacitance per cell (fF)
        i_static = alpha * c_avg_ff * 1e-15 * self.vdd * f_clk_hz  # A
        if vcd_file is None:
            for comp in design.components.values():
                if not comp.is_placed:
                    continue
                out[comp.name] = [(0.0, i_static)]
            return out

        # VCD-driven: compute per-signal toggle rate and scale i_static.
        try:
            from openforge.format.waveform import Waveform

            wf = Waveform.parse_vcd(vcd_file)
        except Exception:
            for comp in design.components.values():
                out[comp.name] = [(0.0, i_static)]
            return out
        dur_ns = max(1.0, wf.end_time * wf.timescale_ps / 1000.0)
        tog_by_name: dict[str, int] = {}
        for key, trans in wf.data.items():
            tog_by_name[key.split(".")[-1]] = len(trans)
        for comp in design.components.values():
            if not comp.is_placed:
                continue
            togs = 0
            for k, v in tog_by_name.items():
                if k and k in comp.name:
                    togs = max(togs, v)
            scale = max(0.1, togs / max(1.0, dur_ns))
            out[comp.name] = [(0.0, i_static * scale)]
        return out

    def solve_dynamic(
        self,
        timestep_ns: float = 0.1,
        duration_ns: float = 10.0,
        violation_drop_mv: float = 80.0,
    ) -> DynamicIrResult:
        if _np is None:
            raise RuntimeError("numpy is required for DynamicIrAnalyzer")
        design, lib = self._load()
        nx = max(1, int(design.width_um / self.grid_size_um))
        ny = max(1, int(design.height_um / self.grid_size_um))
        base_current = _np.zeros((ny, nx), dtype=_np.float32)

        currents = self.compute_per_cell_currents()
        for comp_name, samples in currents.items():
            comp = design.components.get(comp_name)
            if comp is None:
                continue
            cx = design.to_um(comp.x)
            cy = design.to_um(comp.y)
            i_col = min(nx - 1, max(0, int(cx / self.grid_size_um)))
            j_row = min(ny - 1, max(0, int(cy / self.grid_size_um)))
            base_current[j_row, i_col] += samples[0][1] if samples else 0.0

        # Sheet resistance (Ω/square) for sky130 met1 stack is ≈ 0.125,
        # combined with a stripe pitch of ~7 µm we get an effective
        # resistance per grid cell of ~1 mΩ.
        r_cell = 0.001

        # Define an activity envelope: rising edge around t=1ns then decay
        samples: list[DynamicIrSample] = []
        steps = max(1, int(duration_ns / timestep_ns))
        peak = 0.0
        peak_t = 0.0
        total = 0.0
        for k in range(steps):
            t = k * timestep_ns
            env = _np.exp(-((t - 1.0) ** 2) / 2.0) + 0.5
            i_grid = base_current * float(env)
            # Each cell drops I*R locally, plus propagation toward die edges:
            drop = i_grid * r_cell
            # Smoothing kernel models current spreading through the mesh
            smooth = drop.copy()
            smooth[1:, :] += 0.25 * drop[:-1, :]
            smooth[:-1, :] += 0.25 * drop[1:, :]
            smooth[:, 1:] += 0.25 * drop[:, :-1]
            smooth[:, :-1] += 0.25 * drop[:, 1:]
            max_drop = float(smooth.max())
            avg_drop = float(smooth.mean())
            total += avg_drop
            if max_drop > peak:
                peak = max_drop
                peak_t = t
            samples.append(
                DynamicIrSample(
                    time_ns=t,
                    grid=smooth,
                    max_drop_v=max_drop,
                    average_drop_v=avg_drop,
                )
            )

        violations: list[dict] = []
        if peak * 1000.0 > violation_drop_mv:
            violations.append(
                {
                    "time_ns": peak_t,
                    "drop_mv": peak * 1000.0,
                    "limit_mv": violation_drop_mv,
                }
            )
        return DynamicIrResult(
            samples=samples,
            peak_drop_v=peak,
            peak_drop_time_ns=peak_t,
            average_drop_v=total / max(1, len(samples)),
            violations=violations,
        )

    def average_mode(self) -> dict:
        res = self.solve_dynamic(timestep_ns=0.5, duration_ns=5.0)
        return {
            "average_drop_mv": res.average_drop_v * 1000.0,
            "peak_drop_mv": res.peak_drop_v * 1000.0,
        }

    def peak_mode(self) -> dict:
        res = self.solve_dynamic(timestep_ns=0.05, duration_ns=5.0)
        return {
            "peak_drop_mv": res.peak_drop_v * 1000.0,
            "peak_time_ns": res.peak_drop_time_ns,
        }


__all__ = [
    "IrDropPoint",
    "IrDropMap",
    "IrDropEstimator",
    "colorize_drop",
    "export_csv",
    "export_hotspot_report",
    "compute_voltage_grid",
    "merge_drop_maps",
    "DynamicIrSample",
    "DynamicIrResult",
    "DynamicIrAnalyzer",
]
