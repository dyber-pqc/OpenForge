"""Parser and writer for Xilinx XDC (Xilinx Design Constraints) files.

XDC is a subset of Tcl used by Vivado and SymbiFlow/F4PGA to specify
pin assignments, I/O standards, clock definitions and timing
constraints. This module provides a pragmatic, regex-based parser that
understands the most common constructs produced by board vendors and
the F4PGA ecosystem.

The parser is intentionally lenient: unknown commands are preserved
as raw :class:`XdcConstraint` entries so that round-tripping through
:func:`write_xdc` does not lose information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class XdcConstraint:
    """A single raw constraint line with its source metadata."""

    type: str
    raw: str
    line: int = 0


@dataclass(slots=True)
class XdcPinAssignment:
    """Mapping from an RTL port to a physical FPGA pin."""

    port: str
    pin: str
    iostandard: str = "LVCMOS33"
    drive: int = 12
    slew: str = "SLOW"
    pullup: bool = False
    pulldown: bool = False
    pulltype: str | None = None
    comment: str = ""

    def to_xdc_lines(self) -> list[str]:
        """Render this assignment as one or more XDC text lines."""
        port_sel = f"[get_ports {{{self.port}}}]"
        lines: list[str] = []
        if self.comment:
            lines.append(f"# {self.comment}")
        lines.append(f"set_property PACKAGE_PIN {self.pin} {port_sel}")
        lines.append(f"set_property IOSTANDARD {self.iostandard} {port_sel}")
        if self.drive:
            lines.append(f"set_property DRIVE {self.drive} {port_sel}")
        if self.slew and self.slew.upper() != "SLOW":
            lines.append(f"set_property SLEW {self.slew} {port_sel}")
        if self.pullup:
            lines.append(f"set_property PULLUP TRUE {port_sel}")
        elif self.pulldown:
            lines.append(f"set_property PULLDOWN TRUE {port_sel}")
        elif self.pulltype:
            lines.append(f"set_property PULLTYPE {self.pulltype} {port_sel}")
        return lines


@dataclass(slots=True)
class XdcClockDef:
    """A ``create_clock`` constraint."""

    name: str
    source_port: str
    period_ns: float
    duty_cycle: float = 50.0
    waveform: tuple[float, float] | None = None

    @property
    def frequency_mhz(self) -> float:
        return 1000.0 / self.period_ns if self.period_ns else 0.0

    def to_xdc_line(self) -> str:
        parts = [
            "create_clock",
            f"-period {self.period_ns:.3f}",
            f"-name {self.name}",
        ]
        if self.waveform is not None:
            rise, fall = self.waveform
            parts.append(f"-waveform {{{rise:.3f} {fall:.3f}}}")
        parts.append(f"[get_ports {{{self.source_port}}}]")
        return " ".join(parts)


@dataclass(slots=True)
class XdcIoDelay:
    """``set_input_delay`` / ``set_output_delay`` constraint."""

    kind: str  # "input" or "output"
    port: str
    clock: str
    delay_ns: float
    max_min: str = "max"


@dataclass(slots=True)
class XdcFalsePath:
    from_pins: list[str] = field(default_factory=list)
    to_pins: list[str] = field(default_factory=list)


@dataclass(slots=True)
class XdcFile:
    """In-memory representation of an XDC file."""

    pin_assignments: list[XdcPinAssignment] = field(default_factory=list)
    clocks: list[XdcClockDef] = field(default_factory=list)
    io_delays: list[XdcIoDelay] = field(default_factory=list)
    false_paths: list[XdcFalsePath] = field(default_factory=list)
    raw_constraints: list[XdcConstraint] = field(default_factory=list)
    file_path: Path | None = None

    # ------------------------------------------------------------------

    def find_port(self, port: str) -> XdcPinAssignment | None:
        for pa in self.pin_assignments:
            if pa.port == port:
                return pa
        return None

    def upsert_pin(self, assignment: XdcPinAssignment) -> None:
        """Add or update a pin assignment, keyed by port name."""
        existing = self.find_port(assignment.port)
        if existing is None:
            self.pin_assignments.append(assignment)
            return
        # Update in place
        existing.pin = assignment.pin
        existing.iostandard = assignment.iostandard
        existing.drive = assignment.drive
        existing.slew = assignment.slew
        existing.pullup = assignment.pullup
        existing.pulldown = assignment.pulldown
        existing.pulltype = assignment.pulltype

    def ports(self) -> list[str]:
        return [p.port for p in self.pin_assignments]


# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------


_PORT_RE = re.compile(r"get_ports\s*\{?\s*([^\}\]\s]+)\s*\}?", re.IGNORECASE)
_BRACE_RE = re.compile(r"\{([^{}]*)\}")


def _strip_comment(line: str) -> tuple[str, str]:
    """Split a line into (code, comment)."""
    # A '#' preceded by whitespace or at column 0 starts a comment.
    idx = -1
    in_brace = 0
    for i, ch in enumerate(line):
        if ch == "{":
            in_brace += 1
        elif ch == "}":
            in_brace = max(0, in_brace - 1)
        elif ch == "#" and in_brace == 0 and (i == 0 or line[i - 1] in " \t"):
            idx = i
            break
    if idx < 0:
        return line, ""
    return line[:idx], line[idx + 1 :].strip()


def _extract_port(text: str) -> str | None:
    if m := _PORT_RE.search(text):
        return m.group(1).strip("{} ")
    return None


def _extract_value(text: str, keyword: str) -> str | None:
    """Pull the token immediately following ``keyword`` in a set_property line."""
    pattern = re.compile(rf"set_property\s+{re.escape(keyword)}\s+([^\s\[]+)", re.IGNORECASE)
    if m := pattern.search(text):
        return m.group(1).strip("{}")
    return None


def _join_continuations(lines: list[str]) -> list[tuple[int, str]]:
    """Join Tcl backslash-continued lines and keep original line numbers."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 0
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.rstrip("\n")
        if stripped.endswith("\\"):
            if not buf:
                start = idx
            buf.append(stripped[:-1])
            continue
        if buf:
            buf.append(stripped)
            out.append((start, " ".join(buf)))
            buf.clear()
        else:
            out.append((idx, stripped))
    if buf:
        out.append((start, " ".join(buf)))
    return out


# ---------------------------------------------------------------------------
# Public parsing API
# ---------------------------------------------------------------------------


def parse_xdc(filepath: str | Path) -> XdcFile:
    """Parse a Xilinx XDC file into an :class:`XdcFile` object."""
    path = Path(filepath)
    text = path.read_text(errors="replace")
    xdc = parse_xdc_text(text)
    xdc.file_path = path
    return xdc


def parse_xdc_text(text: str) -> XdcFile:
    """Parse XDC content given as a string."""
    xdc = XdcFile()
    pin_map: dict[str, XdcPinAssignment] = {}
    pending_comment = ""

    lines = _join_continuations(text.splitlines())

    for lineno, raw in lines:
        code, comment = _strip_comment(raw)
        code = code.strip()
        if not code:
            if comment and not pending_comment:
                pending_comment = comment
            continue

        low = code.lower()

        if low.startswith("set_property"):
            port = _extract_port(code)

            if "package_pin" in low and port:
                pin_val = _extract_value(code, "PACKAGE_PIN")
                if pin_val:
                    pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=pin_val))
                    pa.pin = pin_val
                    if pending_comment and not pa.comment:
                        pa.comment = pending_comment
            elif "iostandard" in low and port:
                val = _extract_value(code, "IOSTANDARD")
                if val:
                    pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=""))
                    pa.iostandard = val
            elif re.search(r"\bdrive\b", low) and port:
                val = _extract_value(code, "DRIVE")
                if val and val.isdigit():
                    pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=""))
                    pa.drive = int(val)
            elif re.search(r"\bslew\b", low) and port:
                val = _extract_value(code, "SLEW")
                if val:
                    pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=""))
                    pa.slew = val
            elif "pullup" in low and port:
                pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=""))
                pa.pullup = True
            elif "pulldown" in low and port:
                pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=""))
                pa.pulldown = True
            elif "pulltype" in low and port:
                val = _extract_value(code, "PULLTYPE")
                if val:
                    pa = pin_map.setdefault(port, XdcPinAssignment(port=port, pin=""))
                    pa.pulltype = val

            xdc.raw_constraints.append(XdcConstraint(type="set_property", raw=code, line=lineno))
            pending_comment = ""
            continue

        if low.startswith("create_clock"):
            clk = _parse_create_clock(code)
            if clk is not None:
                xdc.clocks.append(clk)
            xdc.raw_constraints.append(XdcConstraint(type="create_clock", raw=code, line=lineno))
            pending_comment = ""
            continue

        if low.startswith("set_input_delay") or low.startswith("set_output_delay"):
            d = _parse_io_delay(code)
            if d is not None:
                xdc.io_delays.append(d)
            xdc.raw_constraints.append(XdcConstraint(type=low.split()[0], raw=code, line=lineno))
            pending_comment = ""
            continue

        if low.startswith("set_false_path"):
            fp = _parse_false_path(code)
            xdc.false_paths.append(fp)
            xdc.raw_constraints.append(XdcConstraint(type="set_false_path", raw=code, line=lineno))
            pending_comment = ""
            continue

        # Unknown: keep as raw.
        xdc.raw_constraints.append(
            XdcConstraint(type=low.split()[0] if low else "unknown", raw=code, line=lineno)
        )
        pending_comment = ""

    # Only keep pins that actually have a physical location.
    xdc.pin_assignments = [p for p in pin_map.values() if p.pin]
    return xdc


def _parse_create_clock(code: str) -> XdcClockDef | None:
    period_m = re.search(r"-period\s+([0-9.]+)", code)
    name_m = re.search(r"-name\s+(\S+)", code)
    port = _extract_port(code)
    if not period_m or not port:
        return None
    period = float(period_m.group(1))
    name = name_m.group(1).strip("{}") if name_m else f"clk_{port}"
    waveform: tuple[float, float] | None = None
    wf_m = re.search(r"-waveform\s*\{([^}]+)\}", code)
    if wf_m:
        nums = [float(x) for x in wf_m.group(1).split()]
        if len(nums) >= 2:
            waveform = (nums[0], nums[1])
    return XdcClockDef(
        name=name,
        source_port=port,
        period_ns=period,
        waveform=waveform,
    )


def _parse_io_delay(code: str) -> XdcIoDelay | None:
    kind = "input" if "input" in code.lower() else "output"
    clock_m = re.search(r"-clock\s+(\S+)", code)
    min_max = "max"
    if re.search(r"-min\b", code):
        min_max = "min"
    tokens = re.findall(r"[-+]?[0-9]*\.?[0-9]+", code)
    delay = float(tokens[-1]) if tokens else 0.0
    port = _extract_port(code) or ""
    clock = clock_m.group(1).strip("{}") if clock_m else ""
    return XdcIoDelay(
        kind=kind,
        port=port,
        clock=clock,
        delay_ns=delay,
        max_min=min_max,
    )


def _parse_false_path(code: str) -> XdcFalsePath:
    fp = XdcFalsePath()
    for m in re.finditer(r"-from\s+\[([^\]]+)\]", code):
        fp.from_pins.append(m.group(1))
    for m in re.finditer(r"-to\s+\[([^\]]+)\]", code):
        fp.to_pins.append(m.group(1))
    return fp


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_xdc(xdc: XdcFile, output: str | Path) -> None:
    """Write an :class:`XdcFile` back out as XDC text."""
    out = Path(output)
    lines: list[str] = []
    lines.append("# Auto-generated by OpenForge XDC writer")
    lines.append("")

    if xdc.clocks:
        lines.append("# ---- Clocks ----")
        for clk in xdc.clocks:
            lines.append(clk.to_xdc_line())
        lines.append("")

    if xdc.pin_assignments:
        lines.append("# ---- Pin assignments ----")
        for pa in xdc.pin_assignments:
            lines.extend(pa.to_xdc_lines())
            lines.append("")

    if xdc.io_delays:
        lines.append("# ---- I/O delays ----")
        for d in xdc.io_delays:
            cmd = "set_input_delay" if d.kind == "input" else "set_output_delay"
            lines.append(
                f"{cmd} -clock {d.clock} -{d.max_min} {d.delay_ns} [get_ports {{{d.port}}}]"
            )
        lines.append("")

    if xdc.false_paths:
        lines.append("# ---- False paths ----")
        for fp in xdc.false_paths:
            parts = ["set_false_path"]
            for src in fp.from_pins:
                parts.append(f"-from [{src}]")
            for dst in fp.to_pins:
                parts.append(f"-to [{dst}]")
            lines.append(" ".join(parts))
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def make_default_xdc(
    clock_port: str,
    clock_pin: str,
    clock_period_ns: float,
    reset_port: str | None = None,
    reset_pin: str | None = None,
    leds: list[tuple[str, str]] | None = None,
    iostandard: str = "LVCMOS33",
) -> XdcFile:
    """Create a minimal XDC with clock, reset and LEDs pre-populated."""
    xdc = XdcFile()
    xdc.pin_assignments.append(
        XdcPinAssignment(port=clock_port, pin=clock_pin, iostandard=iostandard)
    )
    xdc.clocks.append(
        XdcClockDef(
            name=f"{clock_port}_pin",
            source_port=clock_port,
            period_ns=clock_period_ns,
        )
    )
    if reset_port and reset_pin:
        xdc.pin_assignments.append(
            XdcPinAssignment(port=reset_port, pin=reset_pin, iostandard=iostandard)
        )
    if leds:
        for port, pin in leds:
            xdc.pin_assignments.append(XdcPinAssignment(port=port, pin=pin, iostandard=iostandard))
    return xdc
