"""SymbiYosys formal verification engine."""

from __future__ import annotations

import re
from os import PathLike
from textwrap import dedent
from typing import Mapping, Sequence

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


class SymbiYosysEngine(ToolEngine):
    """Wraps SymbiYosys (sby) for formal hardware verification.

    Typical workflow::

        engine = SymbiYosysEngine()
        config = engine.generate_config(
            design_files=["rtl/alu.sv"],
            top_module="alu",
            properties=["props/alu_props.sv"],
            mode="bmc",
            depth=20,
        )
        Path("alu.sby").write_text(config)
        result = engine.run_verification("alu.sby")
    """

    BINARY = "sby"
    DOCKER_IMAGE = "hdlc/formal:latest"

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
            return self.run(["--help"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--help"])
        if result.ok or result.stdout:
            # "sby -- SymbiYosys 0.38 ..."
            text = result.stdout + result.stderr
            if m := re.search(r"SymbiYosys\s+([\d.]+)", text):
                return m.group(1)
            lines = text.strip().splitlines()
            if lines:
                return lines[0]
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_verification(
        self,
        sby_file: str | PathLike[str],
        *,
        task: str | None = None,
        force: bool = True,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a SymbiYosys verification job.

        Parameters
        ----------
        sby_file:
            Path to the ``.sby`` configuration file.
        task:
            Named task within the ``.sby`` file to run.
        force:
            Overwrite previous output directory (``-f``).
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = []

        if force:
            args.append("-f")

        args.extend(extra_args)
        args.append(str(sby_file))

        if task:
            args.append(task)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    @staticmethod
    def generate_config(
        design_files: Sequence[str | PathLike[str]],
        *,
        top_module: str = "top",
        properties: Sequence[str | PathLike[str]] = (),
        mode: str = "bmc",
        depth: int = 20,
        engines: Sequence[str] = ("smtbmc",),
        multiclock: bool = False,
        extra_options: Mapping[str, str] = {},
    ) -> str:
        """Generate the content of a ``.sby`` configuration file.

        Parameters
        ----------
        design_files:
            RTL source files for the design under verification.
        top_module:
            Top-level module name.
        properties:
            SystemVerilog assertion / property files.
        mode:
            Verification mode (``"bmc"``, ``"prove"``, ``"cover"``, ``"live"``).
        depth:
            BMC or induction depth.
        engines:
            Solver engines to use (e.g. ``"smtbmc"``, ``"aiger"``).
        multiclock:
            Enable multi-clock mode.
        extra_options:
            Additional ``[options]`` key-value pairs.

        Returns
        -------
        str
            Complete ``.sby`` file content ready to be written to disk.
        """
        lines: list[str] = []

        # -- [options] -----------------------------------------------------
        lines.append("[options]")
        lines.append(f"mode {mode}")
        lines.append(f"depth {depth}")
        if multiclock:
            lines.append("multiclock on")
        for key, val in extra_options.items():
            lines.append(f"{key} {val}")

        # -- [engines] -----------------------------------------------------
        lines.append("")
        lines.append("[engines]")
        for eng in engines:
            lines.append(eng)

        # -- [script] ------------------------------------------------------
        lines.append("")
        lines.append("[script]")
        all_files = [*design_files, *properties]
        for src in all_files:
            name = str(src)
            if name.endswith((".sv", ".svh")):
                lines.append(f"read -sv {name}")
            elif name.endswith((".vhd", ".vhdl")):
                lines.append(f"read -vhdl {name}")
            else:
                lines.append(f"read -formal {name}")
        lines.append(f"prep -top {top_module}")

        # -- [files] -------------------------------------------------------
        lines.append("")
        lines.append("[files]")
        for src in all_files:
            lines.append(str(src))

        lines.append("")
        return "\n".join(lines)
