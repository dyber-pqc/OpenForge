"""Thin wrapper around ``iceprog`` for Lattice iCE40 devices.

``iceprog`` is the FTDI-based flash programmer shipped with Project
IceStorm. It is used by boards like iCEBreaker and iCE40-HX8K-B-EVN to
write bitstreams into the attached SPI flash over a USB FTDI MPSSE
channel.
"""

from __future__ import annotations

import re
from os import PathLike
from typing import Mapping

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


class IceprogEngine(ToolEngine):
    """Simple wrapper around the ``iceprog`` programmer."""

    BINARY = "iceprog"
    DOCKER_IMAGE = ""  # USB access required

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
    ) -> None:
        super().__init__(backend=backend, binary_override=binary_override)

    # -- ToolEngine --

    def check_installed(self) -> bool:
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["-h"])
        text = (result.stdout or "") + (result.stderr or "")
        if m := re.search(r"iceprog\s*--?\s*simple.*?(\d+\.\d+[\w.\-]*)", text, re.IGNORECASE):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", text):
            return m.group(1)
        return "unknown"

    # -- operations --

    def program(
        self,
        bitstream: str | PathLike[str],
        *,
        device: str | None = None,
        interface: str = "A",
        offset: int | None = None,
        sram: bool = False,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Program a bitstream to flash (default) or SRAM.

        ``iceprog <bin>`` writes to flash. ``iceprog -S <bin>`` writes
        volatile SRAM configuration.
        """
        args: list[str] = []
        if device:
            args += ["-d", device]
        if interface:
            args += ["-I", interface]
        if offset is not None:
            args += ["-o", f"{offset}"]
        if sram:
            args.append("-S")
        args.append(str(bitstream))
        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def verify(
        self,
        bitstream: str | PathLike[str],
        *,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Verify that the flash contents match ``bitstream``."""
        return self.run(["-c", str(bitstream)], cwd=cwd, timeout=timeout)

    def read_flash(
        self,
        output: str | PathLike[str],
        *,
        size_bytes: int | None = None,
        offset: int = 0,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Read SPI flash contents back into a file."""
        args: list[str] = ["-r"]
        if size_bytes is not None:
            args += ["-O", str(offset), "-n", str(size_bytes)]
        args.append(str(output))
        return self.run(args, cwd=cwd, timeout=timeout)

    def erase_flash(
        self,
        *,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Erase the entire SPI flash (``iceprog -b``)."""
        return self.run(["-b"], cwd=cwd, timeout=timeout)

    def test(
        self,
        *,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Probe the device (``iceprog -t``)."""
        return self.run(["-t"], cwd=cwd, timeout=timeout)
