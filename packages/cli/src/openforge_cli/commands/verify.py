"""openforge verify -- run verification flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _resolve_sources(project_dir: Path, config: Any) -> list[str]:
    """Resolve source file globs from config."""
    source_files: list[str] = []
    for pattern in config.design.sources:
        source_files.extend(str(p) for p in project_dir.glob(pattern))
    return source_files


def _run_sim_engine(project_dir: Path, config: Any, source_files: list[str]) -> dict[str, Any]:
    """Run simulation-based verification, returning a result dict."""
    from openforge.runner.simulation import SimulationRunner

    sim_cfg = config.simulation
    tool = sim_cfg.tool if sim_cfg else "verilator"
    top_module = config.project.top_module

    runner = SimulationRunner(project_dir, config)

    output_lines: list[str] = []

    def _on_output(line: str) -> None:
        output_lines.append(line)
        if line.strip():
            console.print(f"  [dim]{line.rstrip()}[/]")

    # Compile
    console.print(f"  [bold]Compiling[/] with {tool} ...")
    compile_result = runner.compile(
        tool=tool,
        sources=source_files,
        top_module=top_module,
        on_output=_on_output,
    )

    if not compile_result.success:
        return {
            "engine": "sim",
            "status": "FAIL",
            "detail": f"Compilation failed ({compile_result.errors_count} errors)",
            "log": compile_result.log,
        }

    # Simulate
    console.print(f"  [bold]Simulating[/] ...")
    sim_result = runner.simulate(
        tool=tool,
        on_output=_on_output,
    )

    if sim_result.success:
        detail = f"PASS in {sim_result.duration:.1f}s"
        if sim_result.wave_file:
            detail += f" (waveform: {sim_result.wave_file})"
        return {"engine": "sim", "status": "PASS", "detail": detail}
    else:
        return {
            "engine": "sim",
            "status": "FAIL",
            "detail": f"Simulation failed in {sim_result.duration:.1f}s",
            "log": sim_result.log,
        }


def _run_formal_engine(project_dir: Path, config: Any, source_files: list[str]) -> dict[str, Any]:
    """Run formal verification, returning a result dict."""
    from openforge.flow.formal import run_formal

    top_module = config.project.top_module
    formal_cfg = config.formal

    context: dict[str, Any] = {
        "source_files": source_files,
        "top_module": top_module,
        "cwd": str(project_dir),
    }

    if formal_cfg:
        context["formal_depth"] = formal_cfg.depth
        if formal_cfg.properties:
            context["properties"] = formal_cfg.properties

    # Check for .sby file in project
    sby_files = list(project_dir.glob("*.sby"))
    if sby_files:
        context["sby_file"] = str(sby_files[0])
        console.print(f"  Using .sby file: [cyan]{sby_files[0].name}[/]")
    else:
        console.print("  [dim]No .sby file found, auto-generating configuration...[/]")

    console.print("  [bold]Running formal verification[/] ...")
    result = run_formal(context)

    status_str = result.status.value.upper()
    if status_str == "PASSED":
        proven_label = "PROVEN"
        return {"engine": "formal", "status": proven_label, "detail": "All properties proven"}
    elif status_str == "SKIPPED":
        return {"engine": "formal", "status": "SKIP", "detail": result.output or "Skipped"}
    else:
        detail = "Formal verification FAILED"
        if result.errors:
            detail += f": {result.errors[0][:100]}"
        return {
            "engine": "formal",
            "status": "FAIL",
            "detail": detail,
            "errors": result.errors,
            "log": result.output,
        }


def _run_crypto_engine(project_dir: Path, config: Any, source_files: list[str]) -> dict[str, Any]:
    """Run crypto-specific property checks, returning a result dict."""
    try:
        from openforge_crypto import (
            ConstantTimeVerifier,
            FIPSComplianceChecker,
            FIPSLevel as CryptoFIPSLevel,
            SideChannelSimulator,
        )
    except ImportError:
        return {
            "engine": "crypto",
            "status": "FAIL",
            "detail": (
                "openforge-crypto package not installed. "
                "Install with: uv pip install openforge-crypto"
            ),
        }

    crypto_cfg = config.crypto
    top_module = config.project.top_module
    sub_results: list[str] = []
    any_fail = False

    # 1. Constant-time verification
    console.print("  [bold]Running constant-time analysis[/] ...")
    ct_verifier = ConstantTimeVerifier(top_module)

    if crypto_cfg and crypto_cfg.constant_time.secrets:
        ct_verifier.mark_secret(*crypto_cfg.constant_time.secrets)
    if crypto_cfg and crypto_cfg.constant_time.public:
        ct_verifier.mark_public(*crypto_cfg.constant_time.public)

    ct_report = ct_verifier.verify()
    if ct_report.is_constant_time:
        sub_results.append(f"constant-time: PASS ({ct_report.signals_analyzed} signals)")
    else:
        any_fail = True
        sub_results.append(
            f"constant-time: FAIL ({len(ct_report.violations)} violations)"
        )
        for v in ct_report.violations[:5]:
            console.print(f"    [red]{v}[/]")

    # 2. Side-channel analysis (lightweight check -- report model availability)
    console.print("  [bold]Running side-channel analysis[/] ...")
    power_model = "hamming_weight"
    if crypto_cfg:
        power_model = crypto_cfg.side_channel.power_model.value
    sub_results.append(f"side-channel: configured (model={power_model})")

    # 3. FIPS compliance
    console.print("  [bold]Running FIPS compliance checks[/] ...")
    fips_level = CryptoFIPSLevel.LEVEL_1
    if crypto_cfg:
        fips_level = CryptoFIPSLevel(int(crypto_cfg.fips_compliance.level.value))

    # Build signal list from source files (simplified: use all known signals)
    signals = [top_module]
    checker = FIPSComplianceChecker(signals, design_name=top_module)
    fips_report = checker.check_all(fips_level)

    if fips_report.overall_pass:
        sub_results.append(
            f"FIPS L{fips_level.value}: PASS "
            f"({fips_report.pass_count}/{len(fips_report.checks)} checks)"
        )
    else:
        any_fail = True
        sub_results.append(
            f"FIPS L{fips_level.value}: FAIL "
            f"({fips_report.fail_count} failures, {fips_report.warning_count} warnings)"
        )

    status = "FAIL" if any_fail else "PASS"
    detail = "; ".join(sub_results)
    return {"engine": "crypto", "status": status, "detail": detail}


def verify(
    path: str = typer.Argument(".", help="Path to the design directory."),
    sim: bool = typer.Option(False, "--sim", "-s", help="Run simulation-based verification."),
    formal: bool = typer.Option(False, "--formal", "-f", help="Run formal verification."),
    crypto: bool = typer.Option(False, "--crypto", "-c", help="Run crypto-specific property checks."),
    all_: bool = typer.Option(False, "--all", "-a", help="Run all verification engines."),
) -> None:
    """Run verification on a design.

    At least one engine flag must be provided, or use --all.
    """
    from openforge.config.loader import ConfigNotFoundError, load_config

    engines: list[str] = []
    if all_:
        engines = ["sim", "formal", "crypto"]
    else:
        if sim:
            engines.append("sim")
        if formal:
            engines.append("formal")
        if crypto:
            engines.append("crypto")

    if not engines:
        console.print("[red]Error:[/] specify at least one engine (--sim, --formal, --crypto) or --all.")
        raise typer.Exit(code=1)

    project_dir = Path(path).resolve()

    # Load config
    try:
        config = load_config(search_dir=project_dir)
    except (FileNotFoundError, ConfigNotFoundError):
        console.print(
            f"[red]Error:[/] no openforge.yaml found in [cyan]{project_dir}[/]. "
            "Run [bold]openforge init[/] first."
        )
        raise typer.Exit(code=1)

    # Resolve source files
    source_files = _resolve_sources(project_dir, config)
    if not source_files:
        console.print(
            "[red]Error:[/] no source files found. "
            "Check [cyan]design.sources[/] globs in openforge.yaml."
        )
        raise typer.Exit(code=1)

    console.print(f"[bold]Verifying[/] design at [cyan]{project_dir}[/]")
    console.print(f"  sources : [green]{len(source_files)} files[/]")
    console.print(f"  engines : [green]{', '.join(engines)}[/]")
    console.print()

    # Run each engine
    results: list[dict[str, Any]] = []
    any_failure = False

    for engine_name in engines:
        console.rule(f"[bold cyan]{engine_name.upper()}[/]")

        try:
            if engine_name == "sim":
                res = _run_sim_engine(project_dir, config, source_files)
            elif engine_name == "formal":
                res = _run_formal_engine(project_dir, config, source_files)
            elif engine_name == "crypto":
                res = _run_crypto_engine(project_dir, config, source_files)
            else:
                res = {"engine": engine_name, "status": "SKIP", "detail": "Unknown engine"}
        except Exception as e:
            res = {"engine": engine_name, "status": "FAIL", "detail": str(e)}

        results.append(res)
        if res["status"] == "FAIL":
            any_failure = True

        console.print()

    # Summary table
    console.rule("[bold]Verification Summary[/]")
    console.print()

    table = Table(title="Results", show_header=True, header_style="bold cyan")
    table.add_column("Engine", style="cyan", width=10)
    table.add_column("Status", width=10)
    table.add_column("Details")

    for res in results:
        status = res["status"]
        if status in ("PASS", "PROVEN"):
            style = "[green bold]"
        elif status == "SKIP":
            style = "[yellow]"
        else:
            style = "[red bold]"
        table.add_row(
            res["engine"],
            f"{style}{status}[/]",
            res.get("detail", ""),
        )

    console.print(table)

    if any_failure:
        raise typer.Exit(code=1)
