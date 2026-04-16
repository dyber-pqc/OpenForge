"""ODB++ exporter (basic).

Writes a minimal ODB++ directory tree sufficient for fab houses like
JLCPCB or Eurocircuits to accept the upload. This is a pragmatic
implementation - not a full ODB++ v8 writer - but produces the
directory structure and feature files needed for common use.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from openforge.pcb.model import PcbBoard, PcbFootprint, PcbPad


_LAYER_TO_ODB = {
    "F.Cu": ("top", "SIGNAL"),
    "B.Cu": ("bot", "SIGNAL"),
    "F.Mask": ("smt", "SOLDER_MASK"),
    "B.Mask": ("smb", "SOLDER_MASK"),
    "F.SilkS": ("sst", "SILK_SCREEN"),
    "B.SilkS": ("ssb", "SILK_SCREEN"),
    "F.Paste": ("spt", "SOLDER_PASTE"),
    "B.Paste": ("spb", "SOLDER_PASTE"),
    "Edge.Cuts": ("profile", "DOCUMENT"),
}


class OdbppExporter:
    def __init__(self, board: PcbBoard) -> None:
        self.board = board

    def export(self, output_dir: Path) -> Path:
        root = Path(output_dir) / f"{self.board.name}_odb"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

        # Top level files
        (root / "misc").mkdir()
        (root / "misc" / "info").write_text(
            "PRODUCT_MODEL_NAME=" + self.board.name + "\n"
            "JOB_NAME=" + self.board.name + "\n"
            "UNITS=MM\n"
            "ODB_VERSION_MAJOR=8\n"
            "ODB_VERSION_MINOR=1\n"
            f"CREATION_DATE={datetime.now(timezone.utc).isoformat()}\n"
        )

        # Steps
        step_dir = root / "steps" / self.board.name
        step_dir.mkdir(parents=True)
        (step_dir / "stephdr").write_text(
            "UNITS=MM\n"
            f"X_DATUM=0\nY_DATUM=0\nX_ORIGIN=0\nY_ORIGIN=0\n"
        )

        # Board outline as "profile"
        profile_dir = step_dir / "layers" / "profile"
        profile_dir.mkdir(parents=True)
        self._write_profile(profile_dir / "features")

        # Copper + mask + silk layers
        matrix_lines: list[str] = ["UNITS=MM", ""]
        row_num = 1
        for layer in self.board.stackup.layers:
            if layer.name not in _LAYER_TO_ODB:
                continue
            odb_name, ctx = _LAYER_TO_ODB[layer.name]
            ldir = step_dir / "layers" / odb_name
            ldir.mkdir(parents=True, exist_ok=True)
            self._write_features(ldir / "features", layer.name)
            matrix_lines.append("STEP {")
            matrix_lines.append(f"  NUM={row_num}")
            matrix_lines.append(f"  NAME={odb_name}")
            matrix_lines.append(f"  CONTEXT={ctx}")
            matrix_lines.append("}")
            row_num += 1

        matrix_dir = root / "matrix"
        matrix_dir.mkdir()
        (matrix_dir / "matrix").write_text("\n".join(matrix_lines) + "\n")

        return root

    # ------------------------------------------------------------------
    def _write_profile(self, path: Path) -> None:
        lines = ["UNITS=MM", "#", "# Profile features", "#"]
        pts = self.board.outline
        if len(pts) >= 3:
            lines.append("S 0")
            lines.append(f"OB {pts[0][0]:.4f} {pts[0][1]:.4f} I")
            for x, y in pts[1:]:
                lines.append(f"OS {x:.4f} {y:.4f}")
            lines.append(f"OS {pts[0][0]:.4f} {pts[0][1]:.4f}")
            lines.append("OE")
            lines.append("SE")
        path.write_text("\n".join(lines) + "\n")

    def _write_features(self, path: Path, layer_name: str) -> None:
        lines = ["UNITS=MM", "#", f"# Layer {layer_name}", "#"]
        sym_index: dict[str, int] = {}

        def sym(s: str) -> int:
            if s not in sym_index:
                sym_index[s] = len(sym_index)
            return sym_index[s]

        feat_lines: list[str] = []
        is_copper = layer_name.endswith(".Cu") or layer_name.startswith("In")

        # Pads
        for fp in self.board.footprints:
            for pad in fp.pads:
                if layer_name not in pad.layers:
                    continue
                x, y = fp.pad_world_xy(pad)
                if pad.shape == "round":
                    s = f"r{pad.size_x_mm:.3f}"
                else:
                    s = f"rect{pad.size_x_mm:.3f}x{pad.size_y_mm:.3f}"
                feat_lines.append(f"P {x:.4f} {y:.4f} {sym(s)} P 0 0")

        # Tracks
        if is_copper:
            for tr in self.board.tracks:
                if tr.layer != layer_name:
                    continue
                s = f"r{tr.width_mm:.3f}"
                feat_lines.append(
                    f"L {tr.x1_mm:.4f} {tr.y1_mm:.4f} {tr.x2_mm:.4f} {tr.y2_mm:.4f} {sym(s)} P 0 0"
                )
            for via in self.board.vias:
                s = f"r{via.diameter_mm:.3f}"
                feat_lines.append(f"P {via.x_mm:.4f} {via.y_mm:.4f} {sym(s)} P 0 0")

        # Symbol table first
        for sname, idx in sorted(sym_index.items(), key=lambda kv: kv[1]):
            lines.append(f"$ {idx} {sname}")
        lines.append("#")
        lines.extend(feat_lines)
        path.write_text("\n".join(lines) + "\n")
