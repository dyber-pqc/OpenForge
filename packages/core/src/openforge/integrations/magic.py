"""Magic VLSI <-> OpenForge interoperability adapter.

Magic's ``.tech`` file is the de-facto source of truth for sky130/gf180mcu DRC
rules. This module parses the ``drc`` section of a Magic tech file and
translates it to the DRX rule-deck format consumed by ``openforge-drc``.

The parser covers the constructs OpenForge's DRX engine has primitives for
(as of v0.4): ``width``, ``spacing`` (intra- and inter-layer via
``.separation``), ``area``, ``surround``, ``overhang``, and ``edge4way``
(notch). Truly exotic constructs (``edge`` with multi-layer asymmetric
distances, ``cifmaxwidth``, ``angles``) are still recognised but emitted as
commented-out TODOs in the DRX output so users can see what was skipped.

Magic tech file reference:
  http://opencircuitdesign.com/magic/tutorial/tut_magic_techfile.html

Magic ``drc`` rule syntax used here::

    drc
        # comment
        width  <layer>           <distance> "<message>"
        spacing <layerA> <layerB> <distance> [touching_ok|touching_illegal] "<msg>"
        area   <layer>           <area> <horizon> "<message>"
        edge   <layerA> <layerB> <dist1> <layerC> <layerD> <dist2> "<msg>"
        # ... other rules ...
    end
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer-name -> GDS (datatype, layer) map
# ---------------------------------------------------------------------------
#
# Magic uses textual layer names ("metal1", "li", ...) while the DRX format
# expects ``input(layer, datatype)`` tuples. We provide a built-in mapping for
# the common sky130 + gf180mcuC names; unknown names get emitted with a
# placeholder so the user can edit afterwards.

_DEFAULT_LAYER_MAP: dict[str, tuple[int, int]] = {
    # sky130A
    "li": (67, 20),
    "li1": (67, 20),
    "licon": (66, 44),
    "mcon": (67, 44),
    "met1": (68, 20),
    "metal1": (68, 20),
    "via": (68, 44),
    "via1": (68, 44),
    "met2": (69, 20),
    "metal2": (69, 20),
    "via2": (69, 44),
    "met3": (70, 20),
    "metal3": (70, 20),
    "met4": (71, 20),
    "metal4": (71, 20),
    "met5": (72, 20),
    "metal5": (72, 20),
    "poly": (66, 20),
    "diff": (65, 20),
    "nwell": (64, 20),
    "pwell": (122, 20),
    # gf180mcuC
    "comp": (22, 0),
    "contact": (33, 0),
}


# ---------------------------------------------------------------------------
# Pydantic models for parsed rules
# ---------------------------------------------------------------------------


class WidthRule(BaseModel):
    """Magic ``width <layer> <distance> "<message>"``."""

    layer: str
    distance: float
    message: str = ""
    rule_name: str = ""


class SpacingRule(BaseModel):
    """Magic ``spacing <layerA> <layerB> <distance> [touching] "<message>"``.

    When ``layer_a == layer_b`` this is the classic same-layer minimum
    spacing rule (the most common case).
    """

    layer_a: str
    layer_b: str
    distance: float
    touching_ok: bool = False
    message: str = ""
    rule_name: str = ""


class AreaRule(BaseModel):
    """Magic ``area <layer> <area> <horizon> "<message>"``.

    ``area`` is the minimum polygon area (um^2). ``horizon`` is the search
    radius for merging adjacent polygons (we ignore it on the DRX side --
    DRX has no first-class area rule yet, so we emit a TODO).
    """

    layer: str
    area: float
    horizon: float = 0.0
    message: str = ""
    rule_name: str = ""


class SurroundRule(BaseModel):
    """Magic ``surround <outer> <inner> <distance> [touching] "<msg>"``.

    ``outer`` must surround ``inner`` by at least ``distance`` on every edge.
    Translated to DRX ``outer.surround(inner, distance)`` (an alias of
    ``.enclosing`` with the Magic-style argument order).
    """

    outer: str
    inner: str
    distance: float
    message: str = ""
    rule_name: str = ""


class OverhangRule(BaseModel):
    """Magic ``overhang <outer> <inner> <distance> "<msg>"``.

    ``outer`` must extend beyond ``inner`` by at least ``distance``.
    Translated to DRX ``outer.overhang(inner, distance)``.
    """

    outer: str
    inner: str
    distance: float
    message: str = ""
    rule_name: str = ""


class NotchRule(BaseModel):
    """Magic ``edge4way <layer> <distance> "<msg>"`` (single-layer notch).

    Translated to DRX ``layer.notch(distance)``.
    """

    layer: str
    distance: float
    message: str = ""
    rule_name: str = ""


class UnsupportedRule(BaseModel):
    """A Magic ``drc`` rule we recognised but did not translate."""

    raw: str
    reason: str = "unsupported construct"


class MagicTechFile(BaseModel):
    """Parsed Magic ``.tech`` file (only the sections we care about)."""

    name: str = "unknown"
    version: str = ""
    layers: dict[str, tuple[int, int]] = Field(default_factory=dict)
    width_rules: list[WidthRule] = Field(default_factory=list)
    spacing_rules: list[SpacingRule] = Field(default_factory=list)
    area_rules: list[AreaRule] = Field(default_factory=list)
    surround_rules: list[SurroundRule] = Field(default_factory=list)
    overhang_rules: list[OverhangRule] = Field(default_factory=list)
    notch_rules: list[NotchRule] = Field(default_factory=list)
    unsupported: list[UnsupportedRule] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _strip_comments(line: str) -> str:
    """Strip Magic ``#`` comments. Quoted ``#`` inside a string is preserved."""
    out = []
    in_str = False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        if ch == "#" and not in_str:
            break
        out.append(ch)
    return "".join(out).rstrip()


_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')


def _tokenize(line: str) -> list[str]:
    """Split a Magic rule line into tokens, keeping quoted strings intact."""
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _TOKEN_RE.finditer(line)]


def _iter_section(lines: list[str], section: str):
    """Yield (line_no, raw_line) inside the named ``section ... end`` block."""
    in_section = False
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not in_section:
            if stripped.lower() == section.lower():
                in_section = True
            continue
        if stripped.lower() == "end":
            return
        yield i, raw


def parse_magic_tech(path: Path) -> MagicTechFile:
    """Parse a Magic ``.tech`` file and return a :class:`MagicTechFile`.

    The parser handles ``tech`` (name/version), ``planes``/``types`` (for
    layer name discovery) and the ``drc`` section. Other sections (``cifoutput``,
    ``extract``, ``mzrouter``, ...) are skipped.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()

    name = p.stem
    version = ""
    layers: dict[str, tuple[int, int]] = dict(_DEFAULT_LAYER_MAP)

    # tech section: name + version
    for _, raw in _iter_section(lines, "tech"):
        toks = _tokenize(_strip_comments(raw))
        if not toks:
            continue
        if toks[0].lower() == "format":
            version = toks[1] if len(toks) > 1 else version
        elif toks[0].lower() in ("name", "techname"):
            if len(toks) > 1:
                name = toks[1]

    # cifoutput / cifinput map magic types <-> GDS (layer, datatype). Many
    # tech files declare them via ``layer <name> <gds_layer> <gds_datatype>``.
    # We do a permissive scan for anything that looks like that triple.
    for raw in lines:
        toks = _tokenize(_strip_comments(raw))
        if len(toks) >= 4 and toks[0].lower() == "layer":
            try:
                gds_layer = int(toks[2])
                gds_dt = int(toks[3])
            except ValueError:
                continue
            layers.setdefault(toks[1].lower(), (gds_layer, gds_dt))

    width_rules: list[WidthRule] = []
    spacing_rules: list[SpacingRule] = []
    area_rules: list[AreaRule] = []
    surround_rules: list[SurroundRule] = []
    overhang_rules: list[OverhangRule] = []
    notch_rules: list[NotchRule] = []
    unsupported: list[UnsupportedRule] = []

    # drc section
    for _, raw in _iter_section(lines, "drc"):
        clean = _strip_comments(raw).strip()
        if not clean:
            continue
        toks = _tokenize(clean)
        kind = toks[0].lower()

        try:
            if kind == "width" and len(toks) >= 3:
                # width <layer> <distance> "<msg>"
                msg = toks[3] if len(toks) > 3 else ""
                width_rules.append(
                    WidthRule(
                        layer=toks[1],
                        distance=float(toks[2]),
                        message=msg,
                        rule_name=f"{toks[1]}.W",
                    )
                )
            elif kind == "spacing" and len(toks) >= 4:
                # spacing <layerA> <layerB> <distance> [touching_ok] "<msg>"
                touching = False
                # The keyword sits between distance and message in many decks
                msg = ""
                rest = toks[4:]
                for r in rest:
                    if r in ("touching_ok", "touching_illegal", "surround_ok"):
                        touching = r == "touching_ok"
                    else:
                        msg = r
                spacing_rules.append(
                    SpacingRule(
                        layer_a=toks[1],
                        layer_b=toks[2],
                        distance=float(toks[3]),
                        touching_ok=touching,
                        message=msg,
                        rule_name=f"{toks[1]}.S",
                    )
                )
            elif kind == "area" and len(toks) >= 3:
                # area <layer> <area> [<horizon>] "<msg>"
                horizon = 0.0
                msg = ""
                if len(toks) >= 4:
                    try:
                        horizon = float(toks[3])
                    except ValueError:
                        msg = toks[3]
                if len(toks) >= 5:
                    msg = toks[4]
                area_rules.append(
                    AreaRule(
                        layer=toks[1],
                        area=float(toks[2]),
                        horizon=horizon,
                        message=msg,
                        rule_name=f"{toks[1]}.A",
                    )
                )
            elif kind == "surround" and len(toks) >= 4:
                # surround <outer> <inner> <distance> [touching_*] "<msg>"
                msg = ""
                rest = toks[4:]
                for r in rest:
                    if r in ("touching_ok", "touching_illegal", "absence_illegal"):
                        continue
                    msg = r
                surround_rules.append(
                    SurroundRule(
                        outer=toks[1],
                        inner=toks[2],
                        distance=float(toks[3]),
                        message=msg,
                        rule_name=f"{toks[1]}.SR.{toks[2]}",
                    )
                )
            elif kind == "overhang" and len(toks) >= 4:
                # overhang <outer> <inner> <distance> "<msg>"
                msg = toks[4] if len(toks) > 4 else ""
                overhang_rules.append(
                    OverhangRule(
                        outer=toks[1],
                        inner=toks[2],
                        distance=float(toks[3]),
                        message=msg,
                        rule_name=f"{toks[1]}.OH.{toks[2]}",
                    )
                )
            elif kind == "edge4way" and len(toks) >= 3:
                # edge4way <layer> <distance> "<msg>"  (notch form)
                # NB: full Magic edge4way takes more tokens for asymmetric
                # rules; we handle the common single-layer notch shape and
                # punt anything more complex to `unsupported`.
                try:
                    dist = float(toks[2])
                except ValueError:
                    unsupported.append(
                        UnsupportedRule(
                            raw=clean,
                            reason="complex edge4way (multi-layer) not translated",
                        )
                    )
                else:
                    msg = toks[3] if len(toks) > 3 else ""
                    notch_rules.append(
                        NotchRule(
                            layer=toks[1],
                            distance=dist,
                            message=msg,
                            rule_name=f"{toks[1]}.N",
                        )
                    )
            elif kind in ("edge", "cifmaxwidth", "angles"):
                # Still no first-class DRX primitive for these.
                unsupported.append(
                    UnsupportedRule(raw=clean, reason=f"'{kind}' rule not yet translated")
                )
            else:
                unsupported.append(UnsupportedRule(raw=clean, reason=f"unknown directive '{kind}'"))
        except (ValueError, IndexError) as exc:  # noqa: PERF203
            unsupported.append(UnsupportedRule(raw=clean, reason=f"parse error: {exc}"))

    return MagicTechFile(
        name=name,
        version=version,
        layers=layers,
        width_rules=width_rules,
        spacing_rules=spacing_rules,
        area_rules=area_rules,
        surround_rules=surround_rules,
        overhang_rules=overhang_rules,
        notch_rules=notch_rules,
        unsupported=unsupported,
    )


# ---------------------------------------------------------------------------
# Translator: Magic -> DRX
# ---------------------------------------------------------------------------


def _layer_tuple(name: str, layers: dict[str, tuple[int, int]]) -> tuple[int, int]:
    """Look up a Magic layer by name; fall back to (0, 0) with a warning."""
    key = name.lower()
    if key in layers:
        return layers[key]
    logger.warning("magic_to_drx: unknown layer %r; emitting placeholder (0, 0)", name)
    return (0, 0)


def magic_to_drx(tech: MagicTechFile) -> str:
    """Render a parsed :class:`MagicTechFile` as a DRX (Ruby-style) deck.

    The output is consumable by ``openforge-drc check --rules-drx <path>``.
    Unsupported Magic rules are preserved as ``# TODO:`` comment lines so the
    user can hand-port them.
    """
    lines: list[str] = []
    lines.append(f"# Auto-generated by openforge: Magic .tech -> DRX ({tech.name})")
    lines.append(f'report("{tech.name} (translated from Magic)")')
    lines.append("")

    # Collect layer names actually referenced by any rule, in stable order.
    referenced: list[str] = []
    seen: set[str] = set()
    for r in tech.width_rules:
        if r.layer.lower() not in seen:
            seen.add(r.layer.lower())
            referenced.append(r.layer)
    for r in tech.spacing_rules:
        for lyr in (r.layer_a, r.layer_b):
            if lyr.lower() not in seen:
                seen.add(lyr.lower())
                referenced.append(lyr)
    for r in tech.area_rules:
        if r.layer.lower() not in seen:
            seen.add(r.layer.lower())
            referenced.append(r.layer)
    for r in tech.surround_rules:
        for lyr in (r.outer, r.inner):
            if lyr.lower() not in seen:
                seen.add(lyr.lower())
                referenced.append(lyr)
    for r in tech.overhang_rules:
        for lyr in (r.outer, r.inner):
            if lyr.lower() not in seen:
                seen.add(lyr.lower())
                referenced.append(lyr)
    for r in tech.notch_rules:
        if r.layer.lower() not in seen:
            seen.add(r.layer.lower())
            referenced.append(r.layer)

    # Layer declarations
    for lyr in referenced:
        gds_layer, gds_dt = _layer_tuple(lyr, tech.layers)
        lines.append(f"{lyr.lower()} = input({gds_layer}, {gds_dt})")
    if referenced:
        lines.append("")

    # Width rules
    if tech.width_rules:
        lines.append("# Width rules")
        for r in tech.width_rules:
            msg = r.message or f"Min width {r.distance}"
            lines.append(f'{r.layer.lower()}.width({r.distance}).output("{r.rule_name}", "{msg}")')
        lines.append("")

    # Spacing rules
    if tech.spacing_rules:
        lines.append("# Spacing rules")
        for r in tech.spacing_rules:
            msg = r.message or f"Min spacing {r.distance}"
            if r.layer_a.lower() == r.layer_b.lower():
                lines.append(
                    f'{r.layer_a.lower()}.space({r.distance}).output("{r.rule_name}", "{msg}")'
                )
            else:
                # Inter-layer spacing -> DRX `.separation()` primitive (v0.4+).
                lines.append(
                    f"{r.layer_a.lower()}.separation({r.layer_b.lower()}, {r.distance})"
                    f'.output("{r.rule_name}", "{msg}")'
                )
        lines.append("")

    # Area rules -> DRX `.area()` (v0.4+).
    if tech.area_rules:
        lines.append("# Area rules")
        for r in tech.area_rules:
            msg = r.message or f"Min area {r.area}"
            lines.append(
                f'{r.layer.lower()}.area({r.area}).output("{r.rule_name}", "{msg}")'
            )
        lines.append("")

    # Surround rules -> DRX `.surround()` (alias of `.enclosing`).
    if tech.surround_rules:
        lines.append("# Surround rules")
        for r in tech.surround_rules:
            msg = r.message or f"{r.outer} surrounds {r.inner} by {r.distance}"
            lines.append(
                f"{r.outer.lower()}.surround({r.inner.lower()}, {r.distance})"
                f'.output("{r.rule_name}", "{msg}")'
            )
        lines.append("")

    # Overhang rules -> DRX `.overhang()`.
    if tech.overhang_rules:
        lines.append("# Overhang rules")
        for r in tech.overhang_rules:
            msg = r.message or f"{r.outer} overhang {r.inner} by {r.distance}"
            lines.append(
                f"{r.outer.lower()}.overhang({r.inner.lower()}, {r.distance})"
                f'.output("{r.rule_name}", "{msg}")'
            )
        lines.append("")

    # Notch rules (Magic edge4way single-layer) -> DRX `.notch()`.
    if tech.notch_rules:
        lines.append("# Notch rules")
        for r in tech.notch_rules:
            msg = r.message or f"Min notch {r.distance}"
            lines.append(
                f'{r.layer.lower()}.notch({r.distance}).output("{r.rule_name}", "{msg}")'
            )
        lines.append("")

    # Unsupported constructs preserved verbatim
    if tech.unsupported:
        lines.append("# Unsupported Magic rules (hand-port required):")
        for u in tech.unsupported:
            lines.append(f"# TODO ({u.reason}): {u.raw}")
        lines.append("")

    return "\n".join(lines)
