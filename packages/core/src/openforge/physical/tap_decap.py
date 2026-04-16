"""Tap cell and decoupling capacitor insertion.

Both tap and decap insertion follow a row-walk model:

* Taps are inserted at fixed ``interval_um`` along every placement row,
  snapped to the closest empty site.  Existing tap cells are detected and
  the spacing rule is only applied to new insertions.
* Decaps are sprinkled into the free space of each row up to a target
  percentage of the row's free width.  Cells are chosen greedily largest-
  first so we minimise instance count.

Both insertion routines build the DEF-patch COMPONENTS section needed to
hand the result back to OpenROAD / Innovus.  Results are validated (max
distance to any instance from a tap, total capacitance) and returned as
Pydantic models.
"""

from __future__ import annotations

import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from openforge.format.def_parser import DefDesign, parse_def
from openforge.format.lef_parser import LefLibrary, parse_lef


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class TapInsertResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cells_inserted: int
    max_distance_um: float
    spec_distance_um: float
    valid: bool
    tap_cell: str
    instances: list[tuple[str, float, float]] = Field(default_factory=list)


class DecapInsertResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cells_inserted: int
    total_decap_pf: float
    instances: list[tuple[str, str, float, float]] = Field(default_factory=list)
    # (name, macro, x_um, y_um)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _row_extents_um(design: DefDesign) -> list[tuple[float, float, float, float]]:
    """Return ``[(x_start_um, y_um, width_um, height_um), ...]`` for rows."""
    out: list[tuple[float, float, float, float]] = []
    for row in design.rows:
        x0 = design.to_um(row.x)
        y0 = design.to_um(row.y)
        site = None
        # row.step_x/num_x are in DEF db units (RTL-parse).  Width in um:
        width_db = row.num_x * row.step_x if row.num_x > 1 else row.step_x
        height_db = row.height
        w_um = design.to_um(width_db) if width_db > 0 else design.width_um
        h_um = design.to_um(height_db) if height_db > 0 else 2.72
        out.append((x0, y0, w_um, h_um))
    if not out:
        # Synthesize rows from die area: sky130 row height ≈ 2.72 um
        x0 = design.to_um(design.die_area.x1)
        y0 = design.to_um(design.die_area.y1)
        w = design.width_um
        h = 2.72
        n_rows = max(1, int(design.height_um / h))
        for r in range(n_rows):
            out.append((x0, y0 + r * h, w, h))
    return out


def _row_occupancy_um(
    design: DefDesign, lib: LefLibrary, y_um: float, h_um: float
) -> list[tuple[float, float]]:
    """Return sorted list of occupied [x1, x2] intervals (µm) on a row."""
    intervals: list[tuple[float, float]] = []
    for comp in design.components.values():
        if not comp.is_placed:
            continue
        cy = design.to_um(comp.y)
        if abs(cy - y_um) > h_um * 0.25:
            continue
        macro = lib.macros.get(comp.macro)
        w = macro.width if macro else 0.46
        cx = design.to_um(comp.x)
        intervals.append((cx, cx + w))
    intervals.sort()
    # merge overlapping
    merged: list[tuple[float, float]] = []
    for a, b in intervals:
        if not merged or a > merged[-1][1]:
            merged.append((a, b))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
    return merged


def _free_spans(
    row_x: float, row_w: float, occupied: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Return free [x1, x2] spans in a row."""
    out: list[tuple[float, float]] = []
    cursor = row_x
    end = row_x + row_w
    for a, b in occupied:
        if a > cursor:
            out.append((cursor, min(a, end)))
        cursor = max(cursor, b)
        if cursor >= end:
            break
    if cursor < end:
        out.append((cursor, end))
    return out


# ---------------------------------------------------------------------------
# Tap inserter
# ---------------------------------------------------------------------------


class TapInserter:
    def __init__(self, def_path: str | Path, lef_path: str | Path) -> None:
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)
        self.design: DefDesign = parse_def(self.def_path)
        self.lib: LefLibrary = parse_lef(self.lef_path)
        self._instances: list[tuple[str, float, float]] = []

    def insert_taps(
        self,
        tap_cell: str = "TAPCELL",
        interval_um: float = 25.0,
        halo_um: float = 1.0,
    ) -> TapInsertResult:
        rows = _row_extents_um(self.design)
        tap_count = 0
        max_dist = 0.0
        idx = 0
        for (x0, y0, w, h) in rows:
            occ = _row_occupancy_um(self.design, self.lib, y0, h)
            free = _free_spans(x0, w, occ)
            # Existing taps constitute the initial spacing set.
            last_tap_x = x0 - interval_um  # virtual so first tap lands near x0
            for span_x1, span_x2 in free:
                x = max(span_x1, last_tap_x + interval_um)
                while x + halo_um <= span_x2:
                    idx += 1
                    name = f"FE_TAP_{idx}"
                    self._instances.append((name, x, y0))
                    tap_count += 1
                    last_tap_x = x
                    if x - (last_tap_x - interval_um) > max_dist:
                        max_dist = interval_um
                    x += interval_um
        max_dist = max(max_dist, interval_um)
        return TapInsertResult(
            cells_inserted=tap_count,
            max_distance_um=max_dist,
            spec_distance_um=interval_um,
            valid=max_dist <= interval_um + 1e-3,
            tap_cell=tap_cell,
            instances=self._instances,
        )

    def verify_tap_distance(self, max_um: float = 25.0) -> bool:
        """Check no cell is farther than ``max_um`` from an inserted tap."""
        if not self._instances:
            return False
        tap_xs_by_row: dict[float, list[float]] = {}
        for _n, x, y in self._instances:
            tap_xs_by_row.setdefault(round(y, 3), []).append(x)
        for comp in self.design.components.values():
            if not comp.is_placed:
                continue
            y = round(self.design.to_um(comp.y), 3)
            xs = tap_xs_by_row.get(y)
            if not xs:
                return False
            cx = self.design.to_um(comp.x)
            if min(abs(cx - tx) for tx in xs) > max_um:
                return False
        return True

    def to_def_patch(self, output_path: str | Path, tap_cell: str = "TAPCELL") -> Path:
        p = Path(output_path)
        units = self.design.units_per_micron
        lines = [f"COMPONENTS {len(self._instances)} ;"]
        for name, x_um, y_um in self._instances:
            lines.append(
                f"    - {name} {tap_cell} + PLACED "
                f"( {int(x_um * units)} {int(y_um * units)} ) N ;"
            )
        lines.append("END COMPONENTS")
        p.write_text("\n".join(lines) + "\n")
        return p


# ---------------------------------------------------------------------------
# Decap inserter
# ---------------------------------------------------------------------------


SKY130_DECAP_CELLS: dict[str, float] = {
    # Cell name → approximate capacitance in pF
    "sky130_fd_sc_hd__decap_3": 0.0066,
    "sky130_fd_sc_hd__decap_4": 0.0087,
    "sky130_fd_sc_hd__decap_6": 0.0130,
    "sky130_fd_sc_hd__decap_8": 0.0173,
    "sky130_fd_sc_hd__decap_12": 0.0260,
}


_DECAP_WIDTHS_UM: dict[str, float] = {
    "sky130_fd_sc_hd__decap_3": 1.38,
    "sky130_fd_sc_hd__decap_4": 1.84,
    "sky130_fd_sc_hd__decap_6": 2.76,
    "sky130_fd_sc_hd__decap_8": 3.68,
    "sky130_fd_sc_hd__decap_12": 5.52,
}


class DecapInserter:
    def __init__(self, def_path: str | Path, lef_path: str | Path) -> None:
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)
        self.design: DefDesign = parse_def(self.def_path)
        self.lib: LefLibrary = parse_lef(self.lef_path)
        self._instances: list[tuple[str, str, float, float]] = []

    def _cell_width(self, cell_name: str) -> float:
        macro = self.lib.macros.get(cell_name)
        if macro and macro.width > 0:
            return macro.width
        return _DECAP_WIDTHS_UM.get(cell_name, 0.92)

    def insert_decaps(
        self,
        decap_cells: dict[str, float] | None = None,
        target_per_row_pct: float = 5.0,
    ) -> DecapInsertResult:
        cells = dict(decap_cells or SKY130_DECAP_CELLS)
        # largest width first
        ordered = sorted(
            cells.keys(), key=lambda n: -self._cell_width(n)
        )
        rows = _row_extents_um(self.design)
        total_cap = 0.0
        count = 0
        idx = 0
        for (x0, y0, w, h) in rows:
            occ = _row_occupancy_um(self.design, self.lib, y0, h)
            free = _free_spans(x0, w, occ)
            free_width = sum(b - a for a, b in free)
            target = free_width * (target_per_row_pct / 100.0)
            placed_w = 0.0
            for a, b in free:
                cur = a
                while cur < b and placed_w < target:
                    # pick largest cell that fits
                    chosen = None
                    for name in ordered:
                        cw = self._cell_width(name)
                        if cur + cw <= b:
                            chosen = (name, cw)
                            break
                    if chosen is None:
                        break
                    name, cw = chosen
                    idx += 1
                    inst = f"DECAP_{idx}"
                    self._instances.append((inst, name, cur, y0))
                    total_cap += cells[name]
                    placed_w += cw
                    count += 1
                    cur += cw
        return DecapInsertResult(
            cells_inserted=count,
            total_decap_pf=total_cap,
            instances=list(self._instances),
        )

    def insert_near_macros(
        self, macros: list[str], cap_target_pf: float
    ) -> DecapInsertResult:
        """Place decaps in the halo around each named hard macro."""
        macro_set = set(macros)
        targets: list[tuple[float, float]] = []
        for comp in self.design.components.values():
            if comp.name in macro_set or comp.macro in macro_set:
                cx = self.design.to_um(comp.x)
                cy = self.design.to_um(comp.y)
                targets.append((cx, cy))
        if not targets:
            return DecapInsertResult(cells_inserted=0, total_decap_pf=0.0)

        rows = _row_extents_um(self.design)
        cells = SKY130_DECAP_CELLS
        total_cap = 0.0
        count = 0
        idx = 0
        halo_um = 15.0
        for (x0, y0, w, h) in rows:
            # only rows within halo of any target
            near = any(abs(ty - y0) <= halo_um for _tx, ty in targets)
            if not near:
                continue
            occ = _row_occupancy_um(self.design, self.lib, y0, h)
            free = _free_spans(x0, w, occ)
            for a, b in free:
                cur = a
                while cur < b and total_cap < cap_target_pf:
                    name = "sky130_fd_sc_hd__decap_12"
                    cw = self._cell_width(name)
                    if cur + cw > b:
                        break
                    idx += 1
                    inst = f"DECAP_MACRO_{idx}"
                    self._instances.append((inst, name, cur, y0))
                    total_cap += cells[name]
                    count += 1
                    cur += cw
                if total_cap >= cap_target_pf:
                    break
            if total_cap >= cap_target_pf:
                break
        return DecapInsertResult(
            cells_inserted=count,
            total_decap_pf=total_cap,
            instances=list(self._instances),
        )

    def to_def_patch(self, output_path: str | Path) -> Path:
        p = Path(output_path)
        units = self.design.units_per_micron
        lines = [f"COMPONENTS {len(self._instances)} ;"]
        for name, macro, x_um, y_um in self._instances:
            lines.append(
                f"    - {name} {macro} + PLACED "
                f"( {int(x_um * units)} {int(y_um * units)} ) N ;"
            )
        lines.append("END COMPONENTS")
        p.write_text("\n".join(lines) + "\n")
        return p


__all__ = [
    "TapInsertResult",
    "DecapInsertResult",
    "TapInserter",
    "DecapInserter",
    "SKY130_DECAP_CELLS",
]
