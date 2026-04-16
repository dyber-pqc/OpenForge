"""Universal FPGA programming via openFPGALoader.

openFPGALoader (https://github.com/trabucayre/openFPGALoader) is a
universal programming utility that supports a wide variety of JTAG
cables and FPGA families (Lattice, Xilinx, Intel, Gowin, Anlogic,
Efinix, etc.). This engine provides a Python wrapper for common
operations such as SRAM loading, SPI flash programming and
verification.
"""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from typing import Mapping, Sequence

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


class OpenFPGALoaderEngine(ToolEngine):
    """Universal FPGA programmer via openFPGALoader."""

    BINARY = "openFPGALoader"
    DOCKER_IMAGE = ""  # USB access required, no Docker by default

    #: A subset of the boards supported by openFPGALoader that we care about.
    KNOWN_BOARDS: tuple[str, ...] = (
        # Lattice ice40
        "icebreaker",
        "icesugar",
        "ice40_hx8k_b_evn",
        "tinyfpga_bx",
        # Lattice ECP5
        "ulx3s",
        "ecpix5",
        "versa_ecp5",
        "ecp5_evn",
        "colorlight-i5",
        # Xilinx 7-series
        "arty_a7_35t",
        "arty_a7_100t",
        "basys3",
        "nexysA7100",
        "cmoda7_35t",
        "genesys2",
        "zybo_z7_10",
        "zybo_z7_20",
        # Intel Cyclone V
        "de10nano",
        "de10lite",
        "de0nano",
        "de1soc",
        # Gowin
        "tangnano9k",
        "tangnano20k",
        "tangprimer20k",
        "tangmega138k",
    )

    #: Common cable names passed to ``-c``.
    KNOWN_CABLES: tuple[str, ...] = (
        "ft232",
        "ft2232",
        "ft232RL",
        "ft4232",
        "ft4232hp",
        "digilent",
        "digilent_hs2",
        "digilent_hs3",
        "jlink",
        "cmsisdap",
        "usb-blaster",
        "usb-blasterII",
        "dirtyJtag",
        "xvc-client",
    )

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
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--Version"])
        if not result.ok:
            result = self.run(["-V"])
        if result.ok:
            text = result.stdout + "\n" + result.stderr
            if m := re.search(r"openFPGALoader\s+v?(\d+\.\d+(?:\.\d+)?)", text):
                return m.group(1)
            if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", text):
                return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_cables(self) -> list[dict[str, str]]:
        """List supported JTAG cables/programmers.

        Returns a list of ``{name, description}`` dictionaries.
        """
        result = self.run(["--list-cables"])
        cables: list[dict[str, str]] = []
        if not result.ok:
            return [{"name": c, "description": ""} for c in self.KNOWN_CABLES]
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("cable") or line.startswith("-"):
                continue
            parts = re.split(r"\s{2,}|\t+", line, maxsplit=1)
            name = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            if name:
                cables.append({"name": name, "description": desc})
        return cables

    def list_boards(self) -> list[str]:
        """Return the list of supported boards."""
        result = self.run(["--list-boards"])
        boards: list[str] = []
        if not result.ok:
            return list(self.KNOWN_BOARDS)
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("board") or line.startswith("-"):
                continue
            name = line.split()[0]
            if name:
                boards.append(name)
        return boards or list(self.KNOWN_BOARDS)

    def list_fpgas(self) -> list[dict[str, str]]:
        """Return the list of supported FPGA part numbers."""
        result = self.run(["--list-fpga"])
        fpgas: list[dict[str, str]] = []
        if not result.ok:
            return fpgas
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("fpga"):
                continue
            m = re.match(r"(0x[0-9a-fA-F]+)\s+(\S+)\s*(.*)", line)
            if m:
                fpgas.append(
                    {"idcode": m.group(1), "model": m.group(2), "family": m.group(3)}
                )
        return fpgas

    def detect_devices(self, cable: str | None = None) -> list[dict[str, str]]:
        """Detect connected FPGA devices on the JTAG chain.

        Invokes ``openFPGALoader --detect`` and parses IDCODE entries.
        """
        args = ["--detect"]
        if cable:
            args = ["-c", cable] + args
        result = self.run(args)
        devices: list[dict[str, str]] = []
        if not result.ok:
            return devices
        pattern = re.compile(
            r"index\s+(\d+).*?idcode\s+(0x[0-9a-fA-F]+).*?manufacturer\s+(\S+).*?model\s+(\S+)",
            re.IGNORECASE,
        )
        text = result.stdout + "\n" + result.stderr
        for m in pattern.finditer(text):
            devices.append(
                {
                    "index": m.group(1),
                    "idcode": m.group(2),
                    "manufacturer": m.group(3),
                    "model": m.group(4),
                }
            )
        if not devices:
            for line in text.splitlines():
                if m := re.search(r"(0x[0-9a-fA-F]{8})", line):
                    devices.append(
                        {
                            "index": str(len(devices)),
                            "idcode": m.group(1),
                            "manufacturer": "unknown",
                            "model": "unknown",
                        }
                    )
        return devices

    # ------------------------------------------------------------------
    # Programming
    # ------------------------------------------------------------------

    def _common_args(
        self,
        *,
        board: str | None,
        cable: str | None,
        fpga_part: str | None,
        freq_hz: int | None,
    ) -> list[str]:
        args: list[str] = []
        if board:
            args += ["-b", board]
        if cable:
            args += ["-c", cable]
        if fpga_part:
            args += ["--fpga-part", fpga_part]
        if freq_hz:
            args += ["--freq", str(freq_hz)]
        return args

    def program(
        self,
        bitstream: str | PathLike[str],
        *,
        board: str | None = None,
        cable: str | None = None,
        fpga_part: str | None = None,
        flash: bool = False,
        verify: bool = False,
        unprotect_flash: bool = False,
        freq_hz: int | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Program a bitstream into the device.

        Parameters
        ----------
        bitstream:
            Path to the ``.bit``/``.bin``/``.rbf``/``.svf`` file.
        flash:
            When *True*, write to SPI flash instead of configuration SRAM.
        verify:
            Verify the flash contents after writing.
        """
        args = self._common_args(
            board=board, cable=cable, fpga_part=fpga_part, freq_hz=freq_hz
        )
        if flash:
            args.append("-f")
        else:
            args.append("-m")
        if verify:
            args.append("--verify")
        if unprotect_flash:
            args.append("--unprotect-flash")
        args.append(str(bitstream))
        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def program_sram(
        self,
        bitstream: str | PathLike[str],
        *,
        board: str | None = None,
        cable: str | None = None,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Shortcut for volatile (SRAM) programming."""
        return self.program(
            bitstream,
            board=board,
            cable=cable,
            flash=False,
            cwd=cwd,
            timeout=timeout,
        )

    def program_flash(
        self,
        bitstream: str | PathLike[str],
        *,
        board: str | None = None,
        cable: str | None = None,
        verify: bool = True,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Shortcut for persistent (SPI flash) programming."""
        return self.program(
            bitstream,
            board=board,
            cable=cable,
            flash=True,
            verify=verify,
            cwd=cwd,
            timeout=timeout,
        )

    def read_flash(
        self,
        output: str | PathLike[str],
        *,
        board: str,
        size_kb: int,
        cable: str | None = None,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Read back the contents of the SPI flash to ``output``."""
        args = self._common_args(
            board=board, cable=cable, fpga_part=None, freq_hz=None
        )
        args += ["--dump-flash", "-o", str(output), "--file-size", str(size_kb * 1024)]
        return self.run(args, cwd=cwd, timeout=timeout)

    def erase_flash(
        self,
        *,
        board: str,
        cable: str | None = None,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Erase the entire SPI flash."""
        args = self._common_args(
            board=board, cable=cable, fpga_part=None, freq_hz=None
        )
        args.append("--unprotect-flash")
        args.append("--bulk-erase")
        return self.run(args, cwd=cwd, timeout=timeout)

    def reset(
        self,
        *,
        board: str | None = None,
        cable: str | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Issue a JTAG reset to the target device."""
        args = self._common_args(
            board=board, cable=cable, fpga_part=None, freq_hz=None
        )
        args.append("--reset")
        return self.run(args, timeout=timeout)

    def read_idcode(
        self,
        *,
        cable: str | None = None,
        timeout: float | None = None,
    ) -> str | None:
        """Return the IDCODE of the first device on the chain."""
        devices = self.detect_devices(cable=cable)
        if devices:
            return devices[0]["idcode"]
        return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def detect_fpga(self, cable: str | None = None) -> dict[str, str]:
        """Return a single ``{idcode, model, manufacturer, name}`` dict.

        Convenience wrapper around :meth:`detect_devices` matching the
        FPGA toolchain API spec.
        """
        devices = self.detect_devices(cable=cable)
        if not devices:
            return {}
        first = devices[0]
        return {
            "idcode": first.get("idcode", ""),
            "model": first.get("model", ""),
            "manufacturer": first.get("manufacturer", ""),
            "name": first.get("model", ""),
        }

    def program_with_mode(
        self,
        bitstream: str | PathLike[str],
        *,
        board: str | None = None,
        cable: str | None = None,
        mode: str = "sram",
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Program with a mode string: ``'sram'`` or ``'flash'``."""
        return self.program(
            bitstream,
            board=board,
            cable=cable,
            flash=(mode == "flash"),
            cwd=cwd,
            timeout=timeout,
        )

    def parse_write_progress(self, log_text: str) -> list[dict[str, str]]:
        """Extract per-phase progress information from a log."""
        phases: list[dict[str, str]] = []
        for line in log_text.splitlines():
            if m := re.match(
                r"(Erase|Write|Verify|Read)\s*(Flash|SRAM)?\s*:?\s*\[?\s*(\d+)%\]?",
                line.strip(),
                re.IGNORECASE,
            ):
                phases.append(
                    {
                        "phase": m.group(1),
                        "target": m.group(2) or "",
                        "percent": m.group(3),
                    }
                )
        return phases


# Convenience alias matching the FPGA toolchain spec.
OpenFpgaLoader = OpenFPGALoaderEngine
