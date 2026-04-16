"""RS-274X Gerber + Excellon drill exporter for OpenForge PCB.

Targets PcbBoard (openforge.pcb.model). Produces valid modern Gerber
(X2 attributes omitted for portability) with %FSLAX46Y46*% and %MOMM*%,
aperture definitions, linear draws, and polygon fill regions (G36/G37).
"""

from __future__ import annotations

import csv
import math
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from openforge.pcb.model import (
        PcbBoard,
        PcbFootprint,
        PcbPad,
    )


def _fmt(v: float) -> str:
    """Format mm as 4.6 fixed point without decimal point."""
    return f"{int(round(v * 1_000_000)):d}"


def _xy(x: float, y: float) -> str:
    return f"X{_fmt(x)}Y{_fmt(y)}"


def _layer_ext(layer: str) -> str:
    mapping = {
        "F.Cu": "GTL",
        "B.Cu": "GBL",
        "F.Mask": "GTS",
        "B.Mask": "GBS",
        "F.SilkS": "GTO",
        "B.SilkS": "GBO",
        "F.Paste": "GTP",
        "B.Paste": "GBP",
        "Edge.Cuts": "GM1",
    }
    if layer in mapping:
        return mapping[layer]
    if layer.startswith("In") and layer.endswith(".Cu"):
        try:
            idx = int(layer[2:].split(".")[0])
            return f"G{idx}"
        except ValueError:
            pass
    return "gbr"


class GerberExporter:
    """Export a PcbBoard to RS-274X Gerber + Excellon drill."""

    def __init__(self, board: PcbBoard) -> None:
        self.board = board

    # ------------------------------------------------------------------
    def _pad_world(self, fp: PcbFootprint, pad: PcbPad) -> tuple[float, float, float]:
        """Return (x, y, rotation_deg) of pad in world coordinates."""
        x, y = fp.pad_world_xy(pad)
        return (x, y, fp.rotation_deg)

    def _iter_footprint_items(self, layer: str) -> Iterable[tuple[PcbFootprint, PcbPad]]:
        for fp in self.board.footprints:
            for pad in fp.pads:
                if layer in pad.layers:
                    yield fp, pad

    # ------------------------------------------------------------------
    def export_layer(self, layer_name: str, output_path: Path) -> Path:
        """Write a single Gerber layer file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build aperture table
        apertures: dict[tuple, int] = {}
        next_d = 10

        def get_ap(kind: str, *params: float) -> int:
            nonlocal next_d
            key = (kind, *(round(p, 6) for p in params))
            if key in apertures:
                return apertures[key]
            apertures[key] = next_d
            next_d += 1
            return apertures[key]

        body: list[str] = []

        is_copper = layer_name.endswith(".Cu") or layer_name.startswith("In")
        is_edge = layer_name == "Edge.Cuts"
        is_mask = layer_name.endswith(".Mask")
        layer_name.endswith(".Paste")
        is_silk = layer_name.endswith(".SilkS") or layer_name == "Edge.Cuts"

        # --- Pads (flashes)
        for fp, pad in self._iter_footprint_items(layer_name):
            x, y = fp.pad_world_xy(pad)
            sx, sy = pad.size_x_mm, pad.size_y_mm
            # mask expansion +0.05mm; paste keeps nominal
            if is_mask:
                sx += 0.1
                sy += 0.1
            if pad.shape == "round":
                d = get_ap("C", sx)
            elif pad.shape == "rect":
                d = get_ap("R", sx, sy)
            elif pad.shape == "oval":
                d = get_ap("O", sx, sy)
            else:  # roundrect
                d = get_ap("R", sx, sy)
            body.append(f"D{d}*")
            body.append(f"{_xy(x, -y)}D03*")

        # --- Vias (on copper layers + mask if tented=no; here covered)
        if is_copper:
            for via in self.board.vias:
                d = get_ap("C", via.diameter_mm)
                body.append(f"D{d}*")
                body.append(f"{_xy(via.x_mm, -via.y_mm)}D03*")

        # --- Tracks (linear draws)
        if is_copper:
            for tr in self.board.tracks:
                if tr.layer != layer_name:
                    continue
                d = get_ap("C", tr.width_mm)
                body.append(f"D{d}*")
                body.append(f"{_xy(tr.x1_mm, -tr.y1_mm)}D02*")
                body.append(f"{_xy(tr.x2_mm, -tr.y2_mm)}D01*")

        # --- Zones (polygon fills)
        if is_copper:
            for zone in self.board.zones:
                if zone.layer != layer_name:
                    continue
                polys = zone.fill_polygons or ([zone.polygon] if zone.polygon else [])
                for poly in polys:
                    if len(poly) < 3:
                        continue
                    body.append("G36*")
                    first = poly[0]
                    body.append(f"{_xy(first[0], -first[1])}D02*")
                    for px, py in poly[1:]:
                        body.append(f"{_xy(px, -py)}D01*")
                    body.append(f"{_xy(first[0], -first[1])}D01*")
                    body.append("G37*")

        # --- Silkscreen segments
        if is_silk and not is_edge:
            for fp in self.board.footprints:
                for x1, y1, x2, y2 in fp.silkscreen:
                    # rotate around footprint origin
                    rot = math.radians(fp.rotation_deg)
                    cs, sn = math.cos(rot), math.sin(rot)
                    wx1 = fp.x_mm + x1 * cs - y1 * sn
                    wy1 = fp.y_mm + x1 * sn + y1 * cs
                    wx2 = fp.x_mm + x2 * cs - y2 * sn
                    wy2 = fp.y_mm + x2 * sn + y2 * cs
                    d = get_ap("C", 0.15)
                    body.append(f"D{d}*")
                    body.append(f"{_xy(wx1, -wy1)}D02*")
                    body.append(f"{_xy(wx2, -wy2)}D01*")

        # --- Edge cuts (board outline)
        if is_edge:
            outline = self.board.outline or []
            if len(outline) >= 2:
                d = get_ap("C", 0.10)
                body.append(f"D{d}*")
                first = outline[0]
                body.append(f"{_xy(first[0], -first[1])}D02*")
                for px, py in outline[1:]:
                    body.append(f"{_xy(px, -py)}D01*")
                body.append(f"{_xy(first[0], -first[1])}D01*")

        # --- Assemble
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        header: list[str] = [
            f"G04 OpenForge RS-274X export layer={layer_name} ts={ts}*",
            "%FSLAX46Y46*%",
            "%MOMM*%",
            "%LPD*%",
            "G01*",
        ]
        # Aperture defs
        aps: list[str] = []
        for (kind, *params), d in apertures.items():
            if kind == "C":
                aps.append(f"%ADD{d}C,{params[0]:.6f}*%")
            elif kind == "R":
                aps.append(f"%ADD{d}R,{params[0]:.6f}X{params[1]:.6f}*%")
            elif kind == "O":
                aps.append(f"%ADD{d}O,{params[0]:.6f}X{params[1]:.6f}*%")

        text = "\n".join(header + aps + body + ["M02*", ""])
        output_path.write_text(text)
        return output_path

    # ------------------------------------------------------------------
    def export_all(self, output_dir: Path) -> dict[str, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        layers_to_export: list[str] = []
        for l in self.board.stackup.layers:
            if l.kind in ("signal", "plane", "mask", "silk", "paste", "edge"):
                layers_to_export.append(l.name)
        if not layers_to_export:
            layers_to_export = [
                "F.Cu",
                "B.Cu",
                "F.Mask",
                "B.Mask",
                "F.SilkS",
                "B.SilkS",
                "F.Paste",
                "B.Paste",
                "Edge.Cuts",
            ]
        results: dict[str, Path] = {}
        for layer in layers_to_export:
            ext = _layer_ext(layer)
            path = output_dir / f"{self.board.name}-{layer}.{ext}"
            results[layer] = self.export_layer(layer, path)
        return results

    # ------------------------------------------------------------------
    def export_drill(self, output_path: Path, format: str = "excellon") -> Path:
        """Write Excellon NC drill file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Collect drills: (diameter_mm, x, y, is_plated)
        drills: list[tuple[float, float, float, bool]] = []
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.drill_mm > 0:
                    x, y = fp.pad_world_xy(pad)
                    drills.append((pad.drill_mm, x, y, True))
        for via in self.board.vias:
            drills.append((via.drill_mm, via.x_mm, via.y_mm, True))

        # Group by diameter
        tools: dict[float, int] = {}
        for d, *_ in drills:
            if d not in tools:
                tools[d] = len(tools) + 1

        lines: list[str] = [
            "M48",
            "; OpenForge Excellon drill export",
            f"; {datetime.now(UTC).isoformat()}",
            "FMAT,2",
            "METRIC,TZ",
        ]
        for dia, tnum in sorted(tools.items(), key=lambda x: x[1]):
            lines.append(f"T{tnum:02d}C{dia:.3f}")
        lines.append("%")
        lines.append("G90")
        lines.append("G05")
        lines.append("M71")  # metric
        for tnum in sorted(set(tools.values())):
            lines.append(f"T{tnum:02d}")
            dia = next(d for d, t in tools.items() if t == tnum)
            for d, x, y, _plated in drills:
                if d == dia:
                    lines.append(f"X{x:.3f}Y{-y:.3f}")
        lines.append("T00")
        lines.append("M30")
        lines.append("")
        output_path.write_text("\n".join(lines))
        return output_path

    # ------------------------------------------------------------------
    def export_pick_and_place(self, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Ref", "Value", "Footprint", "X_mm", "Y_mm", "Rot_deg", "Side"])
            for fp in self.board.footprints:
                w.writerow(
                    [
                        fp.ref,
                        fp.value,
                        fp.name,
                        f"{fp.x_mm:.4f}",
                        f"{fp.y_mm:.4f}",
                        f"{fp.rotation_deg:.2f}",
                        "top" if fp.layer == "top" else "bottom",
                    ]
                )
        return output_path

    # ------------------------------------------------------------------
    def export_bom(self, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        groups: dict[tuple[str, str], list[str]] = {}
        for fp in self.board.footprints:
            key = (fp.value or fp.name, fp.name)
            groups.setdefault(key, []).append(fp.ref)
        with open(output_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Value", "Footprint", "Qty", "Refs"])
            for (value, footprint), refs in sorted(groups.items()):
                w.writerow([value, footprint, len(refs), " ".join(sorted(refs))])
        return output_path

    # ------------------------------------------------------------------
    def export_zip(self, output_dir: Path) -> Path:
        """Produce a fab-ready ZIP for JLCPCB."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        work = output_dir / f"{self.board.name}_fab"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)

        self.export_all(work)
        self.export_drill(work / f"{self.board.name}.drl")
        self.export_pick_and_place(work / f"{self.board.name}-pnp.csv")
        self.export_bom(work / f"{self.board.name}-bom.csv")

        zip_path = output_dir / f"{self.board.name}_jlcpcb.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in work.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(work))
        return zip_path


# Backward-compat shim so the old symbol name still imports.
class OdbPlusPlusExporter:  # pragma: no cover - thin re-export
    def __init__(self, board: PcbBoard) -> None:
        from openforge.pcb.odbpp import OdbppExporter

        self._inner = OdbppExporter(board)

    def export(self, output_dir: Path) -> Path:
        return self._inner.export(output_dir)
