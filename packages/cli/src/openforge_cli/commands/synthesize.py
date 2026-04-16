"""openforge synth -- run synthesis flow with full CLI parity."""

from __future__ import annotations

import json as json_mod
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

# Supported PDK targets
_SUPPORTED_TARGETS = [
    "generic",
    "sky130",
    "gf180mcu",
    "asap7",
    "nangate45",
    "ice40",
    "ecp5",
    "gowin",
]


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


def _resolve_sources(project_dir: Path, config) -> list[str]:
    source_files: list[str] = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))
    return source_files


def synth(
    path: str = typer.Argument(".", help="Path to the design directory."),
    target: str = typer.Option(
        "sky130",
        "--target",
        "-t",
        help=f"Target PDK for synthesis ({', '.join(_SUPPORTED_TARGETS)}).",
    ),
    top: str | None = typer.Option(
        None,
        "--top",
        help="Top-level module name (defaults to config).",
    ),
    output: str = typer.Option(
        "synth_build",
        "--output",
        "-o",
        help="Output directory for synthesis artifacts.",
    ),
    frequency: float | None = typer.Option(
        None,
        "--frequency",
        "-f",
        help="Target clock frequency in MHz.",
    ),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        "-s",
        help="Synthesis strategy: area, speed, or balanced.",
    ),
    flatten: bool = typer.Option(False, "--flatten", help="Flatten hierarchy before mapping."),
    report: bool = typer.Option(False, "--report", help="Show synthesis report after completion."),
    schematic: str | None = typer.Option(
        None,
        "--schematic",
        help="Export schematic view to SVG file.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON result."),
) -> None:
    """Synthesize the design for a target PDK.

    Examples:
        openforge synth --target sky130
        openforge synth --top counter --target ice40 --strategy area
        openforge synth --report
        openforge synth --schematic netlist.svg
    """
    from openforge.synthesis.runner import SynthesisRunner

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    # Resolve top module
    top_module = top or config.project.top_module

    # Resolve source files
    source_files = _resolve_sources(project_dir, config)
    if not source_files:
        console.print(
            "[red]Error:[/] no source files found. "
            "Check [cyan]design.sources[/] globs in openforge.yaml."
        )
        raise typer.Exit(code=1)

    # Report-only mode: show last synthesis results
    if report and not schematic:
        _show_report(project_dir, output, json_output)
        return

    if not quiet:
        console.print(f"[bold]Synthesizing[/] design at [cyan]{project_dir}[/]")
        console.print(f"  target    : [green]{target}[/]")
        console.print(f"  top       : [green]{top_module}[/]")
        console.print(f"  sources   : [green]{len(source_files)} files[/]")
        console.print(f"  output    : [green]{output}[/]")
        if strategy:
            console.print(f"  strategy  : [green]{strategy}[/]")
        if frequency:
            console.print(f"  frequency : [green]{frequency} MHz[/]")
        console.print()

    # Create runner and execute
    try:
        runner = SynthesisRunner(project_dir, config)
    except Exception as e:
        console.print(f"[red]Error initializing synthesis runner:[/] {e}")
        console.print(
            "[dim]Hint: ensure Yosys is installed. Run [bold]openforge tools list[/] to check.[/]"
        )
        raise typer.Exit(code=1)

    output_lines: list[str] = []

    def _on_output(line: str) -> None:
        output_lines.append(line)
        if verbose:
            console.print(f"  [dim]{line.rstrip()}[/]")

    with console.status("[bold blue]Running synthesis...", spinner="dots"):
        result = runner.run_synthesis(
            sources=source_files,
            top_module=top_module,
            pdk=target,
            target_frequency=frequency,
            flatten=flatten,
            output_dir=project_dir / output,
            on_output=_on_output,
        )

    if not result.success:
        if json_output:
            console.print(
                json_mod.dumps(
                    {
                        "status": "failed",
                        "errors": result.errors[:20],
                    }
                )
            )
        else:
            console.print("[red bold]Synthesis FAILED[/]")
            console.print()
            for err in result.errors[:20]:
                console.print(f"  [red]{err[:200]}[/]")
            if result.log:
                console.print()
                console.print("[dim]--- Last 30 lines of log ---[/]")
                for line in result.log.splitlines()[-30:]:
                    console.print(f"  [dim]{line}[/]")
        raise typer.Exit(code=1)

    # JSON output
    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "status": "passed",
                    "gate_count": result.gate_count,
                    "area_um2": result.area_um2,
                    "timing_estimate_ns": result.timing_estimate_ns,
                    "warnings": len(result.warnings),
                    "netlist_path": result.netlist_path,
                    "cell_usage": result.cell_usage,
                    "duration_s": result.duration,
                }
            )
        )
        return

    # Display results
    if not quiet:
        console.print(f"[green bold]Synthesis PASSED[/] in {result.duration:.1f}s")
        console.print()

    summary = Table(title="Synthesis Summary", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")

    summary.add_row("Gate count", f"{result.gate_count:,}")
    summary.add_row("Area", f"{result.area_um2:,.1f} um^2")
    if result.timing_estimate_ns > 0:
        summary.add_row("Timing estimate", f"{result.timing_estimate_ns:.2f} ns")
    summary.add_row("Warnings", f"{len(result.warnings)}")
    summary.add_row("Netlist", result.netlist_path)

    console.print(summary)

    # Cell usage top-10
    if result.cell_usage:
        cell_table = Table(title="Cell Usage (top 10)", show_header=True, header_style="bold cyan")
        cell_table.add_column("Cell Type", style="bold")
        cell_table.add_column("Count", justify="right")

        sorted_cells = sorted(result.cell_usage.items(), key=lambda x: x[1], reverse=True)
        for cell_name, count in sorted_cells[:10]:
            cell_table.add_row(cell_name, f"{count:,}")

        if len(sorted_cells) > 10:
            remaining = sum(c for _, c in sorted_cells[10:])
            cell_table.add_row(f"... ({len(sorted_cells) - 10} more)", f"{remaining:,}")

        console.print()
        console.print(cell_table)

    # Warnings
    if result.warnings and not quiet:
        console.print()
        console.print(f"[yellow]Warnings ({len(result.warnings)}):[/]")
        for warn in result.warnings[:10]:
            console.print(f"  [yellow]{warn[:200]}[/]")
        if len(result.warnings) > 10:
            console.print(f"  [dim]... and {len(result.warnings) - 10} more[/]")

    # Schematic export
    if schematic:
        _export_schematic(project_dir / output, schematic)


def _show_report(project_dir: Path, build_dir: str, json_output: bool) -> None:
    """Display the last synthesis report."""
    from openforge.synthesis.runner import _parse_stat_output

    synth_build = project_dir / build_dir
    netlist_path = synth_build / "netlist.v"

    if not netlist_path.exists():
        console.print(
            "[red]Error:[/] no synthesized netlist found. Run [bold]openforge synth[/] first."
        )
        raise typer.Exit(code=1)

    # Find synthesis log
    synth_log = ""
    for log_candidate in synth_build.glob("*.log"):
        synth_log = log_candidate.read_text()
        break
    if not synth_log:
        for stat_candidate in [synth_build / "stats_incr.txt", synth_build / "stats.txt"]:
            if stat_candidate.exists():
                synth_log = stat_candidate.read_text()
                break

    if not synth_log:
        console.print("[yellow]No synthesis statistics found.[/]")
        raise typer.Exit(code=1)

    gate_count, cell_usage, area = _parse_stat_output(synth_log)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "gate_count": gate_count,
                    "area_um2": area,
                    "cell_types": len(cell_usage),
                    "cell_usage": cell_usage,
                }
            )
        )
        return

    area_table = Table(title="Synthesis Report", show_header=True, header_style="bold cyan")
    area_table.add_column("Metric", style="bold")
    area_table.add_column("Value", justify="right")
    area_table.add_row("Gate count", f"{gate_count:,}")
    area_table.add_row("Chip area", f"{area:,.1f} um^2")
    area_table.add_row("Cell types", f"{len(cell_usage)}")
    console.print(area_table)

    if cell_usage:
        cell_table = Table(title="Cell Usage", show_header=True, header_style="bold cyan")
        cell_table.add_column("Cell Type", style="bold")
        cell_table.add_column("Count", justify="right")
        sorted_cells = sorted(cell_usage.items(), key=lambda x: x[1], reverse=True)
        for name, count in sorted_cells[:20]:
            cell_table.add_row(name, f"{count:,}")
        console.print(cell_table)


def _export_schematic(synth_build: Path, output_path: str) -> None:
    """Export synthesized netlist as SVG schematic."""
    netlist_json = synth_build / "netlist.json"
    if not netlist_json.exists():
        console.print("[yellow]No netlist.json found for schematic export.[/]")
        console.print("[dim]Hint: run synthesis with JSON output enabled.[/]")
        return

    # Use netlistsvg or yosys show command if available
    import shutil
    import subprocess

    netlistsvg = shutil.which("netlistsvg")
    if netlistsvg:
        try:
            subprocess.run(
                [netlistsvg, str(netlist_json), "-o", output_path],
                check=True,
                capture_output=True,
            )
            console.print(f"[green]Schematic exported to:[/] {output_path}")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error running netlistsvg:[/] {e.stderr.decode()[:200]}")
    else:
        console.print("[yellow]netlistsvg not found.[/] Install with: npm install -g netlistsvg")
        console.print(f"  [dim]Netlist JSON at: {netlist_json}[/]")
