"""Monte Carlo statistical static timing analysis.

Pure numpy. Each sample perturbs every data-path stage's delay by a
global + local gaussian term (sigma_global and sigma_local), then
recomputes path arrival and slack. The distribution of slack across
all samples gives mean, std, and yield = P(slack >= 0).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

    from openforge.physical.sta_parser import StaReport, TimingPath


class ProcessVariation(BaseModel):
    """Global + local process variation sigmas (fractional)."""

    model_config = ConfigDict(extra="ignore")

    sigma_global: float = 0.05  # 5% global variation
    sigma_local: float = 0.03   # 3% local per-stage variation
    rng_seed: int | None = 42


class TimingDistribution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path_id: str
    startpoint: str = ""
    endpoint: str = ""
    mean_slack: float = 0.0
    std_slack: float = 0.0
    yield_pct: float = 100.0  # P(slack >= 0) * 100
    p01_slack: float = 0.0
    p99_slack: float = 0.0
    samples: list[float] = Field(default_factory=list)


class MonteCarloTiming:
    """Monte Carlo timing over an StaReport."""

    def __init__(
        self,
        sta_report: StaReport,
        variation: ProcessVariation | None = None,
        samples: int = 1000,
    ) -> None:
        self.sta = sta_report
        self.variation = variation or ProcessVariation()
        self.samples = int(samples)
        self._rng = np.random.default_rng(self.variation.rng_seed)
        self._results: list[TimingDistribution] = []

    # ------------------------------------------------------------------ core

    def _perturb_path_slack(self, path: TimingPath) -> np.ndarray:
        """Return an array of perturbed slack samples for a single path."""
        delays = np.array(
            [float(s.delay_ns or 0.0) for s in path.data_path],
            dtype=np.float64,
        )
        if delays.size == 0:
            delays = np.array([float(path.data_arrival_ns or 0.0)])
        n = self.samples
        sig_g = self.variation.sigma_global
        sig_l = self.variation.sigma_local

        # Global factor per sample (same for every stage on that sample)
        global_factor = self._rng.normal(1.0, sig_g, size=n)
        # Local factor per stage per sample (independent)
        local_factor = self._rng.normal(
            1.0, sig_l, size=(n, delays.size)
        )
        # Perturbed delays: delays * local_factor (row-wise) * global_factor
        perturbed = delays[np.newaxis, :] * local_factor
        perturbed *= global_factor[:, np.newaxis]
        perturbed = np.clip(perturbed, 0.0, None)

        # New arrival = sum across stages
        new_arrival = perturbed.sum(axis=1)

        # Baseline arrival (nominal) and required
        base_arrival = float(path.data_arrival_ns or delays.sum())
        base_slack = float(path.slack_ns or 0.0)

        # slack = base_slack - (new_arrival - base_arrival)
        slack_samples = base_slack - (new_arrival - base_arrival)
        return slack_samples

    def run(
        self,
        paths: Iterable[TimingPath] | None = None,
    ) -> list[TimingDistribution]:
        if paths is None:
            paths = self.sta.paths
        out: list[TimingDistribution] = []
        for i, p in enumerate(paths):
            samples = self._perturb_path_slack(p)
            yield_pct = float((samples >= 0).mean() * 100.0)
            dist = TimingDistribution(
                path_id=f"path_{i}_{p.endpoint or '?'}",
                startpoint=p.startpoint,
                endpoint=p.endpoint,
                mean_slack=float(samples.mean()),
                std_slack=float(samples.std()),
                yield_pct=yield_pct,
                p01_slack=float(np.percentile(samples, 1)),
                p99_slack=float(np.percentile(samples, 99)),
                samples=samples.tolist(),
            )
            out.append(dist)
        self._results = out
        return out

    # ------------------------------------------------------------------ query

    def yield_estimate(self) -> float:
        """Global yield = P(all paths meet)."""
        if not self._results:
            self.run()
        if not self._results:
            return 100.0
        # Each path has an independent sample array of the same length
        arr = np.array([r.samples for r in self._results])  # (P, N)
        all_met = (arr >= 0).all(axis=0)
        return float(all_met.mean() * 100.0)

    def sigma_corner_report(
        self, sigmas: list[float] | None = None
    ) -> dict[str, float]:
        """Return per-sigma worst slack across all paths."""
        if sigmas is None:
            sigmas = [1.0, 2.0, 3.0, 4.5, 6.0]
        if not self._results:
            self.run()
        out: dict[str, float] = {}
        for s in sigmas:
            # Translate sigma to percentile (one-sided tail)
            # N-sigma ~ (0.5 - 0.5*erf(s/sqrt(2))) percentile
            from math import erf, sqrt
            p = 100.0 * (0.5 - 0.5 * erf(s / sqrt(2.0)))
            worst = min(
                (float(np.percentile(r.samples, p)) for r in self._results),
                default=0.0,
            )
            out[f"{s:.1f}sigma"] = worst
        return out


__all__ = [
    "ProcessVariation",
    "TimingDistribution",
    "MonteCarloTiming",
]
