"""``openforge openlane`` -- import/export OpenLane projects.

Subcommands:
  * ``import <path>`` -- read an OpenLane ``config.json`` and write
    ``openforge.yaml`` (plus a synthesized SDC) into the project so the user
    can run the OpenForge flow without rewriting their config.
  * ``export <build-dir> <openlane-run-dir>`` -- mirror OpenForge build
    outputs into the OpenLane ``runs/<tag>/`` layout (final.def, final.gds,
    tritonRoute.drc-style reports, synthesis.stat.rpt).
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="OpenLane interoperability -- import OpenLane projects, export OpenLane reports.",
)


@app.command("import")
def import_cmd(
    path: Path = typer.Argument(
        ..., exists=True, help="Path to OpenLane project directory or its config.json."
    ),
    no_yaml: bool = typer.Option(
        False, "--no-yaml", help="Do not write openforge.yaml; just print the mapping."
    ),
    no_sdc: bool = typer.Option(
        False, "--no-sdc", help="Do not synthesize an SDC from CLOCK_PORT/PERIOD."
    ),
) -> None:
    """Import an OpenLane project into OpenForge format."""
    from openforge.integrations.openlane import import_openlane

    cfg = import_openlane(path, write_yaml=not no_yaml, write_sdc=not no_sdc)
    typer.secho("Imported OpenLane project:", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"  top:        {cfg.project.top_module}")
    typer.echo(f"  pdk:        {cfg.project.target_pdk}")
    typer.echo(f"  sources:    {len(cfg.design.sources)} entries")
    typer.echo(f"  constraints:{len(cfg.design.constraints)} entries")
    if not no_yaml:
        target = path if path.is_dir() else path.parent
        typer.echo(f"  wrote:      {target / 'openforge.yaml'}")


@app.command("export")
def export_cmd(
    build_dir: Path = typer.Argument(..., exists=True, help="OpenForge build directory."),
    openlane_run_dir: Path = typer.Argument(
        ..., help="Target OpenLane run directory (e.g. runs/openforge/)."
    ),
) -> None:
    """Mirror OpenForge build outputs into an OpenLane runs/<tag>/ layout."""
    from openforge.integrations.openlane import export_openlane_reports

    summary = export_openlane_reports(build_dir, openlane_run_dir)
    typer.secho("Exported to OpenLane layout:", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"  target:      {openlane_run_dir}")
    typer.echo(f"  copied:      {len(summary['copied'])} files")
    for f in summary["copied"]:
        typer.echo(f"    - {f}")
    typer.echo(f"  synthesized: {len(summary['synthesized'])} reports")
    for f in summary["synthesized"]:
        typer.echo(f"    - {f}")
