"""Parse OpenSTA ``report_checks`` text output into structured timing data.

This module converts the human-readable reports produced by OpenSTA's
``report_checks`` command into rich Python dataclasses suitable for driving
GUI panels (path browser, timing summary, slack histograms) and downstream
analysis (cross-probing into the layout viewer, RTL editor jumps, etc.).

It is intentionally lenient: OpenSTA reports vary considerably across path
types (setup vs hold, async/recovery/removal checks, multiple corners, paths
with input external delays, paths missing edge markers) and we want to
recover as much as possible without throwing.

Example
-------
>>> from openforge.physical.sta_parser import parse_sta_report
>>> report = parse_sta_report(open('reports/sta.rpt').read())
>>> print(report.wns, report.tns)
>>> for p in report.violating_paths():
...     print(p.endpoint, p.slack_ns)
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TimingStage:
    """A single stage in a timing path - one cell or pin traversal."""

    delay_ns: float = 0.0
    cumulative_ns: float = 0.0
    edge: str = "rise"  # "rise" (^) or "fall" (v)
    pin_name: str = ""  # e.g. "u_alu/and1/A"
    cell_type: str = ""  # e.g. "sky130_fd_sc_hd__and2_1"
    cell_instance: str = ""  # e.g. "u_alu/and1"
    description: str = ""
    is_clock_edge: bool = False
    is_input_external: bool = False
    is_clock_network: bool = False
    is_setup_hold: bool = False  # library setup/hold time line
    slew_ns: float = 0.0
    cap_pf: float = 0.0
    fanout: int = 0

    @property
    def is_register(self) -> bool:
        ct = self.cell_type.lower()
        return any(tok in ct for tok in ("dff", "dlxtp", "dlrtp", "latch", "sdff"))

    @property
    def is_buffer(self) -> bool:
        ct = self.cell_type.lower()
        return ct.startswith("buf") or "__buf" in ct or "__inv" in ct

    @property
    def short_pin(self) -> str:
        """Just the pin name (after last '/')."""
        if "/" in self.pin_name:
            return self.pin_name.rsplit("/", 1)[1]
        return self.pin_name


@dataclass
class TimingPath:
    """A complete timing path from startpoint to endpoint."""

    startpoint: str = ""
    endpoint: str = ""
    startpoint_clock: str = ""
    endpoint_clock: str = ""
    startpoint_clock_edge: str = "rise"
    endpoint_clock_edge: str = "rise"
    path_group: str = ""
    path_type: str = "max"  # "max" (setup), "min" (hold), recovery, removal...
    check_type: str = ""  # setup, hold, recovery, removal, etc.
    corner: str = ""

    data_arrival_ns: float = 0.0
    data_required_ns: float = 0.0
    slack_ns: float = 0.0

    launch_clock_path: list[TimingStage] = field(default_factory=list)
    data_path: list[TimingStage] = field(default_factory=list)
    capture_clock_path: list[TimingStage] = field(default_factory=list)

    raw_text: str = ""  # original text block, useful for debugging / display

    # ----- convenience properties -----------------------------------------

    @property
    def status(self) -> str:
        return "MET" if self.slack_ns >= 0 else "VIOLATED"

    @property
    def is_violated(self) -> bool:
        return self.slack_ns < 0

    @property
    def num_levels(self) -> int:
        """Number of logic levels (gates that aren't flip-flops) in data path."""
        return len(
            [s for s in self.data_path if s.cell_type and not s.is_register and not s.is_clock_edge]
        )

    @property
    def total_delay(self) -> float:
        return self.data_arrival_ns

    @property
    def all_stages(self) -> list[TimingStage]:
        """Return launch + data + capture stages joined."""
        return [*self.launch_clock_path, *self.data_path, *self.capture_clock_path]

    def cell_instances(self) -> list[str]:
        """Return unique cell instance names in the data path, in order."""
        seen: set[str] = set()
        out: list[str] = []
        for s in self.data_path:
            if s.cell_instance and s.cell_instance not in seen:
                seen.add(s.cell_instance)
                out.append(s.cell_instance)
        return out

    def cell_delay_ns(self) -> float:
        """Sum of cell-driven delays (rough heuristic)."""
        return sum(s.delay_ns for s in self.data_path if s.cell_type)


@dataclass
class ClockInfo:
    """Definition of a clock parsed from an SDC or report."""

    name: str
    period_ns: float
    source_pins: list[str] = field(default_factory=list)
    waveform: tuple[float, float] = (0.0, 5.0)  # (rise, fall)
    is_generated: bool = False

    @property
    def frequency_mhz(self) -> float:
        return 1000.0 / self.period_ns if self.period_ns > 0 else 0.0


@dataclass
class StaReport:
    """Complete STA report parsed from OpenSTA output."""

    paths: list[TimingPath] = field(default_factory=list)
    clocks: list[ClockInfo] = field(default_factory=list)
    wns: float = 0.0  # worst negative slack (setup)
    tns: float = 0.0  # total negative slack (setup)
    whs: float = 0.0  # worst hold slack
    ths: float = 0.0  # total hold slack
    num_violations: int = 0
    num_endpoints: int = 0
    num_paths: int = 0
    raw_text: str = ""

    # ----- queries --------------------------------------------------------

    def violating_paths(self) -> list[TimingPath]:
        return [p for p in self.paths if p.slack_ns < 0]

    def setup_paths(self) -> list[TimingPath]:
        return [p for p in self.paths if p.path_type == "max"]

    def hold_paths(self) -> list[TimingPath]:
        return [p for p in self.paths if p.path_type == "min"]

    def critical_path(self) -> TimingPath | None:
        if not self.paths:
            return None
        return min(self.paths, key=lambda p: p.slack_ns)

    def paths_by_clock(self) -> dict[str, list[TimingPath]]:
        result: dict[str, list[TimingPath]] = {}
        for p in self.paths:
            key = p.endpoint_clock or p.startpoint_clock or "unclocked"
            result.setdefault(key, []).append(p)
        return result

    def paths_by_endpoint(self) -> dict[str, list[TimingPath]]:
        result: dict[str, list[TimingPath]] = {}
        for p in self.paths:
            key = p.endpoint or "?"
            result.setdefault(key, []).append(p)
        return result

    def get_clock(self, name: str) -> ClockInfo | None:
        for c in self.clocks:
            if c.name == name:
                return c
        return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


# Regex used to parse a single stage line.
# OpenSTA may emit columns like:
#   "   Delay      Time   Description"
# or with more columns when -fields slew/cap/input_pins/nets is used:
#   "    Cap    Slew   Delay    Time   Description"
# We try the longer-form first and fall back to the shorter one.
_NUM = r"[-+]?\d+\.?\d*"
_STAGE_RE_LONG = re.compile(
    r"^\s*(?P<cap>" + _NUM + r")\s+(?P<slew>" + _NUM + r")\s+"
    r"(?P<delay>" + _NUM + r")\s+(?P<time>" + _NUM + r")\s*"
    r"(?P<edge>[v^])?\s*(?P<rest>.*)$"
)
_STAGE_RE_MED = re.compile(
    r"^\s*(?P<slew>" + _NUM + r")\s+(?P<delay>" + _NUM + r")\s+(?P<time>" + _NUM + r")\s*"
    r"(?P<edge>[v^])?\s*(?P<rest>.*)$"
)
_STAGE_RE_SHORT = re.compile(
    r"^\s*(?P<delay>" + _NUM + r")\s+(?P<time>" + _NUM + r")\s*"
    r"(?P<edge>[v^])?\s*(?P<rest>.*)$"
)

_PIN_CELL_RE = re.compile(r"^(?P<pin>\S+)(?:\s+\((?P<cell>[^)]+)\))?\s*$")

_STARTPOINT_RE = re.compile(
    r"Startpoint:\s+(?P<pin>\S+)"
    r"(?:\s+\(.*?clocked\s+by\s+(?P<clk>\S+?)(?:\s+(?P<edge>rise|fall))?[^)]*\))?"
)
_ENDPOINT_RE = re.compile(
    r"Endpoint:\s+(?P<pin>\S+)"
    r"(?:\s+\(.*?(?:clocked\s+by|against\s+(?:rising|falling)-edge\s+clock)\s+(?P<clk>\S+?)(?:\s+(?P<edge>rise|fall))?[^)]*\))?"
)


def _looks_like_separator(line: str) -> bool:
    s = line.strip()
    return bool(s) and set(s) <= {"-", "="}


def _is_column_header(line: str) -> bool:
    low = line.lower()
    if "description" not in low:
        return False
    return any(tok in low for tok in ("delay", "time", "slew", "cap"))


def _parse_stage_line(line: str) -> TimingStage | None:
    """Try to parse a single stage line into a :class:`TimingStage`.

    Returns ``None`` if the line doesn't look like a stage row.
    """
    # Skip headers and blank lines.
    if not line.strip() or _looks_like_separator(line) or _is_column_header(line):
        return None

    stage: TimingStage | None = None
    rest = ""
    cap = slew = 0.0

    m = _STAGE_RE_LONG.match(line)
    if m:
        try:
            cap = float(m.group("cap"))
            slew = float(m.group("slew"))
            delay = float(m.group("delay"))
            time = float(m.group("time"))
        except ValueError:
            return None
        edge = m.group("edge")
        rest = (m.group("rest") or "").strip()
        stage = TimingStage(
            delay_ns=delay,
            cumulative_ns=time,
            edge="rise" if edge == "^" else ("fall" if edge == "v" else "rise"),
            cap_pf=cap,
            slew_ns=slew,
        )
    else:
        m = _STAGE_RE_MED.match(line)
        if m:
            # Could collide with the SHORT pattern; verify there's a 3rd number.
            try:
                slew = float(m.group("slew"))
                delay = float(m.group("delay"))
                time = float(m.group("time"))
            except ValueError:
                return None
            edge = m.group("edge")
            rest = (m.group("rest") or "").strip()
            stage = TimingStage(
                delay_ns=delay,
                cumulative_ns=time,
                edge="rise" if edge == "^" else ("fall" if edge == "v" else "rise"),
                slew_ns=slew,
            )
        else:
            m = _STAGE_RE_SHORT.match(line)
            if not m:
                return None
            try:
                delay = float(m.group("delay"))
                time = float(m.group("time"))
            except ValueError:
                return None
            edge = m.group("edge")
            rest = (m.group("rest") or "").strip()
            stage = TimingStage(
                delay_ns=delay,
                cumulative_ns=time,
                edge="rise" if edge == "^" else ("fall" if edge == "v" else "rise"),
            )

    if stage is None:
        return None

    # Description side: "u_alu/and1/A (sky130_fd_sc_hd__and2_1)" or
    # "clock clk (rise edge)" or "library setup time" etc.
    rest_low = rest.lower()
    stage.description = rest

    if not rest:
        return stage

    if "clock" in rest_low and ("edge" in rest_low or "(" in rest_low and "rise" in rest_low):
        stage.is_clock_edge = True
    if "clock network delay" in rest_low:
        stage.is_clock_network = True
    if "input external delay" in rest_low:
        stage.is_input_external = True
    if "library setup time" in rest_low or "library hold time" in rest_low:
        stage.is_setup_hold = True
    if "library recovery time" in rest_low or "library removal time" in rest_low:
        stage.is_setup_hold = True
    if "data arrival time" in rest_low or "data required time" in rest_low:
        return None  # not a stage, sentinel handled by caller
    if "slack" in rest_low:
        return None

    pin_cell_m = _PIN_CELL_RE.match(rest)
    if pin_cell_m:
        pin = pin_cell_m.group("pin") or ""
        cell = pin_cell_m.group("cell") or ""
        # Heuristic: pin must contain a "/" or look like a port name.
        if pin and not pin.startswith("("):
            stage.pin_name = pin
            stage.cell_type = cell
            if "/" in pin:
                stage.cell_instance = pin.rsplit("/", 1)[0]
            elif cell:
                stage.cell_instance = pin

    return stage


def _classify_check(line: str) -> tuple[str, str]:
    """Return ``(path_type, check_type)`` based on a Path Type / Endpoint line."""
    low = line.lower()
    if "max" in low or "setup" in low:
        return "max", "setup"
    if "min" in low or "hold" in low:
        return "min", "hold"
    if "recovery" in low:
        return "max", "recovery"
    if "removal" in low:
        return "min", "removal"
    return "max", "setup"


def parse_sta_report(report_text: str) -> StaReport:
    """Parse OpenSTA ``report_checks`` text output into a :class:`StaReport`.

    The parser is line-based and accumulates one path at a time, switching
    between launch-clock / data / capture-clock sections as it sees clock
    edges and the first non-clock data stage.
    """
    report = StaReport(raw_text=report_text)
    if not report_text:
        return report

    lines = report_text.splitlines()
    current: TimingPath | None = None
    section = "launch_clock"  # launch_clock | data | capture_clock
    block_lines: list[str] = []

    def _finalize_current() -> None:
        nonlocal current, block_lines
        if current is not None:
            current.raw_text = "\n".join(block_lines)
            report.paths.append(current)
        current = None
        block_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()

        # New path?
        m_start = _STARTPOINT_RE.search(line)
        if m_start:
            _finalize_current()
            current = TimingPath()
            current.startpoint = m_start.group("pin")
            if m_start.group("clk"):
                current.startpoint_clock = m_start.group("clk")
            if m_start.group("edge"):
                current.startpoint_clock_edge = m_start.group("edge")
            section = "launch_clock"
            block_lines = [line]
            continue

        if current is None:
            continue
        block_lines.append(line)

        m_end = _ENDPOINT_RE.search(line)
        if m_end:
            current.endpoint = m_end.group("pin")
            if m_end.group("clk"):
                current.endpoint_clock = m_end.group("clk")
            if m_end.group("edge"):
                current.endpoint_clock_edge = m_end.group("edge")
            low = line.lower()
            if "recovery" in low:
                current.path_type, current.check_type = "max", "recovery"
            elif "removal" in low:
                current.path_type, current.check_type = "min", "removal"
            elif "hold" in low:
                current.path_type, current.check_type = "min", "hold"
            continue

        if line.startswith("Path Group:"):
            current.path_group = line.split(":", 1)[1].strip()
            continue

        if line.startswith("Path Type:"):
            ptxt = line.split(":", 1)[1].strip()
            current.path_type, current.check_type = _classify_check(ptxt)
            continue

        if line.startswith("Corner:"):
            current.corner = line.split(":", 1)[1].strip()
            continue

        # Sentinel lines for arrival / required / slack.
        low = line.lower()
        if "data arrival time" in low:
            m = re.search(r"(" + _NUM + r")\s+data arrival time", line)
            if m:
                with contextlib.suppress(ValueError):
                    current.data_arrival_ns = float(m.group(1))
            # Anything coming next is the capture clock section.
            section = "capture_clock"
            continue

        if "data required time" in low:
            m = re.search(r"(" + _NUM + r")\s+data required time", line)
            if m:
                with contextlib.suppress(ValueError):
                    current.data_required_ns = float(m.group(1))
            continue

        if "slack" in low and ("met" in low or "violated" in low or re.search(_NUM, line)):
            m = re.search(r"(" + _NUM + r")\s*(?:ns)?\s*slack", line)
            if not m:
                m = re.search(r"slack\s*\(\w+\)\s*(" + _NUM + r")", line)
            if not m:
                m = re.search(_NUM, line)
            if m:
                with contextlib.suppress(ValueError):
                    current.slack_ns = float(m.group(1) if m.lastindex else m.group(0))
            continue

        # Otherwise try to parse this as a stage row.
        stage = _parse_stage_line(line)
        if stage is None:
            continue

        # Section transitions: first non-clock-edge stage with a real cell
        # type promotes us to the data section.
        if section == "launch_clock" and (
            stage.cell_type and not stage.is_clock_edge and not stage.is_clock_network
        ):
            section = "data"

        if section == "launch_clock":
            current.launch_clock_path.append(stage)
        elif section == "data":
            # End-of-data is signalled by hitting "data arrival time", handled above.
            current.data_path.append(stage)
        else:  # capture_clock
            current.capture_clock_path.append(stage)

    _finalize_current()

    _compute_summary(report)
    return report


def _compute_summary(report: StaReport) -> None:
    """Fill in WNS / TNS / counts on the report from its paths."""
    report.num_paths = len(report.paths)
    if not report.paths:
        return

    setup = report.setup_paths()
    if setup:
        report.wns = min(p.slack_ns for p in setup)
        report.tns = sum(p.slack_ns for p in setup if p.slack_ns < 0)

    hold = report.hold_paths()
    if hold:
        report.whs = min(p.slack_ns for p in hold)
        report.ths = sum(p.slack_ns for p in hold if p.slack_ns < 0)

    report.num_violations = sum(1 for p in report.paths if p.slack_ns < 0)
    report.num_endpoints = len({p.endpoint for p in report.paths if p.endpoint})


def parse_sta_report_file(report_path: str | Path) -> StaReport:
    """Parse an STA report from a file."""
    p = Path(report_path)
    return parse_sta_report(p.read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Clock parsing helpers
# ---------------------------------------------------------------------------


_CREATE_CLOCK_RE = re.compile(
    r"create_clock\s+(?:-name\s+(\S+)\s+)?"
    r"(?:.*?-period\s+([\d.]+))?"
    r"(?:.*?-waveform\s+\{\s*([\d.]+)\s+([\d.]+)\s*\})?"
    r"(?:.*?\[get_(?:ports|pins)\s+([^\]]+)\])?",
    re.IGNORECASE,
)


def parse_sdc_clocks(sdc_text: str) -> list[ClockInfo]:
    """Best-effort extract :class:`ClockInfo` definitions from an SDC file."""
    clocks: list[ClockInfo] = []
    for line in sdc_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("create_clock") and not line.startswith("create_generated_clock"):
            continue
        m = _CREATE_CLOCK_RE.search(line)
        if not m:
            continue
        name = m.group(1) or "clk"
        try:
            period = float(m.group(2)) if m.group(2) else 10.0
        except ValueError:
            period = 10.0
        try:
            wave = (float(m.group(3)), float(m.group(4))) if m.group(3) else (0.0, period / 2)
        except ValueError:
            wave = (0.0, period / 2)
        src = m.group(5).strip() if m.group(5) else ""
        clocks.append(
            ClockInfo(
                name=name,
                period_ns=period,
                source_pins=[src] if src else [],
                waveform=wave,
                is_generated=line.startswith("create_generated_clock"),
            )
        )
    return clocks


def attach_clocks(report: StaReport, clocks: Iterable[ClockInfo]) -> None:
    """Attach a sequence of :class:`ClockInfo` definitions to ``report``."""
    existing = {c.name for c in report.clocks}
    for c in clocks:
        if c.name not in existing:
            report.clocks.append(c)
            existing.add(c.name)


__all__ = [
    "TimingStage",
    "TimingPath",
    "ClockInfo",
    "StaReport",
    "parse_sta_report",
    "parse_sta_report_file",
    "parse_sdc_clocks",
    "attach_clocks",
]
