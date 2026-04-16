"""Macro placement assistant.

Pure-Python force-directed placer for hard macros. Connected macros attract
each other proportionally to their connection weight, every pair of macros
repels, and the core boundary repels to keep macros in legal area. No
external dependencies beyond numpy (already a project requirement).
"""

from __future__ import annotations

import math

import numpy as np

from openforge.floorplan.model import Core, Die, MacroPlacement


def force_directed_placement(
    macros: list[MacroPlacement],
    connectivity: dict[tuple[str, str], int],
    die: Die,
    core: Core,
    iters: int = 200,
) -> list[MacroPlacement]:
    """Run a simple force-directed placer over the macro list.

    Parameters
    ----------
    macros:
        Seed placements. Centers are used as starting positions; widths
        and heights (if > 0) feed the repulsion kernel radius.
    connectivity:
        Mapping of ``(instance_a, instance_b) -> weight`` where weight is
        the fanout or estimated connection count.
    die, core:
        Die and core geometry. The core rectangle is the legal area.
    iters:
        Number of relaxation iterations.
    """
    n = len(macros)
    if n == 0:
        return []
    if n == 1:
        m = macros[0].model_copy()
        m.x_um = (core.x1 + core.x2 - max(m.width_um, 1.0)) / 2.0
        m.y_um = (core.y1 + core.y2 - max(m.height_um, 1.0)) / 2.0
        return [m]

    idx = {m.name: i for i, m in enumerate(macros)}

    # Work in centers.
    pos = np.zeros((n, 2), dtype=float)
    size = np.zeros((n, 2), dtype=float)
    for i, m in enumerate(macros):
        w = max(m.width_um, 1.0)
        h = max(m.height_um, 1.0)
        pos[i] = (m.x_um + w / 2.0, m.y_um + h / 2.0)
        size[i] = (w, h)

    # Connectivity matrix (symmetric).
    conn = np.zeros((n, n), dtype=float)
    for (a, b), w in connectivity.items():
        if a not in idx or b not in idx:
            continue
        ia, ib = idx[a], idx[b]
        if ia == ib:
            continue
        conn[ia, ib] += float(w)
        conn[ib, ia] += float(w)

    core_w = core.x2 - core.x1
    core_h = core.y2 - core.y1
    natural = math.sqrt(core_w * core_h / n)  # ideal separation
    k_attr = 0.01
    k_rep = natural * natural * 0.5
    k_wall = natural * 2.0
    step0 = natural * 0.1

    for it in range(iters):
        step = step0 * (1.0 - it / iters) + 0.001
        # Pairwise delta vectors
        delta = pos[:, None, :] - pos[None, :, :]  # (n,n,2)
        dist2 = np.sum(delta * delta, axis=-1) + 1e-6
        dist = np.sqrt(dist2)
        unit = delta / dist[..., None]

        # Repulsion: k_rep / dist for each pair, outward
        rep = (k_rep / dist2)[..., None] * unit
        np.fill_diagonal(rep[..., 0], 0.0)
        np.fill_diagonal(rep[..., 1], 0.0)
        force = rep.sum(axis=1)

        # Attraction: -k_attr * weight * dist toward each other
        attract = -k_attr * conn[..., None] * delta
        force += attract.sum(axis=1)

        # Wall forces keep macros inside the core box.
        for i in range(n):
            cx, cy = pos[i]
            half_w = size[i, 0] / 2.0
            half_h = size[i, 1] / 2.0
            if cx - half_w < core.x1:
                force[i, 0] += k_wall * (core.x1 + half_w - (cx - half_w))
            if cx + half_w > core.x2:
                force[i, 0] -= k_wall * ((cx + half_w) - (core.x2 - half_w))
            if cy - half_h < core.y1:
                force[i, 1] += k_wall * (core.y1 + half_h - (cy - half_h))
            if cy + half_h > core.y2:
                force[i, 1] -= k_wall * ((cy + half_h) - (core.y2 - half_h))

        # Normalise per-node step
        norm = np.linalg.norm(force, axis=1, keepdims=True) + 1e-9
        pos += force / norm * step

        # Hard clamp inside core
        pos[:, 0] = np.clip(
            pos[:, 0], core.x1 + size[:, 0] / 2.0, core.x2 - size[:, 0] / 2.0
        )
        pos[:, 1] = np.clip(
            pos[:, 1], core.y1 + size[:, 1] / 2.0, core.y2 - size[:, 1] / 2.0
        )

    result: list[MacroPlacement] = []
    for i, m in enumerate(macros):
        new = m.model_copy()
        new.x_um = float(pos[i, 0] - size[i, 0] / 2.0)
        new.y_um = float(pos[i, 1] - size[i, 1] / 2.0)
        result.append(new)
    return result


def suggest_orientation(
    macro: MacroPlacement,
    neighbors: list[MacroPlacement],
    pin_sides: dict[str, str] | None = None,
) -> str:
    """Suggest an orientation (N/S/FN/FS) for ``macro``.

    Heuristic: compute the dominant direction from ``macro`` to its
    neighbors. If most neighbors lie to the east, prefer an orientation
    that places the macro's pins on that side. ``pin_sides`` can override
    the default (pins on the east for "N" orientation).
    """
    if not neighbors:
        return macro.orientation or "N"

    mx = macro.x_um + macro.width_um / 2.0
    my = macro.y_um + macro.height_um / 2.0
    dx = 0.0
    dy = 0.0
    for nb in neighbors:
        nx = nb.x_um + nb.width_um / 2.0
        ny = nb.y_um + nb.height_um / 2.0
        dx += nx - mx
        dy += ny - my
    # Pin side defaults.
    pin_sides = pin_sides or {"N": "E", "S": "W", "FN": "W", "FS": "E"}
    want_east = dx >= 0
    want_north = dy >= 0
    # Choose an orientation whose pin side matches the dominant direction.
    if want_east and want_north:
        return "N"
    if want_east and not want_north:
        return "FS"
    if not want_east and want_north:
        return "FN"
    return "S"


def estimate_wirelength(
    macros: list[MacroPlacement],
    connectivity: dict[tuple[str, str], int],
) -> float:
    """Return total Manhattan wirelength (um) across weighted macro pairs."""
    centers = {
        m.name: (m.x_um + m.width_um / 2.0, m.y_um + m.height_um / 2.0)
        for m in macros
    }
    total = 0.0
    for (a, b), w in connectivity.items():
        if a not in centers or b not in centers:
            continue
        ax, ay = centers[a]
        bx, by = centers[b]
        total += w * (abs(ax - bx) + abs(ay - by))
    return float(total)
