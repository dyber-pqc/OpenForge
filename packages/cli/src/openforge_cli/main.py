"""OpenForge CLI main entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from openforge_cli import __version__
from openforge_cli.commands.init import init
from openforge_cli.commands.verify import verify
from openforge_cli.commands.synthesize import synth

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


# ---- Registered commands ------------------------------------------------

app.command()(init)
app.command()(verify)
app.command(name="synth")(synth)


@app.command()
def lint(
    path: str = typer.Argument(".", help="Path to the design directory."),
) -> None:
    """Run Verible lint on HDL source files."""
    from openforge.config.loader import load_config
    from openforge.flow.lint import run_lint

    project_dir = Path(path).resolve()
    console.print(f"[bold]Linting[/] design at [cyan]{project_dir}[/] ...")

    try:
        config = load_config(project_dir)
    except FileNotFoundError:
        console.print("[red]Error:[/] No openforge.yaml found.")
        raise typer.Exit(1)

    # Resolve source globs
    source_files = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))

    result = run_lint({"source_files": source_files, "cwd": str(project_dir)})

    if result.status.value == "passed":
        console.print(f"[green]PASS[/] -- {result.artifacts.get('findings_count', '0')} findings")
    else:
        console.print(f"[red]FAIL[/] -- {result.output[:500]}")
        for err in result.errors:
            console.print(f"  [red]{err}[/]")
        raise typer.Exit(1)


@app.command()
def sim(
    path: str = typer.Argument(".", help="Path to the design directory."),
    tool: str = typer.Option("verilator", "--tool", "-t", help="Simulator (verilator, icarus, ghdl)."),
    waves: bool = typer.Option(True, "--waves/--no-waves", "-w", help="Enable waveform tracing."),
    timeout: int = typer.Option(300, "--timeout", help="Simulation timeout in seconds."),
) -> None:
    """Compile and run RTL simulation."""
    from openforge.config.loader import load_config
    from openforge.flow.simulate import run_simulation

    project_dir = Path(path).resolve()
    console.print(f"[bold]Simulating[/] design at [cyan]{project_dir}[/] with {tool} ...")

    try:
        config = load_config(project_dir)
    except FileNotFoundError:
        console.print("[red]Error:[/] No openforge.yaml found.")
        raise typer.Exit(1)

    source_files = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))

    includes = [str(project_dir / inc) for inc in config.design.includes]

    result = run_simulation({
        "source_files": source_files,
        "top_module": config.project.top_module,
        "sim_tool": tool,
        "includes": includes,
        "coverage": config.simulation.coverage.line if config.simulation else False,
        "cwd": str(project_dir),
        "timeout": float(timeout),
    })

    if result.status.value == "passed":
        console.print("[green]PASS[/] -- Simulation completed successfully.")
        if waveform := result.artifacts.get("waveform"):
            console.print(f"  Waveform: {waveform}")
    else:
        console.print("[red]FAIL[/] -- Simulation failed.")
        for err in result.errors:
            console.print(f"  [red]{err[:200]}[/]")
        raise typer.Exit(1)


@app.command()
def analyze(
    path: str = typer.Argument(".", help="Path to the design directory."),
    timing: bool = typer.Option(False, "--timing", help="Run static timing analysis."),
    power: bool = typer.Option(False, "--power", help="Run power estimation."),
    area: bool = typer.Option(False, "--area", help="Show area statistics."),
) -> None:
    """Analyze design metrics (area, timing, power estimates)."""
    from openforge.config.loader import ConfigNotFoundError, load_config

    project_dir = Path(path).resolve()

    try:
        config = load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            "[red]Error:[/] no openforge.yaml found. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(1)

    checks = []
    if timing:
        checks.append("timing")
    if power:
        checks.append("power")
    if area:
        checks.append("area")
    if not checks:
        checks = ["timing", "area"]

    console.print(f"[bold]Analyzing[/] design at [cyan]{project_dir}[/] ...")
    console.print(f"  checks : [green]{', '.join(checks)}[/]")
    console.print()

    synth_build = project_dir / "synth_build"
    netlist_path = synth_build / "netlist.v"
    any_failure = False

    # ---- Timing analysis ----
    if "timing" in checks:
        console.rule("[bold cyan]Timing Analysis[/]")

        if not netlist_path.exists():
            console.print(
                "[red]Error:[/] no synthesized netlist found at "
                f"[cyan]{netlist_path}[/]. Run [bold]openforge synth[/] first."
            )
            any_failure = True
        else:
            from openforge.physical.timing import TimingAnalyzer

            # Locate liberty and SDC files
            pdk = config.project.target_pdk or "sky130"
            from openforge.synthesis.runner import _PDK_LIBERTY

            liberty_name = _PDK_LIBERTY.get(pdk, "liberty.lib")
            liberty_path = liberty_name  # May be relative; TimingAnalyzer resolves

            # Locate SDC file
            sdc_path: str | None = None
            if config.design.constraints:
                sdc_candidate = project_dir / config.design.constraints[0]
                if sdc_candidate.exists():
                    sdc_path = str(sdc_candidate)
            if config.timing and config.timing.sdc_files:
                for sdc_file in config.timing.sdc_files:
                    sdc_candidate = project_dir / sdc_file
                    if sdc_candidate.exists():
                        sdc_path = str(sdc_candidate)
                        break

            if not sdc_path:
                # Generate a minimal SDC
                clock_period = config.timing.clock_period if config.timing else 10.0
                sdc_dir = project_dir / ".openforge"
                sdc_dir.mkdir(parents=True, exist_ok=True)
                sdc_gen = sdc_dir / "auto_constraints.sdc"
                sdc_gen.write_text(
                    f"create_clock -name clk -period {clock_period} [get_ports clk]\n"
                )
                sdc_path = str(sdc_gen)
                console.print(
                    f"  [dim]Generated SDC with {clock_period} ns clock period[/]"
                )

            analyzer = TimingAnalyzer()

            try:
                with console.status("[bold blue]Running STA...", spinner="dots"):
                    result = analyzer.run_analysis(
                        liberty=liberty_path,
                        netlist=str(netlist_path),
                        sdc=sdc_path,
                        top_module=config.project.top_module,
                        cwd=str(project_dir),
                    )

                # WNS / TNS summary
                timing_table = Table(
                    title="Timing Summary",
                    show_header=True,
                    header_style="bold cyan",
                )
                timing_table.add_column("Metric", style="bold")
                timing_table.add_column("Value", justify="right")

                wns_style = "[red]" if result.wns < 0 else "[green]"
                tns_style = "[red]" if result.tns < 0 else "[green]"

                timing_table.add_row("WNS (Worst Negative Slack)", f"{wns_style}{result.wns:.4f} ns[/]")
                timing_table.add_row("TNS (Total Negative Slack)", f"{tns_style}{result.tns:.4f} ns[/]")
                timing_table.add_row("Endpoints analyzed", str(result.num_endpoints))
                timing_table.add_row("Endpoints violated", str(result.num_violated))

                console.print(timing_table)

                # Clock summary
                if result.clocks:
                    clk_table = Table(
                        title="Clock Summary",
                        show_header=True,
                        header_style="bold cyan",
                    )
                    clk_table.add_column("Clock")
                    clk_table.add_column("Period (ns)", justify="right")
                    clk_table.add_column("Freq (MHz)", justify="right")
                    clk_table.add_column("Slack (ns)", justify="right")

                    for clk_name, clk_info in result.clocks.items():
                        slack_val = clk_info.get("slack", 0.0)
                        slack_style = "[red]" if slack_val < 0 else "[green]"
                        clk_table.add_row(
                            clk_name,
                            f"{clk_info['period']:.2f}",
                            f"{clk_info['frequency_achieved']:.1f}",
                            f"{slack_style}{slack_val:.4f}[/]",
                        )
                    console.print(clk_table)

                # Critical paths (top 5)
                critical = analyzer.get_critical_paths(5)
                if critical:
                    path_table = Table(
                        title="Critical Paths (worst 5)",
                        show_header=True,
                        header_style="bold cyan",
                    )
                    path_table.add_column("Start", max_width=30)
                    path_table.add_column("End", max_width=30)
                    path_table.add_column("Type", width=6)
                    path_table.add_column("Delay (ns)", justify="right")
                    path_table.add_column("Slack (ns)", justify="right")

                    for p in critical:
                        slack_style = "[red]" if p.slack_ns < 0 else "[green]"
                        path_table.add_row(
                            p.start_point,
                            p.end_point,
                            p.path_type,
                            f"{p.delay_ns:.4f}",
                            f"{slack_style}{p.slack_ns:.4f}[/]",
                        )
                    console.print(path_table)

            except Exception as e:
                console.print(f"[red]Timing analysis failed:[/] {e}")
                console.print(
                    "[dim]Hint: ensure OpenSTA is installed. "
                    "Run [bold]openforge tools[/] to check.[/]"
                )
                any_failure = True

        console.print()

    # ---- Area analysis ----
    if "area" in checks:
        console.rule("[bold cyan]Area Analysis[/]")

        stats_file = synth_build / "stats_incr.txt"
        log_sources = [
            synth_build / "synthesis.ys",
        ]

        # Try to read synthesis log for area info
        synth_log = ""
        for log_file in [synth_build / "netlist.json"]:
            pass  # JSON doesn't contain stats

        # Best approach: re-parse from the synthesis runner
        if netlist_path.exists():
            from openforge.synthesis.runner import SynthesisRunner, _parse_stat_output

            # Look for any log file with stat output
            log_found = False
            for log_candidate in synth_build.glob("*.log"):
                synth_log = log_candidate.read_text()
                log_found = True
                break

            if not log_found:
                # Try to read stats from Yosys by running stat on existing netlist
                console.print("  [dim]Reading area from synthesis artifacts...[/]")
                try:
                    runner = SynthesisRunner(project_dir, config)
                    # Use the stat output from any available log
                    # Check if there's a saved stat output
                    for stat_candidate in [
                        synth_build / "stats_incr.txt",
                        synth_build / "stats.txt",
                    ]:
                        if stat_candidate.exists():
                            synth_log = stat_candidate.read_text()
                            log_found = True
                            break
                except Exception:
                    pass

            if synth_log:
                gate_count, cell_usage, area = _parse_stat_output(synth_log)

                area_table = Table(
                    title="Area Summary",
                    show_header=True,
                    header_style="bold cyan",
                )
                area_table.add_column("Metric", style="bold")
                area_table.add_column("Value", justify="right")

                area_table.add_row("Gate count", f"{gate_count:,}")
                area_table.add_row("Chip area", f"{area:,.1f} um^2")
                area_table.add_row("Cell types", f"{len(cell_usage)}")

                console.print(area_table)

                if cell_usage:
                    cell_table = Table(
                        title="Cell Usage",
                        show_header=True,
                        header_style="bold cyan",
                    )
                    cell_table.add_column("Cell Type", style="bold")
                    cell_table.add_column("Count", justify="right")

                    sorted_cells = sorted(cell_usage.items(), key=lambda x: x[1], reverse=True)
                    for name, count in sorted_cells[:15]:
                        cell_table.add_row(name, f"{count:,}")
                    console.print(cell_table)
            else:
                console.print(
                    "[yellow]No synthesis statistics found.[/] "
                    "Run [bold]openforge synth[/] first."
                )
        else:
            console.print(
                "[red]Error:[/] no synthesized netlist found. "
                "Run [bold]openforge synth[/] first."
            )
            any_failure = True

        console.print()

    # ---- Power analysis ----
    if "power" in checks:
        console.rule("[bold cyan]Power Analysis[/]")
        console.print(
            "[yellow]Power estimation requires OpenROAD with parasitic extraction.[/]"
        )
        console.print(
            "  Install OpenROAD: [cyan]https://openroad.readthedocs.io/en/latest/user/Build.html[/]"
        )
        console.print(
            "  Then run: [bold]openforge pnr --full[/] to generate power reports."
        )
        console.print()

    if any_failure:
        raise typer.Exit(1)


@app.command()
def report(
    path: str = typer.Argument(".", help="Path to the design directory."),
    format: str = typer.Option("html", "--format", "-f", help="Report format (html, json, sarif, junit)."),
    output: str = typer.Option("reports/", "--output", "-o", help="Output directory."),
) -> None:
    """Generate a verification / synthesis report."""
    import json as json_mod

    from openforge.config.loader import ConfigNotFoundError, load_config
    from openforge.report.generator import generate_report

    project_dir = Path(path).resolve()
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            "[red]Error:[/] no openforge.yaml found. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(1)

    console.print(f"[bold]Generating[/] {format} report for [cyan]{project_dir}[/] ...")

    # Collect results from .openforge/ and build directories
    results_data: dict[str, object] = {}

    openforge_dir = project_dir / ".openforge"
    synth_build = project_dir / "synth_build"
    pnr_build = project_dir / "pnr_build"

    # Collect synthesis results
    if synth_build.exists():
        for json_file in synth_build.glob("*.json"):
            try:
                step_data = json_mod.loads(json_file.read_text())
                results_data[f"synth_{json_file.stem}"] = step_data
            except (json_mod.JSONDecodeError, OSError):
                pass

    # Collect PnR results
    if pnr_build.exists():
        for json_file in pnr_build.glob("*.json"):
            try:
                step_data = json_mod.loads(json_file.read_text())
                results_data[f"pnr_{json_file.stem}"] = step_data
            except (json_mod.JSONDecodeError, OSError):
                pass

    # Collect .openforge results
    if openforge_dir.exists():
        for json_file in openforge_dir.glob("*.json"):
            try:
                step_data = json_mod.loads(json_file.read_text())
                results_data[json_file.stem] = step_data
            except (json_mod.JSONDecodeError, OSError):
                pass

    if results_data:
        console.print(f"  Collected results from [green]{len(results_data)}[/] artifacts")
    else:
        console.print(
            "  [yellow]No build artifacts found.[/] Report will be empty. "
            "Run [bold]openforge synth[/] or [bold]openforge verify --all[/] first."
        )

    # Build results dict with required metadata
    results_dict = None
    if results_data:
        from datetime import datetime, timezone

        results_dict = {
            "project": project_dir.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "openforge_version": __version__,
            "steps": results_data,
        }

    try:
        report_path = generate_report(
            project_dir=project_dir,
            output_dir=output_dir,
            format=format,
            results=results_dict,
        )
        console.print(f"[green]Report written to:[/] {report_path}")
    except Exception as e:
        console.print(f"[red]Error generating report:[/] {e}")
        raise typer.Exit(1)


@app.command()
def pnr(
    path: str = typer.Argument(".", help="Path to the design directory."),
    target: str = typer.Option("sky130", "--target", "-t", help="Target PDK (sky130, gf180mcu)."),
    utilization: float = typer.Option(0.5, "--utilization", "-u", help="Target core utilization (0.0-1.0)."),
    floorplan_only: bool = typer.Option(False, "--floorplan-only", help="Run only floorplanning."),
    place_only: bool = typer.Option(False, "--place-only", help="Run only placement."),
    route_only: bool = typer.Option(False, "--route-only", help="Run only routing."),
    full: bool = typer.Option(False, "--full", help="Run full PnR flow."),
    netlist: str | None = typer.Option(None, "--netlist", "-n", help="Path to gate-level netlist."),
    sdc: str | None = typer.Option(None, "--sdc", help="Path to SDC constraints file."),
) -> None:
    """Run physical design (place and route) flow."""
    from openforge.config.loader import ConfigNotFoundError, load_config
    from openforge.physical.runner import PhysicalDesignRunner

    project_dir = Path(path).resolve()

    try:
        config = load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            "[red]Error:[/] no openforge.yaml found. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(1)

    # Determine which stage(s) to run
    stages: list[str] = []
    if full:
        stages = ["full"]
    elif floorplan_only:
        stages = ["floorplan"]
    elif place_only:
        stages = ["place"]
    elif route_only:
        stages = ["route"]
    else:
        stages = ["full"]

    # Locate netlist
    netlist_path: Path | None = None
    if netlist:
        netlist_path = Path(netlist)
    else:
        # Default: look in synth_build
        default_netlist = project_dir / "synth_build" / "netlist.v"
        if default_netlist.exists():
            netlist_path = default_netlist
        else:
            console.print(
                "[red]Error:[/] no synthesized netlist found. "
                "Run [bold]openforge synth[/] first, or specify --netlist."
            )
            raise typer.Exit(1)

    if not netlist_path or not netlist_path.exists():
        console.print(f"[red]Error:[/] netlist not found at [cyan]{netlist_path}[/].")
        raise typer.Exit(1)

    # Locate SDC
    sdc_path: Path | None = None
    if sdc:
        sdc_path = Path(sdc)
    else:
        # Check constraints from config
        for constraint in config.design.constraints:
            candidate = project_dir / constraint
            if candidate.exists() and candidate.suffix == ".sdc":
                sdc_path = candidate
                break
        if config.timing and config.timing.sdc_files:
            for sdc_file in config.timing.sdc_files:
                candidate = project_dir / sdc_file
                if candidate.exists():
                    sdc_path = candidate
                    break

        # Auto-generate minimal SDC if none found
        if sdc_path is None:
            clock_period = config.timing.clock_period if config.timing else 10.0
            sdc_dir = project_dir / ".openforge"
            sdc_dir.mkdir(parents=True, exist_ok=True)
            sdc_path = sdc_dir / "auto_constraints.sdc"
            sdc_path.write_text(
                f"create_clock -name clk -period {clock_period} [get_ports clk]\n"
            )
            console.print(f"  [dim]Generated SDC with {clock_period} ns clock period[/]")

    console.print(f"[bold]Running physical design[/] at [cyan]{project_dir}[/]")
    console.print(f"  target      : [green]{target}[/]")
    console.print(f"  utilization : [green]{utilization:.0%}[/]")
    console.print(f"  netlist     : [green]{netlist_path}[/]")
    console.print(f"  sdc         : [green]{sdc_path}[/]")
    console.print(f"  stages      : [green]{', '.join(stages)}[/]")
    console.print()

    try:
        runner = PhysicalDesignRunner(project_dir, config, pdk=target)
    except Exception as e:
        console.print(f"[red]Error initializing PnR runner:[/] {e}")
        console.print(
            "[dim]Hint: ensure OpenROAD is installed. "
            "Run [bold]openforge tools[/] to check.[/]"
        )
        raise typer.Exit(1)

    output_lines: list[str] = []

    def _on_output(line: str) -> None:
        output_lines.append(line)

    stage = stages[0]

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
            # Placement needs a DEF input; look for floorplan output
            def_path = project_dir / "pnr_build" / "floorplan.def"
            if not def_path.exists():
                console.print(
                    "[red]Error:[/] no floorplan DEF found. "
                    "Run [bold]openforge pnr --floorplan-only[/] first."
                )
                raise typer.Exit(1)
            result = runner.run_placement(
                def_input=str(def_path),
                on_output=_on_output,
            )
        elif stage == "route":
            # Routing needs a placed DEF
            def_path = project_dir / "pnr_build" / "placed.def"
            if not def_path.exists():
                console.print(
                    "[red]Error:[/] no placed DEF found. "
                    "Run [bold]openforge pnr --place-only[/] first."
                )
                raise typer.Exit(1)
            result = runner.run_routing(
                def_input=str(def_path),
                on_output=_on_output,
            )
        else:
            console.print(f"[red]Unknown stage:[/] {stage}")
            raise typer.Exit(1)

    if not result.success:
        console.print(f"[red bold]PnR {stage} FAILED[/]")
        if result.log:
            console.print()
            console.print("[dim]--- Last 30 lines of log ---[/]")
            for line in result.log.splitlines()[-30:]:
                console.print(f"  [dim]{line}[/]")
        raise typer.Exit(code=1)

    # Display results
    console.print(f"[green bold]PnR {stage} PASSED[/] in {result.duration:.1f}s")
    console.print()

    pnr_table = Table(
        title="Physical Design Results",
        show_header=True,
        header_style="bold cyan",
    )
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


@app.command()
def tools() -> None:
    """Check availability and versions of EDA tools."""
    from openforge.engine.verilator import VerilatorEngine
    from openforge.engine.yosys import YosysEngine
    from openforge.engine.verible import VeribleEngine

    table = Table(title="OpenForge Tool Status")
    table.add_column("Tool", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Version")

    engines = [
        VerilatorEngine(),
        YosysEngine(),
        VeribleEngine(),
    ]

    # Try to import optional engines
    try:
        from openforge.engine.icarus import IcarusEngine
        engines.append(IcarusEngine())
    except ImportError:
        pass
    try:
        from openforge.engine.ghdl import GHDLEngine
        engines.append(GHDLEngine())
    except ImportError:
        pass
    try:
        from openforge.engine.symbiyosys import SymbiYosysEngine
        engines.append(SymbiYosysEngine())
    except ImportError:
        pass
    try:
        from openforge.engine.opensta import OpenSTAEngine
        engines.append(OpenSTAEngine())
    except ImportError:
        pass
    try:
        from openforge.engine.openroad import OpenROADEngine
        engines.append(OpenROADEngine())
    except ImportError:
        pass

    for engine in engines:
        name = engine.BINARY
        installed = engine.check_installed()
        version = engine.version() if installed else "-"
        status = "[green]OK[/]" if installed else "[red]Missing[/]"
        table.add_row(name, status, version)

    console.print(table)


if __name__ == "__main__":
    app()
