"""PCB DRC (spatial checks).

Uses shapely when available; otherwise falls back to bounding-box and
segment-segment distance math.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from openforge.pcb.model import PcbBoard

try:  # pragma: no cover - optional
    _HAS_SHAPELY = True
except Exception:  # pragma: no cover
    _HAS_SHAPELY = False


RuleKind = Literal[
    "clearance",
    "track_width",
    "drill_to_drill",
    "annular_ring",
    "silkscreen_overlap",
    "courtyard_overlap",
    "unconnected_net",
]


class PcbDrcRule(BaseModel):
    kind: RuleKind
    value_mm: float = 0.2
    layer: str | None = None


class PcbDrcViolation(BaseModel):
    rule: str
    x_mm: float
    y_mm: float
    message: str
    severity: str = "error"


# ----------------------------------------------------------------------
def _seg_seg_distance(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    def pt_seg(p, s, e):
        sx, sy = s
        ex, ey = e
        px, py = p
        dx, dy = ex - sx, ey - sy
        if dx == 0 and dy == 0:
            return math.hypot(px - sx, py - sy)
        t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
        qx, qy = sx + t * dx, sy + t * dy
        return math.hypot(px - qx, py - qy)

    return min(
        pt_seg(a, c, d),
        pt_seg(b, c, d),
        pt_seg(c, a, b),
        pt_seg(d, a, b),
    )


def _poly_bbox(poly: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_overlap(a, b) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


class PcbDrcChecker:
    def __init__(self, board: PcbBoard, rules: list[PcbDrcRule] | None = None) -> None:
        self.board = board
        self.rules = rules or [
            PcbDrcRule(kind="clearance", value_mm=0.2),
            PcbDrcRule(kind="track_width", value_mm=0.1),
            PcbDrcRule(kind="drill_to_drill", value_mm=0.3),
            PcbDrcRule(kind="annular_ring", value_mm=0.1),
            PcbDrcRule(kind="silkscreen_overlap", value_mm=0.15),
            PcbDrcRule(kind="courtyard_overlap", value_mm=0.0),
            PcbDrcRule(kind="unconnected_net", value_mm=0.0),
        ]

    def _rule(self, kind: str) -> PcbDrcRule | None:
        for r in self.rules:
            if r.kind == kind:
                return r
        return None

    # ------------------------------------------------------------------
    def check_track_width(self) -> list[PcbDrcViolation]:
        rule = self._rule("track_width")
        if not rule:
            return []
        out: list[PcbDrcViolation] = []
        for t in self.board.tracks:
            if t.width_mm + 1e-9 < rule.value_mm:
                out.append(
                    PcbDrcViolation(
                        rule="track_width",
                        x_mm=(t.x1_mm + t.x2_mm) / 2,
                        y_mm=(t.y1_mm + t.y2_mm) / 2,
                        message=f"Track width {t.width_mm:.3f}mm < min {rule.value_mm:.3f}mm",
                    )
                )
        return out

    def check_clearance(self) -> list[PcbDrcViolation]:
        rule = self._rule("clearance")
        if not rule:
            return []
        clr = rule.value_mm
        out: list[PcbDrcViolation] = []
        tracks = list(self.board.tracks)
        for i in range(len(tracks)):
            a = tracks[i]
            for j in range(i + 1, len(tracks)):
                b = tracks[j]
                if a.layer != b.layer:
                    continue
                if a.net != 0 and a.net == b.net:
                    continue
                dist = _seg_seg_distance(
                    (a.x1_mm, a.y1_mm),
                    (a.x2_mm, a.y2_mm),
                    (b.x1_mm, b.y1_mm),
                    (b.x2_mm, b.y2_mm),
                )
                min_d = (a.width_mm + b.width_mm) / 2 + clr
                if dist + 1e-9 < min_d:
                    out.append(
                        PcbDrcViolation(
                            rule="clearance",
                            x_mm=(a.x1_mm + a.x2_mm) / 2,
                            y_mm=(a.y1_mm + a.y2_mm) / 2,
                            message=f"Track clearance {dist:.3f}mm < {min_d:.3f}mm",
                        )
                    )
        return out

    def check_drill_to_drill(self) -> list[PcbDrcViolation]:
        rule = self._rule("drill_to_drill")
        if not rule:
            return []
        clr = rule.value_mm
        drills: list[tuple[float, float, float]] = []  # x, y, dia
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.drill_mm > 0:
                    x, y = fp.pad_world_xy(pad)
                    drills.append((x, y, pad.drill_mm))
        for via in self.board.vias:
            drills.append((via.x_mm, via.y_mm, via.drill_mm))

        out: list[PcbDrcViolation] = []
        for i in range(len(drills)):
            x1, y1, d1 = drills[i]
            for j in range(i + 1, len(drills)):
                x2, y2, d2 = drills[j]
                dist = math.hypot(x1 - x2, y1 - y2)
                min_d = (d1 + d2) / 2 + clr
                if dist + 1e-9 < min_d:
                    out.append(
                        PcbDrcViolation(
                            rule="drill_to_drill",
                            x_mm=(x1 + x2) / 2,
                            y_mm=(y1 + y2) / 2,
                            message=f"Drill clearance {dist:.3f}mm < {min_d:.3f}mm",
                        )
                    )
        return out

    def check_annular_ring(self) -> list[PcbDrcViolation]:
        rule = self._rule("annular_ring")
        if not rule:
            return []
        min_ann = rule.value_mm
        out: list[PcbDrcViolation] = []
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.drill_mm > 0:
                    ann = (min(pad.size_x_mm, pad.size_y_mm) - pad.drill_mm) / 2
                    if ann + 1e-9 < min_ann:
                        x, y = fp.pad_world_xy(pad)
                        out.append(
                            PcbDrcViolation(
                                rule="annular_ring",
                                x_mm=x,
                                y_mm=y,
                                message=f"{fp.ref}.{pad.name} annular ring {ann:.3f}mm < {min_ann:.3f}mm",
                            )
                        )
        for via in self.board.vias:
            ann = (via.diameter_mm - via.drill_mm) / 2
            if ann + 1e-9 < min_ann:
                out.append(
                    PcbDrcViolation(
                        rule="annular_ring",
                        x_mm=via.x_mm,
                        y_mm=via.y_mm,
                        message=f"Via annular ring {ann:.3f}mm < {min_ann:.3f}mm",
                    )
                )
        return out

    def check_silkscreen_overlap(self) -> list[PcbDrcViolation]:
        rule = self._rule("silkscreen_overlap")
        if not rule:
            return []
        clr = rule.value_mm
        out: list[PcbDrcViolation] = []
        # Collect pad bboxes on top (simplification)
        pad_boxes: list[tuple[float, float, float, float]] = []
        for fp in self.board.footprints:
            for pad in fp.pads:
                x, y = fp.pad_world_xy(pad)
                pad_boxes.append(
                    (
                        x - pad.size_x_mm / 2 - clr,
                        y - pad.size_y_mm / 2 - clr,
                        x + pad.size_x_mm / 2 + clr,
                        y + pad.size_y_mm / 2 + clr,
                    )
                )
        for fp in self.board.footprints:
            for x1, y1, x2, y2 in fp.silkscreen:
                # to world
                rot = math.radians(fp.rotation_deg)
                cs, sn = math.cos(rot), math.sin(rot)
                wx1 = fp.x_mm + x1 * cs - y1 * sn
                wy1 = fp.y_mm + x1 * sn + y1 * cs
                wx2 = fp.x_mm + x2 * cs - y2 * sn
                wy2 = fp.y_mm + x2 * sn + y2 * cs
                sbox = (min(wx1, wx2), min(wy1, wy2), max(wx1, wx2), max(wy1, wy2))
                for pb in pad_boxes:
                    if _bbox_overlap(sbox, pb):
                        out.append(
                            PcbDrcViolation(
                                rule="silkscreen_overlap",
                                x_mm=(wx1 + wx2) / 2,
                                y_mm=(wy1 + wy2) / 2,
                                message=f"Silkscreen overlaps pad near {fp.ref}",
                                severity="warning",
                            )
                        )
                        break
        return out

    def check_courtyard_overlap(self) -> list[PcbDrcViolation]:
        out: list[PcbDrcViolation] = []
        fps = self.board.footprints
        boxes: list[tuple[float, float, float, float]] = []
        for fp in fps:
            if not fp.courtyard:
                boxes.append((fp.x_mm - 1, fp.y_mm - 1, fp.x_mm + 1, fp.y_mm + 1))
                continue
            xs, ys = [], []
            rot = math.radians(fp.rotation_deg)
            cs, sn = math.cos(rot), math.sin(rot)
            for x, y in fp.courtyard:
                xs.append(fp.x_mm + x * cs - y * sn)
                ys.append(fp.y_mm + x * sn + y * cs)
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _bbox_overlap(boxes[i], boxes[j]):
                    out.append(
                        PcbDrcViolation(
                            rule="courtyard_overlap",
                            x_mm=(boxes[i][0] + boxes[i][2]) / 2,
                            y_mm=(boxes[i][1] + boxes[i][3]) / 2,
                            message=f"Courtyards overlap: {fps[i].ref} and {fps[j].ref}",
                            severity="warning",
                        )
                    )
        return out

    def check_unconnected_nets(self) -> list[PcbDrcViolation]:
        out: list[PcbDrcViolation] = []
        pad_nets: dict[int, int] = {}
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.net > 0:
                    pad_nets[pad.net] = pad_nets.get(pad.net, 0) + 1
        track_nets: set[int] = set(t.net for t in self.board.tracks if t.net > 0)
        for net_id, count in pad_nets.items():
            if count >= 2 and net_id not in track_nets:
                name = self.board.net_name(net_id)
                out.append(
                    PcbDrcViolation(
                        rule="unconnected_net",
                        x_mm=0,
                        y_mm=0,
                        message=f"Net {name or net_id} has no routed tracks",
                    )
                )
        return out

    def check_all(self) -> list[PcbDrcViolation]:
        out: list[PcbDrcViolation] = []
        out.extend(self.check_track_width())
        out.extend(self.check_clearance())
        out.extend(self.check_drill_to_drill())
        out.extend(self.check_annular_ring())
        out.extend(self.check_silkscreen_overlap())
        out.extend(self.check_courtyard_overlap())
        out.extend(self.check_unconnected_nets())
        return out
