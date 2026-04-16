"""Power Distribution Network (PDN) generation for physical design.

Generates OpenROAD-compatible TCL scripts for power grid construction
including VDD/VSS rails, straps, and ring connections for SKY130 and
GF180MCU PDKs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# PDK-specific PDN parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PDNLayerConfig:
    """Configuration for a single power strap layer."""

    layer: str
    direction: str      # "horizontal" or "vertical"
    width: float        # strap width in um
    pitch: float        # strap pitch in um
    offset: float       # offset from origin in um
    followpins: bool    # whether this layer follows standard cell rails


_SKY130_PDN_LAYERS: list[_PDNLayerConfig] = [
    _PDNLayerConfig(
        layer="met1",
        direction="horizontal",
        width=0.48,
        pitch=5.44,
        offset=0.0,
        followpins=True,     # Standard cell VDD/VSS rails on met1
    ),
    _PDNLayerConfig(
        layer="met4",
        direction="vertical",
        width=1.6,
        pitch=27.14,
        offset=13.57,
        followpins=False,
    ),
    _PDNLayerConfig(
        layer="met5",
        direction="horizontal",
        width=1.6,
        pitch=27.2,
        offset=13.6,
        followpins=False,
    ),
]

_GF180MCU_PDN_LAYERS: list[_PDNLayerConfig] = [
    _PDNLayerConfig(
        layer="Metal1",
        direction="horizontal",
        width=0.5,
        pitch=7.84,
        offset=0.0,
        followpins=True,
    ),
    _PDNLayerConfig(
        layer="Metal4",
        direction="vertical",
        width=1.6,
        pitch=28.0,
        offset=14.0,
        followpins=False,
    ),
    _PDNLayerConfig(
        layer="Metal5",
        direction="horizontal",
        width=1.6,
        pitch=28.0,
        offset=14.0,
        followpins=False,
    ),
]

_PDK_PDN_CONFIGS: dict[str, list[_PDNLayerConfig]] = {
    "sky130": _SKY130_PDN_LAYERS,
    "gf180mcu": _GF180MCU_PDN_LAYERS,
}

# VDD/VSS pin patterns for global connection
_PDK_POWER_PINS: dict[str, dict[str, list[str]]] = {
    "sky130": {
        "vdd_patterns": ["^VDD$", "^VPWR$"],
        "vss_patterns": ["^VSS$", "^VGND$"],
    },
    "gf180mcu": {
        "vdd_patterns": ["^VDD$", "^VPW$"],
        "vss_patterns": ["^VSS$", "^VNW$"],
    },
}


# ---------------------------------------------------------------------------
# PDNGenerator
# ---------------------------------------------------------------------------


class PDNGenerator:
    """Generate Power Distribution Network TCL scripts for OpenROAD.

    Produces ``pdngen``-compatible commands for VDD/VSS rail and strap
    creation on SKY130 and GF180MCU process nodes.
    """

    def __init__(self, pdk: str = "sky130") -> None:
        self._pdk = pdk
        self._layers = _PDK_PDN_CONFIGS.get(pdk, _SKY130_PDN_LAYERS)
        self._power_pins = _PDK_POWER_PINS.get(pdk, _PDK_POWER_PINS["sky130"])

    def generate_pdn(
        self,
        die_area: tuple[float, float, float, float],
        metal_layers: Sequence[str] | None = None,
    ) -> str:
        """Generate PDN TCL script for OpenROAD.

        Parameters
        ----------
        die_area:
            Die area as ``(x0, y0, x1, y1)`` in microns (informational,
            used for documentation in the generated script).
        metal_layers:
            Optional list of metal layer names to include.  If ``None``,
            all PDK-default layers are used.

        Returns
        -------
        str
            OpenROAD TCL commands for power grid generation.
        """
        layers = self._layers
        if metal_layers:
            metal_set = set(metal_layers)
            layers = [l for l in layers if l.layer in metal_set] or self._layers

        lines: list[str] = [
            f"# Power Distribution Network -- {self._pdk}",
            f"# Die area: ({die_area[0]:.1f}, {die_area[1]:.1f}) to "
            f"({die_area[2]:.1f}, {die_area[3]:.1f}) um",
            "",
            "# ---- Global power connections ----",
        ]

        # VDD connections
        for pattern in self._power_pins["vdd_patterns"]:
            if pattern == self._power_pins["vdd_patterns"][0]:
                lines.append(
                    f"add_global_connection -net VDD -pin_pattern {{{pattern}}} -power"
                )
            else:
                lines.append(
                    f"add_global_connection -net VDD -pin_pattern {{{pattern}}}"
                )

        # VSS connections
        for pattern in self._power_pins["vss_patterns"]:
            if pattern == self._power_pins["vss_patterns"][0]:
                lines.append(
                    f"add_global_connection -net VSS -pin_pattern {{{pattern}}} -ground"
                )
            else:
                lines.append(
                    f"add_global_connection -net VSS -pin_pattern {{{pattern}}}"
                )

        lines.extend([
            "global_connect",
            "",
            "# ---- Voltage domain ----",
            "set_voltage_domain -power VDD -ground VSS",
            "",
        ])

        # Determine pin layer (topmost strap layer)
        strap_layers = [l for l in layers if not l.followpins]
        pin_layer = strap_layers[-1].layer if strap_layers else layers[-1].layer

        lines.extend([
            "# ---- Power grid definition ----",
            f"define_pdn_grid -name main_grid -pins {{{pin_layer}}}",
            "",
        ])

        # Add straps for each layer
        for layer_cfg in layers:
            if layer_cfg.followpins:
                lines.append(
                    f"add_pdn_stripe -grid main_grid -layer {layer_cfg.layer} "
                    f"-width {layer_cfg.width} -followpins"
                )
            else:
                lines.append(
                    f"add_pdn_stripe -grid main_grid -layer {layer_cfg.layer} "
                    f"-width {layer_cfg.width} -pitch {layer_cfg.pitch} "
                    f"-offset {layer_cfg.offset}"
                )

        lines.append("")

        # Add connections between adjacent strap layers
        for i in range(len(layers) - 1):
            l1 = layers[i].layer
            l2 = layers[i + 1].layer
            lines.append(
                f"add_pdn_connect -grid main_grid -layers {{{l1} {l2}}}"
            )

        lines.append("")
        return "\n".join(lines)

    def generate_power_ring(
        self,
        die_area: tuple[float, float, float, float],
        ring_layer: str | None = None,
        ring_width: float = 2.0,
        ring_offset: float = 2.0,
    ) -> str:
        """Generate TCL for a power ring around the core area.

        Parameters
        ----------
        die_area:
            Die area as ``(x0, y0, x1, y1)`` in microns.
        ring_layer:
            Metal layer for the ring.  Defaults to met4 (SKY130) or
            Metal4 (GF180MCU).
        ring_width:
            Width of the power ring straps in microns.
        ring_offset:
            Offset from core boundary in microns.

        Returns
        -------
        str
            TCL commands for power ring generation.
        """
        if ring_layer is None:
            ring_layer = "met4" if self._pdk == "sky130" else "Metal4"

        # Pair layer for perpendicular direction
        pair_layer = "met5" if self._pdk == "sky130" else "Metal5"

        lines: list[str] = [
            f"# Power ring on {ring_layer}/{pair_layer}",
            f"add_pdn_ring -grid main_grid "
            f"-layers {{{ring_layer} {pair_layer}}} "
            f"-widths {{{ring_width} {ring_width}}} "
            f"-spacings {{2.0 2.0}} "
            f"-core_offsets {{{ring_offset} {ring_offset}}}",
        ]
        return "\n".join(lines)
