"""Simulation flow step -- compile and run RTL simulation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openforge.config.schema import SimulationTool
from openforge.engine.verilator import VerilatorEngine
from openforge.flow.workflow import FlowResult, StepStatus


def run_simulation(context: dict[str, Any]) -> FlowResult:
    """Compile and execute RTL simulation.

    Expects *context* keys:

    * ``source_files`` -- list of resolved source file paths
    * ``top_module`` -- top-level module name
    * ``sim_tool`` -- SimulationTool enum value (default verilator)
    * ``includes`` -- include directories
    * ``coverage`` -- enable coverage collection
    * ``cwd`` -- project working directory
    * ``timeout`` -- simulation timeout in seconds
    """
    source_files: list[str] = context.get("source_files", [])
    top_module: str = context.get("top_module", "top")
    sim_tool = context.get("sim_tool", SimulationTool.VERILATOR)
    includes: list[str] = context.get("includes", [])
    coverage: bool = context.get("coverage", False)
    cwd = context.get("cwd")
    timeout: float | None = context.get("timeout")

    if not source_files:
        return FlowResult(status=StepStatus.SKIPPED, output="No source files to simulate.")

    if sim_tool == SimulationTool.VERILATOR:
        return _run_verilator(source_files, top_module, includes, coverage, cwd, timeout)

    return FlowResult(
        status=StepStatus.FAILED,
        errors=[f"Simulation tool '{sim_tool}' not yet implemented. Use 'verilator'."],
    )


def _run_verilator(
    sources: list[str],
    top_module: str,
    includes: list[str],
    coverage: bool,
    cwd: str | None,
    timeout: float | None,
) -> FlowResult:
    engine = VerilatorEngine()

    if not engine.check_installed():
        return FlowResult(
            status=StepStatus.FAILED,
            errors=["Verilator not found. Install it or use Docker backend."],
        )

    # Compile
    obj_dir = "obj_dir"
    compile_result = engine.compile(
        sources,
        top_module=top_module,
        output_dir=obj_dir,
        includes=includes,
        trace=True,
        coverage=coverage,
        cwd=cwd,
        timeout=timeout,
    )

    if not compile_result.ok:
        return FlowResult(
            status=StepStatus.FAILED,
            output=compile_result.stdout,
            errors=[f"Compilation failed:\n{compile_result.stderr}"],
        )

    # Simulate
    binary = str(Path(obj_dir) / f"V{top_module}")
    sim_result = engine.simulate(binary, cwd=cwd, timeout=timeout)

    artifacts = {}
    # Check for waveform output
    fst_file = Path(cwd or ".") / "dump.fst"
    if fst_file.exists():
        artifacts["waveform"] = str(fst_file)

    return FlowResult(
        status=StepStatus.PASSED if sim_result.ok else StepStatus.FAILED,
        output=sim_result.stdout,
        errors=[sim_result.stderr] if not sim_result.ok and sim_result.stderr.strip() else [],
        artifacts=artifacts,
    )
