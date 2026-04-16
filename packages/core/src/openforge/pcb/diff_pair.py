"""Differential pair detection, impedance calculation, and routing."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover
    from openforge.pcb.model import PcbBoard
    from openforge.pcb.net_classes import NetClassRegistry


class DiffPair(BaseModel):
    name: str
    pos_net: str
    neg_net: str
    target_impedance_ohm: float = 100.0
    gap_mm: float = 0.15
    width_mm: float = 0.15


class DiffPairRouter:
    """Detection + geometry calculator + routing helper for diff pairs."""

    def __init__(self, board: PcbBoard, net_classes: NetClassRegistry | None = None) -> None:
        from openforge.pcb.net_classes import NetClassRegistry

        self.board = board
        self.net_classes = net_classes or NetClassRegistry.with_defaults()

    # ---- detection ---------------------------------------------------
    def detect_pairs(self, pattern: str = r"(.+?)[_\-]?([PpNn])(?:os|eg)?$") -> list[DiffPair]:
        """Find candidate diff pairs by net naming conventions.

        Matches things like ``USB_DP`` / ``USB_DN``, ``CLK_P`` / ``CLK_N``,
        ``DATA_POS`` / ``DATA_NEG``.
        """
        rx = re.compile(pattern)
        names = [nm for nm in self.board.nets.values() if nm]
        # Group by prefix -> {polarity: name}
        groups: dict[str, dict[str, str]] = {}
        for name in names:
            m = rx.match(name)
            if not m:
                continue
            prefix = m.group(1).rstrip("_-")
            polarity = m.group(2).upper()
            groups.setdefault(prefix, {})[polarity] = name
        pairs: list[DiffPair] = []
        for prefix, pol in groups.items():
            if "P" in pol and "N" in pol:
                klass = self.net_classes.get_for_net(pol["P"])
                pairs.append(
                    DiffPair(
                        name=prefix,
                        pos_net=pol["P"],
                        neg_net=pol["N"],
                        target_impedance_ohm=klass.impedance_target_ohm or 100.0,
                        gap_mm=klass.diff_pair_gap_mm or 0.15,
                        width_mm=klass.diff_pair_width_mm or 0.15,
                    )
                )
        return pairs

    # ---- impedance calculation --------------------------------------
    def calc_geometry(
        self,
        impedance: float,
        dielectric: float = 4.3,
        height_mm: float = 0.2,
        copper_oz: float = 1.0,
    ) -> tuple[float, float]:
        """Edge-coupled microstrip geometry for a target differential impedance.

        Uses the IPC-2141 / Wadell edge-coupled microstrip approximation:

            Zdiff ≈ 2 * Z0 * (1 - 0.48 * exp(-0.96 * s / h))

        Z0 is the single-ended microstrip impedance for the chosen width.
        We solve iteratively for ``w`` and ``s``.
        """
        er = dielectric
        h = height_mm
        0.0348 * copper_oz  # 1 oz ~ 34.8 um

        def z0_microstrip(w: float) -> float:
            # Hammerstad-Jensen microstrip single-ended
            wh = w / h
            if wh < 1.0:
                return (
                    60.0 / math.sqrt((er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / wh))
                ) * math.log(8 / wh + wh / 4)
            return (
                120.0 * math.pi / math.sqrt((er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / wh))
            ) / (wh + 1.393 + 0.667 * math.log(wh + 1.444))

        def zdiff(w: float, s: float) -> float:
            z0 = z0_microstrip(w)
            return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))

        # initial guess
        w = h * 2
        s = h
        for _ in range(40):
            z = zdiff(w, s)
            err = z - impedance
            if abs(err) < 0.5:
                break
            # grow/shrink w
            w *= 1 + (err / impedance) * 0.3
            w = max(0.05, min(1.0, w))
        # adjust gap for fine tune
        for _ in range(40):
            z = zdiff(w, s)
            err = z - impedance
            if abs(err) < 0.3:
                break
            s *= 1 - (err / impedance) * 0.3
            s = max(0.05, min(1.0, s))
        # round to common fab resolution
        return (round(w, 3), round(s, 3))

    # ---- routing -----------------------------------------------------
    def route(self, pair: DiffPair, start: tuple[float, float], end: tuple[float, float]) -> bool:
        from openforge.pcb.router import PcbRouter

        router = PcbRouter(self.board, self.net_classes)
        # route pos first
        pos_path = router.walkaround(start, end, pair.pos_net)
        if not pos_path:
            return False
        # offset for neg line
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length
        off = pair.gap_mm + pair.width_mm
        neg_start = (start[0] + px * off, start[1] + py * off)
        neg_end = (end[0] + px * off, end[1] + py * off)
        neg_path = router.walkaround(neg_start, neg_end, pair.neg_net)
        return bool(neg_path)

    # ---- DRC ---------------------------------------------------------
    def gap_violations(self, pair: DiffPair) -> list[dict]:
        """Return track pairs on pair's two nets that violate the gap."""

        nid_p = None
        nid_n = None
        for nid, nm in self.board.nets.items():
            if nm == pair.pos_net:
                nid_p = nid
            elif nm == pair.neg_net:
                nid_n = nid
        if nid_p is None or nid_n is None:
            return []
        pos_tracks = [t for t in self.board.tracks if t.net == nid_p]
        neg_tracks = [t for t in self.board.tracks if t.net == nid_n]
        violations: list[dict] = []
        for p in pos_tracks:
            pm = ((p.x1_mm + p.x2_mm) / 2, (p.y1_mm + p.y2_mm) / 2)
            for n in neg_tracks:
                nm = ((n.x1_mm + n.x2_mm) / 2, (n.y1_mm + n.y2_mm) / 2)
                d = math.hypot(pm[0] - nm[0], pm[1] - nm[1])
                if abs(d - pair.gap_mm) > pair.gap_mm * 0.5:
                    violations.append({"pos": p, "neg": n, "distance_mm": d})
        return violations

    def length_skew(self, pair: DiffPair) -> float:
        nid_p = None
        nid_n = None
        for nid, nm in self.board.nets.items():
            if nm == pair.pos_net:
                nid_p = nid
            elif nm == pair.neg_net:
                nid_n = nid
        if nid_p is None or nid_n is None:
            return 0.0
        lp = sum(t.length_mm() for t in self.board.tracks if t.net == nid_p)
        ln = sum(t.length_mm() for t in self.board.tracks if t.net == nid_n)
        return lp - ln


__all__ = ["DiffPair", "DiffPairRouter"]
