"""PCB fabrication rule classes and cost estimator.

Captures published manufacturing constraints for common PCB fab houses
(JLCPCB, OSH Park, PCBWay, Seeed Studio) and produces:

- A list of PcbDrcViolation entries for features that fall below the
  fab's advertised capability.
- A cost estimate (board area, quantity-based scaling) using the
  houses' public pricing as of 2024.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover
    from openforge.pcb.model import PcbBoard

from openforge.pcb.drc import PcbDrcViolation


class FabRule(BaseModel):
    """A single named fabrication rule."""

    rule_id: str
    description: str
    value: float
    units: str


class FabClass(BaseModel):
    """A fab house's manufacturing capability class."""

    name: str
    min_track_mm: float
    min_clearance_mm: float
    min_drill_mm: float
    min_annular_ring_mm: float
    min_silk_text_mm: float = 0.8
    max_layers: int = 2
    max_board_size_mm: tuple[float, float] = (200.0, 200.0)
    impedance_control: bool = False
    cost_per_dm2: float = 5.0  # USD per dm^2 @ qty 5
    setup_cost: float = 2.0  # USD
    min_order_qty: int = 5

    def area_cost(self, area_mm2: float, quantity: int) -> float:
        area_dm2 = max(area_mm2 / 10000.0, 0.01)
        # Quantity curve: diminishing per-unit cost with volume
        qty_factor = 1.0 + 0.15 * math.log10(max(quantity, 1))
        return self.setup_cost + area_dm2 * self.cost_per_dm2 * quantity / qty_factor


# ----------------------------------------------------------------------
# Published capability snapshots (2024). Values are real advertised
# limits; tighter tech classes require explicit order upgrades.
KNOWN_FAB_CLASSES: dict[str, FabClass] = {
    "jlcpcb_2layer_standard": FabClass(
        name="JLCPCB 2-layer Standard",
        min_track_mm=0.127,  # 5 mil
        min_clearance_mm=0.127,  # 5 mil
        min_drill_mm=0.3,
        min_annular_ring_mm=0.13,
        min_silk_text_mm=0.8,
        max_layers=2,
        max_board_size_mm=(400.0, 500.0),
        impedance_control=False,
        cost_per_dm2=2.0,
        setup_cost=2.0,
        min_order_qty=5,
    ),
    "jlcpcb_4layer_standard": FabClass(
        name="JLCPCB 4-layer Standard",
        min_track_mm=0.0889,  # 3.5 mil
        min_clearance_mm=0.0889,
        min_drill_mm=0.3,
        min_annular_ring_mm=0.13,
        min_silk_text_mm=0.8,
        max_layers=4,
        max_board_size_mm=(400.0, 500.0),
        impedance_control=True,
        cost_per_dm2=18.0,
        setup_cost=7.0,
        min_order_qty=5,
    ),
    "jlcpcb_advanced": FabClass(
        name="JLCPCB Advanced (6-8 layer)",
        min_track_mm=0.0762,  # 3 mil
        min_clearance_mm=0.0762,
        min_drill_mm=0.15,
        min_annular_ring_mm=0.1,
        min_silk_text_mm=0.6,
        max_layers=8,
        max_board_size_mm=(400.0, 500.0),
        impedance_control=True,
        cost_per_dm2=35.0,
        setup_cost=20.0,
        min_order_qty=5,
    ),
    "oshpark_2layer": FabClass(
        name="OSH Park 2-layer (1 oz)",
        min_track_mm=0.1524,  # 6 mil
        min_clearance_mm=0.1524,
        min_drill_mm=0.3302,  # 13 mil
        min_annular_ring_mm=0.1016,  # 4 mil
        min_silk_text_mm=1.0,
        max_layers=2,
        max_board_size_mm=(400.0, 400.0),
        impedance_control=False,
        cost_per_dm2=77.5,  # $5/in^2 for 3 copies, divided per board
        setup_cost=0.0,
        min_order_qty=3,
    ),
    "oshpark_4layer": FabClass(
        name="OSH Park 4-layer",
        min_track_mm=0.127,  # 5 mil
        min_clearance_mm=0.127,
        min_drill_mm=0.3302,
        min_annular_ring_mm=0.1016,
        min_silk_text_mm=1.0,
        max_layers=4,
        max_board_size_mm=(400.0, 400.0),
        impedance_control=False,
        cost_per_dm2=155.0,  # $10/in^2 for 3 copies
        setup_cost=0.0,
        min_order_qty=3,
    ),
    "pcbway_standard": FabClass(
        name="PCBWay Standard",
        min_track_mm=0.1524,
        min_clearance_mm=0.1524,
        min_drill_mm=0.3,
        min_annular_ring_mm=0.13,
        min_silk_text_mm=0.8,
        max_layers=14,
        max_board_size_mm=(500.0, 500.0),
        impedance_control=True,
        cost_per_dm2=5.0,
        setup_cost=5.0,
        min_order_qty=5,
    ),
    "seeedstudio": FabClass(
        name="Seeed Fusion 2-layer",
        min_track_mm=0.1524,
        min_clearance_mm=0.1524,
        min_drill_mm=0.3,
        min_annular_ring_mm=0.13,
        min_silk_text_mm=0.8,
        max_layers=6,
        max_board_size_mm=(300.0, 300.0),
        impedance_control=False,
        cost_per_dm2=4.9,
        setup_cost=4.9,
        min_order_qty=5,
    ),
}


class FabRuleChecker:
    """Check a PcbBoard against a FabClass and estimate cost."""

    def __init__(self, board: "PcbBoard", fab_class: FabClass) -> None:
        self.board = board
        self.fab_class = fab_class

    # ------------------------------------------------------------------
    def check_all(self) -> list[PcbDrcViolation]:
        viols: list[PcbDrcViolation] = []
        fc = self.fab_class

        # Tracks
        for t in getattr(self.board, "tracks", []):
            if t.width_mm + 1e-9 < fc.min_track_mm:
                viols.append(
                    PcbDrcViolation(
                        rule="fab_min_track",
                        x_mm=(t.x1_mm + t.x2_mm) / 2,
                        y_mm=(t.y1_mm + t.y2_mm) / 2,
                        message=(
                            f"Track width {t.width_mm:.4f}mm below "
                            f"{fc.name} minimum {fc.min_track_mm:.4f}mm"
                        ),
                        severity="error",
                    )
                )

        # Vias — drill and annular ring
        for v in getattr(self.board, "vias", []):
            if v.drill_mm + 1e-9 < fc.min_drill_mm:
                viols.append(
                    PcbDrcViolation(
                        rule="fab_min_drill",
                        x_mm=v.x_mm,
                        y_mm=v.y_mm,
                        message=(
                            f"Via drill {v.drill_mm:.3f}mm below "
                            f"{fc.name} minimum {fc.min_drill_mm:.3f}mm"
                        ),
                        severity="error",
                    )
                )
            ring = (v.diameter_mm - v.drill_mm) / 2.0
            if ring + 1e-9 < fc.min_annular_ring_mm:
                viols.append(
                    PcbDrcViolation(
                        rule="fab_min_annular_ring",
                        x_mm=v.x_mm,
                        y_mm=v.y_mm,
                        message=(
                            f"Annular ring {ring:.3f}mm below "
                            f"{fc.name} minimum {fc.min_annular_ring_mm:.3f}mm"
                        ),
                        severity="error",
                    )
                )

        # Footprint pads — annular ring for THT
        for fp in getattr(self.board, "footprints", []):
            for pad in fp.pads:
                if pad.drill_mm > 0:
                    pad_dia = min(pad.size_x_mm, pad.size_y_mm)
                    ring = (pad_dia - pad.drill_mm) / 2.0
                    if ring + 1e-9 < fc.min_annular_ring_mm:
                        wx, wy = fp.pad_world_xy(pad)
                        viols.append(
                            PcbDrcViolation(
                                rule="fab_min_annular_ring",
                                x_mm=wx,
                                y_mm=wy,
                                message=(
                                    f"Pad {fp.ref}.{pad.name} annular ring "
                                    f"{ring:.3f}mm below {fc.name} minimum "
                                    f"{fc.min_annular_ring_mm:.3f}mm"
                                ),
                                severity="error",
                            )
                        )
                    if pad.drill_mm + 1e-9 < fc.min_drill_mm:
                        wx, wy = fp.pad_world_xy(pad)
                        viols.append(
                            PcbDrcViolation(
                                rule="fab_min_drill",
                                x_mm=wx,
                                y_mm=wy,
                                message=(
                                    f"Pad {fp.ref}.{pad.name} drill "
                                    f"{pad.drill_mm:.3f}mm below {fc.name} "
                                    f"minimum {fc.min_drill_mm:.3f}mm"
                                ),
                                severity="error",
                            )
                        )

        # Board size
        bx0, by0, bx1, by1 = self.board.bounding_box()
        width = bx1 - bx0
        height = by1 - by0
        if width > fc.max_board_size_mm[0] or height > fc.max_board_size_mm[1]:
            viols.append(
                PcbDrcViolation(
                    rule="fab_max_board_size",
                    x_mm=(bx0 + bx1) / 2,
                    y_mm=(by0 + by1) / 2,
                    message=(
                        f"Board {width:.1f}x{height:.1f}mm exceeds {fc.name} "
                        f"maximum {fc.max_board_size_mm[0]:.0f}x"
                        f"{fc.max_board_size_mm[1]:.0f}mm"
                    ),
                    severity="error",
                )
            )

        # Layer count
        stackup = getattr(self.board, "stackup", None)
        if stackup is not None:
            n_cu = sum(
                1
                for layer in getattr(stackup, "layers", [])
                if getattr(layer, "kind", "") in ("signal", "plane")
            )
            if n_cu > fc.max_layers:
                viols.append(
                    PcbDrcViolation(
                        rule="fab_max_layers",
                        x_mm=0.0,
                        y_mm=0.0,
                        message=(
                            f"Stackup has {n_cu} copper layers, exceeds "
                            f"{fc.name} maximum {fc.max_layers}"
                        ),
                        severity="error",
                    )
                )

        return viols

    # ------------------------------------------------------------------
    def cost_estimate(self, quantity: int) -> dict[str, float]:
        bx0, by0, bx1, by1 = self.board.bounding_box()
        width = max(bx1 - bx0, 1.0)
        height = max(by1 - by0, 1.0)
        area_mm2 = width * height
        qty = max(quantity, self.fab_class.min_order_qty)
        total = self.fab_class.area_cost(area_mm2, qty)
        unit = total / max(qty, 1)
        return {
            "board_width_mm": width,
            "board_height_mm": height,
            "board_area_mm2": area_mm2,
            "board_area_dm2": area_mm2 / 10000.0,
            "quantity": qty,
            "unit_cost_usd": round(unit, 3),
            "total_cost_usd": round(total, 2),
            "setup_cost_usd": self.fab_class.setup_cost,
            "fab_class": self.fab_class.name,
        }


__all__ = ["FabRule", "FabClass", "FabRuleChecker", "KNOWN_FAB_CLASSES"]
