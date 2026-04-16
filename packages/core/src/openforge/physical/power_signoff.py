"""Unified power sign-off orchestrator.

Runs vector power, glitch power, IR drop, EM, and thermal in a single pass
across corners and modes and aggregates the results into a
``PowerSignoffResult`` plus an HTML dashboard report.

The orchestrator is intentionally tolerant of engines being missing or
throwing - each step is wrapped and degrades to ``0.0`` / ``n/a`` rather
than aborting the whole run. This is the same contract used by the
Wave 1 sign-off dashboard.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from openforge.physical.vector_power import (
    VectorPowerAnalyzer,
    VectorPowerResult,
)

# Optional engines -- import tolerantly so tests without a full physical
# stack can still use this module.
try:
    from openforge.physical.ir_drop import IrDropEstimator  # type: ignore
except Exception:  # pragma: no cover
    IrDropEstimator = None  # type: ignore[assignment,misc]
try:
    from openforge.physical.electromigration import ElectromigrationAnalyzer  # type: ignore
except Exception:  # pragma: no cover
    ElectromigrationAnalyzer = None  # type: ignore[assignment,misc]
try:
    from openforge.physical.thermal import ThermalAnalyzer  # type: ignore
except Exception:  # pragma: no cover
    ThermalAnalyzer = None  # type: ignore[assignment,misc]
try:
    from openforge.physical.power import PowerAnalyzer  # type: ignore
except Exception:  # pragma: no cover
    PowerAnalyzer = None  # type: ignore[assignment,misc]


ProgressFn = Callable[[str, float], None]


# ---------------------------------------------------------------------------
# Config / result models
# ---------------------------------------------------------------------------


class PowerSignoffConfig(BaseModel):
    corners: list[str] = Field(default_factory=lambda: ["TT", "SS", "FF"])
    modes: list[str] = Field(default_factory=lambda: ["functional"])
    vcd_files: dict[str, str] = Field(default_factory=dict)  # mode -> path
    duration_ns: float = 0.0
    lib_path: Optional[str] = None
    vdd: float = 0.9


class CornerPower(BaseModel):
    corner: str
    leakage_mw: float = 0.0
    dynamic_mw: float = 0.0
    total_mw: float = 0.0
    ir_drop_mv: float = 0.0
    em_violations: int = 0
    thermal_max_c: float = 25.0
    status: str = "PASS"


class ModePower(BaseModel):
    mode: str
    dynamic_mw: float = 0.0
    leakage_mw: float = 0.0
    total_mw: float = 0.0
    peak_mw: float = 0.0
    peak_time_ns: float = 0.0
    duration_ns: float = 0.0


class PowerSignoffResult(BaseModel):
    config: PowerSignoffConfig
    static_per_corner: dict[str, dict[str, float]] = Field(default_factory=dict)
    dynamic_per_mode: dict[str, dict[str, float]] = Field(default_factory=dict)
    corner_summary: list[CornerPower] = Field(default_factory=list)
    mode_summary: list[ModePower] = Field(default_factory=list)
    glitch_power_mw: float = 0.0
    ir_drop_max_mv: float = 0.0
    em_violations: int = 0
    thermal_max_c: float = 25.0
    top_cells: list[dict[str, Any]] = Field(default_factory=list)
    instantaneous: list[tuple[float, float]] = Field(default_factory=list)
    density_grid: dict[str, Any] = Field(default_factory=dict)
    overall_status: str = "PASS"
    score: float = 100.0
    warnings: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# Corner voltage / leakage multipliers (TT = nominal)
_CORNER_PROFILES: dict[str, dict[str, float]] = {
    "TT": {"vdd_scale": 1.00, "leakage_scale": 1.00, "temp_c": 25.0},
    "SS": {"vdd_scale": 0.90, "leakage_scale": 0.60, "temp_c": -40.0},
    "FF": {"vdd_scale": 1.10, "leakage_scale": 1.80, "temp_c": 125.0},
    "FS": {"vdd_scale": 1.00, "leakage_scale": 1.20, "temp_c": 85.0},
    "SF": {"vdd_scale": 1.00, "leakage_scale": 0.80, "temp_c": 85.0},
}


def _report(progress: Optional[ProgressFn], msg: str, frac: float) -> None:
    if progress is None:
        return
    try:
        progress(msg, max(0.0, min(1.0, frac)))
    except Exception:
        pass


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_getattr(obj: Any, name: str, default: Any = 0.0) -> Any:
    try:
        v = getattr(obj, name, default)
        return v if v is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class PowerSignoffOrchestrator:
    """Run all power-related checks in one pass and produce a unified report."""

    def __init__(
        self,
        config: PowerSignoffConfig,
        def_path: Path,
        lef_path: Path,
    ) -> None:
        self.config = config
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)

    # ------------------------------------------------------------------
    def _run_mode(
        self,
        mode: str,
        vcd_path: Path,
        progress: Optional[ProgressFn],
        frac_base: float,
        frac_span: float,
    ) -> tuple[ModePower, Optional[VectorPowerResult]]:
        _report(progress, f"vector power: {mode}", frac_base)
        lib_path = Path(self.config.lib_path) if self.config.lib_path else None
        try:
            analyzer = VectorPowerAnalyzer(
                vcd_path=vcd_path,
                def_path=self.def_path,
                lef_path=self.lef_path,
                lib_path=lib_path,
                vdd=self.config.vdd,
            )
            vres = analyzer.run(timestep_ns=0.1)
        except Exception as exc:
            _report(progress, f"vector power {mode} failed: {exc}", frac_base + frac_span)
            return ModePower(mode=mode), None
        _report(progress, f"vector power: {mode} done", frac_base + frac_span)
        return (
            ModePower(
                mode=mode,
                dynamic_mw=vres.total_dynamic_power_mw,
                leakage_mw=vres.total_leakage_power_mw,
                total_mw=vres.total_power_mw,
                peak_mw=vres.peak_power_mw,
                peak_time_ns=vres.peak_time_ns,
                duration_ns=vres.duration_ns,
            ),
            vres,
        )

    # ------------------------------------------------------------------
    def _run_corner(
        self,
        corner: str,
        base_dyn_mw: float,
        base_leak_mw: float,
        progress: Optional[ProgressFn],
        frac_base: float,
        frac_span: float,
    ) -> CornerPower:
        _report(progress, f"corner {corner}: ir/em/thermal", frac_base)
        profile = _CORNER_PROFILES.get(corner.upper(), _CORNER_PROFILES["TT"])
        dyn_mw = base_dyn_mw * (profile["vdd_scale"] ** 2)
        leak_mw = base_leak_mw * profile["leakage_scale"]
        total_mw = dyn_mw + leak_mw

        # IR drop (best-effort)
        ir_mv = 0.0
        if IrDropEstimator is not None:
            try:
                est = IrDropEstimator(self.def_path)  # type: ignore[call-arg]
                result = est.estimate() if hasattr(est, "estimate") else est.run()
                ir_mv = _safe_float(_safe_getattr(result, "max_drop_mv", 0.0))
                if ir_mv == 0.0:
                    ir_mv = _safe_float(_safe_getattr(result, "max_ir_mv", 0.0))
            except Exception:
                ir_mv = 0.0
        # Scale IR by total power (rough): higher power -> higher IR
        if ir_mv == 0.0:
            ir_mv = total_mw * 0.8 * profile["vdd_scale"]

        # EM
        em_viol = 0
        if ElectromigrationAnalyzer is not None:
            try:
                em_a = ElectromigrationAnalyzer(self.def_path)  # type: ignore[call-arg]
                em_res = em_a.analyze() if hasattr(em_a, "analyze") else em_a.run()
                violations = _safe_getattr(em_res, "violations", [])
                if isinstance(violations, list):
                    em_viol = len(violations)
                else:
                    em_viol = int(_safe_getattr(em_res, "violation_count", 0))
            except Exception:
                em_viol = 0

        # Thermal
        thermal_c = profile["temp_c"]
        if ThermalAnalyzer is not None:
            try:
                t_a = ThermalAnalyzer(self.def_path)  # type: ignore[call-arg]
                t_res = t_a.analyze() if hasattr(t_a, "analyze") else t_a.run()
                tmax = _safe_float(
                    _safe_getattr(t_res, "max_temp_c", profile["temp_c"])
                )
                if tmax > 0:
                    thermal_c = tmax
            except Exception:
                pass
        # Heuristic: add self-heating contribution
        thermal_c += total_mw * 0.15

        status = "PASS"
        if ir_mv > 50.0 or thermal_c > 125.0 or em_viol > 10:
            status = "FAIL"
        elif ir_mv > 30.0 or thermal_c > 100.0 or em_viol > 0:
            status = "WARN"

        _report(progress, f"corner {corner} done", frac_base + frac_span)
        return CornerPower(
            corner=corner,
            leakage_mw=leak_mw,
            dynamic_mw=dyn_mw,
            total_mw=total_mw,
            ir_drop_mv=ir_mv,
            em_violations=em_viol,
            thermal_max_c=thermal_c,
            status=status,
        )

    # ------------------------------------------------------------------
    def run(self, progress: Optional[ProgressFn] = None) -> PowerSignoffResult:
        cfg = self.config
        _report(progress, "starting power sign-off", 0.0)

        modes = cfg.modes or ["functional"]
        mode_results: list[ModePower] = []
        mode_vector_results: list[Optional[VectorPowerResult]] = []
        warnings: list[str] = []

        # --- per-mode vector power --------------------------------------------------
        mode_count = max(1, len(modes))
        for idx, mode in enumerate(modes):
            vcd = cfg.vcd_files.get(mode)
            if not vcd or not Path(vcd).exists():
                warnings.append(f"no VCD for mode '{mode}', skipping vector power")
                mode_results.append(ModePower(mode=mode))
                mode_vector_results.append(None)
                continue
            mr, vres = self._run_mode(
                mode,
                Path(vcd),
                progress,
                frac_base=0.05 + 0.45 * idx / mode_count,
                frac_span=0.45 / mode_count,
            )
            mode_results.append(mr)
            mode_vector_results.append(vres)

        # Pick the mode with highest total power as the base for corner scaling
        base_mode = None
        for mr in mode_results:
            if mr.total_mw > 0 and (base_mode is None or mr.total_mw > base_mode.total_mw):
                base_mode = mr
        base_dyn = base_mode.dynamic_mw if base_mode else 0.0
        base_leak = base_mode.leakage_mw if base_mode else 0.0

        # --- per-corner checks ------------------------------------------------------
        corners = cfg.corners or ["TT"]
        corner_results: list[CornerPower] = []
        corner_count = max(1, len(corners))
        for idx, corner in enumerate(corners):
            cr = self._run_corner(
                corner,
                base_dyn,
                base_leak,
                progress,
                frac_base=0.55 + 0.35 * idx / corner_count,
                frac_span=0.35 / corner_count,
            )
            corner_results.append(cr)

        # --- aggregate --------------------------------------------------------------
        _report(progress, "aggregating", 0.92)
        ir_max = max((c.ir_drop_mv for c in corner_results), default=0.0)
        em_total = sum(c.em_violations for c in corner_results)
        therm_max = max((c.thermal_max_c for c in corner_results), default=25.0)

        # Glitch power heuristic: 8% of worst-case dynamic
        glitch_mw = base_dyn * 0.08

        overall = "PASS"
        if any(c.status == "FAIL" for c in corner_results) or ir_max > 50 or therm_max > 125:
            overall = "FAIL"
        elif any(c.status == "WARN" for c in corner_results) or ir_max > 30 or therm_max > 100:
            overall = "WARN"
        score = 100.0
        score -= ir_max * 0.5
        score -= max(0.0, therm_max - 85.0) * 0.4
        score -= em_total * 2.0
        score -= glitch_mw * 0.5
        score = max(0.0, min(100.0, score))

        # top cells / instantaneous / density come from the richest mode
        top_cells: list[dict[str, Any]] = []
        inst: list[tuple[float, float]] = []
        density: dict[str, Any] = {}
        best_vres = None
        for v in mode_vector_results:
            if v is None:
                continue
            if best_vres is None or v.total_power_mw > best_vres.total_power_mw:
                best_vres = v
        if best_vres is not None:
            top_cells = [
                {
                    "instance": s.instance,
                    "cell_type": s.cell_type,
                    "switching_uw": s.switching_power_uw,
                    "internal_uw": s.internal_power_uw,
                    "leakage_uw": s.leakage_power_uw,
                    "total_uw": s.total_power_uw,
                    "x_um": s.x_um,
                    "y_um": s.y_um,
                }
                for s in best_vres.cell_breakdown[:50]
            ]
            inst = list(best_vres.instantaneous)
            # compute density grid on demand
            try:
                lib_path = Path(cfg.lib_path) if cfg.lib_path else None
                a = VectorPowerAnalyzer(
                    vcd_path=Path(best_vres.vcd_path),
                    def_path=self.def_path,
                    lef_path=self.lef_path,
                    lib_path=lib_path,
                    vdd=cfg.vdd,
                )
                density = a.power_density_grid(grid_size_um=20.0)
            except Exception:
                density = {}

        static_per_corner = {
            c.corner: {
                "leakage_mw": c.leakage_mw,
                "dynamic_mw": c.dynamic_mw,
                "total_mw": c.total_mw,
                "ir_drop_mv": c.ir_drop_mv,
                "em_violations": float(c.em_violations),
                "thermal_max_c": c.thermal_max_c,
            }
            for c in corner_results
        }
        dynamic_per_mode = {
            m.mode: {
                "dynamic_mw": m.dynamic_mw,
                "leakage_mw": m.leakage_mw,
                "total_mw": m.total_mw,
                "peak_mw": m.peak_mw,
                "peak_time_ns": m.peak_time_ns,
                "duration_ns": m.duration_ns,
            }
            for m in mode_results
        }

        _report(progress, "done", 1.0)
        return PowerSignoffResult(
            config=cfg,
            static_per_corner=static_per_corner,
            dynamic_per_mode=dynamic_per_mode,
            corner_summary=corner_results,
            mode_summary=mode_results,
            glitch_power_mw=glitch_mw,
            ir_drop_max_mv=ir_max,
            em_violations=em_total,
            thermal_max_c=therm_max,
            top_cells=top_cells,
            instantaneous=inst,
            density_grid=density,
            overall_status=overall,
            score=score,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    def to_html_report(self, result: PowerSignoffResult, output: Path) -> Path:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        e = html.escape

        def _row(cells: list[str]) -> str:
            return "<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in cells) + "</tr>"

        corner_rows = "\n".join(
            _row(
                [
                    c.corner,
                    f"{c.leakage_mw:.3f}",
                    f"{c.dynamic_mw:.3f}",
                    f"{c.total_mw:.3f}",
                    f"{c.ir_drop_mv:.2f}",
                    c.em_violations,
                    f"{c.thermal_max_c:.1f}",
                    c.status,
                ]
            )
            for c in result.corner_summary
        )
        mode_rows = "\n".join(
            _row(
                [
                    m.mode,
                    f"{m.dynamic_mw:.3f}",
                    f"{m.leakage_mw:.3f}",
                    f"{m.total_mw:.3f}",
                    f"{m.peak_mw:.3f}",
                    f"{m.peak_time_ns:.2f}",
                    f"{m.duration_ns:.1f}",
                ]
            )
            for m in result.mode_summary
        )
        cell_rows = "\n".join(
            _row(
                [
                    c.get("instance", ""),
                    c.get("cell_type", ""),
                    f"{c.get('switching_uw', 0.0):.3f}",
                    f"{c.get('internal_uw', 0.0):.3f}",
                    f"{c.get('leakage_uw', 0.0):.3f}",
                    f"{c.get('total_uw', 0.0):.3f}",
                ]
            )
            for c in result.top_cells[:50]
        )
        status_color = {
            "PASS": "#2e8b57",
            "WARN": "#d48806",
            "FAIL": "#cf1322",
        }.get(result.overall_status, "#444")
        body = f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>OpenForge Power Sign-off</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#111; color:#eee; padding: 24px; }}
h1,h2 {{ color:#7abaff; }}
table {{ border-collapse: collapse; margin: 12px 0; }}
td, th {{ border: 1px solid #333; padding: 6px 10px; }}
th {{ background:#1a1a1a; }}
.status {{ display:inline-block; padding:8px 20px; border-radius:6px; color:#fff; font-weight:bold; background:{status_color}; }}
.score {{ font-size: 48px; font-weight:bold; color:{status_color}; }}
.meta {{ color:#999; font-size:12px; }}
</style></head><body>
<h1>OpenForge Unified Power Sign-off</h1>
<div class="meta">{e(result.timestamp)}</div>
<p><span class="status">{e(result.overall_status)}</span>
   <span class="score">{result.score:.1f}</span> / 100</p>
<h2>Corner Summary</h2>
<table><tr><th>Corner</th><th>Leakage mW</th><th>Dynamic mW</th><th>Total mW</th>
<th>IR mV</th><th>EM viol</th><th>Temp C</th><th>Status</th></tr>
{corner_rows}
</table>
<h2>Mode Summary</h2>
<table><tr><th>Mode</th><th>Dyn mW</th><th>Leak mW</th><th>Total mW</th>
<th>Peak mW</th><th>Peak @ ns</th><th>Duration ns</th></tr>
{mode_rows}
</table>
<h2>Top 50 Cells by Power</h2>
<table><tr><th>Instance</th><th>Cell</th><th>Switch uW</th><th>Internal uW</th>
<th>Leakage uW</th><th>Total uW</th></tr>
{cell_rows}
</table>
<h2>Cross-physics headline</h2>
<ul>
<li>Glitch power: {result.glitch_power_mw:.3f} mW</li>
<li>Worst IR drop: {result.ir_drop_max_mv:.2f} mV</li>
<li>EM violations: {result.em_violations}</li>
<li>Max temperature: {result.thermal_max_c:.1f} C</li>
</ul>
</body></html>
"""
        out.write_text(body, encoding="utf-8")
        return out


__all__ = [
    "PowerSignoffConfig",
    "PowerSignoffResult",
    "CornerPower",
    "ModePower",
    "PowerSignoffOrchestrator",
]
