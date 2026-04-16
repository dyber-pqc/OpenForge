"""KiCad symbol library parser (.kicad_sym S-expression format).

Parses KiCad 6/7/8 ``.kicad_sym`` files into OpenForge :class:`SchSymbol`
/ :class:`SchPin` records.  A small, dependency-free recursive
S-expression tokenizer is included so we do not need ``sexpdata``.

Only the features we actually care about are supported:

* ``(symbol "name" ...)`` top-level symbol blocks
* ``(property "Reference|Value|Footprint|Datasheet|ki_keywords|ki_description" ...)``
* ``(pin <direction> <style> (at x y rot) (length L) (name "n") (number "N"))``
* multi-unit symbols (we collapse to unit 1 / common)
* simple graphic body (rectangle/circle/polyline/arc) to derive bbox

The parser is intentionally *defensive*: malformed blocks are skipped
with a log message rather than raising.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openforge_desktop.widgets.schematic_editor import SchPin, SchSymbol


# ---------------------------------------------------------------------------
# Fallback local SchSymbol/SchPin definitions
# ---------------------------------------------------------------------------

# We cannot import the desktop package from the core package at runtime
# (core must not depend on PySide6).  We therefore mirror the dataclasses
# here with the *same field names* so duck-typing works on both sides.


@dataclass
class _LocalSchPin:
    name: str
    number: str
    direction: str
    x: float
    y: float
    length: float = 100.0
    orientation: str = "right"


@dataclass
class _LocalSchSymbol:
    name: str
    library: str
    description: str = ""
    keywords: str = ""
    width: float = 200.0
    height: float = 200.0
    pins: list[_LocalSchPin] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    body_shape: str = "rectangle"


# These will be rebound to the desktop dataclasses if the desktop package is
# importable, but default to the local fallbacks so core works standalone.
SchPin: Any = _LocalSchPin
SchSymbol: Any = _LocalSchSymbol


def _try_bind_desktop_models() -> None:
    global SchPin, SchSymbol
    try:  # pragma: no cover - only when desktop is installed
        from openforge_desktop.widgets.schematic_editor import (  # type: ignore
            SchPin as _SP,
            SchSymbol as _SS,
        )

        SchPin = _SP
        SchSymbol = _SS
    except Exception:
        pass


_try_bind_desktop_models()


# ---------------------------------------------------------------------------
# S-expression tokenizer / parser
# ---------------------------------------------------------------------------


def tokenize_sexpr(text: str) -> list[str]:
    """Return a flat list of tokens from an S-expression string."""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch in "()":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            # String literal - handle escapes
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append('"' + "".join(buf) + '"')
            continue
        # Atom
        j = i
        while j < n and text[j] not in " \t\r\n()":
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def parse_sexpr(text: str) -> list:
    """Parse S-expression *text* into nested lists of strings.

    String literals keep their surrounding double quotes so we can tell
    them apart from symbols.
    """
    tokens = tokenize_sexpr(text)
    pos = 0

    def walk() -> list:
        nonlocal pos
        if pos >= len(tokens):
            return []
        tok = tokens[pos]
        if tok != "(":
            raise ValueError(f"Expected '(' at token {pos}, got {tok!r}")
        pos += 1
        out: list = []
        while pos < len(tokens):
            t = tokens[pos]
            if t == ")":
                pos += 1
                return out
            if t == "(":
                out.append(walk())
            else:
                out.append(t)
                pos += 1
        return out

    # Skip leading whitespace tokens; accept a single top-level expression.
    while pos < len(tokens) and tokens[pos] != "(":
        pos += 1
    if pos >= len(tokens):
        return []
    return walk()


# ---------------------------------------------------------------------------
# Small helpers for walking the parsed tree
# ---------------------------------------------------------------------------


def _is_list(x: Any) -> bool:
    return isinstance(x, list)


def _head(node: Any) -> str | None:
    if _is_list(node) and node and isinstance(node[0], str):
        return node[0]
    return None


def _children(node: list, tag: str) -> list[list]:
    return [c for c in node if _is_list(c) and _head(c) == tag]


def _first(node: list, tag: str) -> list | None:
    for c in node:
        if _is_list(c) and _head(c) == tag:
            return c
    return None


def _unquote(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _num(s: Any, default: float = 0.0) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Pin direction mapping
# ---------------------------------------------------------------------------


# KiCad pin electrical types -> OpenForge SchPin.direction
_KICAD_PIN_DIR = {
    "input": "input",
    "output": "output",
    "bidirectional": "bidirectional",
    "tri_state": "bidirectional",
    "passive": "passive",
    "free": "passive",
    "unspecified": "passive",
    "power_in": "power_in",
    "power_out": "power_out",
    "open_collector": "output",
    "open_emitter": "output",
    "no_connect": "passive",
}


def _map_pin_direction(kicad_dir: str) -> str:
    return _KICAD_PIN_DIR.get(kicad_dir, "passive")


# KiCad pin rotation (0/90/180/270) -> our orientation names.
# KiCad rotation is the *direction the pin points* from its anchor point.
def _rot_to_orient(rot: float) -> str:
    r = int(round(rot)) % 360
    return {0: "right", 90: "up", 180: "left", 270: "down"}.get(r, "right")


# ---------------------------------------------------------------------------
# Symbol block parsers
# ---------------------------------------------------------------------------


def _parse_pin(node: list) -> _LocalSchPin | None:
    # node = ["pin", "<dir>", "<style>", (at x y rot), (length L),
    #         (name "n" ...), (number "N" ...), ...]
    try:
        kdir = node[1] if len(node) > 1 and isinstance(node[1], str) else "passive"
        at = _first(node, "at")
        length_node = _first(node, "length")
        name_node = _first(node, "name")
        number_node = _first(node, "number")

        x = _num(at[1]) if at and len(at) >= 2 else 0.0
        y = _num(at[2]) if at and len(at) >= 3 else 0.0
        rot = _num(at[3]) if at and len(at) >= 4 else 0.0
        length = _num(length_node[1]) if length_node and len(length_node) >= 2 else 100.0
        name = _unquote(name_node[1]) if name_node and len(name_node) >= 2 else "~"
        number = _unquote(number_node[1]) if number_node and len(number_node) >= 2 else ""

        # KiCad uses mm; OpenForge SchPin uses mils.  1mm = ~39.37 mil.
        # But KiCad also uses 1mil-ish native units in some cases.  We
        # convert mm -> mil and flip Y so the symbol renders with our
        # top-left orientation.
        scale = 39.3701
        return _LocalSchPin(
            name=name or "~",
            number=number or name or "?",
            direction=_map_pin_direction(kdir),
            x=x * scale,
            y=-y * scale,
            length=max(length * scale, 50.0),
            orientation=_rot_to_orient(rot),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("skip malformed pin: %s", exc)
        return None


def _parse_properties(node: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for prop in _children(node, "property"):
        if len(prop) < 3:
            continue
        key = _unquote(prop[1])
        val = _unquote(prop[2])
        if key:
            out[key] = val
    return out


def _collect_graphics_bbox(node: list) -> tuple[float, float, float, float]:
    minx = miny = math.inf
    maxx = maxy = -math.inf

    def upd(x: float, y: float) -> None:
        nonlocal minx, miny, maxx, maxy
        if x < minx:
            minx = x
        if x > maxx:
            maxx = x
        if y < miny:
            miny = y
        if y > maxy:
            maxy = y

    def recurse(blk: list) -> None:
        tag = _head(blk) or ""
        if tag == "rectangle":
            s = _first(blk, "start")
            e = _first(blk, "end")
            if s and e and len(s) >= 3 and len(e) >= 3:
                upd(_num(s[1]), _num(s[2]))
                upd(_num(e[1]), _num(e[2]))
        elif tag == "circle":
            c = _first(blk, "center")
            r = _first(blk, "radius")
            if c and r and len(c) >= 3 and len(r) >= 2:
                cx, cy, rad = _num(c[1]), _num(c[2]), _num(r[1])
                upd(cx - rad, cy - rad)
                upd(cx + rad, cy + rad)
        elif tag == "polyline":
            pts = _first(blk, "pts")
            if pts:
                for p in _children(pts, "xy"):
                    if len(p) >= 3:
                        upd(_num(p[1]), _num(p[2]))
        elif tag == "arc":
            for sub in ("start", "mid", "end"):
                s = _first(blk, sub)
                if s and len(s) >= 3:
                    upd(_num(s[1]), _num(s[2]))
        # Recurse into sub-blocks (for multi-unit symbol child symbols).
        for c in blk:
            if _is_list(c):
                recurse(c)

    recurse(node)
    if minx is math.inf:
        return (0.0, 0.0, 200.0, 200.0)
    return (minx, miny, maxx, maxy)


def _parse_symbol(node: list, library: str) -> _LocalSchSymbol | None:
    # node = ["symbol", "\"name\"", ...]
    try:
        if len(node) < 2 or not isinstance(node[1], str):
            return None
        raw_name = _unquote(node[1])
        # Multi-unit child symbols look like "NAME_unit_style"; we only
        # want the parent symbol entry and we fold unit-1 pins back in.
        props = _parse_properties(node)
        desc = props.get("ki_description") or props.get("Description", "")
        keywords = props.get("ki_keywords", "")
        footprint = props.get("Footprint", "")
        value = props.get("Value", raw_name)

        # Walk all direct and nested sub-symbols to collect pins.  KiCad
        # stores per-unit pins inside ``(symbol "NAME_1_1" ...)`` blocks.
        pins: list[_LocalSchPin] = []

        def collect_pins(blk: list) -> None:
            for c in blk:
                if not _is_list(c):
                    continue
                tag = _head(c)
                if tag == "pin":
                    p = _parse_pin(c)
                    if p is not None:
                        pins.append(p)
                elif tag == "symbol":
                    # child unit symbol - only unit 1
                    if len(c) >= 2 and isinstance(c[1], str):
                        child_name = _unquote(c[1])
                        # pattern: <parent>_<unit>_<style>
                        parts = child_name.rsplit("_", 2)
                        if len(parts) == 3 and parts[1].isdigit():
                            if parts[1] not in ("1", "0"):
                                continue
                    collect_pins(c)

        collect_pins(node)

        # De-duplicate pins by (number, x, y)
        seen: set[tuple[str, float, float]] = set()
        uniq_pins: list[_LocalSchPin] = []
        for p in pins:
            key = (p.number, round(p.x, 1), round(p.y, 1))
            if key in seen:
                continue
            seen.add(key)
            uniq_pins.append(p)

        bbox = _collect_graphics_bbox(node)
        w = max((bbox[2] - bbox[0]) * 39.3701, 200.0)
        h = max((bbox[3] - bbox[1]) * 39.3701, 200.0)

        sym = _LocalSchSymbol(
            name=raw_name,
            library=library,
            description=desc,
            keywords=keywords,
            width=w,
            height=h,
            pins=uniq_pins,
            fields={"value": value, "footprint": footprint},
            body_shape="rectangle",
        )
        return sym
    except Exception as exc:
        log.debug("skip malformed symbol %r: %s", node[:2], exc)
        return None


def _coerce_to_runtime(sym: _LocalSchSymbol) -> Any:
    """Convert our local symbol to the desktop SchSymbol if available."""
    if SchSymbol is _LocalSchSymbol:
        return sym
    try:
        runtime_pins = [
            SchPin(
                name=p.name,
                number=p.number,
                direction=p.direction,
                x=p.x,
                y=p.y,
                length=p.length,
                orientation=p.orientation,
            )
            for p in sym.pins
        ]
        return SchSymbol(
            name=sym.name,
            library=sym.library,
            description=sym.description,
            keywords=sym.keywords,
            width=sym.width,
            height=sym.height,
            pins=runtime_pins,
            fields=dict(sym.fields),
            body_shape=sym.body_shape,
        )
    except Exception:  # pragma: no cover - defensive
        return sym


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_kicad_sym_text(text: str, library: str = "Unknown") -> dict[str, Any]:
    """Parse *text* (contents of a .kicad_sym file) into a symbol dict."""
    try:
        tree = parse_sexpr(text)
    except Exception as exc:
        log.warning("failed to tokenize .kicad_sym for %s: %s", library, exc)
        return {}
    if not _is_list(tree) or _head(tree) != "kicad_symbol_lib":
        log.debug("not a kicad_symbol_lib root in %s", library)
        return {}

    out: dict[str, Any] = {}
    for child in _children(tree, "symbol"):
        sym = _parse_symbol(child, library)
        if sym is None:
            continue
        out[sym.name] = _coerce_to_runtime(sym)
    return out


def parse_kicad_sym_file(path: Path) -> dict[str, Any]:
    """Parse a .kicad_sym file and return ``{symbol_name: SchSymbol}``."""
    p = Path(path)
    library = p.stem
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("cannot read %s: %s", p, exc)
        return {}
    return parse_kicad_sym_text(text, library=library)


__all__ = [
    "parse_kicad_sym_file",
    "parse_kicad_sym_text",
    "parse_sexpr",
    "tokenize_sexpr",
    "SchPin",
    "SchSymbol",
]
