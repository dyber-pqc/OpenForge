"""openforge synth -- run synthesis flow."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

# Supported PDK targets
_SUPPORTED_TARGETS = [
    "sky130",
    "gf180mcu",
    "asap7",
    "nangate45",
]


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
        help="Top-level module name (defaults to project name from openforge.yaml).",
    ),
    output: str = typer.Option(
        "build",
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
    flatten: bool = typer.Option(False, "--flatten", help="Flatten hierarchy before mapping."),
) -> None:
    """Synthesize the design for a target PDK."""
    from openforge.config.loader import ConfigNotFoundError, load_config
    from openforge.synthesis.runner import SynthesisRunner

    if target not in _SUPPORTED_TARGETS:
        console.print(
            f"[red]Error:[/] unsupported target [bold]{target}[/]. "
            f"Choose from: {', '.join(_SUPPORTED_TARGETS)}"
        )
        raise typer.Exit(code=1)

    project_dir = Path(path).resolve()

    # Load config
    try:
        config = load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/]. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(code=1)

    # Resolve top module
    top_module = top or config.project.top_module

    # Resolve source files
    source_files: list[str] = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))

    if not source_files:
        console.print(
            "[red]Error:[/] no source files found. "
            "Check [cyan]design.sources[/] globs in openforge.yaml."
        )
        raise typer.Exit(code=1)

    console.print(f"[bold]Synthesizing[/] design at [cyan]{project_dir}[/]")
    console.print(f"  target    : [green]{target}[/]")
    console.print(f"  top       : [green]{top_module}[/]")
    console.print(f"  sources   : [green]{len(source_files)} files[/]")
    console.print(f"  output    : [green]{output}[/]")
    if frequency:
        console.print(f"  frequency : [green]{frequency} MHz[/]")
    console.print()

    # Create runner and execute
    try:
        runner = SynthesisRunner(project_dir, config)
    except Exception as e:
        console.print(f"[red]Error initializing synthesis runner:[/] {e}")
        console.print(
            "[dim]Hint: ensure Yosys is installed. "
            "Run [bold]openforge tools[/] to check.[/]"
        )
        raise typer.Exit(code=1)

    output_lines: list[str] = []

    def _on_output(line: str) -> None:
        output_lines.append(line)

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

    # Display results
    console.print(f"[green bold]Synthesis PASSED[/] in {result.duration:.1f}s")
    console.print()

    # Summary table
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
    if result.warnings:
        console.print()
        console.print(f"[yellow]Warnings ({len(result.warnings)}):[/]")
        for warn in result.warnings[:10]:
            console.print(f"  [yellow]{warn[:200]}[/]")
        if len(result.warnings) > 10:
            console.print(f"  [dim]... and {len(result.warnings) - 10} more[/]")
