"""openforge spice -- analog SPICE simulation commands."""

from __future__ import annotations

import json as json_mod
from pathlib import Path

import typer
from rich.console import Console

console = Console()

app = typer.Typer(
    name="spice",
    help="Analog SPICE simulation commands.",
    no_args_is_help=True,
)


@app.command(name="run")
def spice_run(
    netlist: str = typer.Option(..., "--netlist", "-n", help="SPICE netlist file."),
    analysis: str = typer.Option(
        "tran", "--analysis", "-a", help="Analysis type: tran, dc, ac, op, noise."
    ),
    path: str = typer.Argument(".", help="Working directory."),
    output: str | None = typer.Option(None, "--output", "-o", help="Output raw file path."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run a SPICE simulation with ngspice.

    Examples:
        openforge spice run --netlist circuit.cir --analysis tran
        openforge spice run --netlist amp.spice --analysis ac
        openforge spice run --netlist test.spice --analysis dc
    """
    from openforge.engine.ngspice import NgspiceEngine, SpiceAnalysisConfig

    project_dir = Path(path).resolve()
    netlist_path = Path(netlist)
    if not netlist_path.is_absolute():
        netlist_path = project_dir / netlist_path

    if not netlist_path.exists():
        console.print(f"[red]Error:[/] netlist not found at [cyan]{netlist_path}[/]")
        raise typer.Exit(code=1)

    engine = NgspiceEngine()
    if not engine.check_installed():
        console.print("[red]Error:[/] ngspice not found. Install it first.")
        raise typer.Exit(code=1)

    output_raw = Path(output) if output else (project_dir / "sim_build" / f"{analysis}.raw")
    output_raw.parent.mkdir(parents=True, exist_ok=True)

    analysis_config = SpiceAnalysisConfig(
        output_raw=output_raw,
        output_log=output_raw.parent / f"{analysis}.log",
    )

    if not json_output:
        console.print(f"[bold]SPICE {analysis}[/] on [cyan]{netlist_path}[/]")
        console.print(f"  output : [green]{output_raw}[/]")
        console.print()

    with console.status(f"[bold blue]Running {analysis} analysis...", spinner="dots"):
        if analysis == "tran":
            result = engine.run_tran(
                netlist=str(netlist_path),
                tstep="1n",
                tstop="1u",
                config=analysis_config,
                cwd=str(project_dir),
            )
        elif analysis == "dc":
            result = engine.run_dc(
                netlist=str(netlist_path),
                source="V1",
                start=0.0,
                stop=3.3,
                step=0.01,
                config=analysis_config,
                cwd=str(project_dir),
            )
        elif analysis == "ac":
            result = engine.run_ac(
                netlist=str(netlist_path),
                variation="dec",
                npoints=100,
                fstart=1.0,
                fstop=1e9,
                config=analysis_config,
                cwd=str(project_dir),
            )
        elif analysis == "op":
            result = engine.run_op(
                netlist=str(netlist_path),
                config=analysis_config,
                cwd=str(project_dir),
            )
        elif analysis == "noise":
            result = engine.run_noise(
                netlist=str(netlist_path),
                output_node="out",
                source="V1",
                variation="dec",
                npoints=100,
                fstart=1.0,
                fstop=1e9,
                config=analysis_config,
                cwd=str(project_dir),
            )
        else:
            console.print(f"[red]Unknown analysis type:[/] {analysis}")
            console.print("[dim]Supported: tran, dc, ac, op, noise[/]")
            raise typer.Exit(code=1)

    if not result.ok:
        if json_output:
            console.print(json_mod.dumps({"status": "failed", "returncode": result.returncode}))
        else:
            console.print(f"[red bold]SPICE {analysis} FAILED[/]")
            if result.stderr:
                for line in result.stderr.splitlines()[-20:]:
                    console.print(f"  [red]{line}[/]")
        raise typer.Exit(code=1)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "status": "passed",
                    "analysis": analysis,
                    "output_raw": str(output_raw),
                    "duration_s": result.duration,
                }
            )
        )
        return

    console.print(f"[green bold]SPICE {analysis} PASSED[/] in {result.duration:.1f}s")
    console.print(f"  Raw output: [cyan]{output_raw}[/]")


@app.command(name="monte-carlo")
def monte_carlo(
    netlist: str = typer.Option(..., "--netlist", "-n", help="SPICE netlist file."),
    variable: str = typer.Option(..., "--variable", help="Parameter to vary."),
    sigma: float = typer.Option(0.1, "--sigma", help="Standard deviation (fraction)."),
    samples: int = typer.Option(100, "--samples", help="Number of Monte Carlo samples."),
    path: str = typer.Argument(".", help="Working directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run Monte Carlo SPICE simulation.

    Examples:
        openforge spice monte-carlo --netlist circuit.cir --variable R1 --sigma 0.05 --samples 1000
    """
    from openforge.engine.ngspice import NgspiceEngine

    project_dir = Path(path).resolve()
    netlist_path = Path(netlist)
    if not netlist_path.is_absolute():
        netlist_path = project_dir / netlist_path

    if not netlist_path.exists():
        console.print(f"[red]Error:[/] netlist not found at [cyan]{netlist_path}[/]")
        raise typer.Exit(code=1)

    engine = NgspiceEngine()
    if not engine.check_installed():
        console.print("[red]Error:[/] ngspice not found.")
        raise typer.Exit(code=1)

    if not json_output:
        console.print(f"[bold]Monte Carlo[/] on [cyan]{netlist_path}[/]")
        console.print(f"  variable : [green]{variable}[/]")
        console.print(f"  sigma    : [green]{sigma}[/]")
        console.print(f"  samples  : [green]{samples}[/]")
        console.print()

    output_dir = project_dir / "sim_build" / "monte_carlo"
    output_dir.mkdir(parents=True, exist_ok=True)

    with console.status("[bold blue]Running Monte Carlo...", spinner="dots"):
        result = engine.run_monte_carlo(
            netlist=str(netlist_path),
            variable=variable,
            sigma=sigma,
            num_samples=samples,
            output_dir=str(output_dir),
            cwd=str(project_dir),
        )

    if not result.ok:
        console.print("[red bold]Monte Carlo FAILED[/]")
        raise typer.Exit(code=1)

    if json_output:
        console.print(
            json_mod.dumps(
                {
                    "status": "passed",
                    "samples": samples,
                    "output_dir": str(output_dir),
                }
            )
        )
        return

    console.print(
        f"[green bold]Monte Carlo PASSED[/] ({samples} samples) in {result.duration:.1f}s"
    )
    console.print(f"  Results: [cyan]{output_dir}[/]")
