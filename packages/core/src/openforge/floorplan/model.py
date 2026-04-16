"""Floorplan data model.

Pydantic v2 models describing a chip floorplan: die/core geometry, macro
placements, IO pads, power-delivery network (rings, stripes, followpins,
via-stack), and blockages. The model can round-trip to/from DEF (via the
existing :mod:`openforge.format.def_parser`) and emit an OpenROAD Tcl
script that drives ``initialize_floorplan``, ``place_pin``, ``place_macro``
and ``pdngen`` with the configured power grid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Orientation = Literal["N", "S", "E", "W", "FN", "FS", "FE", "FW"]
Side = Literal["N", "S", "E", "W"]
Direction = Literal["HORIZONTAL", "VERTICAL"]
SignalDir = Literal["INPUT", "OUTPUT", "INOUT"]


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


class Die(BaseModel):
    """Die bounding box in micrometers. Origin is always (0, 0)."""

    width_um: float = Field(..., gt=0)
    height_um: float = Field(..., gt=0)

    @property
    def area_um2(self) -> float:
        return self.width_um * self.height_um


class Core(BaseModel):
    """Core area offset from the die origin (micrometers)."""

    x1: float = Field(..., ge=0)
    y1: float = Field(..., ge=0)
    x2: float = Field(..., gt=0)
    y2: float = Field(..., gt=0)

    @field_validator("x2")
    @classmethod
    def _x2_gt_x1(cls, v: float, info):  # type: ignore[override]
        if "x1" in info.data and v <= info.data["x1"]:
            raise ValueError("x2 must be greater than x1")
        return v

    @field_validator("y2")
    @classmethod
    def _y2_gt_y1(cls, v: float, info):  # type: ignore[override]
        if "y1" in info.data and v <= info.data["y1"]:
            raise ValueError("y2 must be greater than y1")
        return v

    @property
    def width_um(self) -> float:
        return self.x2 - self.x1

    @property
    def height_um(self) -> float:
        return self.y2 - self.y1

    @property
    def area_um2(self) -> float:
        return self.width_um * self.height_um


class Blockage(BaseModel):
    """A placement / routing blockage rectangle (um)."""

    x1: float
    y1: float
    x2: float
    y2: float
    kind: Literal["placement", "routing", "soft"] = "placement"
    layer: str = ""  # empty = all layers (placement blockage)


# ---------------------------------------------------------------------------
# Macros and IO pads
# ---------------------------------------------------------------------------


class MacroPlacement(BaseModel):
    """A placed hard macro instance."""

    name: str  # instance name in the design
    cell: str  # LEF macro name
    x_um: float  # lower-left
    y_um: float
    width_um: float = 0.0  # optional cached bbox for visualization
    height_um: float = 0.0
    orientation: Orientation = "N"
    halo_um: float = 5.0
    is_fixed: bool = True

    def bbox(self) -> tuple[float, float, float, float]:
        return (
            self.x_um,
            self.y_um,
            self.x_um + self.width_um,
            self.y_um + self.height_um,
        )

    def halo_bbox(self) -> tuple[float, float, float, float]:
        return (
            self.x_um - self.halo_um,
            self.y_um - self.halo_um,
            self.x_um + self.width_um + self.halo_um,
            self.y_um + self.height_um + self.halo_um,
        )


class IoPad(BaseModel):
    """A top-level IO pin constraint."""

    name: str
    side: Side
    offset_um: float  # position along the side (from lower/left edge)
    signal_dir: SignalDir = "INOUT"
    layer: str = "met2"


# ---------------------------------------------------------------------------
# PDN
# ---------------------------------------------------------------------------


class PowerStripe(BaseModel):
    """A periodic power/ground stripe configuration on a single metal layer."""

    layer: str
    direction: Direction
    pitch_um: float = Field(..., gt=0)
    width_um: float = Field(..., gt=0)
    offset_um: float = 0.0
    nets: list[str] = Field(default_factory=lambda: ["VDD", "VSS"])


class PowerRing(BaseModel):
    """A pair of power rings around the core (horizontal and vertical layers)."""

    layer_h: str
    layer_v: str
    width_um: float = Field(..., gt=0)
    spacing_um: float = Field(..., gt=0)
    offset_um: float = 0.0
    nets: list[str] = Field(default_factory=lambda: ["VDD", "VSS"])


class ViaStack(BaseModel):
    """A via cut between two metal layers for PDN connectivity."""

    from_layer: str
    to_layer: str
    cut_class: str = "VIA"  # OpenROAD via class name


class PdnConfig(BaseModel):
    """Full power-delivery network configuration."""

    rings: list[PowerRing] = Field(default_factory=list)
    stripes: list[PowerStripe] = Field(default_factory=list)
    followpins: bool = True
    followpins_layer: str = "met1"
    via_stack: list[ViaStack] = Field(default_factory=list)
    core_domain: str = "CORE"


# ---------------------------------------------------------------------------
# Top-level floorplan
# ---------------------------------------------------------------------------


class Floorplan(BaseModel):
    """A complete chip floorplan."""

    die: Die
    core: Core
    macros: list[MacroPlacement] = Field(default_factory=list)
    io_pads: list[IoPad] = Field(default_factory=list)
    pdn: PdnConfig = Field(default_factory=PdnConfig)
    blockages: list[Blockage] = Field(default_factory=list)
    site_name: str = "unithd"
    design_name: str = "top"

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_def(cls, def_path: str | Path) -> Floorplan:
        """Build a :class:`Floorplan` from a DEF file."""
        from openforge.format.def_parser import parse_def

        design = parse_def(Path(def_path))
        to_um = lambda v: v / design.units_per_micron  # noqa: E731

        die = Die(
            width_um=to_um(design.die_area.width) or 1.0,
            height_um=to_um(design.die_area.height) or 1.0,
        )
        # Core area is approximated by the union of placement rows; fall
        # back to an inset of the die if rows are missing.
        if design.rows:
            xs1 = [r.x for r in design.rows]
            ys1 = [r.y for r in design.rows]
            xs2 = [r.x + (r.width if r.width else r.step_x * r.num_x) for r in design.rows]
            ys2 = [r.y + r.height for r in design.rows]
            core = Core(
                x1=to_um(min(xs1)),
                y1=to_um(min(ys1)),
                x2=to_um(max(xs2)),
                y2=to_um(max(ys2)),
            )
        else:
            inset = max(die.width_um, die.height_um) * 0.1
            core = Core(
                x1=inset,
                y1=inset,
                x2=max(die.width_um - inset, inset + 1.0),
                y2=max(die.height_um - inset, inset + 1.0),
            )

        macros: list[MacroPlacement] = []
        for comp in design.components.values():
            if not (comp.is_macro or comp.status == "FIXED"):
                continue
            macros.append(
                MacroPlacement(
                    name=comp.name,
                    cell=comp.macro,
                    x_um=to_um(comp.x),
                    y_um=to_um(comp.y),
                    orientation=comp.orientation or "N",  # type: ignore[arg-type]
                    is_fixed=(comp.status == "FIXED"),
                )
            )

        pads: list[IoPad] = []
        for pin in design.pins.values():
            if pin.is_power:
                continue
            side, offset = _infer_pin_side(
                to_um(pin.x),
                to_um(pin.y),
                die.width_um,
                die.height_um,
            )
            pads.append(
                IoPad(
                    name=pin.name,
                    side=side,
                    offset_um=offset,
                    signal_dir=_dir_to_signal(pin.direction),
                    layer=pin.layer or "met2",
                )
            )

        return cls(
            die=die,
            core=core,
            macros=macros,
            io_pads=pads,
            design_name=design.name or "top",
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def utilization(self) -> float:
        """Return the estimated core-area utilization (0..1)."""
        core_area = self.core.area_um2
        if core_area <= 0:
            return 0.0
        macro_area = 0.0
        for m in self.macros:
            # Include halo in the occupied footprint for a realistic figure.
            x1, y1, x2, y2 = m.halo_bbox()
            macro_area += max(0.0, (x2 - x1) * (y2 - y1))
        return min(1.0, macro_area / core_area)

    def to_openroad_tcl(self) -> str:
        """Emit an OpenROAD Tcl script that realises this floorplan + PDN."""
        lines: list[str] = []
        push = lines.append

        push("# OpenROAD floorplan + PDN script - generated by OpenForge")
        push(f"# Design: {self.design_name}")
        push("")

        die = self.die
        core = self.core
        push("# --- Floorplan ---")
        push(
            "initialize_floorplan "
            f'-die_area "0 0 {die.width_um:g} {die.height_um:g}" '
            f'-core_area "{core.x1:g} {core.y1:g} {core.x2:g} {core.y2:g}" '
            f"-site {self.site_name}"
        )
        push("make_tracks")
        push("")

        # --- Macros ---
        if self.macros:
            push("# --- Macro placement ---")
            for m in self.macros:
                fixed = "-status FIRM" if m.is_fixed else "-status PLACED"
                push(
                    f"place_cell -inst_name {m.name} -origin "
                    f'"{m.x_um:g} {m.y_um:g}" -orient {m.orientation} {fixed}'
                )
                if m.halo_um > 0:
                    push(
                        f"set_placement_padding -instances {{{m.name}}} "
                        f"-left {m.halo_um:g} -right {m.halo_um:g} "
                        f"-top {m.halo_um:g} -bottom {m.halo_um:g}"
                    )
            push("")

        # --- IO pins ---
        if self.io_pads:
            push("# --- IO pin placement ---")
            for pad in self.io_pads:
                x, y = _pad_xy(pad, die)
                push(
                    f"place_pin -pin_name {pad.name} -layer {pad.layer} "
                    f'-location "{x:g} {y:g}" -force_to_die_boundary'
                )
            push("")
        else:
            push("# --- IO pin placement (automatic) ---")
            push("place_pins -hor_layers met3 -ver_layers met4")
            push("")

        # --- Blockages ---
        for blk in self.blockages:
            if blk.kind == "placement":
                push(
                    f'create_placement_blockage -area "{blk.x1:g} {blk.y1:g} {blk.x2:g} {blk.y2:g}"'
                )
            elif blk.kind == "routing":
                layer = blk.layer or "met1"
                push(
                    f"create_routing_blockage -layer {layer} "
                    f'-area "{blk.x1:g} {blk.y1:g} {blk.x2:g} {blk.y2:g}"'
                )
        if self.blockages:
            push("")

        # --- PDN ---
        push("# --- Power-delivery network (pdngen) ---")
        push("pdngen -reset")
        push('add_global_connection -net VDD -inst_pattern ".*" -pin_pattern "^VPWR$|^VDD$" -power')
        push(
            'add_global_connection -net VSS -inst_pattern ".*" -pin_pattern "^VGND$|^VSS$" -ground'
        )
        push("set_voltage_domain -name CORE -power VDD -ground VSS")
        push(f"define_pdn_grid -name core_grid -voltage_domains {self.pdn.core_domain} -pins {{}}")
        if self.pdn.followpins:
            push(
                f"add_pdn_stripe -grid core_grid -layer "
                f"{self.pdn.followpins_layer} -width 0.48 -followpins"
            )
        for ring in self.pdn.rings:
            push(
                f"add_pdn_ring -grid core_grid "
                f"-layers {{{ring.layer_h} {ring.layer_v}}} "
                f'-widths "{ring.width_um:g} {ring.width_um:g}" '
                f'-spacings "{ring.spacing_um:g} {ring.spacing_um:g}" '
                f'-core_offset "{ring.offset_um:g} {ring.offset_um:g}"'
            )
        for stripe in self.pdn.stripes:
            push(
                f"add_pdn_stripe -grid core_grid -layer {stripe.layer} "
                f"-width {stripe.width_um:g} -pitch {stripe.pitch_um:g} "
                f"-offset {stripe.offset_um:g} -extend_to_core_ring"
            )
        for via in self.pdn.via_stack:
            push(f"add_pdn_connect -grid core_grid -layers {{{via.from_layer} {via.to_layer}}}")
        push("pdngen")
        push("")

        push("# Write floorplan checkpoint")
        push("write_def floorplan.def")
        return "\n".join(lines) + "\n"

    def to_def(self) -> str:
        """Emit a minimal DEF text representing die, core rows and macros.

        The output is a lightweight round-trip format intended for
        checkpointing the interactive editor state. It does not include
        nets or routing.
        """
        units = 1000
        lines: list[str] = []
        lines.append("VERSION 5.8 ;")
        lines.append('DIVIDERCHAR "/" ;')
        lines.append('BUSBITCHARS "[]" ;')
        lines.append(f"DESIGN {self.design_name} ;")
        lines.append(f"UNITS DISTANCE MICRONS {units} ;")
        x2 = int(self.die.width_um * units)
        y2 = int(self.die.height_um * units)
        lines.append(f"DIEAREA ( 0 0 ) ( {x2} {y2} ) ;")

        if self.macros:
            lines.append(f"COMPONENTS {len(self.macros)} ;")
            for m in self.macros:
                status = "FIXED" if m.is_fixed else "PLACED"
                x = int(m.x_um * units)
                y = int(m.y_um * units)
                lines.append(f"- {m.name} {m.cell} + {status} ( {x} {y} ) {m.orientation} ;")
            lines.append("END COMPONENTS")

        if self.io_pads:
            lines.append(f"PINS {len(self.io_pads)} ;")
            for pad in self.io_pads:
                x, y = _pad_xy(pad, self.die)
                xi, yi = int(x * units), int(y * units)
                lines.append(
                    f"- {pad.name} + NET {pad.name} + DIRECTION {pad.signal_dir} "
                    f"+ USE SIGNAL + LAYER {pad.layer} ( 0 0 ) ( 100 100 ) "
                    f"+ PLACED ( {xi} {yi} ) N ;"
                )
            lines.append("END PINS")

        lines.append("END DESIGN")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_pin_side(x_um: float, y_um: float, w: float, h: float) -> tuple[Side, float]:
    """Infer which die edge a pin is closest to and return (side, offset)."""
    d_w = x_um
    d_e = max(w - x_um, 0.0)
    d_s = y_um
    d_n = max(h - y_um, 0.0)
    m = min(d_w, d_e, d_s, d_n)
    if m == d_w:
        return ("W", y_um)
    if m == d_e:
        return ("E", y_um)
    if m == d_s:
        return ("S", x_um)
    return ("N", x_um)


def _dir_to_signal(d: str) -> SignalDir:
    d = (d or "").upper()
    if d in ("INPUT", "IN"):
        return "INPUT"
    if d in ("OUTPUT", "OUT"):
        return "OUTPUT"
    return "INOUT"


def _pad_xy(pad: IoPad, die: Die) -> tuple[float, float]:
    """Convert a pad (side, offset) back into absolute (x, y) on the die edge."""
    if pad.side == "W":
        return (0.0, pad.offset_um)
    if pad.side == "E":
        return (die.width_um, pad.offset_um)
    if pad.side == "S":
        return (pad.offset_um, 0.0)
    return (pad.offset_um, die.height_um)
