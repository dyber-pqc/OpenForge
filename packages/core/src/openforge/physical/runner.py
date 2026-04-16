"""High-level physical design runner -- orchestrates OpenROAD for PnR flows."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openforge.config.loader import load_config
from openforge.engine.openroad import OpenROADEngine

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from os import PathLike

    from openforge.config.schema import OpenForgeConfig
    from openforge.pdk.manager import PDKManager

# ---------------------------------------------------------------------------
# PDK-specific physical design configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PDKPhysicalConfig:
    """PDK-specific parameters for physical design."""

    site: str
    tracks_layer_range: str  # e.g. "met1-met5"
    hor_layer: str
    ver_layer: str
    buf_cells: list[str]
    root_buf: str
    clk_buf_list: str  # space-separated for TCL
    tech_lef_name: str
    cell_lef_name: str


_PDK_CONFIGS: dict[str, _PDKPhysicalConfig] = {
    "sky130": _PDKPhysicalConfig(
        site="unithd",
        tracks_layer_range="met1-met5",
        hor_layer="met3",
        ver_layer="met2",
        buf_cells=[
            "sky130_fd_sc_hd__buf_1",
            "sky130_fd_sc_hd__buf_2",
            "sky130_fd_sc_hd__buf_4",
            "sky130_fd_sc_hd__buf_8",
        ],
        root_buf="sky130_fd_sc_hd__buf_4",
        clk_buf_list="sky130_fd_sc_hd__buf_1 sky130_fd_sc_hd__buf_2 sky130_fd_sc_hd__buf_4 sky130_fd_sc_hd__buf_8",
        tech_lef_name="sky130_fd_sc_hd.tlef",
        cell_lef_name="sky130_fd_sc_hd_merged.lef",
    ),
    "gf180mcu": _PDKPhysicalConfig(
        site="GF018hv5v_green_sc7",
        tracks_layer_range="met1-met5",
        hor_layer="Metal3",
        ver_layer="Metal2",
        buf_cells=[
            "gf180mcu_fd_sc_mcu7t5v0__buf_1",
            "gf180mcu_fd_sc_mcu7t5v0__buf_2",
            "gf180mcu_fd_sc_mcu7t5v0__buf_4",
            "gf180mcu_fd_sc_mcu7t5v0__buf_8",
        ],
        root_buf="gf180mcu_fd_sc_mcu7t5v0__buf_4",
        clk_buf_list="gf180mcu_fd_sc_mcu7t5v0__buf_1 gf180mcu_fd_sc_mcu7t5v0__buf_2 gf180mcu_fd_sc_mcu7t5v0__buf_4 gf180mcu_fd_sc_mcu7t5v0__buf_8",
        tech_lef_name="gf180mcu_fd_sc_mcu7t5v0.tlef",
        cell_lef_name="gf180mcu_fd_sc_mcu7t5v0.lef",
    ),
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhysicalDesignResult:
    """Outcome of a physical design run."""

    success: bool
    def_path: str = ""
    gds_path: str = ""
    area_um2: float = 0.0
    utilization_pct: float = 0.0
    wirelength_um: float = 0.0
    drc_violations: int = 0
    timing_wns: float = 0.0
    timing_tns: float = 0.0
    power_mw: float = 0.0
    log: str = ""
    duration: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_area(text: str) -> float:
    """Extract design area from OpenROAD ``report_design_area`` output."""
    if m := re.search(r"Design area\s+([\d.]+)\s+u\^2", text):
        return float(m.group(1))
    if m := re.search(r"(?:total|design)\s+area\s*[=:]\s*([\d.eE+\-]+)", text, re.IGNORECASE):
        return float(m.group(1))
    return 0.0


def _parse_utilization(text: str) -> float:
    """Extract utilization percentage from OpenROAD output."""
    if m := re.search(r"(?:utilization|util)\s*[=:]\s*([\d.]+)\s*%?", text, re.IGNORECASE):
        return float(m.group(1))
    return 0.0


def _parse_wirelength(text: str) -> float:
    """Extract total wirelength from OpenROAD output."""
    if m := re.search(r"(?:total|wirelength)\s*[=:]\s*([\d.eE+\-]+)", text, re.IGNORECASE):
        return float(m.group(1))
    return 0.0


def _parse_drc_count(text: str) -> int:
    """Extract DRC violation count from detailed_route output."""
    if m := re.search(r"Number of DRC violations\s*[=:]\s*(\d+)", text):
        return int(m.group(1))
    if m := re.search(r"Total number of violations\s*[=:]\s*(\d+)", text):
        return int(m.group(1))
    if m := re.search(r"DRC violations\s*[=:]\s*(\d+)", text, re.IGNORECASE):
        return int(m.group(1))
    return 0


def _parse_wns(text: str) -> float:
    """Extract worst negative slack from report_checks."""
    if m := re.search(r"wns\s+([-+]?[\d.]+)", text):
        return float(m.group(1))
    if m := re.search(r"worst\s+(?:negative\s+)?slack\s*[=:]\s*([-+]?[\d.]+)", text, re.IGNORECASE):
        return float(m.group(1))
    return 0.0


def _parse_tns(text: str) -> float:
    """Extract total negative slack from report_checks."""
    if m := re.search(r"tns\s+([-+]?[\d.]+)", text):
        return float(m.group(1))
    if m := re.search(r"total\s+(?:negative\s+)?slack\s*[=:]\s*([-+]?[\d.]+)", text, re.IGNORECASE):
        return float(m.group(1))
    return 0.0


def _parse_power(text: str) -> float:
    """Extract total power in mW from report_power."""
    if m := re.search(r"Total\s+[\d.eE+\-]+\s+[\d.eE+\-]+\s+[\d.eE+\-]+\s+([\d.eE+\-]+)", text):
        return float(m.group(1)) * 1000.0  # W -> mW
    if m := re.search(r"[Tt]otal\s+[Pp]ower\s*[=:]\s*([\d.eE+\-]+)\s*(mW|W|uW)?", text):
        val = float(m.group(1))
        unit = m.group(2) or "mW"
        if unit == "W":
            val *= 1000.0
        elif unit == "uW":
            val /= 1000.0
        return val
    return 0.0


def _collect_warnings(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.search(r"(?i)\bwarning\b", line)]


# ---------------------------------------------------------------------------
# PhysicalDesignRunner
# ---------------------------------------------------------------------------


class PhysicalDesignRunner:
    """High-level physical design runner wrapping OpenROAD.

    Orchestrates floorplanning, placement, clock-tree synthesis,
    and routing through generated TCL scripts.
    """

    def __init__(
        self,
        project_path: str | PathLike[str],
        config: OpenForgeConfig | None = None,
        pdk: str = "sky130",
        *,
        pdk_manager: PDKManager | None = None,
    ) -> None:
        self._project_path = Path(project_path).resolve()
        self._config = (
            config
            if config is not None
            else load_config(
                search_dir=self._project_path,
            )
        )
        self._pdk_name = pdk
        self._pdk_manager = pdk_manager
        self._openroad = OpenROADEngine()
        self._pdk_cfg = _PDK_CONFIGS.get(pdk)

    @property
    def project_path(self) -> Path:
        return self._project_path

    @property
    def config(self) -> OpenForgeConfig:
        return self._config

    # ------------------------------------------------------------------
    # Resolve PDK files
    # ------------------------------------------------------------------

    def _resolve_liberty(self) -> str:
        """Return the path to the Liberty file as a string."""
        if self._pdk_manager:
            lib = self._pdk_manager.get_liberty(self._pdk_name)
            if lib:
                return str(lib)
        # Fallback to well-known names
        from openforge.synthesis.runner import _PDK_LIBERTY

        return _PDK_LIBERTY.get(self._pdk_name, "liberty.lib")

    def _resolve_lef(self, kind: str = "tech") -> str:
        """Return path to tech or cell LEF file."""
        if self._pdk_manager:
            lef = self._pdk_manager.get_lef(self._pdk_name)
            if lef:
                return str(lef)
        cfg = self._pdk_cfg
        if cfg:
            return cfg.tech_lef_name if kind == "tech" else cfg.cell_lef_name
        return "tech.lef" if kind == "tech" else "cells.lef"

    # ------------------------------------------------------------------
    # Full PnR flow
    # ------------------------------------------------------------------

    def run_full_flow(
        self,
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        *,
        pdk_name: str | None = None,
        utilization: float = 0.5,
        aspect_ratio: float = 1.0,
        core_margin: float = 5.0,
        density: float = 0.7,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PhysicalDesignResult:
        """Run the complete floorplan-to-route OpenROAD flow.

        Parameters
        ----------
        netlist:
            Gate-level Verilog netlist from synthesis.
        sdc:
            Synopsys Design Constraints file.
        pdk_name:
            Override the PDK name set in the constructor.
        utilization:
            Target core utilization (0.0--1.0).
        aspect_ratio:
            Floorplan aspect ratio.
        core_margin:
            Core-to-die margin in microns.
        density:
            Global placement target density.
        output_dir:
            Directory for output artefacts.
        timeout:
            OpenROAD process timeout in seconds.
        on_output:
            Callback invoked with each line of OpenROAD output.
        """
        if pdk_name:
            self._pdk_name = pdk_name
            self._pdk_cfg = _PDK_CONFIGS.get(pdk_name)

        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False,
                log=f"Unsupported PDK for physical design: {self._pdk_name}",
            )

        out_dir = Path(output_dir) if output_dir else self._project_path / "pnr_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")
        top_module = self._config.project.top_module

        output_def = out_dir / "final.def"
        output_netlist = out_dir / "final.v"
        drc_report = out_dir / "drc_report.rpt"
        maze_log = out_dir / "maze_route.log"

        util_pct = int(utilization * 100)

        # Build the complete TCL script
        tcl_lines: list[str] = [
            f"# OpenForge Physical Design Flow -- {self._pdk_name}",
            "# Generated by PhysicalDesignRunner",
            "",
            "# ---- Read technology ----",
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {lib_path}",
            "",
            "# ---- Read design ----",
            f"read_verilog {netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
            "",
            "# ---- Floorplan ----",
            f"initialize_floorplan -utilization {util_pct} -aspect_ratio {aspect_ratio} -core_space {core_margin} -site {cfg.site}",
            "",
            "# ---- Track and pin assignment ----",
            "make_tracks",
            f"place_pins -hor_layer {cfg.hor_layer} -ver_layer {cfg.ver_layer}",
            "",
            "# ---- Global placement ----",
            f"global_placement -density {density}",
            "",
            "# ---- Post-placement optimization ----",
            "estimate_parasitics -placement",
            "repair_design",
            "detailed_placement",
            "improve_placement",
            "",
            "# ---- Clock tree synthesis ----",
            f"clock_tree_synthesis -buf_list {{{cfg.clk_buf_list}}} -root_buf {cfg.root_buf}",
            "",
            "# ---- Post-CTS optimization ----",
            "estimate_parasitics -placement",
            "repair_timing",
            "",
            "# ---- Global routing ----",
            f"set_global_routing_layer_adjustment {cfg.tracks_layer_range} 0.5",
            "global_route",
            "",
            "# ---- Detailed routing ----",
            f"detailed_route -output_drc {drc_report} -output_maze {maze_log}",
            "",
            "# ---- Write outputs ----",
            f"write_def {output_def}",
            f"write_verilog {output_netlist}",
            "",
            "# ---- Reports ----",
            "report_design_area",
            "report_power",
            "report_checks -path_delay max",
            "report_checks -path_delay min",
            "report_tns",
            "report_wns",
            "",
            "exit",
        ]

        tcl_content = "\n".join(tcl_lines) + "\n"
        tcl_path = out_dir / "pnr_flow.tcl"
        tcl_path.write_text(tcl_content)

        start = time.monotonic()
        result = self._openroad.run_tcl(
            tcl_path,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        return PhysicalDesignResult(
            success=result.ok,
            def_path=str(output_def),
            gds_path="",  # GDS requires a separate stream-out step
            area_um2=_parse_area(combined),
            utilization_pct=_parse_utilization(combined),
            wirelength_um=_parse_wirelength(combined),
            drc_violations=_parse_drc_count(combined),
            timing_wns=_parse_wns(combined),
            timing_tns=_parse_tns(combined),
            power_mw=_parse_power(combined),
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Individual stages
    # ------------------------------------------------------------------

    def run_floorplan(
        self,
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        *,
        utilization: float = 0.5,
        aspect_ratio: float = 1.0,
        core_margin: float = 5.0,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PhysicalDesignResult:
        """Run only the floorplanning stage."""
        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False,
                log=f"Unsupported PDK: {self._pdk_name}",
            )

        out_dir = Path(output_dir) if output_dir else self._project_path / "pnr_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")
        top_module = self._config.project.top_module
        output_def = out_dir / "floorplan.def"
        util_pct = int(utilization * 100)

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {lib_path}",
            f"read_verilog {netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
            f"initialize_floorplan -utilization {util_pct} -aspect_ratio {aspect_ratio} -core_space {core_margin} -site {cfg.site}",
            "make_tracks",
            f"place_pins -hor_layer {cfg.hor_layer} -ver_layer {cfg.ver_layer}",
            f"write_def {output_def}",
            "report_design_area",
            "exit",
        ]

        return self._run_tcl_stage(tcl_lines, out_dir, "floorplan", output_def, timeout, on_output)

    def run_placement(
        self,
        def_input: str | PathLike[str],
        *,
        density: float = 0.7,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PhysicalDesignResult:
        """Run only the placement stage on an existing DEF."""
        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False,
                log=f"Unsupported PDK: {self._pdk_name}",
            )

        out_dir = Path(output_dir) if output_dir else self._project_path / "pnr_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")
        output_def = out_dir / "placed.def"

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {lib_path}",
            f"read_def {def_input}",
            f"global_placement -density {density}",
            "estimate_parasitics -placement",
            "repair_design",
            "detailed_placement",
            "improve_placement",
            f"write_def {output_def}",
            "report_design_area",
            "exit",
        ]

        return self._run_tcl_stage(tcl_lines, out_dir, "placement", output_def, timeout, on_output)

    def run_cts(
        self,
        def_input: str | PathLike[str],
        *,
        clock_buf_cells: Sequence[str] | None = None,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PhysicalDesignResult:
        """Run only the clock tree synthesis stage."""
        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False,
                log=f"Unsupported PDK: {self._pdk_name}",
            )

        out_dir = Path(output_dir) if output_dir else self._project_path / "pnr_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")
        output_def = out_dir / "cts.def"

        if clock_buf_cells:
            buf_list = " ".join(clock_buf_cells)
            root_buf = clock_buf_cells[0]
        else:
            buf_list = cfg.clk_buf_list
            root_buf = cfg.root_buf

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {lib_path}",
            f"read_def {def_input}",
            f"clock_tree_synthesis -buf_list {{{buf_list}}} -root_buf {root_buf}",
            "estimate_parasitics -placement",
            "repair_timing",
            f"write_def {output_def}",
            "exit",
        ]

        return self._run_tcl_stage(tcl_lines, out_dir, "cts", output_def, timeout, on_output)

    def run_routing(
        self,
        def_input: str | PathLike[str],
        *,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PhysicalDesignResult:
        """Run only the routing stage (global + detailed)."""
        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False,
                log=f"Unsupported PDK: {self._pdk_name}",
            )

        out_dir = Path(output_dir) if output_dir else self._project_path / "pnr_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")
        output_def = out_dir / "routed.def"
        drc_report = out_dir / "drc_report.rpt"
        maze_log = out_dir / "maze_route.log"

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {lib_path}",
            f"read_def {def_input}",
            f"set_global_routing_layer_adjustment {cfg.tracks_layer_range} 0.5",
            "global_route",
            f"detailed_route -output_drc {drc_report} -output_maze {maze_log}",
            f"write_def {output_def}",
            "report_design_area",
            "report_checks -path_delay max",
            "report_wns",
            "report_tns",
            "exit",
        ]

        return self._run_tcl_stage(tcl_lines, out_dir, "routing", output_def, timeout, on_output)

    def run_power_grid(
        self,
        def_input: str | PathLike[str],
        *,
        layer_config: dict[str, Any] | None = None,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PhysicalDesignResult:
        """Generate power straps and rails.

        Parameters
        ----------
        def_input:
            Input DEF file (typically post-floorplan).
        layer_config:
            Optional dict with keys ``hor_layer``, ``ver_layer``,
            ``width``, ``pitch``, ``offset`` for custom power grid
            parameters.
        """
        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False,
                log=f"Unsupported PDK: {self._pdk_name}",
            )

        out_dir = Path(output_dir) if output_dir else self._project_path / "pnr_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")
        output_def = out_dir / "power_grid.def"

        hor_layer = (layer_config or {}).get("hor_layer", cfg.hor_layer)
        ver_layer = (layer_config or {}).get("ver_layer", cfg.ver_layer)
        width = (layer_config or {}).get("width", 1.6)
        pitch = (layer_config or {}).get("pitch", 27.14)
        offset = (layer_config or {}).get("offset", 13.57)

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_def {def_input}",
            "",
            "# Power network definition",
            "add_global_connection -net VDD -pin_pattern {^VDD$} -power",
            "add_global_connection -net VDD -pin_pattern {^VPWR$}",
            "add_global_connection -net VSS -pin_pattern {^VSS$} -ground",
            "add_global_connection -net VSS -pin_pattern {^VGND$}",
            "global_connect",
            "",
            "# Power grid straps",
            "set_voltage_domain -power VDD -ground VSS",
            f"define_pdn_grid -name main_grid -pins {{{ver_layer}}}",
            f"add_pdn_stripe -grid main_grid -layer {ver_layer} -width {width} -pitch {pitch} -offset {offset} -followpins",
            f"add_pdn_stripe -grid main_grid -layer {hor_layer} -width {width} -pitch {pitch} -offset {offset}",
            f"add_pdn_connect -grid main_grid -layers {{{ver_layer} {hor_layer}}}",
            "",
            f"write_def {output_def}",
            "exit",
        ]

        return self._run_tcl_stage(tcl_lines, out_dir, "power_grid", output_def, timeout, on_output)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_tcl_stage(
        self,
        tcl_lines: list[str],
        out_dir: Path,
        stage_name: str,
        output_def: Path,
        timeout: float | None,
        on_output: Callable[[str], None] | None,
    ) -> PhysicalDesignResult:
        """Write TCL, execute in OpenROAD, and parse results."""
        tcl_content = "\n".join(tcl_lines) + "\n"
        tcl_path = out_dir / f"{stage_name}.tcl"
        tcl_path.write_text(tcl_content)

        start = time.monotonic()
        result = self._openroad.run_tcl(
            tcl_path,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        return PhysicalDesignResult(
            success=result.ok,
            def_path=str(output_def),
            area_um2=_parse_area(combined),
            utilization_pct=_parse_utilization(combined),
            wirelength_um=_parse_wirelength(combined),
            drc_violations=_parse_drc_count(combined),
            timing_wns=_parse_wns(combined),
            timing_tns=_parse_tns(combined),
            power_mw=_parse_power(combined),
            log=combined,
            duration=elapsed,
        )
