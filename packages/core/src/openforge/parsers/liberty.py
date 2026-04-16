"""Liberty (.lib) timing library parser.

Parses the Liberty format used by OpenSTA and Yosys for timing
characterization data including cell definitions, pin attributes,
and timing arcs with lookup tables.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PinDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"
    INTERNAL = "internal"


class TimingType(StrEnum):
    COMBINATIONAL = "combinational"
    SETUP_RISING = "setup_rising"
    SETUP_FALLING = "setup_falling"
    HOLD_RISING = "hold_rising"
    HOLD_FALLING = "hold_falling"
    RISING_EDGE = "rising_edge"
    FALLING_EDGE = "falling_edge"
    RECOVERY_RISING = "recovery_rising"
    RECOVERY_FALLING = "recovery_falling"
    REMOVAL_RISING = "removal_rising"
    REMOVAL_FALLING = "removal_falling"
    THREE_STATE_ENABLE = "three_state_enable"
    THREE_STATE_DISABLE = "three_state_disable"
    MIN_PULSE_WIDTH = "min_pulse_width"
    MINIMUM_PERIOD = "minimum_period"
    PRESET = "preset"
    CLEAR = "clear"


class TimingSense(StrEnum):
    POSITIVE_UNATE = "positive_unate"
    NEGATIVE_UNATE = "negative_unate"
    NON_UNATE = "non_unate"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LookupTable:
    """NLDM lookup table with two index dimensions."""

    index_1: list[float] = field(default_factory=list)
    index_2: list[float] = field(default_factory=list)
    values: list[list[float]] = field(default_factory=list)


@dataclass
class TimingArc:
    """A timing arc between two pins."""

    related_pin: str = ""
    timing_type: str = "combinational"
    timing_sense: str = "non_unate"
    cell_rise: LookupTable | None = None
    cell_fall: LookupTable | None = None
    rise_transition: LookupTable | None = None
    fall_transition: LookupTable | None = None
    rise_constraint: LookupTable | None = None
    fall_constraint: LookupTable | None = None
    intrinsic_rise: float | None = None
    intrinsic_fall: float | None = None


@dataclass
class LibertyPin:
    """A pin within a Liberty cell."""

    name: str = ""
    direction: str = "input"
    capacitance: float | None = None
    max_transition: float | None = None
    function: str = ""
    three_state: str = ""
    clock: bool = False
    timing_arcs: list[TimingArc] = field(default_factory=list)


@dataclass
class LibertyCell:
    """A standard cell in the Liberty library."""

    name: str = ""
    area: float = 0.0
    cell_leakage_power: float = 0.0
    cell_footprint: str = ""
    is_sequential: bool = False
    function: str = ""
    pins: list[LibertyPin] = field(default_factory=list)

    def get_pin(self, name: str) -> LibertyPin | None:
        """Find a pin by name."""
        for pin in self.pins:
            if pin.name == name:
                return pin
        return None

    def input_pins(self) -> list[LibertyPin]:
        """Return all input pins."""
        return [p for p in self.pins if p.direction == PinDirection.INPUT]

    def output_pins(self) -> list[LibertyPin]:
        """Return all output pins."""
        return [p for p in self.pins if p.direction == PinDirection.OUTPUT]


@dataclass
class LibertyLibrary:
    """Top-level Liberty library representation."""

    name: str = ""
    technology: str = ""
    delay_model: str = ""
    time_unit: str = ""
    voltage_unit: str = ""
    current_unit: str = ""
    capacitive_load_unit: str = ""
    pulling_resistance_unit: str = ""
    leakage_power_unit: str = ""
    nom_process: float = 1.0
    nom_voltage: float = 0.0
    nom_temperature: float = 0.0
    cells: list[LibertyCell] = field(default_factory=list)

    def get_cell(self, name: str) -> LibertyCell | None:
        """Find a cell by name."""
        for cell in self.cells:
            if cell.name == name:
                return cell
        return None

    def get_all_cells(self) -> list[LibertyCell]:
        """Return all cells."""
        return list(self.cells)

    def get_buf_cells(self) -> list[LibertyCell]:
        """Return cells that are buffers (single input, non-inverting output)."""
        result: list[LibertyCell] = []
        for cell in self.cells:
            if cell.is_sequential:
                continue
            inputs = cell.input_pins()
            outputs = cell.output_pins()
            if len(inputs) == 1 and len(outputs) == 1:
                func = outputs[0].function.strip()
                inp_name = inputs[0].name
                if func == inp_name or func == f"({inp_name})":
                    result.append(cell)
        return result

    def get_inv_cells(self) -> list[LibertyCell]:
        """Return cells that are inverters."""
        result: list[LibertyCell] = []
        for cell in self.cells:
            if cell.is_sequential:
                continue
            inputs = cell.input_pins()
            outputs = cell.output_pins()
            if len(inputs) == 1 and len(outputs) == 1:
                func = outputs[0].function.strip()
                inp_name = inputs[0].name
                if func in (f"!{inp_name}", f"(!{inp_name})", f"{inp_name}'"):
                    result.append(cell)
        return result

    def get_ff_cells(self) -> list[LibertyCell]:
        """Return sequential (flip-flop / latch) cells."""
        return [c for c in self.cells if c.is_sequential]

    def cell_names(self) -> list[str]:
        """Return a sorted list of all cell names."""
        return sorted(c.name for c in self.cells)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Regex patterns for the Liberty lexer
_RE_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_COMMENT_LINE = re.compile(r"//.*$", re.MULTILINE)
_RE_LINE_CONTINUATION = re.compile(r"\\\s*\n")
_RE_FLOAT_LIST = re.compile(r'"([^"]*)"')


def _strip_comments(text: str) -> str:
    """Remove block and line comments."""
    text = _RE_COMMENT_BLOCK.sub("", text)
    text = _RE_COMMENT_LINE.sub("", text)
    return text


def _join_continuations(text: str) -> str:
    """Join backslash-continued lines."""
    return _RE_LINE_CONTINUATION.sub(" ", text)


def _parse_float_list(s: str) -> list[float]:
    """Parse a comma/space-separated list of floats from a string."""
    s = s.strip().strip('"')
    if not s:
        return []
    parts = re.split(r"[,\s]+", s.strip())
    result: list[float] = []
    for p in parts:
        p = p.strip()
        if p:
            with contextlib.suppress(ValueError):
                result.append(float(p))
    return result


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class LibertyParser:
    """Streaming parser for Liberty (.lib) timing library files."""

    def parse(self, path: str | Path) -> LibertyLibrary:
        """Parse a Liberty file and return a LibertyLibrary."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Liberty file not found: {path}")

        text = path.read_text(encoding="utf-8", errors="replace")
        text = _strip_comments(text)
        text = _join_continuations(text)

        library = LibertyLibrary()
        lines = text.splitlines()
        idx = 0
        total = len(lines)

        while idx < total:
            line = lines[idx].strip()
            idx += 1

            if not line or line == "}":
                continue

            # Library group header
            m = re.match(r"library\s*\(([^)]*)\)\s*\{?", line)
            if m:
                library.name = m.group(1).strip().strip('"')
                idx = self._parse_library_body(lines, idx, total, library)
                break

        return library

    def _parse_library_body(
        self,
        lines: list[str],
        idx: int,
        total: int,
        lib: LibertyLibrary,
    ) -> int:
        """Parse the body of a library(...) { } group."""
        while idx < total:
            line = lines[idx].strip()
            idx += 1

            if not line:
                continue
            if line == "}":
                break

            # Simple attribute: key : value ;
            attr_m = re.match(r"(\w+)\s*:\s*(.+?)\s*;?\s*$", line)
            if attr_m and "{" not in line:
                key, val = attr_m.group(1), attr_m.group(2).strip().strip('"')
                self._set_library_attr(lib, key, val)
                continue

            # Cell group
            cell_m = re.match(r"cell\s*\(([^)]*)\)\s*\{?\s*$", line)
            if cell_m:
                cell = LibertyCell(name=cell_m.group(1).strip().strip('"'))
                idx = self._parse_cell_body(lines, idx, total, cell)
                lib.cells.append(cell)
                continue

            # Skip other groups (lu_table_template, etc.)
            if "{" in line:
                idx = self._skip_group(lines, idx, total)
                continue

        return idx

    def _parse_cell_body(
        self,
        lines: list[str],
        idx: int,
        total: int,
        cell: LibertyCell,
    ) -> int:
        """Parse the body of a cell(...) { } group."""
        while idx < total:
            line = lines[idx].strip()
            idx += 1

            if not line:
                continue
            if line == "}":
                break

            # Simple attribute
            attr_m = re.match(r"(\w+)\s*:\s*(.+?)\s*;?\s*$", line)
            if attr_m and "{" not in line:
                key, val = attr_m.group(1), attr_m.group(2).strip().strip('"')
                self._set_cell_attr(cell, key, val)
                continue

            # Pin group
            pin_m = re.match(r"pin\s*\(([^)]*)\)\s*\{?\s*$", line)
            if pin_m:
                pin = LibertyPin(name=pin_m.group(1).strip().strip('"'))
                idx = self._parse_pin_body(lines, idx, total, pin, cell)
                cell.pins.append(pin)
                continue

            # ff / latch group marks the cell as sequential
            ff_m = re.match(r"(ff|latch)\s*\(", line)
            if ff_m:
                cell.is_sequential = True
                if "{" in line:
                    idx = self._skip_group(lines, idx, total)
                continue

            # Skip other groups
            if "{" in line:
                idx = self._skip_group(lines, idx, total)
                continue

        return idx

    def _parse_pin_body(
        self,
        lines: list[str],
        idx: int,
        total: int,
        pin: LibertyPin,
        cell: LibertyCell,
    ) -> int:
        """Parse the body of a pin(...) { } group."""
        while idx < total:
            line = lines[idx].strip()
            idx += 1

            if not line:
                continue
            if line == "}":
                break

            # Simple attribute
            attr_m = re.match(r"(\w+)\s*:\s*(.+?)\s*;?\s*$", line)
            if attr_m and "{" not in line:
                key, val = attr_m.group(1), attr_m.group(2).strip().strip('"')
                self._set_pin_attr(pin, key, val)
                # Capture output function for cell-level convenience
                if key == "function" and pin.direction == PinDirection.OUTPUT:
                    cell.function = val
                continue

            # Timing group
            timing_m = re.match(r"timing\s*\(\s*\)\s*\{?\s*$", line)
            if timing_m:
                arc = TimingArc()
                idx = self._parse_timing_body(lines, idx, total, arc)
                pin.timing_arcs.append(arc)
                continue

            # Skip other sub-groups (internal_power, etc.)
            if "{" in line:
                idx = self._skip_group(lines, idx, total)
                continue

        return idx

    def _parse_timing_body(
        self,
        lines: list[str],
        idx: int,
        total: int,
        arc: TimingArc,
    ) -> int:
        """Parse the body of a timing() { } group."""
        while idx < total:
            line = lines[idx].strip()
            idx += 1

            if not line:
                continue
            if line == "}":
                break

            # Simple attribute
            attr_m = re.match(r"(\w+)\s*:\s*(.+?)\s*;?\s*$", line)
            if attr_m and "{" not in line:
                key, val = attr_m.group(1), attr_m.group(2).strip().strip('"')
                if key == "related_pin":
                    arc.related_pin = val
                elif key == "timing_type":
                    arc.timing_type = val
                elif key == "timing_sense":
                    arc.timing_sense = val
                elif key == "intrinsic_rise":
                    arc.intrinsic_rise = _safe_float(val)
                elif key == "intrinsic_fall":
                    arc.intrinsic_fall = _safe_float(val)
                continue

            # LUT groups
            lut_m = re.match(r"(cell_rise|cell_fall|rise_transition|fall_transition|rise_constraint|fall_constraint)\s*\(([^)]*)\)\s*\{?\s*$", line)
            if lut_m:
                lut = LookupTable()
                idx = self._parse_lut_body(lines, idx, total, lut)
                setattr(arc, lut_m.group(1), lut)
                continue

            # Skip other groups
            if "{" in line:
                idx = self._skip_group(lines, idx, total)
                continue

        return idx

    def _parse_lut_body(
        self,
        lines: list[str],
        idx: int,
        total: int,
        lut: LookupTable,
    ) -> int:
        """Parse a lookup table group body."""
        collecting_values = False
        value_buf: list[str] = []

        while idx < total:
            line = lines[idx].strip()
            idx += 1

            if not line:
                continue
            if line == "}":
                break

            # index_1 / index_2
            idx_m = re.match(r"(index_[12])\s*\((.+)\)\s*;?\s*$", line)
            if idx_m:
                vals = _parse_float_list(idx_m.group(2))
                if idx_m.group(1) == "index_1":
                    lut.index_1 = vals
                else:
                    lut.index_2 = vals
                continue

            # values(...)
            val_m = re.match(r"values\s*\((.*)$", line)
            if val_m:
                rest = val_m.group(1)
                if ")" in rest:
                    # Single-line values
                    rest = rest[: rest.index(")")]
                    self._parse_values_block(rest, lut)
                else:
                    collecting_values = True
                    value_buf.append(rest)
                continue

            if collecting_values:
                if ")" in line:
                    value_buf.append(line[: line.index(")")])
                    self._parse_values_block(" ".join(value_buf), lut)
                    collecting_values = False
                    value_buf.clear()
                else:
                    value_buf.append(line)
                continue

        return idx

    @staticmethod
    def _parse_values_block(text: str, lut: LookupTable) -> None:
        """Parse the inner content of a values(...) block into 2D floats."""
        # Values may be split into quoted rows: "v1, v2, v3", \
        # or just comma/whitespace separated
        rows: list[list[float]] = []
        # Try to find quoted segments first
        quoted = _RE_FLOAT_LIST.findall(text)
        if quoted:
            for q in quoted:
                row = _parse_float_list(q)
                if row:
                    rows.append(row)
        else:
            # Flat list -- wrap in a single row
            flat = _parse_float_list(text)
            if flat:
                rows.append(flat)
        lut.values = rows

    @staticmethod
    def _skip_group(lines: list[str], idx: int, total: int) -> int:
        """Skip past a { ... } group, handling nesting."""
        depth = 1
        while idx < total and depth > 0:
            line = lines[idx].strip()
            idx += 1
            depth += line.count("{") - line.count("}")
        return idx

    # ---------------------------------------------------------------
    # Attribute setters
    # ---------------------------------------------------------------

    @staticmethod
    def _set_library_attr(lib: LibertyLibrary, key: str, val: str) -> None:
        attr_map = {
            "technology": "technology",
            "delay_model": "delay_model",
            "time_unit": "time_unit",
            "voltage_unit": "voltage_unit",
            "current_unit": "current_unit",
            "pulling_resistance_unit": "pulling_resistance_unit",
            "leakage_power_unit": "leakage_power_unit",
        }
        if key in attr_map:
            setattr(lib, attr_map[key], val)
        elif key == "capacitive_load_unit":
            lib.capacitive_load_unit = val
        elif key == "nom_process":
            lib.nom_process = _safe_float(val, 1.0)
        elif key == "nom_voltage":
            lib.nom_voltage = _safe_float(val, 0.0)
        elif key == "nom_temperature":
            lib.nom_temperature = _safe_float(val, 0.0)

    @staticmethod
    def _set_cell_attr(cell: LibertyCell, key: str, val: str) -> None:
        if key == "area":
            cell.area = _safe_float(val)
        elif key == "cell_leakage_power":
            cell.cell_leakage_power = _safe_float(val)
        elif key == "cell_footprint":
            cell.cell_footprint = val

    @staticmethod
    def _set_pin_attr(pin: LibertyPin, key: str, val: str) -> None:
        if key == "direction":
            pin.direction = val
        elif key == "capacitance":
            pin.capacitance = _safe_float(val)
        elif key == "max_transition":
            pin.max_transition = _safe_float(val)
        elif key == "function":
            pin.function = val
        elif key == "three_state":
            pin.three_state = val
        elif key == "clock" and val.lower() in ("true", "1"):
            pin.clock = True


def _safe_float(val: str, default: float = 0.0) -> float:
    """Convert a string to float, returning *default* on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
