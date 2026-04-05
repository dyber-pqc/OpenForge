"""openforge verify -- run verification flows."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def verify(
    path: str = typer.Argument(".", help="Path to the design directory."),
    sim: bool = typer.Option(False, "--sim", "-s", help="Run simulation-based verification."),
    formal: bool = typer.Option(False, "--formal", "-f", help="Run formal verification."),
    crypto: bool = typer.Option(False, "--crypto", "-c", help="Run crypto-specific property checks."),
    all_: bool = typer.Option(False, "--all", "-a", help="Run all verification engines."),
) -> None:
    """Run verification on a design.

    At least one engine flag must be provided, or use --all.
    """
    engines: list[str] = []
    if all_:
        engines = ["sim", "formal", "crypto"]
    else:
        if sim:
            engines.append("sim")
        if formal:
            engines.append("formal")
        if crypto:
            engines.append("crypto")

    if not engines:
        console.print("[red]Error:[/] specify at least one engine (--sim, --formal, --crypto) or --all.")
        raise typer.Exit(code=1)

    project_dir = Path(path).resolve()
    config_path = project_dir / "openforge.yaml"

    if not config_path.exists():
        console.print(f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/].")
        raise typer.Exit(code=1)

    # TODO: Parse openforge.yaml via openforge_core.config
    console.print(f"[bold]Verifying[/] design at [cyan]{project_dir}[/]")

    table = Table(title="Verification Plan")
    table.add_column("Engine", style="cyan")
    table.add_column("Status", style="yellow")

    for engine in engines:
        # TODO: Dispatch to actual verification engine runners
        #   sim    -> cocotb / Verilator / Icarus
        #   formal -> SymbiYosys / Jasper
        #   crypto -> custom crypto property checker
        table.add_row(engine, "pending -- not yet implemented")

    console.print(table)
    console.print("[yellow]verify: engine dispatch not yet implemented[/]")
