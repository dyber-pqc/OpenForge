"""Floorplan modelling, PDN synthesis, macro placement, and IO placement.

This package contains the data model used by the Floorplan Editor and the
PDN Synthesizer panels in the desktop application, as well as headless
helpers (macro force-directed placement, IO pin distribution) usable from
scripts and the CLI.
"""

from openforge.floorplan.model import (
    Core,
    Die,
    Floorplan,
    IoPad,
    MacroPlacement,
    PdnConfig,
    PowerRing,
    PowerStripe,
)
from openforge.floorplan.macro_placer import (
    estimate_wirelength,
    force_directed_placement,
    suggest_orientation,
)
from openforge.floorplan.io_placer import (
    Port,
    auto_place_pins,
    to_openroad_pin_constraints,
)

__all__ = [
    "Core",
    "Die",
    "Floorplan",
    "IoPad",
    "MacroPlacement",
    "PdnConfig",
    "PowerRing",
    "PowerStripe",
    "Port",
    "auto_place_pins",
    "estimate_wirelength",
    "force_directed_placement",
    "suggest_orientation",
    "to_openroad_pin_constraints",
]
