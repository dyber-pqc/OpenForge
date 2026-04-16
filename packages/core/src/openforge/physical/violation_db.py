"""Unified multi-physics violation database.

A single source of truth for every sign-off check. All physical sign-off
engines (STA, DRC, IR, EM, Thermal, Antenna, Crosstalk, Glitch Power, LVS)
feed into this DB via :class:`ViolationImporter`. Consumers - the GUI
violation browser, the HTML signoff report, the REST API - all query this
DB instead of each individual engine.

Uses a lightweight SQLite backend for persistence plus an in-memory
index for fast queries; falls back to pure-Python lists when SQLite is
unavailable.
"""

from __future__ import annotations

import contextlib
import csv
import html
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

VALID_KINDS = {
    "setup",
    "hold",
    "recovery",
    "removal",
    "clock_gating",
    "ir_drop",
    "em",
    "thermal",
    "antenna",
    "drc",
    "lvs",
    "crosstalk",
    "glitch_power",
    "noise",
    "esd",
}
VALID_SEVERITIES = ("critical", "major", "minor", "info")

# Default worst-acceptable thresholds per (kind, unit) -- used to compute
# delta when the importer didn't supply one.
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "setup": 0.0,
    "hold": 0.0,
    "ir_drop": 50.0,
    "em": 1.0,
    "thermal": 125.0,
    "antenna": 400.0,
    "drc": 0.0,
    "lvs": 0.0,
    "crosstalk": 50.0,
    "glitch_power": 1.0,
}


class Violation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: str
    severity: str = "major"
    location: tuple[float, float] | None = None
    instance: str | None = None
    net: str | None = None
    layer: str | None = None
    metric_value: float = 0.0
    metric_unit: str = ""
    threshold: float = 0.0
    delta: float = 0.0
    suggestion: str = ""
    waiver_id: str | None = None
    source: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        if self.kind not in VALID_KINDS:
            # Accept but normalise to a safe kind bucket
            pass
        if self.severity not in VALID_SEVERITIES:
            self.severity = "major"
        if self.delta == 0.0 and self.metric_value != 0.0:
            self.delta = self.metric_value - self.threshold


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS violations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    x REAL,
    y REAL,
    instance TEXT,
    net TEXT,
    layer TEXT,
    metric_value REAL,
    metric_unit TEXT,
    threshold REAL,
    delta REAL,
    suggestion TEXT,
    waiver_id TEXT,
    source TEXT,
    timestamp TEXT
);
CREATE INDEX IF NOT EXISTS idx_kind ON violations(kind);
CREATE INDEX IF NOT EXISTS idx_severity ON violations(severity);
CREATE INDEX IF NOT EXISTS idx_instance ON violations(instance);

CREATE TABLE IF NOT EXISTS waivers (
    waiver_id TEXT PRIMARY KEY,
    justification TEXT,
    created TEXT
);
"""


class ViolationDb:
    """Single source of truth for sign-off violations.

    Backed by SQLite (file or ``:memory:``) with an in-memory mirror for
    fast iteration.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self._mem: list[Violation] = []
        self._conn: sqlite3.Connection | None = None
        try:
            if self.db_path is not None:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(str(self.db_path))
            else:
                self._conn = sqlite3.connect(":memory:")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except Exception:
            self._conn = None

    # ------------------------------------------------------------------
    def _insert_row(self, v: Violation) -> None:
        if self._conn is None:
            return
        x = v.location[0] if v.location else None
        y = v.location[1] if v.location else None
        with contextlib.suppress(Exception):
            self._conn.execute(
                """INSERT OR REPLACE INTO violations
                (id, kind, severity, x, y, instance, net, layer,
                 metric_value, metric_unit, threshold, delta,
                 suggestion, waiver_id, source, timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    v.id,
                    v.kind,
                    v.severity,
                    x,
                    y,
                    v.instance,
                    v.net,
                    v.layer,
                    v.metric_value,
                    v.metric_unit,
                    v.threshold,
                    v.delta,
                    v.suggestion,
                    v.waiver_id,
                    v.source,
                    v.timestamp,
                ),
            )

    def add(self, v: Violation) -> None:
        self._mem.append(v)
        self._insert_row(v)
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.commit()

    def add_bulk(self, vs: Iterable[Violation]) -> None:
        items = list(vs)
        self._mem.extend(items)
        for v in items:
            self._insert_row(v)
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.commit()

    def clear(self) -> None:
        self._mem.clear()
        if self._conn is not None:
            try:
                self._conn.execute("DELETE FROM violations")
                self._conn.commit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def query(
        self,
        kind: str | None = None,
        severity: str | None = None,
        instance: str | None = None,
        include_waived: bool = True,
    ) -> list[Violation]:
        out: list[Violation] = []
        for v in self._mem:
            if kind and v.kind != kind:
                continue
            if severity and v.severity != severity:
                continue
            if instance and (v.instance or "").find(instance) < 0:
                continue
            if not include_waived and v.waiver_id:
                continue
            out.append(v)
        return out

    def all(self) -> list[Violation]:
        return list(self._mem)

    def total_count(self) -> int:
        return len(self._mem)

    def grouped_by_kind(self) -> dict[str, list[Violation]]:
        out: dict[str, list[Violation]] = {}
        for v in self._mem:
            out.setdefault(v.kind, []).append(v)
        return out

    def grouped_by_severity(self) -> dict[str, list[Violation]]:
        out: dict[str, list[Violation]] = {s: [] for s in VALID_SEVERITIES}
        for v in self._mem:
            out.setdefault(v.severity, []).append(v)
        return out

    # ------------------------------------------------------------------
    def heatmap(
        self,
        grid_size_um: float = 10.0,
        extent: tuple[float, float, float, float] | None = None,
    ) -> np.ndarray:
        """2-D histogram of violation locations, weighted by severity."""
        w_map = {"critical": 4.0, "major": 2.0, "minor": 1.0, "info": 0.5}
        pts: list[tuple[float, float, float]] = []
        for v in self._mem:
            if v.location is None or v.waiver_id:
                continue
            pts.append((v.location[0], v.location[1], w_map.get(v.severity, 1.0)))
        if not pts:
            return np.zeros((1, 1), dtype=float)

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if extent is None:
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
        else:
            xmin, xmax, ymin, ymax = extent
        if xmax <= xmin:
            xmax = xmin + grid_size_um
        if ymax <= ymin:
            ymax = ymin + grid_size_um

        nx = max(1, int(np.ceil((xmax - xmin) / grid_size_um)))
        ny = max(1, int(np.ceil((ymax - ymin) / grid_size_um)))
        grid = np.zeros((ny, nx), dtype=float)
        for x, y, w in pts:
            col = int((x - xmin) / grid_size_um)
            row = int((y - ymin) / grid_size_um)
            if 0 <= col < nx and 0 <= row < ny:
                grid[row, col] += w
        return grid

    # ------------------------------------------------------------------
    def signoff_score(self) -> float:
        """0-100 sign-off score. Clean = 100."""
        score = 100.0
        weights = {"critical": 8.0, "major": 2.5, "minor": 0.5, "info": 0.05}
        for v in self._mem:
            if v.waiver_id:
                continue
            score -= weights.get(v.severity, 1.0)
        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    def waive(self, violation_id: str, waiver_id: str, justification: str) -> bool:
        hit = False
        for v in self._mem:
            if v.id == violation_id:
                v.waiver_id = waiver_id
                hit = True
                break
        if self._conn is not None:
            try:
                self._conn.execute(
                    "UPDATE violations SET waiver_id = ? WHERE id = ?",
                    (waiver_id, violation_id),
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO waivers (waiver_id, justification, created) VALUES (?,?,?)",
                    (waiver_id, justification, datetime.utcnow().isoformat()),
                )
                self._conn.commit()
            except Exception:
                pass
        return hit

    def waive_bulk(self, violation_ids: Iterable[str], waiver_id: str, justification: str) -> int:
        count = 0
        for vid in violation_ids:
            if self.waive(vid, waiver_id, justification):
                count += 1
        return count

    # ------------------------------------------------------------------
    def export_json(self, path: Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [v.model_dump() for v in self._mem]
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return p

    def export_csv(self, path: Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "id",
            "kind",
            "severity",
            "location",
            "instance",
            "net",
            "layer",
            "metric_value",
            "metric_unit",
            "threshold",
            "delta",
            "suggestion",
            "waiver_id",
            "source",
            "timestamp",
        ]
        with p.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for v in self._mem:
                row = v.model_dump()
                row["location"] = f"{v.location[0]:.2f},{v.location[1]:.2f}" if v.location else ""
                writer.writerow({k: row.get(k, "") for k in fields})
        return p

    def export_html(self, path: Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        e = html.escape

        def _row(v: Violation) -> str:
            loc = f"{v.location[0]:.1f}, {v.location[1]:.1f}" if v.location else ""
            return (
                "<tr>"
                f"<td>{e(v.kind)}</td><td>{e(v.severity)}</td>"
                f"<td>{e(loc)}</td><td>{e(v.instance or '')}</td>"
                f"<td>{v.metric_value:.3f}</td><td>{e(v.metric_unit)}</td>"
                f"<td>{v.threshold:.3f}</td><td>{v.delta:.3f}</td>"
                f"<td>{e(v.suggestion)}</td><td>{e(v.waiver_id or '')}</td>"
                "</tr>"
            )

        rows = "\n".join(_row(v) for v in self._mem)
        score = self.signoff_score()
        color = "#2e8b57" if score > 90 else ("#d48806" if score > 70 else "#cf1322")
        body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OpenForge Violations</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#111; color:#eee; padding:24px; }}
h1 {{ color:#7abaff; }}
table {{ border-collapse: collapse; width:100%; }}
td, th {{ border: 1px solid #333; padding: 6px 10px; font-size:12px; }}
th {{ background:#1a1a1a; }}
.score {{ font-size:48px; font-weight:bold; color:{color}; }}
</style></head><body>
<h1>OpenForge Multi-Physics Violations</h1>
<p>Sign-off score: <span class="score">{score:.1f}</span> / 100 &nbsp;
Total: {self.total_count()}</p>
<table><tr>
<th>Kind</th><th>Severity</th><th>Location</th><th>Instance</th>
<th>Value</th><th>Unit</th><th>Threshold</th><th>Delta</th>
<th>Suggestion</th><th>Waiver</th></tr>
{rows}
</table></body></html>
"""
        p.write_text(body, encoding="utf-8")
        return p


# ---------------------------------------------------------------------------
# Importers
# ---------------------------------------------------------------------------


def _as_iter(obj: Any, name: str) -> list[Any]:
    v = None
    with contextlib.suppress(Exception):
        v = getattr(obj, name, None)
    if v is None and isinstance(obj, dict):
        v = obj.get(name)
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        v = getattr(obj, name, default)
        return v if v is not None else default
    except Exception:
        return default


def _severity_from_slack(slack_ns: float) -> str:
    if slack_ns < -0.5:
        return "critical"
    if slack_ns < -0.1:
        return "major"
    if slack_ns < 0:
        return "minor"
    return "info"


class ViolationImporter:
    """Import violations from every sign-off engine into a :class:`ViolationDb`."""

    @staticmethod
    def from_sta_report(report: Any) -> list[Violation]:
        """Handles both STA result objects and raw path lists."""
        out: list[Violation] = []
        # Setup paths
        for path in _as_iter(report, "setup_violations") + _as_iter(report, "violating_paths"):
            slack = _safe_num(_get(path, "slack", 0.0))
            if slack >= 0:
                continue
            inst = _get(path, "endpoint") or _get(path, "end_point") or _get(path, "endpoint_inst")
            out.append(
                Violation(
                    kind="setup",
                    severity=_severity_from_slack(slack),
                    instance=str(inst) if inst else None,
                    metric_value=slack,
                    metric_unit="ns",
                    threshold=0.0,
                    delta=slack,
                    suggestion="Insert buffer / resize driver / relax timing constraint",
                    source="sta",
                )
            )
        for path in _as_iter(report, "hold_violations"):
            slack = _safe_num(_get(path, "slack", 0.0))
            if slack >= 0:
                continue
            inst = _get(path, "endpoint") or _get(path, "end_point")
            out.append(
                Violation(
                    kind="hold",
                    severity=_severity_from_slack(slack),
                    instance=str(inst) if inst else None,
                    metric_value=slack,
                    metric_unit="ns",
                    threshold=0.0,
                    delta=slack,
                    suggestion="Add delay buffer on data path",
                    source="sta",
                )
            )
        return out

    @staticmethod
    def from_drc_report(report: Any) -> list[Violation]:
        out: list[Violation] = []
        for viol in _as_iter(report, "violations"):
            x = _safe_num(_get(viol, "x", 0.0))
            y = _safe_num(_get(viol, "y", 0.0))
            out.append(
                Violation(
                    kind="drc",
                    severity=str(_get(viol, "severity", "major")),
                    location=(x, y),
                    layer=str(_get(viol, "layer", "") or "") or None,
                    metric_value=_safe_num(_get(viol, "value", 1.0)),
                    metric_unit=str(_get(viol, "unit", "") or ""),
                    threshold=_safe_num(_get(viol, "threshold", 0.0)),
                    suggestion=str(_get(viol, "rule", _get(viol, "description", "DRC violation"))),
                    source="drc",
                )
            )
        return out

    @staticmethod
    def from_ir_drop_result(result: Any) -> list[Violation]:
        out: list[Violation] = []
        worst = _safe_num(_get(result, "max_drop_mv", _get(result, "max_ir_mv", 0.0)))
        threshold = _safe_num(_get(result, "threshold_mv", 50.0))
        if worst > threshold:
            out.append(
                Violation(
                    kind="ir_drop",
                    severity="critical" if worst > 1.5 * threshold else "major",
                    metric_value=worst,
                    metric_unit="mV",
                    threshold=threshold,
                    delta=worst - threshold,
                    suggestion="Strengthen PDN straps / add decap / reduce local current",
                    source="ir_drop",
                )
            )
        for hot in _as_iter(result, "hotspots"):
            drop = _safe_num(_get(hot, "drop_mv", 0.0))
            if drop <= threshold:
                continue
            out.append(
                Violation(
                    kind="ir_drop",
                    severity="major" if drop < 1.5 * threshold else "critical",
                    location=(_safe_num(_get(hot, "x", 0.0)), _safe_num(_get(hot, "y", 0.0))),
                    metric_value=drop,
                    metric_unit="mV",
                    threshold=threshold,
                    delta=drop - threshold,
                    suggestion="Add local decap or widen straps",
                    source="ir_drop",
                )
            )
        return out

    @staticmethod
    def from_em_result(result: Any) -> list[Violation]:
        out: list[Violation] = []
        for v in _as_iter(result, "violations"):
            ratio = _safe_num(_get(v, "current_ratio", _get(v, "ratio", 1.0)))
            out.append(
                Violation(
                    kind="em",
                    severity="critical" if ratio > 1.5 else "major",
                    net=str(_get(v, "net", "") or "") or None,
                    layer=str(_get(v, "layer", "") or "") or None,
                    location=_get(v, "location"),
                    metric_value=ratio,
                    metric_unit="x_limit",
                    threshold=1.0,
                    delta=ratio - 1.0,
                    suggestion="Widen net / increase number of vias",
                    source="em",
                )
            )
        return out

    @staticmethod
    def from_thermal_result(result: Any) -> list[Violation]:
        out: list[Violation] = []
        tmax = _safe_num(_get(result, "max_temp_c", 0.0))
        threshold = _safe_num(_get(result, "threshold_c", 125.0))
        if tmax > threshold:
            out.append(
                Violation(
                    kind="thermal",
                    severity="critical" if tmax > threshold + 10 else "major",
                    metric_value=tmax,
                    metric_unit="C",
                    threshold=threshold,
                    delta=tmax - threshold,
                    suggestion="Spread power / add thermal vias / reduce local activity",
                    source="thermal",
                )
            )
        for hot in _as_iter(result, "hotspots"):
            temp = _safe_num(_get(hot, "temp_c", 0.0))
            if temp <= threshold:
                continue
            out.append(
                Violation(
                    kind="thermal",
                    severity="major",
                    location=(_safe_num(_get(hot, "x", 0.0)), _safe_num(_get(hot, "y", 0.0))),
                    metric_value=temp,
                    metric_unit="C",
                    threshold=threshold,
                    delta=temp - threshold,
                    suggestion="Thermal relief: spread cells",
                    source="thermal",
                )
            )
        return out

    @staticmethod
    def from_antenna_violations(violations: Any) -> list[Violation]:
        out: list[Violation] = []
        for v in _as_iter(violations, "violations") or (
            violations if isinstance(violations, (list, tuple)) else []
        ):
            ratio = _safe_num(_get(v, "ratio", 0.0))
            limit = _safe_num(_get(v, "limit", 400.0))
            out.append(
                Violation(
                    kind="antenna",
                    severity="major" if ratio <= 2 * limit else "critical",
                    net=str(_get(v, "net", "") or "") or None,
                    layer=str(_get(v, "layer", "") or "") or None,
                    metric_value=ratio,
                    metric_unit="ratio",
                    threshold=limit,
                    delta=ratio - limit,
                    suggestion="Insert diode / break net at higher layer",
                    source="antenna",
                )
            )
        return out

    @staticmethod
    def from_glitch_power(result: Any) -> list[Violation]:
        out: list[Violation] = []
        g = _safe_num(_get(result, "glitch_power_mw", 0.0))
        threshold = _safe_num(_get(result, "threshold_mw", 1.0))
        if g > threshold:
            out.append(
                Violation(
                    kind="glitch_power",
                    severity="major" if g < 2 * threshold else "critical",
                    metric_value=g,
                    metric_unit="mW",
                    threshold=threshold,
                    delta=g - threshold,
                    suggestion="Balance path delays / add glitch filters",
                    source="glitch_power",
                )
            )
        for hot in _as_iter(result, "glitchy_nets"):
            power = _safe_num(_get(hot, "power_mw", 0.0))
            out.append(
                Violation(
                    kind="glitch_power",
                    severity="minor",
                    net=str(_get(hot, "net", "") or "") or None,
                    metric_value=power,
                    metric_unit="mW",
                    threshold=threshold,
                    delta=power - threshold,
                    suggestion="Balance delays on fan-in",
                    source="glitch_power",
                )
            )
        return out

    @staticmethod
    def from_crosstalk_result(result: Any) -> list[Violation]:
        out: list[Violation] = []
        for v in _as_iter(result, "violations"):
            bump = _safe_num(_get(v, "bump_mv", _get(v, "noise_mv", 0.0)))
            limit = _safe_num(_get(v, "limit_mv", 50.0))
            out.append(
                Violation(
                    kind="crosstalk",
                    severity="major" if bump <= 1.5 * limit else "critical",
                    net=str(_get(v, "victim", _get(v, "net", "")) or "") or None,
                    metric_value=bump,
                    metric_unit="mV",
                    threshold=limit,
                    delta=bump - limit,
                    suggestion="Shield victim net / increase spacing",
                    source="crosstalk",
                )
            )
        return out

    @staticmethod
    def from_lvs_report(report: Any) -> list[Violation]:
        out: list[Violation] = []
        for m in _as_iter(report, "mismatches"):
            out.append(
                Violation(
                    kind="lvs",
                    severity="critical",
                    instance=str(_get(m, "instance", "") or "") or None,
                    metric_value=1.0,
                    metric_unit="count",
                    suggestion=str(_get(m, "description", "LVS mismatch")),
                    source="lvs",
                )
            )
        return out

    @staticmethod
    def import_all(
        db: ViolationDb,
        sta: Any = None,
        drc: Any = None,
        ir: Any = None,
        em: Any = None,
        thermal: Any = None,
        antenna: Any = None,
        glitch: Any = None,
        crosstalk: Any = None,
        lvs: Any = None,
    ) -> int:
        """Bulk-import from whichever engines were passed in. Returns count."""
        all_new: list[Violation] = []
        if sta is not None:
            all_new.extend(ViolationImporter.from_sta_report(sta))
        if drc is not None:
            all_new.extend(ViolationImporter.from_drc_report(drc))
        if ir is not None:
            all_new.extend(ViolationImporter.from_ir_drop_result(ir))
        if em is not None:
            all_new.extend(ViolationImporter.from_em_result(em))
        if thermal is not None:
            all_new.extend(ViolationImporter.from_thermal_result(thermal))
        if antenna is not None:
            all_new.extend(ViolationImporter.from_antenna_violations(antenna))
        if glitch is not None:
            all_new.extend(ViolationImporter.from_glitch_power(glitch))
        if crosstalk is not None:
            all_new.extend(ViolationImporter.from_crosstalk_result(crosstalk))
        if lvs is not None:
            all_new.extend(ViolationImporter.from_lvs_report(lvs))
        db.add_bulk(all_new)
        return len(all_new)


def _safe_num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


__all__ = [
    "Violation",
    "ViolationDb",
    "ViolationImporter",
    "VALID_KINDS",
    "VALID_SEVERITIES",
]
