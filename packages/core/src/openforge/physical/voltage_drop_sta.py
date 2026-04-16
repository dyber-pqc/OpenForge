"""Voltage-drop aware static timing analysis.

Combines an IR drop map with cell delay sensitivity to produce per-instance
timing derates. Generates OpenSTA TCL with `set_timing_derate -instance`
commands and parses the resulting timing report.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VoltageDerateEntry:
    """Per-instance voltage and derate information."""

    instance: str
    x: float
    y: float
    nominal_vdd: float
    actual_vdd: float
    drop_mv: float
    timing_derate: float  # multiplier for cell delay; >1 = slower

    @property
    def drop_pct(self) -> float:
        if self.nominal_vdd <= 0:
            return 0.0
        return (self.drop_mv / 1000.0) / self.nominal_vdd * 100.0


@dataclass
class VoltageAwareTimingResult:
    """Output of a voltage-drop aware STA run."""

    nominal_wns: float = 0.0
    voltage_aware_wns: float = 0.0
    derated_paths: list[dict] = field(default_factory=list)
    worst_drop_instance: str = ""
    worst_drop_mv: float = 0.0
    instances_affected: int = 0
    derate_entries: list[VoltageDerateEntry] = field(default_factory=list)
    log: str = ""
    success: bool = True
    error: str = ""

    @property
    def degradation_ns(self) -> float:
        return self.nominal_wns - self.voltage_aware_wns


class VoltageDropAwareSta:
    """STA derated per-instance from an IR drop map."""

    def __init__(self, sensitivity_per_volt: float = 0.5) -> None:
        """sensitivity_per_volt: fractional cell-delay change per volt drop.
        Typical CMOS values are roughly 0.5 (50% slower per 1V drop)."""
        self.sensitivity = sensitivity_per_volt
        self._timeout_seconds = 600

    # ---------- derate calculation ----------

    def derate_from_ir_map(
        self,
        ir_map: Any,
        cell_positions: dict[str, tuple[float, float]],
        nominal_vdd: float = 1.8,
    ) -> dict[str, float]:
        """Compute per-cell timing derate factors from an IR drop map.

        Args:
            ir_map: Object with a `sample(x, y) -> drop_mv` method, or a dict
                mapping (x, y) -> drop in mV, or any object exposing
                `voltage_at(x, y)`.
            cell_positions: instance -> (x, y) in microns.
            nominal_vdd: Nominal VDD in volts.
        """
        derates: dict[str, float] = {}
        for instance, (x, y) in cell_positions.items():
            drop_mv = self._sample_drop(ir_map, x, y)
            actual_v = nominal_vdd - drop_mv / 1000.0
            if actual_v <= 0:
                derates[instance] = 2.0
                continue
            # delay scales as (Vdd / (Vdd - Vt))^a; linearised:
            # derate ~ 1 + sensitivity * (drop / Vdd)
            ratio = (drop_mv / 1000.0) / nominal_vdd
            derate = 1.0 + self.sensitivity * ratio
            derates[instance] = max(derate, 1.0)
        return derates

    def _sample_drop(self, ir_map: Any, x: float, y: float) -> float:
        if ir_map is None:
            return 0.0
        if hasattr(ir_map, "sample"):
            try:
                return float(ir_map.sample(x, y))
            except Exception:
                pass
        if hasattr(ir_map, "voltage_at"):
            try:
                v = float(ir_map.voltage_at(x, y))
                return max(0.0, (1.8 - v)) * 1000.0
            except Exception:
                pass
        if isinstance(ir_map, dict):
            # nearest neighbour
            best = 0.0
            best_d = float("inf")
            for (mx, my), val in ir_map.items():
                d = (mx - x) ** 2 + (my - y) ** 2
                if d < best_d:
                    best_d = d
                    best = val
            return float(best)
        return 0.0

    # ---------- STA execution ----------

    def run_voltage_aware_sta(
        self,
        netlist: Path,
        sdc: Path,
        liberty: Path,
        ir_map: Any,
        cell_positions: dict,
        cwd: Path | None = None,
    ) -> VoltageAwareTimingResult:
        """Run OpenSTA twice: nominal then with per-instance derates."""
        cwd = Path(cwd) if cwd else Path.cwd()
        cwd.mkdir(parents=True, exist_ok=True)
        derates = self.derate_from_ir_map(ir_map, cell_positions)
        nominal_wns = self._run_sta(netlist, sdc, liberty, derates={}, cwd=cwd, tag="nominal")
        derated_wns = self._run_sta(netlist, sdc, liberty, derates=derates, cwd=cwd, tag="derated")
        worst_inst = ""
        worst_drop = 0.0
        entries: list[VoltageDerateEntry] = []
        for inst, (x, y) in cell_positions.items():
            drop = self._sample_drop(ir_map, x, y)
            entry = VoltageDerateEntry(
                instance=inst,
                x=x,
                y=y,
                nominal_vdd=1.8,
                actual_vdd=1.8 - drop / 1000.0,
                drop_mv=drop,
                timing_derate=derates.get(inst, 1.0),
            )
            entries.append(entry)
            if drop > worst_drop:
                worst_drop = drop
                worst_inst = inst
        return VoltageAwareTimingResult(
            nominal_wns=nominal_wns,
            voltage_aware_wns=derated_wns,
            worst_drop_instance=worst_inst,
            worst_drop_mv=worst_drop,
            instances_affected=sum(1 for d in derates.values() if d > 1.001),
            derate_entries=entries,
        )

    def _run_sta(
        self,
        netlist: Path,
        sdc: Path,
        liberty: Path,
        derates: dict[str, float],
        cwd: Path,
        tag: str,
    ) -> float:
        tcl = self._build_tcl(netlist, sdc, liberty, derates)
        tcl_path = cwd / f"sta_{tag}.tcl"
        tcl_path.write_text(tcl, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["sta", "-no_init", "-exit", str(tcl_path)],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
            log = proc.stdout + proc.stderr
        except (FileNotFoundError, subprocess.TimeoutExpired):
            log = ""
        return self._parse_wns(log)

    def _build_tcl(
        self,
        netlist: Path,
        sdc: Path,
        liberty: Path,
        derates: dict[str, float],
    ) -> str:
        lines: list[str] = []
        lines.append(f"read_liberty {Path(liberty).as_posix()}")
        lines.append(f"read_verilog {Path(netlist).as_posix()}")
        lines.append("link_design")
        lines.append(f"read_sdc {Path(sdc).as_posix()}")
        for inst, d in derates.items():
            lines.append(self._derate_line(inst, d))
        lines.append("report_checks -path_delay max -format short")
        lines.append("report_wns")
        lines.append("report_tns")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _derate_line(instance: str, derate: float) -> str:
        late = derate
        early = max(2.0 - derate, 0.5)
        return f"set_timing_derate -instance {instance} -late {late:.4f} -early {early:.4f}"

    def generate_sta_with_derates_tcl(self, derates: dict[str, float]) -> str:
        """Standalone TCL generator (no STA invocation)."""
        out = ["# OpenForge voltage-aware STA derates"]
        for inst, d in derates.items():
            out.append(self._derate_line(inst, d))
        return "\n".join(out) + "\n"

    # ---------- log parsing ----------

    _RE_WNS = re.compile(r"wns\s+(-?\d+\.\d+)", re.IGNORECASE)

    def _parse_wns(self, log: str) -> float:
        if not log:
            return 0.0
        m = self._RE_WNS.search(log)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return 0.0
        return 0.0

    # ---------- reporting ----------

    def generate_report(self, result: VoltageAwareTimingResult) -> str:
        lines = []
        lines.append("=" * 72)
        lines.append("OpenForge Voltage-Drop Aware STA Report")
        lines.append("=" * 72)
        lines.append(f"Nominal WNS:           {result.nominal_wns:.4f} ns")
        lines.append(f"Voltage-aware WNS:     {result.voltage_aware_wns:.4f} ns")
        lines.append(f"Degradation:           {result.degradation_ns:.4f} ns")
        lines.append(
            f"Worst drop:            {result.worst_drop_mv:.2f} mV @ {result.worst_drop_instance}"
        )
        lines.append(f"Instances derated:     {result.instances_affected}")
        lines.append("=" * 72)
        return "\n".join(lines)
