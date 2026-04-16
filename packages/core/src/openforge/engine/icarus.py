"""Icarus Verilog simulation engine -- compile and simulate RTL."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class IcarusEngine(ToolEngine):
    """Wraps Icarus Verilog (iverilog) and the VVP simulation runtime.

    Typical workflow::

        engine = IcarusEngine()
        result = engine.compile(["rtl/top.v"], top_module="top", output="top.vvp")
        if result.ok:
            sim = engine.simulate("top.vvp")
    """

    BINARY = "iverilog"
    DOCKER_IMAGE = "hdlc/sim:latest"

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
            return self.run(["-V"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["-V"])
        if result.ok or result.stderr:
            # iverilog prints version info to stderr:
            # "Icarus Verilog version 12.0 (stable) ..."
            text = result.stderr + result.stdout
            if m := re.search(r"Icarus Verilog version\s+([\d.]+)", text):
                return m.group(1)
            lines = text.strip().splitlines()
            if lines:
                return lines[0]
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def compile(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str | None = None,
        output: str | PathLike[str] = "a.out",
        includes: Sequence[str | PathLike[str]] = (),
        defines: Mapping[str, str] = {},
        generation: str | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Compile Verilog sources into a VVP simulation file.

        Parameters
        ----------
        sources:
            Verilog source files.
        top_module:
            Top-level module name (``-s``).
        output:
            Output VVP file path (``-o``).
        includes:
            Include search directories (``-I``).
        defines:
            Preprocessor defines (``-D``).
        generation:
            Verilog generation flag (e.g. ``"2012"`` for ``-g2012``).
        extra_args:
            Arbitrary extra flags appended to the command.
        """
        args: list[str] = ["-o", str(output)]

        if top_module:
            args.extend(["-s", top_module])

        if generation:
            args.append(f"-g{generation}")

        for inc in includes:
            args.extend(["-I", str(inc)])

        for name, value in defines.items():
            if value:
                args.append(f"-D{name}={value}")
            else:
                args.append(f"-D{name}")

        args.extend(str(s) for s in sources)
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def simulate(
        self,
        vvp_file: str | PathLike[str],
        *,
        plusargs: Mapping[str, str] = {},
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a compiled VVP simulation file.

        Parameters
        ----------
        vvp_file:
            Path to the compiled ``.vvp`` file.
        plusargs:
            Simulation plusargs passed as ``+key=value``.
        extra_args:
            Arbitrary extra flags.
        """
        # vvp is a separate binary; build command manually
        vvp_args: list[str] = [str(vvp_file)]

        for key, val in plusargs.items():
            vvp_args.append(f"+{key}={val}")

        vvp_args.extend(extra_args)

        # Temporarily swap binary to vvp for this invocation
        saved_binary = self.binary
        try:
            self.binary = "vvp"
            return self.run(vvp_args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = saved_binary
