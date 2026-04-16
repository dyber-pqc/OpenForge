"""Physical-aware synthesis - synthesis driven by floorplan constraints.

Iterative synthesis that incorporates rough placement and wire-delay
estimates back into the timing constraints. Approximates the
DC-Topographical / Genus iSpatial flow.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class PhysicalConstraint:
    """A constraint that biases synthesis toward physical-friendly results."""

    constraint_type: str  # placement_region, timing_path, max_fanout
    target: str  # signal or cell name
    value: Any
    location: tuple[float, float] | None = None

    def to_sdc(self) -> str:
        if self.constraint_type == "max_fanout":
            return f"set_max_fanout {self.value} [get_pins {self.target}]"
        if self.constraint_type == "timing_path":
            return f"set_max_delay {self.value} -to [get_pins {self.target}]"
        if self.constraint_type == "placement_region":
            x, y = self.location or (0.0, 0.0)
            return f"# region: {self.target} -> ({x:.2f}, {y:.2f})"
        return f"# unknown constraint: {self.constraint_type}"


@dataclass
class PhysicalSynthResult:
    """Output of a physical-aware synthesis run."""

    netlist: Path
    placement_hints: dict[str, tuple[float, float]] = field(default_factory=dict)
    timing_estimates: dict = field(default_factory=dict)
    iterations: int = 0
    converged: bool = False
    wns_history: list[float] = field(default_factory=list)
    area_history: list[float] = field(default_factory=list)
    sdc_constraints: list[str] = field(default_factory=list)


class PhysicalAwareSynthesizer:
    """Iterative synthesis with floorplan/placement awareness.

    Flow:
        1. Initial Yosys synth with given strategy.
        2. Run a quick floorplan estimator to obtain rough cell positions.
        3. Estimate per-net wire delays from positions.
        4. Convert wire delays into SDC max_delay constraints.
        5. Re-synth with the new constraints. Repeat until converged.
    """

    R_PER_UM = 0.1  # ohms per micron of metal
    C_PER_UM = 0.2e-15  # farads per micron of metal
    DRIVE_R_DEFAULT = 1000.0  # ohms
    LOAD_C_DEFAULT = 5e-15  # farads

    def __init__(self, max_iterations: int = 3) -> None:
        self.max_iterations = max_iterations
        self.convergence_threshold_ns = 0.05

    # ---------- main entry ----------

    def synthesize_with_floorplan(
        self,
        sources: list[Path],
        top_module: str,
        floorplan: dict,
        target_freq_mhz: float,
        liberty: Path,
        on_progress: Optional[Callable[[str, int], None]] = None,
    ) -> PhysicalSynthResult:
        """Run iterative physical-aware synthesis."""
        result = PhysicalSynthResult(netlist=Path("synth_phys.v"))
        period_ns = 1000.0 / max(target_freq_mhz, 1.0)
        constraints: list[str] = [
            f"create_clock -period {period_ns:.3f} [get_ports clk]",
        ]

        for it in range(self.max_iterations):
            if on_progress:
                on_progress(f"iteration {it + 1}", it + 1)

            netlist_json = self._run_yosys(
                sources, top_module, liberty, constraints, iteration=it
            )
            placements = self._estimate_placement(netlist_json, floorplan)
            wire_delays = self.estimate_wire_delays(netlist_json, placements)
            sdc_extra = self.generate_physical_constraints_sdc(wire_delays)

            wns = self._estimate_wns(wire_delays, period_ns)
            area = self._estimate_area(netlist_json)
            result.wns_history.append(wns)
            result.area_history.append(area)

            constraints = constraints[:1] + sdc_extra.splitlines()
            result.placement_hints = placements
            result.timing_estimates = {
                "wns": wns,
                "tns": min(wns * 5, 0.0),
                "period_ns": period_ns,
            }
            result.iterations = it + 1
            result.netlist = netlist_json.with_suffix(".v")
            result.sdc_constraints = constraints

            if it > 0 and abs(
                result.wns_history[-1] - result.wns_history[-2]
            ) < self.convergence_threshold_ns:
                result.converged = True
                break

        return result

    # ---------- physical estimation ----------

    def estimate_wire_delays(
        self,
        netlist_json: Path,
        cell_locations: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        """For each net, estimate Elmore RC delay from driver/load positions.

        Uses a simple half-perimeter wirelength model and treats each net
        as a single lumped RC.
        """
        delays: dict[str, float] = {}
        nets = self._extract_nets(netlist_json)
        for net_name, conns in nets.items():
            if not conns:
                continue
            xs = [cell_locations.get(c, (0.0, 0.0))[0] for c in conns]
            ys = [cell_locations.get(c, (0.0, 0.0))[1] for c in conns]
            if not xs or not ys:
                delays[net_name] = 0.0
                continue
            hpwl = (max(xs) - min(xs)) + (max(ys) - min(ys))  # microns
            r_wire = hpwl * self.R_PER_UM
            c_wire = hpwl * self.C_PER_UM
            c_load = self.LOAD_C_DEFAULT * max(len(conns) - 1, 1)
            # Elmore: t = R_drv * (C_wire + C_load) + R_wire * (C_wire/2 + C_load)
            t = self.DRIVE_R_DEFAULT * (c_wire + c_load) + r_wire * (
                c_wire / 2.0 + c_load
            )
            delays[net_name] = t * 1e9  # to ns
        return delays

    def generate_physical_constraints_sdc(
        self, wire_delays: dict[str, float]
    ) -> str:
        """Convert estimated wire delays into SDC max_delay constraints."""
        out: list[str] = ["# physical-aware constraints"]
        # Threshold the worst nets for explicit constraints
        items = sorted(wire_delays.items(), key=lambda kv: -kv[1])[:50]
        for net, delay in items:
            if delay <= 0.0:
                continue
            out.append(
                f"set_max_delay {delay * 1.1:.4f} -through [get_nets {net}]"
            )
        out.append("set_max_fanout 16 [current_design]")
        out.append("set_max_transition 0.5 [current_design]")
        return "\n".join(out) + "\n"

    # ---------- internal helpers ----------

    def _run_yosys(
        self,
        sources: list[Path],
        top: str,
        liberty: Path,
        constraints: list[str],
        iteration: int,
    ) -> Path:
        """Stub Yosys invocation that produces a JSON netlist path.

        We avoid the actual subprocess call here so the function is unit
        testable; production callers can subclass and override.
        """
        out_dir = Path(".") / f"phys_synth_iter{iteration}"
        out_dir.mkdir(parents=True, exist_ok=True)
        netlist_json = out_dir / f"{top}.json"
        if not netlist_json.exists():
            netlist_json.write_text(
                json.dumps(
                    {
                        "modules": {
                            top: {
                                "cells": {},
                                "netnames": {},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
        # also stage the SDC
        (out_dir / "constraints.sdc").write_text(
            "\n".join(constraints), encoding="utf-8"
        )
        return netlist_json

    def _estimate_placement(
        self, netlist_json: Path, floorplan: dict
    ) -> dict[str, tuple[float, float]]:
        """Cheap force-directed-style placement on a regular grid."""
        try:
            data = json.loads(netlist_json.read_text(encoding="utf-8"))
        except Exception:
            return {}
        die_w = floorplan.get("die_width", 100.0)
        die_h = floorplan.get("die_height", 100.0)
        cells: list[str] = []
        for mod in data.get("modules", {}).values():
            cells.extend(mod.get("cells", {}).keys())
        if not cells:
            return {}
        n = len(cells)
        side = max(int(math.sqrt(n)) + 1, 1)
        step_x = die_w / side
        step_y = die_h / side
        placements: dict[str, tuple[float, float]] = {}
        for i, name in enumerate(cells):
            r, c = divmod(i, side)
            placements[name] = (c * step_x + step_x / 2, r * step_y + step_y / 2)
        return placements

    def _extract_nets(self, netlist_json: Path) -> dict[str, list[str]]:
        try:
            data = json.loads(netlist_json.read_text(encoding="utf-8"))
        except Exception:
            return {}
        nets: dict[str, list[str]] = {}
        for mod in data.get("modules", {}).values():
            for cell_name, cell in mod.get("cells", {}).items():
                for _pin, conn in cell.get("connections", {}).items():
                    if isinstance(conn, list):
                        for bit in conn:
                            net_name = f"net_{bit}" if isinstance(bit, int) else str(bit)
                            nets.setdefault(net_name, []).append(cell_name)
        return nets

    def _estimate_wns(
        self, wire_delays: dict[str, float], period_ns: float
    ) -> float:
        if not wire_delays:
            return 0.0
        worst = max(wire_delays.values())
        # crude: cell delay budget = 0.6*period, wire budget = 0.4*period
        slack = 0.4 * period_ns - worst
        return slack

    def _estimate_area(self, netlist_json: Path) -> float:
        try:
            data = json.loads(netlist_json.read_text(encoding="utf-8"))
        except Exception:
            return 0.0
        cells = 0
        for mod in data.get("modules", {}).values():
            cells += len(mod.get("cells", {}))
        return float(cells) * 4.5  # rough um^2 per cell


def synthesize(
    sources: list[Path], top: str, freq_mhz: float, liberty: Path
) -> PhysicalSynthResult:
    """Convenience wrapper used by the CLI."""
    syn = PhysicalAwareSynthesizer()
    return syn.synthesize_with_floorplan(
        sources=sources,
        top_module=top,
        floorplan={"die_width": 200.0, "die_height": 200.0},
        target_freq_mhz=freq_mhz,
        liberty=liberty,
    )
