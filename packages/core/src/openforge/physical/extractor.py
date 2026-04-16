"""Pattern-based parasitic extractor.

Walks a parsed DEF design's routed net segments and produces per-net R/C
results using sky130-ballpark layer properties. Emits a DSPEF file that
round-trips through ``openforge.format.spef_parser``.

This is **not** foundry sign-off accurate — it's a pattern extractor that
gets within the ballpark of OpenROAD + OpenRCX so that downstream STA /
PBA / crosstalk analysis can run without needing a full RC engine.

Layer property numbers (sheet resistance Ohm/sq, area cap F/um^2,
fringe cap F/um, min width um) are derived from public sky130 ITF /
PEX documentation. They're representative, not golden.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from openforge.format.def_parser import (
    DefDesign,
    DefNet,
    DefRouteSegment,
    parse_def,
)
from openforge.format.spef_parser import (
    SpefCap,
    SpefFile,
    SpefNet,
    SpefRes,
)


# ---------------------------------------------------------------------------
# Sky130 layer properties (ballpark, derived from public PEX docs)
# ---------------------------------------------------------------------------
# sheet_res : Ohm / square
# cap_per_area : F / um^2   (ground plane)
# fringe : F / um           (edge fringe per unit perimeter)
# cap_lat : F / um^2 * um   (effective lateral-coupling coefficient per unit
#                            parallel-run length, divided by spacing)
# width_min : um
# pitch : um (typical routing pitch)

SKY130_LAYER_PROPS: dict[str, dict[str, float]] = {
    "li1": {
        "sheet_res": 12.8,
        "cap_per_area": 8.70e-5 * 1e-12,  # F/um^2  (~0.087 fF/um^2)
        "fringe": 3.80e-4 * 1e-12,        # F/um    (~0.38 fF/um)
        "cap_lat": 4.00e-4 * 1e-12,
        "width_min": 0.17,
        "pitch": 0.34,
    },
    "met1": {
        "sheet_res": 0.125,
        "cap_per_area": 6.40e-5 * 1e-12,
        "fringe": 3.10e-5 * 1e-12,
        "cap_lat": 6.50e-4 * 1e-12,
        "width_min": 0.14,
        "pitch": 0.34,
    },
    "met2": {
        "sheet_res": 0.125,
        "cap_per_area": 3.50e-5 * 1e-12,
        "fringe": 3.80e-5 * 1e-12,
        "cap_lat": 5.20e-4 * 1e-12,
        "width_min": 0.14,
        "pitch": 0.46,
    },
    "met3": {
        "sheet_res": 0.047,
        "cap_per_area": 2.20e-5 * 1e-12,
        "fringe": 4.00e-5 * 1e-12,
        "cap_lat": 4.80e-4 * 1e-12,
        "width_min": 0.30,
        "pitch": 0.68,
    },
    "met4": {
        "sheet_res": 0.047,
        "cap_per_area": 1.70e-5 * 1e-12,
        "fringe": 4.40e-5 * 1e-12,
        "cap_lat": 4.20e-4 * 1e-12,
        "width_min": 0.30,
        "pitch": 0.92,
    },
    "met5": {
        "sheet_res": 0.029,
        "cap_per_area": 1.20e-5 * 1e-12,
        "fringe": 4.80e-5 * 1e-12,
        "cap_lat": 3.80e-4 * 1e-12,
        "width_min": 1.60,
        "pitch": 3.40,
    },
}

# Via resistance table (Ohm, approximate)
SKY130_VIA_RES: dict[str, float] = {
    "mcon": 9.3,
    "via":  4.5,
    "via2": 3.4,
    "via3": 3.0,
    "via4": 2.0,
    "default": 5.0,
}

# Default coupling search radius in um
DEFAULT_COUPLING_DISTANCE_UM = 1.5


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Extracted parasitics for a single net (canonical units)."""

    model_config = ConfigDict(extra="ignore")

    net: str
    total_cap_ff: float = 0.0  # femtofarads
    coupling_caps: dict[str, float] = Field(default_factory=dict)  # neighbour -> fF
    total_res_ohm: float = 0.0
    segments: list[dict[str, Any]] = Field(default_factory=list)
    layers_used: list[str] = Field(default_factory=list)
    length_um: float = 0.0

    @property
    def total_cap_pf(self) -> float:
        return self.total_cap_ff * 1e-3

    @property
    def ground_cap_ff(self) -> float:
        return self.total_cap_ff - sum(self.coupling_caps.values())


# ---------------------------------------------------------------------------
# Segment geometry helper
# ---------------------------------------------------------------------------


def _segment_boxes(
    seg: DefRouteSegment, units_per_um: float, default_width_um: float
) -> list[tuple[str, float, float, float, float]]:
    """Return per-wire-piece rectangles (layer, x1, y1, x2, y2) in microns.

    Each consecutive pair of points in a segment defines a Manhattan wire
    piece. We convert to an axis-aligned bbox using a width of
    ``seg.width`` (or layer default).
    """
    if len(seg.points) < 2:
        return []
    width_um = (seg.width / units_per_um) if seg.width else default_width_um
    half = width_um / 2.0
    boxes: list[tuple[str, float, float, float, float]] = []
    for i in range(len(seg.points) - 1):
        x1, y1, _ = seg.points[i]
        x2, y2, _ = seg.points[i + 1]
        ux1 = x1 / units_per_um
        uy1 = y1 / units_per_um
        ux2 = x2 / units_per_um
        uy2 = y2 / units_per_um
        if ux1 == ux2 and uy1 == uy2:
            continue
        if ux1 == ux2:  # vertical
            bx1 = ux1 - half
            bx2 = ux1 + half
            by1 = min(uy1, uy2)
            by2 = max(uy1, uy2)
        else:            # horizontal (or diagonal - treat as bbox)
            by1 = uy1 - half
            by2 = uy1 + half
            bx1 = min(ux1, ux2)
            bx2 = max(ux1, ux2)
        boxes.append((seg.layer, bx1, by1, bx2, by2))
    return boxes


def _box_overlap_length(
    a: tuple[str, float, float, float, float],
    b: tuple[str, float, float, float, float],
    max_gap_um: float,
) -> tuple[float, float]:
    """Return (parallel_run_length_um, gap_um) for two same-layer boxes.

    Returns (0, inf) when the boxes are not parallel neighbours within
    ``max_gap_um``.
    """
    la, ax1, ay1, ax2, ay2 = a
    lb, bx1, by1, bx2, by2 = b
    if la != lb:
        return 0.0, float("inf")

    a_horiz = (ax2 - ax1) >= (ay2 - ay1)
    b_horiz = (bx2 - bx1) >= (by2 - by1)
    if a_horiz != b_horiz:
        return 0.0, float("inf")

    if a_horiz:
        # parallel run in x, gap in y
        y_gap = max(by1 - ay2, ay1 - by2, 0.0)
        if y_gap > max_gap_um or (ay1 > by2 or by1 > ay2):
            # If boxes overlap in y (y_gap==0 and overlap) still count
            if not (ay2 < by1 or by2 < ay1):
                # overlapping in y - not a coupling neighbour, same track
                y_gap = 0.0
            else:
                return 0.0, float("inf")
        overlap = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        # effective gap from edge to edge
        gap = max(by1 - ay2, ay1 - by2)
        if gap <= 0:
            return 0.0, float("inf")
        return overlap, gap
    else:
        x_gap = max(bx1 - ax2, ax1 - bx2, 0.0)
        if x_gap > max_gap_um:
            return 0.0, float("inf")
        overlap = max(0.0, min(ay2, by2) - max(ay1, by1))
        gap = max(bx1 - ax2, ax1 - bx2)
        if gap <= 0:
            return 0.0, float("inf")
        return overlap, gap


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class ParasiticExtractor:
    """Pattern-based RC extractor over a parsed DEF design."""

    def __init__(
        self,
        def_path: str | Path,
        lef_path: str | Path | None = None,
        tech_layer_props: dict[str, dict[str, float]] | None = None,
        coupling_distance_um: float = DEFAULT_COUPLING_DISTANCE_UM,
    ) -> None:
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path) if lef_path else None
        self.layer_props: dict[str, dict[str, float]] = dict(
            tech_layer_props or SKY130_LAYER_PROPS
        )
        self.coupling_distance_um = coupling_distance_um
        self.design: DefDesign = parse_def(self.def_path)
        self.units_per_um: float = float(self.design.units_per_micron or 1000)

        # Precompute boxes per net (for coupling search)
        self._net_boxes: dict[str, list[tuple[str, float, float, float, float]]] = {}
        for net_name, net in self.design.nets.items():
            if net.is_power:
                continue
            boxes: list[tuple[str, float, float, float, float]] = []
            for seg in net.routes:
                props = self._props_for(seg.layer)
                default_w = props.get("width_min", 0.14) if props else 0.14
                boxes.extend(_segment_boxes(seg, self.units_per_um, default_w))
            self._net_boxes[net_name] = boxes

    # ------------------------------------------------------------------ util

    def _props_for(self, layer: str) -> dict[str, float] | None:
        if not layer:
            return None
        return self.layer_props.get(layer) or self.layer_props.get(layer.lower())

    # ------------------------------------------------------------------ API

    def extract_net(self, net_name: str) -> ExtractionResult:
        """Compute R/C parasitics for a single net."""
        net = self.design.nets.get(net_name)
        if net is None:
            return ExtractionResult(net=net_name)
        return self._extract_one(net)

    def extract_all(self) -> dict[str, ExtractionResult]:
        """Extract parasitics for every signal/clock net in the design."""
        results: dict[str, ExtractionResult] = {}
        for name, net in self.design.nets.items():
            if net.is_power:
                continue
            results[name] = self._extract_one(net)
        return results

    # ------------------------------------------------------------------ core

    def _extract_one(self, net: DefNet) -> ExtractionResult:
        total_c_ff = 0.0
        total_r = 0.0
        segments_out: list[dict[str, Any]] = []
        layers_used: set[str] = set()
        length_um_total = 0.0
        coupling_ff: dict[str, float] = {}

        my_boxes = self._net_boxes.get(net.name, [])

        for seg in net.routes:
            props = self._props_for(seg.layer)
            if props is None:
                # still consider via resistance if this is a via-only segment
                if seg.via:
                    via_r = self._via_resistance(seg.via)
                    total_r += via_r
                    segments_out.append(
                        {
                            "layer": seg.layer or "via",
                            "kind": "via",
                            "via": seg.via,
                            "r_ohm": via_r,
                            "c_ff": 0.0,
                            "length_um": 0.0,
                        }
                    )
                continue

            layers_used.add(seg.layer)
            width_um = (seg.width / self.units_per_um) if seg.width else props["width_min"]
            length_db = seg.length_db
            length_um = length_db / self.units_per_um
            length_um_total += length_um

            # R = rho_sheet * L / W  (Ohms)
            r_ohm = 0.0
            if width_um > 0 and length_um > 0:
                r_ohm = props["sheet_res"] * (length_um / width_um)

            # C_ground = area * cap_per_area + perimeter * fringe
            area = length_um * width_um
            perimeter = 2.0 * (length_um + width_um)
            c_ground_f = (
                area * props["cap_per_area"]
                + perimeter * props["fringe"]
            )
            c_ground_ff = c_ground_f * 1e15

            # Via resistance at segment end
            via_r = 0.0
            if seg.via:
                via_r = self._via_resistance(seg.via)
                r_ohm += via_r

            total_r += r_ohm
            total_c_ff += c_ground_ff

            segments_out.append(
                {
                    "layer": seg.layer,
                    "kind": "wire",
                    "length_um": length_um,
                    "width_um": width_um,
                    "r_ohm": r_ohm,
                    "c_ff": c_ground_ff,
                    "via": seg.via,
                    "via_r_ohm": via_r,
                }
            )

        # Coupling caps - search neighbouring nets for parallel boxes
        if my_boxes:
            coupling_ff = self._compute_coupling(net.name, my_boxes)
            total_c_ff += sum(coupling_ff.values())

        return ExtractionResult(
            net=net.name,
            total_cap_ff=total_c_ff,
            coupling_caps=coupling_ff,
            total_res_ohm=total_r,
            segments=segments_out,
            layers_used=sorted(layers_used),
            length_um=length_um_total,
        )

    def _via_resistance(self, via_name: str) -> float:
        if not via_name:
            return SKY130_VIA_RES["default"]
        key = via_name.lower()
        for k, v in SKY130_VIA_RES.items():
            if k in key:
                return v
        return SKY130_VIA_RES["default"]

    def _compute_coupling(
        self,
        my_name: str,
        my_boxes: list[tuple[str, float, float, float, float]],
    ) -> dict[str, float]:
        """Scan nearby nets, sum parallel coupling cap per neighbour (fF)."""
        out: dict[str, float] = {}
        max_gap = self.coupling_distance_um

        # bbox of this net for broad-phase culling
        if not my_boxes:
            return out
        mb_x1 = min(b[1] for b in my_boxes) - max_gap
        mb_y1 = min(b[2] for b in my_boxes) - max_gap
        mb_x2 = max(b[3] for b in my_boxes) + max_gap
        mb_y2 = max(b[4] for b in my_boxes) + max_gap

        for other_name, other_boxes in self._net_boxes.items():
            if other_name == my_name or not other_boxes:
                continue
            # broad phase
            ox1 = min(b[1] for b in other_boxes)
            oy1 = min(b[2] for b in other_boxes)
            ox2 = max(b[3] for b in other_boxes)
            oy2 = max(b[4] for b in other_boxes)
            if ox2 < mb_x1 or ox1 > mb_x2 or oy2 < mb_y1 or oy1 > mb_y2:
                continue

            coup_ff = 0.0
            for a in my_boxes:
                la = a[0]
                props = self._props_for(la)
                if props is None:
                    continue
                cap_lat = props.get("cap_lat", 0.0)
                for b in other_boxes:
                    if b[0] != la:
                        continue
                    overlap, gap = _box_overlap_length(a, b, max_gap)
                    if overlap <= 0 or gap == float("inf"):
                        continue
                    # cap = overlap_length * cap_lat / gap     (F)
                    # cap_lat already has units F/um per unit gap
                    cap_f = overlap * cap_lat / max(gap, 0.1)
                    coup_ff += cap_f * 1e15
            if coup_ff > 0:
                out[other_name] = out.get(other_name, 0.0) + coup_ff
        return out

    # ------------------------------------------------------------------ I/O

    def write_spef(
        self,
        output_path: str | Path,
        results: dict[str, ExtractionResult] | None = None,
    ) -> Path:
        """Emit a DSPEF file that the project's SPEF parser can read back."""
        if results is None:
            results = self.extract_all()
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        design = self.design.name or "design"
        lines.append('*SPEF "IEEE 1481-1998"')
        lines.append(f'*DESIGN "{design}"')
        lines.append('*DATE "2026-04-08"')
        lines.append('*VENDOR "OpenForge"')
        lines.append('*PROGRAM "openforge.physical.extractor"')
        lines.append('*VERSION "1.0"')
        lines.append('*DESIGN_FLOW "PIN_CAP NONE"')
        lines.append('*DIVIDER /')
        lines.append('*DELIMITER :')
        lines.append('*BUS_DELIMITER [ ]')
        lines.append('*T_UNIT 1 PS')
        lines.append('*C_UNIT 1 FF')
        lines.append('*R_UNIT 1 OHM')
        lines.append('*L_UNIT 1 PH')
        lines.append('')

        cap_id = 1
        res_id = 1
        for name, res in results.items():
            lines.append(f'*D_NET {name} {res.total_cap_ff:.6f}')
            lines.append('*CONN')
            # Emit *I for each component pin on the net (best-effort)
            net = self.design.nets.get(name)
            if net is not None:
                for inst, pin in net.connections:
                    if inst == "PIN":
                        lines.append(f'*P {pin} I')
                    else:
                        lines.append(f'*I {inst}:{pin} B')
            lines.append('*CAP')
            # Ground caps lumped at a synthetic node
            ground_ff = res.ground_cap_ff
            if ground_ff > 0:
                lines.append(f'{cap_id} {name}:1 {ground_ff:.6f}')
                cap_id += 1
            # Coupling caps
            for nb, cff in res.coupling_caps.items():
                lines.append(f'{cap_id} {name}:1 {nb}:1 {cff:.6f}')
                cap_id += 1
            lines.append('*RES')
            if res.total_res_ohm > 0:
                lines.append(f'{res_id} {name}:1 {name}:2 {res.total_res_ohm:.6f}')
                res_id += 1
            lines.append('*END')
            lines.append('')

        out_path.write_text("\n".join(lines), encoding="utf-8")
        return out_path

    # ------------------------------------------------------------------ reduce

    def reduce_spef(
        self,
        input_path: str | Path,
        output_path: str | Path,
        ratio: float = 0.1,
    ) -> Path:
        """SPEF reduction: drop small Cs and short Rs below a threshold.

        ``ratio`` is relative to the maximum C and R across the file.
        """
        spef = SpefFile.parse(input_path)
        # Determine thresholds
        max_c = 0.0
        max_r = 0.0
        for n in spef.nets:
            for c in n.caps:
                if c.cap_pf > max_c:
                    max_c = c.cap_pf
            for r in n.resistances:
                if r.res_ohm > max_r:
                    max_r = r.res_ohm
        c_thr = max_c * ratio
        r_thr = max_r * ratio

        reduced = SpefFile(
            design_name=spef.design_name,
            units=dict(spef.units),
            divider=spef.divider,
            delimiter=spef.delimiter,
        )
        for n in spef.nets:
            new_net = SpefNet(name=n.name, total_cap_pf=0.0)
            new_net.ports = list(n.ports)
            # Merge small caps into a lumped cap on the net
            lumped = 0.0
            for c in n.caps:
                if c.cap_pf < c_thr and c.coupled_to is None:
                    lumped += c.cap_pf
                else:
                    new_net.caps.append(c)
            if lumped > 0:
                new_net.caps.append(
                    SpefCap(node=f"{n.name}:RED", cap_pf=lumped)
                )
            # Drop short R (they become shorts). Represent as a single lumped R.
            lumped_r = 0.0
            kept_r: list[SpefRes] = []
            for r in n.resistances:
                if r.res_ohm < r_thr:
                    lumped_r += r.res_ohm
                else:
                    kept_r.append(r)
            new_net.resistances = kept_r
            if lumped_r > 0:
                new_net.resistances.append(
                    SpefRes(
                        node1=f"{n.name}:RED",
                        node2=f"{n.name}:RED2",
                        res_ohm=lumped_r,
                    )
                )
            new_net.total_cap_pf = sum(c.cap_pf for c in new_net.caps)
            reduced.nets.append(new_net)

        # Write a minimal DSPEF back out
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append('*SPEF "IEEE 1481-1998"')
        lines.append(f'*DESIGN "{reduced.design_name}"')
        lines.append('*DATE "2026-04-08"')
        lines.append('*VENDOR "OpenForge"')
        lines.append('*PROGRAM "openforge.physical.extractor.reduce"')
        lines.append('*VERSION "1.0"')
        lines.append('*DESIGN_FLOW "PIN_CAP NONE"')
        lines.append(f'*DIVIDER {reduced.divider}')
        lines.append(f'*DELIMITER {reduced.delimiter}')
        lines.append('*BUS_DELIMITER [ ]')
        lines.append('*T_UNIT 1 PS')
        lines.append('*C_UNIT 1 PF')
        lines.append('*R_UNIT 1 OHM')
        lines.append('*L_UNIT 1 PH')
        lines.append('')
        cid = 1
        rid = 1
        for n in reduced.nets:
            lines.append(f'*D_NET {n.name} {n.total_cap_pf:.6f}')
            lines.append('*CONN')
            for p in n.ports:
                lines.append(f'*P {p.name} {p.direction or "I"}')
            lines.append('*CAP')
            for c in n.caps:
                if c.coupled_to:
                    lines.append(f'{cid} {c.node} {c.coupled_to} {c.cap_pf:.6f}')
                else:
                    lines.append(f'{cid} {c.node} {c.cap_pf:.6f}')
                cid += 1
            lines.append('*RES')
            for r in n.resistances:
                lines.append(f'{rid} {r.node1} {r.node2} {r.res_ohm:.6f}')
                rid += 1
            lines.append('*END')
            lines.append('')
        out.write_text("\n".join(lines), encoding="utf-8")
        return out


__all__ = [
    "ExtractionResult",
    "ParasiticExtractor",
    "SKY130_LAYER_PROPS",
    "SKY130_VIA_RES",
]
