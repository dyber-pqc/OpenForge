"""Verilator simulation engine -- compile RTL to C++ and run."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class VerilatorEngine(ToolEngine):
    """Wraps the Verilator RTL-to-C++ compiler and simulation runner.

    Typical workflow::

        engine = VerilatorEngine()
        result = engine.compile(["rtl/top.sv"], top_module="top")
        if result.ok:
            sim = engine.simulate("obj_dir/Vtop")
    """

    BINARY = "verilator"
    DOCKER_IMAGE = "verilator/verilator:latest"

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
            # Verilator prints "Verilator 5.024 ..."
            if m := re.search(r"Verilator\s+([\d.]+)", result.stdout):
                return m.group(1)
            return result.stdout.strip().splitlines()[0]
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def compile(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str = "top",
        output_dir: str | PathLike[str] = "obj_dir",
        includes: Sequence[str | PathLike[str]] = (),
        trace: bool = True,
        trace_format: str = "fst",
        coverage: bool = False,
        threads: int = 1,
        warning_flags: Sequence[str] = ("-Wall",),
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Compile RTL sources into a simulation binary.

        Parameters
        ----------
        sources:
            Verilog / SystemVerilog source files.
        top_module:
            Name of the top-level module.
        output_dir:
            Build artefact directory (``-Mdir``).
        includes:
            ``-I`` include search paths.
        trace:
            Enable waveform tracing.
        trace_format:
            ``"fst"`` (default) or ``"vcd"``.
        coverage:
            Enable code-coverage instrumentation.
        threads:
            Number of simulation threads (``--threads``).
        warning_flags:
            Verilator warning flags (e.g. ``-Wall``, ``-Wno-fatal``).
        extra_args:
            Arbitrary extra flags appended to the command.
        """
        args: list[str] = [
            "--cc",
            "--exe",
            "--build",
            "--top-module", top_module,
            "-Mdir", str(output_dir),
        ]

        if trace:
            args.append(f"--trace-{trace_format}")

        if coverage:
            args.append("--coverage")

        if threads > 1:
            args.extend(["--threads", str(threads)])

        args.extend(warning_flags)

        for inc in includes:
            args.extend(["-I", str(inc)])

        args.extend(str(s) for s in sources)
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def simulate(
        self,
        binary: str | PathLike[str],
        *,
        plusargs: dict[str, str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a previously compiled Verilator simulation binary.

        The *binary* is invoked directly (not through ``verilator``), so
        this builds the command manually rather than using :meth:`run`.
        """
        cmd: list[str] = [str(Path(binary).resolve())]

        if plusargs:
            for key, val in plusargs.items():
                cmd.append(f"+{key}={val}")

        import subprocess
        import time

        work_dir = str(cwd) if cwd else None
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                env=dict(env) if env else None,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=time.monotonic() - start,
                command=cmd,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                returncode=-1,
                stderr=f"Simulation timed out after {timeout}s",
                duration=time.monotonic() - start,
                command=cmd,
            )
