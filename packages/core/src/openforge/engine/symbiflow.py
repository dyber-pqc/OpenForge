"""SymbiFlow / F4PGA engine for Xilinx 7-series FPGA synthesis and P&R.

SymbiFlow (now known as F4PGA) is an open-source FPGA toolchain for Xilinx
7-series devices (Artix-7, Kintex-7, Zynq-7000). It chains Yosys (synthesis),
VPR / nextpnr-xilinx (place and route), and fasm2bels / xc7frames2bit
(bitstream generation).

This wrapper provides a high-level Python interface over the various
``symbiflow_*`` shell scripts shipped by the F4PGA distribution.

Example
-------

    >>> eng = SymbiFlowEngine()
    >>> outputs = eng.full_flow(
    ...     sources=["rtl/top.v"],
    ...     top_module="top",
    ...     part="xc7a35tcsg324-1",
    ...     xdc_file="constraints/arty.xdc",
    ... )
    >>> print(outputs["bitstream"])
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


@dataclass(slots=True)
class SymbiFlowArtifacts:
    """Collection of files produced by a full SymbiFlow run."""

    work_dir: Path
    eblif: Path | None = None
    net: Path | None = None
    place: Path | None = None
    route: Path | None = None
    fasm: Path | None = None
    bitstream: Path | None = None
    log_files: list[Path] = field(default_factory=list)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "work_dir": str(self.work_dir),
            "eblif": str(self.eblif) if self.eblif else None,
            "net": str(self.net) if self.net else None,
            "place": str(self.place) if self.place else None,
            "route": str(self.route) if self.route else None,
            "fasm": str(self.fasm) if self.fasm else None,
            "bitstream": str(self.bitstream) if self.bitstream else None,
            "logs": [str(p) for p in self.log_files],
        }


class SymbiFlowEngine(ToolEngine):
    """Wraps SymbiFlow / F4PGA for Xilinx 7-series synthesis and P&R."""

    BINARY = "symbiflow_synth"
    DOCKER_IMAGE = "f4pga/f4pga:latest"

    #: Parts natively supported by the open-source database.
    SUPPORTED_PARTS: dict[str, dict[str, str]] = {
        "xc7a35tcsg324-1": {
            "family": "artix7",
            "die": "xc7a35t",
            "package": "csg324",
            "speed": "1",
        },
        "xc7a35tcpg236-1": {
            "family": "artix7",
            "die": "xc7a35t",
            "package": "cpg236",
            "speed": "1",
        },
        "xc7a50tcsg324-1": {
            "family": "artix7",
            "die": "xc7a50t",
            "package": "csg324",
            "speed": "1",
        },
        "xc7a100tcsg324-1": {
            "family": "artix7",
            "die": "xc7a100t",
            "package": "csg324",
            "speed": "1",
        },
        "xc7a200tsbg484-1": {
            "family": "artix7",
            "die": "xc7a200t",
            "package": "sbg484",
            "speed": "1",
        },
        "xc7z010clg400-1": {
            "family": "zynq7",
            "die": "xc7z010",
            "package": "clg400",
            "speed": "1",
        },
        "xc7z020clg484-1": {
            "family": "zynq7",
            "die": "xc7z020",
            "package": "clg484",
            "speed": "1",
        },
    }

    #: Mapping of board aliases to canonical part numbers.
    KNOWN_BOARDS: dict[str, str] = {
        "arty_a7_35t": "xc7a35tcsg324-1",
        "arty_a7_100t": "xc7a100tcsg324-1",
        "basys3": "xc7a35tcpg236-1",
        "cmod_a7_35t": "xc7a35tcpg236-1",
        "nexys_a7_50t": "xc7a50tcsg324-1",
        "nexys_a7_100t": "xc7a100tcsg324-1",
        "zybo_z7_10": "xc7z010clg400-1",
        "zybo_z7_20": "xc7z020clg400-1",
        "genesys2": "xc7a200tsbg484-1",
    }

    #: Default target clock period in ns when the user does not specify one.
    DEFAULT_PERIOD_NS: float = 10.0

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
        docker_image_override: str | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            binary_override=binary_override,
            docker_image_override=docker_image_override,
        )

    # ------------------------------------------------------------------
    # ToolEngine interface
    # ------------------------------------------------------------------

    def check_installed(self) -> bool:
        if self.backend == ExecutionBackend.DOCKER:
            return True
        # SymbiFlow installs a family of scripts; look for any of them.
        for candidate in (
            "symbiflow_synth",
            "symbiflow_pack",
            "symbiflow_place",
            "symbiflow_route",
            "symbiflow_write_fasm",
            "symbiflow_write_bitstream",
        ):
            if shutil.which(candidate):
                return True
        return False

    def version(self) -> str:
        result = self.run(["--version"])
        if result.ok:
            for line in result.stdout.splitlines() + result.stderr.splitlines():
                if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", line):
                    return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # Part / board helpers
    # ------------------------------------------------------------------

    @classmethod
    def resolve_board(cls, board: str) -> str | None:
        """Map a board alias to a canonical part, or return *None*."""
        return cls.KNOWN_BOARDS.get(board.lower())

    @classmethod
    def part_info(cls, part: str) -> dict[str, str]:
        if part not in cls.SUPPORTED_PARTS:
            raise ValueError(f"Unsupported part: {part}")
        return dict(cls.SUPPORTED_PARTS[part])

    @classmethod
    def list_parts(cls) -> list[str]:
        return sorted(cls.SUPPORTED_PARTS.keys())

    @classmethod
    def list_boards(cls) -> list[str]:
        return sorted(cls.KNOWN_BOARDS.keys())

    # ------------------------------------------------------------------
    # Individual flow steps
    # ------------------------------------------------------------------

    def synthesize(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str,
        part: str,
        xdc_file: str | PathLike[str] | None = None,
        output_eblif: str | PathLike[str] | None = None,
        extra_options: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run Yosys-based synthesis via ``symbiflow_synth``.

        Produces an ``.eblif`` netlist that is fed into VPR for P&R.
        """
        if part not in self.SUPPORTED_PARTS:
            raise ValueError(f"Unsupported part: {part}")

        info = self.SUPPORTED_PARTS[part]
        args: list[str] = [
            "-t",
            top_module,
            "-v",
            *[str(s) for s in sources],
            "-d",
            info["family"],
            "-p",
            part,
        ]
        if xdc_file is not None:
            args += ["-x", str(xdc_file)]
        if output_eblif is not None:
            args += ["-o", str(output_eblif)]
        args.extend(extra_options)

        prev_binary = self.binary
        try:
            self.binary = "symbiflow_synth"
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev_binary

    def pack(
        self,
        eblif: str | PathLike[str],
        *,
        part: str,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run VPR ``pack`` stage via ``symbiflow_pack``."""
        info = self.part_info(part)
        args = ["-e", str(eblif), "-d", info["family"], "-p", part]
        prev = self.binary
        try:
            self.binary = "symbiflow_pack"
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev

    def place(
        self,
        eblif: str | PathLike[str],
        *,
        part: str,
        sdc_file: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run VPR ``place`` stage via ``symbiflow_place``."""
        info = self.part_info(part)
        args = ["-e", str(eblif), "-d", info["family"], "-p", part]
        if sdc_file is not None:
            args += ["-s", str(sdc_file)]
        prev = self.binary
        try:
            self.binary = "symbiflow_place"
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev

    def route(
        self,
        eblif: str | PathLike[str],
        *,
        part: str,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run VPR ``route`` stage via ``symbiflow_route``."""
        info = self.part_info(part)
        args = ["-e", str(eblif), "-d", info["family"], "-p", part]
        prev = self.binary
        try:
            self.binary = "symbiflow_route"
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev

    def place_and_route(
        self,
        eblif: str | PathLike[str],
        *,
        part: str,
        xdc_file: str | PathLike[str] | None = None,
        sdc_file: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute the full pack/place/route sequence.

        Returns the *last* non-ok :class:`ToolResult`, or the routing
        result on success.
        """
        for step in (self.pack, self.place, self.route):
            if step is self.place:
                result = step(
                    eblif,
                    part=part,
                    sdc_file=sdc_file,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                )
            else:
                result = step(
                    eblif,
                    part=part,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                )
            if not result.ok:
                return result
        return result  # last route result

    def write_fasm(
        self,
        eblif: str | PathLike[str],
        *,
        part: str,
        output_fasm: str | PathLike[str],
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Emit an FPGA assembly (FASM) file for the routed design."""
        info = self.part_info(part)
        args = [
            "-e",
            str(eblif),
            "-d",
            info["family"],
            "-p",
            part,
            "-o",
            str(output_fasm),
        ]
        prev = self.binary
        try:
            self.binary = "symbiflow_write_fasm"
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev

    def generate_bitstream(
        self,
        fasm: str | PathLike[str],
        *,
        part: str,
        output_bit: str | PathLike[str],
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Convert FASM to a binary ``.bit`` bitstream."""
        info = self.part_info(part)
        args = [
            "-f",
            str(fasm),
            "-d",
            info["family"],
            "-p",
            part,
            "-b",
            str(output_bit),
        ]
        prev = self.binary
        try:
            self.binary = "symbiflow_write_bitstream"
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev

    # ------------------------------------------------------------------
    # High level flow
    # ------------------------------------------------------------------

    def full_flow(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        top_module: str,
        part: str,
        xdc_file: str | PathLike[str] | None = None,
        work_dir: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, str | None | list[str]]:
        """Run synth -> pack -> place -> route -> fasm -> bit.

        Returns a dictionary describing every artifact produced. On
        failure, the ``error`` key contains stderr of the failing step.
        """
        work = Path(work_dir) if work_dir else Path.cwd() / "build_symbiflow"
        work.mkdir(parents=True, exist_ok=True)

        eblif = work / f"{top_module}.eblif"
        fasm = work / f"{top_module}.fasm"
        bit = work / f"{top_module}.bit"

        artifacts = SymbiFlowArtifacts(work_dir=work)

        syn = self.synthesize(
            sources,
            top_module=top_module,
            part=part,
            xdc_file=xdc_file,
            output_eblif=eblif,
            cwd=work,
            timeout=timeout,
        )
        if not syn.ok:
            return {"ok": False, "step": "synth", "error": syn.stderr, **artifacts.as_dict()}
        artifacts.eblif = eblif

        pnr = self.place_and_route(
            eblif,
            part=part,
            xdc_file=xdc_file,
            cwd=work,
            timeout=timeout,
        )
        if not pnr.ok:
            return {"ok": False, "step": "p&r", "error": pnr.stderr, **artifacts.as_dict()}
        artifacts.net = work / f"{top_module}.net"
        artifacts.place = work / f"{top_module}.place"
        artifacts.route = work / f"{top_module}.route"

        wf = self.write_fasm(eblif, part=part, output_fasm=fasm, cwd=work, timeout=timeout)
        if not wf.ok:
            return {"ok": False, "step": "fasm", "error": wf.stderr, **artifacts.as_dict()}
        artifacts.fasm = fasm

        wb = self.generate_bitstream(
            fasm, part=part, output_bit=bit, cwd=work, timeout=timeout
        )
        if not wb.ok:
            return {"ok": False, "step": "bitstream", "error": wb.stderr, **artifacts.as_dict()}
        artifacts.bitstream = bit

        return {"ok": True, "step": "done", **artifacts.as_dict()}

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def estimate_resource_usage(
        self, eblif: str | PathLike[str]
    ) -> dict[str, int]:
        """Very rough LUT/FF/BRAM estimate from an eblif file."""
        path = Path(eblif)
        counts = {"luts": 0, "ffs": 0, "brams": 0, "dsps": 0}
        if not path.exists():
            return counts
        text = path.read_text(errors="replace")
        counts["luts"] = len(re.findall(r"\.names\b", text))
        counts["ffs"] = len(re.findall(r"\.latch\b", text))
        counts["brams"] = len(re.findall(r"BRAM\b", text, re.IGNORECASE))
        counts["dsps"] = len(re.findall(r"DSP\w*\b", text))
        return counts
