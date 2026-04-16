"""Chip thermal analysis (Icepak/Totem replacement).

Steady-state 2-D thermal solver based on a thermal-resistance network.
Builds a grid over the die area, injects power as heat sources, and relaxes
to a steady-state temperature distribution.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------


@dataclass
class ThermalNode:
    """A node in the thermal network."""

    x: float
    y: float
    temperature_c: float
    power_w: float = 0.0

    def is_hotspot(self, threshold_c: float = 85.0) -> bool:
        return self.temperature_c >= threshold_c


@dataclass
class ThermalMap:
    """Steady-state temperature distribution over the die area."""

    grid: list[list[float]]  # 2D temperature in Celsius
    grid_size_um: float
    width_um: float
    height_um: float
    ambient_c: float
    max_temp_c: float
    min_temp_c: float
    avg_temp_c: float
    hotspots: list[ThermalNode] = field(default_factory=list)
    iterations_run: int = 0
    converged: bool = False

    @property
    def rows(self) -> int:
        return len(self.grid)

    @property
    def cols(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    @property
    def gradient_c(self) -> float:
        return self.max_temp_c - self.min_temp_c

    def temperature_at(self, x_um: float, y_um: float) -> float:
        c = max(0, min(int(x_um / self.grid_size_um), self.cols - 1))
        r = max(0, min(int(y_um / self.grid_size_um), self.rows - 1))
        return self.grid[r][c]


# ----------------------------------------------------------------------------
# Thermal analyzer
# ----------------------------------------------------------------------------


class ThermalAnalyzer:
    """Steady-state thermal analysis using a thermal-resistance network.

    Algorithm:
    1. Build a 2-D thermal network from the layout.
    2. Each grid cell is a thermal node connected to neighbors via thermal
       resistance.  Each cell also has a path to ambient through the
       package thermal resistance.
    3. Power dissipation at each cell becomes a heat source.
    4. Iterate using Gauss-Seidel relaxation until the maximum delta is
       under a tolerance.
    """

    def __init__(
        self,
        ambient_c: float = 25.0,
        package_thermal_r: float = 10.0,  # K/W (junction to ambient, package)
        si_thermal_k: float = 150.0,  # W/(m*K)
    ):
        self.ambient = ambient_c
        self.package_r = package_thermal_r
        self.si_k = si_thermal_k

    # ------------------------------------------------------------------
    def analyze(
        self,
        die_width_um: float,
        die_height_um: float,
        cell_powers: dict[tuple[float, float], float],
        grid_resolution_um: float = 5.0,
        max_iterations: int = 200,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> ThermalMap:
        """Compute steady-state temperature distribution."""

        def progress(f: float, m: str) -> None:
            if on_progress:
                try:
                    on_progress(f, m)
                except Exception:
                    pass

        progress(0.0, "Building thermal grid...")
        cols = max(2, int(math.ceil(die_width_um / grid_resolution_um)))
        rows = max(2, int(math.ceil(die_height_um / grid_resolution_um)))

        # Convert grid pitch to meters for conductance calc
        d_m = grid_resolution_um * 1e-6
        # Thickness of bulk Si active layer assumed = 300 um
        t_m = 300e-6

        # Lateral thermal conductance between cells:
        #   G_lat = k * area / length  ; area = d * t ; length = d
        g_lat = self.si_k * (d_m * t_m) / d_m  # = k * t

        # Vertical conductance per cell to ambient through package
        # The package R is total chip-to-ambient.  We split it across cells.
        n_cells = rows * cols
        g_pkg_per_cell = (1.0 / max(self.package_r, 0.001)) / n_cells
        # In addition allow heat spreading to the immediate substrate -
        # add a small floor so isolated cells still cool.
        g_pkg_per_cell = max(g_pkg_per_cell, 1e-4)

        # Power injection grid (W per cell)
        power_grid = [[0.0 for _ in range(cols)] for _ in range(rows)]
        for (x, y), p in cell_powers.items():
            c = max(0, min(int(x / grid_resolution_um), cols - 1))
            r = max(0, min(int(y / grid_resolution_um), rows - 1))
            power_grid[r][c] += p

        # Initialize temperature grid at ambient
        T = [[self.ambient for _ in range(cols)] for _ in range(rows)]

        progress(0.05, "Solving heat equation...")
        tol = 0.05  # Celsius
        converged = False
        iters_run = 0
        for it in range(max_iterations):
            iters_run = it + 1
            max_delta = 0.0
            if it % max(1, max_iterations // 20) == 0:
                progress(0.05 + 0.9 * (it / max_iterations), f"Iter {it}/{max_iterations}")

            for r in range(rows):
                for c in range(cols):
                    # Sum lateral conductances times neighbor temperatures
                    sum_gT = 0.0
                    sum_g = 0.0
                    if r > 0:
                        sum_gT += g_lat * T[r - 1][c]
                        sum_g += g_lat
                    if r < rows - 1:
                        sum_gT += g_lat * T[r + 1][c]
                        sum_g += g_lat
                    if c > 0:
                        sum_gT += g_lat * T[r][c - 1]
                        sum_g += g_lat
                    if c < cols - 1:
                        sum_gT += g_lat * T[r][c + 1]
                        sum_g += g_lat

                    # Path to ambient
                    sum_gT += g_pkg_per_cell * self.ambient
                    sum_g += g_pkg_per_cell

                    # Heat source
                    p = power_grid[r][c]

                    if sum_g <= 0:
                        continue
                    new_T = (sum_gT + p) / sum_g
                    d = abs(new_T - T[r][c])
                    if d > max_delta:
                        max_delta = d
                    T[r][c] = new_T

            if max_delta < tol:
                converged = True
                break

        progress(0.97, "Building thermal map...")

        max_t = -1e9
        min_t = 1e9
        sum_t = 0.0
        for r in range(rows):
            for c in range(cols):
                v = T[r][c]
                if v > max_t:
                    max_t = v
                if v < min_t:
                    min_t = v
                sum_t += v
        avg_t = sum_t / (rows * cols)

        hotspots: list[ThermalNode] = []
        for r in range(rows):
            for c in range(cols):
                if T[r][c] >= 85.0:
                    hotspots.append(
                        ThermalNode(
                            x=c * grid_resolution_um,
                            y=r * grid_resolution_um,
                            temperature_c=T[r][c],
                            power_w=power_grid[r][c],
                        )
                    )
        hotspots.sort(key=lambda n: n.temperature_c, reverse=True)

        progress(1.0, "Thermal analysis complete")
        return ThermalMap(
            grid=T,
            grid_size_um=grid_resolution_um,
            width_um=die_width_um,
            height_um=die_height_um,
            ambient_c=self.ambient,
            max_temp_c=max_t,
            min_temp_c=min_t,
            avg_temp_c=avg_t,
            hotspots=hotspots,
            iterations_run=iters_run,
            converged=converged,
        )

    # ------------------------------------------------------------------
    def find_hotspots(
        self, thermal_map: ThermalMap, threshold_c: float = 85.0
    ) -> list[ThermalNode]:
        out: list[ThermalNode] = []
        for r in range(thermal_map.rows):
            for c in range(thermal_map.cols):
                t = thermal_map.grid[r][c]
                if t >= threshold_c:
                    out.append(
                        ThermalNode(
                            x=c * thermal_map.grid_size_um,
                            y=r * thermal_map.grid_size_um,
                            temperature_c=t,
                        )
                    )
        out.sort(key=lambda n: n.temperature_c, reverse=True)
        return out

    # ------------------------------------------------------------------
    def compute_thermal_gradient(self, thermal_map: ThermalMap) -> float:
        return thermal_map.max_temp_c - thermal_map.min_temp_c

    # ------------------------------------------------------------------
    def estimate_lifetime(self, thermal_map: ThermalMap) -> float:
        """Arrhenius equation for component lifetime estimation (years).

        Uses an activation energy of ~0.7 eV (typical for transistor
        wear-out) and a reference of 10 years at 85 C.
        """
        Ea = 0.7
        k = 8.617e-5  # eV/K
        ref_T = 85.0 + 273.15
        ref_life_years = 10.0
        T = thermal_map.max_temp_c + 273.15
        if T <= 0:
            return ref_life_years
        af = math.exp((Ea / k) * (1.0 / T - 1.0 / ref_T))
        years = ref_life_years * af
        return max(min(years, 1e6), 0.01)

    # ------------------------------------------------------------------
    def compute_thermal_resistance(
        self, thermal_map: ThermalMap, total_power_w: float
    ) -> float:
        """Theta-JA in K/W from steady-state results."""
        if total_power_w <= 0:
            return 0.0
        return (thermal_map.max_temp_c - thermal_map.ambient_c) / total_power_w

    # ------------------------------------------------------------------
    def slice_along_x(self, thermal_map: ThermalMap, y_um: float) -> list[float]:
        r = max(0, min(int(y_um / thermal_map.grid_size_um), thermal_map.rows - 1))
        return list(thermal_map.grid[r])

    def slice_along_y(self, thermal_map: ThermalMap, x_um: float) -> list[float]:
        c = max(0, min(int(x_um / thermal_map.grid_size_um), thermal_map.cols - 1))
        return [thermal_map.grid[r][c] for r in range(thermal_map.rows)]

    # ------------------------------------------------------------------
    def generate_thermal_report(self, thermal_map: ThermalMap, output: Path) -> Path:
        total_power = sum(
            n.power_w for n in thermal_map.hotspots
        )
        theta_ja = self.compute_thermal_resistance(thermal_map, max(total_power, 0.001))
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("OpenForge Thermal Analysis Report")
        lines.append("=" * 70)
        lines.append(
            f"Die area:        {thermal_map.width_um:.1f} x "
            f"{thermal_map.height_um:.1f} um"
        )
        lines.append(f"Grid pitch:      {thermal_map.grid_size_um:.2f} um")
        lines.append(f"Grid points:     {thermal_map.rows} x {thermal_map.cols}")
        lines.append(f"Iterations:      {thermal_map.iterations_run}")
        lines.append(f"Converged:       {thermal_map.converged}")
        lines.append("")
        lines.append("Temperatures")
        lines.append("-" * 70)
        lines.append(f"Ambient:         {thermal_map.ambient_c:.1f} C")
        lines.append(f"Max:             {thermal_map.max_temp_c:.2f} C")
        lines.append(f"Min:             {thermal_map.min_temp_c:.2f} C")
        lines.append(f"Avg:             {thermal_map.avg_temp_c:.2f} C")
        lines.append(f"Gradient:        {thermal_map.gradient_c:.2f} C")
        lines.append(f"Theta-JA:        {theta_ja:.2f} K/W")
        lines.append(f"Hotspots (>85C): {len(thermal_map.hotspots)}")
        lines.append(f"Est. lifetime:   {self.estimate_lifetime(thermal_map):.2f} years")
        lines.append("")
        if thermal_map.hotspots:
            lines.append("Top 10 hotspots")
            lines.append("-" * 70)
            for i, h in enumerate(thermal_map.hotspots[:10], 1):
                lines.append(
                    f"  {i:2d}. ({h.x:7.1f}, {h.y:7.1f}) {h.temperature_c:6.2f} C "
                    f" P={h.power_w*1e3:6.2f} mW"
                )
        lines.append("")
        lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines))
        return output


# ----------------------------------------------------------------------------
# Convenience helpers
# ----------------------------------------------------------------------------


def uniform_power_grid(
    die_width_um: float,
    die_height_um: float,
    total_power_w: float,
    grid_step_um: float = 10.0,
) -> dict[tuple[float, float], float]:
    """Generate a uniform power-density map for testing."""
    cols = max(1, int(die_width_um / grid_step_um))
    rows = max(1, int(die_height_um / grid_step_um))
    p_per_cell = total_power_w / (rows * cols)
    out: dict[tuple[float, float], float] = {}
    for r in range(rows):
        for c in range(cols):
            out[(c * grid_step_um, r * grid_step_um)] = p_per_cell
    return out


def gaussian_hotspot(
    cx: float,
    cy: float,
    sigma_um: float,
    peak_power_w: float,
    die_width_um: float,
    die_height_um: float,
    grid_step_um: float = 5.0,
) -> dict[tuple[float, float], float]:
    """Synthesize a Gaussian-shaped power hotspot for testing."""
    out: dict[tuple[float, float], float] = {}
    rows = int(die_height_um / grid_step_um)
    cols = int(die_width_um / grid_step_um)
    for r in range(rows):
        for c in range(cols):
            x = c * grid_step_um
            y = r * grid_step_um
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            p = peak_power_w * math.exp(-d2 / (2.0 * sigma_um * sigma_um))
            if p > 1e-9:
                out[(x, y)] = p
    return out
