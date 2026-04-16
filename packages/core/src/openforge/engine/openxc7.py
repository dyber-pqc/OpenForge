"""openXC7 / nextpnr-xilinx engine for Spartan-7 / Artix-7 / Zynq-7000.

Wraps the open-source Xilinx 7-series flow:

    yosys  -->  nextpnr-xilinx  -->  prjxray fasm2frames  -->  xc7frames2bit

References:
- https://github.com/openXC7/nextpnr-xilinx
- https://github.com/f4pga/prjxray
- https://openxc7.org/
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class OpenXC7Paths:
    """Resolved tool / database paths used by the openXC7 flow."""

    yosys: str | None
    nextpnr: str | None
    fasm2frames: str | None
    frames2bit: str | None
    prjxray_db: str | None
    chipdb_dir: str | None

    @property
    def ok(self) -> bool:
        return all(
            p is not None for p in (self.yosys, self.nextpnr, self.fasm2frames, self.frames2bit)
        )


class OpenXC7Engine(ToolEngine):
    """Open-source Xilinx 7-series flow (yosys + nextpnr-xilinx + prjxray)."""

    BINARY = "nextpnr-xilinx"
    DOCKER_IMAGE = "openxc7/toolchain:latest"

    #: Supported devices -> human-readable description.
    SUPPORTED_DEVICES: dict[str, str] = {
        "xc7a35tcsg324-1": "Artix-7 35T (Arty A7-35T, Basys 3)",
        "xc7a35tcpg236-1": "Artix-7 35T CPG236 (CMOD A7-35T, Basys 3 rev alt)",
        "xc7a35ticsg324-1L": "Artix-7 35T Industrial Low-Power",
        "xc7a100tcsg324-1": "Artix-7 100T (Arty A7-100T, Nexys A7-100T)",
        "xc7a200tsbg484-1": "Artix-7 200T SBG484",
        "xc7s50csga324-1": "Spartan-7 50 (Arty S7-50)",
        "xc7z010clg400-1": "Zynq-7010 (ZYBO)",
        "xc7z020clg400-1": "Zynq-7020 (PYNQ-Z2, ZYBO Z7-20)",
        "xc7z020clg484-1": "Zynq-7020 (ZedBoard)",
    }

    #: Map device -> nextpnr-xilinx chipdb family prefix.
    _DEVICE_FAMILY = {
        "xc7a": "artix7",
        "xc7s": "spartan7",
        "xc7z": "zynq7",
    }

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
        docker_image_override: str | None = None,
        prjxray_db: str | None = None,
        chipdb_dir: str | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            binary_override=binary_override,
            docker_image_override=docker_image_override,
        )
        self.prjxray_db = prjxray_db
        self.chipdb_dir = chipdb_dir

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @classmethod
    def detect(cls) -> dict:
        """Probe PATH + conventional locations for every tool we need."""
        yosys = shutil.which("yosys")
        nextpnr = shutil.which("nextpnr-xilinx")
        fasm2frames = shutil.which("fasm2frames.py") or shutil.which("fasm2frames")
        frames2bit = shutil.which("xc7frames2bit") or shutil.which("xc7frames2bit.py")

        prjxray_db = None
        for env in ("XRAY_DATABASE_DIR", "PRJXRAY_DB_DIR"):
            import os

            val = os.environ.get(env)
            if val and Path(val).is_dir():
                prjxray_db = val
                break
        if prjxray_db is None:
            for candidate in (
                Path.home() / ".local/share/prjxray-db",
                Path("/usr/share/prjxray-db"),
                Path("/opt/prjxray-db"),
            ):
                if candidate.is_dir():
                    prjxray_db = str(candidate)
                    break

        chipdb_dir = None
        for candidate in (
            Path.home() / ".local/share/nextpnr-xilinx",
            Path("/usr/share/nextpnr-xilinx"),
            Path("/opt/nextpnr-xilinx/chipdb"),
        ):
            if candidate.is_dir():
                chipdb_dir = str(candidate)
                break

        paths = OpenXC7Paths(
            yosys=yosys,
            nextpnr=nextpnr,
            fasm2frames=fasm2frames,
            frames2bit=frames2bit,
            prjxray_db=prjxray_db,
            chipdb_dir=chipdb_dir,
        )
        return {
            "yosys": paths.yosys,
            "nextpnr-xilinx": paths.nextpnr,
            "fasm2frames": paths.fasm2frames,
            "xc7frames2bit": paths.frames2bit,
            "prjxray_db": paths.prjxray_db,
            "chipdb_dir": paths.chipdb_dir,
            "ok": paths.ok,
        }

    def check_installed(self) -> bool:
        info = self.detect()
        return bool(info.get("ok"))

    def version(self) -> str:
        res = self.run(["--version"])
        if res.ok:
            return res.stdout.strip() or res.stderr.strip()
        return "nextpnr-xilinx (unknown version)"

    # ------------------------------------------------------------------
    # Flow steps
    # ------------------------------------------------------------------

    def synth(
        self,
        rtl_files: Sequence[str | Path],
        top: str,
        output_json: str | Path,
        *,
        cwd: str | Path | None = None,
    ) -> ToolResult:
        """Run yosys synth_xilinx emitting a JSON netlist."""
        read_cmds: list[str] = []
        for f in rtl_files:
            fp = str(Path(f).as_posix())
            if fp.endswith((".sv", ".v")):
                read_cmds.append(f"read_verilog -sv {fp}")
            elif fp.endswith(".vhd") or fp.endswith(".vhdl"):
                read_cmds.append(f"read_vhdl {fp}")
            else:
                read_cmds.append(f"read_verilog {fp}")
        script = "; ".join(
            [
                *read_cmds,
                f"synth_xilinx -flatten -abc9 -arch xc7 -top {top}",
                f"write_json {Path(output_json).as_posix()}",
            ]
        )

        yosys = shutil.which("yosys") or "yosys"
        saved_binary = self.binary
        self.binary = yosys
        try:
            return self.run(["-q", "-p", script], cwd=cwd)
        finally:
            self.binary = saved_binary

    def pack(
        self,
        json_netlist: str | Path,
        device: str,
        output_fasm: str | Path,
        xdc: str | Path | None = None,
        *,
        cwd: str | Path | None = None,
    ) -> ToolResult:
        """Place and route with nextpnr-xilinx, emit FASM."""
        if device not in self.SUPPORTED_DEVICES:
            return ToolResult(
                returncode=2,
                stderr=f"Unsupported device: {device}",
            )

        family = self._family_for(device)
        chipdb = None
        if self.chipdb_dir:
            cand = Path(self.chipdb_dir) / f"{device}.bin"
            if cand.exists():
                chipdb = str(cand)
            else:
                cand2 = Path(self.chipdb_dir) / f"{family}/{device}.bin"
                if cand2.exists():
                    chipdb = str(cand2)

        args: list[str] = [
            "--chipdb",
            chipdb or f"{device}.bin",
            "--xdc",
            str(xdc) if xdc else "",
            "--json",
            str(json_netlist),
            "--fasm",
            str(output_fasm),
        ]
        # Drop empty --xdc if none given.
        if not xdc:
            args = [a for a in args if a not in ("--xdc", "")]
        return self.run(args, cwd=cwd)

    def fasm_to_frames(
        self,
        fasm: str | Path,
        device: str,
        output_frames: str | Path,
        *,
        cwd: str | Path | None = None,
    ) -> ToolResult:
        """Convert FASM to prjxray frames via fasm2frames.py."""
        fasm2frames = shutil.which("fasm2frames.py") or shutil.which("fasm2frames")
        if not fasm2frames:
            return ToolResult(returncode=2, stderr="fasm2frames not found")
        part = device.split("-")[0]  # xc7a35tcsg324-1 -> xc7a35tcsg324
        db = self.prjxray_db or ""
        args = [
            "--db-root",
            f"{db}/{self._family_for(device)}",
            "--part",
            part,
            str(fasm),
            str(output_frames),
        ]
        saved = self.binary
        self.binary = fasm2frames
        try:
            return self.run(args, cwd=cwd)
        finally:
            self.binary = saved

    def frames_to_bit(
        self,
        frames: str | Path,
        device: str,
        output_bit: str | Path,
        *,
        cwd: str | Path | None = None,
    ) -> ToolResult:
        """Final bitstream assembly: frames -> .bit."""
        tool = shutil.which("xc7frames2bit") or shutil.which("xc7frames2bit.py")
        if not tool:
            return ToolResult(returncode=2, stderr="xc7frames2bit not found")
        part = device.split("-")[0]
        db = self.prjxray_db or ""
        args = [
            "--part_file",
            f"{db}/{self._family_for(device)}/{part}/part.yaml",
            "--part_name",
            part,
            "--frm_file",
            str(frames),
            "--output_file",
            str(output_bit),
        ]
        saved = self.binary
        self.binary = tool
        try:
            return self.run(args, cwd=cwd)
        finally:
            self.binary = saved

    # ------------------------------------------------------------------
    # Log parsing
    # ------------------------------------------------------------------

    _UTIL_RE = re.compile(
        r"^\s*(?P<cell>[A-Z0-9_]+):\s+(?P<used>\d+)\s*/\s*(?P<avail>\d+)",
        re.MULTILINE,
    )
    _FMAX_RE = re.compile(
        r"Max frequency for clock\s+'?(?P<clk>[^']+)'?\s*:\s*(?P<mhz>[\d.]+)\s*MHz",
        re.IGNORECASE,
    )
    _ERR_RE = re.compile(r"ERROR:\s*(?P<msg>.+)")
    _WARN_RE = re.compile(r"WARNING:\s*(?P<msg>.+)")

    def parse_pnr_log(self, text: str) -> dict:
        """Extract utilization, fmax, and diagnostics from a nextpnr log."""
        utilization: dict[str, dict[str, int]] = {}
        for m in self._UTIL_RE.finditer(text):
            utilization[m.group("cell")] = {
                "used": int(m.group("used")),
                "available": int(m.group("avail")),
            }

        fmax: dict[str, float] = {}
        for m in self._FMAX_RE.finditer(text):
            fmax[m.group("clk")] = float(m.group("mhz"))

        errors = [m.group("msg").strip() for m in self._ERR_RE.finditer(text)]
        warnings = [m.group("msg").strip() for m in self._WARN_RE.finditer(text)]
        return {
            "utilization": utilization,
            "fmax_mhz": fmax,
            "errors": errors,
            "warnings": warnings,
            "ok": not errors,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _family_for(cls, device: str) -> str:
        for prefix, family in cls._DEVICE_FAMILY.items():
            if device.startswith(prefix):
                return family
        return "artix7"


__all__ = ["OpenXC7Engine", "OpenXC7Paths"]
