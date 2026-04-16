"""Specctra DSN / SES export and import.

Freerouting (and every commercial autorouter worth naming) consumes a
Specctra DSN file and emits a Specctra SES (Session) file with the
routed wires/vias. This module implements a practical subset of that
format sufficient to round-trip an OpenForge ``PcbBoard`` through
freerouting.

Reference: Specctra Design/Session file formats (Cadence).
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from openforge.pcb.model import PcbBoard
    from openforge.pcb.net_classes import NetClassRegistry


# DSN is a Lisp-ish s-expression format. We emit it by hand for clarity
# and parse SES with a tiny recursive-descent tokenizer.


RESOLUTION = 1000  # units per mm -> micrometer resolution


def _fmt(value: float) -> str:
    return f"{value * RESOLUTION:.0f}"


def _signal_layers(board: PcbBoard) -> list[str]:
    return [l.name for l in board.stackup.copper_layers() if l.kind == "signal"]


def _iter_net_pads(board: PcbBoard) -> dict[int, list[tuple[str, str]]]:
    """Return net_id -> list of (component_ref, pad_name)."""
    mapping: dict[int, list[tuple[str, str]]] = {}
    for fp in board.footprints:
        for pad in fp.pads:
            if pad.net:
                mapping.setdefault(pad.net, []).append((fp.ref, pad.name))
    return mapping


def board_to_dsn(
    board: PcbBoard,
    output_path: Path,
    net_classes: NetClassRegistry | None = None,
) -> Path:
    """Write a Specctra DSN file describing ``board``.

    The emitted file contains the structure (boundary + layers + rules),
    placement (components/pads), library (images/padstacks), network
    (nets + classes) and wiring (pre-existing tracks) sections.
    """
    from openforge.pcb.net_classes import NetClassRegistry

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    nc = net_classes or NetClassRegistry.with_defaults()
    lines: list[str] = []
    w = lines.append

    name = board.name or "board"
    w(f"(pcb {name}")
    w("  (parser")
    w('    (string_quote ")')
    w("    (space_in_quoted_tokens on)")
    w("    (host_cad OpenForge)")
    w("    (host_version 1.0)")
    w("  )")
    w(f"  (resolution mm {RESOLUTION})")
    w("  (unit mm)")

    # ---- structure: boundary, layers, rules --------------------------
    w("  (structure")
    for layer in _signal_layers(board):
        w(f"    (layer {layer}")
        w("      (type signal)")
        w("    )")

    # Boundary
    bx1, by1, bx2, by2 = board.bounding_box()
    if board.outline and len(board.outline) >= 3:
        pts = " ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in board.outline)
        closing = f"{_fmt(board.outline[0][0])} {_fmt(board.outline[0][1])}"
        w(f"    (boundary (path pcb 0 {pts} {closing}))")
    else:
        w(
            "    (boundary (path pcb 0 "
            f"{_fmt(bx1)} {_fmt(by1)} "
            f"{_fmt(bx2)} {_fmt(by1)} "
            f"{_fmt(bx2)} {_fmt(by2)} "
            f"{_fmt(bx1)} {_fmt(by2)} "
            f"{_fmt(bx1)} {_fmt(by1)}))"
        )

    default = nc.classes.get(nc.default)
    if default is None:
        default_width = 0.2
        default_clear = 0.2
    else:
        default_width = default.width_mm
        default_clear = default.clearance_mm
    w("    (rule")
    w(f"      (width {_fmt(default_width)})")
    w(f"      (clearance {_fmt(default_clear)})")
    w("    )")
    w("  )")

    # ---- placement ---------------------------------------------------
    w("  (placement")
    for fp in board.footprints:
        side = "front" if fp.layer == "top" else "back"
        image = f"IMG_{fp.ref}"
        w(f"    (component {image}")
        w(f"      (place {fp.ref} {_fmt(fp.x_mm)} {_fmt(fp.y_mm)} {side} {fp.rotation_deg:.1f})")
        w("    )")
    w("  )")

    # ---- library: images + padstacks ---------------------------------
    w("  (library")
    padstack_names: set[str] = set()
    for fp in board.footprints:
        image = f"IMG_{fp.ref}"
        w(f"    (image {image}")
        for pad in fp.pads:
            ps_name = f"PS_{pad.shape}_{pad.size_x_mm:.3f}x{pad.size_y_mm:.3f}_{pad.drill_mm:.2f}"
            ps_name = ps_name.replace(".", "p").replace("-", "m")
            padstack_names.add(ps_name)
            w(f"      (pin {ps_name} {pad.name} {_fmt(pad.x_mm)} {_fmt(pad.y_mm)})")
        w("    )")
    # Emit referenced padstacks
    emitted: set[str] = set()
    for fp in board.footprints:
        for pad in fp.pads:
            ps_name = f"PS_{pad.shape}_{pad.size_x_mm:.3f}x{pad.size_y_mm:.3f}_{pad.drill_mm:.2f}"
            ps_name = ps_name.replace(".", "p").replace("-", "m")
            if ps_name in emitted:
                continue
            emitted.add(ps_name)
            w(f"    (padstack {ps_name}")
            for layer in _signal_layers(board):
                if pad.shape == "round":
                    w(f"      (shape (circle {layer} {_fmt(pad.size_x_mm)}))")
                else:
                    hx = pad.size_x_mm / 2
                    hy = pad.size_y_mm / 2
                    w(f"      (shape (rect {layer} {_fmt(-hx)} {_fmt(-hy)} {_fmt(hx)} {_fmt(hy)}))")
            w("      (attach off)")
            w("    )")
    # Default via padstack
    w("    (padstack VIA_STD")
    for layer in _signal_layers(board):
        w(f"      (shape (circle {layer} {_fmt(0.6)}))")
    w("      (attach off)")
    w("    )")
    w("  )")

    # ---- network -----------------------------------------------------
    w("  (network")
    pads_for_net = _iter_net_pads(board)
    for net_id, pads in pads_for_net.items():
        net_name = board.net_name(net_id) or f"N${net_id}"
        if not net_name:
            continue
        w(f'    (net "{net_name}"')
        pinstr = " ".join(f"{r}-{p}" for r, p in pads)
        w(f"      (pins {pinstr})")
        w("    )")
    # Class sections
    for cname, klass in nc.classes.items():
        if not klass.nets and cname != nc.default:
            continue
        nets_in_class: list[str] = []
        if cname == nc.default:
            assigned = set()
            for c in nc.classes.values():
                assigned.update(c.nets)
            for _nid, nm in board.nets.items():
                if nm and nm not in assigned:
                    nets_in_class.append(nm)
        else:
            nets_in_class = list(klass.nets)
        if not nets_in_class:
            continue
        w(f"    (class {cname} " + " ".join(f'"{n}"' for n in nets_in_class))
        w("      (circuit")
        w("        (use_via VIA_STD)")
        w("      )")
        w("      (rule")
        w(f"        (width {_fmt(klass.width_mm)})")
        w(f"        (clearance {_fmt(klass.clearance_mm)})")
        w("      )")
        w("    )")
    w("  )")

    # ---- wiring (pre-routes) -----------------------------------------
    w("  (wiring")
    for t in board.tracks:
        if not t.net:
            continue
        nm = board.net_name(t.net) or f"N${t.net}"
        w(
            f"    (wire (path {t.layer} {_fmt(t.width_mm)} "
            f"{_fmt(t.x1_mm)} {_fmt(t.y1_mm)} "
            f'{_fmt(t.x2_mm)} {_fmt(t.y2_mm)}) (net "{nm}"))'
        )
    for v in board.vias:
        nm = board.net_name(v.net) or f"N${v.net}"
        w(f'    (via VIA_STD {_fmt(v.x_mm)} {_fmt(v.y_mm)} (net "{nm}"))')
    w("  )")

    w(")")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# SES parser
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r'"([^"]*)"|([^\s()]+)|([()])')


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        if match.group(1) is not None:
            tokens.append(f'"{match.group(1)}"')
        elif match.group(2) is not None:
            tokens.append(match.group(2))
        else:
            tokens.append(match.group(3))
    return tokens


def _parse(tokens: list[str], pos: int = 0):
    if pos >= len(tokens):
        return None, pos
    tok = tokens[pos]
    if tok == "(":
        result: list = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ")":
            child, pos = _parse(tokens, pos)
            result.append(child)
        return result, pos + 1  # skip ')'
    return tok, pos + 1


def _find_all(tree, name: str) -> Iterable[list]:
    if isinstance(tree, list):
        if tree and tree[0] == name:
            yield tree
        for child in tree:
            yield from _find_all(child, name)


def parse_ses(ses_path: Path, board: PcbBoard) -> PcbBoard:
    """Read a Specctra SES file and apply its wiring to ``board``.

    The caller keeps ownership of ``board``; this mutates it in place
    and returns it for convenience. Existing tracks/vias are preserved.
    """
    text = Path(ses_path).read_text(encoding="utf-8", errors="replace")
    tokens = _tokenize(text)
    if not tokens:
        return board
    tree, _ = _parse(tokens, 0)
    if tree is None:
        return board

    # Resolution: (resolution mm N)
    resolution = float(RESOLUTION)
    for node in _find_all(tree, "resolution"):
        with contextlib.suppress(ValueError, IndexError):
            resolution = float(node[2])

    inv = 1.0 / resolution

    # Net names are resolved by string
    name_to_id = {name: nid for nid, name in board.nets.items() if name}

    def _net_id(name: str) -> int:
        clean = name.strip('"')
        if clean in name_to_id:
            return name_to_id[clean]
        return board.add_net(clean)

    from openforge.pcb.model import PcbTrack, PcbVia

    # Each (net "NAME" ...) in the (routes ...) block contains wires/vias
    for net_node in _find_all(tree, "net"):
        if len(net_node) < 2:
            continue
        net_name = net_node[1] if isinstance(net_node[1], str) else ""
        if not net_name or not isinstance(net_name, str):
            continue
        net_id = _net_id(net_name)
        for wire in _find_all(net_node, "wire"):
            for path in _find_all(wire, "path"):
                if len(path) < 5:
                    continue
                layer = path[1]
                try:
                    width = float(path[2]) * inv
                except (ValueError, TypeError):
                    continue
                coords: list[float] = []
                for val in path[3:]:
                    with contextlib.suppress(ValueError, TypeError):
                        coords.append(float(val) * inv)
                for i in range(0, len(coords) - 3, 2):
                    board.tracks.append(
                        PcbTrack(
                            layer=layer,
                            x1_mm=coords[i],
                            y1_mm=coords[i + 1],
                            x2_mm=coords[i + 2],
                            y2_mm=coords[i + 3],
                            width_mm=width,
                            net=net_id,
                        )
                    )
        for via in _find_all(net_node, "via"):
            if len(via) < 4:
                continue
            try:
                x = float(via[2]) * inv
                y = float(via[3]) * inv
            except (ValueError, TypeError):
                continue
            board.vias.append(PcbVia(x_mm=x, y_mm=y, drill_mm=0.3, diameter_mm=0.6, net=net_id))
    return board


__all__ = ["board_to_dsn", "parse_ses"]
