"""Coverage closure manager (vManager-style backend).

Tracks coverage progress across runs, stores snapshots in a JSON history
file, evaluates user-defined goals, identifies coverage holes, and uses
simple heuristics to suggest test stimuli that would close them.

The companion desktop panel (``coverage_closure_panel.py``) consumes this
module entirely - all rendering / charting / interaction lives there.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CoverageGoal:
    """A target the team wants to hit on a particular metric."""

    name: str
    target_pct: float
    current_pct: float = 0.0
    weight: float = 1.0
    metric_type: str = "line"  # line/branch/toggle/fsm/functional/assertion/total

    def met(self) -> bool:
        return self.current_pct >= self.target_pct

    def gap(self) -> float:
        return max(0.0, self.target_pct - self.current_pct)


@dataclass
class CoverageSnapshot:
    """Coverage state at a single point in time."""

    timestamp: datetime
    test_count: int
    line_pct: float
    branch_pct: float
    toggle_pct: float
    fsm_pct: float
    functional_pct: float
    assertion_pct: float
    total_pct: float
    coverage_holes: list[dict] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "test_count": self.test_count,
            "line_pct": self.line_pct,
            "branch_pct": self.branch_pct,
            "toggle_pct": self.toggle_pct,
            "fsm_pct": self.fsm_pct,
            "functional_pct": self.functional_pct,
            "assertion_pct": self.assertion_pct,
            "total_pct": self.total_pct,
            "coverage_holes": self.coverage_holes,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CoverageSnapshot:
        ts = data.get("timestamp")
        try:
            t = datetime.fromisoformat(ts) if ts else datetime.utcnow()
        except (TypeError, ValueError):
            t = datetime.utcnow()
        return cls(
            timestamp=t,
            test_count=int(data.get("test_count", 0)),
            line_pct=float(data.get("line_pct", 0.0)),
            branch_pct=float(data.get("branch_pct", 0.0)),
            toggle_pct=float(data.get("toggle_pct", 0.0)),
            fsm_pct=float(data.get("fsm_pct", 0.0)),
            functional_pct=float(data.get("functional_pct", 0.0)),
            assertion_pct=float(data.get("assertion_pct", 0.0)),
            total_pct=float(data.get("total_pct", 0.0)),
            coverage_holes=list(data.get("coverage_holes", [])),
        )

    def get(self, metric: str) -> float:
        return float(getattr(self, f"{metric}_pct", 0.0))


@dataclass
class CoverageHole:
    """A specific gap in coverage."""

    file: str
    line: int
    type: str
    description: str
    suggestion: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


_METRICS = (
    "line",
    "branch",
    "toggle",
    "fsm",
    "functional",
    "assertion",
    "total",
)


class CoverageClosureManager:
    """Track coverage history, manage goals, surface holes."""

    def __init__(self, project_path: Path) -> None:
        self.project_path = Path(project_path)
        self.history_db = self.project_path / ".openforge" / "coverage_history.json"
        self.snapshots: list[CoverageSnapshot] = []
        self.goals: list[CoverageGoal] = []
        self.load_history()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load_history(self) -> None:
        if not self.history_db.exists():
            return
        try:
            data = json.loads(self.history_db.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.snapshots = [
            CoverageSnapshot.from_json(s) for s in data.get("snapshots", [])
        ]
        self.goals = [
            CoverageGoal(
                name=g["name"],
                target_pct=float(g.get("target_pct", 0.0)),
                current_pct=float(g.get("current_pct", 0.0)),
                weight=float(g.get("weight", 1.0)),
                metric_type=g.get("metric_type", "line"),
            )
            for g in data.get("goals", [])
        ]

    def save_history(self) -> None:
        self.history_db.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshots": [s.to_json() for s in self.snapshots],
            "goals": [asdict(g) for g in self.goals],
        }
        self.history_db.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def add_snapshot(self, coverage_report: Any) -> CoverageSnapshot:
        """Add a snapshot from a coverage report dict-like object.

        Accepts either a dict or any object with attributes matching the
        snapshot field names. Missing fields default to 0.0.
        """
        def grab(key: str, default: float = 0.0) -> float:
            if isinstance(coverage_report, dict):
                return float(coverage_report.get(key, default))
            return float(getattr(coverage_report, key, default))

        line = grab("line_pct")
        branch = grab("branch_pct")
        toggle = grab("toggle_pct")
        fsm = grab("fsm_pct")
        functional = grab("functional_pct")
        assertion = grab("assertion_pct")
        total = grab("total_pct")
        if total == 0:
            parts = [line, branch, toggle, fsm, functional, assertion]
            non_zero = [p for p in parts if p > 0]
            if non_zero:
                total = sum(non_zero) / len(non_zero)
        snap = CoverageSnapshot(
            timestamp=datetime.utcnow(),
            test_count=int(grab("test_count")),
            line_pct=line,
            branch_pct=branch,
            toggle_pct=toggle,
            fsm_pct=fsm,
            functional_pct=functional,
            assertion_pct=assertion,
            total_pct=total,
            coverage_holes=[
                h if isinstance(h, dict) else h.to_json()
                for h in (
                    coverage_report.get("coverage_holes", [])
                    if isinstance(coverage_report, dict)
                    else getattr(coverage_report, "coverage_holes", [])
                )
            ],
        )
        self.snapshots.append(snap)
        # Update goals' current values from this snapshot.
        for goal in self.goals:
            goal.current_pct = snap.get(goal.metric_type)
        self.save_history()
        return snap

    def latest(self) -> CoverageSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def get_trend(
        self, metric: str = "total", days: int = 30
    ) -> list[tuple[datetime, float]]:
        """Return ``(timestamp, pct)`` points for the requested window."""
        if metric not in _METRICS:
            metric = "total"
        cutoff = datetime.utcnow() - timedelta(days=days)
        return [
            (s.timestamp, s.get(metric))
            for s in self.snapshots
            if s.timestamp >= cutoff
        ]

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------
    def add_goal(self, goal: CoverageGoal) -> None:
        # Replace any existing goal with the same name.
        self.goals = [g for g in self.goals if g.name != goal.name]
        latest = self.latest()
        if latest is not None:
            goal.current_pct = latest.get(goal.metric_type)
        self.goals.append(goal)
        self.save_history()

    def remove_goal(self, name: str) -> None:
        self.goals = [g for g in self.goals if g.name != name]
        self.save_history()

    def evaluate_goals(self) -> dict[str, bool]:
        latest = self.latest()
        out: dict[str, bool] = {}
        for goal in self.goals:
            if latest is not None:
                goal.current_pct = latest.get(goal.metric_type)
            out[goal.name] = goal.met()
        return out

    def overall_progress(self) -> float:
        """Weighted average of goal current/target ratios."""
        if not self.goals:
            return 0.0
        total_w = sum(g.weight for g in self.goals) or 1.0
        score = 0.0
        for g in self.goals:
            ratio = g.current_pct / g.target_pct if g.target_pct > 0 else 1.0
            score += min(ratio, 1.0) * g.weight
        return 100.0 * score / total_w

    # ------------------------------------------------------------------
    # Hole analysis
    # ------------------------------------------------------------------
    def find_holes(self, coverage_report: Any) -> list[CoverageHole]:
        """Identify uncovered code locations from a coverage report."""
        raw: list[Any] = []
        if isinstance(coverage_report, dict):
            raw = list(coverage_report.get("coverage_holes", []))
        else:
            raw = list(getattr(coverage_report, "coverage_holes", []))
        holes: list[CoverageHole] = []
        for h in raw:
            if isinstance(h, CoverageHole):
                holes.append(h)
                continue
            if not isinstance(h, dict):
                continue
            holes.append(
                CoverageHole(
                    file=str(h.get("file", "?")),
                    line=int(h.get("line", 0)),
                    type=str(h.get("type", "uncovered_line")),
                    description=str(h.get("description", "")),
                    suggestion=str(h.get("suggestion", "")),
                )
            )
        # Auto-suggest where missing.
        for hole in holes:
            if not hole.suggestion:
                hole.suggestion = self._suggest_for_hole(hole)
        return holes

    def suggest_tests_for_holes(
        self,
        holes: list[CoverageHole],
        max_suggestions: int = 10,
    ) -> list[str]:
        """Generate up to ``max_suggestions`` SystemVerilog test stubs."""
        out: list[str] = []
        for hole in holes[:max_suggestions]:
            out.append(self._suggest_for_hole(hole))
        return out

    def _suggest_for_hole(self, hole: CoverageHole) -> str:
        loc = f"{Path(hole.file).name}:{hole.line}"
        if hole.type == "uncovered_branch":
            return (
                f"// Coverage hole at {loc}: {hole.description}\n"
                f"// Drive the missing branch:\n"
                f"initial begin\n"
                f"  // TODO: set inputs so that the alternative branch is taken\n"
                f"  // {hole.description}\n"
                f"end"
            )
        if hole.type == "missing_toggle":
            return (
                f"// Coverage hole at {loc}: signal never toggled\n"
                f"// {hole.description}\n"
                f"initial begin\n"
                f"  // TODO: toggle the signal high then low\n"
                f"end"
            )
        if hole.type == "fsm_state":
            return (
                f"// FSM state never reached at {loc}: {hole.description}\n"
                f"// TODO: drive sequence that exercises this state"
            )
        if hole.type == "functional":
            return (
                f"// Functional bin not hit at {loc}: {hole.description}\n"
                f"// TODO: add a directed test that produces this value"
            )
        return (
            f"// Coverage hole at {loc}: {hole.description}\n"
            f"// TODO: add a stim that executes this line"
        )

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------
    def compute_closure_estimate(self) -> dict[str, dict[str, Any]]:
        """Estimate the ETA at which each goal will be met."""
        out: dict[str, dict[str, Any]] = {}
        for goal in self.goals:
            slope, intercept = self._linear_fit(goal.metric_type)
            latest = self.latest()
            current = latest.get(goal.metric_type) if latest else 0.0
            met = current >= goal.target_pct
            eta_days: int | None = None
            eta_date: str | None = None
            if met:
                eta_days = 0
            elif slope and slope > 1e-9:
                # slope is pct/day
                remaining = goal.target_pct - current
                eta_days = int(math.ceil(remaining / slope))
                eta_date = (datetime.utcnow() + timedelta(days=eta_days)).strftime("%Y-%m-%d")
            out[goal.name] = {
                "met": met,
                "current": current,
                "target": goal.target_pct,
                "slope_per_day": slope,
                "eta_days": eta_days,
                "eta_date": eta_date,
                "weight": goal.weight,
                "metric": goal.metric_type,
            }
        return out

    def _linear_fit(self, metric: str) -> tuple[float, float]:
        """Tiny least-squares fit over the snapshot history."""
        if len(self.snapshots) < 2:
            return 0.0, 0.0
        first_t = self.snapshots[0].timestamp
        xs = [(s.timestamp - first_t).total_seconds() / 86400.0 for s in self.snapshots]
        ys = [s.get(metric) for s in self.snapshots]
        n = len(xs)
        try:
            mean_x = statistics.fmean(xs)
            mean_y = statistics.fmean(ys)
        except statistics.StatisticsError:
            return 0.0, 0.0
        num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        den = sum((xs[i] - mean_x) ** 2 for i in range(n))
        slope = num / den if den else 0.0
        intercept = mean_y - slope * mean_x
        return slope, intercept

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def generate_closure_report(self, output: Path) -> Path:
        """Render a self-contained HTML report (no external dependencies)."""
        output = Path(output)
        latest = self.latest()
        latest_html = ""
        if latest is not None:
            latest_html = (
                f"<p>Latest snapshot: <b>{latest.timestamp.isoformat()}</b></p>"
                f"<ul>"
                f"<li>Total: {latest.total_pct:.1f}%</li>"
                f"<li>Line: {latest.line_pct:.1f}%</li>"
                f"<li>Branch: {latest.branch_pct:.1f}%</li>"
                f"<li>Toggle: {latest.toggle_pct:.1f}%</li>"
                f"<li>FSM: {latest.fsm_pct:.1f}%</li>"
                f"<li>Functional: {latest.functional_pct:.1f}%</li>"
                f"<li>Assertion: {latest.assertion_pct:.1f}%</li>"
                f"</ul>"
            )

        goals_rows: list[str] = []
        forecast = self.compute_closure_estimate()
        for goal in self.goals:
            f = forecast.get(goal.name, {})
            met_marker = "OK" if f.get("met") else "..."
            eta = f.get("eta_date") or "-"
            goals_rows.append(
                f"<tr><td>{goal.name}</td><td>{goal.metric_type}</td>"
                f"<td>{goal.current_pct:.1f}%</td><td>{goal.target_pct:.1f}%</td>"
                f"<td>{met_marker}</td><td>{eta}</td></tr>"
            )

        history_rows: list[str] = []
        for s in self.snapshots[-50:]:
            history_rows.append(
                f"<tr><td>{s.timestamp.isoformat()}</td>"
                f"<td>{s.test_count}</td>"
                f"<td>{s.total_pct:.1f}%</td></tr>"
            )

        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Coverage Closure Report</title>
<style>
body {{ font-family: sans-serif; margin: 2em; background: #1e1e2e; color: #cdd6f4; }}
table {{ border-collapse: collapse; margin: 1em 0; }}
th, td {{ border: 1px solid #45475a; padding: 4px 10px; }}
th {{ background: #313244; }}
h1, h2 {{ color: #f5c2e7; }}
</style></head>
<body>
<h1>Coverage Closure Report</h1>
{latest_html}
<h2>Goals</h2>
<table><thead><tr><th>Name</th><th>Metric</th><th>Current</th><th>Target</th><th>Met</th><th>ETA</th></tr></thead>
<tbody>{''.join(goals_rows) or '<tr><td colspan=6>(no goals defined)</td></tr>'}</tbody></table>
<h2>Recent History</h2>
<table><thead><tr><th>Timestamp</th><th>Tests</th><th>Total %</th></tr></thead>
<tbody>{''.join(history_rows) or '<tr><td colspan=3>(no snapshots)</td></tr>'}</tbody></table>
</body></html>
"""
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        return output


__all__ = [
    "CoverageGoal",
    "CoverageSnapshot",
    "CoverageHole",
    "CoverageClosureManager",
]
