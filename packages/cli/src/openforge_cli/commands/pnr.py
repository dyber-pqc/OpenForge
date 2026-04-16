"""openforge pnr -- place and route commands."""

from __future__ import annotations

import json as json_mod
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="pnr",
    help="Place and route commands.",
    no_args_is_help=True,
)


def _load_config(project_dir: Path):
    from openforge.config.loader import ConfigNotFoundError, load_config

    try:
        return load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/]. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(code=1)


def _locate_netlist(project_dir: Path, netlist_arg: Optional[str]) -> Path:
    if netlist_arg:
        p = Path(netlist_arg)
        if p.exists():
            return p
        console.print(f"[red]Error:[/] netlist not found at [cyan]{netlist_arg}[/].")
        raise typer.Exit(code=1)
    default = project_dir / "synth_build" / "netlist.v"
    if default.exists():
        return default
    console.print(
        "[red]Error:[/] no synthesized netlist found. "
        "Run [bold]openforge synth[/] first, or specify --netlist."
    )
    raise typer.Exit(code=1)


def _locate_sdc(project_dir: Path, sdc_arg: Optional[str], config) -> Path:
    if sdc_arg:
        return Path(sdc_arg)

    # From config constraints
    for constraint in config.design.constraints:
        candidate = project_dir / constraint
        if candidate.exists() and candidate.suffix == ".sdc":
            return candidate
    if config.timing and config.timing.sdc_files:
        for sdc_file in config.timing.sdc_files:
            candidate = project_dir / sdc_file
            if candidate.exists():
                return candidate

    # Auto-generate
    clock_period = config.timing.clock_period if config.timing else 10.0
    sdc_dir = project_dir / ".openforge"
    sdc_dir.mkdir(parents=True, exist_ok=True)
    sdc_path = sdc_dir / "auto_constraints.sdc"
    sdc_path.write_text(
        f"create_clock -name clk -period {clock_period} [get_ports clk]\n"
    )
    console.print(f"  [dim]Generated SDC with {clock_period} ns clock period[/]")
    return sdc_path


@app.command(name="run")
def pnr_run(
    path: str = typer.Argument(".", help="Path to the design directory."),
    target: str = typer.Option("sky130", "--target", "-t", help="Target PDK."),
    util: float = typer.Option(50.0, "--util", "-u", help="Target core utilization (percent)."),
    freq: Optional[float] = typer.Option(None, "--freq", help="Target frequency in MHz."),
    floorplan: bool = typer.Option(False, "--floorplan", help="Run only floorplanning."),
    place: bool = typer.Option(False, "--place", help="Run only placement."),
    cts: bool = typer.Option(False, "--cts", help="Run only CTS."),
    route: bool = typer.Option(False, "--route", help="Run only routing."),
    netlist: Optional[str] = typer.Option(None, "--netlist", "-n", help="Gate-level netlist path."),
    sdc: Optional[str] = typer.Option(None, "--sdc", help="SDC constraints file."),
    def_out: Optional[str] = typer.Option(None, "--def", help="Export final DEF to this path."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run physical design (place and route) flow.

    Examples:
        openforge pnr run --util 40 --freq 100
        openforge pnr run --floorplan
        openforge pnr run --place
        openforge pnr run --route
        openforge pnr run --def routed.def
    """
    from openforge.physical.runner import PhysicalDesignRunner

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    utilization = util / 100.0 if util > 1.0 else util

    # Determine stage
    if floorplan:
        stage = "floorplan"
    elif place:
        stage = "place"
    elif cts:
        stage = "cts"
    elif route:
        stage = "route"
    else:
        stage = "full"

    netlist_path = _locate_netlist(project_dir, netlist)
    sdc_path = _locate_sdc(project_dir, sdc, config)

    if not quiet:
        console.print(f"[bold]Running physical design[/] at [cyan]{project_dir}[/]")
        console.print(f"  target      : [green]{target}[/]")
        console.print(f"  utilization : [green]{utilization:.0%}[/]")
        console.print(f"  netlist     : [green]{netlist_path}[/]")
        console.print(f"  sdc         : [green]{sdc_path}[/]")
        console.print(f"  stage       : [green]{stage}[/]")
        if freq:
            console.print(f"  frequency   : [green]{freq} MHz[/]")
        console.print()

    try:
        runner = PhysicalDesignRunner(project_dir, config, pdk=target)
    except Exception as e:
        console.print(f"[red]Error initializing PnR runner:[/] {e}")
        console.print(
            "[dim]Hint: ensure OpenROAD is installed. "
            "Run [bold]openforge tools list[/] to check.[/]"
        )
        raise typer.Exit(code=1)

    output_lines: list[str] = []

    def _on_output(line: str) -> None:
        output_lines.append(line)
        if verbose:
            console.print(f"  [dim]{line.rstrip()}[/]")

    with console.status(f"[bold blue]Running {stage} flow...", spinner="dots"):
        if stage == "full":
            result = runner.run_full_flow(
                netlist=str(netlist_path),
                sdc=str(sdc_path),
                utilization=utilization,
                on_output=_on_output,
            )
        elif stage == "floorplan":
            result = runner.run_floorplan(
                netlist=str(netlist_path),
                sdc=str(sdc_path),
                utilization=utilization,
                on_output=_on_output,
            )
        elif stage == "place":
            def_path = project_dir / "pnr_build" / "floorplan.def"
            if not def_path.exists():
                console.print(
                    "[red]Error:[/] no floorplan DEF found. "
                    "Run [bold]openforge pnr run --floorplan[/] first."
                )
                raise typer.Exit(code=1)
            result = runner.run_placement(
                def_input=str(def_path), on_output=_on_output
            )
        elif stage == "cts":
            def_path = project_dir / "pnr_build" / "placed.def"
            if not def_path.exists():
                def_path = project_dir / "pnr_build" / "counter_placed.def"
            if not def_path.exists():
                console.print(
                    "[red]Error:[/] no placed DEF found. "
                    "Run [bold]openforge pnr run --place[/] first."
                )
                raise typer.Exit(code=1)
            result = runner.run_placement(
                def_input=str(def_path), on_output=_on_output
            )
        elif stage == "route":
            def_path = project_dir / "pnr_build" / "placed.def"
            if not def_path.exists():
                console.print(
                    "[red]Error:[/] no placed DEF found. "
                    "Run [bold]openforge pnr run --place[/] first."
                )
                raise typer.Exit(code=1)
            result = runner.run_routing(
                def_input=str(def_path), on_output=_on_output
            )
        else:
            console.print(f"[red]Unknown stage:[/] {stage}")
            raise typer.Exit(code=1)

    if not result.success:
        if json_output:
            console.print(json_mod.dumps({"status": "failed", "stage": stage}))
        else:
            console.print(f"[red bold]PnR {stage} FAILED[/]")
            if result.log:
                console.print("[dim]--- Last 30 lines of log ---[/]")
                for line in result.log.splitlines()[-30:]:
                    console.print(f"  [dim]{line}[/]")
        raise typer.Exit(code=1)

    if json_output:
        console.print(json_mod.dumps({
            "status": "passed",
            "stage": stage,
            "area_um2": result.area_um2,
            "utilization_pct": result.utilization_pct,
            "wirelength_um": result.wirelength_um,
            "drc_violations": result.drc_violations,
            "timing_wns": result.timing_wns,
            "timing_tns": result.timing_tns,
            "power_mw": result.power_mw,
            "def_path": result.def_path,
            "gds_path": result.gds_path,
            "duration_s": result.duration,
        }))
        return

    # Display results
    console.print(f"[green bold]PnR {stage} PASSED[/] in {result.duration:.1f}s")
    console.print()

    pnr_table = Table(title="Physical Design Results", show_header=True, header_style="bold cyan")
    pnr_table.add_column("Metric", style="bold")
    pnr_table.add_column("Value", justify="right")

    pnr_table.add_row("Area", f"{result.area_um2:,.1f} um^2")
    pnr_table.add_row("Utilization", f"{result.utilization_pct:.1f}%")
    pnr_table.add_row("Wirelength", f"{result.wirelength_um:,.1f} um")
    pnr_table.add_row("DRC violations", f"{result.drc_violations}")

    wns_style = "[red]" if result.timing_wns < 0 else "[green]"
    tns_style = "[red]" if result.timing_tns < 0 else "[green]"
    pnr_table.add_row("WNS", f"{wns_style}{result.timing_wns:.4f} ns[/]")
    pnr_table.add_row("TNS", f"{tns_style}{result.timing_tns:.4f} ns[/]")

    if result.power_mw > 0:
        pnr_table.add_row("Power", f"{result.power_mw:.3f} mW")
    if result.def_path:
        pnr_table.add_row("Output DEF", result.def_path)
    if result.gds_path:
        pnr_table.add_row("Output GDS", result.gds_path)

    console.print(pnr_table)

    # Copy DEF if requested
    if def_out and result.def_path:
        import shutil

        shutil.copy2(result.def_path, def_out)
        console.print(f"\n[green]DEF exported to:[/] {def_out}")


@app.command()
def report(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show PnR report from the last run.

    Example:
        openforge pnr report
    """
    project_dir = Path(path).resolve()
    pnr_build = project_dir / "pnr_build"

    if not pnr_build.exists():
        console.print("[red]Error:[/] no pnr_build directory found. Run PnR first.")
        raise typer.Exit(code=1)

    # Collect artifacts
    artifacts: dict[str, str] = {}
    for f in pnr_build.iterdir():
        if f.is_file():
            artifacts[f.name] = str(f)

    if json_output:
        console.print(json_mod.dumps({"pnr_build": str(pnr_build), "artifacts": artifacts}))
        return

    table = Table(title="PnR Artifacts", show_header=True, header_style="bold cyan")
    table.add_column("File", style="bold")
    table.add_column("Path")

    for name, fpath in sorted(artifacts.items()):
        table.add_row(name, fpath)

    console.print(table)

    # Try to show timing/area from JSON reports
    for json_file in pnr_build.glob("*.json"):
        try:
            data = json_mod.loads(json_file.read_text())
            console.print(f"\n[bold]Report:[/] {json_file.name}")
            for k, v in data.items():
                if isinstance(v, (int, float, str)):
                    console.print(f"  {k}: {v}")
        except (json_mod.JSONDecodeError, OSError):
            pass
