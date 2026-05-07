"""End-to-end RTL-to-GDS flow orchestrator.

Chains Yosys synthesis -> OpenROAD (floorplan, placement, CTS, routing, fill)
-> STA -> Magic DRC -> Netgen LVS -> GDS export in a single
:class:`RunGraph` executed by the :class:`RunEngine`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from openforge.runner.engine import RunEngine, RunGraph, RunStage, RunStatus

# ---------------------------------------------------------------------------
# Tool resolution layer
# ---------------------------------------------------------------------------
#
# OpenForge tries tools in this order:
#   1. Native binary on PATH (fastest, preferred)
#   2. Docker (if available + image tag set)
#   3. WSL (if on Windows + WSL detected, last resort)
# The chosen mechanism is recorded so failed flows can report "yosys not
# found anywhere" with actionable next steps.
#
# Set OPENFORGE_DOCKER_IMAGE to use a specific image (default: openforge-eda).
# Set OPENFORGE_PREFER_DOCKER=1 to skip native PATH and go straight to Docker.

_NATIVE_TOOL_NAMES = {
    "yosys", "verible-verilog-lint", "openroad", "magic", "netgen",
    "ngspice", "verilator", "iverilog", "klayout", "openfpgaloader",
    "icepack", "iceprog", "nextpnr-ice40", "nextpnr-ecp5", "sta",
}

# Per-platform Windows binary fallbacks (e.g. yosys.exe)
_WIN_EXTS = (".exe", ".bat", ".cmd")


def _has_native(tool: str) -> bool:
    """Check whether *tool* is on the system PATH."""
    if shutil.which(tool):
        return True
    # On Windows also try .exe suffix etc.
    if os.name == "nt":
        for ext in _WIN_EXTS:
            if shutil.which(tool + ext):
                return True
    return False


def _has_docker(image: str | None = None) -> bool:
    """Check whether docker is available and the OpenForge image is built."""
    if shutil.which("docker") is None:
        return False
    img = image or os.environ.get("OPENFORGE_DOCKER_IMAGE", "openforge-eda")
    try:
        out = subprocess.run(
            ["docker", "images", "-q", img],
            capture_output=True, text=True, timeout=10,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def _has_wsl() -> bool:
    """Check whether WSL is available (Windows only)."""
    if os.name != "nt":
        return False
    return shutil.which("wsl") is not None


def _to_wsl_path(p: str) -> str:
    """Convert a Windows path like ``H:\\openforge\\foo`` to ``/mnt/h/openforge/foo``."""
    s = str(p)
    if os.name == "nt" and len(s) > 1 and s[1] == ":":
        s = "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s.replace("\\", "/")


_WIN_PATH_RE = None  # lazy compile


def _translate_args_for_wsl(args: list[str]) -> list[str]:
    """Rewrite each argument so Windows paths (anywhere in the string)
    become /mnt/<drive>/... paths.

    This handles three cases:
      - standalone path arg: ``H:\\foo\\bar`` -> ``/mnt/h/foo/bar``
      - path embedded in a script string: ``yosys -p "write_json H:\\foo"``
        -> ``yosys -p "write_json /mnt/h/foo"``
      - already-Linux paths: passed through unchanged
    """
    if os.name != "nt":
        return list(args)
    import re

    global _WIN_PATH_RE
    if _WIN_PATH_RE is None:
        # Match a Windows path: drive letter, colon, then path chars (no spaces)
        _WIN_PATH_RE = re.compile(r"([A-Za-z]):([\\/][^\s'\"]+)")

    def _replace(m: "re.Match[str]") -> str:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return f"/mnt/{drive}{rest}"

    return [_WIN_PATH_RE.sub(_replace, a) for a in args]


def resolve_command(
    cmd: list[str],
    *,
    cwd: str | None = None,
    project_dir: Path | None = None,
) -> tuple[list[str], str]:
    """Wrap a tool command for the best available execution backend.

    Returns ``(wrapped_command, mechanism)`` where mechanism is one of
    ``native``, ``docker``, ``wsl``, or ``missing``. ``missing`` means no
    backend can run this tool — the caller should mark the stage failed
    with a clear "tool not found anywhere" error.
    """
    if not cmd:
        return cmd, "missing"
    tool = Path(cmd[0]).name.lower()

    prefer_docker = os.environ.get("OPENFORGE_PREFER_DOCKER", "").lower() in ("1", "true", "yes")

    # 1. Native (unless overridden)
    if not prefer_docker and _has_native(cmd[0]):
        return cmd, "native"

    # 2. Docker — mount the project dir as /workspace, run the tool there
    image = os.environ.get("OPENFORGE_DOCKER_IMAGE", "openforge-eda")
    if _has_docker(image):
        mount = (project_dir or Path(cwd or ".")).resolve()
        wrapped = [
            "docker", "run", "--rm",
            "-v", f"{mount}:/workspace",
            "-w", "/workspace",
            "--entrypoint", cmd[0],
            image,
            *cmd[1:],
        ]
        return wrapped, "docker"

    # 3. WSL — last resort on Windows for Linux-only tools.
    # Translate Windows path args to /mnt/<drive>/... so the Linux tool
    # can actually find the files.
    if _has_wsl() and tool in _NATIVE_TOOL_NAMES:
        # Verify the tool exists in WSL — if not, treat as missing so the
        # engine fails fast with a clear message instead of "no such file".
        try:
            check = subprocess.run(
                ["wsl", "-e", "bash", "-c", f"command -v {cmd[0]}"],
                capture_output=True, text=True, timeout=10,
            )
            if check.returncode != 0 or not check.stdout.strip():
                return cmd, "missing"
        except Exception:
            return cmd, "missing"
        translated = _translate_args_for_wsl(cmd[1:])
        wrapped = ["wsl", "-e", cmd[0], *translated]
        return wrapped, "wsl"

    return cmd, "missing"


def detect_tool_status() -> dict[str, str]:
    """Report which mechanism is available for each known tool."""
    status: dict[str, str] = {}
    has_dock = _has_docker()
    has_wsl_ = _has_wsl()
    for t in sorted(_NATIVE_TOOL_NAMES):
        if _has_native(t):
            status[t] = "native"
        elif has_dock:
            status[t] = "docker"
        elif has_wsl_:
            status[t] = "wsl"
        else:
            status[t] = "missing"
    return status

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class FullFlowConfig(BaseModel):
    """Configuration for a complete RTL-to-GDS flow."""

    top_module: str
    rtl_files: list[str]
    sdc_file: str
    pdk: str = "sky130A"
    std_cell_lib: str = "sky130_fd_sc_hd"
    target_freq_mhz: float = 100.0
    core_utilization: float = 50.0
    output_dir: str = "build"
    skip_lvs: bool = False
    skip_drc: bool = False


# ---------------------------------------------------------------------------
# Stage / result models
# ---------------------------------------------------------------------------


class FlowStageStatus(BaseModel):
    """Status snapshot of a single flow stage."""

    stage: str
    status: str = "pending"  # pending | running | success | failed | skipped
    runtime_s: float = 0.0
    log_path: str = ""
    artifacts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class FullFlowResult(BaseModel):
    """Result of a complete flow run."""

    config: FullFlowConfig
    stages: list[FlowStageStatus] = Field(default_factory=list)
    overall_status: str = "pending"
    gds_path: str | None = None
    total_runtime_s: float = 0.0


# ---------------------------------------------------------------------------
# Stage IDs (canonical order)
# ---------------------------------------------------------------------------

STAGE_IDS: list[str] = [
    "lint",
    "synth",
    "floorplan",
    "placement",
    "cts",
    "routing",
    "fill",
    "sta",
    "drc",
    "lvs",
    "gds_export",
]

# Map stage IDs to human names
STAGE_NAMES: dict[str, str] = {
    "lint": "Lint",
    "synth": "Synthesis (Yosys)",
    "floorplan": "Floorplan",
    "placement": "Placement",
    "cts": "Clock Tree Synthesis",
    "routing": "Routing",
    "fill": "Metal Fill",
    "sta": "Static Timing Analysis",
    "drc": "DRC (Magic)",
    "lvs": "LVS (Netgen)",
    "gds_export": "GDS Export",
}


# ---------------------------------------------------------------------------
# TCL script generators
# ---------------------------------------------------------------------------


def _write_floorplan_tcl(out: Path, cfg: FullFlowConfig) -> str:
    """Write an OpenROAD floorplan TCL script. Returns the script path."""
    pdk_root = "$::env(PDK_ROOT)"
    lib = f"{pdk_root}/{cfg.pdk}/libs.ref/{cfg.std_cell_lib}"
    tech_lef = f"{lib}/techlef/{cfg.std_cell_lib}__nom.tlef"
    cell_lef = f"{lib}/lef/{cfg.std_cell_lib}.lef"
    liberty = f"{lib}/lib/{cfg.std_cell_lib}__tt_025C_1v80.lib"
    netlist = str(out.parent / "synth" / "netlist.v")
    sdc = cfg.sdc_file
    util = cfg.core_utilization

    tcl = f"""\
# OpenROAD floorplan script (auto-generated by OpenForge)
read_lef {tech_lef}
read_lef {cell_lef}
read_liberty {liberty}
read_verilog {netlist}
link_design {cfg.top_module}
read_sdc {sdc}
initialize_floorplan -utilization {util} -aspect_ratio 1.0 -site unithd
source $::env(OPENROAD_FLOW)/scripts/io_placement.tcl || true
global_placement -density 0.7
write_def floorplan.def
"""
    path = out / "floorplan" / "floorplan.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_placement_tcl(out: Path, cfg: FullFlowConfig) -> str:
    tcl = """\
# OpenROAD placement script
source ../floorplan/floorplan_env.tcl || true
read_def ../floorplan/floorplan.def
detailed_placement
write_def placed.def
report_design_area > placement_area.rpt
"""
    path = out / "placement" / "placement.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_cts_tcl(out: Path, cfg: FullFlowConfig) -> str:
    tcl = """\
# OpenROAD CTS script
read_def ../placement/placed.def
clock_tree_synthesis
write_def cts.def
"""
    path = out / "cts" / "cts.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_routing_tcl(out: Path, cfg: FullFlowConfig) -> str:
    tcl = """\
# OpenROAD routing script
read_def ../cts/cts.def
global_route
detailed_route
write_def routed.def
write_spef routed.spef
"""
    path = out / "routing" / "route.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_fill_tcl(out: Path, cfg: FullFlowConfig) -> str:
    tcl = """\
# OpenROAD metal fill script
read_def ../routing/routed.def
density_fill
write_def filled.def
"""
    path = out / "fill" / "fill.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_sta_tcl(out: Path, cfg: FullFlowConfig) -> str:
    pdk_root = "$::env(PDK_ROOT)"
    lib = f"{pdk_root}/{cfg.pdk}/libs.ref/{cfg.std_cell_lib}"
    liberty = f"{lib}/lib/{cfg.std_cell_lib}__tt_025C_1v80.lib"
    netlist = str(out.parent / "synth" / "netlist.v")
    sdc = cfg.sdc_file
    tcl = f"""\
# OpenSTA timing analysis script
read_liberty {liberty}
read_verilog {netlist}
link_design {cfg.top_module}
read_sdc {sdc}
report_checks -path_delay max > timing.rpt
report_checks -path_delay min >> timing.rpt
report_tns >> timing.rpt
report_wns >> timing.rpt
exit
"""
    path = out / "sta" / "sta.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_drc_script(out: Path, cfg: FullFlowConfig) -> str:
    """Write a Magic DRC Tcl script."""
    pdk_root = "$::env(PDK_ROOT)"
    tech = f"{pdk_root}/{cfg.pdk}/libs.tech/magic/{cfg.pdk}.tech"
    gds = str(out.parent / "gds_export" / f"{cfg.top_module}.gds")
    tcl = f"""\
# Magic DRC script
tech load {tech}
gds read {gds}
load {cfg.top_module}
select top cell
drc check
drc catchup
set drc_count [drc count total]
puts "DRC errors: $drc_count"
set fp [open drc.rpt w]
puts $fp "DRC Report for {cfg.top_module}"
puts $fp "Errors: $drc_count"
foreach {{msg}} [drc listall why] {{
    puts $fp $msg
}}
close $fp
quit -noprompt
"""
    path = out / "drc" / "drc_script.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_gds_export_tcl(out: Path, cfg: FullFlowConfig) -> str:
    """Write a Magic GDS export script."""
    pdk_root = "$::env(PDK_ROOT)"
    tech = f"{pdk_root}/{cfg.pdk}/libs.tech/magic/{cfg.pdk}.tech"
    filled_def = str(out.parent / "fill" / "filled.def")
    gds_out = f"{cfg.top_module}.gds"
    tcl = f"""\
# Magic GDS export script
tech load {tech}
def read {filled_def}
load {cfg.top_module}
select top cell
gds write {gds_out}
quit -noprompt
"""
    path = out / "gds_export" / "gds_export.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# FullFlowRunner
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, str], None]  # (stage_name, status)


class FullFlowRunner:
    """Orchestrates the complete RTL-to-GDS flow using the RunEngine."""

    def __init__(self, config: FullFlowConfig, work_dir: Path) -> None:
        self.config = config
        self.work_dir = Path(work_dir).resolve()
        self._out = self.work_dir / config.output_dir
        self._out.mkdir(parents=True, exist_ok=True)
        self._engine = RunEngine(self.work_dir)
        self._graph: RunGraph | None = None
        self._run_id: str | None = None

    # ── Graph construction ────────────────────────────────────────────

    def build_graph(self) -> RunGraph:
        """Build the DAG: lint -> synth -> floorplan -> place -> cts ->
        route -> fill -> sta -> drc -> lvs -> gds_export.

        Uses real tool commands.
        """
        g = RunGraph()
        cfg = self.config
        out = self._out

        # ── Lint ──────────────────────────────────────────────────────
        g.add_stage(
            RunStage(
                id="lint",
                name="Lint",
                tool="verible",
                command=["verible-verilog-lint", *cfg.rtl_files],
                cwd=str(self.work_dir),
                produces=["*.rpt", "*.log"],
            )
        )

        # ── Synthesis (Yosys) ─────────────────────────────────────────
        synth_dir = out / "synth"
        synth_dir.mkdir(parents=True, exist_ok=True)

        read_cmds = "; ".join(f"read_verilog {f}" for f in cfg.rtl_files)
        yosys_script = (
            f"{read_cmds}; synth -top {cfg.top_module} -flatten; "
            f"write_json {synth_dir}/netlist.json; "
            f"write_verilog -noattr {synth_dir}/netlist.v"
        )
        # NOTE: synth is INTENTIONALLY not dependent on lint. Lint is an
        # advisory check; if verible-verilog-lint isn't installed, the user
        # should still be able to synthesize.
        g.add_stage(
            RunStage(
                id="synth",
                name="Synthesis (Yosys)",
                tool="yosys",
                command=["yosys", "-p", yosys_script],
                cwd=str(self.work_dir),
                depends_on=[],
                produces=["netlist.json", "netlist.v"],
            )
        )

        # ── Floorplan (OpenROAD) ──────────────────────────────────────
        fp_tcl = _write_floorplan_tcl(out, cfg)
        fp_dir = out / "floorplan"
        fp_dir.mkdir(parents=True, exist_ok=True)
        g.add_stage(
            RunStage(
                id="floorplan",
                name="Floorplan",
                tool="openroad",
                command=["openroad", "-no_init", "-exit", fp_tcl],
                cwd=str(fp_dir),
                depends_on=["synth"],
                produces=["*.def", "*.rpt", "*.log"],
            )
        )

        # ── Placement (OpenROAD) ──────────────────────────────────────
        pl_tcl = _write_placement_tcl(out, cfg)
        pl_dir = out / "placement"
        pl_dir.mkdir(parents=True, exist_ok=True)
        g.add_stage(
            RunStage(
                id="placement",
                name="Placement",
                tool="openroad",
                command=["openroad", "-no_init", "-exit", pl_tcl],
                cwd=str(pl_dir),
                depends_on=["floorplan"],
                produces=["*.def", "*.rpt"],
            )
        )

        # ── CTS (OpenROAD) ────────────────────────────────────────────
        cts_tcl = _write_cts_tcl(out, cfg)
        cts_dir = out / "cts"
        cts_dir.mkdir(parents=True, exist_ok=True)
        g.add_stage(
            RunStage(
                id="cts",
                name="Clock Tree Synthesis",
                tool="openroad",
                command=["openroad", "-no_init", "-exit", cts_tcl],
                cwd=str(cts_dir),
                depends_on=["placement"],
                produces=["*.def", "*.rpt"],
            )
        )

        # ── Routing (OpenROAD) ────────────────────────────────────────
        rt_tcl = _write_routing_tcl(out, cfg)
        rt_dir = out / "routing"
        rt_dir.mkdir(parents=True, exist_ok=True)
        g.add_stage(
            RunStage(
                id="routing",
                name="Routing",
                tool="openroad",
                command=["openroad", "-no_init", "-exit", rt_tcl],
                cwd=str(rt_dir),
                depends_on=["cts"],
                produces=["*.def", "*.spef", "*.rpt"],
            )
        )

        # ── Metal Fill (OpenROAD) ─────────────────────────────────────
        fill_tcl = _write_fill_tcl(out, cfg)
        fill_dir = out / "fill"
        fill_dir.mkdir(parents=True, exist_ok=True)
        g.add_stage(
            RunStage(
                id="fill",
                name="Metal Fill",
                tool="openroad",
                command=["openroad", "-no_init", "-exit", fill_tcl],
                cwd=str(fill_dir),
                depends_on=["routing"],
                produces=["*.def"],
            )
        )

        # ── GDS Export (Magic) ────────────────────────────────────────
        gds_tcl = _write_gds_export_tcl(out, cfg)
        gds_dir = out / "gds_export"
        gds_dir.mkdir(parents=True, exist_ok=True)
        str(gds_dir / f"{cfg.top_module}.gds")
        g.add_stage(
            RunStage(
                id="gds_export",
                name="GDS Export",
                tool="magic",
                command=[
                    "magic",
                    "-dnull",
                    "-noconsole",
                    "-rcfile",
                    f"${{PDK_ROOT}}/{cfg.pdk}/libs.tech/magic/{cfg.pdk}.magicrc",
                    gds_tcl,
                ],
                cwd=str(gds_dir),
                depends_on=["fill"],
                produces=["*.gds", "*.gds.gz"],
            )
        )

        # ── STA (OpenSTA) ────────────────────────────────────────────
        sta_tcl = _write_sta_tcl(out, cfg)
        sta_dir = out / "sta"
        sta_dir.mkdir(parents=True, exist_ok=True)
        g.add_stage(
            RunStage(
                id="sta",
                name="Static Timing Analysis",
                tool="opensta",
                command=["sta", "-no_splash", "-exit", sta_tcl],
                cwd=str(sta_dir),
                depends_on=["fill"],
                produces=["*.rpt", "sta.log"],
            )
        )

        # ── DRC (Magic) ──────────────────────────────────────────────
        if not cfg.skip_drc:
            drc_tcl = _write_drc_script(out, cfg)
            drc_dir = out / "drc"
            drc_dir.mkdir(parents=True, exist_ok=True)
            g.add_stage(
                RunStage(
                    id="drc",
                    name="DRC (Magic)",
                    tool="magic",
                    command=[
                        "magic",
                        "-dnull",
                        "-noconsole",
                        "-rcfile",
                        f"${{PDK_ROOT}}/{cfg.pdk}/libs.tech/magic/{cfg.pdk}.magicrc",
                        drc_tcl,
                    ],
                    cwd=str(drc_dir),
                    depends_on=["gds_export"],
                    produces=["*.rpt", "drc.log"],
                )
            )

        # ── LVS (Netgen) ─────────────────────────────────────────────
        if not cfg.skip_lvs:
            lvs_dir = out / "lvs"
            lvs_dir.mkdir(parents=True, exist_ok=True)
            layout = str(out / "gds_export" / f"{cfg.top_module}.gds")
            netlist_v = str(out / "synth" / "netlist.v")
            setup_file = f"${{PDK_ROOT}}/{cfg.pdk}/libs.tech/netgen/{cfg.pdk}_setup.tcl"
            report = str(lvs_dir / "lvs.rpt")
            g.add_stage(
                RunStage(
                    id="lvs",
                    name="LVS (Netgen)",
                    tool="netgen",
                    command=[
                        "netgen",
                        "-batch",
                        "lvs",
                        f'"{layout} {cfg.top_module}"',
                        f'"{netlist_v} {cfg.top_module}"',
                        setup_file,
                        report,
                    ],
                    cwd=str(lvs_dir),
                    depends_on=["gds_export"],
                    produces=["*.rpt", "comp.out"],
                )
            )

        # Wrap every stage's command through the tool resolver. If a tool
        # is not available natively, route through Docker or WSL. If no
        # backend can run a tool, mark the command so the engine reports
        # a clear error (instead of WinError 2).
        self._tool_mechanisms: dict[str, str] = {}
        for stage in list(g._stages.values()):
            wrapped, mechanism = resolve_command(
                stage.command, cwd=stage.cwd, project_dir=self.work_dir,
            )
            stage.command = wrapped
            self._tool_mechanisms[stage.id] = mechanism

        self._graph = g
        return g

    def tool_status(self) -> dict[str, str]:
        """Return per-stage tool resolution mechanism after build_graph()."""
        return dict(getattr(self, "_tool_mechanisms", {}))

    # ── Execution ─────────────────────────────────────────────────────

    def run(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> FullFlowResult:
        """Execute the full flow graph via RunEngine.

        ``progress_callback(stage_name, status)`` is called at each
        stage transition (start / finish).
        """
        if self._graph is None:
            self.build_graph()
        assert self._graph is not None

        # Pre-flight: report any "missing" tools clearly before launching.
        # The engine will still attempt them and fail fast, but we annotate
        # the result so the user knows what to install.
        missing = [sid for sid, m in self._tool_mechanisms.items() if m == "missing"]
        if missing:
            tools_needed = sorted({
                Path(self._graph._stages[sid].command[0]).name
                for sid in missing
                if self._graph._stages[sid].command
            })
            print(
                f"[full_flow] WARNING: {len(missing)} stage(s) have no available "
                f"tool backend. Install one of: {', '.join(tools_needed)} natively, "
                f"or build the Docker image (cd installer && docker build -t openforge-eda .), "
                f"or enable WSL on Windows."
            )

        start_time = time.monotonic()

        # Wire callbacks
        if progress_callback is not None:

            def _on_start(_run_id: str, stage: RunStage) -> None:
                progress_callback(stage.id, "running")

            def _on_finish(_run_id: str, stage: RunStage) -> None:
                progress_callback(stage.id, stage.status.value)

            self._engine.on_stage_start = _on_start
            self._engine.on_stage_finish = _on_finish

        # Submit and wait
        self._run_id = self._engine.submit(self._graph)
        self._engine.wait(self._run_id)
        elapsed = time.monotonic() - start_time

        # Build result
        return self._build_result(elapsed)

    def run_from(self, stage: str) -> FullFlowResult:
        """Re-run from a specific stage (and all downstream)."""
        if self._run_id is None:
            raise RuntimeError("No previous run to resume from")

        start_time = time.monotonic()
        new_run_id = self._engine.rerun_from(self._run_id, stage)
        self._run_id = new_run_id
        self._engine.wait(self._run_id)
        elapsed = time.monotonic() - start_time
        return self._build_result(elapsed)

    def cancel(self) -> None:
        """Cancel the current run."""
        if self._run_id:
            self._engine.cancel(self._run_id)

    # ── Internal ──────────────────────────────────────────────────────

    def _build_result(self, elapsed: float) -> FullFlowResult:
        """Construct a FullFlowResult from the current graph state."""
        assert self._graph is not None
        stages: list[FlowStageStatus] = []
        any_failed = False

        for s in self._graph.stages():
            runtime = 0.0
            if s.started_at and s.finished_at:
                try:
                    from datetime import datetime

                    t0 = datetime.fromisoformat(s.started_at)
                    t1 = datetime.fromisoformat(s.finished_at)
                    runtime = (t1 - t0).total_seconds()
                except Exception:
                    pass

            errors: list[str] = []
            if s.status == RunStatus.FAILED:
                any_failed = True
                if s.log_path:
                    try:
                        log_tail = Path(s.log_path).read_text(encoding="utf-8")[-2000:]
                        errors.append(log_tail)
                    except Exception:
                        errors.append(f"stage {s.id} failed (exit code {s.exit_code})")

            stages.append(
                FlowStageStatus(
                    stage=s.id,
                    status=s.status.value,
                    runtime_s=round(runtime, 2),
                    log_path=s.log_path or "",
                    artifacts=[a.path for a in s.artifacts],
                    errors=errors,
                )
            )

        # Find GDS output
        gds_path: str | None = None
        gds_dir = self._out / "gds_export"
        if gds_dir.exists():
            for p in gds_dir.glob("*.gds"):
                gds_path = str(p)
                break

        overall = "failed" if any_failed else "success"
        if all(s.status == "pending" for s in stages):
            overall = "pending"

        return FullFlowResult(
            config=self.config,
            stages=stages,
            overall_status=overall,
            gds_path=gds_path,
            total_runtime_s=round(elapsed, 2),
        )

    @property
    def engine(self) -> RunEngine:
        """Access the underlying RunEngine."""
        return self._engine

    @property
    def graph(self) -> RunGraph | None:
        """Access the built RunGraph (None until build_graph called)."""
        return self._graph

    @property
    def run_id(self) -> str | None:
        """The current run ID, or None."""
        return self._run_id


__all__ = [
    "FullFlowConfig",
    "FullFlowResult",
    "FullFlowRunner",
    "FlowStageStatus",
    "STAGE_IDS",
    "STAGE_NAMES",
]
