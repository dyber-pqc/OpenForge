"""KiCad project importer.

Reads a ``.kicad_pro`` JSON file, locates the associated schematic
(``.kicad_sch``) and PCB (``.kicad_pcb``), extracts the board stackup
and a flat component list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..model import (
    Project,
    ProjectKind,
    Target,
    TargetKind,
)

_COMP_REF = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')
_COMP_VALUE = re.compile(r'\(property\s+"Value"\s+"([^"]+)"')
_COMP_FOOTPRINT = re.compile(r'\(property\s+"Footprint"\s+"([^"]+)"')
_SYMBOL_BLOCK = re.compile(r"\(symbol\b[^\(]*?(?=\(symbol\b|\Z)", re.S)


def _parse_schematic_components(sch_path: Path) -> list[dict[str, str]]:
    text = sch_path.read_text(encoding="utf-8", errors="replace")
    comps: list[dict[str, str]] = []
    for block in _SYMBOL_BLOCK.finditer(text):
        chunk = block.group(0)
        ref = _COMP_REF.search(chunk)
        val = _COMP_VALUE.search(chunk)
        fp = _COMP_FOOTPRINT.search(chunk)
        if not ref:
            continue
        reference = ref.group(1)
        if reference.startswith("#") or reference.endswith("?"):
            continue
        comps.append(
            {
                "ref": reference,
                "value": val.group(1) if val else "",
                "footprint": fp.group(1) if fp else "",
            }
        )
    return comps


def _parse_pcb_stackup(pcb_path: Path) -> list[dict[str, str]]:
    text = pcb_path.read_text(encoding="utf-8", errors="replace")
    stackup: list[dict[str, str]] = []
    # Match (layer N "name" type)
    layer_re = re.compile(
        r'\(layer\s+(\d+)\s+"([^"]+)"\s+(\w+)(?:\s+"[^"]*")?\s*\)'
    )
    for m in layer_re.finditer(text):
        stackup.append(
            {
                "number": m.group(1),
                "name": m.group(2),
                "type": m.group(3),
            }
        )
    return stackup


def import_kicad_project(pro_path: str | Path) -> Project:
    """Import a KiCad project from ``.kicad_pro``."""
    pro = Path(pro_path).resolve()
    if not pro.exists():
        raise FileNotFoundError(pro)
    proj_dir = pro.parent

    try:
        data = json.loads(pro.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    name = pro.stem
    board = data.get("board", {}) if isinstance(data, dict) else {}

    # find schematic and pcb
    sch_path: Path | None = None
    pcb_path: Path | None = None
    for p in proj_dir.glob(f"{name}.kicad_sch"):
        sch_path = p
        break
    for p in proj_dir.glob(f"{name}.kicad_pcb"):
        pcb_path = p
        break
    if sch_path is None:
        matches = list(proj_dir.glob("*.kicad_sch"))
        if matches:
            sch_path = matches[0]
    if pcb_path is None:
        matches = list(proj_dir.glob("*.kicad_pcb"))
        if matches:
            pcb_path = matches[0]

    components: list[dict[str, str]] = []
    if sch_path and sch_path.exists():
        try:
            components = _parse_schematic_components(sch_path)
        except Exception:
            components = []

    stackup: list[dict[str, str]] = []
    if pcb_path and pcb_path.exists():
        try:
            stackup = _parse_pcb_stackup(pcb_path)
        except Exception:
            stackup = []

    metadata: dict[str, Any] = {
        "imported_from": "kicad",
        "source_pro": str(pro),
        "components": components,
        "stackup": stackup,
        "board_settings": board,
    }

    target = Target(kind=TargetKind.PCB, vendor="kicad")
    return Project(
        name=name,
        kind=ProjectKind.PCB,
        schematic_file=str(sch_path) if sch_path else None,
        pcb_file=str(pcb_path) if pcb_path else None,
        board_file=str(pro),
        target=target,
        metadata=metadata,
    )


__all__ = ["import_kicad_project"]
