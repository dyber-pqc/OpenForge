"""nextpnr place-and-route engine wrapper.

Covers the nextpnr family of place-and-route tools: ``nextpnr-ice40``,
``nextpnr-ecp5``, ``nextpnr-nexus``, ``nextpnr-machxo2`` and the
``nextpnr-generic`` flow. Each variant has a slightly different CLI, so
this engine exposes a ``run_*`` method per target.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping
    from os import PathLike

# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


_RESOURCE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "LUTs": [
        re.compile(r"ICESTORM_LC:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"TRELLIS_(?:COMB|SLICE)[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"(?:OXIDE_COMB|LUT4|SLICE_LUTX)[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"LUT[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
    ],
    "FFs": [
        re.compile(r"SB_DFF[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"TRELLIS_FF[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"OXIDE_FF[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"(?:FF|DFF|FLIPFLOP)[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
    ],
    "BRAMs": [
        re.compile(r"(?:ICESTORM_RAM|SB_RAM[^:]*|DP16KD|PDPSC16K|EBR|BRAM)[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
    ],
    "DSPs": [
        re.compile(r"(?:MULT18X18D|ALU54B|DSP|MULT)[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
    ],
    "IOs": [
        re.compile(r"SB_IO[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"TRELLIS_IO[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
        re.compile(r"SEIO[BA]*[^:]*:\s*(\d+)/\s*(\d+)\s+(\d+)%", re.IGNORECASE),
    ],
}

_FMAX_RE = re.compile(
    r"Max frequency for clock\s+'?([^':]+)'?:\s*([\d.]+)\s*MHz", re.IGNORECASE
)
_FMAX_RESTRICTED_RE = re.compile(
    r"Max frequency for clock\s+'?([^':]+)'?\s*\(.*?\):\s*([\d.]+)\s*MHz",
    re.IGNORECASE,
)
_TIMING_FAIL_RE = re.compile(
    r"Max delay .*?(?:FAILED|VIOLATED)|timing failure|slack\s+-[\d.]+\s*ns",
    re.IGNORECASE,
)
_SEED_RE = re.compile(r"Generated random seed:\s*(\d+)", re.IGNORECASE)
_PLACED_CELL_RE = re.compile(r"Placed (\d+) cells", re.IGNORECASE)


def parse_nextpnr_log(text: str) -> dict[str, Any]:
    """Extract utilization, fmax and timing info from nextpnr stdout."""
    utilization: dict[str, tuple[int, int, float]] = {}
    for key, patterns in _RESOURCE_PATTERNS.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                used, total, pct = int(m.group(1)), int(m.group(2)), float(m.group(3))
                utilization[key] = (used, total, pct)
                break

    fmax_mhz = 0.0
    fmax_per_clock: dict[str, float] = {}
    for m in _FMAX_RE.finditer(text):
        clk = m.group(1).strip()
        freq = float(m.group(2))
        fmax_per_clock[clk] = freq
        if freq > fmax_mhz:
            fmax_mhz = freq

    timing_violations = len(_TIMING_FAIL_RE.findall(text))

    seed: int | None = None
    if m := _SEED_RE.search(text):
        seed = int(m.group(1))

    placed = 0
    if m := _PLACED_CELL_RE.search(text):
        placed = int(m.group(1))

    return {
        "utilization": utilization,
        "fmax_mhz": fmax_mhz,
        "fmax_per_clock": fmax_per_clock,
        "timing_violations": timing_violations,
        "placed_cells": placed,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class NextpnrEngine(ToolEngine):
    """Wraps the nextpnr place-and-route tools.

    nextpnr ships as several per-family binaries rather than a single
    executable, so the :pyattr:`BINARY` attribute is unused and each
    ``run_*`` method invokes the appropriate binary directly.
    """

    BINARY = "nextpnr-ice40"
    DOCKER_IMAGE = "hdlc/nextpnr:latest"

    # Known per-family binaries (override via *binary_override* map).
    FAMILY_BINARIES: dict[str, str] = {
        "ice40": "nextpnr-ice40",
        "ecp5": "nextpnr-ecp5",
        "nexus": "nextpnr-nexus",
        "machxo2": "nextpnr-machxo2",
        "generic": "nextpnr-generic",
        "gowin": "nextpnr-gowin",
        "xilinx": "nextpnr-xilinx",
    }

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
        binary_overrides: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(backend=backend, binary_override=binary_override)
        self._family_binaries = dict(self.FAMILY_BINARIES)
        if binary_overrides:
            self._family_binaries.update(binary_overrides)

    # ------------------------------------------------------------------
    # ToolEngine interface
    # ------------------------------------------------------------------

    def check_installed(self) -> bool:
        """True if at least one nextpnr-* binary is on ``$PATH``."""
        import shutil
        return any(shutil.which(b) is not None for b in self._family_binaries.values())

    def version(self, family: str = "ice40") -> str:
        bin_name = self._family_binaries.get(family, self.BINARY)
        prev = self.binary
        self.binary = bin_name
        try:
            result = self.run(["--version"])
        finally:
            self.binary = prev
        text = (result.stdout or "") + (result.stderr or "")
        if m := re.search(r"nextpnr[-\w]*\s+v?([\w.\-]+)", text, re.IGNORECASE):
            return m.group(1)
        if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", text):
            return m.group(1)
        return "unknown"

    def list_installed_families(self) -> list[str]:
        import shutil
        return [
            fam
            for fam, b in self._family_binaries.items()
            if shutil.which(b) is not None
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invoke(
        self,
        family: str,
        args: list[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        bin_name = self._family_binaries.get(family, f"nextpnr-{family}")
        prev = self.binary
        self.binary = bin_name
        try:
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = prev

    @staticmethod
    def _write_log(result: ToolResult, log_path: Path | None) -> str | None:
        if log_path is None:
            return None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            (result.stdout or "") + "\n---STDERR---\n" + (result.stderr or ""),
            encoding="utf-8",
            errors="replace",
        )
        return str(log_path)

    def _build_result_dict(
        self,
        result: ToolResult,
        *,
        log_path: str | None,
        output_path: str | None,
        output_key: str = "asc_path",
    ) -> dict[str, Any]:
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        parsed = parse_nextpnr_log(text)
        return {
            "ok": result.ok,
            "returncode": result.returncode,
            "duration": result.duration,
            "command": result.command,
            "utilization": parsed["utilization"],
            "fmax_mhz": parsed["fmax_mhz"],
            "fmax_per_clock": parsed["fmax_per_clock"],
            "timing_violations": parsed["timing_violations"],
            "placed_cells": parsed["placed_cells"],
            "seed": parsed["seed"],
            "log_path": log_path,
            output_key: output_path,
            "raw_result": result,
        }

    # ------------------------------------------------------------------
    # Per-family runners
    # ------------------------------------------------------------------

    def run_ice40(
        self,
        json_netlist: str | PathLike[str],
        pcf: str | PathLike[str] | None = None,
        *,
        device: str = "up5k",
        package: str = "sg48",
        freq_mhz: float = 12.0,
        output_asc: str | PathLike[str] | None = None,
        log_path: str | PathLike[str] | None = None,
        seed: int | None = None,
        opt_timing: bool = True,
        placer: str | None = None,
        router: str | None = None,
        extra_args: list[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run ``nextpnr-ice40`` for a Lattice iCE40 target."""
        device_flag = f"--{device}"
        args: list[str] = [device_flag, "--package", package, "--json", str(json_netlist)]
        if pcf:
            args += ["--pcf", str(pcf)]
        args += ["--freq", f"{freq_mhz:g}"]
        if output_asc:
            args += ["--asc", str(output_asc)]
        if seed is not None:
            args += ["--seed", str(seed)]
        if opt_timing:
            args.append("--opt-timing")
        if placer:
            args += ["--placer", placer]
        if router:
            args += ["--router", router]
        if extra_args:
            args += list(extra_args)

        result = self._invoke("ice40", args, cwd=cwd, env=env, timeout=timeout)
        lp = self._write_log(result, Path(log_path) if log_path else None)
        return self._build_result_dict(
            result,
            log_path=lp,
            output_path=str(output_asc) if output_asc else None,
            output_key="asc_path",
        )

    def run_ecp5(
        self,
        json_netlist: str | PathLike[str],
        lpf: str | PathLike[str] | None = None,
        *,
        device: str = "25k",
        package: str = "CABGA381",
        speed: int = 6,
        freq_mhz: float | None = None,
        output_config: str | PathLike[str] | None = None,
        log_path: str | PathLike[str] | None = None,
        seed: int | None = None,
        opt_timing: bool = True,
        extra_args: list[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run ``nextpnr-ecp5`` for a Lattice ECP5 target."""
        args: list[str] = [
            f"--{device}",
            "--package",
            package,
            "--speed",
            str(speed),
            "--json",
            str(json_netlist),
        ]
        if lpf:
            args += ["--lpf", str(lpf)]
        if freq_mhz is not None:
            args += ["--freq", f"{freq_mhz:g}"]
        if output_config:
            args += ["--textcfg", str(output_config)]
        if seed is not None:
            args += ["--seed", str(seed)]
        if opt_timing:
            args.append("--timing-allow-fail")
        if extra_args:
            args += list(extra_args)

        result = self._invoke("ecp5", args, cwd=cwd, env=env, timeout=timeout)
        lp = self._write_log(result, Path(log_path) if log_path else None)
        return self._build_result_dict(
            result,
            log_path=lp,
            output_path=str(output_config) if output_config else None,
            output_key="config_path",
        )

    def run_nexus(
        self,
        json_netlist: str | PathLike[str],
        pdc: str | PathLike[str] | None = None,
        *,
        device: str = "LIFCL-40-9BG400C",
        freq_mhz: float | None = None,
        output_fasm: str | PathLike[str] | None = None,
        log_path: str | PathLike[str] | None = None,
        seed: int | None = None,
        extra_args: list[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run ``nextpnr-nexus`` for Lattice Nexus / CrossLink-NX."""
        args: list[str] = ["--device", device, "--json", str(json_netlist)]
        if pdc:
            args += ["--pdc", str(pdc)]
        if freq_mhz is not None:
            args += ["--freq", f"{freq_mhz:g}"]
        if output_fasm:
            args += ["--fasm", str(output_fasm)]
        if seed is not None:
            args += ["--seed", str(seed)]
        if extra_args:
            args += list(extra_args)

        result = self._invoke("nexus", args, cwd=cwd, env=env, timeout=timeout)
        lp = self._write_log(result, Path(log_path) if log_path else None)
        return self._build_result_dict(
            result,
            log_path=lp,
            output_path=str(output_fasm) if output_fasm else None,
            output_key="fasm_path",
        )

    def run_machxo2(
        self,
        json_netlist: str | PathLike[str],
        lpf: str | PathLike[str] | None = None,
        *,
        device: str = "1200",
        package: str = "TQFP100",
        speed: int = 4,
        freq_mhz: float | None = None,
        output_config: str | PathLike[str] | None = None,
        log_path: str | PathLike[str] | None = None,
        seed: int | None = None,
        extra_args: list[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run ``nextpnr-machxo2`` for a Lattice MachXO2 target."""
        args: list[str] = [
            f"--{device}",
            "--package",
            package,
            "--speed",
            str(speed),
            "--json",
            str(json_netlist),
        ]
        if lpf:
            args += ["--lpf", str(lpf)]
        if freq_mhz is not None:
            args += ["--freq", f"{freq_mhz:g}"]
        if output_config:
            args += ["--textcfg", str(output_config)]
        if seed is not None:
            args += ["--seed", str(seed)]
        if extra_args:
            args += list(extra_args)

        result = self._invoke("machxo2", args, cwd=cwd, env=env, timeout=timeout)
        lp = self._write_log(result, Path(log_path) if log_path else None)
        return self._build_result_dict(
            result,
            log_path=lp,
            output_path=str(output_config) if output_config else None,
            output_key="config_path",
        )

    def run_generic(
        self,
        json_netlist: str | PathLike[str],
        *,
        chipdb: str | PathLike[str] | None = None,
        freq_mhz: float | None = None,
        output_json: str | PathLike[str] | None = None,
        output_routed: str | PathLike[str] | None = None,
        log_path: str | PathLike[str] | None = None,
        seed: int | None = None,
        extra_args: list[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run ``nextpnr-generic`` against a prebuilt chipdb."""
        args: list[str] = ["--json", str(json_netlist)]
        if chipdb:
            args += ["--chipdb", str(chipdb)]
        if freq_mhz is not None:
            args += ["--freq", f"{freq_mhz:g}"]
        if output_json:
            args += ["--write", str(output_json)]
        if output_routed:
            args += ["--routed-svg", str(output_routed)]
        if seed is not None:
            args += ["--seed", str(seed)]
        if extra_args:
            args += list(extra_args)

        result = self._invoke("generic", args, cwd=cwd, env=env, timeout=timeout)
        lp = self._write_log(result, Path(log_path) if log_path else None)
        return self._build_result_dict(
            result,
            log_path=lp,
            output_path=str(output_json) if output_json else None,
            output_key="output_json",
        )
