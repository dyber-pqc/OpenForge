"""Metal density measurement and fill cell insertion.

Implements a production-quality layer density analyser plus a numpy-based
fill inserter that respects min spacing, halo around routing / macros,
and per-layer min/max density rules.  The output is emitted as a DEF
"patch" describing the new FILL cells so it can be merged by OpenROAD's
``read_def`` or used directly as input to ``detailed_route_eco``.

The algorithm:

1. Parse DEF + LEF.
2. Rasterise the die area into a grid whose pitch is taken from the rule
   window_size.  Each routing layer gets its own 2D occupancy map.
3. "Paint" instance bounding boxes (with halo) onto the li1/met1 maps.
4. "Paint" every DEF route segment onto the map for its own layer.
5. Compute per-window density as ``painted_pixels / total_pixels`` over
   a sliding window the size of the fill rule window.
6. For every window below the rule minimum density, deposit FILL cells
   into the remaining free pixels respecting the fill min/max size and
   spacing rules.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from openforge.format.def_parser import DefDesign, parse_def
from openforge.format.lef_parser import LefLibrary, parse_lef

# ---------------------------------------------------------------------------
# Rule / result models
# ---------------------------------------------------------------------------


class FillRule(BaseModel):
    """A single foundry density rule for one routing layer."""

    model_config = ConfigDict(extra="ignore")

    layer: str
    min_density_pct: float = 20.0
    max_density_pct: float = 80.0
    window_size_um: float = 100.0
    fill_min_size_um: float = 0.17
    fill_max_size_um: float = 10.0
    fill_spacing_um: float = 0.17


class FillWindow(BaseModel):
    """Density measured on one window of a layer."""

    model_config = ConfigDict(extra="ignore")

    x_um: float
    y_um: float
    size_um: float
    density_pct: float


class FillResult(BaseModel):
    """Before/after density + fill count for one layer."""

    model_config = ConfigDict(extra="ignore")

    layer: str
    pre_density_pct: float
    post_density_pct: float
    cells_inserted: int
    runtime_s: float
    windows_below_min: int = 0
    windows_above_max: int = 0
    rule_min_pct: float = 0.0
    rule_max_pct: float = 0.0
    fill_instances: list[tuple[str, float, float]] = Field(default_factory=list)
    # (inst_name, x_um, y_um) — enough to regenerate a DEF patch.


# ---------------------------------------------------------------------------
# Density filler
# ---------------------------------------------------------------------------


_GRID_PITCH_UM = 0.34  # fine raster pitch (sky130 li1 track-ish)


class DensityFiller:
    """Measure per-layer density and insert FILL cells in low windows."""

    def __init__(
        self,
        def_path: str | Path,
        lef_path: str | Path,
        rules: list[FillRule] | None = None,
        grid_pitch_um: float = _GRID_PITCH_UM,
    ) -> None:
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)
        self.design: DefDesign = parse_def(self.def_path)
        self.lib: LefLibrary = parse_lef(self.lef_path)
        self.rules: list[FillRule] = list(rules or SKY130_FILL_RULES)
        self.grid_pitch_um = float(grid_pitch_um)

        self._die_x1_um = self.design.to_um(self.design.die_area.x1)
        self._die_y1_um = self.design.to_um(self.design.die_area.y1)
        self._die_w_um = max(1.0, self.design.width_um)
        self._die_h_um = max(1.0, self.design.height_um)

        self._nx = max(1, int(self._die_w_um / self.grid_pitch_um) + 1)
        self._ny = max(1, int(self._die_h_um / self.grid_pitch_um) + 1)

        self._layer_masks: dict[str, np.ndarray] = {}
        self._inst_counter = 0
        self._fill_instances: list[tuple[str, str, float, float]] = []
        # (inst_name, macro, x_um, y_um)

    # ------------------------------------------------------------------ util

    def _blank_mask(self) -> np.ndarray:
        return np.zeros((self._ny, self._nx), dtype=np.uint8)

    def _xy_to_ij(self, x_um: float, y_um: float) -> tuple[int, int]:
        i = int((x_um - self._die_x1_um) / self.grid_pitch_um)
        j = int((y_um - self._die_y1_um) / self.grid_pitch_um)
        return (max(0, min(self._ny - 1, j)), max(0, min(self._nx - 1, i)))

    def _paint_rect(
        self,
        mask: np.ndarray,
        x1_um: float,
        y1_um: float,
        x2_um: float,
        y2_um: float,
    ) -> None:
        if x2_um < x1_um:
            x1_um, x2_um = x2_um, x1_um
        if y2_um < y1_um:
            y1_um, y2_um = y2_um, y1_um
        j1, i1 = self._xy_to_ij(x1_um, y1_um)
        j2, i2 = self._xy_to_ij(x2_um, y2_um)
        mask[j1 : j2 + 1, i1 : i2 + 1] = 1

    def _layer_mask(self, layer: str) -> np.ndarray:
        if layer not in self._layer_masks:
            self._layer_masks[layer] = self._build_layer_mask(layer)
        return self._layer_masks[layer]

    # ------------------------------------------------------------------ mask

    def _build_layer_mask(self, layer: str) -> np.ndarray:
        """Rasterise occupied pixels for a single routing layer."""
        mask = self._blank_mask()
        layer_l = layer.lower()

        # 1. Instance bboxes are considered to occupy li1 / met1 / their
        # internal routing layers.  We conservatively paint every instance
        # onto li1, met1 and met2.
        if layer_l in ("li1", "met1", "met2"):
            for comp in self.design.components.values():
                if not comp.is_placed:
                    continue
                macro = self.lib.macros.get(comp.macro)
                if macro is None:
                    w = 0.46
                    h = 2.72
                else:
                    w = macro.width
                    h = macro.height
                x1 = self.design.to_um(comp.x)
                y1 = self.design.to_um(comp.y)
                self._paint_rect(mask, x1, y1, x1 + w, y1 + h)

        # 2. Route segments on this layer.
        for net in self.design.nets.values():
            for seg in net.routes:
                if seg.layer.lower() != layer_l or len(seg.points) < 2:
                    continue
                # default width from LEF (µm)
                layer_lef = self.lib.layers.get(seg.layer) or self.lib.layers.get(seg.layer.lower())
                if seg.width > 0:
                    width_um = self.design.to_um(seg.width)
                elif layer_lef and layer_lef.width > 0:
                    width_um = layer_lef.width
                else:
                    width_um = 0.14
                half = width_um / 2.0
                pts = [(self.design.to_um(x), self.design.to_um(y)) for (x, y, _e) in seg.points]
                for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
                    if abs(x1 - x2) < 1e-9:  # vertical
                        self._paint_rect(mask, x1 - half, min(y1, y2), x1 + half, max(y1, y2))
                    else:
                        self._paint_rect(mask, min(x1, x2), y1 - half, max(x1, x2), y1 + half)

        # 3. Special nets (PDN stripes) - paint them too
        for snet in self.design.special_nets.values():
            for seg in snet.routes:
                if seg.layer.lower() != layer_l or len(seg.points) < 2:
                    continue
                w_um = self.design.to_um(seg.width) if seg.width > 0 else 1.6
                half = w_um / 2.0
                pts = [(self.design.to_um(x), self.design.to_um(y)) for (x, y, _e) in seg.points]
                for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
                    if abs(x1 - x2) < 1e-9:
                        self._paint_rect(mask, x1 - half, min(y1, y2), x1 + half, max(y1, y2))
                    else:
                        self._paint_rect(mask, min(x1, x2), y1 - half, max(x1, x2), y1 + half)

        return mask

    # ------------------------------------------------------------------ api

    def measure_density(
        self, layer: str, window_size_um: float = 100.0
    ) -> dict[tuple[float, float], float]:
        """Return ``{(x_um, y_um): density_pct}`` for each window."""
        mask = self._layer_mask(layer)
        step = max(1, int(window_size_um / self.grid_pitch_um))
        out: dict[tuple[float, float], float] = {}
        for j in range(0, self._ny, step):
            for i in range(0, self._nx, step):
                window = mask[j : j + step, i : i + step]
                if window.size == 0:
                    continue
                density = 100.0 * float(window.mean())
                x = self._die_x1_um + i * self.grid_pitch_um
                y = self._die_y1_um + j * self.grid_pitch_um
                out[(round(x, 3), round(y, 3))] = density
        return out

    def overall_density(self, layer: str) -> float:
        mask = self._layer_mask(layer)
        return 100.0 * float(mask.mean()) if mask.size else 0.0

    def fill_layer(
        self,
        layer: str,
        fill_cell: str = "FILL",
        halo_um: float = 0.5,
    ) -> FillResult:
        t0 = time.perf_counter()
        rule = self._rule_for(layer)
        if rule is None:
            return FillResult(
                layer=layer,
                pre_density_pct=self.overall_density(layer),
                post_density_pct=self.overall_density(layer),
                cells_inserted=0,
                runtime_s=0.0,
            )

        mask = self._layer_mask(layer).copy()
        pre_density = 100.0 * float(mask.mean())

        # Apply a halo around existing shapes so new fills don't clash.
        halo_px = max(1, int(halo_um / self.grid_pitch_um))
        halo_mask = _dilate(mask, halo_px)

        # Sliding window measurement
        step = max(1, int(rule.window_size_um / self.grid_pitch_um))
        below = 0
        above = 0
        inserted = 0
        fill_pitch_px = max(
            1, int((rule.fill_min_size_um + rule.fill_spacing_um) / self.grid_pitch_um)
        )
        fill_size_px = max(1, int(rule.fill_min_size_um / self.grid_pitch_um))

        for j0 in range(0, self._ny, step):
            for i0 in range(0, self._nx, step):
                j1 = min(self._ny, j0 + step)
                i1 = min(self._nx, i0 + step)
                window = halo_mask[j0:j1, i0:i1]
                if window.size == 0:
                    continue
                density_pct = 100.0 * float(window.mean())
                if density_pct > rule.max_density_pct:
                    above += 1
                    continue
                if density_pct >= rule.min_density_pct:
                    continue
                below += 1
                # Insert fills in every empty grid cell on a sparse pattern.
                target_density = rule.min_density_pct / 100.0
                current_fill = float(window.mean())
                for jj in range(j0, j1, fill_pitch_px):
                    for ii in range(i0, i1, fill_pitch_px):
                        if current_fill >= target_density:
                            break
                        jje = min(self._ny, jj + fill_size_px)
                        iie = min(self._nx, ii + fill_size_px)
                        patch = halo_mask[jj:jje, ii:iie]
                        if patch.size == 0 or patch.any():
                            continue
                        halo_mask[jj:jje, ii:iie] = 1
                        mask[jj:jje, ii:iie] = 1
                        x_um = self._die_x1_um + ii * self.grid_pitch_um
                        y_um = self._die_y1_um + jj * self.grid_pitch_um
                        self._inst_counter += 1
                        inst_name = f"FILLER_{layer}_{self._inst_counter}"
                        self._fill_instances.append((inst_name, fill_cell, x_um, y_um))
                        inserted += 1
                        current_fill = float(halo_mask[j0:j1, i0:i1].mean())
                    if current_fill >= target_density:
                        break

        post_density = 100.0 * float(mask.mean())
        self._layer_masks[layer] = mask
        return FillResult(
            layer=layer,
            pre_density_pct=pre_density,
            post_density_pct=post_density,
            cells_inserted=inserted,
            runtime_s=time.perf_counter() - t0,
            windows_below_min=below,
            windows_above_max=above,
            rule_min_pct=rule.min_density_pct,
            rule_max_pct=rule.max_density_pct,
            fill_instances=[
                (n, x, y)
                for (n, _m, x, y) in self._fill_instances
                if n.startswith(f"FILLER_{layer}_")
            ],
        )

    def fill_all(self, fill_cell: str = "FILL") -> dict[str, FillResult]:
        out: dict[str, FillResult] = {}
        for rule in self.rules:
            out[rule.layer] = self.fill_layer(rule.layer, fill_cell=fill_cell)
        return out

    def to_def_patch(self, output_path: str | Path) -> Path:
        """Write a DEF components patch describing the inserted fill cells.

        The format is a minimal DEF fragment that OpenROAD accepts via
        ``read_def -add``:

            COMPONENTS N ;
                - FILLER_met1_1 FILL + PLACED ( 1234 5678 ) N ;
                ...
            END COMPONENTS
        """
        p = Path(output_path)
        units = self.design.units_per_micron
        lines: list[str] = []
        lines.append(f"COMPONENTS {len(self._fill_instances)} ;")
        for name, macro, x_um, y_um in self._fill_instances:
            x_db = int(x_um * units)
            y_db = int(y_um * units)
            lines.append(f"    - {name} {macro} + PLACED ( {x_db} {y_db} ) N ;")
        lines.append("END COMPONENTS")
        p.write_text("\n".join(lines) + "\n")
        return p

    # ------------------------------------------------------------------ int

    def _rule_for(self, layer: str) -> FillRule | None:
        layer_l = layer.lower()
        for r in self.rules:
            if r.layer.lower() == layer_l:
                return r
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    """Binary dilation by ``px`` pixels using box-sum (no scipy dep)."""
    if px <= 0:
        return mask.copy()
    out = mask.astype(np.uint16).copy()
    for _ in range(px):
        tmp = out.copy()
        tmp[1:, :] |= out[:-1, :]
        tmp[:-1, :] |= out[1:, :]
        tmp[:, 1:] |= out[:, :-1]
        tmp[:, :-1] |= out[:, 1:]
        out = tmp
    return (out > 0).astype(np.uint8)


# ---------------------------------------------------------------------------
# SKY130 default rules (from SkyWater PDK)
# ---------------------------------------------------------------------------


SKY130_FILL_RULES: list[FillRule] = [
    FillRule(
        layer="li1",
        min_density_pct=20.0,
        max_density_pct=80.0,
        window_size_um=100.0,
        fill_min_size_um=0.17,
        fill_max_size_um=10.0,
        fill_spacing_um=0.17,
    ),
    FillRule(
        layer="met1",
        min_density_pct=20.0,
        max_density_pct=80.0,
        window_size_um=100.0,
        fill_min_size_um=0.17,
        fill_max_size_um=10.0,
        fill_spacing_um=0.17,
    ),
    FillRule(
        layer="met2",
        min_density_pct=20.0,
        max_density_pct=80.0,
        window_size_um=100.0,
        fill_min_size_um=0.21,
        fill_max_size_um=10.0,
        fill_spacing_um=0.21,
    ),
    FillRule(
        layer="met3",
        min_density_pct=20.0,
        max_density_pct=80.0,
        window_size_um=100.0,
        fill_min_size_um=0.30,
        fill_max_size_um=10.0,
        fill_spacing_um=0.30,
    ),
    FillRule(
        layer="met4",
        min_density_pct=20.0,
        max_density_pct=80.0,
        window_size_um=100.0,
        fill_min_size_um=0.30,
        fill_max_size_um=10.0,
        fill_spacing_um=0.30,
    ),
    FillRule(
        layer="met5",
        min_density_pct=20.0,
        max_density_pct=80.0,
        window_size_um=100.0,
        fill_min_size_um=1.60,
        fill_max_size_um=20.0,
        fill_spacing_um=1.60,
    ),
]


__all__ = [
    "FillRule",
    "FillWindow",
    "FillResult",
    "DensityFiller",
    "SKY130_FILL_RULES",
]
