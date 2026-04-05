"""openforge synth -- run synthesis flow."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

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
) -> None:
    """Synthesize the design for a target PDK."""
    if target not in _SUPPORTED_TARGETS:
        console.print(
            f"[red]Error:[/] unsupported target [bold]{target}[/]. "
            f"Choose from: {', '.join(_SUPPORTED_TARGETS)}"
        )
        raise typer.Exit(code=1)

    project_dir = Path(path).resolve()
    config_path = project_dir / "openforge.yaml"

    if not config_path.exists():
        console.print(f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/].")
        raise typer.Exit(code=1)

    # TODO: Parse openforge.yaml via openforge_core.config
    # TODO: Resolve top-level module from config if --top not given

    console.print(f"[bold]Synthesizing[/] design at [cyan]{project_dir}[/]")
    console.print(f"  target : [green]{target}[/]")
    console.print(f"  top    : [green]{top or '(from config)'}[/]")
    console.print(f"  output : [green]{output}[/]")
    console.print()

    # TODO: Dispatch to Yosys + OpenROAD / other synthesis backends
    #   1. Read source file list from config
    #   2. Run Yosys synthesis with target PDK liberty files
    #   3. Run STA (Static Timing Analysis)
    #   4. Produce area / timing / power reports
    #   5. Write netlist to output directory
    console.print("[yellow]synth: synthesis backend not yet implemented[/]")
