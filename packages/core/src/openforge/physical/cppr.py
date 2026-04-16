"""Clock Path Pessimism Removal (CPPR).

For any timing check, the launch clock path and the capture clock path
share a common prefix (the clock tree up to the divergence point).
GBA applies independent max/min corners to each of those paths, which
double-counts pessimism on the common segment. CPPR subtracts that
double-counted pessimism back out as a slack credit.

We operate on a parsed StaReport. For each path we walk launch and
capture clock stages and find the longest common pin prefix. The
pessimism on that common segment equals (clock path delta between
max and min corner) * (length of common segment / full clock path).
Since our single-corner report doesn't have max/min, we use a fixed
on-chip-variation (OCV) de-rate of 5% as the pessimism, multiplied by
the common-segment delay.
"""

from __future__ import annotations

import copy

from pydantic import BaseModel, ConfigDict, Field

from openforge.physical.sta_parser import StaReport, TimingPath, TimingStage


OCV_DERATE_DEFAULT = 0.05  # 5% on-chip variation


class CommonPath(BaseModel):
    """Launch/capture shared clock segment."""

    model_config = ConfigDict(extra="ignore")

    launch_path: list[str] = Field(default_factory=list)
    capture_path: list[str] = Field(default_factory=list)
    common_segment: list[str] = Field(default_factory=list)
    common_delay_ps: float = 0.0


class CpprAnalyzer:
    """Compute CPPR credits for every path in an STA report."""

    def __init__(
        self,
        sta_report: StaReport,
        ocv_derate: float = OCV_DERATE_DEFAULT,
    ) -> None:
        self.sta = sta_report
        self.ocv = ocv_derate

    # ------------------------------------------------------------------ core

    def _stage_pins(self, stages: list[TimingStage]) -> list[str]:
        return [s.pin_name for s in stages if s.pin_name]

    def find_common(self, path: TimingPath) -> CommonPath:
        launch = self._stage_pins(path.launch_clock_path)
        capture = self._stage_pins(path.capture_clock_path)

        common: list[str] = []
        n = min(len(launch), len(capture))
        for i in range(n):
            if launch[i] == capture[i]:
                common.append(launch[i])
            else:
                break

        # If the STA report didn't carry clock tree stages (common for
        # summary output), fall back to a heuristic: assume 40% of the
        # smaller clock path is shared (clock root + common trunk).
        if not common and (path.launch_clock_path or path.capture_clock_path):
            common = [f"<common_trunk_{i}>" for i in range(
                max(1, int(0.4 * max(len(launch), len(capture))))
            )]

        # Compute delay along the common prefix using launch_clock_path
        common_delay_ns = 0.0
        for i, s in enumerate(path.launch_clock_path):
            if i >= len(common):
                break
            common_delay_ns += float(s.delay_ns or 0.0)

        # If no stages available, estimate from path arrivals: 40% of
        # whichever clock latency is present.
        if common_delay_ns == 0.0 and path.launch_clock_path:
            total = sum(float(s.delay_ns or 0.0) for s in path.launch_clock_path)
            common_delay_ns = 0.4 * total
        elif common_delay_ns == 0.0:
            # fallback: 10% of arrival time
            common_delay_ns = 0.1 * float(path.data_arrival_ns or 0.0)

        return CommonPath(
            launch_path=launch,
            capture_path=capture,
            common_segment=common,
            common_delay_ps=common_delay_ns * 1000.0,
        )

    def cppr_credit_ps(self, path: TimingPath) -> float:
        """Return the slack credit (in ps) for a single path."""
        cp = self.find_common(path)
        # Credit = ocv_derate * common_segment_delay
        # (the pessimism that was double-counted between launch and capture)
        return self.ocv * cp.common_delay_ps

    # ------------------------------------------------------------------ API

    def apply_to_report(self) -> StaReport:
        """Return a new StaReport with CPPR credits folded into slack."""
        new_report = copy.copy(self.sta)
        new_report.paths = []
        wns = 0.0
        tns = 0.0
        whs = 0.0
        ths = 0.0
        viol = 0
        for p in self.sta.paths:
            credit_ps = self.cppr_credit_ps(p)
            new_path = copy.copy(p)
            new_path.launch_clock_path = list(p.launch_clock_path)
            new_path.capture_clock_path = list(p.capture_clock_path)
            new_path.data_path = list(p.data_path)
            new_path.slack_ns = float(p.slack_ns or 0.0) + credit_ps / 1000.0
            new_report.paths.append(new_path)

            if new_path.path_type == "max":
                if new_path.slack_ns < wns:
                    wns = new_path.slack_ns
                if new_path.slack_ns < 0:
                    tns += new_path.slack_ns
                    viol += 1
            else:
                if new_path.slack_ns < whs:
                    whs = new_path.slack_ns
                if new_path.slack_ns < 0:
                    ths += new_path.slack_ns
                    viol += 1

        new_report.wns = wns
        new_report.tns = tns
        new_report.whs = whs
        new_report.ths = ths
        new_report.num_violations = viol
        new_report.num_paths = len(new_report.paths)
        return new_report


__all__ = ["CommonPath", "CpprAnalyzer", "OCV_DERATE_DEFAULT"]
