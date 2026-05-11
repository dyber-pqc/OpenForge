"""``openforge magic`` -- Magic VLSI interop.

Subcommands:
  * ``translate-rules <magic.tech>`` -- parse a Magic ``.tech`` file and emit
    an OpenForge DRX rule deck consumable by ``openforge-drc``.
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Magic VLSI interop -- translate Magic .tech files to OpenForge DRX.",
)


@app.command("translate-rules")
def translate_rules(
    tech: Path = typer.Argument(..., exists=True, help="Magic .tech file."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Output DRX path (default: <tech>.drx)."
    ),
) -> None:
    """Translate a Magic .tech file's DRC section to a DRX rule deck."""
    from openforge.integrations.magic import magic_to_drx, parse_magic_tech

    parsed = parse_magic_tech(tech)
    drx = magic_to_drx(parsed)
    out_path = out if out is not None else tech.with_suffix(".drx")
    out_path.write_text(drx, encoding="utf-8")

    typer.secho("Translated Magic .tech -> DRX:", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"  source:      {tech}")
    typer.echo(f"  out:         {out_path}")
    typer.echo(f"  width:       {len(parsed.width_rules)} rules")
    typer.echo(f"  spacing:     {len(parsed.spacing_rules)} rules")
    typer.echo(f"  area:        {len(parsed.area_rules)} rules")
    if parsed.unsupported:
        typer.secho(
            f"  unsupported: {len(parsed.unsupported)} rules (emitted as TODO comments)",
            fg=typer.colors.YELLOW,
        )
