"""Pure-Python lightweight Liberty (.lib) parser.

Only extracts cells, pins, area, function, and basic timing arcs - enough
to populate a cell library browser. Skips lookup tables and power tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LibertyPin:
    name: str
    direction: str = "input"
    function: str | None = None
    capacitance: float = 0.0
    max_capacitance: float = 0.0
    related_power_pin: str | None = None


@dataclass
class LibertyTimingArc:
    related_pin: str
    sense: str = "non_unate"
    delay_rise_typ: float = 0.0
    delay_fall_typ: float = 0.0


@dataclass
class LibertyCell:
    name: str
    area: float = 0.0
    pins: dict[str, LibertyPin] = field(default_factory=dict)
    timing_arcs: list[LibertyTimingArc] = field(default_factory=list)
    leakage_power: float = 0.0
    is_sequential: bool = False
    is_combinational: bool = True


@dataclass
class LibertyLibrary:
    name: str
    technology: str = "cmos"
    voltage: float = 0.0
    temperature: float = 25.0
    cells: dict[str, LibertyCell] = field(default_factory=dict)


# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(
    r"""
    \s* (
        /\*.*?\*/                       # block comment
      | //[^\n]*                        # line comment
      | "(?:[^"\\]|\\.)*"               # quoted string
      | [{}();:,]                       # punctuation
      | [^\s{}();:,"]+                  # bare token
    )
    """,
    re.VERBOSE | re.DOTALL,
)


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(1)
        if tok.startswith("/*") or tok.startswith("//"):
            continue
        tokens.append(tok)
    return tokens


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _to_float(s: str, default: float = 0.0) -> float:
    try:
        return float(_strip_quotes(s))
    except (ValueError, TypeError):
        return default


def _first_float(s: str, default: float = 0.0) -> float:
    """Extract first float from a (possibly comma-separated) values string."""
    s = _strip_quotes(s).strip()
    if not s:
        return default
    # split on whitespace or comma
    for piece in re.split(r"[,\s]+", s):
        piece = piece.strip()
        if piece:
            try:
                return float(piece)
            except ValueError:
                continue
    return default


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def peek(self, off: int = 0) -> str | None:
        idx = self.pos + off
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def advance(self) -> str | None:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok

    def expect(self, tok: str) -> bool:
        if self.peek() == tok:
            self.advance()
            return True
        return False

    def skip_block(self) -> None:
        """Skip a {...} block, assuming current token is '{'."""
        if not self.expect("{"):
            return
        depth = 1
        while depth > 0 and self.pos < len(self.tokens):
            tok = self.advance()
            if tok == "{":
                depth += 1
            elif tok == "}":
                depth -= 1

    def parse_args(self) -> list[str]:
        """Parse a (...) argument list and return token list."""
        args: list[str] = []
        if not self.expect("("):
            return args
        while self.pos < len(self.tokens):
            tok = self.peek()
            if tok == ")":
                self.advance()
                break
            if tok == ",":
                self.advance()
                continue
            args.append(_strip_quotes(self.advance() or ""))
        return args


def parse_liberty(filepath: Path) -> LibertyLibrary:
    """Parse a Liberty file and return a LibertyLibrary."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    tokens = _tokenize(text)
    p = _Parser(tokens)

    library = LibertyLibrary(name=path.stem)

    # Find 'library' keyword
    while p.pos < len(p.tokens):
        tok = p.advance()
        if tok == "library":
            args = p.parse_args()
            if args:
                library.name = args[0]
            if p.expect("{"):
                _parse_library_body(p, library)
            break
    return library


def _parse_library_body(p: _Parser, library: LibertyLibrary) -> None:
    depth = 1
    while p.pos < len(p.tokens) and depth > 0:
        tok = p.peek()
        if tok is None:
            break
        if tok == "}":
            p.advance()
            depth -= 1
            continue
        if tok == "{":
            p.advance()
            depth += 1
            continue

        # Look ahead for cell definition
        if tok == "cell":
            p.advance()
            args = p.parse_args()
            cell_name = args[0] if args else "?"
            if p.expect("{"):
                cell = _parse_cell_body(p, cell_name)
                library.cells[cell.name] = cell
            continue

        if tok == "technology":
            p.advance()
            args = p.parse_args()
            if args:
                library.technology = args[0]
            # optional ;
            p.expect(";")
            continue

        if tok == "nom_voltage":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "0"
                library.voltage = _to_float(val)
                p.expect(";")
            continue

        if tok == "nom_temperature":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "25"
                library.temperature = _to_float(val)
                p.expect(";")
            continue

        # Generic statement: skip
        _skip_statement(p)


def _skip_statement(p: _Parser) -> None:
    """Skip a single statement (simple attribute or compound group)."""
    # consume one identifier
    p.advance()
    # If followed by '(', skip its args
    if p.peek() == "(":
        p.parse_args()
    # If followed by ':', it's a simple attribute -> consume until ';'
    if p.peek() == ":":
        p.advance()
        while p.pos < len(p.tokens):
            t = p.advance()
            if t == ";" or t is None:
                break
        return
    # If followed by '{', it's a group -> skip block
    if p.peek() == "{":
        p.skip_block()
        return
    # otherwise consume optional ;
    p.expect(";")


def _parse_cell_body(p: _Parser, cell_name: str) -> LibertyCell:
    cell = LibertyCell(name=cell_name)
    depth = 1
    while p.pos < len(p.tokens) and depth > 0:
        tok = p.peek()
        if tok is None:
            break
        if tok == "}":
            p.advance()
            depth -= 1
            continue
        if tok == "{":
            p.advance()
            depth += 1
            continue

        if tok == "area":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "0"
                cell.area = _to_float(val)
                p.expect(";")
            continue

        if tok == "cell_leakage_power":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "0"
                cell.leakage_power = _to_float(val)
                p.expect(";")
            continue

        if tok in ("ff", "latch"):
            cell.is_sequential = True
            cell.is_combinational = False
            p.advance()
            if p.peek() == "(":
                p.parse_args()
            if p.peek() == "{":
                p.skip_block()
            continue

        if tok == "pin":
            p.advance()
            args = p.parse_args()
            pin_name = args[0] if args else "?"
            if p.expect("{"):
                pin, arcs = _parse_pin_body(p, pin_name)
                cell.pins[pin.name] = pin
                cell.timing_arcs.extend(arcs)
            continue

        _skip_statement(p)
    return cell


def _parse_pin_body(p: _Parser, pin_name: str) -> tuple[LibertyPin, list[LibertyTimingArc]]:
    pin = LibertyPin(name=pin_name)
    arcs: list[LibertyTimingArc] = []
    depth = 1
    while p.pos < len(p.tokens) and depth > 0:
        tok = p.peek()
        if tok is None:
            break
        if tok == "}":
            p.advance()
            depth -= 1
            continue
        if tok == "{":
            p.advance()
            depth += 1
            continue

        if tok == "direction":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "input"
                pin.direction = _strip_quotes(val)
                p.expect(";")
            continue

        if tok == "function":
            p.advance()
            if p.expect(":"):
                val = p.advance() or ""
                pin.function = _strip_quotes(val)
                p.expect(";")
            continue

        if tok == "capacitance":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "0"
                pin.capacitance = _to_float(val)
                p.expect(";")
            continue

        if tok == "max_capacitance":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "0"
                pin.max_capacitance = _to_float(val)
                p.expect(";")
            continue

        if tok == "related_power_pin":
            p.advance()
            if p.expect(":"):
                val = p.advance() or ""
                pin.related_power_pin = _strip_quotes(val)
                p.expect(";")
            continue

        if tok == "timing":
            p.advance()
            if p.peek() == "(":
                p.parse_args()
            if p.expect("{"):
                arc = _parse_timing_body(p)
                if arc is not None:
                    arcs.append(arc)
            continue

        _skip_statement(p)
    return pin, arcs


def _parse_timing_body(p: _Parser) -> LibertyTimingArc | None:
    arc = LibertyTimingArc(related_pin="")
    depth = 1
    while p.pos < len(p.tokens) and depth > 0:
        tok = p.peek()
        if tok is None:
            break
        if tok == "}":
            p.advance()
            depth -= 1
            continue
        if tok == "{":
            p.advance()
            depth += 1
            continue

        if tok == "related_pin":
            p.advance()
            if p.expect(":"):
                val = p.advance() or ""
                arc.related_pin = _strip_quotes(val)
                p.expect(";")
            continue

        if tok == "timing_sense":
            p.advance()
            if p.expect(":"):
                val = p.advance() or "non_unate"
                arc.sense = _strip_quotes(val)
                p.expect(";")
            continue

        if tok in ("cell_rise", "cell_fall"):
            kind = tok
            p.advance()
            if p.peek() == "(":
                p.parse_args()
            if p.expect("{"):
                val = _extract_first_values(p)
                if kind == "cell_rise":
                    arc.delay_rise_typ = val
                else:
                    arc.delay_fall_typ = val
            continue

        _skip_statement(p)
    return arc if arc.related_pin else arc


def _extract_first_values(p: _Parser) -> float:
    """Inside a cell_rise/cell_fall block, find first 'values(...)' and grab first float."""
    depth = 1
    result = 0.0
    while p.pos < len(p.tokens) and depth > 0:
        tok = p.peek()
        if tok is None:
            break
        if tok == "}":
            p.advance()
            depth -= 1
            continue
        if tok == "{":
            p.advance()
            depth += 1
            continue
        if tok == "values":
            p.advance()
            args = p.parse_args()
            if args and result == 0.0:
                result = _first_float(args[0])
            p.expect(";")
            continue
        _skip_statement(p)
    return result
