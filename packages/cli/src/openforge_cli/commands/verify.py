"""openforge verify -- sim, formal, eqy, lint, cdc, regression."""

from __future__ import annotations

import json as json_mod
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="verify",
    help="Verification commands -- simulation, formal, lint, CDC, regression.",
    no_args_is_help=True,
)


def _load_config(project_dir: Path):
    from openforge.config.loader import ConfigNotFoundError, load_config

    try:
        return load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/].")
        raise typer.Exit(code=1)


def _resolve_sources(project_dir: Path, config: Any) -> list[str]:
    source_files: list[str] = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))
    return source_files


# ---------------------------------------------------------------------------
# sim
# ---------------------------------------------------------------------------


@app.command()
def sim(
    path: str = typer.Argument(".", help="Path to the design directory."),
    top: str | None = typer.Option(None, "--top", help="Top-level module."),
    tb: str | None = typer.Option(None, "--tb", help="Testbench file."),
    sim_tool: str = typer.Option(
        "icarus", "--sim", "-s", help="Simulator: verilator, icarus, ghdl."
    ),
    waves: bool = typer.Option(True, "--waves/--no-waves", "-w", help="Enable waveform tracing."),
    coverage: bool = typer.Option(False, "--coverage", help="Enable coverage collection."),
    merge: bool = typer.Option(False, "--merge", help="Merge coverage databases."),
    cov_report: bool = typer.Option(False, "--report", help="Show coverage report."),
    timeout: int = typer.Option(300, "--timeout", help="Simulation timeout (seconds)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Compile and run RTL simulation.

    Examples:
        openforge verify sim --sim verilator --waves
        openforge verify sim --tb tb/tb_counter.sv --coverage
        openforge verify sim --coverage --report
    """
    from openforge.runner.simulation import SimulationRunner

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    top_module = top or config.project.top_module
    source_files = _resolve_sources(project_dir, config)
    if not source_files:
        console.print("[red]Error:[/] no source files found.")
        raise typer.Exit(code=1)

    # Add testbench if specified
    if tb:
        tb_path = str(Path(tb).resolve())
        if tb_path not in source_files:
            source_files.append(tb_path)

    runner = SimulationRunner(project_dir, config)

    output_lines: list[str] = []

    def _on_output(line: str) -> None:
        output_lines.append(line)
        if verbose:
            console.print(f"  [dim]{line.rstrip()}[/]")

    if not quiet:
        console.print(f"[bold]Simulating[/] design at [cyan]{project_dir}[/] with {sim_tool}")
        console.print(f"  top     : [green]{top_module}[/]")
        console.print(f"  sources : [green]{len(source_files)} files[/]")
        console.print()

    # Compile
    if not quiet:
        console.print(f"  [bold]Compiling[/] with {sim_tool} ...")

    compile_result = runner.compile(
        tool=sim_tool,
        sources=source_files,
        top_module=top_module,
        on_output=_on_output,
    )

    if not compile_result.success:
        if json_output:
            console.print(
                json_mod.dumps(
                    {"status": "failed", "phase": "compile", "errors": compile_result.errors_count}
                )
            )
        else:
            console.print(f"[red bold]Compilation FAILED[/] ({compile_result.errors_count} errors)")
            if compile_result.log:
                for line in compile_result.log.splitlines()[-20:]:
                    console.print(f"  [red]{line}[/]")
        raise typer.Exit(code=1)

    # Simulate
    if not quiet:
        console.print("  [bold]Simulating[/] ...")

    sim_result = runner.simulate(tool=sim_tool, on_output=_on_output)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "status": "passed" if sim_result.success else "failed",
                    "duration_s": sim_result.duration,
                    "wave_file": sim_result.wave_file,
                }
            )
        )
        if not sim_result.success:
            raise typer.Exit(code=1)
        return

    if sim_result.success:
        console.print(f"[green bold]Simulation PASSED[/] in {sim_result.duration:.1f}s")
        if sim_result.wave_file:
            console.print(f"  Waveform: [cyan]{sim_result.wave_file}[/]")
    else:
        console.print(f"[red bold]Simulation FAILED[/] in {sim_result.duration:.1f}s")
        if sim_result.log:
            for line in sim_result.log.splitlines()[-20:]:
                console.print(f"  [red]{line}[/]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# formal
# ---------------------------------------------------------------------------


@app.command()
def formal(
    path: str = typer.Argument(".", help="Path to the design directory."),
    engine: str = typer.Option("smtbmc", "--engine", help="Formal engine: smtbmc, abc."),
    depth: int = typer.Option(20, "--depth", help="Bounded model checking depth."),
    mode: str = typer.Option("bmc", "--mode", help="Mode: bmc, prove, cover."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run formal verification with SymbiYosys.

    Examples:
        openforge verify formal --engine smtbmc --depth 50
        openforge verify formal --mode prove
        openforge verify formal --mode cover
    """
    from openforge.flow.formal import run_formal

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)
    source_files = _resolve_sources(project_dir, config)
    top_module = config.project.top_module

    context: dict[str, Any] = {
        "source_files": source_files,
        "top_module": top_module,
        "cwd": str(project_dir),
        "formal_depth": depth,
        "formal_engine": engine,
        "formal_mode": mode,
    }

    # Check for .sby file
    sby_files = list(project_dir.glob("*.sby"))
    if sby_files:
        context["sby_file"] = str(sby_files[0])
        if not json_output:
            console.print(f"  Using .sby file: [cyan]{sby_files[0].name}[/]")

    if not json_output:
        console.print(f"[bold]Formal verification[/] ({engine}/{mode}, depth={depth})")

    with console.status("[bold blue]Running formal verification...", spinner="dots"):
        result = run_formal(context)

    status_str = result.status.value.upper()

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "status": status_str,
                    "output": result.output[:1000] if result.output else "",
                    "errors": result.errors,
                }
            )
        )
        if status_str == "FAILED":
            raise typer.Exit(code=1)
        return

    if status_str == "PASSED":
        console.print("[green bold]Formal: All properties PROVEN[/]")
    elif status_str == "SKIPPED":
        console.print(f"[yellow]Formal: SKIPPED[/] -- {result.output or 'no properties'}")
    else:
        console.print("[red bold]Formal: FAILED[/]")
        for err in result.errors[:10]:
            console.print(f"  [red]{err[:200]}[/]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# eqy (equivalence checking)
# ---------------------------------------------------------------------------


@app.command()
def eqy(
    gold: str = typer.Option(..., "--gold", help="Gold (reference) netlist file."),
    gate: str = typer.Option(..., "--gate", help="Gate-level netlist file."),
    path: str = typer.Argument(".", help="Path to the design directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run equivalence checking between gold and gate netlists.

    Example:
        openforge verify eqy --gold rtl/design.v --gate synth_build/netlist.v
    """
    import shutil
    import subprocess

    project_dir = Path(path).resolve()

    eqy_bin = shutil.which("eqy")
    if not eqy_bin:
        console.print("[red]Error:[/] eqy (Yosys equivalence checker) not found.")
        raise typer.Exit(code=1)

    gold_path = Path(gold)
    gate_path = Path(gate)

    if not gold_path.exists():
        console.print(f"[red]Error:[/] gold file not found: {gold}")
        raise typer.Exit(code=1)
    if not gate_path.exists():
        console.print(f"[red]Error:[/] gate file not found: {gate}")
        raise typer.Exit(code=1)

    console.print("[bold]Equivalence Checking[/]")
    console.print(f"  gold : [cyan]{gold_path}[/]")
    console.print(f"  gate : [cyan]{gate_path}[/]")

    # Generate eqy config
    eqy_dir = project_dir / ".openforge" / "eqy"
    eqy_dir.mkdir(parents=True, exist_ok=True)
    eqy_config = eqy_dir / "check.eqy"
    eqy_config.write_text(
        f"[gold]\n"
        f"read -sv {gold_path}\n"
        f"prep\n\n"
        f"[gate]\n"
        f"read -sv {gate_path}\n"
        f"prep\n\n"
        f"[strategy sat]\n"
        f"use sat\n"
    )

    with console.status("[bold blue]Running equivalence check...", spinner="dots"):
        proc = subprocess.run(
            [eqy_bin, str(eqy_config)],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )

    passed = proc.returncode == 0

    if json_output:
        console.print(
            json_mod.dumps(
                {"status": "passed" if passed else "failed", "returncode": proc.returncode}
            )
        )
        if not passed:
            raise typer.Exit(code=1)
        return

    if passed:
        console.print("[green bold]Equivalence: MATCH[/]")
    else:
        console.print("[red bold]Equivalence: MISMATCH[/]")
        if proc.stdout:
            for line in proc.stdout.splitlines()[-20:]:
                console.print(f"  [red]{line}[/]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


@app.command()
def lint(
    path: str = typer.Argument(".", help="Path to the design directory."),
    files: list[str] | None = typer.Option(None, "--files", help="Specific files to lint."),
    rules: list[str] | None = typer.Option(None, "--rules", help="Specific lint rules to enable."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run Verible lint on HDL source files.

    Examples:
        openforge verify lint
        openforge verify lint --files rtl/counter.sv
    """
    from openforge.flow.lint import run_lint

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    if files:
        source_files = [str(Path(f).resolve()) for f in files]
    else:
        source_files = _resolve_sources(project_dir, config)

    if not source_files:
        console.print("[red]Error:[/] no source files found.")
        raise typer.Exit(code=1)

    if not json_output:
        console.print(f"[bold]Linting[/] {len(source_files)} files at [cyan]{project_dir}[/]")

    context: dict[str, Any] = {
        "source_files": source_files,
        "cwd": str(project_dir),
    }
    if rules:
        context["rules"] = rules

    result = run_lint(context)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "status": result.status.value,
                    "findings_count": result.artifacts.get("findings_count", "0"),
                }
            )
        )
        if result.status.value != "passed":
            raise typer.Exit(code=1)
        return

    if result.status.value == "passed":
        console.print(
            f"[green bold]LINT PASS[/] -- {result.artifacts.get('findings_count', '0')} findings"
        )
    else:
        console.print("[red bold]LINT FAIL[/]")
        if result.output:
            for line in result.output.splitlines()[:30]:
                console.print(f"  [red]{line}[/]")
        for err in result.errors[:10]:
            console.print(f"  [red]{err}[/]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# cdc
# ---------------------------------------------------------------------------


@app.command()
def cdc(
    path: str = typer.Argument(".", help="Path to the design directory."),
    top: str | None = typer.Option(None, "--top", help="Top-level module."),
    sdc: str | None = typer.Option(None, "--sdc", help="SDC file for clock definitions."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run clock-domain crossing (CDC) analysis.

    Example:
        openforge verify cdc --top my_design
    """
    from openforge.physical.cdc import CdcAnalyzer

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    top_module = top or config.project.top_module
    source_files = _resolve_sources(project_dir, config)

    console.print(f"[bold]CDC Analysis[/] for [green]{top_module}[/]")

    analyzer = CdcAnalyzer()

    with console.status("[bold blue]Running CDC analysis...", spinner="dots"):
        result = analyzer.analyze(
            sources=source_files,
            top_module=top_module,
            sdc_file=sdc,
            cwd=str(project_dir),
        )

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "crossings": result.crossing_count,
                    "violations": result.violation_count,
                    "clock_domains": result.clock_domains,
                }
            )
        )
        if result.violation_count > 0:
            raise typer.Exit(code=2)
        return

    table = Table(title="CDC Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Clock domains", str(result.clock_domains))
    table.add_row("Crossings", str(result.crossing_count))
    table.add_row("Violations", str(result.violation_count))
    console.print(table)

    if result.violation_count > 0:
        console.print(f"[red]{result.violation_count} CDC violations found[/]")
        raise typer.Exit(code=2)
    else:
        console.print("[green]CDC analysis clean[/]")


# ---------------------------------------------------------------------------
# regression
# ---------------------------------------------------------------------------


@app.command()
def regression(
    path: str = typer.Argument(".", help="Path to the design directory."),
    suite: str | None = typer.Option(None, "--suite", help="Test suite definition file."),
    parallel: int = typer.Option(1, "--parallel", "-j", help="Number of parallel test jobs."),
    seeds: int = typer.Option(1, "--seeds", help="Number of random seeds per test."),
    triage: str | None = typer.Option(None, "--triage", help="Triage results from a JSON file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run regression test suite.

    Examples:
        openforge verify regression --suite tests/suite.yaml --parallel 4
        openforge verify regression --seeds 10
        openforge verify regression --triage results.json
    """
    from openforge.runner.simulation import SimulationRunner

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    # Triage mode
    if triage:
        triage_path = Path(triage)
        if not triage_path.exists():
            console.print(f"[red]Error:[/] triage file not found: {triage}")
            raise typer.Exit(code=1)
        data = json_mod.loads(triage_path.read_text())
        failed = [t for t in data.get("tests", []) if t.get("status") != "passed"]
        if json_output:
            console.print(json_mod.dumps({"failed_count": len(failed), "failed_tests": failed}))
        else:
            console.print(
                f"[bold]Regression Triage:[/] {len(failed)} failures out of {len(data.get('tests', []))}"
            )
            for t in failed[:20]:
                console.print(
                    f"  [red]{t.get('name', 'unknown')}[/] -- {t.get('error', 'unknown error')[:100]}"
                )
        if failed:
            raise typer.Exit(code=1)
        return

    source_files = _resolve_sources(project_dir, config)
    if not source_files:
        console.print("[red]Error:[/] no source files found.")
        raise typer.Exit(code=1)

    top_module = config.project.top_module
    runner = SimulationRunner(project_dir, config)

    results: list[dict[str, Any]] = []
    total_pass = 0
    total_fail = 0

    if not json_output:
        console.print(f"[bold]Regression[/] at [cyan]{project_dir}[/]")
        console.print(f"  parallel : [green]{parallel}[/]")
        console.print(f"  seeds    : [green]{seeds}[/]")
        console.print()

    for seed in range(seeds):
        if not json_output:
            console.print(f"  [bold]Seed {seed}[/] ...")

        output_lines: list[str] = []

        def _on_output(line: str) -> None:
            output_lines.append(line)

        compile_result = runner.compile(
            tool="icarus",
            sources=source_files,
            top_module=top_module,
            on_output=_on_output,
        )

        if not compile_result.success:
            total_fail += 1
            results.append(
                {"name": f"seed_{seed}", "status": "failed", "error": "compilation failed"}
            )
            continue

        sim_result = runner.simulate(tool="icarus", on_output=_on_output)

        if sim_result.success:
            total_pass += 1
            results.append(
                {"name": f"seed_{seed}", "status": "passed", "duration": sim_result.duration}
            )
        else:
            total_fail += 1
            results.append(
                {"name": f"seed_{seed}", "status": "failed", "error": "simulation failed"}
            )

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "total": seeds,
                    "passed": total_pass,
                    "failed": total_fail,
                    "tests": results,
                }
            )
        )
        if total_fail > 0:
            raise typer.Exit(code=1)
        return

    # Summary
    table = Table(title="Regression Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Total tests", str(seeds))
    table.add_row("Passed", f"[green]{total_pass}[/]")
    table.add_row(
        "Failed", f"[red]{total_fail}[/]" if total_fail > 0 else f"[green]{total_fail}[/]"
    )
    console.print(table)

    if total_fail > 0:
        raise typer.Exit(code=1)
