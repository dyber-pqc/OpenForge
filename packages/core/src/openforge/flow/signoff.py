"""Signoff flow step -- aggregates results and checks criteria."""

from __future__ import annotations

from typing import Any

from openforge.flow.workflow import FlowResult, StepStatus


def run_signoff(context: dict[str, Any]) -> FlowResult:
    """Check signoff criteria against collected flow results.

    Expects *context* keys:

    * ``flow_results`` -- dict mapping step name to FlowResult
    * ``required_steps`` -- list of step names that must pass (default: all)
    """
    flow_results: dict[str, FlowResult] = context.get("flow_results", {})
    required: list[str] = context.get("required_steps", list(flow_results.keys()))

    failures = []
    for step_name in required:
        result = flow_results.get(step_name)
        if result is None:
            failures.append(f"{step_name}: not executed")
        elif result.status != StepStatus.PASSED:
            failures.append(f"{step_name}: {result.status.value}")

    if failures:
        return FlowResult(
            status=StepStatus.FAILED,
            output="Signoff FAILED. The following steps did not pass:\n"
            + "\n".join(f"  - {f}" for f in failures),
            errors=failures,
        )

    return FlowResult(
        status=StepStatus.PASSED,
        output=f"Signoff PASSED. All {len(required)} required steps passed.",
    )
