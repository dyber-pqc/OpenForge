"""JTAG / SVF playback for in-system FPGA programming.

This module provides a thin abstraction over the available JTAG
backends (urjtag, openocd, openFPGALoader) so that higher layers can
play back SVF (Serial Vector Format) files without caring which tool
is actually installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable


class JtagBackend(StrEnum):
    """Which command-line tool is used to drive the JTAG interface."""

    OPENFPGALOADER = "openFPGALoader"
    OPENOCD = "openocd"
    URJTAG = "jtag"
    AUTO = "auto"


@dataclass(slots=True)
class JtagDevice:
    """A single device discovered on the scan chain."""

    index: int
    idcode: str
    manufacturer: str = ""
    part: str = ""
    ir_length: int = 0

    @property
    def manufacturer_id(self) -> int:
        try:
            return int(self.idcode, 16) & 0xFFE
        except ValueError:
            return 0


@dataclass(slots=True)
class SvfProgress:
    """Progress event passed to user callbacks during ``SvfPlayer.play``."""

    percent: float
    message: str = ""
    elapsed: float = 0.0


# ---------------------------------------------------------------------------
# Cable detection
# ---------------------------------------------------------------------------


def detect_backend() -> JtagBackend:
    """Pick the first installed backend in a reasonable priority order."""
    if shutil.which("openFPGALoader"):
        return JtagBackend.OPENFPGALOADER
    if shutil.which("openocd"):
        return JtagBackend.OPENOCD
    if shutil.which("jtag"):
        return JtagBackend.URJTAG
    return JtagBackend.AUTO


# ---------------------------------------------------------------------------
# SVF Player
# ---------------------------------------------------------------------------


class SvfPlayer:
    """Plays back SVF (Serial Vector Format) files on a JTAG adapter."""

    def __init__(
        self,
        cable: str = "ft232",
        backend: JtagBackend = JtagBackend.AUTO,
    ) -> None:
        self.cable = cable
        self.backend = detect_backend() if backend == JtagBackend.AUTO else backend

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(
        self,
        svf_file: str | Path,
        frequency_hz: int = 1_000_000,
        on_progress: Callable[[SvfProgress], None] | None = None,
    ) -> bool:
        """Play an SVF file. Returns True on success."""
        path = Path(svf_file)
        if not path.exists():
            raise FileNotFoundError(path)

        if self.backend == JtagBackend.OPENFPGALOADER:
            return self._play_ofl(path, frequency_hz, on_progress)
        if self.backend == JtagBackend.OPENOCD:
            return self._play_openocd(path, frequency_hz, on_progress)
        if self.backend == JtagBackend.URJTAG:
            return self._play_urjtag(path, frequency_hz, on_progress)
        raise RuntimeError("No JTAG backend available")

    # ------------------------------------------------------------------

    def _play_ofl(
        self,
        svf: Path,
        freq: int,
        on_progress: Callable[[SvfProgress], None] | None,
    ) -> bool:
        cmd = [
            "openFPGALoader",
            "-c",
            self.cable,
            "--freq",
            str(freq),
            str(svf),
        ]
        return self._stream(cmd, on_progress)

    def _play_openocd(
        self,
        svf: Path,
        freq: int,
        on_progress: Callable[[SvfProgress], None] | None,
    ) -> bool:
        adapter_cfg = self._openocd_interface_cfg()
        cmd = [
            "openocd",
            "-f",
            adapter_cfg,
            "-c",
            f"adapter speed {freq // 1000}",
            "-c",
            "init",
            "-c",
            f"svf {svf}",
            "-c",
            "shutdown",
        ]
        return self._stream(cmd, on_progress)

    def _play_urjtag(
        self,
        svf: Path,
        freq: int,
        on_progress: Callable[[SvfProgress], None] | None,
    ) -> bool:
        script = (
            f"cable {self.cable}\n"
            f"frequency {freq}\n"
            "detect\n"
            f"svf {svf}\n"
            "quit\n"
        )
        cmd = ["jtag"]
        return self._stream(cmd, on_progress, stdin=script)

    # ------------------------------------------------------------------

    def _openocd_interface_cfg(self) -> str:
        mapping = {
            "ft232": "interface/ftdi/ft232r.cfg",
            "ft2232": "interface/ftdi/dp_busblaster.cfg",
            "jlink": "interface/jlink.cfg",
            "cmsisdap": "interface/cmsis-dap.cfg",
        }
        return mapping.get(self.cable, "interface/ftdi/ft232r.cfg")

    def _stream(
        self,
        cmd: list[str],
        on_progress: Callable[[SvfProgress], None] | None,
        stdin: str | None = None,
    ) -> bool:
        start = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if stdin and proc.stdin:
            proc.stdin.write(stdin)
            proc.stdin.close()

        assert proc.stdout is not None
        for line in proc.stdout:
            if on_progress is not None:
                pct = _parse_percent(line)
                on_progress(
                    SvfProgress(
                        percent=pct if pct is not None else -1.0,
                        message=line.rstrip(),
                        elapsed=time.monotonic() - start,
                    )
                )
        proc.wait()
        return proc.returncode == 0

    # ------------------------------------------------------------------
    # Chain interrogation
    # ------------------------------------------------------------------

    def boundary_scan(self) -> list[JtagDevice]:
        """Read the JTAG IDCODE chain.

        Uses ``openFPGALoader --detect`` when available.
        """
        if self.backend == JtagBackend.OPENFPGALOADER or shutil.which(
            "openFPGALoader"
        ):
            return self._scan_ofl()
        if shutil.which("jtag"):
            return self._scan_urjtag()
        return []

    def _scan_ofl(self) -> list[JtagDevice]:
        try:
            proc = subprocess.run(
                ["openFPGALoader", "-c", self.cable, "--detect"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        devices: list[JtagDevice] = []
        text = proc.stdout + proc.stderr
        for i, m in enumerate(
            re.finditer(r"idcode\s+(0x[0-9a-fA-F]+)", text, re.IGNORECASE)
        ):
            devices.append(JtagDevice(index=i, idcode=m.group(1)))
        return devices

    def _scan_urjtag(self) -> list[JtagDevice]:
        script = f"cable {self.cable}\ndetect\nquit\n"
        try:
            proc = subprocess.run(
                ["jtag"],
                input=script,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        devices: list[JtagDevice] = []
        for i, m in enumerate(
            re.finditer(
                r"IR length:\s*\d+.*IDCODE\s*:\s*(0x[0-9a-fA-F]+)",
                proc.stdout,
                re.IGNORECASE | re.DOTALL,
            )
        ):
            devices.append(JtagDevice(index=i, idcode=m.group(1)))
        return devices


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def bitstream_to_svf(
    bitstream: str | Path,
    output: str | Path,
    board: str,
) -> bool:
    """Convert a bitstream to SVF using openFPGALoader when available.

    Returns True on success.
    """
    bs = Path(bitstream)
    out = Path(output)
    if not bs.exists():
        raise FileNotFoundError(bs)

    if shutil.which("openFPGALoader"):
        cmd = [
            "openFPGALoader",
            "-b",
            board,
            "--file-type",
            "svf",
            "-o",
            str(out),
            str(bs),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and out.exists():
            return True

    if shutil.which("bit2svf"):
        proc = subprocess.run(
            ["bit2svf", str(bs), str(out)], capture_output=True, text=True
        )
        return proc.returncode == 0 and out.exists()

    return False


def _parse_percent(line: str) -> float | None:
    m = re.search(r"(\d{1,3})\s*%", line)
    if not m:
        return None
    try:
        pct = float(m.group(1))
        if 0.0 <= pct <= 100.0:
            return pct
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class JtagSession:
    """High level session combining scan + playback."""

    cable: str = "ft232"
    backend: JtagBackend = JtagBackend.AUTO
    devices: list[JtagDevice] = field(default_factory=list)

    def open(self) -> "JtagSession":
        player = SvfPlayer(cable=self.cable, backend=self.backend)
        self.devices = player.boundary_scan()
        return self

    def play_svf(
        self,
        svf: str | Path,
        frequency_hz: int = 1_000_000,
        on_progress: Callable[[SvfProgress], None] | None = None,
    ) -> bool:
        player = SvfPlayer(cable=self.cable, backend=self.backend)
        return player.play(svf, frequency_hz=frequency_hz, on_progress=on_progress)
