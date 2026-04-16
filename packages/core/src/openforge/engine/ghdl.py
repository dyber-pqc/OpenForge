"""GHDL VHDL simulation engine -- analyze, elaborate, and simulate."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class GHDLEngine(ToolEngine):
    """Wraps the GHDL open-source VHDL simulator.

    Typical workflow::

        engine = GHDLEngine()
        engine.analyze(["rtl/alu.vhd"])
        engine.elaborate("alu")
        result = engine.simulate("alu", stop_time="100ns", wave_file="alu.ghw")
    """

    BINARY = "ghdl"
    DOCKER_IMAGE = "hdlc/ghdl:latest"

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
            # "GHDL 4.1.0 (v4.1.0) ..."
            if m := re.search(r"GHDL\s+([\d.]+)", result.stdout):
                return m.group(1)
            return result.stdout.strip().splitlines()[0]
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def analyze(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        std: str = "08",
        work: str | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Analyze (compile) VHDL source files.

        Parameters
        ----------
        sources:
            VHDL source files.
        std:
            VHDL standard (``"87"``, ``"93"``, ``"02"``, ``"08"``).
        work:
            Work library name (``--work=``).
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = ["-a", f"--std={std}"]

        if work:
            args.append(f"--work={work}")

        args.extend(str(s) for s in sources)
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def elaborate(
        self,
        top_unit: str,
        *,
        std: str = "08",
        work: str | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Elaborate a VHDL design unit.

        Parameters
        ----------
        top_unit:
            Top-level entity or configuration name.
        std:
            VHDL standard.
        work:
            Work library name.
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = ["-e", f"--std={std}"]

        if work:
            args.append(f"--work={work}")

        args.append(top_unit)
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def simulate(
        self,
        top_unit: str,
        *,
        std: str = "08",
        stop_time: str | None = None,
        wave_file: str | PathLike[str] | None = None,
        vcd_file: str | PathLike[str] | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a simulation of an elaborated design.

        Parameters
        ----------
        top_unit:
            Top-level entity or configuration name.
        std:
            VHDL standard.
        stop_time:
            Simulation stop time (e.g. ``"100ns"``, ``"1ms"``).
        wave_file:
            GHW waveform output file (``--wave=``).
        vcd_file:
            VCD waveform output file (``--vcd=``).
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = ["-r", f"--std={std}", top_unit]

        if stop_time:
            args.append(f"--stop-time={stop_time}")

        if wave_file:
            args.append(f"--wave={wave_file}")

        if vcd_file:
            args.append(f"--vcd={vcd_file}")

        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)
