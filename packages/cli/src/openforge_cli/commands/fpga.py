"""openforge fpga -- FPGA synthesis, PnR, bitstream, and programming."""

from __future__ import annotations

import json as json_mod
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

app = typer.Typer(
    name="fpga",
    help="FPGA flow commands -- synthesis, P&R, pack, flash.",
    no_args_is_help=True,
)


def _load_config(project_dir: Path):
    from openforge.config.loader import ConfigNotFoundError, load_config

    try:
        return load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/]. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(code=1)


def _resolve_sources(project_dir: Path, config) -> list[str]:
    source_files: list[str] = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))
    return source_files


@app.command()
def synth(
    path: str = typer.Argument(".", help="Path to the design directory."),
    device: str = typer.Option(
        "ice40", "--device", "-d", help="FPGA device family (ice40, ecp5, gowin)."
    ),
    top: str | None = typer.Option(None, "--top", help="Top-level module name."),
    json_out: str | None = typer.Option(None, "--json-out", help="Write JSON netlist to file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON result."),
) -> None:
    """Synthesize design for an FPGA target using Yosys.

    Examples:
        openforge fpga synth --device ice40
        openforge fpga synth --device ecp5 --top blinky
        openforge fpga synth --device gowin --json-out synth.json
    """
    from openforge.engine.yosys import YosysEngine

    project_dir = Path(path).resolve()
    config = _load_config(project_dir)

    top_module = top or config.project.top_module
    source_files = _resolve_sources(project_dir, config)
    if not source_files:
        console.print("[red]Error:[/] no source files found.")
        raise typer.Exit(code=1)

    engine = YosysEngine()
    if not engine.check_installed():
        console.print(
            "[red]Error:[/] Yosys not found. Install it or run [bold]openforge tools install yosys[/]."
        )
        raise typer.Exit(code=1)

    if not quiet:
        console.print(f"[bold]FPGA synthesis[/] for [green]{device}[/] at [cyan]{project_dir}[/]")
        console.print(f"  top     : [green]{top_module}[/]")
        console.print(f"  sources : [green]{len(source_files)} files[/]")
        console.print()

    output_dir = project_dir / "fpga_build"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_out or str(output_dir / "synth.json")

    # Build Yosys script
    synth_cmd_map = {
        "ice40": "synth_ice40",
        "ecp5": "synth_ecp5",
        "gowin": "synth_gowin",
        "xilinx": "synth_xilinx",
    }
    synth_cmd = synth_cmd_map.get(device, f"synth_{device}")

    script_lines = []
    for src in source_files:
        script_lines.append(f"read_verilog -sv {src}")
    script_lines.append(f"{synth_cmd} -top {top_module} -json {json_path}")

    script_path = output_dir / "fpga_synth.ys"
    script_path.write_text("\n".join(script_lines) + "\n")

    with console.status("[bold blue]Running FPGA synthesis...", spinner="dots"):
        result = engine.run_script(str(script_path), cwd=str(project_dir))

    if not result.ok:
        console.print("[red bold]FPGA synthesis FAILED[/]")
        if result.stderr:
            for line in result.stderr.splitlines()[-20:]:
                console.print(f"  [red]{line}[/]")
        raise typer.Exit(code=1)

    if json_output:
        console.print(json_mod.dumps({"status": "passed", "json_netlist": json_path}))
        return

    console.print(f"[green bold]FPGA synthesis PASSED[/] in {result.duration:.1f}s")
    console.print(f"  JSON netlist: [cyan]{json_path}[/]")


@app.command()
def pnr(
    path: str = typer.Argument(".", help="Path to the design directory."),
    device: str = typer.Option(
        "", "--device", "-d", help="FPGA device (e.g. hx8k, lfe5u-85f, GW1NR-9C)."
    ),
    package: str = typer.Option("", "--package", help="Device package (e.g. ct256, CABGA381)."),
    pcf: str | None = typer.Option(None, "--pcf", help="Pin constraints file (iCE40)."),
    lpf: str | None = typer.Option(None, "--lpf", help="Pin constraints file (ECP5)."),
    xdc: str | None = typer.Option(None, "--xdc", help="Pin constraints file (Xilinx)."),
    freq: float | None = typer.Option(None, "--freq", help="Target frequency in MHz."),
    json_netlist: str | None = typer.Option(
        None, "--json", help="Input JSON netlist (from synth)."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
) -> None:
    """Run nextpnr place and route on a synthesized FPGA design.

    Examples:
        openforge fpga pnr --device hx8k --package ct256 --pcf pins.pcf
        openforge fpga pnr --device lfe5u-85f --lpf board.lpf --freq 100
    """
    from openforge.engine.nextpnr import NextpnrEngine

    project_dir = Path(path).resolve()
    fpga_build = project_dir / "fpga_build"
    fpga_build.mkdir(parents=True, exist_ok=True)

    json_in = json_netlist or str(fpga_build / "synth.json")
    if not Path(json_in).exists():
        console.print(
            f"[red]Error:[/] JSON netlist not found at [cyan]{json_in}[/]. "
            "Run [bold]openforge fpga synth[/] first."
        )
        raise typer.Exit(code=1)

    # Determine constraint file
    constraint = pcf or lpf or xdc
    constraint_flag = None
    if pcf:
        constraint_flag = "--pcf"
    elif lpf:
        constraint_flag = "--lpf"
    elif xdc:
        constraint_flag = "--xdc"

    engine = NextpnrEngine()
    if not engine.check_installed():
        console.print("[red]Error:[/] nextpnr not found. Install it first.")
        raise typer.Exit(code=1)

    if not quiet:
        console.print(f"[bold]FPGA P&R[/] at [cyan]{project_dir}[/]")
        if device:
            console.print(f"  device  : [green]{device}[/]")
        if package:
            console.print(f"  package : [green]{package}[/]")
        if constraint:
            console.print(f"  pins    : [green]{constraint}[/]")
        if freq:
            console.print(f"  freq    : [green]{freq} MHz[/]")
        console.print()

    output_asc = str(fpga_build / "routed.asc")
    output_log = str(fpga_build / "nextpnr.log")

    # Build nextpnr command
    args: list[str] = [
        "--json",
        json_in,
    ]
    if device:
        # Determine which nextpnr variant to use
        args.extend(["--" + device.split("-")[0] if "-" in device else "--hx8k"])
    if package:
        args.extend(["--package", package])
    if constraint and constraint_flag:
        args.extend([constraint_flag, constraint])
    if freq:
        args.extend(["--freq", str(freq)])
    args.extend(["--asc", output_asc, "--log", output_log])

    with console.status("[bold blue]Running FPGA P&R...", spinner="dots"):
        result = engine.run_pnr(
            json_netlist=json_in,
            device=device,
            package=package,
            constraint_file=constraint,
            freq_mhz=freq,
            output_dir=str(fpga_build),
        )

    if not result.success:
        console.print("[red bold]FPGA P&R FAILED[/]")
        if result.log:
            for line in result.log.splitlines()[-20:]:
                console.print(f"  [red]{line}[/]")
        raise typer.Exit(code=1)

    console.print(f"[green bold]FPGA P&R PASSED[/] in {result.duration:.1f}s")
    if result.fmax_mhz:
        fmax_style = "[green]" if (not freq or result.fmax_mhz >= freq) else "[red]"
        console.print(f"  Fmax: {fmax_style}{result.fmax_mhz:.1f} MHz[/]")
    console.print(f"  Output: [cyan]{output_asc}[/]")


@app.command()
def pack(
    path: str = typer.Argument(".", help="Path to the design directory."),
    output: str | None = typer.Option(None, "--output", "-o", help="Output bitstream file."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
) -> None:
    """Pack FPGA routed design into a bitstream.

    Examples:
        openforge fpga pack --output design.bin
    """
    from openforge.engine.bitstream import BitstreamEngine

    project_dir = Path(path).resolve()
    fpga_build = project_dir / "fpga_build"

    # Find routed ASC/config
    asc_file = fpga_build / "routed.asc"
    if not asc_file.exists():
        console.print(
            "[red]Error:[/] no routed design found. Run [bold]openforge fpga pnr[/] first."
        )
        raise typer.Exit(code=1)

    output_bin = output or str(fpga_build / "bitstream.bin")

    engine = BitstreamEngine()
    if not engine.check_installed():
        console.print("[red]Error:[/] icepack/ecppack not found.")
        raise typer.Exit(code=1)

    if not quiet:
        console.print(f"[bold]Packing bitstream[/] from [cyan]{asc_file}[/]")

    with console.status("[bold blue]Packing bitstream...", spinner="dots"):
        result = engine.pack(str(asc_file), output_bin)

    if not result.ok:
        console.print("[red bold]Pack FAILED[/]")
        raise typer.Exit(code=1)

    console.print(f"[green bold]Bitstream written to:[/] {output_bin}")


@app.command()
def flash(
    path: str = typer.Argument(".", help="Path to the design directory."),
    board: str | None = typer.Option(
        None, "--board", "-b", help="Board name (auto-detect if omitted)."
    ),
    bitstream: str | None = typer.Option(None, "--bitstream", help="Path to bitstream file."),
    mode: str = typer.Option("sram", "--mode", "-m", help="Programming mode: sram or flash."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
) -> None:
    """Flash a bitstream to an FPGA board.

    Examples:
        openforge fpga flash --board icebreaker --mode sram
        openforge fpga flash --bitstream design.bin
    """
    from openforge.fpga.programmer import program_device

    project_dir = Path(path).resolve()
    fpga_build = project_dir / "fpga_build"

    bitstream_path = bitstream or str(fpga_build / "bitstream.bin")
    if not Path(bitstream_path).exists():
        console.print(
            f"[red]Error:[/] bitstream not found at [cyan]{bitstream_path}[/]. "
            "Run [bold]openforge fpga pack[/] first."
        )
        raise typer.Exit(code=1)

    if not quiet:
        console.print(f"[bold]Flashing[/] [cyan]{bitstream_path}[/]")
        if board:
            console.print(f"  board : [green]{board}[/]")
        console.print(f"  mode  : [green]{mode}[/]")

    with console.status("[bold blue]Programming FPGA...", spinner="dots"):
        result = program_device(
            bitstream=bitstream_path,
            board_name=board,
            mode=mode,
        )

    if not result.success:
        console.print(f"[red bold]Flash FAILED:[/] {result.message}")
        raise typer.Exit(code=1)

    console.print(f"[green bold]Flash PASSED[/] in {result.time_seconds:.1f}s")
    if result.verified:
        console.print("  [green]Verification: OK[/]")


@app.command()
def detect(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Scan JTAG chain and detect connected FPGA boards.

    Example:
        openforge fpga detect
    """
    from openforge.fpga.programmer import detect_devices

    with console.status("[bold blue]Scanning for FPGA devices...", spinner="dots"):
        devices = detect_devices()

    if json_output:
        console.print(
            json_mod.dumps(
                [
                    {
                        "name": d.name,
                        "usb_id": d.usb_id,
                        "type": d.device_type,
                        "programmer": d.programmer,
                    }
                    for d in devices
                ]
            )
        )
        return

    if not devices:
        console.print("[yellow]No FPGA devices detected.[/]")
        console.print("[dim]Check USB connections and drivers.[/]")
        return

    table = Table(title="Detected FPGA Devices", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("USB ID")
    table.add_column("Type")
    table.add_column("Programmer")

    for dev in devices:
        table.add_row(dev.name, dev.usb_id, dev.device_type, dev.programmer)

    console.print(table)


@app.command(name="boards")
def list_boards(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """List all supported FPGA boards.

    Example:
        openforge fpga boards
    """
    from openforge.fpga.boards import BOARDS

    if json_output:
        console.print(
            json_mod.dumps(
                [
                    {
                        "name": b.name,
                        "vendor": b.vendor,
                        "family": b.family,
                        "device": b.device,
                        "package": b.package,
                        "constraint_format": b.constraint_format.value,
                        "clock_mhz": b.default_clk_freq_mhz,
                    }
                    for b in BOARDS.values()
                ]
            )
        )
        return

    table = Table(title="Supported FPGA Boards", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Vendor")
    table.add_column("Family")
    table.add_column("Device")
    table.add_column("Package")
    table.add_column("Clock (MHz)", justify="right")

    for b in BOARDS.values():
        table.add_row(
            b.name,
            b.vendor,
            b.family,
            b.device,
            b.package,
            f"{b.default_clk_freq_mhz:.0f}",
        )

    console.print(table)
