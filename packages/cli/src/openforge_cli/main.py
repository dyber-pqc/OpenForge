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
        "coverage": config.verification.simulation.coverage.line if config.verification and config.verification.simulation else False,
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
    project_dir = Path(path).resolve()
    console.print(f"[bold]Analyzing[/] design at [cyan]{project_dir}[/] ...")

    checks = []
    if timing:
        checks.append("timing")
    if power:
        checks.append("power")
    if area:
        checks.append("area")
    if not checks:
        checks = ["timing", "area"]

    for check in checks:
        console.print(f"  Running {check} analysis ...")
        # TODO: Wire to real engines when STA/power flows are built
        console.print(f"  [yellow]{check}: coming in Phase 4[/]")


@app.command()
def report(
    path: str = typer.Argument(".", help="Path to the design directory."),
    format: str = typer.Option("html", "--format", "-f", help="Report format (html, json, sarif, junit)."),
    output: str = typer.Option("reports/", "--output", "-o", help="Output directory."),
) -> None:
    """Generate a verification / synthesis report."""
    from openforge.report.generator import generate_report

    project_dir = Path(path).resolve()
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Generating[/] {format} report for [cyan]{project_dir}[/] ...")

    try:
        report_path = generate_report(
            project_dir=project_dir,
            output_dir=output_dir,
            format=format,
        )
        console.print(f"[green]Report written to:[/] {report_path}")
    except Exception as e:
        console.print(f"[red]Error generating report:[/] {e}")
        raise typer.Exit(1)


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

    for engine in engines:
        name = engine.BINARY
        installed = engine.check_installed()
        version = engine.version() if installed else "-"
        status = "[green]OK[/]" if installed else "[red]Missing[/]"
        table.add_row(name, status, version)

    console.print(table)


if __name__ == "__main__":
    app()
