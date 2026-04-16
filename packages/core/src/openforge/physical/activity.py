"""Activity-driven power analysis using VCD/SAIF input.

Reads switching activity from a simulation waveform (VCD) or a SAIF file,
computes per-signal toggle counts and static probabilities, and feeds the
result into OpenSTA's read_power_activities + report_power for accurate
dynamic power analysis.

Also provides a sliding window analysis to produce a power-vs-time curve
suitable for plotting in the desktop UI.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SignalActivity:
    """Activity statistics for a single signal."""

    name: str
    toggle_count: int = 0
    static_prob_high: float = 0.0  # P(signal=1) over time
    sample_period_ns: float = 0.0
    bit_width: int = 1
    transitions: list[tuple[float, int]] = field(default_factory=list)

    @property
    def toggle_rate(self) -> float:
        """Toggles per nanosecond."""
        if self.sample_period_ns <= 0:
            return 0.0
        return self.toggle_count / self.sample_period_ns

    @property
    def activity_factor(self) -> float:
        """Average switching activity factor (alpha) - between 0 and 1.

        Defined as toggles per clock cycle / 2. Without a clock reference we
        approximate it as toggle_count / (2 * num_possible_toggles), which we
        cap at 1.0.
        """
        if self.sample_period_ns <= 0:
            return 0.0
        # Assume a default 1 GHz reference for normalization
        possible = max(1, int(self.sample_period_ns * 2))
        return min(1.0, self.toggle_count / possible)

    @property
    def is_clock_like(self) -> bool:
        """Heuristic: high toggle rate and ~50% duty cycle."""
        return self.toggle_rate > 0.1 and 0.4 <= self.static_prob_high <= 0.6


@dataclass
class ActivityFile:
    """Parsed VCD or SAIF activity data."""

    format: str  # vcd/saif
    duration_ns: float
    signals: dict[str, SignalActivity] = field(default_factory=dict)
    timescale_ns: float = 1.0
    top_scope: str = ""

    def get_average_activity(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.activity_factor for s in self.signals.values()) / len(self.signals)

    def get_signal(self, name: str) -> SignalActivity | None:
        return self.signals.get(name)

    def get_total_toggles(self) -> int:
        return sum(s.toggle_count for s in self.signals.values())

    def get_clock_signals(self) -> list[SignalActivity]:
        return [s for s in self.signals.values() if s.is_clock_like]

    def __len__(self) -> int:
        return len(self.signals)


# ---------------------------------------------------------------------------
# VCD parser
# ---------------------------------------------------------------------------


_TIMESCALE_FACTORS = {
    "fs": 1e-6,
    "ps": 1e-3,
    "ns": 1.0,
    "us": 1e3,
    "ms": 1e6,
    "s": 1e9,
}


def _parse_timescale(text: str) -> float:
    """Convert a VCD $timescale string to nanoseconds-per-tick."""
    text = text.strip().replace(" ", "")
    m = re.match(r"(\d+)([a-z]+)", text, re.IGNORECASE)
    if not m:
        return 1.0
    num = int(m.group(1))
    unit = m.group(2).lower()
    return num * _TIMESCALE_FACTORS.get(unit, 1.0)


def parse_vcd_for_activity(vcd_path: Path) -> ActivityFile:
    """Parse a VCD waveform and compute toggle counts per signal.

    Algorithm:
    1. Parse VCD header to get scope and var declarations.
    2. Read time markers (#NNN) and value changes.
    3. For each signal, count 0->1 and 1->0 transitions.
    4. Compute time-weighted P(signal=1) for each signal.
    5. Return ActivityFile with all stats.
    """
    vcd_path = Path(vcd_path)
    if not vcd_path.exists():
        raise FileNotFoundError(f"VCD file not found: {vcd_path}")

    timescale_ns = 1.0
    # id_code -> (full_name, width)
    id_to_name: dict[str, tuple[str, int]] = {}
    scope_stack: list[str] = []
    top_scope = ""

    # Parse header first
    with vcd_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("$timescale"):
                # Could be on same line or following line
                rest = line[len("$timescale") :].strip()
                if not rest or rest == "$end":
                    rest = next(f).strip()
                timescale_ns = _parse_timescale(rest)
            elif line.startswith("$scope"):
                parts = line.split()
                if len(parts) >= 3:
                    scope_stack.append(parts[2])
                    if not top_scope:
                        top_scope = parts[2]
            elif line.startswith("$upscope"):
                if scope_stack:
                    scope_stack.pop()
            elif line.startswith("$var"):
                # $var wire 1 ! clk $end
                parts = line.split()
                if len(parts) >= 5:
                    width = int(parts[2]) if parts[2].isdigit() else 1
                    id_code = parts[3]
                    name = parts[4]
                    full = ".".join(scope_stack + [name]) if scope_stack else name
                    id_to_name[id_code] = (full, width)
            elif line.startswith("$enddefinitions"):
                break

        # Initialize per-signal state
        signal_state: dict[str, str] = {}
        toggle_counts: dict[str, int] = {id_code: 0 for id_code in id_to_name}
        time_high: dict[str, float] = {id_code: 0.0 for id_code in id_to_name}
        last_change_time: dict[str, float] = {id_code: 0.0 for id_code in id_to_name}

        current_time = 0.0
        max_time = 0.0

        for line in f:
            line = line.strip()
            if not line:
                continue
            c = line[0]
            if c == "#":
                try:
                    current_time = float(line[1:])
                except ValueError:
                    continue
                if current_time > max_time:
                    max_time = current_time
            elif c in ("0", "1", "x", "z", "X", "Z"):
                value = c.lower()
                id_code = line[1:]
                _record_change(
                    id_code,
                    value,
                    current_time,
                    signal_state,
                    toggle_counts,
                    time_high,
                    last_change_time,
                )
            elif c in ("b", "B"):
                # bit vector: bVALUE id
                try:
                    value, id_code = line[1:].split(" ", 1)
                except ValueError:
                    continue
                # Treat as toggled if any bit changed - simplified.
                prev = signal_state.get(id_code)
                if prev != value:
                    if prev is not None and prev not in ("x", "z"):
                        toggle_counts[id_code] = toggle_counts.get(id_code, 0) + 1
                    signal_state[id_code] = value
                    last_change_time[id_code] = current_time
            elif c in ("r", "R"):
                # real number, skip
                continue
            elif line.startswith("$"):
                continue

    # Convert to ActivityFile
    duration_ticks = max(max_time, 1.0)
    duration_ns = duration_ticks * timescale_ns

    # Account for time spent at the final value
    for id_code, state in signal_state.items():
        if state == "1":
            time_high[id_code] = time_high.get(id_code, 0.0) + (
                duration_ticks - last_change_time.get(id_code, 0.0)
            )

    signals: dict[str, SignalActivity] = {}
    for id_code, (name, width) in id_to_name.items():
        toggles = toggle_counts.get(id_code, 0)
        prob_high = 0.0
        if duration_ticks > 0:
            prob_high = time_high.get(id_code, 0.0) / duration_ticks
            prob_high = max(0.0, min(1.0, prob_high))
        signals[name] = SignalActivity(
            name=name,
            toggle_count=toggles,
            static_prob_high=prob_high,
            sample_period_ns=duration_ns,
            bit_width=width,
        )

    return ActivityFile(
        format="vcd",
        duration_ns=duration_ns,
        signals=signals,
        timescale_ns=timescale_ns,
        top_scope=top_scope,
    )


def _record_change(
    id_code: str,
    value: str,
    current_time: float,
    state: dict[str, str],
    toggles: dict[str, int],
    time_high: dict[str, float],
    last_change: dict[str, float],
) -> None:
    prev = state.get(id_code)
    if prev == "1":
        time_high[id_code] = time_high.get(id_code, 0.0) + (
            current_time - last_change.get(id_code, 0.0)
        )
    if prev is not None and prev != value and prev not in ("x", "z") and value not in ("x", "z"):
        toggles[id_code] = toggles.get(id_code, 0) + 1
    state[id_code] = value
    last_change[id_code] = current_time


# ---------------------------------------------------------------------------
# SAIF parser
# ---------------------------------------------------------------------------


def parse_saif(saif_path: Path) -> ActivityFile:
    """Parse a SAIF (Switching Activity Interchange Format) file.

    SAIF format::

        (SAIFILE
          (SAIFVERSION "2.0")
          (DESIGN dut)
          (DURATION 1000000)
          (TIMESCALE 1ns)
          (DIVIDER /)
          (INSTANCE dut
            (NET
              (sig1 (T0 500) (T1 500) (TX 0) (TC 100) (IG 0))
              ...
            )
          )
        )
    """
    saif_path = Path(saif_path)
    if not saif_path.exists():
        raise FileNotFoundError(f"SAIF file not found: {saif_path}")

    text = saif_path.read_text(encoding="utf-8", errors="replace")

    # Strip comments
    text = re.sub(r"//[^\n]*", "", text)

    # Extract scalar fields
    duration_m = re.search(r"\(DURATION\s+([\d.]+)\)", text)
    timescale_m = re.search(r"\(TIMESCALE\s+([^)]+)\)", text)
    design_m = re.search(r"\(DESIGN\s+(\S+)\)", text)
    divider_m = re.search(r"\(DIVIDER\s+(\S+)\)", text)

    duration = float(duration_m.group(1)) if duration_m else 0.0
    timescale_ns = _parse_timescale(timescale_m.group(1).strip()) if timescale_m else 1.0
    top_scope = design_m.group(1) if design_m else ""
    divider = divider_m.group(1) if divider_m else "/"

    duration_ns = duration * timescale_ns

    # Walk INSTANCE blocks. We do a simple bracket-aware traversal.
    signals: dict[str, SignalActivity] = {}
    _walk_saif_instances(text, "", divider, duration_ns, signals)

    return ActivityFile(
        format="saif",
        duration_ns=duration_ns,
        signals=signals,
        timescale_ns=timescale_ns,
        top_scope=top_scope,
    )


def _walk_saif_instances(
    text: str,
    prefix: str,
    divider: str,
    duration_ns: float,
    out: dict[str, SignalActivity],
) -> None:
    """Walk INSTANCE blocks in a SAIF body and accumulate signal stats."""
    pos = 0
    while True:
        m = re.search(r"\(INSTANCE\s+(\S+)", text[pos:])
        if not m:
            break
        name = m.group(1)
        start = pos + m.end()
        # Find matching close paren
        end = _find_matching_paren(text, pos + m.start())
        if end < 0:
            break
        body = text[start:end]
        full_prefix = f"{prefix}{divider}{name}" if prefix else name

        # Parse NET block within this instance (non-recursive subset)
        net_m = re.search(r"\(NET\b", body)
        if net_m:
            net_end = _find_matching_paren(body, net_m.start())
            net_body = body[net_m.end() : net_end] if net_end > 0 else body[net_m.end() :]
            for sig_m in re.finditer(
                r"\(\s*(\S+)\s*\(T0\s+([\d.]+)\)\s*\(T1\s+([\d.]+)\)"
                r"(?:\s*\(TX\s+([\d.]+)\))?\s*\(TC\s+(\d+)\)",
                net_body,
            ):
                sig_name = sig_m.group(1)
                t0 = float(sig_m.group(2))
                t1 = float(sig_m.group(3))
                tc = int(sig_m.group(5))
                total = t0 + t1
                prob_high = (t1 / total) if total > 0 else 0.0
                full = f"{full_prefix}{divider}{sig_name}"
                out[full] = SignalActivity(
                    name=full,
                    toggle_count=tc,
                    static_prob_high=prob_high,
                    sample_period_ns=duration_ns,
                )

        # Recurse into nested INSTANCE blocks
        _walk_saif_instances(body, full_prefix, divider, duration_ns, out)
        pos = end + 1


def _find_matching_paren(text: str, open_idx: int) -> int:
    """Return the index of the matching ')' for the '(' at open_idx, or -1."""
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


# ---------------------------------------------------------------------------
# Power analyzer
# ---------------------------------------------------------------------------


class ActivityDrivenPowerAnalyzer:
    """Power analysis using real switching activity from simulation."""

    def __init__(
        self,
        liberty: Path,
        netlist: Path,
        sdc: Path,
        opensta_bin: str = "sta",
    ) -> None:
        self.liberty = Path(liberty)
        self.netlist = Path(netlist)
        self.sdc = Path(sdc)
        self.opensta_bin = opensta_bin

    def analyze(
        self,
        activity: ActivityFile,
        top_module: str,
        cwd: Path | None = None,
        vcd_path: Path | None = None,
        saif_path: Path | None = None,
    ) -> dict:
        """Run OpenSTA with read_power_activities loaded from VCD/SAIF.

        Returns a structured dict with totals and per-instance breakdown.
        """
        work = Path(cwd) if cwd else Path(tempfile.mkdtemp(prefix="powact_"))
        work.mkdir(parents=True, exist_ok=True)
        tcl_path = work / "power_activity.tcl"
        tcl_path.write_text(
            self._generate_tcl(activity, top_module, vcd_path, saif_path),
            encoding="utf-8",
        )

        log = ""
        error = ""
        try:
            proc = subprocess.run(
                [self.opensta_bin, "-no_init", "-exit", str(tcl_path)],
                capture_output=True,
                text=True,
                cwd=str(work),
                timeout=600,
            )
            log = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if proc.returncode != 0:
                error = f"OpenSTA exit {proc.returncode}"
        except FileNotFoundError:
            error = f"OpenSTA binary not found: {self.opensta_bin}"
        except subprocess.TimeoutExpired:
            error = "OpenSTA timed out"
        except Exception as e:  # pragma: no cover
            error = str(e)

        return self._parse_power_log(log, error, activity)

    def _generate_tcl(
        self,
        activity: ActivityFile,
        top_module: str,
        vcd_path: Path | None,
        saif_path: Path | None,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# Activity-driven power analysis for {top_module}")
        lines.append(f"read_liberty {{{_p(self.liberty)}}}")
        lines.append(f"read_verilog {{{_p(self.netlist)}}}")
        lines.append(f"link_design {top_module}")
        lines.append(f"read_sdc {{{_p(self.sdc)}}}")
        if vcd_path is not None:
            lines.append(f"read_power_activities -scope {top_module} -vcd {{{_p(vcd_path)}}}")
        elif saif_path is not None:
            lines.append(f"read_power_activities -scope {top_module} -saif {{{_p(saif_path)}}}")
        else:
            # Set average activity for the design
            avg = activity.get_average_activity()
            lines.append(f"set_power_activity -global -activity {avg:.4f}")
        lines.append("report_power -hierarchy")
        lines.append("report_power")
        lines.append("exit")
        return "\n".join(lines) + "\n"

    def _parse_power_log(self, log: str, error: str, activity: ActivityFile) -> dict:
        result: dict = {
            "error": error,
            "raw_log": log,
            "total_internal_w": 0.0,
            "total_switching_w": 0.0,
            "total_leakage_w": 0.0,
            "total_w": 0.0,
            "by_group": {},
            "by_instance": [],
            "average_activity": activity.get_average_activity(),
            "duration_ns": activity.duration_ns,
            "num_signals": len(activity.signals),
        }
        if not log:
            return result

        # Total power line: "Total <internal> <switching> <leakage> <total> ..."
        m = re.search(
            r"Total\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)",
            log,
        )
        if m:
            result["total_internal_w"] = float(m.group(1))
            result["total_switching_w"] = float(m.group(2))
            result["total_leakage_w"] = float(m.group(3))
            result["total_w"] = float(m.group(4))

        # Group power: Sequential / Combinational / Clock / Macro / Pad
        for grp in ("Sequential", "Combinational", "Clock", "Macro", "Pad"):
            gm = re.search(
                rf"{grp}\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)",
                log,
            )
            if gm:
                result["by_group"][grp.lower()] = {
                    "internal_w": float(gm.group(1)),
                    "switching_w": float(gm.group(2)),
                    "leakage_w": float(gm.group(3)),
                    "total_w": float(gm.group(4)),
                }
        return result

    def generate_dynamic_power_curve(
        self,
        activity: ActivityFile,
        time_resolution_ns: float = 100.0,
    ) -> list[tuple[float, float]]:
        """Generate a power-vs-time curve via sliding window over the activity.

        Returns a list of (time_ns, power_mw) tuples.
        """
        if activity.duration_ns <= 0 or time_resolution_ns <= 0:
            return []

        num_buckets = max(1, int(activity.duration_ns / time_resolution_ns))
        buckets = [0.0] * num_buckets

        # For VCD-derived activity we may not have per-transition timing,
        # so we approximate by distributing toggles uniformly. If we have
        # transition times we will use them.
        for sig in activity.signals.values():
            if sig.transitions:
                for t, _ in sig.transitions:
                    idx = min(num_buckets - 1, int(t / time_resolution_ns))
                    buckets[idx] += 1.0
            else:
                if sig.toggle_count > 0:
                    per_bucket = sig.toggle_count / num_buckets
                    for i in range(num_buckets):
                        buckets[i] += per_bucket

        # Convert raw toggle count per bucket to a notional power (mW). We use
        # a constant scale factor; calibration would come from the technology.
        scale_mw_per_toggle = 1e-4
        curve: list[tuple[float, float]] = []
        for i, b in enumerate(buckets):
            t_ns = (i + 0.5) * time_resolution_ns
            curve.append((t_ns, b * scale_mw_per_toggle))
        return curve


def _p(path: Path) -> str:
    return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def summarize_activity(activity: ActivityFile, top_n: int = 20) -> dict:
    """Compute summary statistics for an ActivityFile.

    Returns a dict with totals, averages, top toggling signals, and clock
    candidates - useful for displaying in the desktop UI.
    """
    if not activity.signals:
        return {
            "format": activity.format,
            "duration_ns": activity.duration_ns,
            "num_signals": 0,
            "total_toggles": 0,
            "avg_toggle_rate": 0.0,
            "avg_activity": 0.0,
            "top_toggling": [],
            "clock_candidates": [],
        }

    sigs = list(activity.signals.values())
    sigs_sorted = sorted(sigs, key=lambda s: -s.toggle_count)
    top = []
    for s in sigs_sorted[:top_n]:
        top.append(
            {
                "name": s.name,
                "toggle_count": s.toggle_count,
                "toggle_rate": s.toggle_rate,
                "static_prob_high": s.static_prob_high,
                "activity_factor": s.activity_factor,
                "bit_width": s.bit_width,
            }
        )

    clk_candidates = [
        {
            "name": s.name,
            "toggle_rate": s.toggle_rate,
            "duty_cycle": s.static_prob_high,
        }
        for s in sigs
        if s.is_clock_like
    ]
    clk_candidates.sort(key=lambda d: -d["toggle_rate"])

    total_toggles = sum(s.toggle_count for s in sigs)
    avg_rate = sum(s.toggle_rate for s in sigs) / len(sigs) if sigs else 0.0

    return {
        "format": activity.format,
        "duration_ns": activity.duration_ns,
        "num_signals": len(sigs),
        "total_toggles": total_toggles,
        "avg_toggle_rate": avg_rate,
        "avg_activity": activity.get_average_activity(),
        "top_toggling": top,
        "clock_candidates": clk_candidates[:10],
    }


def merge_activities(files: list[ActivityFile]) -> ActivityFile:
    """Merge multiple ActivityFile objects (e.g. from different test cases).

    Toggle counts are summed and probabilities are duration-weighted averages.
    """
    if not files:
        return ActivityFile(format="merged", duration_ns=0.0)
    if len(files) == 1:
        return files[0]

    total_duration = sum(f.duration_ns for f in files)
    merged_signals: dict[str, SignalActivity] = {}

    all_names: set[str] = set()
    for f in files:
        all_names.update(f.signals.keys())

    for name in all_names:
        toggle_sum = 0
        weighted_prob = 0.0
        width = 1
        for f in files:
            sig = f.signals.get(name)
            if sig is None:
                continue
            toggle_sum += sig.toggle_count
            if total_duration > 0:
                weighted_prob += sig.static_prob_high * (f.duration_ns / total_duration)
            width = max(width, sig.bit_width)
        merged_signals[name] = SignalActivity(
            name=name,
            toggle_count=toggle_sum,
            static_prob_high=weighted_prob,
            sample_period_ns=total_duration,
            bit_width=width,
        )

    return ActivityFile(
        format="merged",
        duration_ns=total_duration,
        signals=merged_signals,
        timescale_ns=files[0].timescale_ns,
        top_scope=files[0].top_scope,
    )


def write_saif(activity: ActivityFile, output: Path) -> None:
    """Serialize an ActivityFile back to SAIF format.

    Useful when converting a parsed VCD into SAIF for downstream tools that
    only accept SAIF input.
    """
    output = Path(output)
    lines: list[str] = []
    lines.append("(SAIFILE")
    lines.append('  (SAIFVERSION "2.0")')
    lines.append(f"  (DESIGN {activity.top_scope or 'design'})")
    lines.append(f"  (DURATION {activity.duration_ns})")
    lines.append("  (TIMESCALE 1ns)")
    lines.append("  (DIVIDER /)")
    lines.append("  (INSTANCE top")
    lines.append("    (NET")
    for sig in activity.signals.values():
        prob_low = 1.0 - sig.static_prob_high
        t1 = int(sig.static_prob_high * activity.duration_ns)
        t0 = int(prob_low * activity.duration_ns)
        lines.append(
            f"      ({sig.name} (T0 {t0}) (T1 {t1}) (TX 0) (TC {sig.toggle_count}) (IG 0))"
        )
    lines.append("    )")
    lines.append("  )")
    lines.append(")")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "SignalActivity",
    "ActivityFile",
    "parse_vcd_for_activity",
    "parse_saif",
    "ActivityDrivenPowerAnalyzer",
    "summarize_activity",
    "merge_activities",
    "write_saif",
]
