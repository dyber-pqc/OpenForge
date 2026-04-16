"""OpenLane2 project importer.

Reads ``config.json`` (preferred) or ``config.tcl`` from an OpenLane2
design directory and maps it to an OpenForge ASIC project targeting
sky130 by default.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..model import (
    Constraint,
    ConstraintKind,
    PDKRef,
    Project,
    ProjectKind,
    Target,
    TargetKind,
)

_TCL_SET = re.compile(r"^\s*set\s+(?:::)?(\w+)\s+(.+?)\s*$", re.M)


def _parse_tcl_config(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in _TCL_SET.finditer(text):
        key = m.group(1)
        val = m.group(2).strip()
        val = val.strip('"').strip("{}")
        out[key] = val
    return out


def _expand_list(value: Any, root: Path) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        items = re.split(r"\s+", str(value).strip())
    out: list[str] = []
    for item in items:
        if not item:
            continue
        item = item.replace("$::env(DESIGN_DIR)", str(root))
        item = item.replace("$DESIGN_DIR", str(root))
        p = Path(item)
        if not p.is_absolute():
            p = (root / item).resolve()
        out.append(str(p))
    return out


def import_openlane_dir(dir: str | Path) -> Project:
    """Import an OpenLane2 design directory."""
    root = Path(dir).resolve()
    if not root.exists():
        raise FileNotFoundError(root)

    cfg: dict[str, Any] = {}
    cfg_json = root / "config.json"
    cfg_tcl = root / "config.tcl"
    if cfg_json.exists():
        try:
            cfg = json.loads(cfg_json.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    elif cfg_tcl.exists():
        cfg = _parse_tcl_config(cfg_tcl.read_text(encoding="utf-8"))

    name = str(cfg.get("DESIGN_NAME") or root.name)
    top_module = str(cfg.get("DESIGN_NAME") or name)
    rtl_sources = _expand_list(cfg.get("VERILOG_FILES"), root)
    sdc_files = _expand_list(cfg.get("SDC_FILE") or cfg.get("SDC_FILES"), root)

    constraints: list[Constraint] = []
    clock_port = cfg.get("CLOCK_PORT")
    clock_period = cfg.get("CLOCK_PERIOD")
    if clock_port and clock_period:
        try:
            period = float(clock_period)
        except (TypeError, ValueError):
            period = 10.0
        constraints.append(
            Constraint(
                kind=ConstraintKind.CLOCK,
                name=str(clock_port),
                value=period,
                paths=[str(clock_port)],
                comment="Imported from OpenLane2 CLOCK_PORT / CLOCK_PERIOD",
            )
        )

    metadata: dict[str, Any] = {
        "imported_from": "openlane2",
        "source_dir": str(root),
    }
    if "FP_CORE_UTIL" in cfg:
        metadata["fp_core_util"] = cfg["FP_CORE_UTIL"]
    if "DIE_AREA" in cfg:
        metadata["die_area"] = cfg["DIE_AREA"]
    if "PL_TARGET_DENSITY" in cfg:
        metadata["pl_target_density"] = cfg["PL_TARGET_DENSITY"]

    pdk_name = str(cfg.get("PDK") or "sky130A")
    std_cell = str(cfg.get("STD_CELL_LIBRARY") or "sky130_fd_sc_hd")
    pdk = PDKRef(name=pdk_name, std_cell_lib=std_cell)
    target = Target(kind=TargetKind.ASIC, vendor="open-source", family=pdk_name)

    return Project(
        name=name,
        kind=ProjectKind.ASIC,
        top_module=top_module,
        rtl_sources=rtl_sources,
        constraint_files=sdc_files,
        pdk=pdk,
        target=target,
        constraints=constraints,
        metadata=metadata,
    )


__all__ = ["import_openlane_dir"]
