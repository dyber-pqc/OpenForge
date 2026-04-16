"""Crosstalk-aware delay and noise.

Given a parsed SPEF (from either a real tool or our ``extractor``) and
an STA report, this module identifies aggressor nets for every victim,
computes a delta delay / delta slew contribution from the coupled
capacitance, and can fold that back into the STA report as an updated
slack value.

Formulas follow the Miller-based approximation used by fast STA
engines (PrimeTime-SI, Tempus): for each aggressor the effective
victim cap increases by

    C_eff = C_coupling * (1 + miller_factor)

where ``miller_factor`` depends on whether the aggressor switches in
the same or opposite direction (2x for opposing, 0 for same). The
added delay is then

    delta_delay = R_victim_driver * C_eff

and a small glitch voltage is estimated via the coupling divider.
"""

from __future__ import annotations

import copy
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from openforge.format.spef_parser import SpefFile, SpefNet
from openforge.physical.sta_parser import StaReport, TimingPath


MILLER_OPPOSING = 2.0
MILLER_SAME = 0.0
MILLER_UNKNOWN = 1.0

DEFAULT_DRIVER_RES_OHM = 250.0  # typical sky130 std-cell drive strength
DEFAULT_SUPPLY_V = 1.8


class CrosstalkAggressor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    aggressor_net: str
    coupling_cap_ff: float
    switching_window_ns: tuple[float, float] = (0.0, 0.0)
    switching_direction: str = "rise"  # 'rise' | 'fall' | 'unknown'


class CrosstalkResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    victim_net: str
    aggressors: list[CrosstalkAggressor] = Field(default_factory=list)
    delta_delay_ps: float = 0.0
    delta_slew_ps: float = 0.0
    glitch_voltage_v: float = 0.0
    total_coupling_ff: float = 0.0


class CrosstalkAnalyzer:
    """Crosstalk-aware delay adjustment."""

    def __init__(
        self,
        spef_file: SpefFile | str | Path,
        sta_report: StaReport | None = None,
        driver_res_ohm: float = DEFAULT_DRIVER_RES_OHM,
        supply_v: float = DEFAULT_SUPPLY_V,
    ) -> None:
        if isinstance(spef_file, (str, Path)):
            self.spef = SpefFile.parse(spef_file)
        else:
            self.spef = spef_file
        self.sta = sta_report
        self.driver_res = driver_res_ohm
        self.supply_v = supply_v

        # index SPEF nets by name
        self._by_name: dict[str, SpefNet] = {n.name: n for n in self.spef.nets}

        # Precompute a map of net -> switching window from the STA report
        self._switch_windows: dict[str, tuple[float, float, str]] = {}
        if sta_report is not None:
            self._build_switch_windows(sta_report)

    def _build_switch_windows(self, report: StaReport) -> None:
        for p in report.paths:
            cum = 0.0
            for s in p.data_path:
                cum += float(s.delay_ns or 0.0)
                if not s.pin_name:
                    continue
                # heuristic: derive a net name from the pin
                net = s.pin_name.rsplit("/", 1)[0] if "/" in s.pin_name else s.pin_name
                slew = float(s.slew_ns or 0.05)
                start = max(0.0, cum - slew)
                end = cum + slew
                direction = s.edge or "rise"
                prev = self._switch_windows.get(net)
                if prev is None:
                    self._switch_windows[net] = (start, end, direction)
                else:
                    self._switch_windows[net] = (
                        min(prev[0], start),
                        max(prev[1], end),
                        prev[2],
                    )

    # ------------------------------------------------------------------ API

    def find_aggressors(
        self,
        victim_net: str,
        switching_window: tuple[float, float] | None = None,
    ) -> list[CrosstalkAggressor]:
        """Return aggressor nets coupled to ``victim_net`` that switch in an
        overlapping window."""
        n = self._by_name.get(victim_net)
        if n is None:
            return []
        aggressors: list[CrosstalkAggressor] = []
        for other_net, cap_pf in n.aggressors().items():
            cap_ff = cap_pf * 1000.0
            win_a = self._switch_windows.get(other_net)
            if switching_window is not None and win_a is not None:
                vs, ve = switching_window
                as_, ae, _ = win_a
                if ae < vs or as_ > ve:
                    continue  # no overlap
            direction = win_a[2] if win_a else "unknown"
            sw = (win_a[0], win_a[1]) if win_a else (0.0, 0.0)
            aggressors.append(
                CrosstalkAggressor(
                    aggressor_net=other_net,
                    coupling_cap_ff=cap_ff,
                    switching_window_ns=sw,
                    switching_direction=direction,
                )
            )
        return aggressors

    def analyze_net(self, victim_net: str) -> CrosstalkResult:
        n = self._by_name.get(victim_net)
        if n is None:
            return CrosstalkResult(victim_net=victim_net)

        victim_win = self._switch_windows.get(victim_net)
        sw = (victim_win[0], victim_win[1]) if victim_win else None
        victim_dir = victim_win[2] if victim_win else "rise"

        aggs = self.find_aggressors(victim_net, sw)

        total_coup_ff = 0.0
        c_eff_ff = 0.0
        for a in aggs:
            total_coup_ff += a.coupling_cap_ff
            if a.switching_direction == "unknown":
                mf = MILLER_UNKNOWN
            elif a.switching_direction == victim_dir:
                mf = MILLER_SAME
            else:
                mf = MILLER_OPPOSING
            c_eff_ff += a.coupling_cap_ff * (1.0 + mf)

        # delta_delay = R_driver * C_eff.
        # R in Ohm, C in F -> delay in s. Convert to ps.
        c_eff_f = c_eff_ff * 1e-15
        delta_delay_s = self.driver_res * c_eff_f
        delta_delay_ps = delta_delay_s * 1e12

        # slew increases ~ 0.69 * R * C_eff
        delta_slew_ps = 0.69 * delta_delay_ps

        # Glitch voltage: capacitive divider. V_glitch = V * C_c / (C_c + C_victim).
        victim_cap_pf = n.total_cap_pf
        victim_cap_ff = victim_cap_pf * 1000.0
        if victim_cap_ff > 0:
            glitch = self.supply_v * (total_coup_ff / (total_coup_ff + victim_cap_ff))
        else:
            glitch = 0.0

        return CrosstalkResult(
            victim_net=victim_net,
            aggressors=aggs,
            delta_delay_ps=delta_delay_ps,
            delta_slew_ps=delta_slew_ps,
            glitch_voltage_v=glitch,
            total_coupling_ff=total_coup_ff,
        )

    def analyze_top_n(self, n: int = 100) -> list[CrosstalkResult]:
        """Analyze the N nets with the largest coupling exposure."""
        scored: list[tuple[float, str]] = []
        for net in self.spef.nets:
            coup = sum(net.aggressors().values())
            if coup > 0:
                scored.append((coup, net.name))
        scored.sort(reverse=True)
        out: list[CrosstalkResult] = []
        for _score, name in scored[:n]:
            out.append(self.analyze_net(name))
        return out

    def apply_xtalk_to_sta(self, sta_report: StaReport) -> StaReport:
        """Add delta-delay contributions to stages whose nets have xtalk."""
        # Precompute per-net delta_delay_ps for anything we've ever touched
        net_delta: dict[str, float] = {}
        for net in self.spef.nets:
            if not net.aggressors():
                continue
            res = self.analyze_net(net.name)
            if res.delta_delay_ps > 0:
                net_delta[net.name] = res.delta_delay_ps

        new_report = copy.copy(sta_report)
        new_report.paths = []
        wns = 0.0
        tns = 0.0
        viol = 0
        for p in sta_report.paths:
            new_path = copy.copy(p)
            new_path.data_path = [copy.copy(s) for s in p.data_path]
            added_ns = 0.0
            for s in new_path.data_path:
                net_guess = (
                    s.pin_name.rsplit("/", 1)[0]
                    if "/" in s.pin_name
                    else s.pin_name
                )
                dd = net_delta.get(net_guess)
                if dd:
                    s.delay_ns = float(s.delay_ns or 0.0) + dd / 1000.0
                    added_ns += dd / 1000.0
            new_path.data_arrival_ns = float(p.data_arrival_ns or 0.0) + added_ns
            new_path.slack_ns = float(p.slack_ns or 0.0) - added_ns
            new_report.paths.append(new_path)

            if new_path.path_type == "max":
                if new_path.slack_ns < wns:
                    wns = new_path.slack_ns
                if new_path.slack_ns < 0:
                    tns += new_path.slack_ns
                    viol += 1

        new_report.wns = wns
        new_report.tns = tns
        new_report.num_violations = viol
        new_report.num_paths = len(new_report.paths)
        return new_report


__all__ = [
    "CrosstalkAggressor",
    "CrosstalkResult",
    "CrosstalkAnalyzer",
]
