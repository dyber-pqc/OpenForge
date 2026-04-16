"""Clock Domain Crossing (CDC) analysis via structural netlist inspection."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openforge.engine.yosys import YosysEngine

if TYPE_CHECKING:
    from collections.abc import Sequence
    from os import PathLike

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClockDomain:
    """A single clock domain in the design."""

    name: str
    frequency: float = 0.0  # MHz, 0 if unknown
    source: str = ""  # SDC clock name or net name
    num_ffs: int = 0


@dataclass(frozen=True, slots=True)
class CdcCrossing:
    """A signal that crosses between two clock domains."""

    from_domain: str
    to_domain: str
    signal: str
    synchronized: bool = False
    sync_type: str = ""  # "2ff", "3ff", "fifo", "pulse", "none"


@dataclass(frozen=True, slots=True)
class CdcViolation:
    """A CDC violation (missing or inadequate synchronizer)."""

    signal: str
    from_clk: str
    to_clk: str
    severity: str = "error"  # "error", "warning", "info"
    recommendation: str = ""


@dataclass(frozen=True, slots=True)
class CdcResult:
    """Aggregate CDC analysis results."""

    crossings: list[CdcCrossing] = field(default_factory=list)
    violations: list[CdcViolation] = field(default_factory=list)
    clock_domains: list[ClockDomain] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Clock definition from SDC or user-supplied
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClockDefinition:
    """User-supplied or SDC-parsed clock definition."""

    name: str
    port_or_net: str
    period_ns: float = 0.0

    @property
    def frequency_mhz(self) -> float:
        return 1000.0 / self.period_ns if self.period_ns > 0 else 0.0


# ---------------------------------------------------------------------------
# CdcAnalyzer
# ---------------------------------------------------------------------------


class CdcAnalyzer:
    """Clock domain crossing analyzer using structural netlist inspection.

    Since Yosys does not have native CDC analysis, this performs a
    structural analysis of the synthesised netlist:

    1. Synthesise the design to a JSON netlist via Yosys.
    2. Parse the JSON to identify all flip-flops and their clock nets.
    3. Group FFs by clock domain.
    4. Trace combinational paths between FFs in different domains.
    5. Check for recognised synchroniser patterns (2-FF, 3-FF chains).

    Typical workflow::

        analyzer = CdcAnalyzer()
        result = analyzer.analyze(
            sources=["design.v"],
            top_module="top",
            clock_definitions=[
                ClockDefinition("clk_a", "clk_a", 10.0),
                ClockDefinition("clk_b", "clk_b", 20.0),
            ],
        )
        for v in result.violations:
            print(f"CDC violation: {v.signal} ({v.from_clk} -> {v.to_clk})")
    """

    def __init__(self) -> None:
        self._yosys = YosysEngine()
        self._last_output: str = ""

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(
        self,
        sources: Sequence[str | PathLike[str]],
        top_module: str,
        clock_definitions: Sequence[ClockDefinition],
        *,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> CdcResult:
        """Run CDC analysis on the given RTL sources.

        Parameters
        ----------
        sources:
            Verilog/SystemVerilog source files.
        top_module:
            Top-level module name.
        clock_definitions:
            Clock definitions mapping names to ports/nets.
        cwd:
            Working directory.
        timeout:
            Process timeout in seconds.
        """
        # Step 1: Synthesise to JSON netlist via Yosys
        netlist_json = self._synthesize_to_json(
            sources,
            top_module,
            cwd=cwd,
            timeout=timeout,
        )
        if netlist_json is None:
            return CdcResult()

        # Step 2: Parse the JSON netlist
        try:
            netlist = json.loads(netlist_json)
        except json.JSONDecodeError:
            return CdcResult()

        # Step 3: Structural CDC analysis
        return self._analyze_netlist(netlist, top_module, clock_definitions)

    # ------------------------------------------------------------------
    # Yosys synthesis to JSON
    # ------------------------------------------------------------------

    def _synthesize_to_json(
        self,
        sources: Sequence[str | PathLike[str]],
        top_module: str,
        *,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> str | None:
        """Synthesise the design and export a JSON netlist."""
        work_dir = Path(cwd) if cwd else Path.cwd()
        json_path = work_dir / ".cdc_netlist.json"

        read_cmds = " ".join(f"read_verilog {s}" for s in sources)
        yosys_script = (
            f"{read_cmds}; hierarchy -top {top_module}; proc; opt; flatten; write_json {json_path}"
        )

        result = self._yosys.run(
            ["-p", yosys_script],
            cwd=cwd,
            timeout=timeout,
        )

        self._last_output = result.stdout + result.stderr

        if json_path.exists():
            try:
                content = json_path.read_text()
                return content
            finally:
                json_path.unlink(missing_ok=True)

        return None

    # ------------------------------------------------------------------
    # Structural analysis
    # ------------------------------------------------------------------

    def _analyze_netlist(
        self,
        netlist: dict[str, Any],
        top_module: str,
        clock_defs: Sequence[ClockDefinition],
    ) -> CdcResult:
        """Perform structural CDC analysis on a Yosys JSON netlist."""

        modules = netlist.get("modules", {})
        top = modules.get(top_module, {})
        cells = top.get("cells", {})
        nets = top.get("netnames", {})

        # Build clock name -> net bit mapping
        clk_net_map: dict[str, set[int]] = {}
        for cdef in clock_defs:
            # Find the net bits for this clock port/net
            if cdef.port_or_net in nets:
                bits = nets[cdef.port_or_net].get("bits", [])
                clk_net_map[cdef.name] = {b for b in bits if isinstance(b, int)}

        # Identify all flip-flops and their clock connections
        ff_types = {
            "$dff",
            "$sdff",
            "$adff",
            "$dffe",
            "$sdffe",
            "$adffe",
            "$_DFF_P_",
            "$_DFF_N_",
            "$_DFFE_PP_",
            "$_DFFE_PN_",
            "$_SDFF_PP0_",
            "$_SDFF_PP1_",
        }

        @dataclass
        class FFInfo:
            cell_name: str
            cell_type: str
            clk_bits: set[int]
            d_bits: list[int]
            q_bits: list[int]
            clock_domain: str = ""

        flip_flops: list[FFInfo] = []

        for cell_name, cell in cells.items():
            cell_type = cell.get("type", "")
            if cell_type not in ff_types:
                continue

            connections = cell.get("connections", {})
            clk_bits_raw = connections.get("CLK", connections.get("C", []))
            d_bits = connections.get("D", [])
            q_bits = connections.get("Q", [])

            clk_bits = {b for b in clk_bits_raw if isinstance(b, int)}
            d_int = [b for b in d_bits if isinstance(b, int)]
            q_int = [b for b in q_bits if isinstance(b, int)]

            ff = FFInfo(
                cell_name=cell_name,
                cell_type=cell_type,
                clk_bits=clk_bits,
                d_bits=d_int,
                q_bits=q_int,
            )

            # Assign clock domain
            for clk_name, clk_nets in clk_net_map.items():
                if clk_bits & clk_nets:
                    ff.clock_domain = clk_name
                    break
            else:
                # Unknown clock -- assign based on net name heuristic
                ff.clock_domain = f"_unknown_{id(ff) & 0xFFFF:04x}"

            flip_flops.append(ff)

        # Group FFs by clock domain
        domain_ffs: dict[str, list[FFInfo]] = {}
        for ff in flip_flops:
            domain_ffs.setdefault(ff.clock_domain, []).append(ff)

        # Build clock domain summary
        clk_def_map = {cd.name: cd for cd in clock_defs}
        clock_domains: list[ClockDomain] = []
        for dom_name, ffs in domain_ffs.items():
            cdef = clk_def_map.get(dom_name)
            clock_domains.append(
                ClockDomain(
                    name=dom_name,
                    frequency=cdef.frequency_mhz if cdef else 0.0,
                    source=cdef.port_or_net if cdef else "",
                    num_ffs=len(ffs),
                )
            )

        # Build Q-bit -> (FF, domain) map for tracing
        q_to_domain: dict[int, tuple[FFInfo, str]] = {}
        for ff in flip_flops:
            for qb in ff.q_bits:
                q_to_domain[qb] = (ff, ff.clock_domain)

        # Find crossings: D-input of FF in domain B driven by Q of FF in domain A
        crossings: list[CdcCrossing] = []
        violations: list[CdcViolation] = []

        for ff in flip_flops:
            for db in ff.d_bits:
                # Trace back: is this bit driven by a FF in a different domain?
                # Direct connection check
                if db in q_to_domain:
                    src_ff, src_domain = q_to_domain[db]
                    if src_domain != ff.clock_domain and src_domain != ff.clock_domain:
                        # This is a clock domain crossing
                        signal_name = self._find_net_name(nets, db)

                        # Check for synchroniser pattern: is the destination FF
                        # followed by another FF in the same domain with
                        # matching D/Q chain?
                        sync_type, is_synced = self._check_synchronizer(
                            ff,
                            flip_flops,
                            q_to_domain,
                        )

                        crossing = CdcCrossing(
                            from_domain=src_domain,
                            to_domain=ff.clock_domain,
                            signal=signal_name,
                            synchronized=is_synced,
                            sync_type=sync_type,
                        )
                        crossings.append(crossing)

                        if not is_synced:
                            violations.append(
                                CdcViolation(
                                    signal=signal_name,
                                    from_clk=src_domain,
                                    to_clk=ff.clock_domain,
                                    severity="error",
                                    recommendation=(
                                        f"Add a 2-FF synchroniser for signal "
                                        f"'{signal_name}' crossing from "
                                        f"'{src_domain}' to '{ff.clock_domain}'."
                                    ),
                                )
                            )

        return CdcResult(
            crossings=crossings,
            violations=violations,
            clock_domains=clock_domains,
        )

    # ------------------------------------------------------------------
    # Synchroniser detection
    # ------------------------------------------------------------------

    def _check_synchronizer(
        self,
        dest_ff: Any,
        all_ffs: list[Any],
        q_to_domain: dict[int, tuple[Any, str]],
    ) -> tuple[str, bool]:
        """Check if dest_ff is the first stage of a synchroniser chain.

        Returns (sync_type, is_synchronized).
        """
        # A 2-FF synchroniser: dest_ff.Q feeds another FF in the same domain
        dest_q_bits = set(dest_ff.q_bits)
        chain_length = 1

        current_q = dest_q_bits
        for _ in range(3):  # Check up to 3 stages
            next_stage_found = False
            for ff in all_ffs:
                if ff is dest_ff:
                    continue
                if ff.clock_domain != dest_ff.clock_domain:
                    continue
                # Check if any D-input of ff comes from current Q
                if set(ff.d_bits) & current_q:
                    chain_length += 1
                    current_q = set(ff.q_bits)
                    next_stage_found = True
                    break
            if not next_stage_found:
                break

        if chain_length >= 3:
            return "3ff", True
        elif chain_length >= 2:
            return "2ff", True
        else:
            return "none", False

    @staticmethod
    def _find_net_name(nets: dict[str, Any], bit: int) -> str:
        """Find the net name for a given bit index."""
        for net_name, net_info in nets.items():
            bits = net_info.get("bits", [])
            if bit in bits:
                return net_name
        return f"net_{bit}"

    @property
    def last_output(self) -> str:
        """Raw Yosys output from the last analysis."""
        return self._last_output


# ===========================================================================
# Phase 11 Wave 1: Pydantic CDC API (spec-compliant)
#
# This is the structured, Pydantic-based CDC analyser used by the CDC panel.
# It coexists with the legacy dataclass API above for backwards compat.
# ===========================================================================


from pydantic import BaseModel as _PydanticBaseModel  # noqa: E402
from pydantic import Field as _Field


class ClockDomainModel(_PydanticBaseModel):
    """A clock domain detected during structural analysis."""

    name: str
    period_ns: float = 0.0
    source: str = ""
    related_domains: list[str] = _Field(default_factory=list)


class CdcCrossingModel(_PydanticBaseModel):
    """A single signal crossing between two clock domains."""

    src_signal: str
    dst_signal: str
    src_domain: str
    dst_domain: str
    crossing_type: str = "unknown"
    has_synchronizer: bool = False
    sync_depth: int = 0
    severity: str = "warning"
    suggestion: str = ""


class CdcReport(_PydanticBaseModel):
    """Aggregate CDC report returned by :class:`CdcChecker`."""

    domains: list[ClockDomainModel] = _Field(default_factory=list)
    crossings: list[CdcCrossingModel] = _Field(default_factory=list)
    safe_count: int = 0
    unsafe_count: int = 0


class CdcChecker:
    """Structural CDC checker driven by yosys netlist JSON.

    Call :meth:`detect_clock_domains` then :meth:`detect_crossings` then
    :meth:`report` (or just :meth:`report` which runs the full pipeline).
    """

    _SYNC_REGEX = re.compile(r"sync|meta|cdc|xdomain|ff2", re.IGNORECASE)
    _GRAY_REGEX = re.compile(r"gray|gry", re.IGNORECASE)
    _FIFO_REGEX = re.compile(r"fifo|async_fifo", re.IGNORECASE)
    _HANDSHAKE_REGEX = re.compile(r"req|ack|handshake", re.IGNORECASE)

    def __init__(
        self,
        rtl_files: list[Path] | list[str],
        top: str,
        sdc: Path | None = None,
    ) -> None:
        self._rtl = [Path(p) for p in rtl_files]
        self._top = top
        self._sdc = Path(sdc) if sdc else None
        self._domains: list[ClockDomainModel] = []
        self._crossings: list[CdcCrossingModel] = []
        self._netlist: dict[str, Any] = {}

    # -- clock domains -------------------------------------------------

    def detect_clock_domains(self) -> list[ClockDomainModel]:
        """Detect clock domains by running yosys and walking the netlist."""
        self._ensure_netlist()
        clock_sources: dict[str, int] = {}
        modules = self._netlist.get("modules", {})
        for _mname, mdata in modules.items():
            cells = mdata.get("cells", {})
            nets = mdata.get("netnames", {})
            for _cname, cdata in cells.items():
                ctype = str(cdata.get("type", ""))
                if "DFF" not in ctype.upper() and "FF" not in ctype.upper():
                    continue
                conns = cdata.get("connections", {})
                clk_bits = conns.get("C") or conns.get("CLK") or conns.get("clk")
                if not clk_bits:
                    continue
                name = _find_net_name_top(nets, clk_bits[0]) if clk_bits else "clk"
                clock_sources[name] = clock_sources.get(name, 0) + 1

        # Parse SDC for periods.
        periods: dict[str, float] = {}
        if self._sdc and self._sdc.exists():
            try:
                sdc_text = self._sdc.read_text(encoding="utf-8", errors="replace")
            except OSError:
                sdc_text = ""
            for line in sdc_text.splitlines():
                m = re.search(r"create_clock.*?-period\s+([\d.]+).*?-name\s+(\w+)", line)
                if m:
                    periods[m.group(2)] = float(m.group(1))
                else:
                    m = re.search(r"create_clock.*?-name\s+(\w+).*?-period\s+([\d.]+)", line)
                    if m:
                        periods[m.group(1)] = float(m.group(2))

        self._domains = [
            ClockDomainModel(
                name=name,
                period_ns=periods.get(name, 0.0),
                source=name,
                related_domains=[],
            )
            for name in sorted(clock_sources.keys())
        ]
        return list(self._domains)

    # -- crossings -----------------------------------------------------

    def detect_crossings(self) -> list[CdcCrossingModel]:
        """Walk the flattened netlist and detect signals that cross domains."""
        if not self._domains:
            self.detect_clock_domains()
        self._ensure_netlist()

        # Build FF -> clock map.
        ff_to_clock: dict[str, str] = {}
        ff_data_bits: dict[str, list[int]] = {}
        ff_q_bits: dict[str, list[int]] = {}
        modules = self._netlist.get("modules", {})
        for _mname, mdata in modules.items():
            cells = mdata.get("cells", {})
            nets = mdata.get("netnames", {})
            for cname, cdata in cells.items():
                ctype = str(cdata.get("type", ""))
                if "DFF" not in ctype.upper() and "FF" not in ctype.upper():
                    continue
                conns = cdata.get("connections", {})
                clk_bits = conns.get("C") or conns.get("CLK") or conns.get("clk")
                if not clk_bits:
                    continue
                clk_name = _find_net_name_top(nets, clk_bits[0])
                ff_to_clock[cname] = clk_name
                d_bits = conns.get("D") or conns.get("d") or []
                q_bits = conns.get("Q") or conns.get("q") or []
                ff_data_bits[cname] = list(d_bits)
                ff_q_bits[cname] = list(q_bits)

            # For each FF, find the FF whose Q drives this FF's D.
            for ff_name, d_bits in ff_data_bits.items():
                dst_clk = ff_to_clock.get(ff_name)
                if not dst_clk:
                    continue
                for src_name, q_bits in ff_q_bits.items():
                    if src_name == ff_name:
                        continue
                    src_clk = ff_to_clock.get(src_name)
                    if not src_clk or src_clk == dst_clk:
                        continue
                    if any(b in q_bits for b in d_bits):
                        kind, sync, depth = self._classify(ff_name, src_name)
                        safe = kind in (
                            "two_ff_sync",
                            "handshake",
                            "fifo",
                            "gray_counter",
                            "mux_sync",
                        )
                        self._crossings.append(
                            CdcCrossingModel(
                                src_signal=_net_from_bits(nets, q_bits) or src_name,
                                dst_signal=_net_from_bits(nets, d_bits) or ff_name,
                                src_domain=src_clk,
                                dst_domain=dst_clk,
                                crossing_type=kind,
                                has_synchronizer=sync,
                                sync_depth=depth,
                                severity="info" if safe else "critical",
                                suggestion=self._suggestion(kind),
                            )
                        )
        return list(self._crossings)

    def _classify(self, dst_ff: str, src_ff: str) -> tuple[str, bool, int]:
        name = f"{dst_ff} {src_ff}".lower()
        if self._GRAY_REGEX.search(name):
            return "gray_counter", True, 2
        if self._FIFO_REGEX.search(name):
            return "fifo", True, 2
        if self._HANDSHAKE_REGEX.search(name):
            return "handshake", True, 2
        if self._SYNC_REGEX.search(name):
            return "two_ff_sync", True, 2
        return "unsynchronized", False, 0

    @staticmethod
    def _suggestion(kind: str) -> str:
        return {
            "unsynchronized": "Insert a 2-FF synchroniser on the destination clock.",
            "two_ff_sync": "Ensure the synchroniser depth is at least 2 for MTBF.",
            "handshake": "Verify the req/ack protocol handles backpressure.",
            "fifo": "Confirm the async FIFO pointers use gray coding.",
            "gray_counter": "Confirm the gray->bin decode sits in the destination domain.",
            "mux_sync": "Confirm the select line is stable for >= 2 destination cycles.",
            "unknown": "Review this crossing manually.",
        }.get(kind, "Review this crossing manually.")

    # -- report --------------------------------------------------------

    def report(self) -> CdcReport:
        if not self._domains:
            self.detect_clock_domains()
        if not self._crossings:
            self.detect_crossings()
        safe = sum(1 for c in self._crossings if c.has_synchronizer)
        return CdcReport(
            domains=list(self._domains),
            crossings=list(self._crossings),
            safe_count=safe,
            unsafe_count=len(self._crossings) - safe,
        )

    def to_html(self, path: Path) -> None:
        """Emit a simple HTML report to ``path``."""
        rep = self.report()
        rows = "".join(
            (
                f"<tr class='{c.severity}'>"
                f"<td>{c.src_signal}</td><td>{c.dst_signal}</td>"
                f"<td>{c.src_domain}</td><td>{c.dst_domain}</td>"
                f"<td>{c.crossing_type}</td><td>{c.severity}</td>"
                f"<td>{c.suggestion}</td>"
                "</tr>"
            )
            for c in rep.crossings
        )
        domain_rows = "".join(
            f"<tr><td>{d.name}</td><td>{d.period_ns:.2f}</td><td>{d.source}</td></tr>"
            for d in rep.domains
        )
        html = (
            "<html><head><title>CDC Report</title>"
            "<style>"
            "body{font-family:sans-serif;background:#1e1e2e;color:#cdd6f4;}"
            "table{border-collapse:collapse;width:100%;margin-bottom:2em;}"
            "th,td{border:1px solid #45475a;padding:6px;text-align:left;}"
            "tr.critical{background:#f38ba8;color:#1e1e2e;}"
            "tr.warning{background:#f9e2af;color:#1e1e2e;}"
            "tr.info{background:#a6e3a1;color:#1e1e2e;}"
            "</style></head><body>"
            f"<h1>CDC Report: {self._top}</h1>"
            f"<p>safe={rep.safe_count} unsafe={rep.unsafe_count}</p>"
            "<h2>Clock domains</h2>"
            "<table><tr><th>name</th><th>period ns</th><th>source</th></tr>"
            f"{domain_rows}</table>"
            "<h2>Crossings</h2>"
            "<table><tr><th>src</th><th>dst</th><th>src domain</th>"
            "<th>dst domain</th><th>type</th><th>severity</th>"
            f"<th>suggestion</th></tr>{rows}</table>"
            "</body></html>"
        )
        Path(path).write_text(html, encoding="utf-8")

    # -- internals -----------------------------------------------------

    def _ensure_netlist(self) -> None:
        if self._netlist:
            return
        if not self._rtl:
            return
        with tempfile.TemporaryDirectory() as td:
            out_json = Path(td) / "netlist.json"
            read_cmds = "; ".join(
                f"read_verilog -sv {str(p).replace(chr(92), '/')}" for p in self._rtl
            )
            script = (
                f"{read_cmds}; hierarchy -top {self._top}; "
                f"proc; flatten; write_json {str(out_json).replace(chr(92), '/')}"
            )
            try:
                subprocess.run(
                    ["yosys", "-q", "-p", script],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # Yosys unavailable -- leave netlist empty; detect_* become no-ops.
                self._netlist = {}
                return
            try:
                self._netlist = json.loads(out_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._netlist = {}


def _find_net_name_top(nets: dict[str, Any], bit: Any) -> str:
    for net_name, net_info in nets.items():
        bits = net_info.get("bits", [])
        if bit in bits:
            return net_name
    return str(bit)


def _net_from_bits(nets: dict[str, Any], bits: list[Any]) -> str:
    if not bits:
        return ""
    return _find_net_name_top(nets, bits[0])


# Public Pydantic aliases used by the spec (CDC panel imports these).
ClockDomainV2 = ClockDomainModel
CdcCrossingV2 = CdcCrossingModel
