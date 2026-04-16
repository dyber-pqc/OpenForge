"""F4PGA (formerly Symbiflow) fallback engine for Xilinx 7-series.

F4PGA provides a Makefile-driven flow that runs Yosys synthesis, VPR
place-and-route, and the same prjxray backend as openXC7. When
``nextpnr-xilinx`` is unavailable, OpenForge falls back to F4PGA.

References:
- https://f4pga.readthedocs.io/
- https://github.com/chipsalliance/f4pga
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Sequence


class F4pgaEngine(ToolEngine):
    """Symbiflow/F4PGA wrapper for Xilinx 7-series fallback."""

    BINARY = "f4pga"
    DOCKER_IMAGE = "ghcr.io/chipsalliance/f4pga:latest"

    SUPPORTED_DEVICES = {
        "xc7a35tcsg324-1": "artix7",
        "xc7a35tcpg236-1": "artix7",
        "xc7a100tcsg324-1": "artix7",
        "xc7a200tsbg484-1": "artix7",
        "xc7s50csga324-1": "spartan7",
        "xc7z010clg400-1": "zynq7",
        "xc7z020clg400-1": "zynq7",
        "xc7z020clg484-1": "zynq7",
    }

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @classmethod
    def detect(cls) -> dict:
        f4pga = shutil.which("f4pga")
        symbiflow = shutil.which("symbiflow_synth")
        vpr = shutil.which("vpr")
        return {
            "f4pga": f4pga,
            "symbiflow_synth": symbiflow,
            "vpr": vpr,
            "ok": bool(f4pga or symbiflow) and bool(vpr),
        }

    def check_installed(self) -> bool:
        return bool(self.detect().get("ok"))

    def version(self) -> str:
        res = self.run(["--version"])
        if res.ok:
            return res.stdout.strip() or res.stderr.strip()
        return "f4pga (unknown)"

    # ------------------------------------------------------------------
    # Flow
    # ------------------------------------------------------------------

    def run_flow(
        self,
        rtl_files: Sequence[str | Path],
        top: str,
        device: str,
        xdc: str | Path,
        output_dir: str | Path,
        *,
        cwd: str | Path | None = None,
    ) -> ToolResult:
        """Run the full synth -> pack -> place -> route -> bit flow."""
        if device not in self.SUPPORTED_DEVICES:
            return ToolResult(
                returncode=2,
                stderr=f"Unsupported device: {device}",
            )
        family = self.SUPPORTED_DEVICES[device]
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        rtl = " ".join(str(Path(f).as_posix()) for f in rtl_files)
        eos = [
            "f4pga",
            "build",
            "-t",
            top,
            "-f",
            family,
            "-p",
            device,
            "--xdc",
            str(xdc),
            "--sources",
            rtl,
            "--out",
            str(out),
        ]
        saved = self.binary
        self.binary = shutil.which("f4pga") or "f4pga"
        try:
            return self.run(eos[1:], cwd=cwd or out)
        finally:
            self.binary = saved

    # ------------------------------------------------------------------
    # Log parsing
    # ------------------------------------------------------------------

    _UTIL_RE = re.compile(
        r"^\s*(?P<kind>[A-Za-z0-9_]+)\s*:\s*(?P<used>\d+)\s*/\s*(?P<avail>\d+)",
        re.MULTILINE,
    )
    _CRIT_RE = re.compile(
        r"(?:critical path delay|Final critical path).*?([\d.]+)\s*ns",
        re.IGNORECASE,
    )
    _ERR_RE = re.compile(r"(?:ERROR|error):\s*(.+)")

    def parse_log(self, text: str) -> dict:
        util: dict[str, dict[str, int]] = {}
        for m in self._UTIL_RE.finditer(text):
            util[m.group("kind")] = {
                "used": int(m.group("used")),
                "available": int(m.group("avail")),
            }
        cp_ns: float | None = None
        crit = self._CRIT_RE.search(text)
        if crit:
            try:
                cp_ns = float(crit.group(1))
            except ValueError:
                cp_ns = None
        errors = [m.group(1).strip() for m in self._ERR_RE.finditer(text)]
        return {
            "utilization": util,
            "critical_path_ns": cp_ns,
            "fmax_mhz": (1_000.0 / cp_ns) if cp_ns else None,
            "errors": errors,
            "ok": not errors,
        }


__all__ = ["F4pgaEngine"]
