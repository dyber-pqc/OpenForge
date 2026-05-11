"""Netgen <-> OpenForge interoperability adapter.

Netgen is the LVS engine bundled with the open-source PDKs (sky130, gf180).
Its setup file is a Tcl script consumed by ``netgen -batch lvs ...`` to define
device-equivalence rules (``equate elements``, ``permute``, ``ignore``).

OpenForge's native LVS (``openforge-lvs``) consumes SPICE schematic netlists
directly, so users migrating from Netgen mostly need:

  1. their setup file's equivalence/permute rules turned into OpenForge LVS
     options (a YAML / dict the LVS engine consumes), and
  2. a parser for ``lvs.report`` so they can compare the OpenForge run against
     their existing Netgen baseline.

Netgen setup file directives we model:

  * ``permute <cell> <portA> <portB> [<portC> ...]``    -- order-independent ports
  * ``equate elements <a> <b>``                         -- treat two device names as the same
  * ``equate classes {<a> <b>}``                        -- alternate form
  * ``ignore class <name>``                             -- skip a device class
  * ``property <cell> <prop> tolerance <val>``          -- numeric matching tolerance
  * ``property <cell> <prop> ignore``                   -- ignore a numeric property

Netgen report fields we extract:

  * Top-cell names being compared (``Subcircuit summarizing ...``)
  * Per-cell device counts on layout vs schematic
  * Net counts
  * Match / mismatch verdict line (``Circuits match uniquely`` etc.)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setup-file model
# ---------------------------------------------------------------------------


class PermuteRule(BaseModel):
    cell: str
    ports: list[str]


class EquateElements(BaseModel):
    """``equate elements <a> <b>`` -- treat ``a`` and ``b`` as the same device."""

    layout: str
    schematic: str


class IgnoreClass(BaseModel):
    cell: str
    scope: str = "both"  # "both" | "layout" | "schematic"


class PropertyRule(BaseModel):
    cell: str
    prop: str
    action: str  # "tolerance" | "ignore"
    value: float | None = None


class NetgenSetup(BaseModel):
    """Parsed contents of a Netgen LVS setup ``.tcl`` file."""

    source_path: str = ""
    permute: list[PermuteRule] = Field(default_factory=list)
    equate_elements: list[EquateElements] = Field(default_factory=list)
    equate_classes: list[tuple[str, str]] = Field(default_factory=list)
    ignore_classes: list[IgnoreClass] = Field(default_factory=list)
    properties: list[PropertyRule] = Field(default_factory=list)
    raw_directives: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Setup-file parser
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"\{([^{}]*)\}|\"([^\"]*)\"|(\S+)")


def _tokenize_tcl(line: str) -> list[str]:
    """Tokenise a Tcl line. Handles ``{ ... }`` and ``" ... "`` grouping but
    not nested braces (good enough for Netgen setup files in the wild).
    """
    out: list[str] = []
    for m in _TOKEN_RE.finditer(line):
        out.append(m.group(1) if m.group(1) is not None else m.group(2) or m.group(3))
    return out


def _strip_comment(line: str) -> str:
    s = line.lstrip()
    if s.startswith("#"):
        return ""
    return line


def parse_netgen_setup(path: Path) -> NetgenSetup:
    """Parse a Netgen setup ``.tcl`` file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    setup = NetgenSetup(source_path=str(p))

    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        toks = _tokenize_tcl(line)
        if not toks:
            continue
        head = toks[0].lower()

        if head == "permute" and len(toks) >= 4:
            # permute <cell> <portA> <portB> [<portC> ...]
            setup.permute.append(PermuteRule(cell=toks[1], ports=toks[2:]))
        elif head == "equate" and len(toks) >= 3:
            sub = toks[1].lower()
            if sub == "elements":
                setup.equate_elements.append(EquateElements(layout=toks[2], schematic=toks[3]))
            elif sub == "classes":
                # `equate classes {a b}` or `equate classes a b`
                names = toks[2:]
                if len(names) == 1:
                    parts = names[0].split()
                    if len(parts) >= 2:
                        setup.equate_classes.append((parts[0], parts[1]))
                elif len(names) >= 2:
                    setup.equate_classes.append((names[0], names[1]))
        elif head == "ignore" and len(toks) >= 3 and toks[1].lower() == "class":
            setup.ignore_classes.append(IgnoreClass(cell=toks[2]))
        elif head == "property" and len(toks) >= 4:
            cell, prop = toks[1], toks[2]
            if "ignore" in (t.lower() for t in toks[3:]):
                setup.properties.append(PropertyRule(cell=cell, prop=prop, action="ignore"))
            elif "tolerance" in (t.lower() for t in toks[3:]):
                # find the value following the keyword
                idx = next(i for i, t in enumerate(toks[3:], start=3) if t.lower() == "tolerance")
                value: float | None = None
                if idx + 1 < len(toks):
                    try:
                        value = float(toks[idx + 1])
                    except ValueError:
                        value = None
                setup.properties.append(
                    PropertyRule(cell=cell, prop=prop, action="tolerance", value=value)
                )
        else:
            setup.raw_directives.append(line)

    return setup


# ---------------------------------------------------------------------------
# Translate setup -> openforge-lvs options
# ---------------------------------------------------------------------------


def netgen_to_lvs_options(setup: NetgenSetup) -> dict[str, Any]:
    """Map a parsed :class:`NetgenSetup` to a dict of openforge-lvs options.

    The returned dict matches the schema the OpenForge LVS engine consumes:

    .. code-block:: yaml

        permute_ports:
          - cell: nfet_01v8
            ports: [S, D]
        device_aliases:
          - {layout: pfet_01v8, schematic: PMOS}
        ignore_devices: [phantom_cap]
        property_tolerances:
          - {cell: nfet_01v8, prop: w, tolerance: 0.001}
        ignore_properties:
          - {cell: pfet_01v8, prop: as}
    """
    permute_ports = [{"cell": r.cell, "ports": list(r.ports)} for r in setup.permute]
    device_aliases = [{"layout": e.layout, "schematic": e.schematic} for e in setup.equate_elements]
    # equate classes -> also emit as device aliases (symmetric)
    for a, b in setup.equate_classes:
        device_aliases.append({"layout": a, "schematic": b})

    ignore_devices = [c.cell for c in setup.ignore_classes]

    property_tolerances: list[dict[str, Any]] = []
    ignore_properties: list[dict[str, str]] = []
    for prop in setup.properties:
        if prop.action == "tolerance":
            property_tolerances.append(
                {"cell": prop.cell, "prop": prop.prop, "tolerance": prop.value}
            )
        elif prop.action == "ignore":
            ignore_properties.append({"cell": prop.cell, "prop": prop.prop})

    return {
        "permute_ports": permute_ports,
        "device_aliases": device_aliases,
        "ignore_devices": ignore_devices,
        "property_tolerances": property_tolerances,
        "ignore_properties": ignore_properties,
    }


# ---------------------------------------------------------------------------
# lvs.report parser
# ---------------------------------------------------------------------------


class CellComparison(BaseModel):
    """One subcircuit comparison block in a Netgen ``lvs.report``."""

    cell: str
    layout_devices: int = 0
    schematic_devices: int = 0
    layout_nets: int = 0
    schematic_nets: int = 0
    matched: bool | None = None  # None if not yet decided


class NetgenReport(BaseModel):
    """Parsed Netgen ``lvs.report`` output."""

    source_path: str = ""
    top_cell: str = ""
    overall_match: bool = False
    verdict: str = ""
    cells: list[CellComparison] = Field(default_factory=list)


_NUM_RE = re.compile(r"(\d+)")


def parse_netgen_report(path: Path) -> NetgenReport:
    """Parse a Netgen ``lvs.report`` file.

    Netgen's report format is line-oriented and not formally specified; we
    look for the canonical phrases:

      * ``Subcircuit summary:`` introduces the per-cell tables
      * ``Subcircuit pins:`` / ``Subcircuit summary:`` blocks contain
        ``Number of devices`` and ``Number of nets`` lines
      * Verdict lines: ``Circuits match uniquely.`` / ``Circuits match with
        warnings.`` / ``Netlists do not match.``
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    report = NetgenReport(source_path=str(p))

    current: CellComparison | None = None
    last_cell_name: str = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()

        # Subcircuit header: "Subcircuit summarizing the circuit:" or
        # "Subcircuit: <name>"
        if low.startswith("subcircuit:"):
            last_cell_name = line.split(":", 1)[1].strip()
        elif low.startswith("subcircuit summary"):
            # Begin a fresh per-cell block
            if current is not None:
                report.cells.append(current)
            cell_name = last_cell_name or "(unknown)"
            current = CellComparison(cell=cell_name)
        elif low.startswith("number of devices"):
            nums = [int(m.group(1)) for m in _NUM_RE.finditer(line)]
            if current is not None and len(nums) >= 2:
                current.layout_devices, current.schematic_devices = nums[0], nums[1]
        elif low.startswith("number of nets"):
            nums = [int(m.group(1)) for m in _NUM_RE.finditer(line)]
            if current is not None and len(nums) >= 2:
                current.layout_nets, current.schematic_nets = nums[0], nums[1]
        elif "circuits match uniquely" in low or "circuits match with warnings" in low:
            report.overall_match = True
            report.verdict = line
            if current is not None:
                current.matched = True
        elif "netlists do not match" in low or "circuits do not match" in low:
            report.overall_match = False
            report.verdict = line
            if current is not None:
                current.matched = False
        elif low.startswith("top level cell") or low.startswith("toplevel"):
            # "Top level cell: <name>"
            parts = line.split(":", 1)
            if len(parts) == 2:
                report.top_cell = parts[1].strip()

    if current is not None:
        report.cells.append(current)

    if not report.top_cell and report.cells:
        report.top_cell = report.cells[-1].cell

    return report


def report_to_openforge_json(report: NetgenReport) -> str:
    """Serialize a :class:`NetgenReport` as the OpenForge LVS JSON shape."""
    payload = {
        "tool": "netgen",
        "top_cell": report.top_cell,
        "match": report.overall_match,
        "verdict": report.verdict,
        "cells": [c.model_dump() for c in report.cells],
    }
    return json.dumps(payload, indent=2)
