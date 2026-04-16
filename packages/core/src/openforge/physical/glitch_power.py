"""Glitch power analyser.

Reads a VCD (via :class:`openforge.format.waveform.Waveform`) and
identifies spurious transition pairs whose pulse width is below the
user-supplied threshold.  These glitches dissipate real dynamic power
(``E = 0.5 * C * V^2`` per transition) but do not contribute to any
meaningful logic state change, so they are a prime candidate for design
optimisation.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from openforge.format.waveform import Waveform, WaveTransition

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class GlitchEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    signal: str
    time_ns: float
    duration_ns: float
    energy_pj: float = 0.0


class GlitchPowerResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_glitch_power_mw: float
    total_energy_pj: float
    glitch_count: int
    simulation_duration_ns: float
    top_glitchy_signals: list[tuple[str, int, float]] = Field(default_factory=list)
    events_by_signal: dict[str, list[GlitchEvent]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Analyser
# ---------------------------------------------------------------------------


class GlitchPowerAnalyzer:
    """Detect glitches and estimate their power contribution."""

    def __init__(self, vcd_path: str | Path) -> None:
        self.vcd_path = Path(vcd_path)
        self.waveform: Waveform = Waveform.parse_vcd(self.vcd_path)
        self._events: dict[str, list[GlitchEvent]] = {}

    # ------------------------------------------------------------------ time

    def _tick_to_ns(self, tick: int) -> float:
        return tick * self.waveform.timescale_ps / 1000.0

    # ------------------------------------------------------------------ api

    def detect_glitches(self, min_pulse_width_ns: float = 0.5) -> list[GlitchEvent]:
        """Find transition pairs (H-L-H or L-H-L) inside ``min_pulse_width_ns``.

        A glitch is defined as *three* transitions at times t1 < t2 < t3
        where the net returns to its pre-t1 value by t3 and the middle
        pulse width ``t3 - t1`` is below the threshold.
        """
        all_events: list[GlitchEvent] = []
        self._events.clear()
        for sig_name, trans in self.waveform.data.items():
            if not trans or len(trans) < 3:
                continue
            events: list[GlitchEvent] = []
            history: list[WaveTransition] = []
            for t in trans:
                history.append(t)
                if len(history) < 3:
                    continue
                t_old, t_mid, t_new = history[-3], history[-2], history[-1]
                w_ns = self._tick_to_ns(t_new.time - t_old.time)
                v_old = _normalise_value(t_old.value)
                v_mid = _normalise_value(t_mid.value)
                v_new = _normalise_value(t_new.value)
                if (
                    v_old == v_new
                    and v_old != v_mid
                    and v_old in (0, 1)
                    and w_ns > 0.0
                    and w_ns < min_pulse_width_ns
                ):
                    events.append(
                        GlitchEvent(
                            signal=sig_name,
                            time_ns=self._tick_to_ns(t_old.time),
                            duration_ns=w_ns,
                        )
                    )
            if events:
                self._events[sig_name] = events
                all_events.extend(events)
        return all_events

    def estimate_power(
        self,
        load_caps_ff: dict[str, float] | None = None,
        vdd: float = 1.8,
        default_cap_ff: float = 4.0,
    ) -> GlitchPowerResult:
        if not self._events:
            self.detect_glitches()
        load_caps_ff = load_caps_ff or {}
        duration_ns = self._tick_to_ns(self.waveform.end_time) or 1.0
        total_energy_pj = 0.0
        total_events = 0
        per_sig: list[tuple[str, int, float]] = []
        for sig, events in self._events.items():
            c_ff = load_caps_ff.get(sig, default_cap_ff)
            # One glitch = two transitions → two C*V^2 events
            energy_pj_per_event = 2 * 0.5 * c_ff * 1e-3 * (vdd**2)
            # C is in fF → C*V^2 = fF*V^2 = fJ = 1e-3 pJ
            sig_energy = 0.0
            for ev in events:
                ev.energy_pj = energy_pj_per_event
                sig_energy += energy_pj_per_event
            total_energy_pj += sig_energy
            total_events += len(events)
            per_sig.append((sig, len(events), sig_energy))
        per_sig.sort(key=lambda r: -r[1])
        power_mw = total_energy_pj / max(1e-6, duration_ns)  # pJ/ns == mW
        return GlitchPowerResult(
            total_glitch_power_mw=power_mw,
            total_energy_pj=total_energy_pj,
            glitch_count=total_events,
            simulation_duration_ns=duration_ns,
            top_glitchy_signals=per_sig[:25],
            events_by_signal=dict(self._events),
        )

    def classify_signals(self) -> dict[str, str]:
        """Classify each signal as 'clean' / 'glitchy' / 'pathological'."""
        classes: dict[str, str] = {}
        for sig, _trans in self.waveform.data.items():
            n_glitch = len(self._events.get(sig, []))
            if n_glitch == 0:
                classes[sig] = "clean"
            elif n_glitch < 5:
                classes[sig] = "glitchy"
            else:
                classes[sig] = "pathological"
        return classes


def _normalise_value(v: int | str) -> int | str:
    if isinstance(v, int):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("1", "h"):
        return 1
    if s in ("0", "l"):
        return 0
    return s  # x/z/etc.


__all__ = [
    "GlitchEvent",
    "GlitchPowerResult",
    "GlitchPowerAnalyzer",
]
