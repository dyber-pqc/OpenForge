"""OpenROAD RTL-to-GDSII flow engine."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class OpenROADEngine(ToolEngine):
    """Wraps the OpenROAD physical design toolchain.

    Typical workflow::

        engine = OpenROADEngine()
        result = engine.run_tcl("flow.tcl")
    """

    BINARY = "openroad"
    DOCKER_IMAGE = "openroad/flow:latest"

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
            return self.run(["-version"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["-version"])
        text = result.stdout + result.stderr
        # e.g. "OpenROAD v2.0-12345-g..."
        if m := re.search(r"(?:OpenROAD|openroad)\s+v?([\d.]+[\w.-]*)", text):
            return m.group(1)
        lines = text.strip().splitlines()
        if lines:
            return lines[0].strip()
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_flow(
        self,
        config_file: str | PathLike[str],
        *,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run an OpenROAD-flow-scripts based flow.

        Parameters
        ----------
        config_file:
            Path to the flow configuration / TCL script.
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = ["-exit", str(config_file)]
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def run_tcl(
        self,
        tcl_script: str | PathLike[str],
        *,
        no_init: bool = False,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute a TCL script within OpenROAD and exit.

        Parameters
        ----------
        tcl_script:
            Path to the TCL script.
        no_init:
            Skip default initialization scripts (``-no_init``).
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = []

        if no_init:
            args.append("-no_init")

        args.extend(["-exit", str(tcl_script)])
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def floorplan(
        self,
        *,
        lef: str | PathLike[str],
        def_file: str | PathLike[str] | None = None,
        die_area: tuple[float, float, float, float] | None = None,
        core_area: tuple[float, float, float, float] | None = None,
        site_name: str = "unithd",
        extra_tcl: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Generate and run a TCL-based floorplan script.

        Parameters
        ----------
        lef:
            LEF technology / macro file.
        def_file:
            Optional existing DEF file to read.
        die_area:
            Die area as ``(x0, y0, x1, y1)`` in microns.
        core_area:
            Core area as ``(x0, y0, x1, y1)`` in microns.
        site_name:
            Placement site name for initialization.
        extra_tcl:
            Additional TCL commands appended to the script.
        """
        tcl_lines: list[str] = [
            f"read_lef {lef}",
        ]

        if def_file:
            tcl_lines.append(f"read_def {def_file}")

        if die_area and core_area:
            da = " ".join(str(v) for v in die_area)
            ca = " ".join(str(v) for v in core_area)
            tcl_lines.append(
                f"initialize_floorplan -die_area {{{da}}} -core_area {{{ca}}} -site {site_name}"
            )

        tcl_lines.extend(extra_tcl)
        tcl_lines.append("exit")

        tcl_content = "\n".join(tcl_lines) + "\n"

        work_dir = Path(cwd) if cwd else Path.cwd()
        tcl_path = work_dir / ".openroad_floorplan.tcl"
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
