"""FPGA device programming -- iceprog, ujprog, openFPGALoader."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectedDevice:
    """An FPGA board discovered on the system."""

    name: str
    usb_id: str = ""       # vid:pid
    device_type: str = ""   # e.g. "ice40", "ecp5", "gowin"
    programmer: str = ""    # tool that can program it


@dataclass(frozen=True, slots=True)
class ProgramResult:
    """Outcome of a programming operation."""

    success: bool
    device_name: str = ""
    time_seconds: float = 0.0
    verified: bool = False
    message: str = ""


# ---------------------------------------------------------------------------
# Programmer tool helpers
# ---------------------------------------------------------------------------

_TOOL_DEVICE_MAP: dict[str, list[str]] = {
    "iceprog": ["ice40"],
    "ujprog": ["ecp5"],
    "openFPGALoader": [
        "ice40", "ecp5", "gowin", "xilinx", "altera", "lattice",
        "efinix", "anlogic", "colognechip",
    ],
}


def _which(binary: str) -> str | None:
    """Locate a binary on PATH."""
    return shutil.which(binary)


def _run_tool(
    cmd: list[str],
    *,
    timeout: float = 120.0,
) -> tuple[int, str, str]:
    """Run a programming tool, returning (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Process timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"Tool not found: {cmd[0]}"


# ---------------------------------------------------------------------------
# FpgaProgrammer
# ---------------------------------------------------------------------------


class FpgaProgrammer:
    """Unified FPGA programming interface supporting multiple backends.

    Supports:
    - ``iceprog`` for Lattice iCE40 devices (USB/SPI)
    - ``ujprog`` for Lattice ECP5 devices (JTAG)
    - ``openFPGALoader`` as a universal fallback

    Typical workflow::

        prog = FpgaProgrammer()
        devices = prog.detect_devices()
        result = prog.program("design.bin", verify=True)
    """

    def __init__(self) -> None:
        self._available_tools: dict[str, str] = {}
        self._refresh_tools()

    def _refresh_tools(self) -> None:
        """Detect which programming tools are available."""
        self._available_tools.clear()
        for tool in ("iceprog", "ujprog", "openFPGALoader"):
            path = _which(tool)
            if path:
                self._available_tools[tool] = path

    # ------------------------------------------------------------------
    # Device detection
    # ------------------------------------------------------------------

    def detect_devices(self) -> list[DetectedDevice]:
        """Detect connected FPGA boards.

        Tries openFPGALoader first (broadest support), then falls back
        to tool-specific detection.
        """
        devices: list[DetectedDevice] = []

        # openFPGALoader --detect is the most comprehensive
        if "openFPGALoader" in self._available_tools:
            rc, stdout, stderr = _run_tool(
                ["openFPGALoader", "--detect"], timeout=15.0,
            )
            combined = stdout + stderr
            # Parse lines like: "index 0: ... (IDCODE 0x12345678, ...)"
            for m in re.finditer(
                r"index\s+\d+:\s*(.+?)(?:\(|$)",
                combined,
            ):
                dev_name = m.group(1).strip()
                if dev_name:
                    # Try to identify device type from name
                    dev_type = ""
                    lower = dev_name.lower()
                    if "ice40" in lower or "ice" in lower:
                        dev_type = "ice40"
                    elif "ecp5" in lower:
                        dev_type = "ecp5"
                    elif "gowin" in lower:
                        dev_type = "gowin"

                    devices.append(DetectedDevice(
                        name=dev_name,
                        device_type=dev_type,
                        programmer="openFPGALoader",
                    ))

        # Also try USB device enumeration for known FPGA programmers
        try:
            rc, stdout, stderr = _run_tool(["lsusb"], timeout=5.0)
            if rc == 0:
                # Known FTDI/FPGA USB IDs
                known_usb: dict[str, tuple[str, str]] = {
                    "0403:6010": ("Lattice iCE40 (FTDI)", "ice40"),
                    "0403:6014": ("Lattice ECP5 (FTDI)", "ecp5"),
                    "1d50:602b": ("TinyFPGA BX", "ice40"),
                    "1209:5bf0": ("Fomu", "ice40"),
                }
                for line in stdout.splitlines():
                    for usb_id, (name, dev_type) in known_usb.items():
                        if usb_id in line:
                            # Avoid duplicates
                            if not any(d.usb_id == usb_id for d in devices):
                                devices.append(DetectedDevice(
                                    name=name,
                                    usb_id=usb_id,
                                    device_type=dev_type,
                                ))
        except Exception:
            pass

        return devices

    # ------------------------------------------------------------------
    # Programming
    # ------------------------------------------------------------------

    def program(
        self,
        bitstream_path: str | PathLike[str],
        *,
        device: str | None = None,
        verify: bool = True,
    ) -> ProgramResult:
        """Program an FPGA with the given bitstream.

        Parameters
        ----------
        bitstream_path:
            Path to the bitstream file (.bin, .bit, .svf).
        device:
            Device type hint (e.g. "ice40", "ecp5"). If None, auto-detects.
        verify:
            Whether to verify after programming.
        """
        bs_path = Path(bitstream_path)
        if not bs_path.exists():
            return ProgramResult(
                success=False,
                message=f"Bitstream file not found: {bs_path}",
            )

        start = time.monotonic()

        # Determine which tool to use
        tool, cmd = self._build_program_cmd(bs_path, device=device, verify=verify)
        if tool is None:
            return ProgramResult(
                success=False,
                message="No suitable programming tool found. Install iceprog, "
                        "ujprog, or openFPGALoader.",
            )

        rc, stdout, stderr = _run_tool(cmd, timeout=120.0)
        elapsed = time.monotonic() - start
        combined = stdout + stderr

        success = rc == 0
        verified = False
        if success and verify:
            # Check for verification confirmation in output
            verified = (
                "verify ok" in combined.lower()
                or "verification successful" in combined.lower()
                or "verify pass" in combined.lower()
                or (verify and "error" not in combined.lower())
            )

        dev_name = device or self._guess_device_from_bitstream(bs_path)

        return ProgramResult(
            success=success,
            device_name=dev_name,
            time_seconds=elapsed,
            verified=verified,
            message=combined.strip() if not success else f"Programmed via {tool}",
        )

    # ------------------------------------------------------------------
    # Erase
    # ------------------------------------------------------------------

    def erase(self, *, device: str | None = None) -> ProgramResult:
        """Erase the flash memory on the connected FPGA.

        Parameters
        ----------
        device:
            Device type hint (e.g. "ice40", "ecp5").
        """
        start = time.monotonic()

        if "openFPGALoader" in self._available_tools:
            cmd = ["openFPGALoader", "--unprotect-flash", "--erase"]
            if device:
                cmd.extend(["--fpga-part", device])
        elif "iceprog" in self._available_tools and (device is None or device == "ice40"):
            cmd = ["iceprog", "-e"]
        else:
            return ProgramResult(
                success=False,
                message="No suitable tool for erase operation.",
            )

        rc, stdout, stderr = _run_tool(cmd, timeout=60.0)
        elapsed = time.monotonic() - start

        return ProgramResult(
            success=rc == 0,
            device_name=device or "unknown",
            time_seconds=elapsed,
            message=(stdout + stderr).strip(),
        )

    # ------------------------------------------------------------------
    # Read flash
    # ------------------------------------------------------------------

    def read_flash(
        self,
        output_path: str | PathLike[str],
        *,
        device: str | None = None,
        size: int = 0,
    ) -> ProgramResult:
        """Read back the bitstream from flash.

        Parameters
        ----------
        output_path:
            File path to write the read-back bitstream.
        device:
            Device type hint.
        size:
            Number of bytes to read (0 = auto).
        """
        out = Path(output_path)
        start = time.monotonic()

        if "openFPGALoader" in self._available_tools:
            cmd = ["openFPGALoader", "--read-flash", str(out)]
            if device:
                cmd.extend(["--fpga-part", device])
            if size > 0:
                cmd.extend(["--offset", "0", "--len", str(size)])
        elif "iceprog" in self._available_tools and (device is None or device == "ice40"):
            cmd = ["iceprog", "-r", str(out)]
            if size > 0:
                cmd.extend(["-n", str(size)])
        else:
            return ProgramResult(
                success=False,
                message="No suitable tool for flash read.",
            )

        rc, stdout, stderr = _run_tool(cmd, timeout=120.0)
        elapsed = time.monotonic() - start

        success = rc == 0 and out.exists()

        return ProgramResult(
            success=success,
            device_name=device or "unknown",
            time_seconds=elapsed,
            message=f"Read {out.stat().st_size} bytes to {out}" if success
                    else (stdout + stderr).strip(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_program_cmd(
        self,
        bitstream: Path,
        *,
        device: str | None,
        verify: bool,
    ) -> tuple[str | None, list[str]]:
        """Select the best tool and build the programming command."""
        dev = device or self._guess_device_from_bitstream(bitstream)

        # Prefer device-specific tools, fall back to openFPGALoader
        if dev == "ice40" and "iceprog" in self._available_tools:
            cmd = ["iceprog"]
            if verify:
                cmd.append("-v")
            cmd.append(str(bitstream))
            return "iceprog", cmd

        if dev == "ecp5" and "ujprog" in self._available_tools:
            cmd = ["ujprog"]
            if verify:
                cmd.append("-j")  # JTAG verify
            cmd.append(str(bitstream))
            return "ujprog", cmd

        if "openFPGALoader" in self._available_tools:
            cmd = ["openFPGALoader"]
            if verify:
                cmd.append("--verify")
            if device:
                cmd.extend(["--fpga-part", device])
            cmd.extend(["--write-flash", str(bitstream)])
            return "openFPGALoader", cmd

        return None, []

    @staticmethod
    def _guess_device_from_bitstream(path: Path) -> str:
        """Try to infer the device type from the bitstream file extension."""
        name = path.name.lower()
        if "ice40" in name or path.suffix == ".bin":
            return "ice40"
        if "ecp5" in name or path.suffix == ".svf":
            return "ecp5"
        if path.suffix == ".bit":
            return "ecp5"
        return "unknown"
