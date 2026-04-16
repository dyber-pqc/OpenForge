"""Path-based timing analysis (PBA).

Graph-based STA (GBA) takes the worst arrival time per pin as the
starting point for every fanout stage, which produces pessimistic path
delays because no single transition can cause all the worst cases
simultaneously. PBA re-propagates the actual transition along each
critical path, removing that pessimism stage by stage.

Here we operate on a parsed ``StaReport`` (graph-based numbers) and
compute a PBA-corrected delay per path.

If an ``ExtractionResult`` mapping is supplied, we additionally scale
stage delays by the ratio of extracted net cap to the cap the STA
report saw (pin cap column). This is a rough wire-load correction so
PBA results reflect the freshly extracted parasitics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

    from openforge.physical.sta_parser import StaReport, TimingPath


class PathDelay(BaseModel):
    """PBA vs GBA delay summary for one path."""

    model_config = ConfigDict(extra="ignore")

    path_id: str
    startpoint: str = ""
    endpoint: str = ""
    gba_delay: float = 0.0  # ns
    pba_delay: float = 0.0  # ns
    pessimism_reduction_ps: float = 0.0
    slack_gba_ns: float = 0.0
    slack_pba_ns: float = 0.0
    stages: list[dict] = Field(default_factory=list)


class PbaAnalyzer:
    """Path-based analysis over a parsed STA report."""

    def __init__(
        self,
        sta_report: StaReport,
        parasitic_results: dict | None = None,
    ) -> None:
        self.sta = sta_report
        # parasitic_results keyed by net name -> ExtractionResult-like
        self.parasitics = parasitic_results or {}

    # ------------------------------------------------------------------ API

    def analyze_path(self, path: TimingPath, index: int = 0) -> PathDelay:
        path_id = f"path_{index}_{path.endpoint or '?'}"
        gba_delay = float(path.data_arrival_ns or 0.0)

        # PBA: walk the data path stage by stage and recompute a
        # less-pessimistic cumulative delay. The heuristic:
        #
        #   pba_stage_delay = gba_stage_delay - pessimism_per_stage
        #
        # pessimism_per_stage is a small fraction of the stage's transition
        # time. When libraries report GBA delay they latch onto the worst
        # input slew, so subtracting a slew-proportional term approximates
        # what a real PBA engine would do (which re-derives delay from the
        # actually-arriving slew).
        pba_delay = 0.0
        stage_dicts: list[dict] = []
        for s in path.data_path:
            if not s.cell_type and not s.pin_name:
                continue
            gba_d = float(s.delay_ns or 0.0)

            # pessimism per stage: 15% of slew contribution, capped at 30% of delay
            slew_pess = 0.15 * float(s.slew_ns or 0.0)
            gba_cap = 0.3 * abs(gba_d)
            pess_ns = min(slew_pess, gba_cap) if gba_d > 0 else 0.0

            # Wire-load correction from extracted parasitics
            wire_scale = 1.0
            if self.parasitics and s.pin_name:
                net_guess = s.pin_name.rsplit("/", 1)[0] if "/" in s.pin_name else s.pin_name
                ext = self.parasitics.get(net_guess)
                if ext is not None and s.cap_pf > 0:
                    ext_cap_pf = getattr(ext, "total_cap_pf", 0.0)
                    if ext_cap_pf > 0:
                        wire_scale = 0.5 + 0.5 * (ext_cap_pf / max(s.cap_pf, 1e-6))
                        wire_scale = max(0.7, min(1.5, wire_scale))

            pba_d = max(0.0, (gba_d - pess_ns) * wire_scale)
            pba_delay += pba_d

            stage_dicts.append(
                {
                    "pin": s.pin_name,
                    "cell": s.cell_type,
                    "gba_ns": gba_d,
                    "pba_ns": pba_d,
                    "pessimism_ps": pess_ns * 1000.0,
                    "slew_ns": s.slew_ns,
                    "cap_pf": s.cap_pf,
                }
            )

        if pba_delay == 0.0:
            pba_delay = gba_delay * 0.97  # baseline 3% credit if no breakdown

        pess_ps = (gba_delay - pba_delay) * 1000.0
        slack_pba = float(path.slack_ns or 0.0) + (pess_ps / 1000.0)

        return PathDelay(
            path_id=path_id,
            startpoint=path.startpoint,
            endpoint=path.endpoint,
            gba_delay=gba_delay,
            pba_delay=pba_delay,
            pessimism_reduction_ps=pess_ps,
            slack_gba_ns=float(path.slack_ns or 0.0),
            slack_pba_ns=slack_pba,
            stages=stage_dicts,
        )

    def analyze_all_critical_paths(
        self, paths: Iterable[TimingPath] | None = None
    ) -> list[PathDelay]:
        paths_iter = list(paths) if paths is not None else list(self.sta.paths)
        out: list[PathDelay] = []
        for i, p in enumerate(paths_iter):
            out.append(self.analyze_path(p, i))
        return out

    def total_pessimism_reduction_ps(self, results: list[PathDelay] | None = None) -> float:
        if results is None:
            results = self.analyze_all_critical_paths()
        return sum(r.pessimism_reduction_ps for r in results)


__all__ = ["PathDelay", "PbaAnalyzer"]
