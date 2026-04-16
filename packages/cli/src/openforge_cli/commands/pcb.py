"""openforge pcb -- PCB design commands (ERC, DRC, Gerber, BOM, routing, export)."""

from __future__ import annotations

import json as json_mod
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="pcb",
    help="PCB design commands -- ERC, DRC, Gerber, BOM, routing, impedance, export.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# ERC
# ---------------------------------------------------------------------------


@app.command()
def erc(
    path: str = typer.Argument(".", help="Path to the design directory."),
    schematic: str | None = typer.Option(None, "--schematic", help="Schematic file to check."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run electrical rule check on a schematic.

    Examples:
        openforge pcb erc
        openforge pcb erc --schematic schematics/main.kicad_sch
    """
    from openforge.pcb.erc import ErcChecker

    project_dir = Path(path).resolve()

    # Find schematic
    sch_path = schematic
    if not sch_path:
        for ext in ("*.kicad_sch", "*.sch", "*.asc"):
            matches = list(project_dir.rglob(ext))
            if matches:
                sch_path = str(matches[0])
                break
    if not sch_path:
        console.print("[red]Error:[/] no schematic file found. Specify --schematic.")
        raise typer.Exit(code=1)

    console.print(f"[bold]ERC[/] on [cyan]{sch_path}[/]")

    checker = ErcChecker()
    with console.status("[bold blue]Running ERC...", spinner="dots"):
        result = checker.check(schematic_file=sch_path)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "passed": result.passed,
                    "errors": result.error_count,
                    "warnings": result.warning_count,
                }
            )
        )
        if not result.passed:
            raise typer.Exit(code=2)
        return

    if result.passed:
        console.print(f"[green bold]ERC CLEAN[/] -- {result.warning_count} warnings")
    else:
        console.print(
            f"[red bold]ERC FAILED[/] -- {result.error_count} errors, {result.warning_count} warnings"
        )
        for v in result.violations[:20]:
            style = "[red]" if v.severity == "error" else "[yellow]"
            console.print(f"  {style}{v.rule}: {v.message}[/]")
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# PCB DRC
# ---------------------------------------------------------------------------


@app.command()
def drc(
    path: str = typer.Argument(".", help="Path to the design directory."),
    board: str | None = typer.Option(None, "--board", help="Board file to check."),
    fab: str = typer.Option("jlcpcb", "--fab", help="Fab house rules: jlcpcb, oshpark, pcbway."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run PCB design rule check with fab-specific rules.

    Examples:
        openforge pcb drc --fab jlcpcb
        openforge pcb drc --board layout/board.kicad_pcb --fab oshpark
    """
    from openforge.pcb.drc import PcbDrcChecker
    from openforge.pcb.fab_rules import get_fab_rules

    project_dir = Path(path).resolve()

    board_path = board
    if not board_path:
        for ext in ("*.kicad_pcb", "*.pcb"):
            matches = list(project_dir.rglob(ext))
            if matches:
                board_path = str(matches[0])
                break
    if not board_path:
        console.print("[red]Error:[/] no board file found. Specify --board.")
        raise typer.Exit(code=1)

    console.print(f"[bold]PCB DRC[/] on [cyan]{board_path}[/] (fab: {fab})")

    rules = get_fab_rules(fab)
    checker = PcbDrcChecker(rules=rules)

    with console.status("[bold blue]Running PCB DRC...", spinner="dots"):
        result = checker.check(board_file=board_path)

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
        console.print("[green bold]PCB DRC CLEAN[/]")
    else:
        console.print(f"[red bold]PCB DRC FAILED[/] -- {len(result.violations)} violations")
        for v in result.violations[:20]:
            console.print(f"  [red]{v.rule}: {v.message}[/]")
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# Gerber
# ---------------------------------------------------------------------------


@app.command()
def gerber(
    path: str = typer.Argument(".", help="Path to the design directory."),
    output_dir: str = typer.Option("gerbers", "--output-dir", "-o", help="Output directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Export Gerber files for PCB fabrication.

    Example:
        openforge pcb gerber --output-dir gerbers/
    """
    from openforge.pcb.gerber import GerberExporter

    project_dir = Path(path).resolve()
    out = project_dir / output_dir
    out.mkdir(parents=True, exist_ok=True)

    # Find board
    board_path = None
    for ext in ("*.kicad_pcb", "*.pcb"):
        matches = list(project_dir.rglob(ext))
        if matches:
            board_path = str(matches[0])
            break
    if not board_path:
        console.print("[red]Error:[/] no board file found.")
        raise typer.Exit(code=1)

    console.print(f"[bold]Exporting Gerbers[/] from [cyan]{board_path}[/]")

    exporter = GerberExporter()
    with console.status("[bold blue]Generating Gerber files...", spinner="dots"):
        result = exporter.export(board_file=board_path, output_dir=str(out))

    if json_output:
        console.print(json_mod.dumps({"output_dir": str(out), "files": result.files}))
        return

    console.print("[green bold]Gerber export complete[/]")
    console.print(f"  Output: [cyan]{out}[/]")
    for f in result.files:
        console.print(f"  [dim]{f}[/]")


# ---------------------------------------------------------------------------
# Drill
# ---------------------------------------------------------------------------


@app.command()
def drill(
    path: str = typer.Argument(".", help="Path to the design directory."),
    output: str = typer.Option("gerbers/drill.drl", "--output", "-o", help="Output drill file."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Export drill file for PCB fabrication.

    Example:
        openforge pcb drill --output gerbers/drill.drl
    """
    from openforge.pcb.gerber import GerberExporter

    project_dir = Path(path).resolve()
    out_path = project_dir / output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    board_path = None
    for ext in ("*.kicad_pcb", "*.pcb"):
        matches = list(project_dir.rglob(ext))
        if matches:
            board_path = str(matches[0])
            break
    if not board_path:
        console.print("[red]Error:[/] no board file found.")
        raise typer.Exit(code=1)

    exporter = GerberExporter()
    with console.status("[bold blue]Generating drill file...", spinner="dots"):
        exporter.export_drill(board_file=board_path, output_file=str(out_path))

    console.print(f"[green]Drill file written to:[/] {out_path}")


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


@app.command()
def bom(
    path: str = typer.Argument(".", help="Path to the design directory."),
    output: str = typer.Option("bom.csv", "--output", "-o", help="Output BOM file."),
    fmt: str = typer.Option("csv", "--format", "-f", help="BOM format: csv, html."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Generate bill of materials.

    Examples:
        openforge pcb bom --output bom.csv
        openforge pcb bom --format html --output bom.html
    """
    from openforge.pcb.bom import BomGenerator

    project_dir = Path(path).resolve()
    out_path = project_dir / output

    schematic_path = None
    for ext in ("*.kicad_sch", "*.sch"):
        matches = list(project_dir.rglob(ext))
        if matches:
            schematic_path = str(matches[0])
            break
    if not schematic_path:
        console.print("[red]Error:[/] no schematic found for BOM generation.")
        raise typer.Exit(code=1)

    console.print(f"[bold]Generating BOM[/] from [cyan]{schematic_path}[/]")

    generator = BomGenerator()
    with console.status("[bold blue]Generating BOM...", spinner="dots"):
        bom_data = generator.generate(schematic_file=schematic_path, output_format=fmt)

    out_path.write_text(bom_data.content, encoding="utf-8")

    if json_output:
        console.print(json_mod.dumps({"output": str(out_path), "line_count": bom_data.line_count}))
        return

    console.print(f"[green]BOM written to:[/] {out_path} ({bom_data.line_count} lines)")


# ---------------------------------------------------------------------------
# Pick & Place
# ---------------------------------------------------------------------------


@app.command(name="pick-place")
def pick_place(
    path: str = typer.Argument(".", help="Path to the design directory."),
    output: str = typer.Option("pick_place.csv", "--output", "-o", help="Output file."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Export pick-and-place data for SMT assembly.

    Example:
        openforge pcb pick-place --output pnp.csv
    """
    from openforge.pcb.bom import BomGenerator

    project_dir = Path(path).resolve()
    out_path = project_dir / output

    board_path = None
    for ext in ("*.kicad_pcb", "*.pcb"):
        matches = list(project_dir.rglob(ext))
        if matches:
            board_path = str(matches[0])
            break
    if not board_path:
        console.print("[red]Error:[/] no board file found.")
        raise typer.Exit(code=1)

    generator = BomGenerator()
    with console.status("[bold blue]Generating pick & place data...", spinner="dots"):
        pnp_data = generator.generate_pick_place(board_file=board_path)

    out_path.write_text(pnp_data.content, encoding="utf-8")
    console.print(f"[green]Pick & place data written to:[/] {out_path}")


# ---------------------------------------------------------------------------
# Impedance
# ---------------------------------------------------------------------------


@app.command()
def impedance(
    width: float = typer.Option(0.15, "--width", help="Trace width in mm."),
    height: float = typer.Option(0.2, "--height", help="Dielectric height in mm."),
    er: float = typer.Option(4.5, "--er", help="Relative permittivity (Er)."),
    kind: str = typer.Option("microstrip", "--kind", help="Type: microstrip or stripline."),
    thickness: float = typer.Option(0.035, "--thickness", help="Copper thickness in mm."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Calculate trace impedance for PCB design.

    Examples:
        openforge pcb impedance --width 0.15 --height 0.2 --er 4.5
        openforge pcb impedance --kind stripline --width 0.1
    """
    from openforge.pcb.impedance import calculate_impedance

    result = calculate_impedance(
        width_mm=width,
        height_mm=height,
        er=er,
        kind=kind,
        thickness_mm=thickness,
    )

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "impedance_ohm": result.impedance_ohm,
                    "kind": kind,
                    "width_mm": width,
                    "height_mm": height,
                    "er": er,
                }
            )
        )
        return

    table = Table(title="Impedance Calculation", show_header=True, header_style="bold cyan")
    table.add_column("Parameter", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Type", kind)
    table.add_row("Width", f"{width:.3f} mm")
    table.add_row("Dielectric height", f"{height:.3f} mm")
    table.add_row("Er", f"{er:.2f}")
    table.add_row("Cu thickness", f"{thickness:.3f} mm")
    table.add_row("Impedance", f"[bold green]{result.impedance_ohm:.1f} Ohm[/]")
    console.print(table)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@app.command()
def route(
    path: str = typer.Argument(".", help="Path to the design directory."),
    engine: str = typer.Option(
        "builtin", "--engine", help="Routing engine: builtin or freerouting."
    ),
    nets: list[str] | None = typer.Option(None, "--nets", help="Specific nets to route."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Auto-route PCB traces.

    Examples:
        openforge pcb route --engine freerouting
        openforge pcb route --nets VCC GND CLK
    """
    from openforge.pcb.router import PcbRouter, RoutingMode

    project_dir = Path(path).resolve()

    board_path = None
    for ext in ("*.kicad_pcb", "*.pcb"):
        matches = list(project_dir.rglob(ext))
        if matches:
            board_path = str(matches[0])
            break
    if not board_path:
        console.print("[red]Error:[/] no board file found.")
        raise typer.Exit(code=1)

    router = PcbRouter()
    mode = RoutingMode.FREEROUTING if engine == "freerouting" else RoutingMode.BUILTIN

    console.print(f"[bold]Routing[/] with [green]{engine}[/] on [cyan]{board_path}[/]")

    with console.status("[bold blue]Auto-routing...", spinner="dots"):
        result = router.route(
            board_file=board_path,
            mode=mode,
            net_filter=nets,
        )

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "routed": result.routed_count,
                    "unrouted": result.unrouted_count,
                    "total_length_mm": result.total_length_mm,
                }
            )
        )
        return

    table = Table(title="Routing Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Routed", str(result.routed_count))
    table.add_row("Unrouted", str(result.unrouted_count))
    table.add_row("Total length", f"{result.total_length_mm:.1f} mm")
    console.print(table)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@app.command()
def export(
    path: str = typer.Argument(".", help="Path to the design directory."),
    ipc2581: bool = typer.Option(False, "--ipc2581", help="Export IPC-2581."),
    odbpp: bool = typer.Option(False, "--odbpp", help="Export ODB++."),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file or directory."),
    output_dir: str | None = typer.Option(
        None, "--output-dir", help="Output directory (for ODB++)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Export PCB design in industry-standard formats.

    Examples:
        openforge pcb export --ipc2581 --output design.xml
        openforge pcb export --odbpp --output-dir odbpp_out/
    """
    project_dir = Path(path).resolve()

    board_path = None
    for ext in ("*.kicad_pcb", "*.pcb"):
        matches = list(project_dir.rglob(ext))
        if matches:
            board_path = str(matches[0])
            break
    if not board_path:
        console.print("[red]Error:[/] no board file found.")
        raise typer.Exit(code=1)

    if ipc2581:
        from openforge.pcb.ipc2581 import Ipc2581Exporter

        out = output or str(project_dir / "export" / "design.xml")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        exporter = Ipc2581Exporter()

        with console.status("[bold blue]Exporting IPC-2581...", spinner="dots"):
            exporter.export(board_file=board_path, output_file=out)

        console.print(f"[green]IPC-2581 exported to:[/] {out}")

    if odbpp:
        from openforge.pcb.odbpp import OdbppExporter

        out_dir = output_dir or str(project_dir / "export" / "odbpp")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        exporter = OdbppExporter()

        with console.status("[bold blue]Exporting ODB++...", spinner="dots"):
            exporter.export(board_file=board_path, output_dir=out_dir)

        console.print(f"[green]ODB++ exported to:[/] {out_dir}")

    if not ipc2581 and not odbpp:
        console.print("[yellow]Specify --ipc2581 or --odbpp.[/]")
        raise typer.Exit(code=1)
