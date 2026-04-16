"""Approximate analytic STA "what-if" engine.

Real sign-off STA requires re-running OpenSTA / PrimeTime. That round-trip
takes minutes at best. This module provides *instant* previews by scaling
arrival / slack values of an existing :class:`StaReport` based on linear
approximations that EDA-savvy engineers use in their heads all the time:

* Changing the clock period shifts *required arrival time* for every path
  in that clock domain: ``new_slack = old_slack + (new_period - old_period)``.
* Changing driver strength on matching cells scales the cell delay of those
  stages by ``1/scale`` (stronger drivers are faster).
* Changing wire load scales the RC contribution of matching nets by ``scale``.
* Changing OCV derate multiplies cell delays for paths on that corner.
* Changing fanout re-scales load-dependent delay (approximately linear in
  cap_pf) for the cells driving those nets.

All operations return a list of :class:`WhatIfResult` records showing how the
slack of each affected path changes. :meth:`StaWhatIf.apply` returns a brand
new :class:`StaReport` with every change applied (useful for feeding a panel
or exporting an SDC patch).
"""

from __future__ import annotations

import copy
import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from openforge.physical.sta_parser import StaReport, TimingPath

ChangeKind = Literal[
    "clock_period",
    "driver_strength",
    "wire_load",
    "derate",
    "fanout",
]


class WhatIfChange(BaseModel):
    """A single parameter tweak to apply to a report."""

    kind: ChangeKind
    target: str  # clock name, cell name pattern, net pattern, corner name...
    old_value: float
    new_value: float


class WhatIfResult(BaseModel):
    """The impact of a change on a single timing path."""

    path: str  # "startpoint -> endpoint"
    original_slack: float
    new_slack: float
    delta: float


@dataclass
class _PathView:
    """Mutable scratch copy we modify during ``apply``."""

    path: TimingPath

    @property
    def pid(self) -> str:
        return f"{self.path.startpoint} -> {self.path.endpoint}"


class StaWhatIf:
    """Analytic what-if analyzer around a :class:`StaReport`."""

    def __init__(self, report: StaReport):
        self.original = report
        self._working = self._clone(report)

    # ------------------------------------------------------------------
    # Public knobs
    # ------------------------------------------------------------------

    def change_clock_period(self, clock: str, new_period_ns: float) -> list[WhatIfResult]:
        """Change the period of ``clock``.

        For setup (``max``) paths the slack delta is ``+delta_period``; for
        hold (``min``) paths the slack is unaffected by period to first order,
        so we leave it alone.
        """
        old_period = self._period_of(clock)
        delta = new_period_ns - old_period
        out: list[WhatIfResult] = []
        for p in self._working.paths:
            if not self._path_uses_clock(p, clock):
                continue
            original = p.slack_ns
            if p.path_type == "max":
                p.slack_ns = original + delta
                p.data_required_ns += delta
            out.append(self._result(p, original))
        self._update_clock_period(clock, new_period_ns)
        self._recompute_summary(self._working)
        return out

    def change_driver_strength(self, cell_pattern: str, scale: float) -> list[WhatIfResult]:
        """Scale effective cell delay for any stage whose cell_type matches
        ``cell_pattern`` (glob) by ``1/scale``.

        ``scale=2.0`` doubles the drive strength and therefore halves cell
        delay on the matching stages. Paths become faster -> slack improves
        for setup, worsens for hold.
        """
        if scale <= 0:
            raise ValueError("scale must be positive")
        factor = 1.0 / scale
        out: list[WhatIfResult] = []
        for p in self._working.paths:
            saved = 0.0
            for st in p.data_path:
                if st.cell_type and fnmatch.fnmatchcase(st.cell_type, cell_pattern):
                    change = st.delay_ns * (factor - 1.0)
                    st.delay_ns += change
                    saved += change
            if saved == 0.0:
                continue
            original = p.slack_ns
            if p.path_type == "max":  # setup
                p.slack_ns = original - saved  # saved is negative => slack up
                p.data_arrival_ns += saved
            else:  # hold
                p.slack_ns = original + saved
                p.data_arrival_ns += saved
            out.append(self._result(p, original))
        self._recompute_summary(self._working)
        return out

    def change_wire_load(self, net_pattern: str, scale: float) -> list[WhatIfResult]:
        """Scale net RC contribution for nets matching ``net_pattern``.

        We treat the wire contribution per stage as the fraction of delay that
        is *not* cell-driven (i.e. stages with no cell_type). For stages that
        do have a cell_type we take 20% of the delay as wire load -- a
        reasonable rule of thumb for sub-micron nodes.
        """
        out: list[WhatIfResult] = []
        for p in self._working.paths:
            delta = 0.0
            for st in p.data_path:
                if not fnmatch.fnmatchcase(st.pin_name, net_pattern):
                    continue
                wire_frac = 1.0 if not st.cell_type else 0.2
                wire_delay = st.delay_ns * wire_frac
                change = wire_delay * (scale - 1.0)
                st.delay_ns += change
                delta += change
            if delta == 0.0:
                continue
            original = p.slack_ns
            if p.path_type == "max":
                p.slack_ns = original - delta
            else:
                p.slack_ns = original + delta
            p.data_arrival_ns += delta
            out.append(self._result(p, original))
        self._recompute_summary(self._working)
        return out

    def change_derate(self, corner: str, new_derate: float) -> list[WhatIfResult]:
        """Apply a new OCV derate factor to paths on ``corner``.

        The derate multiplies every cell delay on matching paths.
        """
        if new_derate <= 0:
            raise ValueError("derate must be positive")
        out: list[WhatIfResult] = []
        for p in self._working.paths:
            if corner and p.corner and p.corner != corner:
                continue
            original = p.slack_ns
            delta = 0.0
            for st in p.data_path:
                if st.cell_type:
                    change = st.delay_ns * (new_derate - 1.0)
                    st.delay_ns += change
                    delta += change
            if delta == 0.0:
                continue
            if p.path_type == "max":
                p.slack_ns = original - delta
            else:
                p.slack_ns = original + delta
            p.data_arrival_ns += delta
            out.append(self._result(p, original))
        self._recompute_summary(self._working)
        return out

    def change_fanout(self, cell_pattern: str, scale: float) -> list[WhatIfResult]:
        """Scale effective fanout load on matching stages.

        Load-dependent delay is approximately linear in cap_pf at the stage
        output, so we scale the cell delay contribution by a load factor
        derived from ``scale``. A ``scale`` of 2.0 means 2x fanout, which
        roughly adds ~20% delay to the driving stage.
        """
        if scale <= 0:
            raise ValueError("scale must be positive")
        load_factor = 1.0 + 0.2 * (scale - 1.0)
        out: list[WhatIfResult] = []
        for p in self._working.paths:
            delta = 0.0
            for st in p.data_path:
                if st.cell_type and fnmatch.fnmatchcase(st.cell_type, cell_pattern):
                    change = st.delay_ns * (load_factor - 1.0)
                    st.delay_ns += change
                    delta += change
            if delta == 0.0:
                continue
            original = p.slack_ns
            if p.path_type == "max":
                p.slack_ns = original - delta
            else:
                p.slack_ns = original + delta
            p.data_arrival_ns += delta
            out.append(self._result(p, original))
        self._recompute_summary(self._working)
        return out

    # ------------------------------------------------------------------
    # Apply a list of changes to a fresh copy
    # ------------------------------------------------------------------

    def apply(self, changes: list[WhatIfChange]) -> StaReport:
        """Apply ``changes`` to a fresh copy of the original report."""
        # Reset working copy
        self._working = self._clone(self.original)
        for change in changes:
            if change.kind == "clock_period":
                self.change_clock_period(change.target, change.new_value)
            elif change.kind == "driver_strength":
                self.change_driver_strength(change.target, change.new_value)
            elif change.kind == "wire_load":
                self.change_wire_load(change.target, change.new_value)
            elif change.kind == "derate":
                self.change_derate(change.target, change.new_value)
            elif change.kind == "fanout":
                self.change_fanout(change.target, change.new_value)
        return self._clone(self._working)

    # ------------------------------------------------------------------
    # Current-state accessors (useful to panels showing a live preview)
    # ------------------------------------------------------------------

    @property
    def working(self) -> StaReport:
        return self._working

    def reset(self) -> None:
        self._working = self._clone(self.original)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clone(report: StaReport) -> StaReport:
        return copy.deepcopy(report)

    def _period_of(self, clock: str) -> float:
        for c in self._working.clocks:
            if c.name == clock:
                return c.period_ns
        return 0.0

    def _update_clock_period(self, clock: str, new_period: float) -> None:
        for c in self._working.clocks:
            if c.name == clock:
                c.period_ns = new_period

    @staticmethod
    def _path_uses_clock(p: TimingPath, clock: str) -> bool:
        return p.endpoint_clock == clock or p.startpoint_clock == clock

    @staticmethod
    def _result(p: TimingPath, original: float) -> WhatIfResult:
        return WhatIfResult(
            path=f"{p.startpoint} -> {p.endpoint}",
            original_slack=original,
            new_slack=p.slack_ns,
            delta=p.slack_ns - original,
        )

    @staticmethod
    def _recompute_summary(report: StaReport) -> None:
        setup = [p for p in report.paths if p.path_type == "max"]
        hold = [p for p in report.paths if p.path_type == "min"]
        report.wns = min((p.slack_ns for p in setup), default=0.0)
        report.tns = sum(min(p.slack_ns, 0.0) for p in setup)
        report.whs = min((p.slack_ns for p in hold), default=0.0)
        report.ths = sum(min(p.slack_ns, 0.0) for p in hold)
        report.num_violations = sum(1 for p in report.paths if p.slack_ns < 0)
