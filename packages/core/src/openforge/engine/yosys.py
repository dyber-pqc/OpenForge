"""Yosys open-source synthesis engine."""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from typing import Mapping, Sequence

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


class YosysEngine(ToolEngine):
    """Wraps the Yosys RTL synthesis framework.

    Typical workflow::

        engine = YosysEngine()
        result = engine.synthesize(
            sources=["rtl/aes.sv"],
            top_module="aes_core",
            liberty_file="sky130_fd_sc_hd.lib",
            output_json="synth.json",
        )
    """

    BINARY = "yosys"
    DOCKER_IMAGE = "hdlc/yosys:latest"

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
        if result.ok:
            # "Yosys 0.38 (git sha1 ...)"
            if m := re.search(r"Yosys\s+([\d.]+)", result.stdout):
                return m.group(1)
            return result.stdout.strip().splitlines()[0]
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def synthesize(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str = "top",
        liberty_file: str | PathLike[str] | None = None,
        output_verilog: str | PathLike[str] | None = None,
        output_json: str | PathLike[str] | None = None,
        output_blif: str | PathLike[str] | None = None,
        flatten: bool = False,
        extra_commands: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a full RTL-to-gate synthesis flow.

        Constructs a Yosys script from the provided parameters and
        executes it via ``yosys -p <script>``.

        Parameters
        ----------
        sources:
            HDL source files (``.v``, ``.sv``, ``.vhd``).
        top_module:
            The top-level module name for hierarchy resolution.
        liberty_file:
            Technology library for ABC mapping.  When *None* a generic
            gate-level synthesis is performed.
        output_verilog:
            Write synthesised netlist as Verilog.
        output_json:
            Write synthesised netlist as JSON.
        output_blif:
            Write synthesised netlist as BLIF.
        flatten:
            Flatten the design hierarchy before mapping.
        extra_commands:
            Additional Yosys commands injected after ``opt``.
        """
        script_lines: list[str] = []

        # -- Read sources --------------------------------------------------
        for src in sources:
            p = Path(src)
            # Use POSIX paths (forward slashes) for Docker compatibility
            src_str = p.as_posix()
            match p.suffix:
                case ".sv" | ".svh":
                    script_lines.append(f"read_verilog -sv {src_str}")
                case ".vhd" | ".vhdl":
                    script_lines.append(f"read_vhdl {src_str}")
                case _:
                    script_lines.append(f"read_verilog {src_str}")

        # -- Elaborate -----------------------------------------------------
        script_lines.append(f"hierarchy -top {top_module}")

        if flatten:
            script_lines.append("flatten")

        script_lines += ["proc", "opt", "techmap", "opt"]

        # -- Technology mapping --------------------------------------------
        if liberty_file:
            script_lines.append(f"dfflibmap -liberty {liberty_file}")
            script_lines.append(f"abc -liberty {liberty_file}")

        script_lines.append("clean")

        # -- User commands -------------------------------------------------
        script_lines.extend(extra_commands)

        # -- Write outputs -------------------------------------------------
        if output_verilog:
            script_lines.append(f"write_verilog {output_verilog}")
        if output_json:
            script_lines.append(f"write_json {output_json}")
        if output_blif:
            script_lines.append(f"write_blif {output_blif}")

        script_lines.append("stat")

        script = "; ".join(script_lines)
        return self.run(["-p", script], cwd=cwd, env=env, timeout=timeout)

    def run_script(
        self,
        script_file: str | PathLike[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run an existing Yosys TCL / command script file."""
        return self.run(["-s", str(script_file)], cwd=cwd, env=env, timeout=timeout)

    def read_stats(self, synthesis_result: ToolResult) -> dict[str, int]:
        """Parse gate-count statistics from synthesis stdout.

        Returns a dict like ``{"cells": 1234, "wires": 567, ...}``.
        """
        stats: dict[str, int] = {}
        for line in synthesis_result.stdout.splitlines():
            line = line.strip()
            if m := re.match(r"Number of (\w[\w\s]*\w)\s*:\s*(\d+)", line):
                key = m.group(1).lower().replace(" ", "_")
                stats[key] = int(m.group(2))
        return stats
