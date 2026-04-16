"""Multi-corner static timing analysis across PVT corners."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.opensta import OpenSTAEngine

if TYPE_CHECKING:
    from collections.abc import Sequence
    from os import PathLike

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Corner:
    """A single PVT (Process/Voltage/Temperature) corner."""

    name: str
    liberty_file: str
    temperature: float = 25.0  # Celsius
    voltage: float = 1.8  # Volts
    process: str = "typical"  # "typical", "slow", "fast"


@dataclass(frozen=True, slots=True)
class CornerTimingResult:
    """Timing result for one corner."""

    corner: str
    wns: float = 0.0
    tns: float = 0.0
    fmax_mhz: float = 0.0
    num_violated: int = 0
    raw_output: str = ""


@dataclass(frozen=True, slots=True)
class MultiCornerResult:
    """Aggregate multi-corner timing analysis results."""

    per_corner: list[CornerTimingResult] = field(default_factory=list)
    worst_corner: str = ""
    worst_wns: float = 0.0
    worst_tns: float = 0.0
    worst_fmax_mhz: float = 0.0


# ---------------------------------------------------------------------------
# Pre-defined corners for supported PDKs
# ---------------------------------------------------------------------------


SKY130_CORNERS: list[Corner] = [
    Corner(
        name="tt_025C_1v80",
        liberty_file="sky130_fd_sc_hd__tt_025C_1v80.lib",
        temperature=25.0,
        voltage=1.80,
        process="typical",
    ),
    Corner(
        name="ss_100C_1v60",
        liberty_file="sky130_fd_sc_hd__ss_100C_1v60.lib",
        temperature=100.0,
        voltage=1.60,
        process="slow",
    ),
    Corner(
        name="ff_n40C_1v95",
        liberty_file="sky130_fd_sc_hd__ff_n40C_1v95.lib",
        temperature=-40.0,
        voltage=1.95,
        process="fast",
    ),
]

GF180_CORNERS: list[Corner] = [
    Corner(
        name="tt",
        liberty_file="gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib",
        temperature=25.0,
        voltage=3.30,
        process="typical",
    ),
    Corner(
        name="ss",
        liberty_file="gf180mcu_fd_sc_mcu7t5v0__ss_125C_3v00.lib",
        temperature=125.0,
        voltage=3.00,
        process="slow",
    ),
    Corner(
        name="ff",
        liberty_file="gf180mcu_fd_sc_mcu7t5v0__ff_n40C_3v60.lib",
        temperature=-40.0,
        voltage=3.60,
        process="fast",
    ),
]

PDK_CORNERS: dict[str, list[Corner]] = {
    "sky130": SKY130_CORNERS,
    "gf180": GF180_CORNERS,
}


# ---------------------------------------------------------------------------
# MultiCornerAnalyzer
# ---------------------------------------------------------------------------


class MultiCornerAnalyzer:
    """Run static timing analysis across multiple PVT corners.

    Typical workflow::

        analyzer = MultiCornerAnalyzer()
        result = analyzer.run_multicorner(
            netlist="synth.v",
            sdc="constraints.sdc",
            corners=SKY130_CORNERS,
            top_module="top",
        )
        print(f"Worst corner: {result.worst_corner}, WNS={result.worst_wns:.3f} ns")
    """

    def __init__(self) -> None:
        self._sta = OpenSTAEngine()
        self._last_outputs: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Multi-corner analysis
    # ------------------------------------------------------------------

    def run_multicorner(
        self,
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        corners: Sequence[Corner],
        *,
        top_module: str = "top",
        clock_period_ns: float = 10.0,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: callable | None = None,
    ) -> MultiCornerResult:
        """Run STA for each corner and collect results.

        Parameters
        ----------
        netlist:
            Gate-level Verilog netlist.
        sdc:
            SDC timing constraints file.
        corners:
            List of PVT corners to analyze.
        top_module:
            Top-level module name.
        clock_period_ns:
            Clock period for Fmax calculation.
        cwd:
            Working directory.
        timeout:
            Per-corner timeout in seconds.
        on_output:
            Optional callback ``(corner_name: str, line: str) -> None``
            invoked for each line of tool output.
        """
        per_corner: list[CornerTimingResult] = []
        self._last_outputs.clear()

        for corner in corners:
            if on_output:
                on_output(corner.name, f"=== Running STA for corner: {corner.name} ===")

            corner_result = self._run_single_corner(
                netlist=netlist,
                sdc=sdc,
                corner=corner,
                top_module=top_module,
                clock_period_ns=clock_period_ns,
                cwd=cwd,
                timeout=timeout,
            )

            per_corner.append(corner_result)
            self._last_outputs[corner.name] = corner_result.raw_output

            if on_output:
                on_output(
                    corner.name,
                    f"  WNS={corner_result.wns:.3f} ns, "
                    f"TNS={corner_result.tns:.3f} ns, "
                    f"Fmax={corner_result.fmax_mhz:.1f} MHz",
                )

        # Determine worst corner
        worst_corner = ""
        worst_wns = float("inf")
        worst_tns = 0.0
        worst_fmax = float("inf")

        for cr in per_corner:
            if cr.wns < worst_wns:
                worst_wns = cr.wns
                worst_corner = cr.corner
            if cr.tns < worst_tns:
                worst_tns = cr.tns
            if cr.fmax_mhz < worst_fmax:
                worst_fmax = cr.fmax_mhz

        if not per_corner:
            worst_wns = 0.0
            worst_fmax = 0.0

        return MultiCornerResult(
            per_corner=per_corner,
            worst_corner=worst_corner,
            worst_wns=worst_wns,
            worst_tns=worst_tns,
            worst_fmax_mhz=worst_fmax,
        )

    # ------------------------------------------------------------------
    # Convenience: run with PDK name
    # ------------------------------------------------------------------

    def run_for_pdk(
        self,
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        pdk: str,
        *,
        top_module: str = "top",
        clock_period_ns: float = 10.0,
        lib_dir: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> MultiCornerResult:
        """Run multi-corner STA using pre-defined corners for a PDK.

        Parameters
        ----------
        pdk:
            PDK name ("sky130" or "gf180").
        lib_dir:
            Directory containing the Liberty files. If provided, corner
            liberty_file paths are resolved relative to this directory.
        """
        corners = PDK_CORNERS.get(pdk, [])
        if not corners:
            return MultiCornerResult()

        # Resolve liberty file paths if lib_dir provided
        if lib_dir is not None:
            ld = Path(lib_dir)
            resolved: list[Corner] = []
            for c in corners:
                resolved_lib = str(ld / c.liberty_file)
                resolved.append(
                    Corner(
                        name=c.name,
                        liberty_file=resolved_lib,
                        temperature=c.temperature,
                        voltage=c.voltage,
                        process=c.process,
                    )
                )
            corners = resolved

        return self.run_multicorner(
            netlist=netlist,
            sdc=sdc,
            corners=corners,
            top_module=top_module,
            clock_period_ns=clock_period_ns,
            cwd=cwd,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Single-corner execution
    # ------------------------------------------------------------------

    def _run_single_corner(
        self,
        *,
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        corner: Corner,
        top_module: str,
        clock_period_ns: float,
        cwd: str | PathLike[str] | None,
        timeout: float | None,
    ) -> CornerTimingResult:
        """Run STA for a single corner."""
        import re

        result = self._sta.run_timing(
            liberty=corner.liberty_file,
            verilog_netlist=netlist,
            sdc=sdc,
            top_module=top_module,
            cwd=cwd,
            timeout=timeout,
        )

        text = result.stdout + result.stderr

        # Parse WNS
        wns = 0.0
        if (m := re.search(r"wns\s+([-+]?\d+\.?\d*)", text)) or (
            m := re.search(r"slack\s+\((?:VIOLATED|MET)\)\s+([-+]?\d+\.?\d*)", text)
        ):
            wns = float(m.group(1))

        # Parse TNS
        tns = 0.0
        if m := re.search(r"tns\s+([-+]?\d+\.?\d*)", text):
            tns = float(m.group(1))

        # Calculate Fmax
        fmax = 0.0
        if clock_period_ns > 0:
            achieved_period = clock_period_ns - wns
            if achieved_period > 0:
                fmax = 1000.0 / achieved_period  # MHz

        # Count violations
        num_violated = len(re.findall(r"VIOLATED", text))

        return CornerTimingResult(
            corner=corner.name,
            wns=wns,
            tns=tns,
            fmax_mhz=fmax,
            num_violated=num_violated,
            raw_output=text,
        )
