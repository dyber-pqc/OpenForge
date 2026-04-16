"""Mixed-signal co-simulation between digital RTL and analog SPICE.

The :class:`MixedSignalSimulator` runs a *digital first* style of co-sim:

1. The digital simulator (Verilator/Icarus, run externally) produces a VCD
   tracing the boundary signals.
2. :meth:`MixedSignalSimulator.vcd_to_pwl` converts those digital
   transitions into piecewise-linear (PWL) voltage sources, written as a
   ``.include`` file consumed by SPICE.
3. ngspice runs an analog transient that uses these PWL sources as inputs
   into the analog block (described as a subckt).
4. :meth:`MixedSignalSimulator.spice_raw_to_vcd` samples analog node
   voltages and converts them back into VCD digital signals (with a
   threshold).
5. The optional feedback loop re-runs the digital sim with the analog VCD
   as inputs - the orchestration here only does one round-trip but the
   building blocks are reusable.

This module deliberately avoids any UI dependencies and operates purely on
files; the desktop SpicePanel can drive it via Qt threads.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from openforge.engine.ngspice import NgspiceEngine, parse_si_value


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CoSimSignal:
    """Description of a digital/analog boundary signal."""

    name: str
    direction: str  # "digital_to_analog" | "analog_to_digital"
    voltage_high: float = 1.8
    voltage_low: float = 0.0
    rise_time_ns: float = 0.1
    threshold: float = 0.9  # used for A2D sampling
    bit_index: int | None = None  # for vector signals


@dataclass
class CoSimResult:
    """Outcome of a co-simulation run."""

    success: bool
    duration_s: float
    digital_vcd: Path | None
    analog_raw: Path | None
    transitions: int = 0
    log: str = ""
    pwl_file: Path | None = None
    a2d_vcd: Path | None = None
    spice_returncode: int = 0
    samples: int = 0


# ---------------------------------------------------------------------------
# Simple VCD parser (sufficient for boundary signals)
# ---------------------------------------------------------------------------


@dataclass
class _VcdSignal:
    name: str
    width: int
    code: str
    transitions: list[tuple[int, str]] = field(default_factory=list)


def _parse_vcd(path: Path) -> tuple[float, dict[str, _VcdSignal]]:
    """Parse a VCD file. Returns (timescale_seconds, name->signal)."""
    timescale_s = 1e-9  # default 1ns
    signals_by_code: dict[str, _VcdSignal] = {}
    signals_by_name: dict[str, _VcdSignal] = {}
    in_dump = False
    current_time = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        tokens: list[str] = []
        for raw in fh:
            tokens.extend(raw.split())
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "$timescale":
                # consume until $end
                j = i + 1
                buf: list[str] = []
                while j < len(tokens) and tokens[j] != "$end":
                    buf.append(tokens[j])
                    j += 1
                ts_text = "".join(buf).lower()
                m = re.match(r"(\d+)([a-z]+)", ts_text)
                if m:
                    n = int(m.group(1))
                    unit = m.group(2)
                    factor = {
                        "s": 1.0,
                        "ms": 1e-3,
                        "us": 1e-6,
                        "ns": 1e-9,
                        "ps": 1e-12,
                        "fs": 1e-15,
                    }.get(unit, 1e-9)
                    timescale_s = n * factor
                i = j + 1
                continue
            if tok == "$var":
                # $var wire 1 ! sig $end
                kind = tokens[i + 1]
                width = int(tokens[i + 2])
                code = tokens[i + 3]
                name = tokens[i + 4]
                # consume to $end
                j = i + 5
                while j < len(tokens) and tokens[j] != "$end":
                    j += 1
                sig = _VcdSignal(name=name, width=width, code=code)
                signals_by_code[code] = sig
                signals_by_name[name] = sig
                _ = kind
                i = j + 1
                continue
            if tok == "$enddefinitions":
                # consume to $end
                j = i + 1
                while j < len(tokens) and tokens[j] != "$end":
                    j += 1
                in_dump = True
                i = j + 1
                continue
            if in_dump:
                if tok.startswith("#"):
                    try:
                        current_time = int(tok[1:])
                    except ValueError:
                        pass
                    i += 1
                    continue
                if tok in ("$dumpvars", "$dumpall", "$dumpoff", "$dumpon", "$end"):
                    i += 1
                    continue
                # scalar: 0!  /  1!  /  x!  /  z!
                if tok and tok[0] in "01xzXZ" and len(tok) >= 2:
                    val = tok[0]
                    code = tok[1:]
                    sig = signals_by_code.get(code)
                    if sig is not None:
                        sig.transitions.append((current_time, val))
                    i += 1
                    continue
                # vector: b1010 !
                if tok.startswith("b") or tok.startswith("B"):
                    val = tok[1:]
                    if i + 1 < len(tokens):
                        code = tokens[i + 1]
                        sig = signals_by_code.get(code)
                        if sig is not None:
                            sig.transitions.append((current_time, val))
                        i += 2
                        continue
                i += 1
                continue
            i += 1
    return timescale_s, signals_by_name


# ---------------------------------------------------------------------------
# Mixed-signal simulator
# ---------------------------------------------------------------------------


class MixedSignalSimulator:
    """Co-simulate a digital block (Verilog) with an analog block (SPICE)."""

    def __init__(self) -> None:
        self.spice = NgspiceEngine()
        self.last_log: list[str] = []

    # ------------------------------------------------------------------
    # VCD <-> PWL conversion
    # ------------------------------------------------------------------
    def vcd_to_pwl(
        self,
        vcd_path: Path,
        signals: list[CoSimSignal],
        output_pwl: Path,
    ) -> int:
        """Convert digital VCD signals to PWL voltage sources.

        Writes a SPICE include file with one ``V<sig> sig 0 PWL(...)``
        line per digital_to_analog signal. Returns the number of
        transitions written.
        """
        vcd_path = Path(vcd_path)
        output_pwl = Path(output_pwl)
        timescale_s, sig_map = _parse_vcd(vcd_path)
        wanted = {s.name: s for s in signals if s.direction == "digital_to_analog"}
        total_trans = 0
        out_lines: list[str] = ["* PWL voltage sources generated by OpenForge co-sim"]
        for name, cosig in wanted.items():
            vcd_sig = sig_map.get(name)
            if vcd_sig is None:
                out_lines.append(f"* WARNING: signal {name} not found in VCD")
                continue
            pwl_pts: list[tuple[float, float]] = []
            for t_int, val in vcd_sig.transitions:
                t_s = t_int * timescale_s
                # Glitch in a small ramp at +/- rise_time/2
                ramp = (cosig.rise_time_ns or 0.1) * 1e-9
                v = self._digital_to_voltage(val, cosig)
                if pwl_pts:
                    last_t, last_v = pwl_pts[-1]
                    pwl_pts.append((max(t_s - ramp / 2, last_t + 1e-15), last_v))
                pwl_pts.append((t_s + ramp / 2, v))
                total_trans += 1
            if not pwl_pts:
                pwl_pts.append((0.0, cosig.voltage_low))
            pts_text = " ".join(f"{t:.6e} {v:.6f}" for t, v in pwl_pts)
            out_lines.append(f"V{name} {name} 0 PWL({pts_text})")
        output_pwl.parent.mkdir(parents=True, exist_ok=True)
        output_pwl.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        self.last_log.append(
            f"vcd_to_pwl: {len(wanted)} signals, {total_trans} transitions -> {output_pwl}"
        )
        return total_trans

    @staticmethod
    def _digital_to_voltage(val: str, cosig: CoSimSignal) -> float:
        v = val.lower()
        if v in ("1", "h"):
            return cosig.voltage_high
        if v in ("0", "l"):
            return cosig.voltage_low
        # x/z -> midpoint
        return (cosig.voltage_high + cosig.voltage_low) / 2.0

    def spice_raw_to_vcd(
        self,
        raw_path: Path,
        signals: list[CoSimSignal],
        threshold: float,
        output_vcd: Path,
    ) -> int:
        """Convert ngspice .raw output to VCD by sampling analog nodes."""
        raw_path = Path(raw_path)
        output_vcd = Path(output_vcd)
        data = NgspiceEngine.parse_raw_ascii(raw_path)
        if "error" in data:
            self.last_log.append(f"spice_raw_to_vcd: {data['error']}")
            return 0
        variables = data.get("variables", [])
        values = data.get("values", [])
        if not variables or not values:
            return 0

        # Locate the time column (the variable typed "time" by ngspice).
        time_idx = None
        for i, var in enumerate(variables):
            if var.get("type", "").lower() == "time":
                time_idx = i
                break
        if time_idx is None:
            time_idx = 0

        wanted = [s for s in signals if s.direction == "analog_to_digital"]
        col_for_signal: dict[str, int] = {}
        for cosig in wanted:
            target = f"v({cosig.name.lower()})"
            for i, var in enumerate(variables):
                if var["name"].lower() == target or var["name"].lower() == cosig.name.lower():
                    col_for_signal[cosig.name] = i
                    break

        # Pick VCD codes for each signal
        codes = {name: chr(33 + i) for i, name in enumerate(col_for_signal)}

        # Find the smallest non-zero dt to choose the timescale.
        timescale_ns = 1
        if len(values) >= 2:
            try:
                dt = abs(values[1][time_idx] - values[0][time_idx])
                if dt > 0:
                    timescale_ns = max(int(dt * 1e9), 1)
            except (IndexError, TypeError):
                pass

        out: list[str] = [
            "$timescale 1ns $end",
            "$scope module top $end",
        ]
        for name, code in codes.items():
            out.append(f"$var wire 1 {code} {name} $end")
        out.append("$upscope $end")
        out.append("$enddefinitions $end")
        out.append("$dumpvars")

        last_state: dict[str, str] = {n: "x" for n in codes}
        sample_count = 0
        for row in values:
            if not row or time_idx >= len(row):
                continue
            t_s = row[time_idx]
            t_ns = int(t_s * 1e9)
            line_buf: list[str] = []
            for cosig in wanted:
                idx = col_for_signal.get(cosig.name)
                if idx is None or idx >= len(row):
                    continue
                v = row[idx]
                state = "1" if v >= threshold else "0"
                if state != last_state.get(cosig.name):
                    line_buf.append(f"{state}{codes[cosig.name]}")
                    last_state[cosig.name] = state
            if line_buf:
                out.append(f"#{t_ns}")
                out.extend(line_buf)
                sample_count += len(line_buf)
        out.append("$end")
        output_vcd.parent.mkdir(parents=True, exist_ok=True)
        output_vcd.write_text("\n".join(out) + "\n", encoding="utf-8")
        _ = timescale_ns
        self.last_log.append(
            f"spice_raw_to_vcd: {sample_count} sample edges -> {output_vcd}"
        )
        return sample_count

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------
    def run_cosimulation(
        self,
        digital_top: str,
        digital_sources: list[Path],
        analog_top_subckt: str,
        analog_netlist: Path,
        boundary_signals: list[CoSimSignal],
        sim_time_ns: float = 1000.0,
        work_dir: Path | None = None,
    ) -> CoSimResult:
        """Run a single round of digital -> analog co-simulation."""
        start = time.monotonic()
        work_dir = Path(work_dir or Path("./cosim_work").resolve())
        work_dir.mkdir(parents=True, exist_ok=True)

        # The desktop panel typically runs the digital sim externally and
        # passes the resulting VCD path via digital_sources[0]. We accept
        # either a single .vcd or a Verilog source list.
        digital_vcd: Path | None = None
        if len(digital_sources) == 1 and digital_sources[0].suffix.lower() == ".vcd":
            digital_vcd = digital_sources[0]
        else:
            digital_vcd = self._maybe_locate_existing_vcd(work_dir, digital_top)

        log_lines: list[str] = [
            f"co-sim: digital_top={digital_top}",
            f"co-sim: analog_top_subckt={analog_top_subckt}",
            f"co-sim: analog_netlist={analog_netlist}",
            f"co-sim: boundary_signals={[s.name for s in boundary_signals]}",
        ]

        if digital_vcd is None or not digital_vcd.exists():
            log_lines.append("co-sim: no digital VCD available; producing stub")
            digital_vcd = self._stub_digital_vcd(work_dir, boundary_signals, sim_time_ns)

        # Step 1: VCD -> PWL
        pwl_path = work_dir / "boundary_pwl.cir"
        n_trans = self.vcd_to_pwl(digital_vcd, boundary_signals, pwl_path)
        log_lines.append(f"co-sim: wrote {n_trans} PWL transitions")

        # Step 2: assemble a SPICE wrapper deck around the analog netlist
        wrapper_path = work_dir / "cosim_wrapper.cir"
        port_list = " ".join(s.name for s in boundary_signals)
        wrapper_lines = [
            "* OpenForge mixed-signal cosim wrapper",
            f".include {Path(analog_netlist).resolve().as_posix()}",
            f".include {pwl_path.as_posix()}",
            f"X_DUT {port_list} {analog_top_subckt}",
            f".tran 1n {sim_time_ns}n",
            ".end",
        ]
        wrapper_path.write_text("\n".join(wrapper_lines) + "\n", encoding="utf-8")

        # Step 3: run ngspice on the wrapper
        raw_path = work_dir / "cosim.raw"
        result = self.spice.run_tran(
            wrapper_path,
            tstep=1e-9,
            tstop=sim_time_ns * 1e-9,
        )
        log_lines.append(f"co-sim: ngspice rc={result.returncode} dur={result.duration:.2f}s")

        # Step 4: convert analog raw -> VCD
        a2d_vcd = work_dir / "analog_to_digital.vcd"
        samples = 0
        if raw_path.exists():
            samples = self.spice_raw_to_vcd(
                raw_path,
                boundary_signals,
                threshold=0.9,
                output_vcd=a2d_vcd,
            )

        duration = time.monotonic() - start
        success = result.ok or n_trans > 0
        log_lines.extend(self.last_log)
        return CoSimResult(
            success=success,
            duration_s=duration,
            digital_vcd=digital_vcd,
            analog_raw=raw_path if raw_path.exists() else None,
            transitions=n_trans,
            log="\n".join(log_lines),
            pwl_file=pwl_path,
            a2d_vcd=a2d_vcd if a2d_vcd.exists() else None,
            spice_returncode=result.returncode,
            samples=samples,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _maybe_locate_existing_vcd(self, work_dir: Path, digital_top: str) -> Path | None:
        for cand in (
            work_dir / f"{digital_top}.vcd",
            work_dir / "dump.vcd",
            work_dir / "sim.vcd",
        ):
            if cand.exists():
                return cand
        return None

    def _stub_digital_vcd(
        self,
        work_dir: Path,
        signals: list[CoSimSignal],
        sim_time_ns: float,
    ) -> Path:
        """Generate a tiny placeholder VCD with toggling D2A signals."""
        path = work_dir / "stub_digital.vcd"
        d2a = [s for s in signals if s.direction == "digital_to_analog"]
        codes = {s.name: chr(33 + i) for i, s in enumerate(d2a)}
        out: list[str] = [
            "$timescale 1ns $end",
            "$scope module stub $end",
        ]
        for s in d2a:
            out.append(f"$var wire 1 {codes[s.name]} {s.name} $end")
        out.append("$upscope $end")
        out.append("$enddefinitions $end")
        out.append("$dumpvars")
        for s in d2a:
            out.append(f"0{codes[s.name]}")
        # Toggle each signal at intervals scaled to sim_time_ns
        period = max(int(sim_time_ns / 10), 1)
        for tick in range(1, 11):
            out.append(f"#{tick * period}")
            for s in d2a:
                out.append(f"{tick % 2}{codes[s.name]}")
        out.append("$end")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Convenience helpers used by the panel
# ---------------------------------------------------------------------------


def signal_from_dict(d: dict) -> CoSimSignal:
    """Build a :class:`CoSimSignal` from a plain dict (UI form data)."""
    return CoSimSignal(
        name=d["name"],
        direction=d.get("direction", "digital_to_analog"),
        voltage_high=float(d.get("vh", 1.8)),
        voltage_low=float(d.get("vl", 0.0)),
        rise_time_ns=float(d.get("rise_ns", 0.1)),
        threshold=float(d.get("threshold", 0.9)),
        bit_index=d.get("bit_index"),
    )


def parse_voltage(text: str) -> float:
    """Parse SPICE-style voltage strings such as ``1.8``, ``900m``."""
    return parse_si_value(text)


__all__ = [
    "CoSimSignal",
    "CoSimResult",
    "MixedSignalSimulator",
    "signal_from_dict",
    "parse_voltage",
]
