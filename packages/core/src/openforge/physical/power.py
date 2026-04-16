"""Power analysis integration wrapping OpenSTA with rich result parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.opensta import OpenSTAEngine

if TYPE_CHECKING:
    from os import PathLike

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PowerResult:
    """Aggregate power analysis results."""

    total_mw: float = 0.0
    dynamic_mw: float = 0.0
    leakage_mw: float = 0.0
    internal_mw: float = 0.0
    switching_mw: float = 0.0
    by_hierarchy: dict[str, float] = field(default_factory=dict)
    by_cell_type: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_power_report(text: str) -> PowerResult:
    """Parse OpenSTA ``report_power`` output into a structured result.

    OpenSTA power report typically contains lines like::

        Total Power  =  1.234e-03 W  (100.0%)
        Dynamic Power =  1.000e-03 W  (81.0%)
        Leakage Power =  2.340e-04 W  (19.0%)
        Internal Power =  6.000e-04 W  (48.6%)
        Switching Power = 4.000e-04 W  (32.4%)
    """
    total = 0.0
    dynamic = 0.0
    leakage = 0.0
    internal = 0.0
    switching = 0.0
    by_hierarchy: dict[str, float] = {}
    by_cell_type: dict[str, float] = {}

    # Generic power value pattern: name = value unit
    def _extract_watts(pattern: str, txt: str) -> float:
        m = re.search(pattern, txt, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                pass
        return 0.0

    # Try multiple formats OpenSTA may produce
    # Format 1: "Total Power = <val> W" or "Total <val> W"
    total = _extract_watts(r"total\s+(?:power\s*[=:])?\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]", text)
    dynamic = _extract_watts(r"dynamic\s+(?:power\s*[=:])?\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]", text)
    leakage = _extract_watts(r"leakage\s+(?:power\s*[=:])?\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]", text)
    internal = _extract_watts(r"internal\s+(?:power\s*[=:])?\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]", text)
    switching = _extract_watts(r"switching\s+(?:power\s*[=:])?\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]", text)

    # Convert W to mW
    to_mw = 1000.0
    total_mw = total * to_mw
    dynamic_mw = dynamic * to_mw
    leakage_mw = leakage * to_mw
    internal_mw = internal * to_mw
    switching_mw = switching * to_mw

    # Fallback: if total is zero but dynamic + leakage are non-zero
    if total_mw == 0.0 and (dynamic_mw > 0.0 or leakage_mw > 0.0):
        total_mw = dynamic_mw + leakage_mw

    # Parse per-hierarchy power (OpenSTA may list "Instance: <name> <power>")
    for m in re.finditer(
        r"Instance\s+(\S+)\s+.*?([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]",
        text,
        re.IGNORECASE,
    ):
        hier_name = m.group(1)
        hier_power = float(m.group(2)) * to_mw
        by_hierarchy[hier_name] = hier_power

    # Parse per-cell-type power (OpenSTA may list cell types with power)
    for m in re.finditer(
        r"Cell\s+Type\s+(\S+)\s+.*?([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*[wW]",
        text,
        re.IGNORECASE,
    ):
        cell_type = m.group(1)
        cell_power = float(m.group(2)) * to_mw
        by_cell_type[cell_type] = cell_power

    return PowerResult(
        total_mw=total_mw,
        dynamic_mw=dynamic_mw,
        leakage_mw=leakage_mw,
        internal_mw=internal_mw,
        switching_mw=switching_mw,
        by_hierarchy=by_hierarchy,
        by_cell_type=by_cell_type,
    )


# ---------------------------------------------------------------------------
# PowerAnalyzer
# ---------------------------------------------------------------------------


class PowerAnalyzer:
    """Power analysis wrapper using OpenSTA with structured result parsing.

    Uses :class:`OpenSTAEngine` to run power analysis and parses the
    ``report_power`` output into :class:`PowerResult` objects.

    Typical workflow::

        analyzer = PowerAnalyzer()
        result = analyzer.run_power_analysis(
            liberty="sky130.lib",
            netlist="synth.v",
            sdc="constraints.sdc",
        )
        print(f"Total power: {result.total_mw:.3f} mW")
    """

    def __init__(self) -> None:
        self._sta = OpenSTAEngine()
        self._last_output: str = ""

    # ------------------------------------------------------------------
    # Full analysis
    # ------------------------------------------------------------------

    def run_power_analysis(
        self,
        liberty: str | PathLike[str],
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        *,
        activity_file: str | PathLike[str] | None = None,
        top_module: str = "top",
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> PowerResult:
        """Run power analysis via OpenSTA.

        Parameters
        ----------
        liberty:
            Liberty timing library (``.lib``) file.
        netlist:
            Gate-level Verilog netlist.
        sdc:
            SDC timing constraints file.
        activity_file:
            Optional switching activity file (SAIF or VCD).
        top_module:
            Top-level module name.
        cwd:
            Working directory.
        timeout:
            Process timeout in seconds.
        """
        tcl_lines: list[str] = [
            f"read_liberty {liberty}",
            f"read_verilog {netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
        ]

        # Load switching activity if provided
        if activity_file is not None:
            act_path = str(activity_file)
            if act_path.lower().endswith(".saif"):
                tcl_lines.append(f"read_power_activities -scope {top_module} {activity_file}")
            elif act_path.lower().endswith(".vcd"):
                tcl_lines.append(f"read_power_activities -scope {top_module} -vcd {activity_file}")
            else:
                # Try generic activity read
                tcl_lines.append(f"read_power_activities -scope {top_module} {activity_file}")

        tcl_lines.extend([
            "report_power",
            "report_power -hierarchy",
            "report_power -cell_type",
            "exit",
        ])

        tcl_content = "\n".join(tcl_lines) + "\n"

        work_dir = Path(cwd) if cwd else Path.cwd()
        tcl_path = work_dir / ".opensta_power.tcl"
        tcl_path.write_text(tcl_content)

        try:
            result = self._sta.run(
                ["-exit", str(tcl_path)],
                cwd=cwd,
                timeout=timeout,
            )
        finally:
            tcl_path.unlink(missing_ok=True)

        self._last_output = result.stdout + result.stderr
        return self.parse_power_report(self._last_output)

    # ------------------------------------------------------------------
    # Estimation without tools
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_power_from_synthesis(
        gate_count: int,
        frequency_mhz: float,
        vdd: float = 1.8,
        *,
        activity_factor: float = 0.1,
        capacitance_per_gate_ff: float = 15.0,
    ) -> float:
        """Quick power estimation without running EDA tools.

        Uses the CMOS dynamic power formula: P = alpha * C * V^2 * f

        Parameters
        ----------
        gate_count:
            Number of logic gates in the design.
        frequency_mhz:
            Clock frequency in MHz.
        vdd:
            Supply voltage in volts.
        activity_factor:
            Average switching activity (alpha), typically 0.05-0.2.
        capacitance_per_gate_ff:
            Average capacitance per gate in femtofarads.

        Returns
        -------
        float
            Estimated total power in milliwatts.
        """
        # Convert units: fF to F, MHz to Hz
        total_capacitance_f = gate_count * capacitance_per_gate_ff * 1e-15
        frequency_hz = frequency_mhz * 1e6

        # P = alpha * C * V^2 * f (Watts)
        power_w = activity_factor * total_capacitance_f * (vdd ** 2) * frequency_hz

        # Add ~20% for leakage as a rough estimate
        leakage_factor = 1.2

        return power_w * leakage_factor * 1000.0  # convert to mW

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_power_report(self, sta_output: str) -> PowerResult:
        """Parse OpenSTA power output into a structured :class:`PowerResult`."""
        return _parse_power_report(sta_output)

    @property
    def last_output(self) -> str:
        """Raw output from the last analysis run."""
        return self._last_output
