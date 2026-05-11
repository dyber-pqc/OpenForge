"""``openforge netgen`` -- Netgen LVS interop.

Subcommands:
  * ``import-setup <netgen.tcl>`` -- convert a Netgen setup file into an
    OpenForge LVS options YAML.
  * ``parse-report <lvs.report>`` -- convert a Netgen lvs.report into the
    OpenForge LVS JSON shape so users can compare against their baseline.
"""

from __future__ import annotations

from pathlib import Path

import typer
import yaml

app = typer.Typer(
    no_args_is_help=True,
    help="Netgen LVS interop -- import setup files, parse lvs.report.",
)


@app.command("import-setup")
def import_setup(
    setup: Path = typer.Argument(..., exists=True, help="Netgen setup .tcl file."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Output YAML path (default: lvs-options.yaml)."
    ),
) -> None:
    """Translate a Netgen setup file to OpenForge LVS options YAML."""
    from openforge.integrations.netgen import netgen_to_lvs_options, parse_netgen_setup

    parsed = parse_netgen_setup(setup)
    options = netgen_to_lvs_options(parsed)

    out_path = out if out is not None else Path("lvs-options.yaml")
    out_path.write_text(yaml.safe_dump(options, sort_keys=False), encoding="utf-8")

    typer.secho("Imported Netgen setup -> LVS options:", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"  source:             {setup}")
    typer.echo(f"  out:                {out_path}")
    typer.echo(f"  permute rules:      {len(options['permute_ports'])}")
    typer.echo(f"  device aliases:     {len(options['device_aliases'])}")
    typer.echo(f"  ignore devices:     {len(options['ignore_devices'])}")
    typer.echo(f"  property tols:      {len(options['property_tolerances'])}")
    typer.echo(f"  ignore properties:  {len(options['ignore_properties'])}")


@app.command("parse-report")
def parse_report(
    report: Path = typer.Argument(..., exists=True, help="Netgen lvs.report file."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Output JSON path (default: lvs.json)."
    ),
) -> None:
    """Parse a Netgen lvs.report and emit OpenForge LVS JSON."""
    from openforge.integrations.netgen import (
        parse_netgen_report,
        report_to_openforge_json,
    )

    parsed = parse_netgen_report(report)
    out_path = out if out is not None else Path("lvs.json")
    out_path.write_text(report_to_openforge_json(parsed), encoding="utf-8")

    color = typer.colors.GREEN if parsed.overall_match else typer.colors.RED
    typer.secho("Parsed Netgen lvs.report:", bold=True, fg=color)
    typer.echo(f"  source:    {report}")
    typer.echo(f"  out:       {out_path}")
    typer.echo(f"  top cell:  {parsed.top_cell}")
    typer.echo(f"  verdict:   {parsed.verdict or '(unknown)'}")
    typer.echo(f"  match:     {parsed.overall_match}")
    typer.echo(f"  cells:     {len(parsed.cells)} compared")
