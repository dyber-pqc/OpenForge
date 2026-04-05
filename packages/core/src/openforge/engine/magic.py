"""Magic VLSI layout tool engine."""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from typing import Mapping, Sequence

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


class MagicEngine(ToolEngine):
    """Wraps Magic for DRC, extraction, and layout scripting.

    Typical workflow::

        engine = MagicEngine()
        result = engine.run_drc("layout.mag", tech_file="sky130A.tech")
    """

    BINARY = "magic"
    DOCKER_IMAGE = ""  # No standard Docker image

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
            return self.run(["--version"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--version"])
        text = result.stdout + result.stderr
        # "magic 8.3.460"
        if m := re.search(r"magic\s+([\d.]+)", text, re.IGNORECASE):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+[\d.]*)", text):
            return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_drc(
        self,
        mag_file: str | PathLike[str],
        *,
        tech_file: str | PathLike[str] | None = None,
        extra_tcl: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run DRC on a Magic layout file.

        Generates a TCL script that loads the cell, runs ``drc check``,
        and reports violations.

        Parameters
        ----------
        mag_file:
            Magic layout file (``.mag``).
        tech_file:
            Technology file to load (``-T``).
        extra_tcl:
            Additional TCL commands inserted before the DRC report.
        """
        cell_name = Path(mag_file).stem

        tcl_lines: list[str] = [
            f"load {mag_file}",
            "select top cell",
            "drc check",
            "drc catchup",
            *extra_tcl,
            f"set drc_count [drc listall why]",
            "puts \"DRC errors: $drc_count\"",
            "quit -noprompt",
        ]

        return self._run_magic_tcl(
            tcl_lines,
            tech_file=tech_file,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )

    def extract(
        self,
        mag_file: str | PathLike[str],
        *,
        output_spice: str | PathLike[str] | None = None,
        tech_file: str | PathLike[str] | None = None,
        parasitic: bool = False,
        extra_tcl: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Extract a layout to SPICE netlist.

        Parameters
        ----------
        mag_file:
            Magic layout file (``.mag``).
        output_spice:
            Output SPICE file path. Defaults to ``<cell>.spice``.
        tech_file:
            Technology file to load (``-T``).
        parasitic:
            Enable parasitic extraction (capacitance and resistance).
        extra_tcl:
            Additional TCL commands.
        """
        cell_name = Path(mag_file).stem
        spice_out = output_spice or f"{cell_name}.spice"

        tcl_lines: list[str] = [
            f"load {mag_file}",
            "select top cell",
            "extract all",
        ]

        if parasitic:
            tcl_lines.extend([
                "ext2sim labels on",
                "ext2sim",
                f"extresist tolerance 10",
                "extresist all",
            ])

        tcl_lines.extend([
            f"ext2spice lvs",
            f"ext2spice -o {spice_out}",
            *extra_tcl,
            "quit -noprompt",
        ])

        return self._run_magic_tcl(
            tcl_lines,
            tech_file=tech_file,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )

    def run_tcl(
        self,
        tcl_script: str | PathLike[str],
        *,
        tech_file: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute an existing TCL script in Magic non-interactively.

        Parameters
        ----------
        tcl_script:
            Path to the TCL script file.
        tech_file:
            Technology file to load (``-T``).
        """
        args: list[str] = ["-dnull", "-noconsole"]

        if tech_file:
            args.extend(["-T", str(tech_file)])

        args.append(str(tcl_script))

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_magic_tcl(
        self,
        tcl_lines: Sequence[str],
        *,
        tech_file: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Write TCL lines to a temp file and run Magic in batch mode."""
        tcl_content = "\n".join(tcl_lines) + "\n"

        work_dir = Path(cwd) if cwd else Path.cwd()
        tcl_path = work_dir / ".magic_batch.tcl"
        tcl_path.write_text(tcl_content)

        try:
            args: list[str] = ["-dnull", "-noconsole"]
            if tech_file:
                args.extend(["-T", str(tech_file)])
            args.append(str(tcl_path))
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            tcl_path.unlink(missing_ok=True)
