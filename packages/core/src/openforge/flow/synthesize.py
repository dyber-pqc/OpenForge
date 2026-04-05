"""Synthesis flow step -- runs Yosys RTL synthesis."""

from __future__ import annotations

from typing import Any

from openforge.engine.yosys import YosysEngine
from openforge.flow.workflow import FlowResult, StepStatus


def run_synthesis(context: dict[str, Any]) -> FlowResult:
    """Execute RTL synthesis via Yosys.

    Expects *context* keys:

    * ``source_files`` -- list of resolved source file paths
    * ``top_module`` -- top-level module name
    * ``liberty_file`` -- path to Liberty timing library (optional)
    * ``output_verilog`` -- output netlist path (optional)
    * ``output_json`` -- output JSON netlist path (optional)
    * ``flatten`` -- flatten hierarchy (default False)
    * ``cwd`` -- project working directory
    * ``timeout`` -- synthesis timeout in seconds
    """
    source_files: list[str] = context.get("source_files", [])
    top_module: str = context.get("top_module", "top")
    liberty_file = context.get("liberty_file")
    output_verilog = context.get("output_verilog")
    output_json = context.get("output_json")
    flatten: bool = context.get("flatten", False)
    cwd = context.get("cwd")
    timeout: float | None = context.get("timeout")

    if not source_files:
        return FlowResult(status=StepStatus.SKIPPED, output="No source files to synthesize.")

    engine = YosysEngine()

    if not engine.check_installed():
        return FlowResult(
            status=StepStatus.FAILED,
            errors=["Yosys not found. Install it or use Docker backend."],
        )

    result = engine.synthesize(
        source_files,
        top_module=top_module,
        liberty_file=liberty_file,
        output_verilog=output_verilog,
        output_json=output_json,
        flatten=flatten,
        cwd=cwd,
        timeout=timeout,
    )

    artifacts = {}
    stats = engine.read_stats(result)
    if stats:
        artifacts["cells"] = str(stats.get("cells", 0))
        artifacts["wires"] = str(stats.get("wires", 0))

    if output_verilog:
        artifacts["netlist_verilog"] = str(output_verilog)
    if output_json:
        artifacts["netlist_json"] = str(output_json)

    return FlowResult(
        status=StepStatus.PASSED if result.ok else StepStatus.FAILED,
        output=result.stdout,
        errors=[result.stderr] if not result.ok and result.stderr.strip() else [],
        artifacts=artifacts,
    )
