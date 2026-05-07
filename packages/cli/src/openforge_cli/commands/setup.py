"""``openforge setup`` — one-shot environment bootstrapping.

Installs PDKs and verifies tool availability. Designed so a fresh user can
go from clone-to-buildable in one command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, help="Environment setup — install PDKs, detect tools.")


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

_REQUIRED_TOOLS = [
    "yosys",
    "openroad",
    "magic",
    "netgen",
    "klayout",
    "verilator",
    "iverilog",
    "ngspice",
]
_FPGA_TOOLS = ["nextpnr-ice40", "nextpnr-ecp5", "icepack", "iceprog"]


def _has_native(tool: str) -> bool:
    if shutil.which(tool):
        return True
    if os.name == "nt":
        for ext in (".exe", ".bat", ".cmd"):
            if shutil.which(tool + ext):
                return True
    return False


def _has_wsl_tool(tool: str) -> bool:
    if os.name != "nt" or not shutil.which("wsl"):
        return False
    try:
        r = subprocess.run(
            ["wsl", "-e", "bash", "-c", f"command -v {tool}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _has_docker() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def doctor() -> None:
    """Check what's installed and what's missing."""
    typer.secho("OpenForge environment check", bold=True, fg=typer.colors.CYAN)
    typer.echo()

    # Backends
    typer.secho("Execution backends:", bold=True)
    typer.echo(
        f"  native (PATH)  {'OK' if any(_has_native(t) for t in _REQUIRED_TOOLS) else 'no tools found'}"
    )
    typer.echo(f"  WSL            {'OK' if shutil.which('wsl') else 'missing'}")
    typer.echo(f"  Docker         {'OK' if _has_docker() else 'missing'}")
    typer.echo()

    # Tools — check each via every available backend
    typer.secho("Required ASIC tools:", bold=True)
    for tool in _REQUIRED_TOOLS:
        sources = []
        if _has_native(tool):
            sources.append("native")
        if _has_wsl_tool(tool):
            sources.append("wsl")
        status = ", ".join(sources) if sources else "MISSING"
        color = typer.colors.GREEN if sources else typer.colors.RED
        typer.secho(f"  {tool:<25} {status}", fg=color)

    typer.echo()
    typer.secho("FPGA tools:", bold=True)
    for tool in _FPGA_TOOLS:
        sources = []
        if _has_native(tool):
            sources.append("native")
        if _has_wsl_tool(tool):
            sources.append("wsl")
        status = ", ".join(sources) if sources else "MISSING"
        color = typer.colors.GREEN if sources else typer.colors.YELLOW
        typer.secho(f"  {tool:<25} {status}", fg=color)

    typer.echo()
    typer.secho("PDKs:", bold=True)
    pdk_root = os.environ.get("PDK_ROOT", "")
    if pdk_root and Path(pdk_root, "sky130A").exists():
        typer.secho(f"  sky130A             OK ({pdk_root}/sky130A)", fg=typer.colors.GREEN)
    else:
        candidates = [
            Path.home() / ".volare" / "sky130A",
            Path("/usr/share/pdk/sky130A"),
            Path("/opt/skywater/sky130A"),
        ]
        found = next((p for p in candidates if p.exists()), None)
        if found:
            typer.secho(f"  sky130A             OK ({found})", fg=typer.colors.GREEN)
            typer.echo(f"      hint: export PDK_ROOT={found.parent}")
        else:
            typer.secho(
                "  sky130A             MISSING — run `openforge setup pdk sky130A`",
                fg=typer.colors.RED,
            )


@app.command()
def pdk(
    name: str = typer.Argument("sky130A", help="PDK name: sky130A | sky130B | gf180mcuC"),
    pdk_root: str = typer.Option("", "--pdk-root", help="Install location (default: ~/.volare)"),
    use_wsl: bool = typer.Option(False, "--wsl", help="Install inside WSL (Windows)"),
) -> None:
    """Install a PDK using volare."""
    target = pdk_root or str(Path.home() / ".volare")

    if use_wsl and os.name == "nt":
        typer.echo(f"Installing {name} via WSL volare into {target}…")
        cmd = (
            "python3 -m pip install --user volare --break-system-packages 2>/dev/null || "
            "python3 -m pip install --user volare; "
            f"python3 -m volare enable --pdk {name.removesuffix('A').removesuffix('B').lower()} "
            f"--pdk-root {target} || true"
        )
        subprocess.run(["wsl", "-e", "bash", "-c", cmd])
    else:
        typer.echo(f"Installing {name} via volare into {target}…")
        try:
            subprocess.run(
                ["pip", "install", "--user", "volare"],
                check=False,
            )
            family = name.removesuffix("A").removesuffix("B").lower()
            subprocess.run(
                ["python", "-m", "volare", "enable", "--pdk", family, "--pdk-root", target],
                check=False,
            )
        except FileNotFoundError:
            typer.secho("Volare install failed — is Python on PATH?", fg=typer.colors.RED)
            raise typer.Exit(1) from None

    typer.echo()
    typer.secho(f"Set PDK_ROOT for future sessions: export PDK_ROOT={target}", fg=typer.colors.CYAN)


@app.command(name="all")
def setup_all() -> None:
    """Run the full setup: install PDK + verify tools."""
    typer.secho("Running full OpenForge setup…", bold=True, fg=typer.colors.CYAN)
    pdk("sky130A")
    typer.echo()
    doctor()
