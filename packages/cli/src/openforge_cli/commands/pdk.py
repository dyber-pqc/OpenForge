"""openforge pdk -- PDK management commands."""

from __future__ import annotations

import json as json_mod

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="pdk",
    help="PDK management -- list, install, info.",
    no_args_is_help=True,
)


@app.command(name="list")
def list_pdks(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """List all known and installed PDKs.

    Example:
        openforge pdk list
    """
    from openforge.pdk import PdkManager

    mgr = PdkManager()
    pdks = mgr.list_pdks()

    if json_output:
        console.print(json_mod.dumps([
            {
                "name": p.name,
                "display_name": p.display_name,
                "foundry": p.foundry,
                "node_nm": p.process_node_nm,
                "installed": p.installed,
                "path": str(p.install_path) if p.install_path else None,
                "libraries": p.cell_libraries,
            }
            for p in pdks
        ]))
        return

    table = Table(title="OpenForge PDKs", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Display Name")
    table.add_column("Foundry")
    table.add_column("Node (nm)", justify="right")
    table.add_column("Status")
    table.add_column("Libraries")

    for p in pdks:
        status = "[green]Installed[/]" if p.installed else "[dim]Not installed[/]"
        libs = ", ".join(p.cell_libraries[:3])
        if len(p.cell_libraries) > 3:
            libs += f" +{len(p.cell_libraries) - 3}"
        table.add_row(
            p.name,
            p.display_name,
            p.foundry,
            str(p.process_node_nm),
            status,
            libs,
        )

    console.print(table)


@app.command()
def install(
    pdk_name: str = typer.Argument(..., help="PDK to install (e.g. sky130A, gf180mcuC, asap7)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Install a PDK.

    Examples:
        openforge pdk install sky130A
        openforge pdk install gf180mcuC
        openforge pdk install asap7
    """
    from openforge.pdk import PdkManager

    mgr = PdkManager()

    # Check known PDKs
    pdk_info = mgr.get_pdk(pdk_name)

    # Also check the installer registry
    if not pdk_info:
        try:
            from openforge.pdk.installer import PdkInstaller

            installer = PdkInstaller()
            if pdk_name in installer.KNOWN_PDKS:
                console.print(f"[bold]Installing PDK:[/] [cyan]{pdk_name}[/] via PdkInstaller ...")

                def _progress(msg: str, pct: float) -> None:
                    if verbose:
                        console.print(f"  [dim]{msg} ({pct:.0%})[/]")

                success = installer.install(pdk_name, progress_callback=_progress)
                if success:
                    if json_output:
                        console.print(json_mod.dumps({"status": "installed", "pdk": pdk_name}))
                    else:
                        console.print(f"[green bold]PDK {pdk_name} installed successfully![/]")
                    return
                else:
                    console.print(f"[red]PDK installation failed for {pdk_name}.[/]")
                    raise typer.Exit(code=1)
        except ImportError:
            pass

        console.print(f"[red]Error:[/] unknown PDK [bold]{pdk_name}[/].")
        console.print("[dim]Run [bold]openforge pdk list[/] to see available PDKs.[/]")
        raise typer.Exit(code=1)

    if pdk_info.installed:
        console.print(f"[yellow]PDK {pdk_name} is already installed at {pdk_info.install_path}.[/]")
        return

    console.print(f"[bold]Installing PDK:[/] [cyan]{pdk_name}[/] ({pdk_info.display_name})")

    def _progress(msg: str, pct: float) -> None:
        if verbose or pct in (0.0, 1.0):
            console.print(f"  [dim]{msg} ({pct:.0%})[/]")

    with console.status(f"[bold blue]Installing {pdk_name}...", spinner="dots"):
        success = mgr.install(pdk_name, progress_callback=_progress)

    if success:
        if json_output:
            console.print(json_mod.dumps({"status": "installed", "pdk": pdk_name}))
        else:
            console.print(f"[green bold]PDK {pdk_name} installed successfully![/]")
    else:
        console.print("[red]PDK installation failed.[/] Check network connection and git availability.")
        raise typer.Exit(code=1)


@app.command()
def info(
    pdk_name: str = typer.Argument(..., help="PDK name."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show detailed information about a PDK.

    Example:
        openforge pdk info sky130
    """
    from openforge.pdk import PdkManager

    mgr = PdkManager()
    pdk_info = mgr.get_pdk(pdk_name)

    if not pdk_info:
        # Try installer registry
        try:
            from openforge.pdk.installer import PdkInstaller

            installer = PdkInstaller()
            if pdk_name in installer.KNOWN_PDKS:
                inst_info = installer.KNOWN_PDKS[pdk_name]
                if json_output:
                    console.print(json_mod.dumps({
                        "name": inst_info.name,
                        "foundry": inst_info.foundry,
                        "vendor": inst_info.vendor,
                        "node_nm": inst_info.node_nm,
                        "license": inst_info.license,
                        "url": inst_info.sources_url,
                        "supported_libs": inst_info.supported_libs,
                    }))
                else:
                    table = Table(title=f"PDK: {pdk_name}", show_header=True, header_style="bold cyan")
                    table.add_column("Property", style="bold")
                    table.add_column("Value")
                    table.add_row("Name", inst_info.name)
                    table.add_row("Foundry", inst_info.foundry)
                    table.add_row("Vendor", inst_info.vendor)
                    table.add_row("Node", f"{inst_info.node_nm} nm")
                    table.add_row("License", inst_info.license)
                    table.add_row("URL", inst_info.sources_url)
                    table.add_row("Libraries", ", ".join(inst_info.supported_libs[:5]))
                    console.print(table)
                return
        except ImportError:
            pass

        console.print(f"[red]Error:[/] unknown PDK [bold]{pdk_name}[/].")
        raise typer.Exit(code=1)

    if json_output:
        console.print(json_mod.dumps({
            "name": pdk_info.name,
            "display_name": pdk_info.display_name,
            "foundry": pdk_info.foundry,
            "node_nm": pdk_info.process_node_nm,
            "installed": pdk_info.installed,
            "install_path": str(pdk_info.install_path) if pdk_info.install_path else None,
            "libraries": pdk_info.cell_libraries,
            "tech_lef": str(pdk_info.tech_lef) if pdk_info.tech_lef else None,
            "merged_lef": str(pdk_info.merged_lef) if pdk_info.merged_lef else None,
            "corners": {
                lib: [{"name": c.name, "process": c.process, "temp": c.temperature, "voltage": c.voltage}
                      for c in corners]
                for lib, corners in pdk_info.corners.items()
            },
        }))
        return

    table = Table(title=f"PDK: {pdk_info.display_name}", show_header=True, header_style="bold cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Name", pdk_info.name)
    table.add_row("Display name", pdk_info.display_name)
    table.add_row("Foundry", pdk_info.foundry)
    table.add_row("Node", f"{pdk_info.process_node_nm} nm")
    table.add_row("Installed", "[green]Yes[/]" if pdk_info.installed else "[red]No[/]")
    if pdk_info.install_path:
        table.add_row("Path", str(pdk_info.install_path))
    if pdk_info.tech_lef:
        table.add_row("Tech LEF", str(pdk_info.tech_lef))
    if pdk_info.merged_lef:
        table.add_row("Merged LEF", str(pdk_info.merged_lef))
    table.add_row("Libraries", ", ".join(pdk_info.cell_libraries))

    console.print(table)

    # Show corners
    if pdk_info.corners:
        for lib_name, corners in pdk_info.corners.items():
            corner_table = Table(
                title=f"Corners: {lib_name}",
                show_header=True,
                header_style="bold cyan",
            )
            corner_table.add_column("Corner")
            corner_table.add_column("Process")
            corner_table.add_column("Temperature", justify="right")
            corner_table.add_column("Voltage", justify="right")

            for c in corners:
                corner_table.add_row(c.name, c.process, f"{c.temperature:.0f} C", f"{c.voltage:.2f} V")

            console.print(corner_table)
