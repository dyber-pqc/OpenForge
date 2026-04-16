"""openforge tools -- tool management commands."""

from __future__ import annotations

import json as json_mod
import shutil
import subprocess

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="tools",
    help="EDA tool management -- list, install, check health.",
    no_args_is_help=True,
)


# Tool registry: (name, engine_class_path, binary)
_TOOL_REGISTRY: list[tuple[str, str, str]] = [
    ("yosys", "openforge.engine.yosys.YosysEngine", "yosys"),
    ("verilator", "openforge.engine.verilator.VerilatorEngine", "verilator"),
    ("verible", "openforge.engine.verible.VeribleEngine", "verible-verilog-lint"),
    ("icarus", "openforge.engine.icarus.IcarusEngine", "iverilog"),
    ("ghdl", "openforge.engine.ghdl.GHDLEngine", "ghdl"),
    ("symbiyosys", "openforge.engine.symbiyosys.SymbiYosysEngine", "sby"),
    ("opensta", "openforge.engine.opensta.OpenSTAEngine", "sta"),
    ("openroad", "openforge.engine.openroad.OpenROADEngine", "openroad"),
    ("nextpnr-ice40", "openforge.engine.nextpnr.NextpnrEngine", "nextpnr-ice40"),
    ("nextpnr-ecp5", "openforge.engine.nextpnr.NextpnrEngine", "nextpnr-ecp5"),
    ("magic", "openforge.engine.magic.MagicEngine", "magic"),
    ("netgen", "openforge.engine.netgen.NetgenEngine", "netgen"),
    ("klayout", "openforge.engine.klayout.KLayoutEngine", "klayout"),
    ("ngspice", "openforge.engine.ngspice.NgspiceEngine", "ngspice"),
    ("openFPGALoader", "openforge.engine.openfpgaloader.OpenFPGALoaderEngine", "openFPGALoader"),
]


def _load_engine(class_path: str):
    """Dynamically import and instantiate an engine class."""
    module_path, class_name = class_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


@app.command(name="list")
def list_tools(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show all detected EDA tools with versions.

    Example:
        openforge tools list
    """
    results: list[dict[str, str]] = []

    for name, class_path, binary in _TOOL_REGISTRY:
        try:
            engine = _load_engine(class_path)
            installed = engine.check_installed()
            version = engine.version() if installed else "-"
            status_str = "OK" if installed else "Missing"
        except Exception:
            # Fallback: just check binary on PATH
            installed = shutil.which(binary) is not None
            version = "-"
            status_str = "OK (binary)" if installed else "Missing"

        results.append(
            {
                "name": name,
                "binary": binary,
                "status": status_str,
                "version": version,
                "installed": str(installed),
            }
        )

    if json_output:
        console.print(json_mod.dumps(results))
        return

    table = Table(title="OpenForge Tool Status", show_header=True, header_style="bold cyan")
    table.add_column("Tool", style="cyan")
    table.add_column("Binary")
    table.add_column("Status")
    table.add_column("Version")

    for r in results:
        status_style = "[green]" if "OK" in r["status"] else "[red]"
        table.add_row(
            r["name"],
            r["binary"],
            f"{status_style}{r['status']}[/]",
            r["version"],
        )

    console.print(table)

    # Summary
    ok_count = sum(1 for r in results if "OK" in r["status"])
    total = len(results)
    console.print(f"\n[bold]{ok_count}/{total}[/] tools available")


@app.command()
def install(
    tool: str = typer.Argument(..., help="Tool to install (e.g. yosys, verilator, nextpnr-ice40)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
) -> None:
    """Install an EDA tool.

    The installer uses the system package manager or downloads pre-built
    binaries where available.

    Examples:
        openforge tools install yosys
        openforge tools install openroad
        openforge tools install verilator
    """
    import platform
    import sys

    console.print(f"[bold]Installing[/] [cyan]{tool}[/] ...")

    # Map tools to install commands
    _apt_packages: dict[str, str] = {
        "yosys": "yosys",
        "verilator": "verilator",
        "icarus": "iverilog",
        "ghdl": "ghdl",
        "ngspice": "ngspice",
        "magic": "magic",
        "netgen": "netgen-lvs",
        "klayout": "klayout",
    }

    _pip_packages: dict[str, str] = {
        "symbiyosys": "sby",
    }

    system = platform.system().lower()

    if tool in _pip_packages:
        console.print(f"  Installing via pip: {_pip_packages[tool]}")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", _pip_packages[tool]],
                check=True,
                capture_output=not verbose,
            )
            console.print(f"[green]Installed {tool}[/]")
            return
        except subprocess.CalledProcessError as e:
            console.print(f"[red]pip install failed:[/] {e}")
            raise typer.Exit(code=1)

    if system == "linux" and tool in _apt_packages:
        pkg = _apt_packages[tool]
        console.print(f"  Installing via apt: {pkg}")
        try:
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", pkg],
                check=True,
                capture_output=not verbose,
            )
            console.print(f"[green]Installed {tool}[/]")
            return
        except subprocess.CalledProcessError as e:
            console.print(f"[red]apt install failed:[/] {e}")
            raise typer.Exit(code=1)

    # Fallback: try conda/mamba
    conda = shutil.which("mamba") or shutil.which("conda")
    if conda:
        console.print(f"  Trying conda-forge: {tool}")
        try:
            subprocess.run(
                [conda, "install", "-y", "-c", "conda-forge", tool],
                check=True,
                capture_output=not verbose,
            )
            console.print(f"[green]Installed {tool} via conda[/]")
            return
        except subprocess.CalledProcessError:
            pass

    console.print(f"[yellow]Automatic installation not available for {tool} on {system}.[/]")
    console.print("[dim]Install manually from:[/]")

    _urls: dict[str, str] = {
        "yosys": "https://github.com/YosysHQ/yosys",
        "verilator": "https://verilator.org",
        "nextpnr-ice40": "https://github.com/YosysHQ/nextpnr",
        "nextpnr-ecp5": "https://github.com/YosysHQ/nextpnr",
        "openroad": "https://github.com/The-OpenROAD-Project/OpenROAD",
        "opensta": "https://github.com/The-OpenROAD-Project/OpenSTA",
        "magic": "https://github.com/RTimothyEdwards/magic",
        "netgen": "https://github.com/RTimothyEdwards/netgen",
        "klayout": "https://www.klayout.de",
        "ngspice": "https://ngspice.sourceforge.io",
        "openFPGALoader": "https://github.com/trabucayre/openFPGALoader",
    }
    url = _urls.get(tool, f"https://github.com/search?q={tool}")
    console.print(f"  [cyan]{url}[/]")
    raise typer.Exit(code=1)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Full health check -- verify all tools, paths, and permissions.

    Example:
        openforge tools doctor
    """
    import platform
    import sys

    issues: list[dict[str, str]] = []

    # Check Python version
    py_ver = sys.version_info
    if py_ver < (3, 12):
        issues.append(
            {
                "level": "warning",
                "msg": f"Python {py_ver.major}.{py_ver.minor} -- 3.12+ recommended",
            }
        )

    # Check each tool
    for name, class_path, binary in _TOOL_REGISTRY:
        try:
            engine = _load_engine(class_path)
            if not engine.check_installed():
                issues.append({"level": "info", "msg": f"{name} ({binary}) not found on PATH"})
        except Exception as e:
            issues.append({"level": "warning", "msg": f"{name}: import error: {e}"})

    # Check WSL availability on Windows
    if platform.system() == "Windows":
        wsl = shutil.which("wsl")
        if not wsl:
            issues.append(
                {"level": "warning", "msg": "WSL not available -- many EDA tools require Linux"}
            )

    # Check git
    if not shutil.which("git"):
        issues.append({"level": "warning", "msg": "git not found on PATH"})

    if json_output:
        console.print(json_mod.dumps({"issues": issues, "healthy": len(issues) == 0}))
        return

    if not issues:
        console.print("[green bold]All checks passed![/] Your environment is healthy.")
        return

    console.print("[bold]Health Check Results:[/]")
    for issue in issues:
        level = issue["level"]
        if level == "error":
            console.print(f"  [red]ERROR:[/] {issue['msg']}")
        elif level == "warning":
            console.print(f"  [yellow]WARN:[/]  {issue['msg']}")
        else:
            console.print(f"  [dim]INFO:[/]  {issue['msg']}")

    error_count = sum(1 for i in issues if i["level"] == "error")
    if error_count:
        raise typer.Exit(code=1)
