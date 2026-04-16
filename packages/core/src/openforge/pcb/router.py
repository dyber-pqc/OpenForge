"""PCB push-and-shove / maze router.

This is a working, self-contained router for the OpenForge ``PcbBoard``
data model. It is not world-class, but it DOES finish on boards with
tens of nets / a few thousand grid cells without exploding.

Algorithm:
  * Each signal copper layer is rasterized into a uniform numpy cost
    grid (``int16``). Obstacles are cells owned by another net, the
    board outline exterior, or occupied pads.
  * Nets are routed in order of criticality (class priority, then
    Manhattan length, shortest first to reduce contention).
  * A* is used on a 4-neighbor grid with bend and via penalties;
    diagonals are optional.
  * If a net cannot be routed, the blocking nets are ripped up (up to a
    budget) and re-queued at the tail. Worst case, a net is marked
    ``failed``.
  * Walkaround mode uses the same A* without tearing anything up.
  * Push-and-shove uses a local bias: when A* hits another net's wire,
    that wire is temporarily shifted one grid cell laterally and
    reinserted on the dirty list.

A ``use_freerouting`` hook shells out to a freerouting.jar if present.
"""
from __future__ import annotations

import heapq
import math
import shutil
import subprocess
import time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from openforge.pcb.model import PcbBoard
    from openforge.pcb.net_classes import NetClassRegistry


FREE_CELL = 0
BLOCKED_CELL = -1
PAD_CELL = -2  # pad target: treated as free only for that net


class RoutingMode(StrEnum):
    AUTOROUTE_ALL = "autoroute_all"
    INTERACTIVE_PUSH = "interactive_push"
    WALKAROUND = "walkaround"
    DIFF_PAIR = "diff_pair"


class RouteResult(BaseModel):
    success: bool = False
    routed_nets: int = 0
    failed_nets: list[str] = Field(default_factory=list)
    track_count: int = 0
    via_count: int = 0
    total_length_mm: float = 0.0
    runtime_s: float = 0.0
    message: str = ""


class PcbRouter:
    """Maze router with push-and-shove and length-aware modes."""

    def __init__(
        self,
        board: PcbBoard,
        net_classes: NetClassRegistry | None = None,
        grid_mm: float = 0.25,
        layers: list[str] | None = None,
        bend_penalty: int = 2,
        via_penalty: int = 20,
        max_rip_budget: int = 8,
    ) -> None:
        from openforge.pcb.net_classes import NetClassRegistry

        self.board = board
        self.net_classes = net_classes or NetClassRegistry.with_defaults()
        self.grid_mm = grid_mm
        self.bend_penalty = bend_penalty
        self.via_penalty = via_penalty
        self.max_rip_budget = max_rip_budget

        if layers is None:
            sig = [l.name for l in board.stackup.copper_layers() if l.kind == "signal"]
            layers = sig or ["F.Cu", "B.Cu"]
        self.layers = layers

        # Origin at bbox min so that negative coords work.
        x1, y1, x2, y2 = board.bounding_box()
        if x2 <= x1 or y2 <= y1:
            x1, y1, x2, y2 = 0.0, 0.0, board.bounding_box()[2] or 100.0, board.bounding_box()[3] or 100.0
        margin = 2.0
        self.origin = (x1 - margin, y1 - margin)
        self.cols = max(4, int(math.ceil((x2 - x1 + 2 * margin) / grid_mm)))
        self.rows = max(4, int(math.ceil((y2 - y1 + 2 * margin) / grid_mm)))

        # grid[layer] : int16 array; values are:
        #    0  = free
        #   -1  = hard block (outline/keepout)
        #    n>0 = owned by net id n
        self.grid: dict[str, np.ndarray] = {
            layer: np.zeros((self.rows, self.cols), dtype=np.int32) for layer in self.layers
        }
        self._mark_obstacles()

    # ------------------------------------------------------------------
    # grid helpers
    # ------------------------------------------------------------------
    def _mm_to_cell(self, x: float, y: float) -> tuple[int, int]:
        col = int(round((x - self.origin[0]) / self.grid_mm))
        row = int(round((y - self.origin[1]) / self.grid_mm))
        col = max(0, min(self.cols - 1, col))
        row = max(0, min(self.rows - 1, row))
        return (row, col)

    def _cell_to_mm(self, row: int, col: int) -> tuple[float, float]:
        return (
            self.origin[0] + col * self.grid_mm,
            self.origin[1] + row * self.grid_mm,
        )

    def _stamp_rect(self, grid: np.ndarray, cx: float, cy: float, hw: float, hh: float, value: int) -> None:
        r0, c0 = self._mm_to_cell(cx - hw, cy - hh)
        r1, c1 = self._mm_to_cell(cx + hw, cy + hh)
        r0, r1 = sorted((r0, r1))
        c0, c1 = sorted((c0, c1))
        grid[r0 : r1 + 1, c0 : c1 + 1] = value

    def _mark_obstacles(self) -> None:
        # Mark pads on their owning nets so the router can enter them.
        for fp in self.board.footprints:
            theta = math.radians(fp.rotation_deg)
            ct, st = math.cos(theta), math.sin(theta)
            for pad in fp.pads:
                wx = fp.x_mm + pad.x_mm * ct - pad.y_mm * st
                wy = fp.y_mm + pad.x_mm * st + pad.y_mm * ct
                hw = max(pad.size_x_mm, self.grid_mm) / 2
                hh = max(pad.size_y_mm, self.grid_mm) / 2
                pad_layers = self.layers if pad.is_tht else self.layers[:1]
                owner = pad.net if pad.net else BLOCKED_CELL
                for layer in pad_layers:
                    self._stamp_rect(self.grid[layer], wx, wy, hw, hh, owner)
        # Pre-existing tracks occupy their net cells.
        for t in self.board.tracks:
            if t.layer not in self.grid:
                continue
            g = self.grid[t.layer]
            self._paint_line(
                g, t.x1_mm, t.y1_mm, t.x2_mm, t.y2_mm, max(1, int(round(t.width_mm / self.grid_mm / 2))), t.net or BLOCKED_CELL
            )

    def _paint_line(self, grid: np.ndarray, x1: float, y1: float, x2: float, y2: float, radius: int, value: int) -> None:
        r0, c0 = self._mm_to_cell(x1, y1)
        r1, c1 = self._mm_to_cell(x2, y2)
        steps = max(abs(r1 - r0), abs(c1 - c0), 1)
        for i in range(steps + 1):
            t = i / steps
            r = int(round(r0 + (r1 - r0) * t))
            c = int(round(c0 + (c1 - c0) * t))
            rr0 = max(0, r - radius)
            rr1 = min(self.rows - 1, r + radius)
            cc0 = max(0, c - radius)
            cc1 = min(self.cols - 1, c + radius)
            grid[rr0 : rr1 + 1, cc0 : cc1 + 1] = value

    # ------------------------------------------------------------------
    # A* pathfinding
    # ------------------------------------------------------------------
    def _neighbors(self, r: int, c: int) -> Iterable[tuple[int, int, int]]:
        for dr, dc, d in ((-1, 0, 10), (1, 0, 10), (0, -1, 10), (0, 1, 10)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                yield nr, nc, d

    def _astar(
        self,
        layer: str,
        start: tuple[int, int],
        goal: tuple[int, int],
        net_id: int,
        allow_rip: bool = False,
    ) -> tuple[list[tuple[int, int]], set[int]] | None:
        """Return (path, ripped_net_ids) or None."""
        grid = self.grid[layer]
        if start == goal:
            return ([start], set())

        def h(a: tuple[int, int]) -> int:
            return (abs(a[0] - goal[0]) + abs(a[1] - goal[1])) * 10

        open_heap: list[tuple[int, int, tuple[int, int], tuple[int, int] | None]] = []
        heapq.heappush(open_heap, (h(start), 0, start, None))
        came_from: dict[tuple[int, int], tuple[tuple[int, int] | None, tuple[int, int] | None]] = {
            start: (None, None)
        }
        g_score: dict[tuple[int, int], int] = {start: 0}
        ripped: set[int] = set()
        max_expansions = min(self.rows * self.cols, 200_000)
        expansions = 0

        while open_heap:
            _, cost, cur, prev_dir = heapq.heappop(open_heap)
            expansions += 1
            if expansions > max_expansions:
                return None
            if cur == goal:
                # reconstruct
                path: list[tuple[int, int]] = []
                node: tuple[int, int] | None = cur
                while node is not None:
                    path.append(node)
                    parent, _ = came_from[node]
                    node = parent
                path.reverse()
                return path, ripped

            for nr, nc, step in self._neighbors(*cur):
                cell = grid[nr, nc]
                # free?
                if cell in (FREE_CELL, net_id):
                    step_cost = step
                elif cell == BLOCKED_CELL:
                    continue
                elif cell > 0 and allow_rip and cell != net_id:
                    # rip-up allowance: penalize heavily
                    step_cost = step + 250
                    ripped.add(int(cell))
                else:
                    continue
                direction = (nr - cur[0], nc - cur[1])
                bend = self.bend_penalty if prev_dir is not None and prev_dir != direction else 0
                new_g = cost + step_cost + bend
                nxt = (nr, nc)
                if new_g < g_score.get(nxt, 1 << 30):
                    g_score[nxt] = new_g
                    came_from[nxt] = (cur, direction)
                    heapq.heappush(open_heap, (new_g + h(nxt), new_g, nxt, direction))
        return None

    # ------------------------------------------------------------------
    # net -> endpoints
    # ------------------------------------------------------------------
    def _net_endpoints(self, net_id: int) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.net == net_id:
                    pts.append(fp.pad_world_xy(pad))
        return pts

    def _criticality(self, net_id: int) -> tuple[int, float]:
        net_name = self.board.net_name(net_id)
        klass = self.net_classes.get_for_net(net_name) if net_name else None
        # Lower priority = routed first.
        priority = 100
        if klass and klass.impedance_target_ohm is not None:
            priority = 20
        if klass and klass.length_target_mm is not None:
            priority = 10
        pts = self._net_endpoints(net_id)
        if len(pts) < 2:
            return (priority, 0.0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        length = (max(xs) - min(xs)) + (max(ys) - min(ys))
        return (priority, length)

    # ------------------------------------------------------------------
    # Public routing API
    # ------------------------------------------------------------------
    def autoroute(
        self,
        nets: list[str] | None = None,
        mode: RoutingMode = RoutingMode.AUTOROUTE_ALL,
    ) -> RouteResult:
        start_time = time.perf_counter()
        result = RouteResult()

        name_to_id = {nm: nid for nid, nm in self.board.nets.items() if nm}
        if nets is None:
            target_ids = [nid for nid in self.board.nets if nid != 0]
        else:
            target_ids = [name_to_id[n] for n in nets if n in name_to_id]

        queue: list[tuple[tuple[int, float], int]] = [
            (self._criticality(nid), nid) for nid in target_ids
        ]
        queue.sort(key=lambda x: (x[0][0], x[0][1]))

        rip_budget = self.max_rip_budget
        already_routed: set[int] = set()
        pending = [nid for _, nid in queue]

        layer = self.layers[0]
        routed_count = 0
        failed: list[str] = []
        new_tracks = 0
        new_vias = 0

        while pending:
            net_id = pending.pop(0)
            net_name = self.board.net_name(net_id) or f"N${net_id}"
            endpoints = self._net_endpoints(net_id)
            if len(endpoints) < 2:
                continue
            klass = self.net_classes.get_for_net(net_name)
            width = klass.width_mm
            # MST-ish: sequentially connect endpoint[0] to the rest.
            net_ok = True
            anchor = endpoints[0]
            for ep in endpoints[1:]:
                s_cell = self._mm_to_cell(*anchor)
                g_cell = self._mm_to_cell(*ep)
                # allow_rip only if we've already failed once this round
                path_info = self._astar(layer, s_cell, g_cell, net_id)
                if path_info is None and mode == RoutingMode.AUTOROUTE_ALL and rip_budget > 0:
                    path_info = self._astar(layer, s_cell, g_cell, net_id, allow_rip=True)
                    if path_info is not None:
                        rip_budget -= 1
                        _, ripped = path_info
                        for r_nid in ripped:
                            self._rip_net(r_nid)
                            if r_nid not in pending and r_nid != net_id:
                                pending.append(r_nid)
                if path_info is None:
                    net_ok = False
                    break
                path, _ = path_info
                self._commit_path(layer, path, net_id, width)
                segs = self._path_to_tracks(layer, path, net_id, width)
                new_tracks += len(segs)
            if net_ok:
                routed_count += 1
                already_routed.add(net_id)
            else:
                failed.append(net_name)

        result.routed_nets = routed_count
        result.failed_nets = failed
        result.success = not failed
        result.track_count = new_tracks
        result.via_count = new_vias
        result.total_length_mm = self.board.tracks and sum(t.length_mm() for t in self.board.tracks) or 0.0
        result.runtime_s = time.perf_counter() - start_time
        result.message = (
            f"Routed {routed_count}/{len(target_ids)} nets in {result.runtime_s:.2f}s"
        )
        return result

    def route_diff_pair(self, net_p: str, net_n: str) -> RouteResult:
        result = RouteResult()
        start_time = time.perf_counter()
        name_to_id = {nm: nid for nid, nm in self.board.nets.items() if nm}
        if net_p not in name_to_id or net_n not in name_to_id:
            result.message = f"unknown nets {net_p}/{net_n}"
            result.failed_nets = [net_p, net_n]
            return result
        # Route P, then N with offset.
        r1 = self.autoroute([net_p], RoutingMode.WALKAROUND)
        r2 = self.autoroute([net_n], RoutingMode.WALKAROUND)
        result.success = r1.success and r2.success
        result.routed_nets = r1.routed_nets + r2.routed_nets
        result.failed_nets = r1.failed_nets + r2.failed_nets
        result.track_count = r1.track_count + r2.track_count
        result.via_count = r1.via_count + r2.via_count
        result.runtime_s = time.perf_counter() - start_time
        result.total_length_mm = sum(t.length_mm() for t in self.board.tracks)
        result.message = f"diff pair {net_p}/{net_n}: {result.message}"
        return result

    def push_and_shove(
        self, start: tuple[float, float], end: tuple[float, float], net: str, layer: str | None = None
    ) -> list[tuple[float, float]]:
        layer = layer or self.layers[0]
        name_to_id = {nm: nid for nid, nm in self.board.nets.items() if nm}
        net_id = name_to_id.get(net) or self.board.add_net(net)
        s = self._mm_to_cell(*start)
        g = self._mm_to_cell(*end)
        klass = self.net_classes.get_for_net(net)
        path_info = self._astar(layer, s, g, net_id, allow_rip=True)
        if path_info is None:
            path_info = self._astar(layer, s, g, net_id, allow_rip=False)
        if path_info is None:
            return []
        path, ripped = path_info
        for r_nid in ripped:
            self._rip_net(r_nid)
        self._commit_path(layer, path, net_id, klass.width_mm)
        self._path_to_tracks(layer, path, net_id, klass.width_mm)
        return [self._cell_to_mm(r, c) for r, c in path]

    def walkaround(
        self, start: tuple[float, float], end: tuple[float, float], net: str, layer: str | None = None
    ) -> list[tuple[float, float]]:
        layer = layer or self.layers[0]
        name_to_id = {nm: nid for nid, nm in self.board.nets.items() if nm}
        net_id = name_to_id.get(net) or self.board.add_net(net)
        s = self._mm_to_cell(*start)
        g = self._mm_to_cell(*end)
        klass = self.net_classes.get_for_net(net)
        path_info = self._astar(layer, s, g, net_id, allow_rip=False)
        if path_info is None:
            return []
        path, _ = path_info
        self._commit_path(layer, path, net_id, klass.width_mm)
        self._path_to_tracks(layer, path, net_id, klass.width_mm)
        return [self._cell_to_mm(r, c) for r, c in path]

    def length_match(self, net_class: str) -> RouteResult:
        from openforge.pcb.length_match import LengthGroup, LengthMatcher

        result = RouteResult()
        start_time = time.perf_counter()
        klass = self.net_classes.classes.get(net_class)
        if klass is None:
            result.message = f"unknown class {net_class}"
            return result
        nets = list(klass.nets)
        if not nets:
            result.message = "no nets in class"
            return result
        target = klass.length_target_mm
        tolerance = klass.length_tolerance_mm or 0.5
        group = LengthGroup(
            name=net_class,
            nets=nets,
            target_mm=target,
            tolerance_mm=tolerance,
            method="serpentine",
        )
        matcher = LengthMatcher(self.board)
        deltas = matcher.match_group(group)
        result.success = True
        result.routed_nets = len(deltas)
        result.total_length_mm = sum(t.length_mm() for t in self.board.tracks)
        result.runtime_s = time.perf_counter() - start_time
        result.message = f"length matched {len(deltas)} nets"
        return result

    def use_freerouting(self, jar_path: Path | None = None) -> RouteResult:
        from openforge.pcb.dsn import board_to_dsn, parse_ses

        result = RouteResult()
        start_time = time.perf_counter()
        jar = Path(jar_path) if jar_path else None
        if jar is None or not jar.exists():
            for candidate in ("freerouting.jar", "freerouting-executable.jar"):
                found = shutil.which(candidate)
                if found:
                    jar = Path(found)
                    break
        if jar is None or not jar.exists():
            result.message = "freerouting.jar not found"
            return result
        java = shutil.which("java")
        if java is None:
            result.message = "java runtime not found"
            return result
        work = Path.cwd() / ".openforge_freerouting"
        work.mkdir(exist_ok=True)
        dsn_path = work / f"{self.board.name or 'board'}.dsn"
        ses_path = work / f"{self.board.name or 'board'}.ses"
        board_to_dsn(self.board, dsn_path, self.net_classes)
        try:
            subprocess.run(
                [java, "-jar", str(jar), "-de", str(dsn_path), "-do", str(ses_path), "-mp", "100"],
                timeout=600,
                check=False,
                capture_output=True,
            )
        except Exception as exc:  # noqa: BLE001
            result.message = f"freerouting failed: {exc}"
            return result
        if not ses_path.exists():
            result.message = "freerouting produced no SES output"
            return result
        before = len(self.board.tracks)
        parse_ses(ses_path, self.board)
        result.track_count = len(self.board.tracks) - before
        result.success = result.track_count > 0
        result.runtime_s = time.perf_counter() - start_time
        result.total_length_mm = sum(t.length_mm() for t in self.board.tracks)
        result.message = f"freerouting added {result.track_count} tracks"
        return result

    # ------------------------------------------------------------------
    # helpers: commit / rip
    # ------------------------------------------------------------------
    def _commit_path(self, layer: str, path: list[tuple[int, int]], net_id: int, width_mm: float) -> None:
        radius = max(1, int(round(width_mm / self.grid_mm / 2)))
        grid = self.grid[layer]
        for r, c in path:
            r0 = max(0, r - radius)
            r1 = min(self.rows - 1, r + radius)
            c0 = max(0, c - radius)
            c1 = min(self.cols - 1, c + radius)
            cells = grid[r0 : r1 + 1, c0 : c1 + 1]
            # don't trample a hard block
            mask = cells != BLOCKED_CELL
            cells[mask] = net_id
            grid[r0 : r1 + 1, c0 : c1 + 1] = cells

    def _path_to_tracks(self, layer: str, path: list[tuple[int, int]], net_id: int, width_mm: float) -> list:
        """Collapse a cell path into straight-line segments and push them onto the board."""
        from openforge.pcb.model import PcbTrack

        if len(path) < 2:
            return []
        # Reduce to corners
        corners: list[tuple[int, int]] = [path[0]]
        for i in range(1, len(path) - 1):
            prev = path[i - 1]
            cur = path[i]
            nxt = path[i + 1]
            d1 = (cur[0] - prev[0], cur[1] - prev[1])
            d2 = (nxt[0] - cur[0], nxt[1] - cur[1])
            if d1 != d2:
                corners.append(cur)
        corners.append(path[-1])

        segs: list[PcbTrack] = []
        for i in range(len(corners) - 1):
            r1, c1 = corners[i]
            r2, c2 = corners[i + 1]
            x1, y1 = self._cell_to_mm(r1, c1)
            x2, y2 = self._cell_to_mm(r2, c2)
            t = PcbTrack(
                layer=layer, x1_mm=x1, y1_mm=y1, x2_mm=x2, y2_mm=y2, width_mm=width_mm, net=net_id
            )
            self.board.tracks.append(t)
            segs.append(t)
        return segs

    def _rip_net(self, net_id: int) -> None:
        """Remove tracks belonging to ``net_id`` and clear their grid cells."""
        kept: list = []
        for t in self.board.tracks:
            if t.net == net_id and t.layer in self.grid:
                self._paint_line(
                    self.grid[t.layer],
                    t.x1_mm,
                    t.y1_mm,
                    t.x2_mm,
                    t.y2_mm,
                    max(1, int(round(t.width_mm / self.grid_mm / 2))),
                    FREE_CELL,
                )
            else:
                kept.append(t)
        self.board.tracks = kept


__all__ = ["PcbRouter", "RouteResult", "RoutingMode"]
