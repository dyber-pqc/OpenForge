"""Reset Domain Crossing (RDC) analysis.

Mirrors the CDC checker but classifies reset nets instead of clock nets.
Uses yosys to flatten the design and walk the JSON netlist.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ResetDomain(BaseModel):
    """A detected reset domain."""

    name: str
    polarity: str = "active_low"  # 'active_high' | 'active_low'
    sync: str = "async"  # 'sync' | 'async'
    source: str = ""


class RdcCrossing(BaseModel):
    """A register driven by a signal born in a different reset domain."""

    src_reset: str
    dst_reset: str
    register: str
    crossing_type: str = "no_isolation"
    severity: str = "warning"
    suggestion: str = ""


class RdcReport(BaseModel):
    domains: list[ResetDomain] = Field(default_factory=list)
    crossings: list[RdcCrossing] = Field(default_factory=list)


class RdcAnalyzer:
    """Reset domain crossing analyser driven by yosys netlist JSON."""

    _ACTIVE_LOW_RE = re.compile(r"_n$|rst_n|rstn|reset_n|resetn", re.IGNORECASE)
    _ASYNC_RE = re.compile(r"async|arst", re.IGNORECASE)

    def __init__(self, rtl_files: list[Path] | list[str], top: str) -> None:
        self._rtl = [Path(p) for p in rtl_files]
        self._top = top
        self._domains: list[ResetDomain] = []
        self._crossings: list[RdcCrossing] = []
        self._netlist: dict[str, Any] = {}

    def detect_reset_domains(self) -> list[ResetDomain]:
        self._ensure_netlist()
        found: dict[str, int] = {}
        modules = self._netlist.get("modules", {})
        for _mname, mdata in modules.items():
            cells = mdata.get("cells", {})
            nets = mdata.get("netnames", {})
            for _cname, cdata in cells.items():
                ctype = str(cdata.get("type", "")).upper()
                if "DFF" not in ctype and "FF" not in ctype:
                    continue
                conns = cdata.get("connections", {})
                rst_bits = (
                    conns.get("R")
                    or conns.get("RST")
                    or conns.get("CLR")
                    or conns.get("PRE")
                )
                if not rst_bits:
                    continue
                name = _find_net_name(nets, rst_bits[0])
                found[name] = found.get(name, 0) + 1

        self._domains = [
            ResetDomain(
                name=name,
                polarity=(
                    "active_low" if self._ACTIVE_LOW_RE.search(name) else "active_high"
                ),
                sync=("async" if self._ASYNC_RE.search(name) else "sync"),
                source=name,
            )
            for name in sorted(found.keys())
        ]
        return list(self._domains)

    def detect_crossings(self) -> list[RdcCrossing]:
        if not self._domains:
            self.detect_reset_domains()
        self._ensure_netlist()

        ff_to_reset: dict[str, str] = {}
        ff_d: dict[str, list[int]] = {}
        ff_q: dict[str, list[int]] = {}

        modules = self._netlist.get("modules", {})
        for _mname, mdata in modules.items():
            cells = mdata.get("cells", {})
            for cname, cdata in cells.items():
                ctype = str(cdata.get("type", "")).upper()
                if "DFF" not in ctype and "FF" not in ctype:
                    continue
                conns = cdata.get("connections", {})
                rst_bits = (
                    conns.get("R")
                    or conns.get("RST")
                    or conns.get("CLR")
                    or conns.get("PRE")
                )
                if not rst_bits:
                    continue
                nets = mdata.get("netnames", {})
                rst_name = _find_net_name(nets, rst_bits[0])
                ff_to_reset[cname] = rst_name
                ff_d[cname] = list(conns.get("D", []))
                ff_q[cname] = list(conns.get("Q", []))

            for dst_ff, d_bits in ff_d.items():
                dst_rst = ff_to_reset.get(dst_ff)
                if not dst_rst:
                    continue
                for src_ff, q_bits in ff_q.items():
                    if src_ff == dst_ff:
                        continue
                    src_rst = ff_to_reset.get(src_ff)
                    if not src_rst or src_rst == dst_rst:
                        continue
                    if any(b in q_bits for b in d_bits):
                        src_dom = next(
                            (d for d in self._domains if d.name == src_rst), None
                        )
                        dst_dom = next(
                            (d for d in self._domains if d.name == dst_rst), None
                        )
                        kind = "no_isolation"
                        if src_dom and dst_dom and src_dom.polarity != dst_dom.polarity:
                            kind = "shared_polarity_mismatch"
                        self._crossings.append(
                            RdcCrossing(
                                src_reset=src_rst,
                                dst_reset=dst_rst,
                                register=dst_ff,
                                crossing_type=kind,
                                severity="warning",
                                suggestion=(
                                    "Place an isolation cell or synchroniser "
                                    "between the two reset domains."
                                ),
                            )
                        )
        return list(self._crossings)

    def report(self) -> RdcReport:
        if not self._domains:
            self.detect_reset_domains()
        if not self._crossings:
            self.detect_crossings()
        return RdcReport(domains=list(self._domains), crossings=list(self._crossings))

    def _ensure_netlist(self) -> None:
        if self._netlist or not self._rtl:
            return
        with tempfile.TemporaryDirectory() as td:
            out_json = Path(td) / "netlist.json"
            reads = "; ".join(
                f"read_verilog -sv {str(p).replace(chr(92), '/')}" for p in self._rtl
            )
            script = (
                f"{reads}; hierarchy -top {self._top}; proc; flatten; "
                f"write_json {str(out_json).replace(chr(92), '/')}"
            )
            try:
                subprocess.run(
                    ["yosys", "-q", "-p", script],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                self._netlist = {}
                return
            try:
                self._netlist = json.loads(out_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._netlist = {}


def _find_net_name(nets: dict[str, Any], bit: Any) -> str:
    for name, info in nets.items():
        if bit in info.get("bits", []):
            return name
    return str(bit)
