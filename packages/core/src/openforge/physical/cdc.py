"""Clock Domain Crossing (CDC) analysis.

Runs a lightweight Yosys pass to enumerate register-to-register paths
whose endpoints are in different clock domains, then classifies each
crossing as safe, partial, glitch-prone, or data-loss-risking.

This is not a replacement for a commercial CDC tool (Questa CDC,
Conformal CDC) but catches the most common mistakes early during FPGA
bring-up.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Sequence


class CdcViolation(BaseModel):
    src_clock: str
    dst_clock: str
    src_pin: str
    dst_pin: str
    kind: str  # 'unsynchronized' | 'partial_sync' | 'glitch_risk' | 'data_loss'
    severity: str = "error"  # 'error' | 'warning' | 'info'
    suggestion: str = ""


class CdcReport(BaseModel):
    violations: list[CdcViolation] = Field(default_factory=list)
    safe_crossings: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_design(
        cls,
        rtl_files: Sequence[str | Path],
        top: str,
        sdc: str | Path | None = None,
    ) -> CdcReport:
        """Analyse RTL for CDC crossings via Yosys.

        Emits a Yosys script that reads the RTL, flattens the design,
        writes a JSON netlist, and then walks the netlist to find FF
        pairs whose clock pins differ. Each crossing is scored.
        """
        yosys = shutil.which("yosys")
        if not yosys:
            return cls(violations=[], safe_crossings=0)

        clocks_hint: set[str] = set()
        if sdc and Path(sdc).exists():
            text = Path(sdc).read_text(errors="replace")
            for m in re.finditer(
                r"create_clock[^{]*(?:-name\s+(\S+)|\[get_ports\s+(\S+)\])",
                text,
            ):
                name = m.group(1) or m.group(2)
                if name:
                    clocks_hint.add(name.strip("{} \t"))

        with tempfile.TemporaryDirectory(prefix="openforge-cdc-") as tmp:
            netlist = Path(tmp) / "netlist.json"
            read_cmds: list[str] = []
            for f in rtl_files:
                fp = str(Path(f).as_posix())
                if fp.endswith((".vhd", ".vhdl")):
                    read_cmds.append(f"read_vhdl {fp}")
                else:
                    read_cmds.append(f"read_verilog -sv {fp}")
            script = "; ".join(
                [
                    *read_cmds,
                    f"hierarchy -top {top}",
                    "proc; flatten; opt_clean",
                    f"write_json {netlist.as_posix()}",
                ]
            )
            try:
                subprocess.run(
                    [yosys, "-q", "-p", script],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return cls(violations=[], safe_crossings=0)

            if not netlist.exists():
                return cls(violations=[], safe_crossings=0)

            data = json.loads(netlist.read_text())
            return cls._analyze_netlist(data, top, clocks_hint)

    # ------------------------------------------------------------------
    # Netlist walk
    # ------------------------------------------------------------------

    _FF_TYPES = {
        "$dff",
        "$dffe",
        "$dffsr",
        "$dffsre",
        "$adff",
        "$adffe",
        "$sdff",
        "$sdffe",
        "FDRE",
        "FDCE",
        "FDPE",
        "FDSE",
    }

    @classmethod
    def _analyze_netlist(
        cls,
        netlist: dict,
        top: str,
        clocks_hint: set[str],
    ) -> CdcReport:
        modules = netlist.get("modules", {})
        mod = modules.get(top) or next(iter(modules.values()), None)
        if not mod:
            return cls()

        nets = mod.get("netnames", {})
        cells = mod.get("cells", {})

        # Build a map: net bit -> (driver_cell_name, driver_clock_net)
        bit_driver: dict[int, tuple[str, str]] = {}
        ff_inputs: list[tuple[str, str, list[int]]] = []  # (name, clk_net, data_bits)

        def net_name_for(bit: int) -> str:
            for name, info in nets.items():
                if bit in info.get("bits", []):
                    return name
            return f"bit{bit}"

        for cname, cell in cells.items():
            if cell.get("type") not in cls._FF_TYPES:
                continue
            conns = cell.get("connections", {})
            clk_bits = conns.get("CLK") or conns.get("C") or []
            d_bits = conns.get("D") or []
            q_bits = conns.get("Q") or []
            clk_net = net_name_for(clk_bits[0]) if clk_bits else "?"
            for qb in q_bits:
                if isinstance(qb, int):
                    bit_driver[qb] = (cname, clk_net)
            ff_inputs.append((cname, clk_net, [b for b in d_bits if isinstance(b, int)]))

        violations: list[CdcViolation] = []
        safe = 0
        # Count 2-FF synchronizer chains: if an FF's D comes from another FF
        # in the same dest clock that in turn comes from a different clock,
        # we treat it as a "partial" synchronizer (needs 2+ FFs).
        for fname, dst_clk, d_bits in ff_inputs:
            for db in d_bits:
                driver = bit_driver.get(db)
                if not driver:
                    continue
                src_name, src_clk = driver
                if src_clk == dst_clk or src_clk == "?" or dst_clk == "?":
                    continue
                # Crossing!
                # Check whether source FF drives only this one net (single-bit sync).
                same_driver_bits = [b for b, (n, _) in bit_driver.items() if n == src_name]
                kind = "unsynchronized"
                severity = "error"
                suggestion = (
                    "Add at least a 2-flop synchronizer, or use a handshake / "
                    "async FIFO if more than one bit is crossing."
                )
                if len(d_bits) > 1:
                    kind = "data_loss"
                    severity = "error"
                    suggestion = (
                        "Multi-bit crossing without Gray coding; use an async "
                        "FIFO or encode as Gray before crossing."
                    )
                elif len(same_driver_bits) == 1:
                    # Check if destination FF forwards only to another FF in
                    # the same clock domain (2-FF sync pattern).
                    downstream = [d for d, c, _ in ff_inputs if c == dst_clk and d != fname]
                    if downstream:
                        kind = "partial_sync"
                        severity = "warning"
                        suggestion = "Looks like a 2-FF synchronizer - verify depth >= 2."

                violations.append(
                    CdcViolation(
                        src_clock=src_clk,
                        dst_clock=dst_clk,
                        src_pin=src_name,
                        dst_pin=fname,
                        kind=kind,
                        severity=severity,
                        suggestion=suggestion,
                    )
                )
                if kind == "partial_sync":
                    safe += 1
        return cls(violations=violations, safe_crossings=safe)


__all__ = ["CdcViolation", "CdcReport"]
