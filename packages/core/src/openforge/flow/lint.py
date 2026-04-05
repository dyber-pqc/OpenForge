"""Lint flow step -- runs Verible lint on design sources."""

from __future__ import annotations

from typing import Any

from openforge.engine.verible import VeribleEngine
from openforge.flow.workflow import FlowResult, StepStatus


def run_lint(context: dict[str, Any]) -> FlowResult:
    """Execute linting on all design source files.

    Expects *context* keys:

    * ``source_files`` -- list of resolved source file paths
    * ``cwd`` -- project working directory
    """
    source_files: list[str] = context.get("source_files", [])
    cwd = context.get("cwd")

    if not source_files:
        return FlowResult(
            status=StepStatus.SKIPPED,
            output="No source files to lint.",
        )

    engine = VeribleEngine()

    if not engine.check_installed():
        return FlowResult(
            status=StepStatus.FAILED,
            errors=["verible-verilog-lint not found. Install Verible or use Docker backend."],
        )

    result = engine.lint(source_files, cwd=cwd)

    findings = engine.parse_lint_findings(result)
    errors = [f for f in findings if "error" in str(f.get("message", "")).lower()]

    return FlowResult(
        status=StepStatus.PASSED if result.ok else StepStatus.FAILED,
        output=result.stdout,
        errors=[result.stderr] if result.stderr.strip() else [],
        artifacts={
            "findings_count": str(len(findings)),
            "error_count": str(len(errors)),
        },
    )
