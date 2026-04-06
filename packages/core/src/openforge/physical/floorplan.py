"""Floorplan generation for physical design.

Generates OpenROAD-compatible floorplan configurations including die/core
area sizing, placement site selection, and metal track definitions for
SKY130 and GF180MCU PDKs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# PDK-specific constants
# ---------------------------------------------------------------------------

# Standard cell site dimensions (width x height in microns)
_SITE_DIMENSIONS: dict[str, tuple[float, float]] = {
    "sky130": (0.46, 2.72),      # unithd
    "gf180mcu": (0.56, 3.92),    # GF018hv5v_green_sc7
}

_SITE_NAMES: dict[str, str] = {
    "sky130": "unithd",
    "gf180mcu": "GF018hv5v_green_sc7",
}

# Metal track definitions: layer -> (direction, pitch_um, offset_um)
_SKY130_TRACKS: dict[str, tuple[str, float, float]] = {
    "li1":  ("X", 0.46, 0.23),
    "met1": ("X", 0.34, 0.17),
    "met2": ("Y", 0.46, 0.23),
    "met3": ("X", 0.68, 0.34),
    "met4": ("Y", 0.92, 0.46),
    "met5": ("X", 3.40, 1.70),
}

_GF180MCU_TRACKS: dict[str, tuple[str, float, float]] = {
    "Metal1": ("X", 0.56, 0.28),
    "Metal2": ("Y", 0.56, 0.28),
    "Metal3": ("X", 0.56, 0.28),
    "Metal4": ("Y", 0.56, 0.28),
    "Metal5": ("X", 0.56, 0.28),
}

_PDK_TRACKS: dict[str, dict[str, tuple[str, float, float]]] = {
    "sky130": _SKY130_TRACKS,
    "gf180mcu": _GF180MCU_TRACKS,
}

# Typical gate density per um^2 (after technology mapping)
_GATES_PER_UM2: dict[str, float] = {
    "sky130": 800.0,     # ~800 gates per um^2 at hd library
    "gf180mcu": 400.0,   # ~400 gates per um^2
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FloorplanConfig:
    """Complete floorplan configuration for OpenROAD."""

    die_area: tuple[float, float, float, float]   # (x0, y0, x1, y1) in um
    core_area: tuple[float, float, float, float]   # (x0, y0, x1, y1) in um
    site_name: str = "unithd"
    tracks_config: str = ""   # TCL make_tracks commands
    die_width_um: float = 0.0
    die_height_um: float = 0.0
    core_width_um: float = 0.0
    core_height_um: float = 0.0
    estimated_gate_count: int = 0

    def __post_init__(self) -> None:
        self.die_width_um = self.die_area[2] - self.die_area[0]
        self.die_height_um = self.die_area[3] - self.die_area[1]
        self.core_width_um = self.core_area[2] - self.core_area[0]
        self.core_height_um = self.core_area[3] - self.core_area[1]

    @property
    def die_area_um2(self) -> float:
        return self.die_width_um * self.die_height_um

    @property
    def core_area_um2(self) -> float:
        return self.core_width_um * self.core_height_um

    @property
    def die_area_mm2(self) -> float:
        return self.die_area_um2 / 1e6

    @property
    def core_area_mm2(self) -> float:
        return self.core_area_um2 / 1e6


# ---------------------------------------------------------------------------
# FloorplanGenerator
# ---------------------------------------------------------------------------


class FloorplanGenerator:
    """Generate floorplan configurations for OpenROAD physical design.

    Handles die/core sizing, site snapping, track generation, and
    produces TCL commands compatible with OpenROAD's ``initialize_floorplan``.
    """

    def __init__(self, pdk: str = "sky130") -> None:
        self._pdk = pdk
        self._site_w, self._site_h = _SITE_DIMENSIONS.get(pdk, (0.46, 2.72))
        self._site_name = _SITE_NAMES.get(pdk, "unithd")
        self._tracks = _PDK_TRACKS.get(pdk, _SKY130_TRACKS)
        self._gates_per_um2 = _GATES_PER_UM2.get(pdk, 800.0)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def generate_floorplan(
        self,
        die_width_um: float,
        die_height_um: float,
        core_margin_um: float = 50.0,
        utilization_pct: float = 70.0,
    ) -> FloorplanConfig:
        """Generate a floorplan from explicit die dimensions.

        Parameters
        ----------
        die_width_um:
            Die width in microns.
        die_height_um:
            Die height in microns.
        core_margin_um:
            Margin between die edge and core area in microns.
        utilization_pct:
            Target utilization percentage (informational).

        Returns
        -------
        FloorplanConfig
            Complete floorplan configuration with snapped dimensions.
        """
        # Snap die dimensions to site grid
        die_w = self._snap_to_site_width(die_width_um)
        die_h = self._snap_to_site_height(die_height_um)

        # Snap core margin to site grid
        margin_w = self._snap_to_site_width(core_margin_um)
        margin_h = self._snap_to_site_height(core_margin_um)

        core_x0 = margin_w
        core_y0 = margin_h
        core_x1 = die_w - margin_w
        core_y1 = die_h - margin_h

        # Ensure core area is positive
        if core_x1 <= core_x0 or core_y1 <= core_y0:
            # Fall back to minimal margin
            core_x0 = self._site_w
            core_y0 = self._site_h
            core_x1 = die_w - self._site_w
            core_y1 = die_h - self._site_h

        tracks_config = self.generate_tracks_config()

        return FloorplanConfig(
            die_area=(0.0, 0.0, die_w, die_h),
            core_area=(core_x0, core_y0, core_x1, core_y1),
            site_name=self._site_name,
            tracks_config=tracks_config,
        )

    def auto_size(
        self,
        gate_count: int,
        utilization_target: float = 0.5,
    ) -> FloorplanConfig:
        """Estimate die size from gate count and target utilization.

        Parameters
        ----------
        gate_count:
            Estimated gate count from synthesis.
        utilization_target:
            Target core utilization (0.0 -- 1.0).  The die is sized so
            that placing ``gate_count`` gates would achieve this density.

        Returns
        -------
        FloorplanConfig
            Auto-sized floorplan configuration.
        """
        if utilization_target <= 0 or utilization_target > 1.0:
            utilization_target = 0.5

        # Calculate required core area
        area_per_gate = 1.0 / self._gates_per_um2
        total_gate_area = gate_count * area_per_gate
        required_core_area = total_gate_area / utilization_target

        # Square die with margin
        core_side = math.sqrt(required_core_area)
        core_side = max(core_side, 100.0)  # minimum 100 um

        # Standard margin: 10% of core side, minimum 20 um
        margin = max(core_side * 0.10, 20.0)

        die_side = core_side + 2 * margin

        # Snap to grid
        die_w = self._snap_to_site_width(die_side)
        die_h = self._snap_to_site_height(die_side)
        margin_w = self._snap_to_site_width(margin)
        margin_h = self._snap_to_site_height(margin)

        tracks_config = self.generate_tracks_config()

        config = FloorplanConfig(
            die_area=(0.0, 0.0, die_w, die_h),
            core_area=(margin_w, margin_h, die_w - margin_w, die_h - margin_h),
            site_name=self._site_name,
            tracks_config=tracks_config,
            estimated_gate_count=gate_count,
        )
        return config

    def generate_tracks_config(self) -> str:
        """Generate TCL ``make_tracks`` commands for the PDK."""
        lines: list[str] = ["# Metal track definitions"]
        for layer, (direction, pitch, offset) in self._tracks.items():
            lines.append(
                f"make_tracks {layer} "
                f"-x_offset {offset} -x_pitch {pitch} "
                f"-y_offset {offset} -y_pitch {pitch}"
            )
        return "\n".join(lines)

    def generate_openroad_tcl(
        self,
        config: FloorplanConfig,
        netlist: str,
        sdc: str,
        top_module: str,
        liberty: str,
        tech_lef: str,
        cell_lef: str,
        output_def: str,
    ) -> str:
        """Generate a complete OpenROAD floorplan TCL script.

        Parameters
        ----------
        config:
            Floorplan configuration from ``generate_floorplan`` or
            ``auto_size``.
        netlist:
            Path to the gate-level Verilog netlist.
        sdc:
            Path to the SDC constraints file.
        top_module:
            Top-level module name.
        liberty:
            Path to the Liberty timing library.
        tech_lef:
            Path to the technology LEF file.
        cell_lef:
            Path to the cell LEF file.
        output_def:
            Path for the output DEF file.

        Returns
        -------
        str
            Complete TCL script ready for ``openroad -exit``.
        """
        da = " ".join(f"{v:.3f}" for v in config.die_area)
        ca = " ".join(f"{v:.3f}" for v in config.core_area)

        hor_layer = "met3" if self._pdk == "sky130" else "Metal3"
        ver_layer = "met2" if self._pdk == "sky130" else "Metal2"

        lines: list[str] = [
            f"# OpenForge Floorplan Script -- {self._pdk}",
            f"# Die:  {config.die_width_um:.1f} x {config.die_height_um:.1f} um "
            f"({config.die_area_mm2:.4f} mm^2)",
            f"# Core: {config.core_width_um:.1f} x {config.core_height_um:.1f} um "
            f"({config.core_area_mm2:.4f} mm^2)",
            "",
            "# ---- Read technology ----",
            f"read_lef {tech_lef}",
            f"read_lef {cell_lef}",
            f"read_liberty {liberty}",
            "",
            "# ---- Read design ----",
            f"read_verilog {netlist}",
            f"link_design {top_module}",
            f"read_sdc {sdc}",
            "",
            "# ---- Initialize floorplan ----",
            f"initialize_floorplan -die_area {{{da}}} -core_area {{{ca}}} "
            f"-site {config.site_name}",
            "",
            "# ---- Metal tracks ----",
            config.tracks_config if config.tracks_config else "make_tracks",
            "",
            "# ---- IO pin placement ----",
            f"place_pins -hor_layer {hor_layer} -ver_layer {ver_layer}",
            "",
            "# ---- Write output ----",
            f"write_def {output_def}",
            "report_design_area",
            "",
            "exit",
        ]

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Grid snapping
    # ------------------------------------------------------------------

    def _snap_to_site_width(self, value: float) -> float:
        """Snap a value up to the nearest site width multiple."""
        return math.ceil(value / self._site_w) * self._site_w

    def _snap_to_site_height(self, value: float) -> float:
        """Snap a value up to the nearest site height multiple."""
        return math.ceil(value / self._site_h) * self._site_h
