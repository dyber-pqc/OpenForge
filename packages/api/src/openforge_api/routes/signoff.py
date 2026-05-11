"""Sign-off result routes (DRC / LVS / xRC).

Reads JSON reports written by the native Rust sign-off binaries
(`openforge-drc`, `openforge-lvs`, `openforge-xrc`) from a project's
``build/`` directory and exposes them to the web UI.

The on-disk shapes mirror the desktop panels in
``packages/desktop/src/openforge_desktop/panels/{drc_browser,lvs_debugger_panel,parasitic_heatmap}.py``
so the same payload renders identically in Qt and the SvelteKit web app.

If a report is missing for a project, the endpoint returns 404 — the web
UI falls back to baked-in mock data in that case so the dashboard is still
useful in dev environments without any real run on disk.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DrcRuleCount(BaseModel):
    rule: str
    count: int


class DrcReport(BaseModel):
    project_id: str
    rule_deck: str = ""
    rules_loaded: int = 0
    total_violations: int = 0
    top_rules: list[DrcRuleCount] = Field(default_factory=list)
    severity: str = "green"  # green | yellow | red


class LvsSideCounts(BaseModel):
    devices: int = 0
    nets: int = 0


class LvsReport(BaseModel):
    project_id: str
    verdict: str = "UNKNOWN"  # MATCH | MISMATCH | UNKNOWN
    layout: LvsSideCounts = Field(default_factory=LvsSideCounts)
    schematic: LvsSideCounts = Field(default_factory=LvsSideCounts)
    physical_only_filtered: int = 0
    mismatched_devices: list[str] = Field(default_factory=list)
    mismatched_nets: list[str] = Field(default_factory=list)


class XrcCornerC(BaseModel):
    min: float = 0.0
    typ: float = 0.0
    max: float = 0.0


class XrcWorstNet(BaseModel):
    name: str = ""
    r: float = 0.0
    c: float = 0.0


class XrcReport(BaseModel):
    project_id: str
    total_wirelength_um: float = 0.0
    total_r_ohm: float = 0.0
    total_c_ff: XrcCornerC = Field(default_factory=XrcCornerC)
    worst_net: XrcWorstNet = Field(default_factory=XrcWorstNet)
    coupling_pairs: int = 0
    spef_files: dict[str, str] = Field(default_factory=dict)  # corner -> relative path


# ---------------------------------------------------------------------------
# Project-root resolution
# ---------------------------------------------------------------------------


def _project_root(project_id: str) -> Path:
    """Resolve a project's working directory.

    Honours ``OPENFORGE_PROJECTS_DIR`` if set, otherwise looks under
    ``./projects/<id>``. The path is not required to exist; downstream
    readers handle missing files gracefully.
    """
    base = Path(os.environ.get("OPENFORGE_PROJECTS_DIR", "projects"))
    return base / project_id


def _severity_for(violations: int) -> str:
    if violations > 1000:
        return "red"
    if violations > 100:
        return "yellow"
    return "green"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{project_id}/drc", response_model=DrcReport)
async def get_drc(project_id: str) -> DrcReport:
    root = _project_root(project_id)
    data = _read_json(root / "build" / "drc" / "drc.json")
    if data is None:
        # try the txt sidecar as a fallback (count violations only)
        txt = root / "build" / "drc" / "drc.txt"
        if not txt.exists():
            raise HTTPException(status_code=404, detail="DRC report not found")
        violations = txt.read_text(encoding="utf-8", errors="ignore").count("\n")
        return DrcReport(
            project_id=project_id,
            rule_deck=str(txt.name),
            total_violations=violations,
            severity=_severity_for(violations),
        )

    violations: list[dict[str, Any]] = data.get("violations", [])
    counter = Counter(v.get("rule", "<unknown>") for v in violations)
    top = [DrcRuleCount(rule=r, count=c) for r, c in counter.most_common(10)]
    total = data.get("total_violations", len(violations))
    return DrcReport(
        project_id=project_id,
        rule_deck=data.get("rule_deck", ""),
        rules_loaded=int(data.get("rules_loaded", 0)),
        total_violations=int(total),
        top_rules=top,
        severity=_severity_for(int(total)),
    )


@router.get("/{project_id}/lvs", response_model=LvsReport)
async def get_lvs(project_id: str) -> LvsReport:
    root = _project_root(project_id)
    data = _read_json(root / "build" / "lvs" / "lvs.json")
    if data is None:
        raise HTTPException(status_code=404, detail="LVS report not found")
    layout = data.get("layout", {})
    schem = data.get("schematic", {})
    return LvsReport(
        project_id=project_id,
        verdict=str(data.get("verdict", "UNKNOWN")).upper(),
        layout=LvsSideCounts(
            devices=int(layout.get("devices", 0)),
            nets=int(layout.get("nets", 0)),
        ),
        schematic=LvsSideCounts(
            devices=int(schem.get("devices", 0)),
            nets=int(schem.get("nets", 0)),
        ),
        physical_only_filtered=int(data.get("physical_only_filtered", 0)),
        mismatched_devices=list(data.get("mismatched_devices", [])),
        mismatched_nets=list(data.get("mismatched_nets", [])),
    )


@router.get("/{project_id}/xrc", response_model=XrcReport)
async def get_xrc(project_id: str) -> XrcReport:
    root = _project_root(project_id)
    xrc_dir = root / "build" / "xrc"
    summary = _read_json(xrc_dir / "summary.json")
    if summary is None:
        raise HTTPException(status_code=404, detail="xRC report not found")

    spef = {}
    for corner in ("min", "typ", "max"):
        for candidate in xrc_dir.glob(f"*.{corner}.spef"):
            spef[corner] = str(candidate.relative_to(root))
            break

    cap = summary.get("total_c_ff", {})
    worst = summary.get("worst_net", {})
    return XrcReport(
        project_id=project_id,
        total_wirelength_um=float(summary.get("total_wirelength_um", 0.0)),
        total_r_ohm=float(summary.get("total_r_ohm", 0.0)),
        total_c_ff=XrcCornerC(
            min=float(cap.get("min", 0.0)),
            typ=float(cap.get("typ", 0.0)),
            max=float(cap.get("max", 0.0)),
        ),
        worst_net=XrcWorstNet(
            name=str(worst.get("name", "")),
            r=float(worst.get("r", 0.0)),
            c=float(worst.get("c", 0.0)),
        ),
        coupling_pairs=int(summary.get("coupling_pairs", 0)),
        spef_files=spef,
    )
