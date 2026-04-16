"""OpenForge PCB design subsystem.

Provides Altium-parity PCB design capabilities:
- Schematic capture
- Board layout
- Auto-routing
- Gerber/ODB++ export
- Component database
- BOM generation
"""

from openforge.pcb.board import (
    Board,
    BoardComponent,
    CopperLayer,
    Footprint,
    Track,
    Via,
    Zone,
)
from openforge.pcb.bom import Bom, BomGenerator, BomLine
from openforge.pcb.component_db import (
    BUILTIN_COMPONENTS,
    Component,
    ComponentDatabase,
)
from openforge.pcb.diff_pair import DiffPair, DiffPairRouter
from openforge.pcb.drc import PcbDrcChecker, PcbDrcRule, PcbDrcViolation
from openforge.pcb.dsn import board_to_dsn, parse_ses
from openforge.pcb.footprints import FOOTPRINTS, get_footprint, list_footprints
from openforge.pcb.gerber import GerberExporter, OdbPlusPlusExporter
from openforge.pcb.length_match import LengthGroup, LengthMatcher
from openforge.pcb.model import (
    PcbBoard,
    PcbFootprint,
    PcbLayer,
    PcbPad,
    PcbStackup,
    PcbTrack,
    PcbVia,
    PcbZone,
)
from openforge.pcb.net_classes import DEFAULT_CLASSES, NetClass, NetClassRegistry
from openforge.pcb.odbpp import OdbppExporter
from openforge.pcb.router import PcbRouter, RouteResult, RoutingMode
from openforge.pcb.schematic import (
    Pin,
    SchComponent,
    Schematic,
    SchNet,
    SchSymbol,
)

__all__ = [
    "Pin",
    "SchSymbol",
    "SchComponent",
    "SchNet",
    "Schematic",
    "CopperLayer",
    "Footprint",
    "BoardComponent",
    "Track",
    "Via",
    "Zone",
    "Board",
    "PcbRouter",
    "GerberExporter",
    "OdbPlusPlusExporter",
    "Component",
    "ComponentDatabase",
    "BUILTIN_COMPONENTS",
    "BomLine",
    "Bom",
    "BomGenerator",
]
