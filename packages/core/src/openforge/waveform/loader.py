"""Waveform file loader -- supports VCD and FST formats.

Uses the Rust openforge-wave parser when available, falls back to
a pure-Python VCD parser for portability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SignalType(StrEnum):
    WIRE = "wire"
    REG = "reg"
    INTEGER = "integer"
    REAL = "real"
    PARAMETER = "parameter"


class TimeUnit(StrEnum):
    S = "s"
    MS = "ms"
    US = "us"
    NS = "ns"
    PS = "ps"
    FS = "fs"


@dataclass
class ValueChange:
    time: int
    value: str  # binary string for digital, float string for real


@dataclass
class Signal:
    name: str
    width: int
    id_code: str
    signal_type: SignalType
    scope: str = ""
    changes: list[ValueChange] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.scope}.{self.name}" if self.scope else self.name

    @property
    def is_bus(self) -> bool:
        return self.width > 1

    def value_at(self, time: int) -> str:
        """Get the signal value at a given time."""
        val = ""
        for vc in self.changes:
            if vc.time <= time:
                val = vc.value
            else:
                break
        return val


@dataclass
class WaveformData:
    signals: list[Signal] = field(default_factory=list)
    timescale_magnitude: int = 1
    timescale_unit: TimeUnit = TimeUnit.NS
    total_time: int = 0
    date: str = ""
    version: str = ""

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    def get_signal(self, name: str) -> Signal | None:
        """Find a signal by full name."""
        for sig in self.signals:
            if sig.full_name == name or sig.name == name:
                return sig
        return None

    def search_signals(self, pattern: str) -> list[Signal]:
        """Search signals by name pattern (case-insensitive substring)."""
        pattern_lower = pattern.lower()
        return [s for s in self.signals if pattern_lower in s.full_name.lower()]

    def time_range(self) -> tuple[int, int]:
        """Return (min_time, max_time) across all signals."""
        if not self.signals:
            return (0, 0)
        min_t = min(
            (s.changes[0].time for s in self.signals if s.changes),
            default=0,
        )
        max_t = max(
            (s.changes[-1].time for s in self.signals if s.changes),
            default=0,
        )
        return (min_t, max_t)


def load_waveform(path: str | Path) -> WaveformData:
    """Load a waveform file (VCD or FST).

    Tries the Rust parser first (via subprocess), falls back to Python.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Waveform file not found: {path}")

    ext = path.suffix.lower()

    if ext == ".vcd":
        return _load_vcd_python(path)
    elif ext == ".fst":
        raise NotImplementedError("FST support requires the openforge-wave Rust tool.")
    else:
        raise ValueError(f"Unknown waveform format: {ext}")


def _load_vcd_python(path: Path) -> WaveformData:
    """Pure-Python VCD parser -- handles IEEE 1364 VCD format."""
    data = WaveformData()
    id_to_signal: dict[str, Signal] = {}
    scope_stack: list[str] = []
    in_defs = False
    current_time = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Header parsing
            if line.startswith("$timescale"):
                # May be on this line or next
                ts_text = line.replace("$timescale", "").replace("$end", "").strip()
                if not ts_text:
                    ts_text = next(f, "").strip().replace("$end", "").strip()
                _parse_timescale(data, ts_text)
                continue

            if line.startswith("$scope"):
                parts = line.split()
                if len(parts) >= 3:
                    scope_stack.append(parts[2])
                continue

            if line.startswith("$upscope"):
                if scope_stack:
                    scope_stack.pop()
                continue

            if line.startswith("$var"):
                parts = line.split()
                if len(parts) >= 5:
                    var_type = parts[1]
                    width = int(parts[2])
                    id_code = parts[3]
                    name = parts[4]
                    scope = ".".join(scope_stack)

                    sig_type = SignalType.WIRE
                    if var_type == "reg":
                        sig_type = SignalType.REG
                    elif var_type == "integer":
                        sig_type = SignalType.INTEGER
                    elif var_type == "real":
                        sig_type = SignalType.REAL
                    elif var_type == "parameter":
                        sig_type = SignalType.PARAMETER

                    sig = Signal(
                        name=name,
                        width=width,
                        id_code=id_code,
                        signal_type=sig_type,
                        scope=scope,
                    )
                    id_to_signal[id_code] = sig
                    data.signals.append(sig)
                continue

            if line.startswith("$enddefinitions"):
                in_defs = True
                continue

            if line.startswith("$"):
                # Skip other directives ($comment, $dumpvars, etc.)
                continue

            if not in_defs:
                continue

            # Value change parsing
            if line.startswith("#"):
                try:
                    current_time = int(line[1:])
                except ValueError:
                    pass
                continue

            # Single-bit value change: 0id, 1id, xid, zid
            if len(line) >= 2 and line[0] in "01xzXZ":
                val = line[0]
                id_code = line[1:]
                sig = id_to_signal.get(id_code)
                if sig:
                    sig.changes.append(ValueChange(time=current_time, value=val))
                continue

            # Multi-bit value change: b<binary> <id>
            if line.startswith("b") or line.startswith("B"):
                parts = line[1:].split()
                if len(parts) >= 2:
                    binary_val = parts[0]
                    id_code = parts[1]
                    sig = id_to_signal.get(id_code)
                    if sig:
                        # Pad to signal width
                        padded = binary_val.zfill(sig.width)
                        sig.changes.append(ValueChange(time=current_time, value=padded))
                continue

            # Real value change: r<real> <id>
            if line.startswith("r") or line.startswith("R"):
                parts = line[1:].split()
                if len(parts) >= 2:
                    real_val = parts[0]
                    id_code = parts[1]
                    sig = id_to_signal.get(id_code)
                    if sig:
                        sig.changes.append(ValueChange(time=current_time, value=real_val))
                continue

    data.total_time = current_time
    return data


def _parse_timescale(data: WaveformData, text: str) -> None:
    """Parse timescale like '1ns', '10ps', '100fs'."""
    text = text.strip().lower()
    for unit in TimeUnit:
        if text.endswith(unit.value):
            num_str = text[: -len(unit.value)].strip()
            try:
                data.timescale_magnitude = int(num_str) if num_str else 1
            except ValueError:
                data.timescale_magnitude = 1
            data.timescale_unit = unit
            return
