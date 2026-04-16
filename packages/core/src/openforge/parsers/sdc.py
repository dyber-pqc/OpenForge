"""SDC (Synopsys Design Constraints) parser.

Parses TCL-like SDC constraint files used by OpenSTA and synthesis
tools, extracting clock definitions, I/O delays, timing exceptions,
and clock group constraints for static timing analysis.
"""

from __future__ import annotations

import contextlib
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SDCClock:
    """A clock constraint from create_clock or create_generated_clock."""

    name: str = ""
    period_ns: float = 0.0
    waveform: tuple[float, float] = (0.0, 0.0)
    source: str = ""
    generated: bool = False
    master_clock: str = ""
    divide_by: int = 1
    multiply_by: int = 1
    duty_cycle: float = 50.0
    invert: bool = False
    edges: list[int] = field(default_factory=list)
    edge_shift: list[float] = field(default_factory=list)
    comment: str = ""


@dataclass
class SDCInputDelay:
    """An input delay constraint from set_input_delay."""

    port: str = ""
    clock: str = ""
    delay_ns: float = 0.0
    min_delay_ns: float | None = None
    clock_fall: bool = False
    add_delay: bool = False


@dataclass
class SDCOutputDelay:
    """An output delay constraint from set_output_delay."""

    port: str = ""
    clock: str = ""
    delay_ns: float = 0.0
    min_delay_ns: float | None = None
    clock_fall: bool = False
    add_delay: bool = False


@dataclass
class SDCFalsePath:
    """A false path exception from set_false_path."""

    from_list: list[str] = field(default_factory=list)
    to_list: list[str] = field(default_factory=list)
    through_list: list[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class SDCMulticyclePath:
    """A multicycle path exception from set_multicycle_path."""

    from_list: list[str] = field(default_factory=list)
    to_list: list[str] = field(default_factory=list)
    through_list: list[str] = field(default_factory=list)
    setup_mult: int = 1
    hold_mult: int = 0
    comment: str = ""


@dataclass
class SDCMaxDelay:
    """A max/min delay constraint from set_max_delay / set_min_delay."""

    delay_ns: float = 0.0
    from_list: list[str] = field(default_factory=list)
    to_list: list[str] = field(default_factory=list)
    through_list: list[str] = field(default_factory=list)
    is_min: bool = False


@dataclass
class SDCClockGroup:
    """Clock grouping from set_clock_groups."""

    groups: list[list[str]] = field(default_factory=list)
    exclusive: bool = False
    asynchronous: bool = False
    physically_exclusive: bool = False


@dataclass
class SDCCaseAnalysis:
    """A case analysis setting from set_case_analysis."""

    pin: str = ""
    value: str = ""  # "0", "1", "rising", "falling"


@dataclass
class SDCData:
    """Top-level SDC constraint data."""

    clocks: list[SDCClock] = field(default_factory=list)
    input_delays: list[SDCInputDelay] = field(default_factory=list)
    output_delays: list[SDCOutputDelay] = field(default_factory=list)
    false_paths: list[SDCFalsePath] = field(default_factory=list)
    multicycle_paths: list[SDCMulticyclePath] = field(default_factory=list)
    max_delays: list[SDCMaxDelay] = field(default_factory=list)
    clock_groups: list[SDCClockGroup] = field(default_factory=list)
    case_analysis: list[SDCCaseAnalysis] = field(default_factory=list)

    def get_clock(self, name: str) -> SDCClock | None:
        """Find a clock by name."""
        for clk in self.clocks:
            if clk.name == name:
                return clk
        return None

    def clock_names(self) -> list[str]:
        """Return sorted list of clock names."""
        return sorted(c.name for c in self.clocks)


# ---------------------------------------------------------------------------
# TCL-like tokenizer
# ---------------------------------------------------------------------------

_RE_COMMENT = re.compile(r"(?:^|\s)#.*$", re.MULTILINE)
_RE_CONTINUATION = re.compile(r"\\\s*\n")
_RE_GET_EXPR = re.compile(r"\[get_(?:ports|pins|clocks|nets|cells)\s+([^\]]*)\]")


def _preprocess(text: str) -> list[str]:
    """Preprocess SDC text into logical command lines."""
    # Join continuations
    text = _RE_CONTINUATION.sub(" ", text)
    # Remove comments (but not inside brackets)
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Remove trailing comment
        comment_idx = _find_comment(stripped)
        if comment_idx >= 0:
            stripped = stripped[:comment_idx].strip()
        if stripped:
            lines.append(stripped)
    return lines


def _find_comment(line: str) -> int:
    """Find the position of a # comment outside of quotes/brackets."""
    depth = 0
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_quote = not in_quote
        elif not in_quote:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            elif ch == "#" and depth == 0:
                return i
    return -1


def _tokenize_cmd(line: str) -> list[str]:
    """Tokenize an SDC command line, handling TCL quoting."""
    try:
        return shlex.split(line)
    except ValueError:
        # Fallback for malformed quoting
        return line.split()


def _resolve_tcl_expr(token: str) -> list[str]:
    """Extract port/pin names from [get_ports ...] expressions."""
    m = _RE_GET_EXPR.search(token)
    if m:
        inner = m.group(1).strip().strip("{}")
        return re.split(r"\s+", inner)
    # Could be a bare name or brace-group
    token = token.strip("{}")
    if token:
        return re.split(r"\s+", token)
    return []


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class SDCParser:
    """Parser for SDC (Synopsys Design Constraints) files."""

    def parse(self, path: str | Path) -> SDCData:
        """Parse an SDC file and return SDCData."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"SDC file not found: {path}")

        text = path.read_text(encoding="utf-8", errors="replace")
        data = SDCData()

        for line in _preprocess(text):
            tokens = _tokenize_cmd(line)
            if not tokens:
                continue

            cmd = tokens[0]

            if cmd == "create_clock":
                clk = self._parse_create_clock(tokens[1:])
                data.clocks.append(clk)

            elif cmd == "create_generated_clock":
                clk = self._parse_create_generated_clock(tokens[1:])
                data.clocks.append(clk)

            elif cmd == "set_input_delay":
                delay = self._parse_io_delay(tokens[1:], is_input=True)
                if delay:
                    data.input_delays.append(delay)

            elif cmd == "set_output_delay":
                delay = self._parse_io_delay(tokens[1:], is_input=False)
                if delay:
                    data.output_delays.append(delay)

            elif cmd == "set_false_path":
                fp = self._parse_false_path(tokens[1:])
                data.false_paths.append(fp)

            elif cmd == "set_multicycle_path":
                mp = self._parse_multicycle_path(tokens[1:])
                data.multicycle_paths.append(mp)

            elif cmd in ("set_max_delay", "set_min_delay"):
                md = self._parse_max_delay(tokens[1:], is_min=(cmd == "set_min_delay"))
                data.max_delays.append(md)

            elif cmd == "set_clock_groups":
                cg = self._parse_clock_groups(tokens[1:])
                data.clock_groups.append(cg)

            elif cmd == "set_case_analysis":
                ca = self._parse_case_analysis(tokens[1:])
                if ca:
                    data.case_analysis.append(ca)

        return data

    # ---------------------------------------------------------------
    # Command parsers
    # ---------------------------------------------------------------

    @staticmethod
    def _parse_create_clock(args: list[str]) -> SDCClock:
        clk = SDCClock()
        i = 0
        positional_done = False
        while i < len(args):
            a = args[i]
            if a == "-name" and i + 1 < len(args):
                clk.name = args[i + 1]
                i += 2
            elif a == "-period" and i + 1 < len(args):
                clk.period_ns = _sf(args[i + 1])
                i += 2
            elif a == "-waveform" and i + 1 < len(args):
                vals = _resolve_tcl_expr(args[i + 1])
                if len(vals) >= 2:
                    clk.waveform = (_sf(vals[0]), _sf(vals[1]))
                i += 2
            elif not a.startswith("-") and not positional_done:
                # Positional argument: source port/pin or get expression
                names = _resolve_tcl_expr(a)
                if names:
                    clk.source = names[0]
                    if not clk.name:
                        clk.name = names[0]
                positional_done = True
                i += 1
            else:
                i += 1

        # Default waveform
        if clk.waveform == (0.0, 0.0) and clk.period_ns > 0:
            clk.waveform = (0.0, clk.period_ns / 2.0)

        return clk

    @staticmethod
    def _parse_create_generated_clock(args: list[str]) -> SDCClock:
        clk = SDCClock(generated=True)
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-name" and i + 1 < len(args):
                clk.name = args[i + 1]
                i += 2
            elif a == "-source" and i + 1 < len(args):
                names = _resolve_tcl_expr(args[i + 1])
                clk.source = names[0] if names else args[i + 1]
                i += 2
            elif a == "-master_clock" and i + 1 < len(args):
                clk.master_clock = args[i + 1]
                i += 2
            elif a == "-divide_by" and i + 1 < len(args):
                clk.divide_by = _si(args[i + 1])
                i += 2
            elif a == "-multiply_by" and i + 1 < len(args):
                clk.multiply_by = _si(args[i + 1])
                i += 2
            elif a == "-duty_cycle" and i + 1 < len(args):
                clk.duty_cycle = _sf(args[i + 1])
                i += 2
            elif a == "-invert":
                clk.invert = True
                i += 1
            elif a == "-edges" and i + 1 < len(args):
                vals = _resolve_tcl_expr(args[i + 1])
                clk.edges = [_si(v) for v in vals]
                i += 2
            elif a == "-edge_shift" and i + 1 < len(args):
                vals = _resolve_tcl_expr(args[i + 1])
                clk.edge_shift = [_sf(v) for v in vals]
                i += 2
            elif not a.startswith("-"):
                names = _resolve_tcl_expr(a)
                if names and not clk.source:
                    clk.source = names[0]
                i += 1
            else:
                i += 1

        return clk

    @staticmethod
    def _parse_io_delay(
        args: list[str], *, is_input: bool,
    ) -> SDCInputDelay | SDCOutputDelay | None:
        delay_val: float | None = None
        min_val: float | None = None
        clock = ""
        port = ""
        clock_fall = False
        add_delay = False
        is_max = False
        is_min = False

        i = 0
        while i < len(args):
            a = args[i]
            if a == "-clock" and i + 1 < len(args):
                names = _resolve_tcl_expr(args[i + 1])
                clock = names[0] if names else args[i + 1]
                i += 2
            elif a == "-max" and i + 1 < len(args):
                delay_val = _sf(args[i + 1])
                is_max = True
                i += 2
            elif a == "-min" and i + 1 < len(args):
                min_val = _sf(args[i + 1])
                is_min = True
                i += 2
            elif a == "-clock_fall":
                clock_fall = True
                i += 1
            elif a == "-add_delay":
                add_delay = True
                i += 1
            elif not a.startswith("-"):
                # Could be delay value or port
                names = _resolve_tcl_expr(a)
                if names:
                    # If we haven't seen a delay value yet and this looks numeric
                    if delay_val is None and not is_max and not is_min:
                        try:
                            delay_val = float(a)
                            i += 1
                            continue
                        except ValueError:
                            pass
                    port = names[0]
                i += 1
            else:
                i += 1

        if delay_val is None:
            delay_val = 0.0

        if is_input:
            return SDCInputDelay(
                port=port,
                clock=clock,
                delay_ns=delay_val,
                min_delay_ns=min_val,
                clock_fall=clock_fall,
                add_delay=add_delay,
            )
        else:
            return SDCOutputDelay(
                port=port,
                clock=clock,
                delay_ns=delay_val,
                min_delay_ns=min_val,
                clock_fall=clock_fall,
                add_delay=add_delay,
            )

    @staticmethod
    def _parse_false_path(args: list[str]) -> SDCFalsePath:
        fp = SDCFalsePath()
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-from" and i + 1 < len(args):
                fp.from_list = _resolve_tcl_expr(args[i + 1])
                i += 2
            elif a == "-to" and i + 1 < len(args):
                fp.to_list = _resolve_tcl_expr(args[i + 1])
                i += 2
            elif a == "-through" and i + 1 < len(args):
                fp.through_list.extend(_resolve_tcl_expr(args[i + 1]))
                i += 2
            else:
                i += 1
        return fp

    @staticmethod
    def _parse_multicycle_path(args: list[str]) -> SDCMulticyclePath:
        mp = SDCMulticyclePath()
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-from" and i + 1 < len(args):
                mp.from_list = _resolve_tcl_expr(args[i + 1])
                i += 2
            elif a == "-to" and i + 1 < len(args):
                mp.to_list = _resolve_tcl_expr(args[i + 1])
                i += 2
            elif a == "-through" and i + 1 < len(args):
                mp.through_list.extend(_resolve_tcl_expr(args[i + 1]))
                i += 2
            elif a == "-setup" and i + 1 < len(args):
                mp.setup_mult = _si(args[i + 1])
                i += 2
            elif a == "-hold" and i + 1 < len(args):
                mp.hold_mult = _si(args[i + 1])
                i += 2
            elif not a.startswith("-"):
                # Positional: path multiplier
                with contextlib.suppress(ValueError):
                    mp.setup_mult = int(a)
                i += 1
            else:
                i += 1
        return mp

    @staticmethod
    def _parse_max_delay(args: list[str], *, is_min: bool) -> SDCMaxDelay:
        md = SDCMaxDelay(is_min=is_min)
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-from" and i + 1 < len(args):
                md.from_list = _resolve_tcl_expr(args[i + 1])
                i += 2
            elif a == "-to" and i + 1 < len(args):
                md.to_list = _resolve_tcl_expr(args[i + 1])
                i += 2
            elif a == "-through" and i + 1 < len(args):
                md.through_list.extend(_resolve_tcl_expr(args[i + 1]))
                i += 2
            elif not a.startswith("-"):
                with contextlib.suppress(ValueError):
                    md.delay_ns = float(a)
                i += 1
            else:
                i += 1
        return md

    @staticmethod
    def _parse_clock_groups(args: list[str]) -> SDCClockGroup:
        cg = SDCClockGroup()
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-exclusive":
                cg.exclusive = True
                i += 1
            elif a == "-asynchronous":
                cg.asynchronous = True
                i += 1
            elif a == "-physically_exclusive":
                cg.physically_exclusive = True
                i += 1
            elif a == "-group" and i + 1 < len(args):
                names = _resolve_tcl_expr(args[i + 1])
                cg.groups.append(names)
                i += 2
            elif a == "-name":
                i += 2  # skip the name value
            else:
                i += 1
        return cg

    @staticmethod
    def _parse_case_analysis(args: list[str]) -> SDCCaseAnalysis | None:
        if len(args) < 2:
            return None
        value = args[0]
        pin_names = _resolve_tcl_expr(args[1]) if len(args) > 1 else []
        pin = pin_names[0] if pin_names else (args[1] if len(args) > 1 else "")
        return SDCCaseAnalysis(pin=pin, value=value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(val: str, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _si(val: str, default: int = 1) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default
