"""OpenSTA static timing analysis engine."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class OpenSTAEngine(ToolEngine):
    """Wraps OpenSTA for static timing analysis.

    Typical workflow::

        engine = OpenSTAEngine()
        result = engine.run_timing(
            liberty="sky130.lib",
            verilog_netlist="synth.v",
            sdc="constraints.sdc",
            top_module="top",
        )
        slack = engine.parse_slack(result)
    """

    BINARY = "sta"
    DOCKER_IMAGE = "openroad/opensta:latest"

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            binary_override=binary_override,
        )

    # ------------------------------------------------------------------
    # ToolEngine interface
    # ------------------------------------------------------------------

    def check_installed(self) -> bool:
        if self.backend == ExecutionBackend.DOCKER:
            return self.run(["-help"]).returncode != -1
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["-version"])
        text = result.stdout + result.stderr
        if m := re.search(r"(\d+\.\d+[\w.-]*)", text):
            return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_timing(
        self,
        *,
        liberty: str | PathLike[str],
        verilog_netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        top_module: str = "top",
        extra_tcl: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a static timing analysis flow.

        Generates a TCL script that reads the liberty library, gate-level
        netlist, and SDC constraints, then reports timing.

        Parameters
        ----------
        liberty:
            Liberty timing library (``.lib``) file.
        verilog_netlist:
            Gate-level Verilog netlist.
        sdc:
            Synopsys Design Constraints file.
        top_module:
            Top-level module name.
        extra_tcl:
            Additional TCL commands inserted before ``report_checks``.
        """
        tcl_lines: list[str] = [
            f"read_liberty {liberty}",
            f"read_verilog {verilog_netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
            *extra_tcl,
            "report_checks -path_delay max -format full",
            "report_checks -path_delay min -format full",
            "report_tns",
            "report_wns",
            "exit",
        ]

        tcl_content = "\n".join(tcl_lines) + "\n"

        # Write the TCL script to a temporary file and run it
        work_dir = Path(cwd) if cwd else Path.cwd()
        tcl_path = work_dir / ".opensta_timing.tcl"
        tcl_path.write_text(tcl_content)

        try:
            return self.run(
                ["-exit", str(tcl_path)],
                cwd=cwd,
                env=env,
                timeout=timeout,
            )
        finally:
            tcl_path.unlink(missing_ok=True)

    @staticmethod
    def parse_slack(result: ToolResult) -> float | None:
        """Extract the worst negative slack (WNS) from STA output.

        Parameters
        ----------
        result:
            A :class:`ToolResult` from :meth:`run_timing`.

        Returns
        -------
        float | None
            The worst slack value in nanoseconds, or *None* if parsing fails.
        """
        text = result.stdout + result.stderr
        # Look for "wns <value>" pattern from report_wns
        if m := re.search(r"wns\s+([-+]?\d+\.?\d*)", text):
            return float(m.group(1))
        # Also try "slack\s+(VIOLATED|MET)\s+([-+]?\d+\.?\d*)"
        if m := re.search(r"slack\s+\((?:VIOLATED|MET)\)\s+([-+]?\d+\.?\d*)", text):
            return float(m.group(1))
        return None
