"""Static timing analysis flow step -- runs OpenSTA."""

from __future__ import annotations

import re
from typing import Any

from openforge.flow.workflow import FlowResult, StepStatus


def run_sta(context: dict[str, Any]) -> FlowResult:
    """Execute static timing analysis via OpenSTA.

    Expects *context* keys:

    * ``liberty_file`` -- Liberty timing library path
    * ``verilog_netlist`` -- gate-level netlist (post-synthesis)
    * ``sdc_file`` -- SDC timing constraints
    * ``top_module`` -- top-level module name
    * ``cwd`` -- project working directory
    * ``timeout`` -- STA timeout in seconds
    """
    from openforge.engine.opensta import OpenSTAEngine

    liberty_file = context.get("liberty_file")
    verilog_netlist = context.get("verilog_netlist")
    sdc_file = context.get("sdc_file")
    top_module: str = context.get("top_module", "top")
    cwd = context.get("cwd")
    timeout: float | None = context.get("timeout")

    if not liberty_file or not verilog_netlist:
        return FlowResult(
            status=StepStatus.SKIPPED,
            output="STA requires liberty_file and verilog_netlist. Skipping.",
        )

    engine = OpenSTAEngine()

    if not engine.check_installed():
        return FlowResult(
            status=StepStatus.FAILED,
            errors=["OpenSTA (sta) not found. Install it or use Docker backend."],
        )

    result = engine.run_timing(
        liberty=liberty_file,
        verilog_netlist=verilog_netlist,
        sdc=sdc_file,
        top_module=top_module,
        cwd=cwd,
        timeout=timeout,
    )

    slack = engine.parse_slack(result)
    artifacts = {}
    if slack is not None:
        artifacts["worst_slack_ns"] = f"{slack:.3f}"
        artifacts["timing_met"] = "true" if slack >= 0 else "false"

    errors = []
    if not result.ok:
        errors.append(result.stderr.strip() if result.stderr.strip() else "STA failed")

    return FlowResult(
        status=StepStatus.PASSED if result.ok else StepStatus.FAILED,
        output=result.stdout,
        errors=errors,
        artifacts=artifacts,
    )
