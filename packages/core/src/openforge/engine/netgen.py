"""Netgen LVS (Layout vs. Schematic) engine."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class NetgenEngine(ToolEngine):
    """Wraps Netgen for layout-vs-schematic comparison.

    Typical workflow::

        engine = NetgenEngine()
        result = engine.run_lvs(
            netlist1="extracted.spice",
            netlist2="synthesized.v",
            setup_file="setup.tcl",
        )
    """

    BINARY = "netgen-lvs"  # Ubuntu package: netgen-lvs
    _FALLBACK_BINARY = "netgen"
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
        # Try primary binary (netgen-lvs) then fallback (netgen)
        if self._which() is not None:
            return True
        import shutil
        return shutil.which(self._FALLBACK_BINARY) is not None

    def version(self) -> str:
        result = self.run(["--version"])
        text = result.stdout + result.stderr
        # "Netgen 1.5.272"
        if m := re.search(r"[Nn]etgen\s+([\d.]+)", text):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+[\d.]*)", text):
            return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_lvs(
        self,
        netlist1: str | PathLike[str],
        netlist2: str | PathLike[str],
        *,
        setup_file: str | PathLike[str] | None = None,
        output: str | PathLike[str] | None = None,
        netlist1_type: str = "spice",
        netlist2_type: str = "verilog",
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a layout-vs-schematic comparison.

        Parameters
        ----------
        netlist1:
            First netlist file (typically extracted layout).
        netlist2:
            Second netlist file (typically gate-level source).
        setup_file:
            Netgen setup / configuration TCL file.
        output:
            Output comparison report file.
        netlist1_type:
            Type of the first netlist (``"spice"``, ``"verilog"``).
        netlist2_type:
            Type of the second netlist (``"spice"``, ``"verilog"``).
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = ["-batch", "lvs"]

        # Netgen LVS syntax: netgen -batch lvs "net1 type1" "net2 type2" setup output
        args.append(f"{netlist1} {netlist1_type}")
        args.append(f"{netlist2} {netlist2_type}")

        if setup_file:
            args.append(str(setup_file))
        else:
            args.append("/dev/null")

        if output:
            args.append(str(output))

        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    @staticmethod
    def parse_result(result: ToolResult) -> bool:
        """Check whether the LVS comparison passed.

        Parameters
        ----------
        result:
            A :class:`ToolResult` from :meth:`run_lvs`.

        Returns
        -------
        bool
            *True* if the netlists match (LVS clean), *False* otherwise.
        """
        text = result.stdout + result.stderr
        # Netgen prints "Circuits match uniquely." on success
        return "Circuits match uniquely." in text
