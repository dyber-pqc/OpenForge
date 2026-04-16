"""OpenForge PCB design subsystem.

Provides Altium-parity PCB design capabilities:
- Schematic capture
- Board layout
- Auto-routing
- Gerber/ODB++ export
- Component database
- BOM generation
"""
from openforge.pcb.schematic import (
    Pin,
    SchSymbol,
    SchComponent,
    SchNet,
    Schematic,
)
from openforge.pcb.board import (
    CopperLayer,
    Footprint,
    BoardComponent,
    Track,
    Via,
    Zone,
    Board,
)
from openforge.pcb.router import PcbRouter, RouteResult, RoutingMode
from openforge.pcb.net_classes import NetClass, NetClassRegistry, DEFAULT_CLASSES
from openforge.pcb.length_match import LengthGroup, LengthMatcher
from openforge.pcb.diff_pair import DiffPair, DiffPairRouter
from openforge.pcb.dsn import board_to_dsn, parse_ses
from openforge.pcb.gerber import GerberExporter, OdbPlusPlusExporter
from openforge.pcb.component_db import (
    Component,
    ComponentDatabase,
    BUILTIN_COMPONENTS,
)
from openforge.pcb.bom import BomLine, Bom, BomGenerator
from openforge.pcb.model import (
    PcbLayer,
    PcbStackup,
    PcbPad,
    PcbFootprint,
    PcbTrack,
    PcbVia,
    PcbZone,
    PcbBoard,
)
from openforge.pcb.footprints import FOOTPRINTS, get_footprint, list_footprints
from openforge.pcb.drc import PcbDrcRule, PcbDrcViolation, PcbDrcChecker
from openforge.pcb.odbpp import OdbppExporter

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
