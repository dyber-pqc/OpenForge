"""openforge flow -- full-flow orchestration commands."""

from __future__ import annotations

import json as json_mod
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="flow",
    help="Flow orchestration -- run full/partial flows, check status, manage artifacts.",
    no_args_is_help=True,
)


def _load_config(project_dir: Path):
    from openforge.config.loader import ConfigNotFoundError, load_config

    try:
        return load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/]."
        )
        raise typer.Exit(code=1)


@app.command(name="run")
def flow_run(
    path: str = typer.Argument(".", help="Path to the design directory."),
    from_stage: str | None = typer.Option(None, "--from", help="Start from this stage."),
    to_stage: str | None = typer.Option(None, "--to", help="Stop after this stage."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run the full or partial RTL-to-GDS flow.

    Examples:
        openforge flow run
        openforge flow run --from synth --to routing
        openforge flow run --to sta
    """
    from openforge.flow import STAGE_IDS, FullFlowConfig, FullFlowRunner

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    # Resolve source files
    source_files: list[str] = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))
    if not source_files:
        console.print("[red]Error:[/] no source files found.")
        raise typer.Exit(code=1)

    # SDC
    sdc_file = None
    for constraint in config.design.constraints:
        candidate = project_dir / constraint
        if candidate.exists() and candidate.suffix == ".sdc":
            sdc_file = str(candidate)
            break
    if not sdc_file:
        clock_period = config.timing.clock_period if config.timing else 10.0
        sdc_dir = project_dir / ".openforge"
        sdc_dir.mkdir(parents=True, exist_ok=True)
        sdc_gen = sdc_dir / "auto_constraints.sdc"
        sdc_gen.write_text(f"create_clock -name clk -period {clock_period} [get_ports clk]\n")
        sdc_file = str(sdc_gen)

    pdk = config.project.target_pdk or "sky130A"
    freq = 1000.0 / (config.timing.clock_period if config.timing else 10.0)

    flow_config = FullFlowConfig(
        top_module=config.project.top_module,
        rtl_files=source_files,
        sdc_file=sdc_file,
        pdk=pdk,
        target_freq_mhz=freq,
        output_dir=str(project_dir / "build"),
    )

    if not json_output:
        console.print(f"[bold]Running flow[/] at [cyan]{project_dir}[/]")
        console.print(f"  stages : [green]{', '.join(STAGE_IDS)}[/]")
        if from_stage:
            console.print(f"  from   : [green]{from_stage}[/]")
        if to_stage:
            console.print(f"  to     : [green]{to_stage}[/]")
        console.print()

    runner = FullFlowRunner()

    def _on_stage(stage: str, status: str) -> None:
        if not json_output and verbose:
            console.print(f"  [{status}] {stage}")

    with console.status("[bold blue]Running flow...", spinner="dots"):
        result = runner.run(
            config=flow_config,
            from_stage=from_stage,
            to_stage=to_stage,
            on_stage_update=_on_stage,
        )

    if json_output:
        console.print(json_mod.dumps({
            "overall_status": result.overall_status,
            "gds_path": result.gds_path,
            "total_runtime_s": result.total_runtime_s,
            "stages": [
                {
                    "stage": s.stage,
                    "status": s.status,
                    "runtime_s": s.runtime_s,
                    "errors": s.errors,
                }
                for s in result.stages
            ],
        }))
        if result.overall_status != "success":
            raise typer.Exit(code=1)
        return

    # Display results
    table = Table(title="Flow Results", show_header=True, header_style="bold cyan")
    table.add_column("Stage", style="bold")
    table.add_column("Status", width=10)
    table.add_column("Runtime (s)", justify="right")
    table.add_column("Errors")

    for s in result.stages:
        status = s.status
        if status == "success":
            style = "[green]"
        elif status == "skipped":
            style = "[yellow]"
        elif status == "pending":
            style = "[dim]"
        else:
            style = "[red]"
        table.add_row(
            s.stage,
            f"{style}{status}[/]",
            f"{s.runtime_s:.1f}",
            ", ".join(s.errors[:2]) if s.errors else "",
        )

    console.print(table)
    console.print(f"\n[bold]Overall:[/] {result.overall_status} in {result.total_runtime_s:.1f}s")
    if result.gds_path:
        console.print(f"[green]GDS output:[/] {result.gds_path}")

    if result.overall_status != "success":
        raise typer.Exit(code=1)


@app.command()
def status(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show current flow status based on existing build artifacts.

    Example:
        openforge flow status
    """
    from openforge.flow import STAGE_IDS

    project_dir = Path(path).resolve()

    # Check what build artifacts exist
    stage_status: list[dict[str, str]] = []

    artifact_map = {
        "lint": [".openforge/lint_result.json"],
        "synth": ["synth_build/netlist.v", "synth_build/netlist.json"],
        "floorplan": ["pnr_build/floorplan.def"],
        "placement": ["pnr_build/placed.def", "pnr_build/counter_placed.def"],
        "cts": ["pnr_build/cts.def"],
        "routing": ["pnr_build/routed.def", "pnr_build/counter_routed.def"],
        "fill": ["pnr_build/filled.def"],
        "sta": [".openforge/sta_result.json"],
        "drc": [".openforge/drc_result.json", "pnr_build/drc_report.rpt"],
        "lvs": [".openforge/lvs_result.json"],
        "gds_export": ["pnr_build/*.gds"],
    }

    for stage in STAGE_IDS:
        candidates = artifact_map.get(stage, [])
        found = False
        for candidate in candidates:
            if "*" in candidate:
                if list(project_dir.glob(candidate)):
                    found = True
                    break
            elif (project_dir / candidate).exists():
                found = True
                break
        stage_status.append({
            "stage": stage,
            "status": "done" if found else "pending",
        })

    if json_output:
        console.print(json_mod.dumps({"stages": stage_status}))
        return

    table = Table(title="Flow Status", show_header=True, header_style="bold cyan")
    table.add_column("Stage", style="bold")
    table.add_column("Status")

    for s in stage_status:
        style = "[green]" if s["status"] == "done" else "[dim]"
        icon = "done" if s["status"] == "done" else "pending"
        table.add_row(s["stage"], f"{style}{icon}[/]")

    console.print(table)


@app.command()
def artifacts(
    path: str = typer.Argument(".", help="Path to the design directory."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """List all generated build artifacts.

    Example:
        openforge flow artifacts
    """
    project_dir = Path(path).resolve()

    build_dirs = ["synth_build", "pnr_build", "fpga_build", "sim_build", ".openforge", "build"]
    all_artifacts: list[dict[str, str]] = []

    for build_dir in build_dirs:
        bdir = project_dir / build_dir
        if bdir.exists():
            for f in sorted(bdir.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(project_dir)
                    size_kb = f.stat().st_size / 1024
                    all_artifacts.append({
                        "path": str(rel),
                        "size_kb": f"{size_kb:.1f}",
                    })

    if json_output:
        console.print(json_mod.dumps({"artifacts": all_artifacts}))
        return

    if not all_artifacts:
        console.print("[yellow]No build artifacts found.[/]")
        return

    table = Table(title="Build Artifacts", show_header=True, header_style="bold cyan")
    table.add_column("Path", style="bold")
    table.add_column("Size (KB)", justify="right")

    for a in all_artifacts:
        table.add_row(a["path"], a["size_kb"])

    console.print(table)
    console.print(f"\n[dim]Total: {len(all_artifacts)} files[/]")


@app.command()
def clean(
    path: str = typer.Argument(".", help="Path to the design directory."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
) -> None:
    """Remove all build artifacts.

    Example:
        openforge flow clean
        openforge flow clean --force
    """
    project_dir = Path(path).resolve()

    build_dirs = ["synth_build", "pnr_build", "fpga_build", "sim_build", "build"]
    dirs_to_clean = [project_dir / d for d in build_dirs if (project_dir / d).exists()]

    if not dirs_to_clean:
        console.print("[yellow]No build directories to clean.[/]")
        return

    console.print("[bold]Directories to remove:[/]")
    for d in dirs_to_clean:
        console.print(f"  [red]{d}[/]")

    if not force:
        confirm = typer.confirm("Remove these directories?")
        if not confirm:
            console.print("[dim]Aborted.[/]")
            raise typer.Exit()

    for d in dirs_to_clean:
        shutil.rmtree(d)
        console.print(f"  [dim]removed[/] {d}")

    console.print("[green]Clean complete.[/]")


@app.command()
def graph(
    path: str = typer.Argument(".", help="Path to the design directory."),
    fmt: str = typer.Option("ascii", "--format", "-f", help="Output format: ascii or dot."),
) -> None:
    """Print the flow DAG as ASCII art or DOT format.

    Examples:
        openforge flow graph
        openforge flow graph --format dot > flow.dot
    """
    from openforge.flow import STAGE_IDS

    # Build simple dependency chain
    deps: dict[str, list[str]] = {}
    for i, stage in enumerate(STAGE_IDS):
        deps[stage] = [STAGE_IDS[i - 1]] if i > 0 else []

    if fmt == "dot":
        print("digraph flow {")
        print("  rankdir=LR;")
        print('  node [shape=box, style=filled, fillcolor="#e8e8e8"];')
        for stage, dep_list in deps.items():
            for dep in dep_list:
                print(f"  {dep} -> {stage};")
        print("}")
    else:
        # ASCII art
        for i, stage in enumerate(STAGE_IDS):
            if i == 0:
                console.print(f"[bold cyan]{stage}[/]")
            else:
                console.print("  | ")
                console.print("  v")
                console.print(f"[bold cyan]{stage}[/]")
