"""Cocotb testbench runner engine."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class CocotbEngine(ToolEngine):
    """Wraps cocotb for Python-based HDL testbench execution.

    Typical workflow::

        engine = CocotbEngine()
        result = engine.run_tests(
            test_module="test_alu",
            top_module="alu",
            simulator="icarus",
        )
    """

    BINARY = "cocotb-config"
    DOCKER_IMAGE = ""  # Typically installed via pip

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
        # "cocotb 1.9.0" or just "1.9.0"
        if m := re.search(r"(\d+\.\d+[\d.]*)", text):
            return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_tests(
        self,
        *,
        test_module: str,
        top_module: str,
        simulator: str = "icarus",
        sources: Sequence[str | PathLike[str]] = (),
        sim_build_dir: str | PathLike[str] = "sim_build",
        extra_env: Mapping[str, str] = {},
        use_makefile: bool = False,
        makefile_path: str | PathLike[str] | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run cocotb tests against an HDL design.

        Parameters
        ----------
        test_module:
            Python module containing the cocotb tests (without ``.py``).
        top_module:
            Top-level HDL module name (``TOPLEVEL``).
        simulator:
            Simulator to use (``"icarus"``, ``"verilator"``, ``"ghdl"``, etc.).
        sources:
            HDL source files (``VERILOG_SOURCES`` / ``VHDL_SOURCES``).
        sim_build_dir:
            Simulation build directory (``SIM_BUILD``).
        extra_env:
            Additional environment variables for the cocotb run.
        use_makefile:
            When *True*, invoke ``make`` with a cocotb Makefile instead of
            using ``cocotb-config`` runner.
        makefile_path:
            Path to a custom Makefile (implies ``use_makefile=True``).
        extra_args:
            Arbitrary extra flags.
        """
        # Build cocotb environment variables
        cocotb_env: dict[str, str] = {
            "MODULE": test_module,
            "TOPLEVEL": top_module,
            "TOPLEVEL_LANG": "verilog",
            "SIM": simulator,
            "SIM_BUILD": str(sim_build_dir),
        }

        if sources:
            verilog_srcs = []
            vhdl_srcs = []
            for src in sources:
                name = str(src)
                if name.endswith((".vhd", ".vhdl")):
                    vhdl_srcs.append(name)
                else:
                    verilog_srcs.append(name)

            if verilog_srcs:
                cocotb_env["VERILOG_SOURCES"] = " ".join(verilog_srcs)
            if vhdl_srcs:
                cocotb_env["VHDL_SOURCES"] = " ".join(vhdl_srcs)
                cocotb_env["TOPLEVEL_LANG"] = "vhdl"

        cocotb_env.update(extra_env)

        # Merge with any user-provided env
        merged_env = dict(env) if env else {}
        merged_env.update(cocotb_env)

        if use_makefile or makefile_path:
            # Use make-based flow
            make_args: list[str] = ["make"]
            if makefile_path:
                make_args.extend(["-f", str(makefile_path)])
            make_args.extend(extra_args)

            import subprocess
            import time

            work_dir = str(cwd) if cwd else None
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    make_args,
                    cwd=work_dir,
                    env=merged_env if merged_env else None,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                return ToolResult(
                    returncode=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    duration=time.monotonic() - start,
                    command=make_args,
                )
            except subprocess.TimeoutExpired:
                return ToolResult(
                    returncode=-1,
                    stderr=f"Make timed out after {timeout}s",
                    duration=time.monotonic() - start,
                    command=make_args,
                )
        else:
            # Use cocotb-config --runner approach or direct pytest
            args: list[str] = ["--runner"]
            args.extend(extra_args)

            return self.run(args, cwd=cwd, env=merged_env, timeout=timeout)

    @staticmethod
    def discover_tests(
        test_dir: str | PathLike[str],
        *,
        pattern: str = "test_*.py",
    ) -> list[str]:
        """Find Python test files in a directory.

        Parameters
        ----------
        test_dir:
            Directory to search for test files.
        pattern:
            Glob pattern for test file names.

        Returns
        -------
        list[str]
            Sorted list of discovered test module names (without ``.py``).
        """
        test_path = Path(test_dir)
        if not test_path.is_dir():
            return []

        modules: list[str] = sorted(
            p.stem for p in test_path.glob(pattern) if p.is_file()
        )
        return modules
