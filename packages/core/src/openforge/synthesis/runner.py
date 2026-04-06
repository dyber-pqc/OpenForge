"""High-level synthesis runner -- orchestrates Yosys for RTL-to-gate flows."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from openforge.config.loader import load_config
from openforge.config.schema import OpenForgeConfig
from openforge.engine.yosys import YosysEngine
from openforge.pdk.manager import PDKManager
from openforge.synthesis.optimization import (
    OptimizationPass,
    generate_abc_script,
    generate_synth_script,
)


# ---------------------------------------------------------------------------
# PDK-specific library names
# ---------------------------------------------------------------------------

_PDK_LIBERTY: dict[str, str] = {
    "sky130": "sky130_fd_sc_hd__tt_025C_1v80.lib",
    "gf180mcu": "gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80.lib",
}

_PDK_CORNER_PATTERNS: dict[str, dict[str, str]] = {
    "sky130": {
        "tt": "sky130_fd_sc_hd__tt_025C_1v80",
        "ss": "sky130_fd_sc_hd__ss_100C_1v60",
        "ff": "sky130_fd_sc_hd__ff_n40C_1v95",
    },
    "gf180mcu": {
        "tt": "gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80",
        "ss": "gf180mcu_fd_sc_mcu7t5v0__ss_125C_1v62",
        "ff": "gf180mcu_fd_sc_mcu7t5v0__ff_n40C_1v98",
    },
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Outcome of a synthesis run."""

    success: bool
    gate_count: int = 0
    cell_usage: dict[str, int] = field(default_factory=dict)
    area_um2: float = 0.0
    timing_estimate_ns: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    netlist_path: str = ""
    json_path: str = ""
    log: str = ""
    duration: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_stat_output(text: str) -> tuple[int, dict[str, int], float]:
    """Parse Yosys ``stat -liberty`` output.

    Returns
    -------
    tuple
        (total_cells, cell_usage_dict, area_um2)
    """
    cell_usage: dict[str, int] = {}
    total_cells = 0
    area = 0.0

    in_cell_section = False
    for line in text.splitlines():
        stripped = line.strip()

        # Detect the cell-histogram section
        if stripped.startswith("Number of cells:"):
            if m := re.search(r"(\d+)", stripped):
                total_cells = int(m.group(1))
            in_cell_section = True
            continue

        # Parse individual cell counts, e.g. "  sky130_fd_sc_hd__and2_1   42"
        if in_cell_section:
            if m := re.match(r"\s+(\S+)\s+(\d+)", line):
                cell_usage[m.group(1)] = int(m.group(2))
                continue
            # End of cell section when we hit a non-matching line
            if stripped and not stripped.startswith("$"):
                in_cell_section = False

        # Chip area
        if m := re.search(r"Chip area for (?:top-level )?module .+?:\s+([\d.]+)", stripped):
            area = float(m.group(1))
        elif m := re.search(r"Estimated chip area:\s+([\d.]+)", stripped):
            area = float(m.group(1))

    return total_cells, cell_usage, area


def _collect_warnings(text: str) -> list[str]:
    """Extract warning lines from Yosys output."""
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r"(?i)\bwarning\b", line)
    ]


def _collect_errors(text: str) -> list[str]:
    """Extract error lines from Yosys output."""
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r"(?i)\berror\b", line)
    ]


def _resolve_liberty(
    pdk_name: str,
    pdk_manager: PDKManager | None,
    corner: str = "tt",
) -> Path | None:
    """Locate the Liberty file for *pdk_name* and *corner*.

    Tries the PDKManager first; falls back to well-known filenames.
    """
    if pdk_manager:
        lib = pdk_manager.get_liberty(pdk_name, corner=corner)
        if lib:
            return lib

    # Fallback: check if well-known Liberty file exists on disk
    default_name = _PDK_LIBERTY.get(pdk_name)
    if default_name:
        p = Path(default_name)
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# SynthesisRunner
# ---------------------------------------------------------------------------


class SynthesisRunner:
    """High-level synthesis runner that orchestrates Yosys for RTL-to-gate flows.

    Uses :class:`YosysEngine` under the hood and streams output through
    the callback for real-time feedback in the desktop or CLI.
    """

    def __init__(
        self,
        project_path: str | PathLike[str],
        config: OpenForgeConfig | None = None,
        *,
        pdk_manager: PDKManager | None = None,
    ) -> None:
        self._project_path = Path(project_path).resolve()
        self._config = config if config is not None else load_config(
            search_dir=self._project_path,
        )
        self._pdk_manager = pdk_manager
        # Auto-detect: use Docker backend if native Yosys not installed
        self._yosys = YosysEngine()
        if not self._yosys.check_installed():
            from openforge.engine.base import ExecutionBackend
            self._yosys = YosysEngine(backend=ExecutionBackend.DOCKER)

    @property
    def project_path(self) -> Path:
        return self._project_path

    @property
    def config(self) -> OpenForgeConfig:
        return self._config

    # ------------------------------------------------------------------
    # Full synthesis
    # ------------------------------------------------------------------

    def run_synthesis(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str = "top",
        pdk: str = "sky130",
        target_frequency: float | None = None,
        flatten: bool = False,
        extra_passes: Sequence[str] = (),
        opt_pass: OptimizationPass = OptimizationPass.BALANCED,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> SynthesisResult:
        """Run a complete RTL-to-gate synthesis flow.

        Parameters
        ----------
        sources:
            HDL source files (``.v``, ``.sv``, ``.vhd``).
        top_module:
            Top-level module name for hierarchy resolution.
        pdk:
            Target PDK name (``"sky130"``, ``"gf180mcu"``).
        target_frequency:
            Target clock frequency in MHz.  Converted to a delay
            constraint for ABC.
        flatten:
            Flatten hierarchy before technology mapping.
        extra_passes:
            Additional Yosys commands injected after FSM optimisation.
        opt_pass:
            ABC optimisation strategy.
        output_dir:
            Directory for output artefacts.  Defaults to
            ``<project>/synth_build/``.
        timeout:
            Yosys process timeout in seconds.
        on_output:
            Callback invoked with each line of Yosys output.
        """
        out_dir = Path(output_dir) if output_dir else self._project_path / "synth_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Resolve liberty file (optional -- generic synthesis if not found)
        liberty = _resolve_liberty(pdk, self._pdk_manager)
        if liberty is None:
            # Fall back to generic synthesis without technology mapping
            liberty = ""

        # Compute delay target from frequency
        target_delay_ps: float | None = None
        if target_frequency and target_frequency > 0:
            period_ns = 1000.0 / target_frequency  # MHz -> ns
            target_delay_ps = period_ns * 1000.0    # ns -> ps

        # Generate the Yosys script (use relative output dir for Docker compat)
        try:
            rel_out = out_dir.relative_to(self._project_path)
        except ValueError:
            rel_out = out_dir
        script = generate_synth_script(
            sources=sources,
            top=top_module,
            liberty=liberty,
            output_dir=rel_out,
            opt_pass=opt_pass,
            target_delay_ps=target_delay_ps,
            flatten=flatten,
            extra_commands=list(extra_passes),
        )

        # Write the script to disk for reproducibility
        script_path = out_dir / "synthesis.ys"
        script_path.write_text(script)

        # Use relative path for Docker compatibility
        try:
            rel_script = script_path.relative_to(self._project_path)
        except ValueError:
            rel_script = script_path
        script_arg = rel_script.as_posix()

        start = time.monotonic()
        result = self._yosys.run_script(
            script_arg,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        # Parse statistics
        gate_count, cell_usage, area = _parse_stat_output(combined)

        # Rough timing estimate from target
        timing_ns = 0.0
        if target_delay_ps:
            timing_ns = target_delay_ps / 1000.0

        netlist_path = str(out_dir / "netlist.v")
        json_path = str(out_dir / "netlist.json")

        return SynthesisResult(
            success=result.ok,
            gate_count=gate_count,
            cell_usage=cell_usage,
            area_um2=area,
            timing_estimate_ns=timing_ns,
            warnings=_collect_warnings(combined),
            errors=_collect_errors(combined) if not result.ok else [],
            netlist_path=netlist_path,
            json_path=json_path,
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Incremental synthesis
    # ------------------------------------------------------------------

    def run_incremental_synthesis(
        self,
        changed_files: Sequence[str | PathLike[str]],
        *,
        top_module: str = "top",
        pdk: str = "sky130",
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> SynthesisResult:
        """Re-synthesize only the modules in *changed_files*.

        This reads only the changed source files, performs hierarchy
        analysis, and runs synthesis on just the affected modules.
        Useful for rapid iteration during RTL development.
        """
        out_dir = Path(output_dir) if output_dir else self._project_path / "synth_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        liberty = _resolve_liberty(pdk, self._pdk_manager)
        if liberty is None:
            return SynthesisResult(
                success=False,
                errors=[f"Cannot locate Liberty file for PDK '{pdk}'"],
            )

        lines: list[str] = []
        for src in changed_files:
            p = Path(src)
            match p.suffix:
                case ".sv" | ".svh":
                    lines.append(f"read_verilog -sv {p}")
                case ".vhd" | ".vhdl":
                    lines.append(f"read_vhdl {p}")
                case _:
                    lines.append(f"read_verilog {p}")

        lines.append(f"hierarchy -top {top_module} -check")
        lines.append("proc; opt; memory; opt; fsm; opt")
        lines.append("techmap; opt")
        lines.append(f"dfflibmap -liberty {liberty}")
        lines.append(f"abc -liberty {liberty}")
        lines.append("opt_clean")
        lines.append(f"write_verilog {out_dir / 'netlist_incr.v'}")
        lines.append(f"write_json {out_dir / 'netlist_incr.json'}")
        lines.append(f"tee -o {out_dir / 'stats_incr.txt'} stat -liberty {liberty}")
        lines.append(f"stat -liberty {liberty}")

        script = "\n".join(lines) + "\n"
        script_path = out_dir / "synthesis_incr.ys"
        script_path.write_text(script)

        start = time.monotonic()
        result = self._yosys.run_script(
            script_path,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        gate_count, cell_usage, area = _parse_stat_output(combined)

        return SynthesisResult(
            success=result.ok,
            gate_count=gate_count,
            cell_usage=cell_usage,
            area_um2=area,
            warnings=_collect_warnings(combined),
            errors=_collect_errors(combined) if not result.ok else [],
            netlist_path=str(out_dir / "netlist_incr.v"),
            json_path=str(out_dir / "netlist_incr.json"),
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Area optimisation
    # ------------------------------------------------------------------

    def run_area_optimization(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str = "top",
        pdk: str = "sky130",
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> SynthesisResult:
        """Run synthesis with aggressive area optimisation.

        Uses the ``AREA`` ABC recipe with additional ``opt -full`` passes
        for maximum area reduction.
        """
        return self.run_synthesis(
            sources,
            top_module=top_module,
            pdk=pdk,
            opt_pass=OptimizationPass.AREA,
            flatten=True,
            extra_passes=["opt -full", "share -aggressive", *list(())],
            output_dir=output_dir,
            timeout=timeout,
            on_output=on_output,
        )

    # ------------------------------------------------------------------
    # Timing optimisation
    # ------------------------------------------------------------------

    def run_timing_optimization(
        self,
        sources: Sequence[str | PathLike[str]],
        target_delay_ps: float,
        *,
        top_module: str = "top",
        pdk: str = "sky130",
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> SynthesisResult:
        """Run synthesis with tight timing constraints.

        Uses the ``SPEED`` ABC recipe with the specified target delay to
        prioritise timing closure over area.
        """
        freq_mhz = 1_000_000.0 / target_delay_ps if target_delay_ps > 0 else None
        return self.run_synthesis(
            sources,
            top_module=top_module,
            pdk=pdk,
            target_frequency=freq_mhz,
            opt_pass=OptimizationPass.SPEED,
            output_dir=output_dir,
            timeout=timeout,
            on_output=on_output,
        )

    # ------------------------------------------------------------------
    # Post-synthesis queries
    # ------------------------------------------------------------------

    def get_cell_usage(self, synthesis_log: str) -> dict[str, int]:
        """Extract cell-type usage counts from a synthesis log.

        Parameters
        ----------
        synthesis_log:
            The raw Yosys stdout/stderr text (or the ``log`` field of a
            :class:`SynthesisResult`).

        Returns
        -------
        dict[str, int]
            Mapping of cell type name to instance count.
        """
        _, cell_usage, _ = _parse_stat_output(synthesis_log)
        return cell_usage

    def get_area_estimate(self, synthesis_log: str) -> float:
        """Extract area estimate in um^2 from a synthesis log.

        Parameters
        ----------
        synthesis_log:
            The raw Yosys stdout/stderr text.

        Returns
        -------
        float
            Estimated chip area in um^2 from Liberty-based ``stat``.
        """
        _, _, area = _parse_stat_output(synthesis_log)
        return area
