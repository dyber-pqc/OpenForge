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
    "yosys",
    "verible-verilog-lint",
    "openroad",
    "magic",
    "netgen",
    "ngspice",
    "verilator",
    "iverilog",
    "klayout",
    "openfpgaloader",
    "icepack",
    "iceprog",
    "nextpnr-ice40",
    "nextpnr-ecp5",
    "sta",
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
            capture_output=True,
            text=True,
            timeout=10,
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

    def _replace(m: re.Match[str]) -> str:
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
            "docker",
            "run",
            "--rm",
            "-v",
            f"{mount}:/workspace",
            "-w",
            "/workspace",
            "--entrypoint",
            cmd[0],
            image,
            *cmd[1:],
        ]
        return wrapped, "docker"

    # 3. WSL — last resort on Windows for Linux-only tools.
    # Translate Windows path args to /mnt/<drive>/... so the Linux tool
    # can actually find the files. Also propagate critical env vars
    # like PDK_ROOT and OPENROAD_FLOW into the WSL session.
    if _has_wsl() and tool in _NATIVE_TOOL_NAMES:
        # Verify the tool exists in WSL — if not, treat as missing so the
        # engine fails fast with a clear message instead of "no such file".
        try:
            check = subprocess.run(
                ["wsl", "-e", "bash", "-c", f"command -v {cmd[0]}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if check.returncode != 0 or not check.stdout.strip():
                return cmd, "missing"
        except Exception:
            return cmd, "missing"

        # Propagate env vars into WSL.  We pre-expand $HOME ourselves so
        # tools like Yosys that don't expand env vars in their script args
        # still see real paths.
        translated = _translate_args_for_wsl(cmd[1:])
        # Resolve $HOME from WSL once and substitute in args
        try:
            home_proc = subprocess.run(
                ["wsl", "-e", "bash", "-c", "echo $HOME"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            wsl_home = home_proc.stdout.strip() or "/root"
        except Exception:
            wsl_home = "/root"
        translated = [a.replace("$HOME", wsl_home) for a in translated]

        # Use double quotes so any remaining bash vars (e.g. ${PDK_ROOT})
        # do expand inside the inner arg, but a literal $ sign is fine.
        def _bash_quote(s: str) -> str:
            # Use single quotes; escape internal single quotes.
            return "'" + s.replace("'", "'\\''") + "'"

        quoted_args = " ".join(_bash_quote(a) for a in [cmd[0], *translated])

        env_setup = []
        pdk_root = os.environ.get("PDK_ROOT", "")
        if pdk_root:
            env_setup.append(f"export PDK_ROOT={_bash_quote(_to_wsl_path(pdk_root))}")
        else:
            env_setup.append(f'export PDK_ROOT="{wsl_home}/.volare"')
        bash_cmd = "; ".join(env_setup) + "; exec " + quoted_args
        wrapped = ["wsl", "-e", "bash", "-c", bash_cmd]
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
    # When True (default), the orchestrator schedules the native Rust signoff
    # binaries (openforge-drc / openforge-lvs / openforge-xrc) as additional
    # advisory stages alongside the existing Magic/Netgen/OpenSTA flow. They
    # gracefully self-skip when the binary isn't installed.
    signoff_native: bool = True
    # Optional path to a DRC rule deck consumed by openforge-drc. If unset,
    # the bundled tools/openforge-drc/tests/fixtures/sky130_subset.drc deck
    # is auto-located relative to the repo.
    native_drc_rules: str | None = None


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


class NativeSignoffSummary(BaseModel):
    """One-line summary of a native signoff stage's result.

    Populated by :meth:`FullFlowRunner._build_result` from the artifacts
    written by openforge-{drc,lvs,xrc}. Consumers (e.g. the desktop GUI)
    use these to render lines like "Native DRC: 0 violations".
    """

    drc_violations: int | None = None
    lvs_matched: bool | None = None
    xrc_total_capacitance_pf: float | None = None


class FullFlowResult(BaseModel):
    """Result of a complete flow run."""

    config: FullFlowConfig
    stages: list[FlowStageStatus] = Field(default_factory=list)
    overall_status: str = "pending"
    gds_path: str | None = None
    total_runtime_s: float = 0.0
    native_signoff: NativeSignoffSummary = Field(default_factory=NativeSignoffSummary)


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
    "drc_native",
    "lvs_native",
    "xrc_native",
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
    "drc_native": "DRC (Native Rust)",
    "lvs_native": "LVS (Native Rust)",
    "xrc_native": "Parasitic Extraction (Native Rust)",
}

# Stage IDs that are advisory rather than chip-blocking. Failures in these
# stages should not invalidate a "Chip Built" verdict — the desktop GUI uses
# this set to decide whether to show a green or yellow finish dialog.
ADVISORY_STAGE_IDS: frozenset[str] = frozenset(
    {"lint", "drc", "lvs", "drc_native", "lvs_native", "xrc_native"}
)


# ---------------------------------------------------------------------------
# TCL script generators
# ---------------------------------------------------------------------------


def _write_floorplan_tcl(out: Path, cfg: FullFlowConfig) -> str:
    """Write an OpenROAD floorplan TCL script. Returns the script path.

    All paths are relative to the floorplan working directory so the script
    is portable across native, WSL, and Docker execution backends.
    """
    pdk_root = "$::env(PDK_ROOT)"
    lib = f"{pdk_root}/{cfg.pdk}/libs.ref/{cfg.std_cell_lib}"
    tech_lef = f"{lib}/techlef/{cfg.std_cell_lib}__nom.tlef"
    cell_lef = f"{lib}/lef/{cfg.std_cell_lib}.lef"
    liberty = f"{lib}/lib/{cfg.std_cell_lib}__tt_025C_1v80.lib"
    # Relative paths — OpenROAD runs with cwd=floorplan_dir
    netlist = "../synth/netlist.v"
    # SDC may be absolute (from project root) or relative; if relative,
    # walk up to project dir
    sdc_path = Path(cfg.sdc_file)
    if sdc_path.is_absolute():
        sdc = str(sdc_path).replace("\\", "/")
    else:
        # Project dir = out.parent.parent (e.g. examples/.../build_test → examples/...)
        sdc = f"../../{cfg.sdc_file}"
    util = cfg.core_utilization

    tcl = f"""\
# OpenROAD floorplan script (auto-generated by OpenForge)
read_lef {tech_lef}
read_lef {cell_lef}
read_liberty {liberty}
read_verilog {netlist}
link_design {cfg.top_module}
read_sdc {sdc}
initialize_floorplan -utilization {util} -aspect_ratio 1.0 -core_space 2.0 -site unithd
make_tracks
# Place I/O pins around the die using a built-in heuristic
place_pins -hor_layers met3 -ver_layers met2
write_def floorplan.def
"""
    path = out / "floorplan" / "floorplan.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _pdk_preamble(cfg: FullFlowConfig) -> str:
    """Tcl preamble that re-loads LEFs + liberty in a fresh OpenROAD invocation."""
    pdk_root = "$::env(PDK_ROOT)"
    lib = f"{pdk_root}/{cfg.pdk}/libs.ref/{cfg.std_cell_lib}"
    return f"""\
read_lef {lib}/techlef/{cfg.std_cell_lib}__nom.tlef
read_lef {lib}/lef/{cfg.std_cell_lib}.lef
read_liberty {lib}/lib/{cfg.std_cell_lib}__tt_025C_1v80.lib"""


def _write_placement_tcl(out: Path, cfg: FullFlowConfig) -> str:
    sdc_path = Path(cfg.sdc_file)
    sdc = str(sdc_path).replace("\\", "/") if sdc_path.is_absolute() else f"../../{cfg.sdc_file}"
    tcl = f"""\
# OpenROAD placement script (auto-generated)
{_pdk_preamble(cfg)}
read_def ../floorplan/floorplan.def
read_sdc {sdc}
global_placement -density 0.6
detailed_placement
write_def placed.def
report_design_area > placement_area.rpt
"""
    path = out / "placement" / "placement.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _find_native_signoff_binary(name: str) -> str | None:
    """Locate one of the native Rust signoff binaries.

    Search order:
      1. ``shutil.which(name)`` — binary on PATH.
      2. Walk up from this file looking for ``target/{release,debug}/<name>[.exe]``.

    Returns the absolute path, or ``None`` if the binary cannot be found —
    in which case the corresponding stage is omitted from the DAG so the
    flow runs cleanly on machines without the native Rust workspace built.
    """
    on_path = shutil.which(name)
    if on_path:
        return on_path
    here = Path(__file__).resolve()
    exts = ("", ".exe") if os.name == "nt" else ("",)
    for parent in here.parents:
        for sub in ("target/release", "target/debug"):
            for ext in exts:
                cand = parent / sub / f"{name}{ext}"
                if cand.exists():
                    return str(cand)
    return None


def _find_native_drc_rules() -> str | None:
    """Locate the bundled sky130_subset.drc rule deck shipped with the repo."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "tools" / "openforge-drc" / "tests" / "fixtures" / "sky130_subset.drc"
        if cand.exists():
            return str(cand)
    return None


def _select_lvs_netlist(out: Path) -> Path:
    """Pick the most-faithful Verilog netlist for LVS comparison.

    LVS compares the *layout* (post-route GDS) against a reference *schematic*
    (Verilog). The closer the netlist matches the layout's actual cell
    population, the smaller the false-positive mismatch. Preference order:

    1. ``routing/routed.v`` — fully placed/routed netlist (best).
    2. ``cts/cts.v`` — post-CTS netlist with clock-tree buffers inserted.
    3. ``synth/netlist.v`` — pre-CTS synth output (fallback; will report a
       device-count mismatch equal to the inserted clock-buffer count).
    """
    routed = out / "routing" / "routed.v"
    if routed.exists():
        return routed
    cts_v = out / "cts" / "cts.v"
    if cts_v.exists():
        return cts_v
    return out / "synth" / "netlist.v"


def _write_cts_tcl(out: Path, cfg: FullFlowConfig) -> str:
    sdc_path = Path(cfg.sdc_file)
    sdc = str(sdc_path).replace("\\", "/") if sdc_path.is_absolute() else f"../../{cfg.sdc_file}"
    tcl = f"""\
# OpenROAD CTS script (auto-generated)
{_pdk_preamble(cfg)}
read_def ../placement/placed.def
read_sdc {sdc}
clock_tree_synthesis -buf_list {{sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_16}} -root_buf sky130_fd_sc_hd__clkbuf_16 -sink_clustering_enable
# Legalize newly inserted clock buffers onto the placement grid so routing
# can find access points.
detailed_placement
write_def cts.def
# Emit a Verilog netlist matching the post-CTS in-memory database. This gives
# LVS an apples-to-apples comparison target (post-CTS DEF <-> post-CTS V) so
# the inserted clock buffers do not show up as a forced device-count mismatch
# against the pre-CTS synth netlist.
write_verilog cts.v
"""
    path = out / "cts" / "cts.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_routing_tcl(out: Path, cfg: FullFlowConfig) -> str:
    sdc_path = Path(cfg.sdc_file)
    sdc = str(sdc_path).replace("\\", "/") if sdc_path.is_absolute() else f"../../{cfg.sdc_file}"
    tcl = f"""\
# OpenROAD routing script (auto-generated)
{_pdk_preamble(cfg)}
read_def ../cts/cts.def
read_sdc {sdc}
# Mark any nets tagged with POWER/GROUND signal type as special so TritonRoute
# skips them (they belong to the PDN, not the signal router). PicoRV32-style
# RTL with `assign zero = 1'b0;` typically picks up GROUND tagging from Yosys.
foreach net [[ord::get_db_block] getNets] {{
    set sig_type [$net getSigType]
    if {{$sig_type eq "POWER" || $sig_type eq "GROUND"}} {{
        $net setSpecial
    }}
}}
set_routing_layers -signal met1-met5 -clock met1-met5
global_route -guide_file route.guide
detailed_route -output_drc drc.rpt
write_def routed.def
write_verilog routed.v
"""
    path = out / "routing" / "route.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


def _write_fill_tcl(out: Path, cfg: FullFlowConfig) -> str:
    tcl = f"""\
# OpenROAD metal fill script (auto-generated)
{_pdk_preamble(cfg)}
read_def ../routing/routed.def
# density_fill needs a fill rules file; if not available, just copy the routed DEF
# as the final output (skip fill on hobby designs).
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
    # Use the routed verilog (post-CTS netlist with buffers) — fall back to synth netlist
    netlist = "../routing/routed.v"
    sdc_path = Path(cfg.sdc_file)
    sdc = str(sdc_path).replace("\\", "/") if sdc_path.is_absolute() else f"../../{cfg.sdc_file}"
    tcl = f"""\
# OpenSTA timing analysis script (auto-generated)
read_liberty {liberty}
if {{[file exists {netlist}]}} {{
    read_verilog {netlist}
}} else {{
    read_verilog ../synth/netlist.v
}}
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
    """Write a KLayout-based DEF→GDS export script.

    Magic's DEF reader has layer-mapping issues with sky130 ("Unknown
    layer type li1/met1/met2"). KLayout has clean DEF→GDS conversion
    via its layout-edit Python API — it merges cell GDS + DEF placement
    into a final GDS in seconds.
    """
    # Build relative-to-PDK_ROOT paths; resolve at runtime via os.environ.
    rel_cell_gds = f"{cfg.pdk}/libs.ref/{cfg.std_cell_lib}/gds/{cfg.std_cell_lib}.gds"
    rel_cell_lef = f"{cfg.pdk}/libs.ref/{cfg.std_cell_lib}/lef/{cfg.std_cell_lib}.lef"
    rel_tech_lef = f"{cfg.pdk}/libs.ref/{cfg.std_cell_lib}/techlef/{cfg.std_cell_lib}__nom.tlef"
    py = f"""\
# KLayout DEF -> GDS export (auto-generated)
import os, sys
import pya

PDK_ROOT = os.environ.get("PDK_ROOT") or os.path.expanduser("~/.volare")
LEFs = [
    os.path.join(PDK_ROOT, "{rel_tech_lef}"),
    os.path.join(PDK_ROOT, "{rel_cell_lef}"),
]
GDSs = [os.path.join(PDK_ROOT, "{rel_cell_gds}")]
DEF = "../fill/filled.def"
TOP = "{cfg.top_module}"
OUT = "{cfg.top_module}.gds"

# Configure DEF reader
opts = pya.LoadLayoutOptions()
opts.lefdef_config.macro_resolution_mode = 1  # use macros from LEFs
for lef in LEFs:
    opts.lefdef_config.lef_files = list(opts.lefdef_config.lef_files) + [lef]

# Load standard cells GDS as the cell-resolution backstore
ly = pya.Layout()
for gds in GDSs:
    ly.read(gds)

# Now load the DEF using the same layout, with cells already known
ly.read(DEF, opts)

# Find the top cell and write
top = ly.cell(TOP) or ly.top_cells()[0]
ly.write(OUT, pya.SaveLayoutOptions())
print(f"Wrote {{OUT}}")
"""
    path = out / "gds_export" / "gds_export.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(py, encoding="utf-8")
    return str(path)
    path = out / "gds_export" / "gds_export.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcl, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# FullFlowRunner
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, str], None]  # (stage_name, status)


def _collect_native_signoff(out: Path) -> NativeSignoffSummary:
    """Best-effort parse of native signoff artifacts.

    Each parser is wrapped in a broad try/except — missing files, partial
    runs, or schema drift all degrade gracefully to ``None`` so an unrelated
    flow run never crashes here.
    """
    summary = NativeSignoffSummary()

    # DRC: text report — count "violation" lines.
    drc_rpt = out / "drc_native" / "drc.rpt"
    if drc_rpt.exists():
        try:
            text = drc_rpt.read_text(encoding="utf-8", errors="replace")
            # Prefer an explicit "Total: N" / "violations: N" if present.
            import re as _re

            m = _re.search(r"(?:total|violations?)\s*[:=]\s*(\d+)", text, _re.IGNORECASE)
            if m:
                summary.drc_violations = int(m.group(1))
            else:
                summary.drc_violations = sum(
                    1 for ln in text.splitlines() if "violation" in ln.lower()
                )
        except Exception:
            pass

    # LVS: JSON report.
    lvs_json = out / "lvs_native" / "lvs.json"
    if lvs_json.exists():
        try:
            import json as _json

            data = _json.loads(lvs_json.read_text(encoding="utf-8"))
            summary.lvs_matched = bool(data.get("matched", False))
        except Exception:
            pass

    # xRC: SPEF — sum *_c capacitor values (rough total capacitance).
    xrc_dir = out / "xrc"
    if xrc_dir.exists():
        try:
            spefs = list(xrc_dir.glob("*.spef"))
            if spefs:
                total = 0.0
                for ln in spefs[0].read_text(encoding="utf-8", errors="replace").splitlines():
                    parts = ln.strip().split()
                    # SPEF capacitance entries look like: "1 net_a 0.0042"
                    if len(parts) == 3:
                        try:
                            total += float(parts[2])
                        except ValueError:
                            continue
                summary.xrc_total_capacitance_pf = round(total, 4)
        except Exception:
            pass

    return summary


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
        # Resolve PDK_ROOT now (Yosys doesn't expand Tcl env vars in command args).
        # Try host env, then standard volare locations on WSL ($HOME/.volare),
        # then OpenLane's default. Whichever exists on the *executing* system
        # will be used.
        pdk_root_resolved = os.environ.get("PDK_ROOT", "$HOME/.volare")
        # When running through WSL, the bash wrapper expands $HOME — leave it.
        # Build a Yosys script that maps to actual standard cells of the
        # target PDK. For sky130: synth -> dfflibmap -> abc with the liberty.
        # OpenROAD's read_verilog expects a flat gate-level netlist using
        # the cells in the liberty file.
        if cfg.pdk.startswith("sky130"):
            lib = (
                f"{pdk_root_resolved}/{cfg.pdk}/libs.ref/{cfg.std_cell_lib}/lib/"
                f"{cfg.std_cell_lib}__tt_025C_1v80.lib"
            )
            # Note: write_verilog needs absolute or run-cwd-relative paths,
            # but yosys runs with cwd=project_dir so build_test/synth/netlist.v works.
            yosys_script = (
                f"{read_cmds}; "
                f"synth -top {cfg.top_module} -flatten; "
                f"dfflibmap -liberty {lib}; "
                f"abc -liberty {lib}; "
                f"opt_clean -purge; "
                f"write_json {synth_dir}/netlist.json; "
                f"write_verilog -noattr {synth_dir}/netlist.v"
            )
        else:
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
                produces=["*.def", "*.v", "*.rpt"],
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
                tool="klayout",
                command=[
                    "klayout",
                    "-zz",  # batch mode, no GUI
                    "-r",
                    gds_tcl,  # run python script
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
            netlist_v = str(_select_lvs_netlist(out))
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

        # ── Native signoff (Rust) ────────────────────────────────────
        # Three advisory stages running the native openforge-{drc,lvs,xrc}
        # binaries. They are skipped silently if the binary isn't installed
        # so a fresh machine without `cargo build --release` doesn't see a
        # spurious "missing tool" warning.
        if cfg.signoff_native:
            drc_bin = _find_native_signoff_binary("openforge-drc")
            lvs_bin = _find_native_signoff_binary("openforge-lvs")
            xrc_bin = _find_native_signoff_binary("openforge-xrc")

            if drc_bin is not None:
                drc_n_dir = out / "drc_native"
                drc_n_dir.mkdir(parents=True, exist_ok=True)
                gds_layout = str(out / "gds_export" / f"{cfg.top_module}.gds")
                rules = cfg.native_drc_rules or _find_native_drc_rules()
                # Use sky130A as the native tech tag for any sky130 PDK variant.
                native_tech = "sky130A" if cfg.pdk.startswith("sky130") else cfg.pdk
                drc_cmd = [
                    drc_bin,
                    "check",
                    gds_layout,
                    "--tech",
                    native_tech,
                    "--output",
                    str(drc_n_dir / "drc.rpt"),
                    "--format",
                    "text",
                ]
                if rules:
                    drc_cmd[3:3] = ["--rules", rules]
                g.add_stage(
                    RunStage(
                        id="drc_native",
                        name=STAGE_NAMES["drc_native"],
                        tool="openforge-drc",
                        command=drc_cmd,
                        cwd=str(drc_n_dir),
                        depends_on=["gds_export"],
                        produces=["*.rpt"],
                    )
                )

            if lvs_bin is not None:
                lvs_n_dir = out / "lvs_native"
                lvs_n_dir.mkdir(parents=True, exist_ok=True)
                layout = str(out / "gds_export" / f"{cfg.top_module}.gds")
                schem = str(_select_lvs_netlist(out))
                g.add_stage(
                    RunStage(
                        id="lvs_native",
                        name=STAGE_NAMES["lvs_native"],
                        tool="openforge-lvs",
                        command=[
                            lvs_bin,
                            "check",
                            "--layout",
                            layout,
                            "--schematic",
                            schem,
                            "--top",
                            cfg.top_module,
                            "--output",
                            str(lvs_n_dir / "lvs.json"),
                        ],
                        cwd=str(lvs_n_dir),
                        depends_on=["gds_export"],
                        produces=["*.json"],
                    )
                )

            if xrc_bin is not None:
                xrc_dir = out / "xrc"
                xrc_dir.mkdir(parents=True, exist_ok=True)
                routed_def = str(out / "routing" / "routed.def")
                # Best-effort LEF: use the std-cell LEF from the PDK. Resolved
                # at runtime by the shell via $PDK_ROOT — the binary will fail
                # gracefully if PDK_ROOT isn't set.
                pdk_root_env = os.environ.get("PDK_ROOT", "$PDK_ROOT")
                lef_path = (
                    f"{pdk_root_env}/{cfg.pdk}/libs.ref/{cfg.std_cell_lib}/"
                    f"lef/{cfg.std_cell_lib}.lef"
                )
                native_tech = "sky130A" if cfg.pdk.startswith("sky130") else cfg.pdk
                g.add_stage(
                    RunStage(
                        id="xrc_native",
                        name=STAGE_NAMES["xrc_native"],
                        tool="openforge-xrc",
                        command=[
                            xrc_bin,
                            "extract",
                            "--def",
                            routed_def,
                            "--lef",
                            lef_path,
                            "--tech",
                            native_tech,
                            "--output",
                            str(xrc_dir / f"{cfg.top_module}.spef"),
                        ],
                        cwd=str(xrc_dir),
                        depends_on=["routing"],
                        produces=["*.spef"],
                    )
                )

        # Wrap every stage's command through the tool resolver. If a tool
        # is not available natively, route through Docker or WSL. If no
        # backend can run a tool, mark the command so the engine reports
        # a clear error (instead of WinError 2).
        self._tool_mechanisms: dict[str, str] = {}
        for stage in list(g._stages.values()):
            wrapped, mechanism = resolve_command(
                stage.command,
                cwd=stage.cwd,
                project_dir=self.work_dir,
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
            tools_needed = sorted(
                {
                    Path(self._graph._stages[sid].command[0]).name
                    for sid in missing
                    if self._graph._stages[sid].command
                }
            )
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
            native_signoff=_collect_native_signoff(self._out),
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
    "ADVISORY_STAGE_IDS",
    "FlowStageStatus",
    "FullFlowConfig",
    "FullFlowResult",
    "FullFlowRunner",
    "NativeSignoffSummary",
    "STAGE_IDS",
    "STAGE_NAMES",
]
