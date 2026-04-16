"""Formal verification flow step -- runs SymbiYosys."""

from __future__ import annotations

from typing import Any

from openforge.flow.workflow import FlowResult, StepStatus


def run_formal(context: dict[str, Any]) -> FlowResult:
    """Execute formal verification via SymbiYosys.

    Expects *context* keys:

    * ``sby_file`` -- path to .sby configuration file
    * ``sby_task`` -- optional task name within the .sby file
    * ``cwd`` -- project working directory
    * ``timeout`` -- verification timeout in seconds

    If ``sby_file`` is not provided, attempts to auto-generate one from:

    * ``source_files``, ``top_module``, ``properties``, ``formal_depth``
    """
    from openforge.engine.symbiyosys import SymbiYosysEngine

    cwd = context.get("cwd")
    timeout: float | None = context.get("timeout")

    engine = SymbiYosysEngine()

    if not engine.check_installed():
        return FlowResult(
            status=StepStatus.FAILED,
            errors=["SymbiYosys (sby) not found. Install it or use Docker backend."],
        )

    sby_file = context.get("sby_file")

    if not sby_file:
        # Auto-generate .sby config
        source_files = context.get("source_files", [])
        top_module = context.get("top_module", "top")
        properties = context.get("properties", [])
        depth = context.get("formal_depth", 100)

        if not source_files:
            return FlowResult(status=StepStatus.SKIPPED, output="No source files for formal.")

        sby_content = engine.generate_config(
            design_files=source_files,
            top_module=top_module,
            properties=properties,
            mode="prove",
            depth=depth,
        )

        # Write temporary .sby file
        from pathlib import Path

        sby_path = Path(cwd or ".") / ".openforge" / "formal.sby"
        sby_path.parent.mkdir(parents=True, exist_ok=True)
        sby_path.write_text(sby_content)
        sby_file = str(sby_path)

    result = engine.run_verification(sby_file, cwd=cwd, timeout=timeout)

    # Parse result status
    if result.ok:
        proven = "PROVEN" in result.stdout.upper() or "PASS" in result.stdout.upper()
        status = StepStatus.PASSED if proven else StepStatus.FAILED
    else:
        status = StepStatus.FAILED

    # Extract counterexample info if failed
    errors = []
    if status == StepStatus.FAILED:
        for line in result.stdout.splitlines():
            if "FAIL" in line.upper() or "counterexample" in line.lower():
                errors.append(line.strip())
        if result.stderr.strip():
            errors.append(result.stderr.strip())

    return FlowResult(
        status=status,
        output=result.stdout,
        errors=errors,
    )
