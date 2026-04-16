"""KiCad footprint (.kicad_mod) S-expression parser.

Converts KiCad footprint modules into an OpenForge :class:`PcbFootprint`.
The footprint model is defined by a sibling module ``pcb.model`` that is
currently being written by another agent; we try to import it and fall
back to a local minimal definition with identical field names when it
is not present.

Only the elements we actually consume from real libraries are supported:

* ``(footprint "name" ...)``
* ``(layer "F.Cu")``, ``(descr ...)``, ``(tags ...)``
* ``(pad "N" smd|thru_hole|np_thru_hole|connect <shape> (at ...)
      (size ...) (drill ...) (layers ...))``
* ``(fp_line|fp_arc|fp_circle|fp_rect ... (layer "F.SilkS"))``
* ``(fp_text reference|value|user ...)``
* ``(model "path" ...)``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openforge.pcb.kicad_sym_parser import (
    _children,
    _first,
    _head,
    _is_list,
    _num,
    _unquote,
    parse_sexpr,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local fallback footprint model
# ---------------------------------------------------------------------------


@dataclass
class _LocalPcbPad:
    number: str
    pad_type: str  # smd / thru_hole / np_thru_hole / connect
    shape: str  # rect / circle / oval / roundrect / trapezoid
    x: float
    y: float
    rotation: float = 0.0
    width: float = 0.0
    height: float = 0.0
    drill: float = 0.0
    layers: list[str] = field(default_factory=list)


@dataclass
class _LocalPcbLine:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "F.SilkS"
    width: float = 0.12


@dataclass
class _LocalPcbArc:
    start_x: float
    start_y: float
    mid_x: float
    mid_y: float
    end_x: float
    end_y: float
    layer: str = "F.SilkS"
    width: float = 0.12


@dataclass
class _LocalPcbCircle:
    center_x: float
    center_y: float
    end_x: float
    end_y: float
    layer: str = "F.SilkS"
    width: float = 0.12


@dataclass
class _LocalPcbRect:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "F.SilkS"
    width: float = 0.12


@dataclass
class _LocalPcbText:
    text: str
    kind: str  # reference / value / user
    x: float
    y: float
    layer: str = "F.SilkS"


@dataclass
class _LocalPcbFootprint:
    name: str
    library: str = ""
    description: str = ""
    tags: str = ""
    layer: str = "F.Cu"
    pads: list[_LocalPcbPad] = field(default_factory=list)
    lines: list[_LocalPcbLine] = field(default_factory=list)
    arcs: list[_LocalPcbArc] = field(default_factory=list)
    circles: list[_LocalPcbCircle] = field(default_factory=list)
    rectangles: list[_LocalPcbRect] = field(default_factory=list)
    texts: list[_LocalPcbText] = field(default_factory=list)
    models: list[str] = field(default_factory=list)


# Try to bind to the external model if the sibling agent has produced it.
PcbFootprint: Any = _LocalPcbFootprint
PcbPad: Any = _LocalPcbPad
PcbLine: Any = _LocalPcbLine
PcbArc: Any = _LocalPcbArc
PcbCircle: Any = _LocalPcbCircle
PcbRect: Any = _LocalPcbRect
PcbText: Any = _LocalPcbText


def _try_bind_external_model() -> None:
    global PcbFootprint, PcbPad, PcbLine, PcbArc, PcbCircle, PcbRect, PcbText
    try:
        from openforge.pcb import model as _m  # type: ignore

        PcbFootprint = getattr(_m, "PcbFootprint", PcbFootprint)
        PcbPad = getattr(_m, "PcbPad", PcbPad)
        PcbLine = getattr(_m, "PcbLine", PcbLine)
        PcbArc = getattr(_m, "PcbArc", PcbArc)
        PcbCircle = getattr(_m, "PcbCircle", PcbCircle)
        PcbRect = getattr(_m, "PcbRect", PcbRect)
        PcbText = getattr(_m, "PcbText", PcbText)
    except Exception:
        pass


_try_bind_external_model()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _layers_of(node: list) -> list[str]:
    layers_node = _first(node, "layers")
    if not layers_node:
        return []
    out: list[str] = []
    for t in layers_node[1:]:
        if isinstance(t, str):
            out.append(_unquote(t))
    return out


def _parse_pad(node: list) -> _LocalPcbPad | None:
    # node = ["pad", "\"1\"", "smd", "rect", (at x y [rot]), (size w h),
    #         (drill ...), (layers ...)]
    try:
        if len(node) < 4:
            return None
        number = _unquote(node[1])
        pad_type = node[2] if isinstance(node[2], str) else "smd"
        shape = node[3] if isinstance(node[3], str) else "rect"
        at = _first(node, "at")
        size = _first(node, "size")
        drill = _first(node, "drill")
        x = _num(at[1]) if at and len(at) >= 2 else 0.0
        y = _num(at[2]) if at and len(at) >= 3 else 0.0
        rot = _num(at[3]) if at and len(at) >= 4 else 0.0
        w = _num(size[1]) if size and len(size) >= 2 else 0.0
        h = _num(size[2]) if size and len(size) >= 3 else w
        # Drill may be ("drill" d) or ("drill" "oval" d d) - take first numeric.
        drill_v = 0.0
        if drill:
            for t in drill[1:]:
                if isinstance(t, str):
                    try:
                        drill_v = float(t)
                        break
                    except ValueError:
                        continue
        layers = _layers_of(node)
        return _LocalPcbPad(
            number=number,
            pad_type=pad_type,
            shape=shape,
            x=x,
            y=y,
            rotation=rot,
            width=w,
            height=h,
            drill=drill_v,
            layers=layers,
        )
    except Exception as exc:
        log.debug("skip malformed pad: %s", exc)
        return None


def _layer_of(node: list, default: str = "F.SilkS") -> str:
    layer = _first(node, "layer")
    if layer and len(layer) >= 2 and isinstance(layer[1], str):
        return _unquote(layer[1])
    return default


def _width_of(node: list, default: float = 0.12) -> float:
    w = _first(node, "width") or _first(node, "stroke")
    if not w:
        return default
    # (width X) or (stroke (width X) ...)
    if _head(w) == "width" and len(w) >= 2:
        return _num(w[1], default)
    inner = _first(w, "width")
    if inner and len(inner) >= 2:
        return _num(inner[1], default)
    return default


def _parse_fp_line(node: list) -> _LocalPcbLine | None:
    try:
        s = _first(node, "start")
        e = _first(node, "end")
        if not s or not e:
            return None
        return _LocalPcbLine(
            x1=_num(s[1]),
            y1=_num(s[2]),
            x2=_num(e[1]),
            y2=_num(e[2]),
            layer=_layer_of(node),
            width=_width_of(node),
        )
    except Exception:
        return None


def _parse_fp_arc(node: list) -> _LocalPcbArc | None:
    try:
        s = _first(node, "start")
        m = _first(node, "mid")
        e = _first(node, "end")
        if not s or not e:
            return None
        if m is None:
            m = s
        return _LocalPcbArc(
            start_x=_num(s[1]),
            start_y=_num(s[2]),
            mid_x=_num(m[1]),
            mid_y=_num(m[2]),
            end_x=_num(e[1]),
            end_y=_num(e[2]),
            layer=_layer_of(node),
            width=_width_of(node),
        )
    except Exception:
        return None


def _parse_fp_circle(node: list) -> _LocalPcbCircle | None:
    try:
        c = _first(node, "center")
        e = _first(node, "end")
        if not c or not e:
            return None
        return _LocalPcbCircle(
            center_x=_num(c[1]),
            center_y=_num(c[2]),
            end_x=_num(e[1]),
            end_y=_num(e[2]),
            layer=_layer_of(node),
            width=_width_of(node),
        )
    except Exception:
        return None


def _parse_fp_rect(node: list) -> _LocalPcbRect | None:
    try:
        s = _first(node, "start")
        e = _first(node, "end")
        if not s or not e:
            return None
        return _LocalPcbRect(
            x1=_num(s[1]),
            y1=_num(s[2]),
            x2=_num(e[1]),
            y2=_num(e[2]),
            layer=_layer_of(node),
            width=_width_of(node),
        )
    except Exception:
        return None


def _parse_fp_text(node: list) -> _LocalPcbText | None:
    try:
        if len(node) < 3:
            return None
        kind = node[1] if isinstance(node[1], str) else "user"
        text = _unquote(node[2])
        at = _first(node, "at")
        x = _num(at[1]) if at and len(at) >= 2 else 0.0
        y = _num(at[2]) if at and len(at) >= 3 else 0.0
        return _LocalPcbText(
            text=text, kind=kind, x=x, y=y, layer=_layer_of(node, "F.SilkS")
        )
    except Exception:
        return None


def _coerce_footprint(fp: _LocalPcbFootprint) -> Any:
    if PcbFootprint is _LocalPcbFootprint:
        return fp
    # Best-effort conversion: try to construct with the same kwargs.
    try:
        return PcbFootprint(**fp.__dict__)  # type: ignore[arg-type]
    except Exception:
        return fp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_kicad_mod_text(text: str, library: str = "") -> Any:
    """Parse a .kicad_mod file text into a PcbFootprint (or None)."""
    try:
        tree = parse_sexpr(text)
    except Exception as exc:
        log.warning("failed to tokenize footprint in %s: %s", library, exc)
        return None
    if not _is_list(tree):
        return None
    # The top node tag may be "footprint" (modern) or "module" (legacy).
    tag = _head(tree)
    if tag not in ("footprint", "module"):
        return None

    try:
        name = _unquote(tree[1]) if len(tree) >= 2 else ""
    except Exception:
        name = ""

    descr_node = _first(tree, "descr")
    tags_node = _first(tree, "tags")
    layer_node = _first(tree, "layer")

    descr = _unquote(descr_node[1]) if descr_node and len(descr_node) >= 2 else ""
    tags = _unquote(tags_node[1]) if tags_node and len(tags_node) >= 2 else ""
    layer = _unquote(layer_node[1]) if layer_node and len(layer_node) >= 2 else "F.Cu"

    fp = _LocalPcbFootprint(
        name=name, library=library, description=descr, tags=tags, layer=layer
    )

    for p in _children(tree, "pad"):
        pad = _parse_pad(p)
        if pad is not None:
            fp.pads.append(pad)

    for ln in _children(tree, "fp_line"):
        line = _parse_fp_line(ln)
        if line is not None:
            fp.lines.append(line)

    for ar in _children(tree, "fp_arc"):
        arc = _parse_fp_arc(ar)
        if arc is not None:
            fp.arcs.append(arc)

    for ci in _children(tree, "fp_circle"):
        circ = _parse_fp_circle(ci)
        if circ is not None:
            fp.circles.append(circ)

    for rc in _children(tree, "fp_rect"):
        r = _parse_fp_rect(rc)
        if r is not None:
            fp.rectangles.append(r)

    for tx in _children(tree, "fp_text"):
        t = _parse_fp_text(tx)
        if t is not None:
            fp.texts.append(t)

    for md in _children(tree, "model"):
        if len(md) >= 2 and isinstance(md[1], str):
            fp.models.append(_unquote(md[1]))

    return _coerce_footprint(fp)


def parse_kicad_mod_file(path: Path) -> Any:
    """Parse a .kicad_mod file and return a PcbFootprint (or None)."""
    p = Path(path)
    library = p.parent.name  # e.g. "Resistor_SMD.pretty"
    if library.endswith(".pretty"):
        library = library[: -len(".pretty")]
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("cannot read %s: %s", p, exc)
        return None
    fp = parse_kicad_mod_text(text, library=library)
    if fp is not None and not getattr(fp, "name", ""):
        # Use the file stem as a fallback name.
        try:
            fp.name = p.stem
        except Exception:
            pass
    return fp


__all__ = [
    "parse_kicad_mod_file",
    "parse_kicad_mod_text",
    "PcbFootprint",
    "PcbPad",
    "PcbLine",
    "PcbArc",
    "PcbCircle",
    "PcbRect",
    "PcbText",
]
