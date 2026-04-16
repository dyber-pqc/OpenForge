"""Mistral / nextpnr-mistral engine for Intel Cyclone V FPGAs.

Mistral is an open-source bitstream documentation project for Intel
(Altera) Cyclone V FPGAs, integrated with nextpnr via the
``nextpnr-mistral`` binary. This engine wraps that binary to provide
a Python-level interface analogous to the iCE40 / ECP5 flows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping
    from os import PathLike


class MistralEngine(ToolEngine):
    """Wraps mistral (open Cyclone V P&R) for Intel/Altera FPGAs."""

    BINARY = "nextpnr-mistral"
    DOCKER_IMAGE = ""  # No standard image

    #: Known Cyclone V parts. Logic element counts are approximate.
    SUPPORTED_PARTS: dict[str, dict[str, object]] = {
        "5CSEMA5F31C6": {
            "family": "cyclone5",
            "die": "5CSEMA5",
            "package": "F31",
            "speed": "6",
            "logic_elements": 32070,
            "m10k_blocks": 397,
            "dsp_blocks": 87,
        },
        "5CSEMA4U23C6": {
            "family": "cyclone5",
            "die": "5CSEMA4",
            "package": "U23",
            "speed": "6",
            "logic_elements": 18480,
            "m10k_blocks": 280,
            "dsp_blocks": 66,
        },
        "5CGXFC5C6F27C7": {
            "family": "cyclone5",
            "die": "5CGXFC5",
            "package": "F27",
            "speed": "7",
            "logic_elements": 29080,
            "m10k_blocks": 446,
            "dsp_blocks": 150,
        },
        "5CSXFC6D6F31C6": {
            "family": "cyclone5",
            "die": "5CSXFC6",
            "package": "F31",
            "speed": "6",
            "logic_elements": 110000,
            "m10k_blocks": 621,
            "dsp_blocks": 112,
        },
    }

    #: Mapping of board aliases to canonical part numbers.
    KNOWN_BOARDS: dict[str, str] = {
        "de10_nano": "5CSEMA5F31C6",
        "de10_standard": "5CSXFC6D6F31C6",
        "de1_soc": "5CSEMA5F31C6",
        "sockit": "5CSXFC6D6F31C6",
        "arrow_sockit": "5CSXFC6D6F31C6",
    }

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
        result = self.run(["--version"])
        if result.ok:
            for line in (result.stdout + "\n" + result.stderr).splitlines():
                if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", line):
                    return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def resolve_board(cls, board: str) -> str | None:
        return cls.KNOWN_BOARDS.get(board.lower())

    @classmethod
    def part_info(cls, part: str) -> dict[str, object]:
        if part not in cls.SUPPORTED_PARTS:
            raise ValueError(f"Unsupported Cyclone V part: {part}")
        return dict(cls.SUPPORTED_PARTS[part])

    @classmethod
    def list_parts(cls) -> list[str]:
        return sorted(cls.SUPPORTED_PARTS.keys())

    @classmethod
    def list_boards(cls) -> list[str]:
        return sorted(cls.KNOWN_BOARDS.keys())

    # ------------------------------------------------------------------
    # Flow steps
    # ------------------------------------------------------------------

    def place_and_route(
        self,
        json_file: str | PathLike[str],
        *,
        part: str,
        qsf_file: str | PathLike[str] | None = None,
        output_asc: str | PathLike[str] | None = None,
        output_rbf: str | PathLike[str] | None = None,
        seed: int | None = None,
        freq_mhz: float | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run ``nextpnr-mistral`` place and route.

        ``json_file`` is the Yosys JSON netlist. ``qsf_file`` is a
        Quartus Settings File containing pin assignments.
        """
        info = self.part_info(part)

        args: list[str] = [
            "--device",
            part,
            "--json",
            str(json_file),
        ]
        if qsf_file is not None:
            args += ["--qsf", str(qsf_file)]
        if output_asc is not None:
            args += ["--write", str(output_asc)]
        if output_rbf is not None:
            args += ["--rbf", str(output_rbf)]
        if seed is not None:
            args += ["--seed", str(seed)]
        if freq_mhz is not None:
            args += ["--freq", str(freq_mhz)]

        # Silence unused warning on info
        _ = info

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def generate_bitstream(
        self,
        routed_json: str | PathLike[str],
        *,
        part: str,
        output_rbf: str | PathLike[str],
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Regenerate a raw binary (``.rbf``) file from a routed JSON."""
        args = [
            "--device",
            part,
            "--json",
            str(routed_json),
            "--rbf",
            str(output_rbf),
        ]
        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def full_flow(
        self,
        json_file: str | PathLike[str],
        *,
        part: str,
        top_module: str = "top",
        qsf_file: str | PathLike[str] | None = None,
        work_dir: str | PathLike[str] | None = None,
        freq_mhz: float | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Run P&R and bitstream generation for a pre-synthesized JSON.

        Yosys synthesis must be performed separately (``synth_intel_alm``
        is the recommended target).
        """
        work = Path(work_dir) if work_dir else Path.cwd() / "build_mistral"
        work.mkdir(parents=True, exist_ok=True)

        routed = work / f"{top_module}_routed.json"
        rbf = work / f"{top_module}.rbf"

        result = self.place_and_route(
            json_file,
            part=part,
            qsf_file=qsf_file,
            output_asc=routed,
            output_rbf=rbf,
            freq_mhz=freq_mhz,
            cwd=work,
            timeout=timeout,
        )
        if not result.ok:
            return {
                "ok": False,
                "step": "pnr",
                "error": result.stderr,
                "work_dir": str(work),
            }

        return {
            "ok": True,
            "step": "done",
            "work_dir": str(work),
            "routed_json": str(routed),
            "rbf": str(rbf),
        }

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def parse_utilization(self, log_text: str) -> dict[str, int]:
        """Extract nextpnr utilization counters from a log."""
        usage: dict[str, int] = {}
        patterns = {
            "logic_cells": r"Logic cells:\s*(\d+)",
            "ffs": r"FFs:\s*(\d+)",
            "m10k": r"M10K:\s*(\d+)",
            "dsps": r"DSP:\s*(\d+)",
            "io": r"IO:\s*(\d+)",
        }
        for key, pattern in patterns.items():
            if m := re.search(pattern, log_text):
                usage[key] = int(m.group(1))
        return usage
