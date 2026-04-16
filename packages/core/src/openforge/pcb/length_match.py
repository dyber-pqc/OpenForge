"""Length matching / serpentine tromboning engine.

Given a group of nets with a target length and tolerance, this module
measures each net's routed length and adds serpentine (tromboning)
detours to bring shorter nets up to target.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover
    from openforge.pcb.model import PcbBoard


Method = Literal["serpentine", "tromboning", "meander"]


class LengthGroup(BaseModel):
    name: str
    nets: list[str] = Field(default_factory=list)
    target_mm: float | None = None
    tolerance_mm: float = 0.5
    method: Method = "serpentine"


class LengthMatcher:
    """Measure and add detours to match net lengths."""

    def __init__(self, board: PcbBoard) -> None:
        self.board = board
        self._name_to_id = {nm: nid for nid, nm in board.nets.items() if nm}

    # ---- measurement -------------------------------------------------
    def measure_net(self, net: str) -> float:
        nid = self._name_to_id.get(net)
        if nid is None:
            return 0.0
        total = 0.0
        for t in self.board.tracks:
            if t.net == nid:
                total += t.length_mm()
        return total

    def measure_group(self, group: LengthGroup) -> dict[str, float]:
        return {n: self.measure_net(n) for n in group.nets}

    # ---- auto topology ----------------------------------------------
    def auto_topology(self, group: LengthGroup) -> str:
        """Heuristic: inspect endpoint fan-out to guess the topology."""
        fanout = 0
        for net in group.nets:
            nid = self._name_to_id.get(net)
            if nid is None:
                continue
            sinks = 0
            for fp in self.board.footprints:
                for pad in fp.pads:
                    if pad.net == nid:
                        sinks += 1
            if sinks > 2:
                fanout += 1
        if fanout >= max(1, len(group.nets) // 2):
            return "fly_by"
        if len(group.nets) >= 4:
            return "daisy_chain"
        return "star"

    # ---- serpentine insertion ---------------------------------------
    def add_serpentine(self, net: str, extra_length_mm: float, segment_idx: int = 0) -> bool:
        """Insert a serpentine into net, adding ``extra_length_mm`` of length.

        The serpentine is inserted by replacing segment ``segment_idx`` of
        the net's longest track with a zig-zag that adds the required
        detour length. The detour is placed perpendicular to the segment
        direction.
        """
        from openforge.pcb.model import PcbTrack

        if extra_length_mm <= 0.0:
            return True
        nid = self._name_to_id.get(net)
        if nid is None:
            return False
        net_tracks = [t for t in self.board.tracks if t.net == nid]
        if not net_tracks:
            return False
        seg = net_tracks[min(segment_idx, len(net_tracks) - 1)]
        # Direction
        dx = seg.x2_mm - seg.x1_mm
        dy = seg.y2_mm - seg.y1_mm
        seg_len = math.hypot(dx, dy)
        if seg_len < 1.0:
            return False
        ux, uy = dx / seg_len, dy / seg_len
        # perpendicular
        px, py = -uy, ux

        # Serpentine geometry: N bumps, each bump adds ~ (2*amp + pitch) - pitch
        # = 2*amp of extra length. Use amplitude = 1.0 mm.
        amp = max(0.5, seg.width_mm * 4)
        # Each full zig-zag (up then down) adds 2*amp extra
        n_bumps = max(1, int(math.ceil(extra_length_mm / (2 * amp))))
        # Pitch between bumps so they fit in the segment.
        usable = seg_len * 0.6  # leave 20% on each end for lead-in/out
        pitch = usable / max(1, n_bumps * 2)
        if pitch < seg.width_mm * 2:
            return False

        # Remove the original segment
        self.board.tracks.remove(seg)
        # Start midway
        start_t = (seg_len - n_bumps * 2 * pitch) / 2
        sx = seg.x1_mm + ux * start_t
        sy = seg.y1_mm + uy * start_t

        pts: list[tuple[float, float]] = [(seg.x1_mm, seg.y1_mm), (sx, sy)]
        cur_x, cur_y = sx, sy
        direction = 1
        for _ in range(n_bumps):
            # up
            nx = cur_x + px * amp * direction
            ny = cur_y + py * amp * direction
            pts.append((nx, ny))
            # across
            nx2 = nx + ux * pitch
            ny2 = ny + uy * pitch
            pts.append((nx2, ny2))
            # back down
            nx3 = nx2 - px * amp * direction
            ny3 = ny2 - py * amp * direction
            pts.append((nx3, ny3))
            # advance
            cur_x = nx3 + ux * pitch
            cur_y = ny3 + uy * pitch
            pts.append((cur_x, cur_y))
        pts.append((seg.x2_mm, seg.y2_mm))

        for i in range(len(pts) - 1):
            self.board.tracks.append(
                PcbTrack(
                    layer=seg.layer,
                    x1_mm=pts[i][0],
                    y1_mm=pts[i][1],
                    x2_mm=pts[i + 1][0],
                    y2_mm=pts[i + 1][1],
                    width_mm=seg.width_mm,
                    net=nid,
                )
            )
        return True

    # ---- group matching ---------------------------------------------
    def match_group(self, group: LengthGroup) -> dict[str, float]:
        """Pad each net up to target length (or longest in group)."""
        lengths = self.measure_group(group)
        if not lengths:
            return {}
        target = group.target_mm if group.target_mm else max(lengths.values())
        tolerance = group.tolerance_mm
        deltas: dict[str, float] = {}
        for net, length in lengths.items():
            delta = target - length
            if delta <= tolerance:
                deltas[net] = 0.0
                continue
            ok = self.add_serpentine(net, delta)
            deltas[net] = delta if ok else 0.0
        return deltas


__all__ = ["LengthGroup", "LengthMatcher", "Method"]
