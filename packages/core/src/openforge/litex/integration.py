"""LiteX SoC builder integration.

Generates a ``litex_build.py`` script from a :class:`LiteXSocConfig`
and provides helpers to run ``python litex_build.py --build`` and
``--flash`` via subprocess.

LiteX itself is a huge Python ecosystem -- this module only shells out
to the per-board target modules that ship with it (e.g.
``litex_boards.targets.icebreaker``), which are the official,
supported way to build SoCs for each board.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from openforge.engine.base import ToolResult

if TYPE_CHECKING:
    from os import PathLike

# ---------------------------------------------------------------------------
# Board registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiteXBoardInfo:
    """Metadata for a LiteX-supported board."""

    name: str
    target_module: str  # e.g. "litex_boards.targets.icebreaker"
    default_cpu: str
    default_clk_mhz: int
    bitstream_ext: str  # "bit" / "bin" / "fs"
    programmer_hint: str  # openFPGALoader board name


SUPPORTED_BOARDS: dict[str, LiteXBoardInfo] = {
    "icebreaker": LiteXBoardInfo(
        "icebreaker", "litex_boards.targets.icebreaker", "serv", 12, "bin", "icebreaker"
    ),
    "icestick": LiteXBoardInfo(
        "icestick", "litex_boards.targets.icestick", "serv", 12, "bin", "icestick"
    ),
    "tinyfpga_bx": LiteXBoardInfo(
        "tinyfpga_bx",
        "litex_boards.targets.tinyfpga_bx",
        "serv",
        16,
        "bin",
        "tinyfpga_bx",
    ),
    "fomu": LiteXBoardInfo(
        "fomu", "litex_boards.targets.fomu", "vexriscv", 12, "bin", "fomu"
    ),
    "ulx3s": LiteXBoardInfo(
        "ulx3s", "litex_boards.targets.radiona_ulx3s", "vexriscv", 50, "bit", "ulx3s"
    ),
    "ecpix5": LiteXBoardInfo(
        "ecpix5", "litex_boards.targets.lambdaconcept_ecpix5", "vexriscv", 100, "bit", "ecpix5"
    ),
    "tangnano9k": LiteXBoardInfo(
        "tangnano9k",
        "litex_boards.targets.sipeed_tang_nano_9k",
        "vexriscv",
        27,
        "fs",
        "tangnano9k",
    ),
    "tangnano20k": LiteXBoardInfo(
        "tangnano20k",
        "litex_boards.targets.sipeed_tang_nano_20k",
        "vexriscv",
        27,
        "fs",
        "tangnano20k",
    ),
}


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


class LiteXSocConfig(BaseModel):
    """Configuration for a LiteX SoC build."""

    cpu_type: str = Field(
        default="vexriscv",
        description="CPU core: vexriscv, picorv32, serv, neorv32, naxriscv, none.",
    )
    cpu_variant: str = Field(
        default="standard",
        description="CPU variant string passed to LiteX (e.g. 'standard', 'lite').",
    )
    sys_clk_freq: int = Field(
        default=50_000_000,
        description="System clock frequency in Hz.",
    )
    integrated_rom_size: int = Field(
        default=0x8000,
        description="Integrated ROM size in bytes (0 = disable).",
    )
    integrated_sram_size: int = Field(
        default=0x2000,
        description="Integrated SRAM size in bytes (0 = disable).",
    )
    integrated_main_ram_size: int = Field(
        default=0x4000,
        description="Integrated main RAM in bytes (0 = use external DDR).",
    )
    uart_name: str = Field(
        default="serial",
        description="UART backend: serial, jtag_uart, crossover, stub.",
    )
    with_ethernet: bool = False
    with_etherbone: bool = False
    with_sdcard: bool = False
    with_video_terminal: bool = False
    custom_args: dict[str, Any] = Field(default_factory=dict)

    def as_cli_flags(self, board: LiteXBoardInfo) -> list[str]:
        """Convert this config to ``litex_boards.targets.<board>`` CLI flags."""
        flags: list[str] = [
            f"--cpu-type={self.cpu_type}",
            f"--cpu-variant={self.cpu_variant}",
            f"--sys-clk-freq={self.sys_clk_freq}",
            f"--integrated-rom-size={self.integrated_rom_size}",
            f"--integrated-sram-size={self.integrated_sram_size}",
            f"--integrated-main-ram-size={self.integrated_main_ram_size}",
            f"--uart-name={self.uart_name}",
        ]
        if self.with_ethernet:
            flags.append("--with-ethernet")
        if self.with_etherbone:
            flags.append("--with-etherbone")
        if self.with_sdcard:
            flags.append("--with-sdcard")
        if self.with_video_terminal:
            flags.append("--with-video-terminal")
        for k, v in self.custom_args.items():
            key = k.replace("_", "-")
            if isinstance(v, bool):
                if v:
                    flags.append(f"--{key}")
            else:
                flags.append(f"--{key}={v}")
        return flags


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


_LITEX_SCRIPT_TEMPLATE = """#!/usr/bin/env python3
# Auto-generated by OpenForge LiteXBuilder.
# Board: {board_name}
# Target module: {target_module}

import sys
import runpy

sys.argv = [
    {argv_literal},
]

# Invoke the LiteX board target as if it were run from the command line.
runpy.run_module({target_module_literal}, run_name="__main__")
"""


class LiteXBuilder:
    """Drives a LiteX build for a single board.

    Parameters
    ----------
    board_name:
        Key into :data:`SUPPORTED_BOARDS`.
    config:
        Populated :class:`LiteXSocConfig`.
    output_dir:
        Directory where the generated build script and artifacts live.
    """

    def __init__(
        self,
        board_name: str,
        config: LiteXSocConfig,
        output_dir: str | PathLike[str],
    ) -> None:
        if board_name not in SUPPORTED_BOARDS:
            raise ValueError(
                f"Unsupported LiteX board: {board_name!r}. "
                f"Supported: {sorted(SUPPORTED_BOARDS)}"
            )
        self.board_name = board_name
        self.board_info = SUPPORTED_BOARDS[board_name]
        self.config = config
        self.output_dir = Path(output_dir)
        self.script_path = self.output_dir / "litex_build.py"

    # ------------------------------------------------------------------
    # Script generation
    # ------------------------------------------------------------------

    def _argv(self, *, build: bool = True, flash: bool = False) -> list[str]:
        argv: list[str] = [self.board_info.target_module]
        argv += self.config.as_cli_flags(self.board_info)
        argv += [f"--output-dir={self.output_dir.as_posix()}"]
        if build:
            argv.append("--build")
        if flash:
            argv.append("--flash")
        return argv

    def generate(self) -> Path:
        """Write a standalone ``litex_build.py`` script and return its path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        argv = self._argv(build=True)
        argv_literal = ",\n    ".join(repr(a) for a in argv)
        content = _LITEX_SCRIPT_TEMPLATE.format(
            board_name=self.board_name,
            target_module=self.board_info.target_module,
            argv_literal=argv_literal,
            target_module_literal=repr(self.board_info.target_module),
        )
        self.script_path.write_text(content, encoding="utf-8")
        return self.script_path

    # ------------------------------------------------------------------
    # Build / flash
    # ------------------------------------------------------------------

    def _run_python(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        cmd = [sys.executable, "-m"] + argv
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.output_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=time.monotonic() - start,
                command=cmd,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                returncode=-1,
                stderr=f"LiteX build timed out after {timeout}s",
                duration=time.monotonic() - start,
                command=cmd,
            )
        except FileNotFoundError as exc:
            return ToolResult(
                returncode=-1,
                stderr=f"Failed to launch Python: {exc}",
                duration=time.monotonic() - start,
                command=cmd,
            )

    def build(self, *, timeout: float | None = None) -> ToolResult:
        """Run the LiteX board target with ``--build``."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        argv = self._argv(build=True, flash=False)
        return self._run_python(argv, timeout=timeout)

    def flash(
        self,
        bitstream: str | PathLike[str] | None = None,
        *,
        cable: str | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Flash the last built bitstream to the board.

        Tries the LiteX target ``--flash`` flag first. If that target
        module isn't available, falls back to invoking ``openFPGALoader``
        on the known bitstream path.
        """
        argv = self._argv(build=False, flash=True)
        result = self._run_python(argv, timeout=timeout)
        if result.ok:
            return result

        bit_path: Path
        bit_path = Path(bitstream) if bitstream else self._guess_bitstream()
        if not bit_path.exists():
            return result  # propagate the litex error

        ofl = shutil.which("openFPGALoader") or "openFPGALoader"
        cmd = [ofl, "-b", self.board_info.programmer_hint]
        if cable:
            cmd += ["-c", cable]
        cmd.append(str(bit_path))
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return ToolResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=time.monotonic() - start,
                command=cmd,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return ToolResult(
                returncode=-1,
                stderr=str(exc),
                duration=time.monotonic() - start,
                command=cmd,
            )

    def _guess_bitstream(self) -> Path:
        ext = self.board_info.bitstream_ext
        gateware = self.output_dir / "gateware"
        if gateware.exists():
            for p in gateware.glob(f"*.{ext}"):
                return p
        for p in self.output_dir.rglob(f"*.{ext}"):
            return p
        return self.output_dir / f"{self.board_name}.{ext}"
