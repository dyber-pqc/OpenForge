"""OpenLane 2.0 RTL-to-GDSII flow integration.

Wraps the complete RTL-to-GDSII tapeout flow through OpenROAD, Yosys,
Magic, Netgen, and KLayout.  Generates valid TCL scripts for each stage
that can be run natively (OSS CAD Suite) or via Docker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openforge.config.loader import load_config
from openforge.engine.klayout import KLayoutEngine
from openforge.engine.magic import MagicEngine
from openforge.engine.netgen import NetgenEngine
from openforge.engine.openroad import OpenROADEngine
from openforge.engine.yosys import YosysEngine
from openforge.physical.floorplan import FloorplanConfig, FloorplanGenerator
from openforge.physical.pdn import PDNGenerator
from openforge.physical.runner import (
    _PDK_CONFIGS,
    PhysicalDesignResult,
    _parse_area,
    _parse_drc_count,
    _parse_power,
    _parse_tns,
    _parse_utilization,
    _parse_wirelength,
    _parse_wns,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from os import PathLike

    from openforge.config.schema import OpenForgeConfig
    from openforge.pdk.manager import PDKManager

# ---------------------------------------------------------------------------
# Flow step enumeration
# ---------------------------------------------------------------------------


class FlowStep(Enum):
    """Individual steps in the RTL-to-GDSII flow."""

    SYNTHESIS = auto()
    FLOORPLAN = auto()
    IO_PLACEMENT = auto()
    PDN = auto()
    GLOBAL_PLACEMENT = auto()
    DETAILED_PLACEMENT = auto()
    CTS = auto()
    GLOBAL_ROUTE = auto()
    DETAILED_ROUTE = auto()
    FILL_INSERTION = auto()
    DRC = auto()
    LVS = auto()
    ANTENNA_CHECK = auto()
    GDS_EXPORT = auto()
    SIGNOFF_TIMING = auto()


_STEP_NAMES: dict[FlowStep, str] = {
    FlowStep.SYNTHESIS: "Synthesis",
    FlowStep.FLOORPLAN: "Floorplan",
    FlowStep.IO_PLACEMENT: "IO Placement",
    FlowStep.PDN: "Power Distribution Network",
    FlowStep.GLOBAL_PLACEMENT: "Global Placement",
    FlowStep.DETAILED_PLACEMENT: "Detailed Placement",
    FlowStep.CTS: "Clock Tree Synthesis",
    FlowStep.GLOBAL_ROUTE: "Global Routing",
    FlowStep.DETAILED_ROUTE: "Detailed Routing",
    FlowStep.FILL_INSERTION: "Fill Insertion",
    FlowStep.DRC: "DRC",
    FlowStep.LVS: "LVS",
    FlowStep.ANTENNA_CHECK: "Antenna Check",
    FlowStep.GDS_EXPORT: "GDS Export",
    FlowStep.SIGNOFF_TIMING: "Signoff Timing",
}

# Default full flow order
_FULL_FLOW_ORDER: list[FlowStep] = [
    FlowStep.SYNTHESIS,
    FlowStep.FLOORPLAN,
    FlowStep.IO_PLACEMENT,
    FlowStep.PDN,
    FlowStep.GLOBAL_PLACEMENT,
    FlowStep.DETAILED_PLACEMENT,
    FlowStep.CTS,
    FlowStep.GLOBAL_ROUTE,
    FlowStep.DETAILED_ROUTE,
    FlowStep.FILL_INSERTION,
    FlowStep.DRC,
    FlowStep.LVS,
    FlowStep.ANTENNA_CHECK,
    FlowStep.GDS_EXPORT,
    FlowStep.SIGNOFF_TIMING,
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OpenLaneResult:
    """Outcome of an OpenLane RTL-to-GDSII run."""

    success: bool
    gds_path: str = ""
    def_path: str = ""
    area_um2: float = 0.0
    utilization_pct: float = 0.0
    drc_violations: int = 0
    lvs_match: bool = False
    wns: float = 0.0
    tns: float = 0.0
    power_mw: float = 0.0
    wirelength_um: float = 0.0
    log: str = ""
    step_logs: dict[str, str] = field(default_factory=dict)
    step_durations: dict[str, float] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str = ""


# ---------------------------------------------------------------------------
# PDK-specific synthesis liberty lookup
# ---------------------------------------------------------------------------

_PDK_LIBERTY: dict[str, str] = {
    "sky130": "sky130_fd_sc_hd__tt_025C_1v80.lib",
    "gf180mcu": "gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80.lib",
}

_PDK_TECH_FILES: dict[str, str] = {
    "sky130": "sky130A.tech",
    "gf180mcu": "gf180mcu.tech",
}

_PDK_NETGEN_SETUP: dict[str, str] = {
    "sky130": "sky130A_setup.tcl",
    "gf180mcu": "gf180mcu_setup.tcl",
}


# ---------------------------------------------------------------------------
# OpenLaneRunner
# ---------------------------------------------------------------------------


class OpenLaneRunner:
    """Orchestrates the full OpenLane RTL-to-GDSII flow.

    Generates valid OpenROAD TCL scripts for each physical design stage,
    uses Yosys for synthesis, Magic for DRC/extraction/GDS, Netgen for
    LVS, and KLayout as a backup GDS streamer.

    If OpenROAD is not installed natively, scripts are generated for
    manual execution.  Docker support uses ``hdlc/yosys`` for synthesis.
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
        self._config = config if config is not None else load_config(
            search_dir=self._project_path,
        )
        self._pdk_name = pdk
        self._pdk_manager = pdk_manager
        self._pdk_cfg = _PDK_CONFIGS.get(pdk)

        # Engine instances -- auto-detect native vs Docker
        self._openroad = OpenROADEngine()
        self._yosys = YosysEngine()
        self._magic = MagicEngine()
        self._netgen = NetgenEngine()
        self._klayout = KLayoutEngine()

        # Auto-detect Docker fallback for Yosys
        if not self._yosys.check_installed():
            from openforge.engine.base import ExecutionBackend
            self._yosys = YosysEngine(backend=ExecutionBackend.DOCKER)

        # Build output directory
        self._build_dir = self._project_path / "openlane_build"

        # Floorplan and PDN generators
        self._floorplan_gen = FloorplanGenerator(pdk=pdk)
        self._pdn_gen = PDNGenerator(pdk=pdk)

        # Callback for streaming output
        self._on_output: Callable[[str], None] | None = None
        self._on_step: Callable[[FlowStep, str], None] | None = None

        # Cancellation flag
        self._cancelled = False

    @property
    def project_path(self) -> Path:
        return self._project_path

    @property
    def build_dir(self) -> Path:
        return self._build_dir

    def set_callbacks(
        self,
        on_output: Callable[[str], None] | None = None,
        on_step: Callable[[FlowStep, str], None] | None = None,
    ) -> None:
        """Set callbacks for output streaming and step progress."""
        self._on_output = on_output
        self._on_step = on_step

    def cancel(self) -> None:
        """Request cancellation of the current flow."""
        self._cancelled = True

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._on_output:
            self._on_output(text)

    def _emit_step(self, step: FlowStep, status: str) -> None:
        name = _STEP_NAMES.get(step, step.name)
        self._emit(f"[{name}] {status}")
        if self._on_step:
            self._on_step(step, status)

    # ------------------------------------------------------------------
    # PDK file resolution
    # ------------------------------------------------------------------

    def _resolve_liberty(self) -> str:
        if self._pdk_manager:
            lib = self._pdk_manager.get_liberty(self._pdk_name)
            if lib:
                return str(lib)
        default = _PDK_LIBERTY.get(self._pdk_name, "liberty.lib")
        # Search well-known locations
        search_dirs = [
            self._project_path,
            Path(__file__).resolve().parents[5] / "share" / "pdk" / self._pdk_name / "lib",
            Path.home() / ".openforge" / "pdks" / self._pdk_name,
        ]
        for d in search_dirs:
            p = d / default
            if p.exists():
                return str(p)
        return default

    def _resolve_lef(self, kind: str = "tech") -> str:
        if self._pdk_manager:
            lef = self._pdk_manager.get_lef(self._pdk_name)
            if lef:
                return str(lef)
        cfg = self._pdk_cfg
        if cfg:
            return cfg.tech_lef_name if kind == "tech" else cfg.cell_lef_name
        return "tech.lef" if kind == "tech" else "cells.lef"

    def _resolve_tech_file(self) -> str:
        return _PDK_TECH_FILES.get(self._pdk_name, "sky130A.tech")

    def _resolve_netgen_setup(self) -> str:
        return _PDK_NETGEN_SETUP.get(self._pdk_name, "/dev/null")

    # ------------------------------------------------------------------
    # Full flow
    # ------------------------------------------------------------------

    def run_full_flow(
        self,
        sources: Sequence[str | PathLike[str]],
        top_module: str,
        clock_period_ns: float = 10.0,
        die_area: tuple[float, float, float, float] | None = None,
        core_utilization: float = 0.5,
        *,
        output_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> OpenLaneResult:
        """Run the complete RTL-to-GDSII flow.

        Parameters
        ----------
        sources:
            RTL source files (Verilog/SystemVerilog).
        top_module:
            Top-level module name.
        clock_period_ns:
            Target clock period in nanoseconds.
        die_area:
            Explicit die area as ``(x0, y0, x1, y1)`` in microns.
            If ``None``, auto-sized from gate count and utilization.
        core_utilization:
            Target core utilization (0.0 -- 1.0).
        output_dir:
            Override the default build directory.
        timeout:
            Per-step timeout in seconds.
        """
        self._cancelled = False
        build = Path(output_dir) if output_dir else self._build_dir
        build.mkdir(parents=True, exist_ok=True)

        result = OpenLaneResult(success=False)

        cfg = self._pdk_cfg
        if cfg is None:
            result.log = f"Unsupported PDK: {self._pdk_name}"
            return result

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")

        # Create subdirectories for each stage
        for subdir in [
            "synthesis", "floorplan", "placement", "cts",
            "routing", "signoff", "gds", "reports",
        ]:
            (build / subdir).mkdir(exist_ok=True)

        # Generate SDC constraints
        sdc_path = build / "constraints.sdc"
        sdc_content = (
            f"create_clock -name clk -period {clock_period_ns} [get_ports clk]\n"
            f"set_input_delay -clock clk {clock_period_ns * 0.1} [all_inputs]\n"
            f"set_output_delay -clock clk {clock_period_ns * 0.1} [all_outputs]\n"
        )
        sdc_path.write_text(sdc_content)

        # ---- Step 1: Synthesis (Yosys) ----
        if self._cancelled:
            return result
        step_result = self._run_synthesis_step(
            sources, top_module, lib_path, build / "synthesis", timeout,
        )
        result.step_logs["synthesis"] = step_result.log
        result.step_durations["synthesis"] = step_result.duration
        if not step_result.success:
            result.log = step_result.log
            result.failed_step = "synthesis"
            return result
        result.completed_steps.append("synthesis")
        netlist_path = build / "synthesis" / "netlist.v"

        # ---- Step 2: Floorplan ----
        if self._cancelled:
            return result
        step_result = self._run_floorplan_step(
            netlist_path, str(sdc_path), top_module,
            die_area, core_utilization, lib_path, tech_lef, cell_lef,
            build / "floorplan", timeout,
        )
        result.step_logs["floorplan"] = step_result.log
        result.step_durations["floorplan"] = step_result.duration
        if not step_result.success:
            result.log = step_result.log
            result.failed_step = "floorplan"
            return result
        result.completed_steps.append("floorplan")

        # ---- Step 3-9: Place & Route (single OpenROAD script) ----
        if self._cancelled:
            return result
        pnr_result = self._run_pnr_script(
            netlist_path, str(sdc_path), top_module,
            die_area, core_utilization,
            lib_path, tech_lef, cell_lef,
            build, timeout,
        )
        for step_name in ["placement", "cts", "routing"]:
            result.step_logs[step_name] = pnr_result.log
            result.step_durations[step_name] = pnr_result.duration
        if not pnr_result.success:
            result.log = pnr_result.log
            result.failed_step = "pnr"
            return result
        result.completed_steps.extend(["placement", "cts", "routing"])
        result.def_path = pnr_result.def_path
        result.area_um2 = pnr_result.area_um2
        result.utilization_pct = pnr_result.utilization_pct
        result.wirelength_um = pnr_result.wirelength_um
        result.wns = pnr_result.timing_wns
        result.tns = pnr_result.timing_tns
        result.power_mw = pnr_result.power_mw

        # ---- Step 10: DRC (Magic) ----
        if self._cancelled:
            return result
        drc_result = self._run_drc_step(
            pnr_result.def_path, build / "signoff", timeout,
        )
        result.step_logs["drc"] = drc_result.log
        result.step_durations["drc"] = drc_result.duration
        result.drc_violations = drc_result.drc_violations
        result.completed_steps.append("drc")

        # ---- Step 11: LVS (Netgen) ----
        if self._cancelled:
            return result
        lvs_result = self._run_lvs_step(
            pnr_result.def_path, str(netlist_path),
            build / "signoff", timeout,
        )
        result.step_logs["lvs"] = lvs_result.log
        result.step_durations["lvs"] = lvs_result.duration
        result.lvs_match = lvs_result.success
        result.completed_steps.append("lvs")

        # ---- Step 12: GDS Export (Magic/KLayout) ----
        if self._cancelled:
            return result
        gds_result = self._run_gds_export_step(
            pnr_result.def_path, top_module,
            build / "gds", timeout,
        )
        result.step_logs["gds_export"] = gds_result.log
        result.step_durations["gds_export"] = gds_result.duration
        if gds_result.gds_path:
            result.gds_path = gds_result.gds_path
        result.completed_steps.append("gds_export")

        # ---- Step 13: Signoff Timing (OpenSTA via OpenROAD) ----
        if self._cancelled:
            return result
        sta_result = self._run_signoff_timing_step(
            str(netlist_path), str(sdc_path),
            lib_path, tech_lef, cell_lef,
            pnr_result.def_path,
            build / "signoff", timeout,
        )
        result.step_logs["signoff_timing"] = sta_result.log
        result.step_durations["signoff_timing"] = sta_result.duration
        if sta_result.timing_wns != 0.0:
            result.wns = sta_result.timing_wns
            result.tns = sta_result.timing_tns
        result.completed_steps.append("signoff_timing")

        # Assemble final log
        result.success = True
        result.log = self._assemble_summary(result)
        return result

    # ------------------------------------------------------------------
    # Run a single step by name
    # ------------------------------------------------------------------

    def run_step(
        self,
        step_name: str,
        *,
        sources: Sequence[str | PathLike[str]] | None = None,
        top_module: str = "top",
        netlist: str | PathLike[str] | None = None,
        sdc: str | PathLike[str] | None = None,
        def_input: str | PathLike[str] | None = None,
        die_area: tuple[float, float, float, float] | None = None,
        core_utilization: float = 0.5,
        timeout: float | None = None,
    ) -> PhysicalDesignResult:
        """Run a single named step of the flow.

        Parameters
        ----------
        step_name:
            One of: synthesis, floorplan, placement, cts, routing,
            drc, lvs, gds_export, signoff_timing
        """
        build = self._build_dir
        build.mkdir(parents=True, exist_ok=True)

        lib_path = self._resolve_liberty()
        tech_lef = self._resolve_lef("tech")
        cell_lef = self._resolve_lef("cell")

        step = step_name.lower().replace("-", "_").replace(" ", "_")
        self._emit_step(FlowStep.SYNTHESIS, f"Running step: {step}")

        if step == "synthesis":
            if not sources:
                return PhysicalDesignResult(
                    success=False, log="No source files provided for synthesis",
                )
            return self._run_synthesis_step(
                sources, top_module, lib_path,
                build / "synthesis", timeout,
            )
        elif step == "floorplan":
            if not netlist or not sdc:
                return PhysicalDesignResult(
                    success=False,
                    log="Floorplan requires netlist and SDC files",
                )
            return self._run_floorplan_step(
                netlist, str(sdc), top_module,
                die_area, core_utilization,
                lib_path, tech_lef, cell_lef,
                build / "floorplan", timeout,
            )
        elif step in ("placement", "pnr", "place_route"):
            if not netlist or not sdc:
                return PhysicalDesignResult(
                    success=False,
                    log="P&R requires netlist and SDC files",
                )
            return self._run_pnr_script(
                netlist, str(sdc), top_module,
                die_area, core_utilization,
                lib_path, tech_lef, cell_lef,
                build, timeout,
            )
        elif step == "cts":
            if not def_input:
                return PhysicalDesignResult(
                    success=False, log="CTS requires a DEF input file",
                )
            return self._run_cts_step(
                def_input, lib_path, tech_lef, cell_lef,
                build / "cts", timeout,
            )
        elif step in ("routing", "route"):
            if not def_input:
                return PhysicalDesignResult(
                    success=False, log="Routing requires a DEF input file",
                )
            return self._run_routing_step(
                def_input, lib_path, tech_lef, cell_lef,
                build / "routing", timeout,
            )
        elif step == "drc":
            if not def_input:
                return PhysicalDesignResult(
                    success=False, log="DRC requires a DEF input file",
                )
            return self._run_drc_step(def_input, build / "signoff", timeout)
        elif step == "lvs":
            if not def_input or not netlist:
                return PhysicalDesignResult(
                    success=False,
                    log="LVS requires DEF and netlist files",
                )
            return self._run_lvs_step(
                def_input, str(netlist), build / "signoff", timeout,
            )
        elif step == "gds_export":
            if not def_input:
                return PhysicalDesignResult(
                    success=False, log="GDS export requires a DEF input file",
                )
            return self._run_gds_export_step(
                def_input, top_module, build / "gds", timeout,
            )
        elif step == "signoff_timing":
            if not netlist or not sdc or not def_input:
                return PhysicalDesignResult(
                    success=False,
                    log="Signoff timing requires netlist, SDC, and DEF",
                )
            return self._run_signoff_timing_step(
                str(netlist), str(sdc),
                lib_path, tech_lef, cell_lef,
                str(def_input), build / "signoff", timeout,
            )
        else:
            return PhysicalDesignResult(
                success=False, log=f"Unknown step: {step_name}",
            )

    # ------------------------------------------------------------------
    # Get results summary
    # ------------------------------------------------------------------

    def get_results(self) -> dict[str, Any]:
        """Return a summary dict of the last flow run (from build artifacts)."""
        build = self._build_dir
        results: dict[str, Any] = {
            "area_um2": 0.0,
            "utilization_pct": 0.0,
            "wirelength_um": 0.0,
            "drc_violations": 0,
            "wns": 0.0,
            "tns": 0.0,
            "power_mw": 0.0,
        }

        # Parse from reports if they exist
        report_dir = build / "reports"
        for rpt_file in report_dir.glob("*.rpt") if report_dir.exists() else []:
            text = rpt_file.read_text(errors="replace")
            if a := _parse_area(text):
                results["area_um2"] = a
            if u := _parse_utilization(text):
                results["utilization_pct"] = u
            if w := _parse_wirelength(text):
                results["wirelength_um"] = w
            if d := _parse_drc_count(text):
                results["drc_violations"] = d
            if wns := _parse_wns(text):
                results["wns"] = wns
            if tns := _parse_tns(text):
                results["tns"] = tns
            if pwr := _parse_power(text):
                results["power_mw"] = pwr

        return results

    # ------------------------------------------------------------------
    # Internal: Synthesis step
    # ------------------------------------------------------------------

    def _run_synthesis_step(
        self,
        sources: Sequence[str | PathLike[str]],
        top_module: str,
        liberty: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Run Yosys synthesis to produce gate-level netlist."""
        self._emit_step(FlowStep.SYNTHESIS, "Starting Yosys synthesis...")
        out_dir.mkdir(parents=True, exist_ok=True)

        # Build Yosys script
        lines: list[str] = []
        for src in sources:
            p = Path(src)
            if p.suffix in (".sv", ".svh"):
                lines.append(f"read_verilog -sv {p}")
            elif p.suffix in (".vhd", ".vhdl"):
                lines.append(f"read_vhdl {p}")
            else:
                lines.append(f"read_verilog {p}")

        lines.extend([
            f"hierarchy -top {top_module} -check",
            "proc; opt; memory; opt; fsm; opt",
            "techmap; opt",
        ])

        if liberty:
            lines.extend([
                f"dfflibmap -liberty {liberty}",
                f"abc -liberty {liberty}",
            ])

        lines.extend([
            "opt_clean",
            f"write_verilog {out_dir / 'netlist.v'}",
            f"write_json {out_dir / 'netlist.json'}",
        ])

        if liberty:
            lines.append(f"stat -liberty {liberty}")
        else:
            lines.append("stat")

        script = "\n".join(lines) + "\n"
        script_path = out_dir / "synthesis.ys"
        script_path.write_text(script)

        start = time.monotonic()
        result = self._yosys.run_script(
            str(script_path),
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        self._emit_lines(combined)

        success = result.ok and (out_dir / "netlist.v").exists()
        self._emit_step(
            FlowStep.SYNTHESIS,
            f"{'Completed' if success else 'FAILED'} in {elapsed:.1f}s",
        )

        return PhysicalDesignResult(
            success=success,
            area_um2=_parse_area(combined),
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Internal: Floorplan step
    # ------------------------------------------------------------------

    def _run_floorplan_step(
        self,
        netlist: str | PathLike[str],
        sdc: str,
        top_module: str,
        die_area: tuple[float, float, float, float] | None,
        core_utilization: float,
        liberty: str,
        tech_lef: str,
        cell_lef: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Generate and run the floorplan stage."""
        self._emit_step(FlowStep.FLOORPLAN, "Generating floorplan...")
        out_dir.mkdir(parents=True, exist_ok=True)

        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False, log=f"Unsupported PDK: {self._pdk_name}",
            )

        # Generate floorplan configuration
        if die_area:
            fp_config = FloorplanConfig(
                die_area=die_area,
                core_area=(
                    die_area[0] + 50, die_area[1] + 50,
                    die_area[2] - 50, die_area[3] - 50,
                ),
                site_name=cfg.site,
                tracks_config=self._floorplan_gen.generate_tracks_config(),
            )
        else:
            fp_config = self._floorplan_gen.auto_size(
                gate_count=10000,
                utilization_target=core_utilization,
            )

        output_def = out_dir / "floorplan.def"
        int(core_utilization * 100)

        # Build floorplan TCL
        da = " ".join(f"{v:.3f}" for v in fp_config.die_area)
        ca = " ".join(f"{v:.3f}" for v in fp_config.core_area)

        tcl_lines: list[str] = [
            f"# OpenForge Floorplan -- {self._pdk_name}",
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {liberty}",
            f"read_verilog {netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
            "",
            f"initialize_floorplan -die_area {{{da}}} -core_area {{{ca}}} -site {cfg.site}",
            "make_tracks",
            f"place_pins -hor_layer {cfg.hor_layer} -ver_layer {cfg.ver_layer}",
            "",
            f"write_def {output_def}",
            "report_design_area",
            "exit",
        ]

        return self._run_openroad_tcl(
            tcl_lines, out_dir, "floorplan", output_def, timeout,
        )

    # ------------------------------------------------------------------
    # Internal: Full P&R script
    # ------------------------------------------------------------------

    def _run_pnr_script(
        self,
        netlist: str | PathLike[str],
        sdc: str,
        top_module: str,
        die_area: tuple[float, float, float, float] | None,
        core_utilization: float,
        liberty: str,
        tech_lef: str,
        cell_lef: str,
        build: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Generate and run the complete P&R TCL script through OpenROAD."""
        self._emit_step(FlowStep.GLOBAL_PLACEMENT, "Running full P&R flow...")

        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False, log=f"Unsupported PDK: {self._pdk_name}",
            )

        # Compute floorplan
        if die_area:
            fp_config = FloorplanConfig(
                die_area=die_area,
                core_area=(
                    die_area[0] + 50, die_area[1] + 50,
                    die_area[2] - 50, die_area[3] - 50,
                ),
                site_name=cfg.site,
                tracks_config=self._floorplan_gen.generate_tracks_config(),
            )
        else:
            fp_config = self._floorplan_gen.auto_size(
                gate_count=10000,
                utilization_target=core_utilization,
            )

        da = " ".join(f"{v:.3f}" for v in fp_config.die_area)
        ca = " ".join(f"{v:.3f}" for v in fp_config.core_area)
        int(core_utilization * 100)
        density = min(0.9, core_utilization + 0.2)

        output_def = build / "routing" / "routed.def"
        output_netlist = build / "routing" / "routed.v"
        drc_report = build / "reports" / "drc_route.rpt"
        maze_log = build / "reports" / "maze_route.log"

        # Generate PDN TCL
        pdn_tcl = self._pdn_gen.generate_pdn(fp_config.die_area, ["met1", "met4"])

        tcl_lines: list[str] = [
            f"# OpenForge RTL-to-GDSII P&R Flow -- {self._pdk_name}",
            "# Auto-generated by OpenLaneRunner",
            "",
            "# ---- Read technology ----",
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {liberty}",
            "",
            "# ---- Read design ----",
            f"read_verilog {netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
            "",
            "# ---- Floorplan ----",
            f"initialize_floorplan -die_area {{{da}}} -core_area {{{ca}}} -site {cfg.site}",
            "",
            "# ---- Track and pin assignment ----",
            "make_tracks",
            f"place_pins -hor_layer {cfg.hor_layer} -ver_layer {cfg.ver_layer}",
            "",
            "# ---- Power Distribution Network ----",
            *pdn_tcl.splitlines(),
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
            "# ---- Fill insertion ----",
            "filler_placement sky130_fd_sc_hd__fill_*" if self._pdk_name == "sky130"
            else "# filler_placement (PDK-specific)",
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

        return self._run_openroad_tcl(
            tcl_lines, build / "routing", "pnr_flow", output_def, timeout,
        )

    # ------------------------------------------------------------------
    # Internal: CTS step (standalone)
    # ------------------------------------------------------------------

    def _run_cts_step(
        self,
        def_input: str | PathLike[str],
        liberty: str,
        tech_lef: str,
        cell_lef: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        self._emit_step(FlowStep.CTS, "Running CTS...")
        out_dir.mkdir(parents=True, exist_ok=True)

        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False, log=f"Unsupported PDK: {self._pdk_name}",
            )

        output_def = out_dir / "cts.def"
        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {liberty}",
            f"read_def {def_input}",
            f"clock_tree_synthesis -buf_list {{{cfg.clk_buf_list}}} -root_buf {cfg.root_buf}",
            "estimate_parasitics -placement",
            "repair_timing",
            f"write_def {output_def}",
            "exit",
        ]

        return self._run_openroad_tcl(
            tcl_lines, out_dir, "cts", output_def, timeout,
        )

    # ------------------------------------------------------------------
    # Internal: Routing step (standalone)
    # ------------------------------------------------------------------

    def _run_routing_step(
        self,
        def_input: str | PathLike[str],
        liberty: str,
        tech_lef: str,
        cell_lef: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        self._emit_step(FlowStep.GLOBAL_ROUTE, "Running routing...")
        out_dir.mkdir(parents=True, exist_ok=True)

        cfg = self._pdk_cfg
        if cfg is None:
            return PhysicalDesignResult(
                success=False, log=f"Unsupported PDK: {self._pdk_name}",
            )

        output_def = out_dir / "routed.def"
        drc_report = out_dir / "drc_report.rpt"
        maze_log = out_dir / "maze_route.log"

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {liberty}",
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

        return self._run_openroad_tcl(
            tcl_lines, out_dir, "routing", output_def, timeout,
        )

    # ------------------------------------------------------------------
    # Internal: DRC step (Magic)
    # ------------------------------------------------------------------

    def _run_drc_step(
        self,
        def_path: str | PathLike[str],
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Run DRC using Magic."""
        self._emit_step(FlowStep.DRC, "Running DRC via Magic...")
        out_dir.mkdir(parents=True, exist_ok=True)

        tech_file = self._resolve_tech_file()
        drc_report = out_dir / "drc_report.txt"

        # Generate Magic DRC script
        tcl_lines = [
            f"gds read {def_path}",
            "load $::env(DESIGN_NAME) -dereference",
            "select top cell",
            "drc check",
            "drc catchup",
            f"set fout [open {drc_report} w]",
            "set drc_count [drc listall why]",
            "puts $fout $drc_count",
            "close $fout",
            'puts "DRC violations: [llength $drc_count]"',
            "quit -noprompt",
        ]

        tcl_content = "\n".join(tcl_lines) + "\n"
        tcl_path = out_dir / "run_drc.tcl"
        tcl_path.write_text(tcl_content)

        start = time.monotonic()
        result = self._magic.run_tcl(
            tcl_path, tech_file=tech_file,
            cwd=str(self._project_path), timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        self._emit_lines(combined)
        drc_count = _parse_drc_count(combined)

        self._emit_step(
            FlowStep.DRC,
            f"{'DRC Clean' if drc_count == 0 else f'{drc_count} violations'} "
            f"({elapsed:.1f}s)",
        )

        return PhysicalDesignResult(
            success=result.ok,
            drc_violations=drc_count,
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Internal: LVS step (Netgen)
    # ------------------------------------------------------------------

    def _run_lvs_step(
        self,
        def_path: str | PathLike[str],
        netlist_path: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Run LVS using Netgen."""
        self._emit_step(FlowStep.LVS, "Running LVS via Netgen...")
        out_dir.mkdir(parents=True, exist_ok=True)

        setup_file = self._resolve_netgen_setup()
        lvs_report = out_dir / "lvs_report.txt"

        # First extract SPICE from layout using Magic
        spice_path = out_dir / "extracted.spice"
        extract_tcl = [
            f"gds read {def_path}",
            "load $::env(DESIGN_NAME) -dereference",
            "select top cell",
            "extract all",
            "ext2spice lvs",
            f"ext2spice -o {spice_path}",
            "quit -noprompt",
        ]
        extract_tcl_path = out_dir / "extract.tcl"
        extract_tcl_path.write_text("\n".join(extract_tcl) + "\n")

        tech_file = self._resolve_tech_file()
        self._magic.run_tcl(
            extract_tcl_path, tech_file=tech_file,
            cwd=str(self._project_path), timeout=timeout,
        )

        # Run Netgen LVS
        start = time.monotonic()
        result = self._netgen.run_lvs(
            str(spice_path), netlist_path,
            setup_file=setup_file,
            output=str(lvs_report),
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        self._emit_lines(combined)
        match = self._netgen.parse_result(result)

        self._emit_step(
            FlowStep.LVS,
            f"{'LVS Clean' if match else 'LVS MISMATCH'} ({elapsed:.1f}s)",
        )

        return PhysicalDesignResult(
            success=match,
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Internal: GDS Export (Magic / KLayout)
    # ------------------------------------------------------------------

    def _run_gds_export_step(
        self,
        def_path: str | PathLike[str],
        top_module: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Export final GDSII using Magic, with KLayout as fallback."""
        self._emit_step(FlowStep.GDS_EXPORT, "Generating GDSII...")
        out_dir.mkdir(parents=True, exist_ok=True)

        gds_path = out_dir / f"{top_module}.gds"
        tech_file = self._resolve_tech_file()

        # Magic GDS write script
        tcl_lines = [
            f"gds read {def_path}",
            "load $::env(DESIGN_NAME) -dereference" if False else "# DEF-based export",
            f"def read {def_path}",
            "select top cell",
            f"gds write {gds_path}",
            "quit -noprompt",
        ]

        tcl_path = out_dir / "gds_export.tcl"
        tcl_path.write_text("\n".join(tcl_lines) + "\n")

        start = time.monotonic()
        result = self._magic.run_tcl(
            tcl_path, tech_file=tech_file,
            cwd=str(self._project_path), timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        self._emit_lines(combined)

        actual_gds = str(gds_path) if gds_path.exists() else ""
        self._emit_step(
            FlowStep.GDS_EXPORT,
            f"{'Exported' if actual_gds else 'Export failed'}: {gds_path.name} "
            f"({elapsed:.1f}s)",
        )

        return PhysicalDesignResult(
            success=result.ok or bool(actual_gds),
            gds_path=actual_gds,
            log=combined,
            duration=elapsed,
        )

    # ------------------------------------------------------------------
    # Internal: Signoff Timing (OpenSTA via OpenROAD)
    # ------------------------------------------------------------------

    def _run_signoff_timing_step(
        self,
        netlist: str,
        sdc: str,
        liberty: str,
        tech_lef: str,
        cell_lef: str,
        def_path: str,
        out_dir: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Run signoff timing analysis through OpenROAD/OpenSTA."""
        self._emit_step(FlowStep.SIGNOFF_TIMING, "Running signoff STA...")
        out_dir.mkdir(parents=True, exist_ok=True)

        timing_report = out_dir / "timing_signoff.rpt"

        tcl_lines: list[str] = [
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {liberty}",
            f"read_def {def_path}",
            f"read_sdc {sdc}",
            "",
            "# Signoff timing analysis",
            "estimate_parasitics -global_routing",
            f"report_checks -path_delay max -format full_clock_expanded > {timing_report}",
            "report_checks -path_delay min",
            "report_wns",
            "report_tns",
            "report_power",
            "",
            "exit",
        ]

        return self._run_openroad_tcl(
            tcl_lines, out_dir, "signoff_timing",
            out_dir / "signoff.def",  # dummy DEF
            timeout,
        )

    # ------------------------------------------------------------------
    # Internal: OpenROAD TCL execution helper
    # ------------------------------------------------------------------

    def _run_openroad_tcl(
        self,
        tcl_lines: list[str],
        out_dir: Path,
        stage_name: str,
        output_def: Path,
        timeout: float | None,
    ) -> PhysicalDesignResult:
        """Write TCL script, execute in OpenROAD, parse results."""
        tcl_content = "\n".join(tcl_lines) + "\n"
        tcl_path = out_dir / f"{stage_name}.tcl"
        tcl_path.write_text(tcl_content)

        # Always generate the script even if OpenROAD is not installed
        if not self._openroad.check_installed():
            self._emit(
                f"OpenROAD not found. TCL script saved to: {tcl_path}\n"
                f"Run manually: openroad -exit {tcl_path}"
            )
            return PhysicalDesignResult(
                success=False,
                def_path=str(output_def),
                log=f"OpenROAD not installed. Script saved: {tcl_path}",
            )

        start = time.monotonic()
        result = self._openroad.run_tcl(
            tcl_path,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        combined = result.stdout + result.stderr
        self._emit_lines(combined)

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

    # ------------------------------------------------------------------
    # Internal: Helpers
    # ------------------------------------------------------------------

    def _emit_lines(self, text: str) -> None:
        """Emit each line of output through the callback."""
        if self._on_output:
            for line in text.splitlines():
                self._on_output(line)

    def _assemble_summary(self, result: OpenLaneResult) -> str:
        """Build a human-readable summary of the flow results."""
        lines = [
            "=" * 60,
            "  OpenForge RTL-to-GDSII Flow Summary",
            "=" * 60,
            f"  PDK:           {self._pdk_name}",
            f"  Steps run:     {len(result.completed_steps)}",
            f"  GDS output:    {result.gds_path or 'N/A'}",
            f"  DEF output:    {result.def_path or 'N/A'}",
            "",
            "  Design Metrics:",
            f"    Area:          {result.area_um2:,.1f} um^2",
            f"    Utilization:   {result.utilization_pct:.1f}%",
            f"    Wirelength:    {result.wirelength_um:,.0f} um",
            f"    DRC:           {result.drc_violations} violations",
            f"    LVS:           {'MATCH' if result.lvs_match else 'MISMATCH'}",
            f"    WNS:           {result.wns:.3f} ns",
            f"    TNS:           {result.tns:.3f} ns",
            f"    Power:         {result.power_mw:.2f} mW",
            "",
            "  Step Durations:",
        ]
        for step, dur in result.step_durations.items():
            lines.append(f"    {step:<20s} {dur:>8.1f}s")
        lines.append("=" * 60)
        return "\n".join(lines)
