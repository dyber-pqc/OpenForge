"""Bitstream packers for open-source FPGA flows.

Wraps the small CLI tools that turn nextpnr's intermediate output into
vendor bitstreams:

* :class:`IcestormEngine` -- ``icepack`` / ``icetime`` (Project IceStorm)
* :class:`TrellisEngine` -- ``ecppack`` (Project Trellis, ECP5)
* :class:`GowinPackEngine` -- ``gowin_pack`` (Project Apicula, Gowin GW1N/GW2A)
"""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from typing import Any, Mapping

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


# ---------------------------------------------------------------------------
# Project IceStorm
# ---------------------------------------------------------------------------


_ICETIME_FREQ_RE = re.compile(
    r"Total path delay:\s*([\d.]+)\s*ns\s*\(([\d.]+)\s*MHz\)", re.IGNORECASE
)


class IcestormEngine(ToolEngine):
    """Wraps Project IceStorm's ``icepack`` and ``icetime`` tools."""

    BINARY = "icepack"
    DOCKER_IMAGE = "hdlc/icestorm:latest"

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
        icetime_binary: str = "icetime",
    ) -> None:
        super().__init__(backend=backend, binary_override=binary_override)
        self.icetime_binary = icetime_binary

    # -- ToolEngine --

    def check_installed(self) -> bool:
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--help"])
        text = (result.stdout or "") + (result.stderr or "")
        if m := re.search(r"IceStorm\s+v?([\w.\-]+)", text, re.IGNORECASE):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", text):
            return m.group(1)
        return "unknown"

    # -- operations --

    def pack(
        self,
        asc: str | PathLike[str],
        output_bin: str | PathLike[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run ``icepack <asc> <bin>`` to produce an iCE40 bitstream."""
        return self.run(
            [str(asc), str(output_bin)],
            cwd=cwd,
            env=env,
            timeout=timeout,
        )

    def unpack(
        self,
        bin_file: str | PathLike[str],
        output_asc: str | PathLike[str],
        *,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        return self.run(
            ["-u", str(bin_file), str(output_asc)],
            cwd=cwd,
            timeout=timeout,
        )

    def time(
        self,
        asc: str | PathLike[str],
        *,
        device: str | None = None,
        report_path: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run ``icetime`` static timing analysis and parse the result."""
        prev = self.binary
        self.binary = self.icetime_binary
        try:
            args: list[str] = []
            if device:
                args += ["-d", device]
            args += ["-t"]
            if report_path:
                args += ["-r", str(report_path)]
            args.append(str(asc))
            result = self.run(args, cwd=cwd, timeout=timeout)
        finally:
            self.binary = prev

        text = (result.stdout or "") + "\n" + (result.stderr or "")
        fmax = 0.0
        delay_ns = 0.0
        if m := _ICETIME_FREQ_RE.search(text):
            delay_ns = float(m.group(1))
            fmax = float(m.group(2))
        return {
            "ok": result.ok,
            "fmax_mhz": fmax,
            "critical_path_ns": delay_ns,
            "log": text,
            "report_path": str(report_path) if report_path else None,
            "raw_result": result,
        }


# ---------------------------------------------------------------------------
# Project Trellis (ECP5)
# ---------------------------------------------------------------------------


class TrellisEngine(ToolEngine):
    """Wraps Project Trellis' ``ecppack`` for ECP5 bitstreams."""

    BINARY = "ecppack"
    DOCKER_IMAGE = "hdlc/prjtrellis:latest"

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
    ) -> None:
        super().__init__(backend=backend, binary_override=binary_override)

    def check_installed(self) -> bool:
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--help"])
        text = (result.stdout or "") + (result.stderr or "")
        if m := re.search(r"Project Trellis\s+([\w.\-]+)", text, re.IGNORECASE):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", text):
            return m.group(1)
        return "unknown"

    def pack(
        self,
        config: str | PathLike[str],
        output_bit: str | PathLike[str],
        *,
        svf: str | PathLike[str] | None = None,
        idcode: str | None = None,
        freq_mhz: float | None = None,
        compress: bool = True,
        spimode: str | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run ``ecppack --input <cfg> --bit <bit>``."""
        args: list[str] = ["--input", str(config), "--bit", str(output_bit)]
        if svf:
            args += ["--svf", str(svf)]
        if idcode:
            args += ["--idcode", idcode]
        if freq_mhz is not None:
            args += ["--freq", f"{freq_mhz:g}"]
        if compress:
            args.append("--compress")
        if spimode:
            args += ["--spimode", spimode]
        return self.run(args, cwd=cwd, env=env, timeout=timeout)


# ---------------------------------------------------------------------------
# Project Apicula (Gowin)
# ---------------------------------------------------------------------------


class GowinPackEngine(ToolEngine):
    """Wraps ``gowin_pack`` from Project Apicula for Gowin GW1N/GW2A."""

    BINARY = "gowin_pack"
    DOCKER_IMAGE = ""

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
    ) -> None:
        super().__init__(backend=backend, binary_override=binary_override)

    def check_installed(self) -> bool:
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--help"])
        text = (result.stdout or "") + (result.stderr or "")
        if m := re.search(r"gowin[_-]pack\s+v?([\w.\-]+)", text, re.IGNORECASE):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", text):
            return m.group(1)
        return "unknown"

    def pack(
        self,
        unpacked: str | PathLike[str],
        output_fs: str | PathLike[str],
        *,
        device: str,
        png: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run ``gowin_pack -d <device> -o <fs> <unpacked>``.

        Produces a Gowin ``.fs`` bitstream.
        """
        args: list[str] = ["-d", device, "-o", str(output_fs)]
        if png:
            args += ["--png", str(png)]
        args.append(str(unpacked))
        return self.run(args, cwd=cwd, env=env, timeout=timeout)
