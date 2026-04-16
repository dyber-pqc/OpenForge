"""OpenForge CLI main entry point.

Registers all subcommand groups so that every feature available
in the GUI is also available from the command line.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from openforge_cli import __version__

# ---------------------------------------------------------------------------
# Sub-apps (Typer groups)
# ---------------------------------------------------------------------------
from openforge_cli.commands.project import app as project_app
from openforge_cli.commands.pnr import app as pnr_app
from openforge_cli.commands.fpga import app as fpga_app
from openforge_cli.commands.signoff import app as signoff_app
from openforge_cli.commands.verify import app as verify_app
from openforge_cli.commands.pcb import app as pcb_app
from openforge_cli.commands.analog import app as spice_app
from openforge_cli.commands.flow import app as flow_app
from openforge_cli.commands.tools import app as tools_app
from openforge_cli.commands.pdk import app as pdk_app

# Standalone commands (registered directly)
from openforge_cli.commands.synthesize import synth
from openforge_cli.commands.serve import serve

# ---------------------------------------------------------------------------
# Root app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="openforge",
    help="OpenForge EDA -- open-source hardware design & verification toolkit.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold green]openforge[/] {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Show the OpenForge version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """OpenForge EDA toolkit."""


# ---------------------------------------------------------------------------
# Register sub-apps (command groups)
# ---------------------------------------------------------------------------

# Project management: openforge project {init,open,info,validate}
app.add_typer(project_app, name="project", help="Project management -- init, open, info, validate.")

# Synthesis: openforge synth [OPTIONS]
app.command(name="synth")(synth)

# Place & Route: openforge pnr {run,report}
app.add_typer(pnr_app, name="pnr", help="Place and route -- floorplan, place, CTS, route.")

# FPGA flow: openforge fpga {synth,pnr,pack,flash,detect,boards}
app.add_typer(fpga_app, name="fpga", help="FPGA flow -- synth, PnR, pack, flash.")

# Signoff: openforge signoff {sta,drc,lvs,ir-drop,em,thermal,antenna,all,report}
app.add_typer(signoff_app, name="signoff", help="Signoff -- STA, DRC, LVS, IR drop, EM, thermal, antenna.")

# Verification: openforge verify {sim,formal,eqy,lint,cdc,regression}
app.add_typer(verify_app, name="verify", help="Verification -- sim, formal, lint, CDC, regression.")

# PCB: openforge pcb {erc,drc,gerber,drill,bom,pick-place,impedance,route,export}
app.add_typer(pcb_app, name="pcb", help="PCB design -- ERC, DRC, Gerber, BOM, routing, export.")

# Analog: openforge spice {run,monte-carlo}
app.add_typer(spice_app, name="spice", help="Analog SPICE simulation.")

# Flow: openforge flow {run,status,artifacts,clean,graph}
app.add_typer(flow_app, name="flow", help="Flow orchestration -- run, status, artifacts, clean.")

# Tools: openforge tools {list,install,doctor}
app.add_typer(tools_app, name="tools", help="EDA tool management.")

# PDK: openforge pdk {list,install,info}
app.add_typer(pdk_app, name="pdk", help="PDK management.")

# Serve: openforge serve [OPTIONS]
app.command(name="serve")(serve)


# ---------------------------------------------------------------------------
# Convenience aliases at root level
# These are the most common operations and can be used without the group name.
# ---------------------------------------------------------------------------


@app.command()
def init(
    name: str = typer.Argument(..., help="Project name."),
    kind: str = typer.Option("asic", "--kind", "-k", help="Project type: asic, fpga, pcb, mixed."),
    template: str = typer.Option("empty", "--template", "-t", help="Template: sky130, ice40, ecp5, gowin, caravel, pcb, empty."),
    from_vivado: Optional[str] = typer.Option(None, "--from-vivado", help="Import Vivado .xpr."),
    from_openlane: Optional[str] = typer.Option(None, "--from-openlane", help="Import OpenLane directory."),
    from_kicad: Optional[str] = typer.Option(None, "--from-kicad", help="Import KiCad .kicad_pro."),
    from_quartus: Optional[str] = typer.Option(None, "--from-quartus", help="Import Quartus .qpf."),
) -> None:
    """Create a new OpenForge project (shortcut for 'openforge project init').

    Examples:
        openforge init my_chip --kind asic --template sky130
        openforge init my_fpga --kind fpga --template ice40
        openforge init imported --from-vivado path/to/project.xpr
    """
    from openforge_cli.commands.project import init as project_init, ProjectKind, TemplateName

    # Map string args to enums
    kind_enum = ProjectKind(kind)
    template_enum = TemplateName(template)
    project_init(
        name=name,
        kind=kind_enum,
        template=template_enum,
        from_vivado=from_vivado,
        from_openlane=from_openlane,
        from_kicad=from_kicad,
        from_quartus=from_quartus,
    )


@app.command()
def info(
    project_dir: str = typer.Argument(".", help="Path to the project directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Detailed info."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show project summary (shortcut for 'openforge project info')."""
    from openforge_cli.commands.project import info as project_info

    project_info(project_dir=project_dir, verbose=verbose, json_output=json_output)


@app.command()
def validate(
    project_dir: str = typer.Argument(".", help="Path to the project directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Validate openforge.yaml consistency (shortcut for 'openforge project validate')."""
    from openforge_cli.commands.project import validate as project_validate

    project_validate(project_dir=project_dir, json_output=json_output)


@app.command()
def sim(
    path: str = typer.Argument(".", help="Path to the design directory."),
    top: Optional[str] = typer.Option(None, "--top", help="Top-level module."),
    tb: Optional[str] = typer.Option(None, "--tb", help="Testbench file."),
    sim_tool: str = typer.Option("icarus", "--sim", "-s", help="Simulator: verilator, icarus, ghdl."),
    waves: bool = typer.Option(True, "--waves/--no-waves", "-w", help="Waveform tracing."),
    timeout: int = typer.Option(300, "--timeout", help="Timeout in seconds."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Compile and run RTL simulation (shortcut for 'openforge verify sim')."""
    from openforge_cli.commands.verify import sim as verify_sim

    verify_sim(
        path=path,
        top=top,
        tb=tb,
        sim_tool=sim_tool,
        waves=waves,
        timeout=timeout,
        verbose=verbose,
        json_output=json_output,
    )


@app.command()
def lint(
    path: str = typer.Argument(".", help="Path to the design directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run Verible lint (shortcut for 'openforge verify lint')."""
    from openforge_cli.commands.verify import lint as verify_lint

    verify_lint(path=path, verbose=verbose, json_output=json_output)


@app.command()
def sta(
    path: str = typer.Argument(".", help="Path to the design directory."),
    sdc: Optional[str] = typer.Option(None, "--sdc", help="SDC constraints file."),
    corner: str = typer.Option("tt", "--corner", help="PVT corner: tt, ss, ff."),
    report: bool = typer.Option(False, "--report", help="Show detailed timing report."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run static timing analysis (shortcut for 'openforge signoff sta')."""
    from openforge_cli.commands.signoff import sta as signoff_sta

    signoff_sta(path=path, sdc=sdc, corner=corner, report=report, json_output=json_output)


@app.command()
def drc(
    path: str = typer.Argument(".", help="Path to the design directory."),
    tool: str = typer.Option("magic", "--tool", help="DRC tool: magic or klayout."),
    gds: Optional[str] = typer.Option(None, "--gds", help="GDS file to check."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run design rule check (shortcut for 'openforge signoff drc')."""
    from openforge_cli.commands.signoff import drc as signoff_drc

    signoff_drc(path=path, tool=tool, gds=gds, json_output=json_output)


@app.command()
def lvs(
    path: str = typer.Argument(".", help="Path to the design directory."),
    gds: Optional[str] = typer.Option(None, "--gds", help="GDS layout file."),
    netlist: Optional[str] = typer.Option(None, "--netlist", help="Reference netlist."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run layout-vs-schematic (shortcut for 'openforge signoff lvs')."""
    from openforge_cli.commands.signoff import lvs as signoff_lvs

    signoff_lvs(path=path, gds=gds, netlist=netlist, json_output=json_output)


@app.command()
def formal(
    path: str = typer.Argument(".", help="Path to the design directory."),
    engine: str = typer.Option("smtbmc", "--engine", help="Formal engine."),
    depth: int = typer.Option(20, "--depth", help="BMC depth."),
    mode: str = typer.Option("bmc", "--mode", help="Mode: bmc, prove, cover."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run formal verification (shortcut for 'openforge verify formal')."""
    from openforge_cli.commands.verify import formal as verify_formal

    verify_formal(path=path, engine=engine, depth=depth, mode=mode, json_output=json_output)


@app.command()
def regression(
    path: str = typer.Argument(".", help="Path to the design directory."),
    suite: Optional[str] = typer.Option(None, "--suite", help="Test suite file."),
    parallel: int = typer.Option(1, "--parallel", "-j", help="Parallel jobs."),
    seeds: int = typer.Option(1, "--seeds", help="Random seeds per test."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run regression tests (shortcut for 'openforge verify regression')."""
    from openforge_cli.commands.verify import regression as verify_regression

    verify_regression(path=path, suite=suite, parallel=parallel, seeds=seeds, json_output=json_output)


@app.command(name="ir-drop")
def ir_drop(
    path: str = typer.Argument(".", help="Path to the design directory."),
    vdd: float = typer.Option(1.8, "--vdd", help="Supply voltage."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Estimate IR drop (shortcut for 'openforge signoff ir-drop')."""
    from openforge_cli.commands.signoff import ir_drop as signoff_ir

    signoff_ir(path=path, vdd=vdd, json_output=json_output)


@app.command()
def em(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run electromigration analysis (shortcut for 'openforge signoff em')."""
    from openforge_cli.commands.signoff import em as signoff_em

    signoff_em(path=path, json_output=json_output)


@app.command()
def thermal(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run thermal analysis (shortcut for 'openforge signoff thermal')."""
    from openforge_cli.commands.signoff import thermal as signoff_thermal

    signoff_thermal(path=path, json_output=json_output)


@app.command()
def antenna(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run antenna check (shortcut for 'openforge signoff antenna')."""
    from openforge_cli.commands.signoff import antenna as signoff_antenna

    signoff_antenna(path=path, json_output=json_output)


@app.command()
def cdc(
    path: str = typer.Argument(".", help="Path to the design directory."),
    top: Optional[str] = typer.Option(None, "--top", help="Top-level module."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run CDC analysis (shortcut for 'openforge verify cdc')."""
    from openforge_cli.commands.verify import cdc as verify_cdc

    verify_cdc(path=path, top=top, json_output=json_output)


if __name__ == "__main__":
    app()
