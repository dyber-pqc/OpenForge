"""JTAG bridge built on the openocd TCL RPC server.

``JtagBridge`` spawns ``openocd`` in background with its TCL server
enabled (default port 6666), then issues ``irscan`` / ``drscan``
commands through the RPC socket. This is the same mechanism used by
Xilinx Vivado's hw_server / XSDB and by most open debug tools, and it
works with FTDI, J-Link, Digilent HS3, Tigard, and DirtyJTAG adapters
without any proprietary code.

The bridge deliberately doesn't require pyftdi at import time - it's
used only as a fallback when openocd isn't available.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Adapter / device models
# ---------------------------------------------------------------------------


class JtagAdapter(BaseModel):
    """A physical JTAG probe."""

    model_config = ConfigDict(frozen=True)

    name: str
    vid: int
    pid: int
    description: str = ""
    interface: str = "ftdi"  # 'ftdi', 'jlink', 'cmsis-dap', 'stlink', 'dirtyjtag'
    openocd_config: str | None = None

    @property
    def usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


class JtagDevice(BaseModel):
    """A single tap in the JTAG chain."""

    model_config = ConfigDict(frozen=True)

    idcode: int
    irlen: int
    name: str = ""
    manufacturer: str = ""
    position: int = 0

    @property
    def idcode_hex(self) -> str:
        return f"0x{self.idcode:08x}"


# ---------------------------------------------------------------------------
# Known adapters and IDCODEs
# ---------------------------------------------------------------------------


KNOWN_ADAPTERS: list[JtagAdapter] = [
    JtagAdapter(
        name="FT2232H",
        vid=0x0403,
        pid=0x6010,
        description="FTDI FT2232H dual-channel USB JTAG",
        interface="ftdi",
        openocd_config="interface/ftdi/ft2232h.cfg",
    ),
    JtagAdapter(
        name="FT232H",
        vid=0x0403,
        pid=0x6014,
        description="FTDI FT232H single-channel MPSSE",
        interface="ftdi",
        openocd_config="interface/ftdi/ft232h.cfg",
    ),
    JtagAdapter(
        name="Digilent JTAG-HS3",
        vid=0x0403,
        pid=0x6014,
        description="Digilent JTAG-HS3 (FTDI-based)",
        interface="ftdi",
        openocd_config="interface/ftdi/digilent-hs3.cfg",
    ),
    JtagAdapter(
        name="Digilent JTAG-HS2",
        vid=0x0403,
        pid=0x6014,
        description="Digilent JTAG-HS2 (FTDI-based)",
        interface="ftdi",
        openocd_config="interface/ftdi/digilent-hs2.cfg",
    ),
    JtagAdapter(
        name="Olimex ARM-USB-OCD-H",
        vid=0x15BA,
        pid=0x002B,
        description="Olimex ARM-USB-OCD-H high-speed JTAG",
        interface="ftdi",
        openocd_config="interface/ftdi/olimex-arm-usb-ocd-h.cfg",
    ),
    JtagAdapter(
        name="J-Link",
        vid=0x1366,
        pid=0x0101,
        description="SEGGER J-Link",
        interface="jlink",
        openocd_config="interface/jlink.cfg",
    ),
    JtagAdapter(
        name="Tigard",
        vid=0x0403,
        pid=0x6010,
        description="Tigard (FT2232HQ based) debug tool",
        interface="ftdi",
        openocd_config="interface/ftdi/tigard.cfg",
    ),
    JtagAdapter(
        name="DirtyJTAG",
        vid=0x1209,
        pid=0xC0CA,
        description="DirtyJTAG (STM32 bluepill based)",
        interface="cmsis-dap",
        openocd_config="interface/cmsis-dap.cfg",
    ),
    JtagAdapter(
        name="CMSIS-DAP",
        vid=0xC251,
        pid=0xF001,
        description="Generic CMSIS-DAP probe",
        interface="cmsis-dap",
        openocd_config="interface/cmsis-dap.cfg",
    ),
    JtagAdapter(
        name="ST-Link V2",
        vid=0x0483,
        pid=0x3748,
        description="STMicro ST-Link V2",
        interface="stlink",
        openocd_config="interface/stlink.cfg",
    ),
]


#: Known JTAG IDCODEs across vendors.
KNOWN_IDCODES: dict[int, str] = {
    # Xilinx 7-series
    0x0362D093: "xc7a35t",
    0x0362C093: "xc7a50t",
    0x13631093: "xc7a100t",
    0x13636093: "xc7a200t",
    0x0362F093: "xc7s50",
    0x03727093: "xc7z010",
    0x03722093: "xc7z020",
    0x03732093: "xc7z030",
    # Xilinx UltraScale
    0x04A63093: "xcku040",
    0x04B31093: "xczu3eg",
    # Lattice iCE40
    0x20000913: "iCE40HX1K",
    0x20001913: "iCE40HX4K",
    0x20021913: "iCE40HX8K",
    0x20010913: "iCE40LP1K",
    0x20011913: "iCE40LP4K",
    0x20012913: "iCE40LP8K",
    0x20040913: "iCE40UP5K",
    # Lattice ECP5
    0x21111043: "LFE5U-12F",
    0x41111043: "LFE5U-25F",
    0x41112043: "LFE5U-45F",
    0x41113043: "LFE5U-85F",
    0x01111043: "LFE5UM-25F",
    0x01112043: "LFE5UM-45F",
    0x01113043: "LFE5UM-85F",
    # Gowin
    0x0900281B: "GW1N-1",
    0x0900381B: "GW1N-4",
    0x0900481B: "GW1N-9",
    0x1100581B: "GW2A-18",
    0x0000181B: "GW2A-55",
    # RISC-V / ARM cores
    0x20000001: "OpenHW CVA6",
    0x4BA00477: "ARM DAP (Cortex-A9)",
    0x5BA00477: "ARM DAP (Cortex-A53)",
}


def lookup_idcode(idcode: int) -> str:
    """Return the best-effort human name for an IDCODE, or 'unknown'."""
    name = KNOWN_IDCODES.get(idcode)
    if name:
        return name
    # Manufacturer ID is bits[11:1], version in bits[31:28].
    masked = idcode & 0x0FFFFFFF
    return KNOWN_IDCODES.get(masked, f"unknown ({idcode:#010x})")


# ---------------------------------------------------------------------------
# openocd TCL RPC bridge
# ---------------------------------------------------------------------------


# openocd's TCL RPC delimits commands with \x1a.
_TCL_TERM = b"\x1a"


class JtagBridge:
    """Drive a JTAG chain via an openocd subprocess in TCL-server mode."""

    def __init__(
        self,
        adapter: JtagAdapter | None = None,
        openocd_path: str | None = None,
        tcl_port: int = 6666,
        host: str = "127.0.0.1",
        extra_init: Iterable[str] = (),
    ) -> None:
        self.adapter = adapter
        self.openocd_path = openocd_path or shutil.which("openocd") or "openocd"
        self.tcl_port = tcl_port
        self.host = host
        self.extra_init = list(extra_init)
        self._proc: subprocess.Popen[bytes] | None = None
        self._sock: socket.socket | None = None
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Adapter discovery
    # ------------------------------------------------------------------

    @staticmethod
    def list_adapters() -> list[JtagAdapter]:
        """Return all adapters we know how to talk to (static list)."""
        return list(KNOWN_ADAPTERS)

    @staticmethod
    def auto_detect() -> JtagAdapter | None:
        """Enumerate USB and match the first connected known adapter.

        Uses ``pyusb``/``libusb`` if present, otherwise falls back to
        parsing ``lsusb``/``ioreg``/``Get-PnpDevice`` output. Returns
        None when nothing is found.
        """
        try:
            import usb.core  # type: ignore

            for a in KNOWN_ADAPTERS:
                dev = usb.core.find(idVendor=a.vid, idProduct=a.pid)
                if dev is not None:
                    return a
            return None
        except Exception:
            pass

        # Fallback: parse platform-specific USB enumeration.
        usb_ids: set[str] = set()
        try:
            if os.name == "posix" and shutil.which("lsusb"):
                out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=4).stdout
                for m in re.finditer(r"ID\s+([0-9a-f]{4}):([0-9a-f]{4})", out):
                    usb_ids.add(f"{m.group(1)}:{m.group(2)}")
            elif os.name == "nt":
                out = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Get-PnpDevice -PresentOnly | "
                        "Where-Object Class -eq 'USB' | "
                        "Select-Object -ExpandProperty InstanceId",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=6,
                ).stdout
                for m in re.finditer(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", out):
                    usb_ids.add(f"{m.group(1).lower()}:{m.group(2).lower()}")
        except Exception:
            return None

        for a in KNOWN_ADAPTERS:
            if a.usb_id in usb_ids:
                return a
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """Spawn openocd in TCL server mode and connect."""
        if self._proc is not None:
            return True
        if shutil.which(self.openocd_path) is None and not Path(self.openocd_path).exists():
            return False

        cfg_lines: list[str] = []
        if self.adapter and self.adapter.openocd_config:
            cfg_lines.append(f"source [find {self.adapter.openocd_config}]")
        cfg_lines.append(f"tcl_port {self.tcl_port}")
        cfg_lines.append("telnet_port disabled")
        cfg_lines.append("gdb_port disabled")
        cfg_lines.append("adapter speed 1000")
        cfg_lines.extend(self.extra_init)
        cfg_lines.append("init")

        argv = [self.openocd_path]
        for line in cfg_lines:
            argv += ["-c", line]

        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for the TCL port to accept a connection.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                s = socket.create_connection((self.host, self.tcl_port), timeout=0.5)
                self._sock = s
                return True
            except OSError:
                time.sleep(0.1)
                if self._proc.poll() is not None:
                    return False
        return False

    def close(self) -> None:
        try:
            if self._sock is not None:
                with contextlib.suppress(OSError):
                    self._sock.sendall(b"exit" + _TCL_TERM)
                self._sock.close()
                self._sock = None
        except Exception:
            pass
        try:
            if self._proc is not None:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                self._proc = None
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Core TCL command
    # ------------------------------------------------------------------

    def cmd(self, cmd: str, timeout: float = 5.0) -> str:
        """Send a TCL command, return the response (without terminator)."""
        if self._sock is None:
            raise RuntimeError("JtagBridge.open() must be called first")
        self._sock.settimeout(timeout)
        self._sock.sendall(cmd.encode() + _TCL_TERM)
        buf = bytearray()
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if _TCL_TERM in chunk:
                break
        return buf.replace(_TCL_TERM, b"").decode(errors="replace").strip()

    # ------------------------------------------------------------------
    # Scan chain + IR/DR
    # ------------------------------------------------------------------

    _IDCODE_RE = re.compile(r"0x([0-9a-fA-F]+)")

    def scan_chain(self) -> list[JtagDevice]:
        """Query openocd for the current scan chain."""
        if self._sock is None and not self.open():
            return []
        try:
            resp = self.cmd("scan_chain")
        except Exception:
            return []
        devices: list[JtagDevice] = []
        idx = 0
        for line in resp.splitlines():
            m = self._IDCODE_RE.search(line)
            if not m:
                continue
            try:
                idcode = int(m.group(1), 16)
            except ValueError:
                continue
            if idcode == 0:
                continue
            # Attempt to find IR length in the same row (openocd prints it).
            irlen_m = re.search(r"(?:IR\s*length|irlen)\s*[:=]?\s*(\d+)", line)
            irlen = int(irlen_m.group(1)) if irlen_m else 6
            name = lookup_idcode(idcode)
            devices.append(
                JtagDevice(
                    idcode=idcode,
                    irlen=irlen,
                    name=name,
                    manufacturer=name.split()[0] if name else "",
                    position=idx,
                )
            )
            idx += 1
        return devices

    def write_ir(self, data: int, length_bits: int, tap: str = "openforge.tap") -> None:
        self.cmd(f"irscan {tap} {length_bits} 0x{data:x}")

    def read_ir(self, length_bits: int, tap: str = "openforge.tap") -> int:
        resp = self.cmd(f"irscan {tap} {length_bits} 0x0 -endstate IRPAUSE")
        m = self._IDCODE_RE.search(resp)
        return int(m.group(1), 16) if m else 0

    def write_dr(self, data: int, length_bits: int, tap: str = "openforge.tap") -> None:
        self.cmd(f"drscan {tap} {length_bits} 0x{data:x}")

    def read_dr(self, length_bits: int, tap: str = "openforge.tap") -> int:
        resp = self.cmd(f"drscan {tap} {length_bits} 0x0")
        m = self._IDCODE_RE.search(resp)
        return int(m.group(1), 16) if m else 0

    # ------------------------------------------------------------------
    # Context manager sugar
    # ------------------------------------------------------------------

    def __enter__(self) -> JtagBridge:
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "JtagAdapter",
    "JtagDevice",
    "JtagBridge",
    "KNOWN_ADAPTERS",
    "KNOWN_IDCODES",
    "lookup_idcode",
]
