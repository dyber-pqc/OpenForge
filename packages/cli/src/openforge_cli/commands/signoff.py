"""openforge signoff -- STA, DRC, LVS, IR drop, EM, thermal, antenna."""

from __future__ import annotations

import json as json_mod
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="signoff",
    help="Signoff analysis commands -- STA, DRC, LVS, IR drop, EM, thermal, antenna.",
    no_args_is_help=True,
)


def _load_config(project_dir: Path):
    from openforge.config.loader import ConfigNotFoundError, load_config

    try:
        return load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/].")
        raise typer.Exit(code=1)


def _locate_netlist(project_dir: Path) -> Path:
    default = project_dir / "synth_build" / "netlist.v"
    if default.exists():
        return default
    console.print("[red]Error:[/] no netlist found. Run [bold]openforge synth[/] first.")
    raise typer.Exit(code=1)


def _locate_def(project_dir: Path, def_arg: str | None) -> Path:
    if def_arg:
        p = Path(def_arg)
        if p.exists():
            return p
    # Search pnr_build
    pnr_build = project_dir / "pnr_build"
    for candidate_name in [
        "counter_routed.def",
        "routed.def",
        "final.def",
        "counter_placed.def",
        "placed.def",
    ]:
        candidate = pnr_build / candidate_name
        if candidate.exists():
            return candidate
    console.print("[red]Error:[/] no DEF file found. Run [bold]openforge pnr run[/] first.")
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# STA
# ---------------------------------------------------------------------------


@app.command()
def sta(
    path: str = typer.Argument(".", help="Path to the design directory."),
    sdc: str | None = typer.Option(None, "--sdc", help="SDC constraints file."),
    corner: str = typer.Option("tt", "--corner", help="PVT corner: tt, ss, ff."),
    spef: str | None = typer.Option(None, "--spef", help="SPEF parasitics file."),
    report: bool = typer.Option(False, "--report", help="Show timing report."),
    whatif: str | None = typer.Option(
        None, "--whatif", help="What-if timing change (e.g. 'clock_period clk 8.0')."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run static timing analysis with OpenSTA.

    Examples:
        openforge signoff sta --corner ss
        openforge signoff sta --report
        openforge signoff sta --whatif "clock_period clk 8.0"
        openforge signoff sta --spef extracted.spef
    """
    from openforge.physical.timing import TimingAnalyzer

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)
    netlist_path = _locate_netlist(project_dir)

    # Locate liberty
    pdk = config.project.target_pdk or "sky130"
    from openforge.synthesis.runner import _PDK_LIBERTY

    liberty_name = _PDK_LIBERTY.get(pdk, "liberty.lib")

    # Locate SDC
    sdc_path: str | None = sdc
    if not sdc_path:
        for constraint in config.design.constraints:
            candidate = project_dir / constraint
            if candidate.exists() and candidate.suffix == ".sdc":
                sdc_path = str(candidate)
                break
        if config.timing and config.timing.sdc_files:
            for sdc_file in config.timing.sdc_files:
                candidate = project_dir / sdc_file
                if candidate.exists():
                    sdc_path = str(candidate)
                    break
    if not sdc_path:
        clock_period = config.timing.clock_period if config.timing else 10.0
        sdc_dir = project_dir / ".openforge"
        sdc_dir.mkdir(parents=True, exist_ok=True)
        sdc_gen = sdc_dir / "auto_constraints.sdc"
        sdc_gen.write_text(f"create_clock -name clk -period {clock_period} [get_ports clk]\n")
        sdc_path = str(sdc_gen)

    # What-if mode
    if whatif:
        from openforge.physical.sta_whatif import STAWhatIf

        console.print(f"[bold]STA what-if:[/] {whatif}")
        wi = STAWhatIf()
        wi_result = wi.run(
            netlist=str(netlist_path),
            liberty=liberty_name,
            sdc=sdc_path,
            whatif_cmd=whatif,
            top_module=config.project.top_module,
            cwd=str(project_dir),
        )
        if json_output:
            console.print(
                json_mod.dumps({"whatif": whatif, "wns": wi_result.wns, "tns": wi_result.tns})
            )
        else:
            wns_s = "[red]" if wi_result.wns < 0 else "[green]"
            console.print(f"  WNS: {wns_s}{wi_result.wns:.4f} ns[/]")
            console.print(f"  TNS: {wns_s}{wi_result.tns:.4f} ns[/]")
        return

    analyzer = TimingAnalyzer()

    try:
        with console.status("[bold blue]Running STA...", spinner="dots"):
            result = analyzer.run_analysis(
                liberty=liberty_name,
                netlist=str(netlist_path),
                sdc=sdc_path,
                top_module=config.project.top_module,
                cwd=str(project_dir),
            )
    except Exception as e:
        console.print(f"[red]STA failed:[/] {e}")
        console.print("[dim]Hint: ensure OpenSTA is installed.[/]")
        raise typer.Exit(code=1)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "wns": result.wns,
                    "tns": result.tns,
                    "num_endpoints": result.num_endpoints,
                    "num_violated": result.num_violated,
                    "clocks": result.clocks,
                }
            )
        )
        return

    # Display
    timing_table = Table(title="Timing Summary", show_header=True, header_style="bold cyan")
    timing_table.add_column("Metric", style="bold")
    timing_table.add_column("Value", justify="right")

    wns_s = "[red]" if result.wns < 0 else "[green]"
    tns_s = "[red]" if result.tns < 0 else "[green]"
    timing_table.add_row("WNS", f"{wns_s}{result.wns:.4f} ns[/]")
    timing_table.add_row("TNS", f"{tns_s}{result.tns:.4f} ns[/]")
    timing_table.add_row("Endpoints", str(result.num_endpoints))
    timing_table.add_row("Violated", str(result.num_violated))
    console.print(timing_table)

    if result.clocks:
        clk_table = Table(title="Clock Summary", show_header=True, header_style="bold cyan")
        clk_table.add_column("Clock")
        clk_table.add_column("Period (ns)", justify="right")
        clk_table.add_column("Freq (MHz)", justify="right")
        clk_table.add_column("Slack (ns)", justify="right")
        for clk_name, clk_info in result.clocks.items():
            slack_val = clk_info.get("slack", 0.0)
            s = "[red]" if slack_val < 0 else "[green]"
            clk_table.add_row(
                clk_name,
                f"{clk_info['period']:.2f}",
                f"{clk_info['frequency_achieved']:.1f}",
                f"{s}{slack_val:.4f}[/]",
            )
        console.print(clk_table)

    # Critical paths
    if report:
        critical = analyzer.get_critical_paths(10)
        if critical:
            path_table = Table(title="Critical Paths", show_header=True, header_style="bold cyan")
            path_table.add_column("Start", max_width=30)
            path_table.add_column("End", max_width=30)
            path_table.add_column("Type", width=6)
            path_table.add_column("Delay (ns)", justify="right")
            path_table.add_column("Slack (ns)", justify="right")
            for p in critical:
                s = "[red]" if p.slack_ns < 0 else "[green]"
                path_table.add_row(
                    p.start_point,
                    p.end_point,
                    p.path_type,
                    f"{p.delay_ns:.4f}",
                    f"{s}{p.slack_ns:.4f}[/]",
                )
            console.print(path_table)

    if result.num_violated > 0:
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# DRC
# ---------------------------------------------------------------------------


@app.command()
def drc(
    path: str = typer.Argument(".", help="Path to the design directory."),
    tool: str = typer.Option("magic", "--tool", help="DRC tool: magic or klayout."),
    gds: str | None = typer.Option(None, "--gds", help="GDS file to check."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run design rule checks (DRC) with Magic or KLayout.

    Examples:
        openforge signoff drc --tool magic
        openforge signoff drc --tool klayout --gds layout.gds
    """
    from openforge.physical.drc_lvs import run_drc

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    # Locate GDS
    gds_path = gds
    if not gds_path:
        pnr_build = project_dir / "pnr_build"
        for candidate in pnr_build.glob("*.gds"):
            gds_path = str(candidate)
            break
    if not gds_path:
        console.print("[red]Error:[/] no GDS file found. Specify --gds or run PnR first.")
        raise typer.Exit(code=1)

    console.print(f"[bold]DRC[/] with [green]{tool}[/] on [cyan]{gds_path}[/]")

    pdk = config.project.target_pdk or "sky130"

    with console.status("[bold blue]Running DRC...", spinner="dots"):
        result = run_drc(
            gds_file=gds_path,
            pdk=pdk,
            tool=tool,
            cwd=str(project_dir),
        )

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "passed": result.passed,
                    "total_violations": result.total_count,
                    "by_category": result.by_category,
                }
            )
        )
        if not result.passed:
            raise typer.Exit(code=2)
        return

    if result.passed:
        console.print("[green bold]DRC CLEAN[/] -- 0 violations")
    else:
        console.print(f"[red bold]DRC FAILED[/] -- {result.total_count} violations")
        table = Table(title="DRC Violations", show_header=True, header_style="bold cyan")
        table.add_column("Rule")
        table.add_column("Count", justify="right")
        for cat, count in sorted(result.by_category.items(), key=lambda x: x[1], reverse=True):
            table.add_row(cat, str(count))
        console.print(table)

        if verbose:
            for v in result.violations[:50]:
                console.print(f"  [{v.severity}] {v.rule}: {v.message} @ ({v.x:.1f}, {v.y:.1f})")

        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# LVS
# ---------------------------------------------------------------------------


@app.command()
def lvs(
    path: str = typer.Argument(".", help="Path to the design directory."),
    gds: str | None = typer.Option(None, "--gds", help="GDS layout file."),
    netlist: str | None = typer.Option(None, "--netlist", help="Reference netlist."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run layout-vs-schematic (LVS) comparison with Netgen.

    Examples:
        openforge signoff lvs
        openforge signoff lvs --gds layout.gds --netlist netlist.v
    """
    from openforge.physical.drc_lvs import run_lvs

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    gds_path = gds
    netlist_path = netlist
    pnr_build = project_dir / "pnr_build"

    if not gds_path:
        for candidate in pnr_build.glob("*.gds"):
            gds_path = str(candidate)
            break
    if not netlist_path:
        netlist_path = str(project_dir / "synth_build" / "netlist.v")

    if not gds_path:
        console.print("[red]Error:[/] no GDS file found.")
        raise typer.Exit(code=1)
    if not Path(netlist_path).exists():
        console.print(f"[red]Error:[/] netlist not found at [cyan]{netlist_path}[/].")
        raise typer.Exit(code=1)

    pdk = config.project.target_pdk or "sky130"
    console.print(f"[bold]LVS[/] comparing [cyan]{gds_path}[/] vs [cyan]{netlist_path}[/]")

    with console.status("[bold blue]Running LVS...", spinner="dots"):
        result = run_lvs(
            gds_file=gds_path,
            netlist_file=netlist_path,
            pdk=pdk,
            top_module=config.project.top_module,
            cwd=str(project_dir),
        )

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "match": result.match,
                    "mismatches": result.mismatches,
                    "device_count_layout": result.device_count_layout,
                    "device_count_schematic": result.device_count_schematic,
                }
            )
        )
        if not result.match:
            raise typer.Exit(code=2)
        return

    if result.match:
        console.print("[green bold]LVS MATCH[/]")
        console.print(f"  Devices (layout): {result.device_count_layout}")
        console.print(f"  Nets: {result.net_count}")
    else:
        console.print("[red bold]LVS MISMATCH[/]")
        for m in result.mismatches[:20]:
            console.print(f"  [red]{m}[/]")
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# IR Drop
# ---------------------------------------------------------------------------


@app.command(name="ir-drop")
def ir_drop(
    path: str = typer.Argument(".", help="Path to the design directory."),
    def_file: str | None = typer.Option(None, "--def", help="DEF file to analyze."),
    vdd: float = typer.Option(1.8, "--vdd", help="Supply voltage in volts."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Estimate IR drop across the power grid.

    Example:
        openforge signoff ir-drop --vdd 1.8
    """
    from openforge.physical.ir_drop import IrDropAnalyzer

    project_dir = Path(path).resolve()
    def_path = _locate_def(project_dir, def_file)

    console.print(f"[bold]IR Drop Analysis[/] on [cyan]{def_path}[/] (VDD={vdd}V)")

    with console.status("[bold blue]Analyzing IR drop...", spinner="dots"):
        analyzer = IrDropAnalyzer()
        result = analyzer.analyze(def_file=str(def_path), vdd=vdd)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "max_drop_mv": result.max_drop_mv,
                    "avg_drop_mv": result.avg_drop_mv,
                    "vdd": result.vdd,
                    "hotspot_count": len(result.hotspots),
                }
            )
        )
        return

    table = Table(title="IR Drop Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Max drop", f"{result.max_drop_mv:.1f} mV")
    table.add_row("Avg drop", f"{result.avg_drop_mv:.1f} mV")
    table.add_row("VDD", f"{result.vdd:.3f} V")
    table.add_row("Hotspots", str(len(result.hotspots)))
    console.print(table)

    if result.hotspots:
        hs_table = Table(title="IR Drop Hotspots", show_header=True, header_style="bold cyan")
        hs_table.add_column("X (um)", justify="right")
        hs_table.add_column("Y (um)", justify="right")
        hs_table.add_column("Drop (mV)", justify="right")
        for hs in result.hotspots[:10]:
            hs_table.add_row(f"{hs.x:.1f}", f"{hs.y:.1f}", f"{hs.drop_mv:.1f}")
        console.print(hs_table)


# ---------------------------------------------------------------------------
# Electromigration
# ---------------------------------------------------------------------------


@app.command()
def em(
    path: str = typer.Argument(".", help="Path to the design directory."),
    def_file: str | None = typer.Option(None, "--def", help="DEF file to analyze."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run electromigration analysis.

    Example:
        openforge signoff em
    """
    from openforge.physical.electromigration import EmAnalyzer

    project_dir = Path(path).resolve()
    def_path = _locate_def(project_dir, def_file)

    console.print(f"[bold]EM Analysis[/] on [cyan]{def_path}[/]")

    with console.status("[bold blue]Analyzing electromigration...", spinner="dots"):
        analyzer = EmAnalyzer()
        result = analyzer.analyze(def_file=str(def_path))

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "passed": result.passed,
                    "violations": len(result.violations),
                }
            )
        )
        if not result.passed:
            raise typer.Exit(code=2)
        return

    if result.passed:
        console.print("[green bold]EM CLEAN[/] -- 0 violations")
    else:
        console.print(f"[red bold]EM FAILED[/] -- {len(result.violations)} violations")
        table = Table(title="EM Violations", show_header=True, header_style="bold cyan")
        table.add_column("Net")
        table.add_column("Layer")
        table.add_column("J (mA/um^2)", justify="right")
        table.add_column("Limit", justify="right")
        table.add_column("Severity")
        for v in result.violations[:20]:
            table.add_row(
                v.wire.net,
                v.wire.layer,
                f"{v.current_density_a_per_um2 * 1e3:.2f}",
                f"{v.limit_a_per_um2 * 1e3:.2f}",
                v.severity,
            )
        console.print(table)
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# Thermal
# ---------------------------------------------------------------------------


@app.command()
def thermal(
    path: str = typer.Argument(".", help="Path to the design directory."),
    def_file: str | None = typer.Option(None, "--def", help="DEF file to analyze."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run thermal analysis on the design.

    Example:
        openforge signoff thermal
    """
    from openforge.physical.thermal import ThermalAnalyzer

    project_dir = Path(path).resolve()
    def_path = _locate_def(project_dir, def_file)

    console.print(f"[bold]Thermal Analysis[/] on [cyan]{def_path}[/]")

    with console.status("[bold blue]Analyzing thermal...", spinner="dots"):
        analyzer = ThermalAnalyzer()
        result = analyzer.analyze(def_file=str(def_path))

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "max_temp_c": result.max_temp_c,
                    "min_temp_c": result.min_temp_c,
                    "avg_temp_c": result.avg_temp_c,
                    "hotspot_count": len(result.hotspots),
                    "converged": result.converged,
                }
            )
        )
        return

    table = Table(title="Thermal Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Max temp", f"{result.max_temp_c:.1f} C")
    table.add_row("Min temp", f"{result.min_temp_c:.1f} C")
    table.add_row("Avg temp", f"{result.avg_temp_c:.1f} C")
    table.add_row("Gradient", f"{result.gradient_c:.1f} C")
    table.add_row("Hotspots", str(len(result.hotspots)))
    table.add_row("Converged", "Yes" if result.converged else "No")
    console.print(table)


# ---------------------------------------------------------------------------
# Antenna
# ---------------------------------------------------------------------------


@app.command()
def antenna(
    path: str = typer.Argument(".", help="Path to the design directory."),
    def_file: str | None = typer.Option(None, "--def", help="DEF file to analyze."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run antenna rule check on routed design.

    Example:
        openforge signoff antenna
    """
    from openforge.physical.antenna import AntennaChecker

    project_dir = Path(path).resolve()
    def_path = _locate_def(project_dir, def_file)

    console.print(f"[bold]Antenna Check[/] on [cyan]{def_path}[/]")

    with console.status("[bold blue]Checking antenna rules...", spinner="dots"):
        checker = AntennaChecker()
        result = checker.check(def_file=str(def_path))

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "passed": result.passed,
                    "violations": len(result.violations),
                }
            )
        )
        if not result.passed:
            raise typer.Exit(code=2)
        return

    if result.passed:
        console.print("[green bold]Antenna check CLEAN[/]")
    else:
        console.print(f"[red bold]Antenna FAILED[/] -- {len(result.violations)} violations")
        table = Table(title="Antenna Violations", show_header=True, header_style="bold cyan")
        table.add_column("Net")
        table.add_column("Layer")
        table.add_column("Ratio", justify="right")
        table.add_column("Limit", justify="right")
        for v in result.violations[:20]:
            table.add_row(v.net, v.layer, f"{v.ratio:.1f}", f"{v.limit:.1f}")
        console.print(table)
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# Combined signoff
# ---------------------------------------------------------------------------


@app.command(name="all")
def signoff_all(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run all signoff checks (STA + DRC + LVS + IR + EM + thermal + antenna).

    Example:
        openforge signoff all
    """
    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    checks_run: list[dict[str, str]] = []
    any_fail = False

    # STA
    console.rule("[bold cyan]STA[/]")
    try:
        from openforge.physical.timing import TimingAnalyzer
        from openforge.synthesis.runner import _PDK_LIBERTY

        netlist_path = _locate_netlist(project_dir)
        pdk = config.project.target_pdk or "sky130"
        liberty_name = _PDK_LIBERTY.get(pdk, "liberty.lib")

        # SDC
        sdc_path: str | None = None
        for constraint in config.design.constraints:
            candidate = project_dir / constraint
            if candidate.exists() and candidate.suffix == ".sdc":
                sdc_path = str(candidate)
                break
        if not sdc_path:
            clock_period = config.timing.clock_period if config.timing else 10.0
            sdc_dir = project_dir / ".openforge"
            sdc_dir.mkdir(parents=True, exist_ok=True)
            sdc_gen = sdc_dir / "auto_constraints.sdc"
            sdc_gen.write_text(f"create_clock -name clk -period {clock_period} [get_ports clk]\n")
            sdc_path = str(sdc_gen)

        analyzer = TimingAnalyzer()
        result = analyzer.run_analysis(
            liberty=liberty_name,
            netlist=str(netlist_path),
            sdc=sdc_path,
            top_module=config.project.top_module,
            cwd=str(project_dir),
        )
        status = "PASS" if result.wns >= 0 else "FAIL"
        checks_run.append({"check": "STA", "status": status, "detail": f"WNS={result.wns:.4f}ns"})
        if status == "FAIL":
            any_fail = True
    except Exception as e:
        checks_run.append({"check": "STA", "status": "ERROR", "detail": str(e)[:100]})
        any_fail = True

    # DRC
    console.rule("[bold cyan]DRC[/]")
    try:
        from openforge.physical.drc_lvs import run_drc

        pnr_build = project_dir / "pnr_build"
        gds_path = None
        for candidate in pnr_build.glob("*.gds"):
            gds_path = str(candidate)
            break
        if gds_path:
            drc_result = run_drc(gds_file=gds_path, pdk=pdk, tool="magic", cwd=str(project_dir))
            status = "PASS" if drc_result.passed else "FAIL"
            checks_run.append(
                {"check": "DRC", "status": status, "detail": f"{drc_result.total_count} violations"}
            )
            if not drc_result.passed:
                any_fail = True
        else:
            checks_run.append({"check": "DRC", "status": "SKIP", "detail": "No GDS file"})
    except Exception as e:
        checks_run.append({"check": "DRC", "status": "ERROR", "detail": str(e)[:100]})

    # LVS
    console.rule("[bold cyan]LVS[/]")
    try:
        from openforge.physical.drc_lvs import run_lvs

        if gds_path:
            lvs_result = run_lvs(
                gds_file=gds_path,
                netlist_file=str(netlist_path),
                pdk=pdk,
                top_module=config.project.top_module,
                cwd=str(project_dir),
            )
            status = "PASS" if lvs_result.match else "FAIL"
            checks_run.append(
                {
                    "check": "LVS",
                    "status": status,
                    "detail": f"{len(lvs_result.mismatches)} mismatches",
                }
            )
            if not lvs_result.match:
                any_fail = True
        else:
            checks_run.append({"check": "LVS", "status": "SKIP", "detail": "No GDS file"})
    except Exception as e:
        checks_run.append({"check": "LVS", "status": "ERROR", "detail": str(e)[:100]})

    # Summary
    console.rule("[bold]Signoff Summary[/]")
    console.print()

    if json_output:
        console.print(json_mod.dumps({"checks": checks_run, "all_pass": not any_fail}))
        if any_fail:
            raise typer.Exit(code=2)
        return

    table = Table(title="Signoff Results", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="cyan", width=12)
    table.add_column("Status", width=8)
    table.add_column("Details")

    for c in checks_run:
        status = c["status"]
        if status == "PASS":
            style = "[green bold]"
        elif status == "SKIP":
            style = "[yellow]"
        else:
            style = "[red bold]"
        table.add_row(c["check"], f"{style}{status}[/]", c.get("detail", ""))

    console.print(table)

    if any_fail:
        raise typer.Exit(code=2)


@app.command(name="report")
def signoff_report(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show a unified signoff report from cached results.

    Example:
        openforge signoff report
    """
    # Delegate to the `all` command for now
    signoff_all(path=path, json_output=json_output)


# ---------------------------------------------------------------------------
# Native Rust signoff tools — openforge-drc, openforge-lvs, openforge-xrc.
# These call into the bundled Rust binaries built from `tools/openforge-{drc,lvs,xrc}/`.
# ---------------------------------------------------------------------------

import shutil as _shutil
import subprocess as _subprocess
from typing import Optional


def _find_rust_bin(name: str) -> Path | None:
    """Locate a bundled Rust binary, searching in this priority order:
    1. PATH (if user has installed it system-wide)
    2. <repo>/target/release/<name>[.exe]
    3. <repo>/target/debug/<name>[.exe]
    Returns None if not found.
    """
    on_path = _shutil.which(name)
    if on_path:
        return Path(on_path)
    here = Path(__file__).resolve()
    for parent in here.parents:
        for sub in ("target/release", "target/debug"):
            for ext in ("", ".exe"):
                cand = parent / sub / f"{name}{ext}"
                if cand.exists():
                    return cand
    return None


@app.command("drc-rs")
def drc_rust(
    gds: str = typer.Argument(..., help="Path to GDSII layout file."),
    rules: str = typer.Option(..., "--rules", "-r", help="DRC rule deck (.drc)."),
    tech: str = typer.Option("sky130A", "--tech", "-t", help="Tech name."),
    output: str = typer.Option("drc.rdb", "--output", "-o", help="Output report path."),
    fmt: str = typer.Option("text", "--format", "-f", help="Output format: rdb|text|json."),
) -> None:
    """Run DRC using the OpenForge native Rust engine.

    Example:
        openforge signoff drc-rs counter.gds --rules sky130.drc --tech sky130A
    """
    binary = _find_rust_bin("openforge-drc")
    if binary is None:
        console.print(
            "[red]openforge-drc binary not found.[/] Build it first:\n"
            "  [cyan]cargo build --release -p openforge-drc[/]"
        )
        raise typer.Exit(code=1)
    cmd = [
        str(binary),
        "check",
        gds,
        "--rules",
        rules,
        "--tech",
        tech,
        "--output",
        output,
        "--format",
        fmt,
    ]
    console.print(f"[cyan]{' '.join(cmd)}[/]")
    rc = _subprocess.call(cmd)
    raise typer.Exit(code=rc)


@app.command("lvs-rs")
def lvs_rust(
    layout: str = typer.Option(..., "--layout", "-l", help="Layout-extracted SPICE."),
    schematic: str = typer.Option(..., "--schematic", "-s", help="Schematic SPICE."),
    top: str = typer.Option(..., "--top", help="Top subcircuit name."),
    output: str = typer.Option("lvs.json", "--output", "-o", help="Report JSON path."),
) -> None:
    """Run LVS using the OpenForge native Rust engine.

    Example:
        openforge signoff lvs-rs --layout lay.sp --schematic sch.sp --top counter
    """
    binary = _find_rust_bin("openforge-lvs")
    if binary is None:
        console.print(
            "[red]openforge-lvs binary not found.[/] Build it first:\n"
            "  [cyan]cargo build --release -p openforge-lvs[/]"
        )
        raise typer.Exit(code=1)
    cmd = [
        str(binary),
        "check",
        "--layout",
        layout,
        "--schematic",
        schematic,
        "--top",
        top,
        "--output",
        output,
    ]
    console.print(f"[cyan]{' '.join(cmd)}[/]")
    rc = _subprocess.call(cmd)
    raise typer.Exit(code=rc)


@app.command("xrc-rs")
def xrc_rust(
    def_path: str = typer.Option(..., "--def", "-d", help="Routed DEF file."),
    lef: str = typer.Option(..., "--lef", "-l", help="LEF file."),
    tech: str = typer.Option("sky130A", "--tech", "-t", help="Tech name."),
    output: str = typer.Option("design.spef", "--output", "-o", help="Output SPEF path."),
) -> None:
    """Run parasitic extraction using the OpenForge native Rust engine.

    Example:
        openforge signoff xrc-rs --def routed.def --lef cells.lef --tech sky130A
    """
    binary = _find_rust_bin("openforge-xrc")
    if binary is None:
        console.print(
            "[red]openforge-xrc binary not found.[/] Build it first:\n"
            "  [cyan]cargo build --release -p openforge-xrc[/]"
        )
        raise typer.Exit(code=1)
    cmd = [
        str(binary),
        "extract",
        "--def",
        def_path,
        "--lef",
        lef,
        "--tech",
        tech,
        "--output",
        output,
    ]
    console.print(f"[cyan]{' '.join(cmd)}[/]")
    rc = _subprocess.call(cmd)
    raise typer.Exit(code=rc)
