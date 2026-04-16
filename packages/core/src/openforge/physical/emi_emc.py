"""EMI/EMC pre-screening (SIwave replacement).

This is NOT a 3D solver - it provides quick estimates for:
- Spectral content from clock frequencies and harmonics
- Radiated emission magnitude based on di/dt and trace lengths
- FCC Part 15 / CISPR 22 Class B compliance flags

Useful as a design-stage warning system before running a real EMC scan.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------


@dataclass
class EmiSource:
    name: str
    frequency_mhz: float
    amplitude_v: float
    location: tuple[float, float]
    radiated_power_uw: float = 0.0


@dataclass
class EmiResult:
    sources: list[EmiSource]
    near_field_max_v_per_m: float
    far_field_at_10m_uv_per_m: float
    fcc_class_b_compliant: bool
    ce_compliant: bool
    worst_frequency_mhz: float
    worst_emission_db_uv_per_m: float
    spectrum: list[tuple[float, float]] = field(default_factory=list)
    runtime_s: float = 0.0

    @property
    def is_compliant(self) -> bool:
        return self.fcc_class_b_compliant and self.ce_compliant


# ----------------------------------------------------------------------------
# Analyzer
# ----------------------------------------------------------------------------


class EmiEmcAnalyzer:
    """Simplified EMI/EMC pre-screening."""

    def __init__(self):
        # FCC Part 15 Class B limits at 3 m, in dB(uV/m).
        # Frequencies are upper bounds of each segment in MHz.
        self.fcc_limits_dbuv = {
            30: 40.0,
            88: 40.0,
            216: 43.5,
            960: 46.0,
            1000: 54.0,
            6000: 54.0,
        }
        # CISPR 22 Class B limits at 10 m
        self.ce_limits_dbuv = {
            30: 30.0,
            230: 30.0,
            1000: 37.0,
            6000: 47.0,
        }

    # ------------------------------------------------------------------
    def analyze(
        self,
        clock_frequencies_mhz: list[float],
        signal_currents: dict[str, float],
        trace_lengths: dict[str, float],
        package_inductance_nh: float = 5.0,
    ) -> EmiResult:
        """Estimate the EMI emission spectrum and check FCC/CE limits."""
        start = time.time()
        sources: list[EmiSource] = []
        spectrum: list[tuple[float, float]] = []

        # 1. Build harmonic spectrum from each clock
        for fclk in clock_frequencies_mhz:
            for f, mag in self.compute_spectrum(fclk, harmonics=12):
                spectrum.append((f, mag))
                sources.append(
                    EmiSource(
                        name=f"clk{fclk:.0f}M_{f:.0f}M",
                        frequency_mhz=f,
                        amplitude_v=mag,
                        location=(0.0, 0.0),
                        radiated_power_uw=mag * mag * 1e3,
                    )
                )

        # 2. Add radiated contribution from di/dt across trace antennas
        for net, current in signal_currents.items():
            length = trace_lengths.get(net, 1.0)
            # treat trace as small dipole; effective height ~ length/2
            for fclk in clock_frequencies_mhz:
                # f -> wavelength (m); 300/f_MHz
                wavelength = 300.0 / max(fclk, 0.1)
                # crude di/dt -> radiated voltage estimate
                ldi_dt = package_inductance_nh * 1e-9 * current * fclk * 1e6 * 2 * math.pi
                # Field at 3 m from a short dipole
                e_3m = abs(ldi_dt) * (length / max(wavelength, 1e-3)) / 3.0
                # Convert V/m to uV/m
                e_uv = e_3m * 1e6
                if e_uv <= 0:
                    continue
                e_db = 20.0 * math.log10(max(e_uv, 1e-3))
                spectrum.append((fclk, e_db))

        # 3. Combine: convert linear-V values to dBuV/m on a dipole-at-3m basis
        spectrum_db: list[tuple[float, float]] = []
        for f, val in spectrum:
            if val <= 0:
                continue
            # Already in dB if it's large; otherwise convert from V to uV/m
            if val > 100.0:
                spectrum_db.append((f, val))
            else:
                e_field = val * 1e6  # V -> uV
                db = 20.0 * math.log10(max(e_field, 1e-3))
                spectrum_db.append((f, db))

        spectrum_db.sort(key=lambda x: x[0])

        # 4. Determine the worst harmonic and compliance
        worst_db = -1e9
        worst_f = 0.0
        for f, db in spectrum_db:
            if db > worst_db:
                worst_db = db
                worst_f = f

        fcc_ok = self.check_fcc_class_b(spectrum_db)
        ce_ok = self.check_ce_class_b(spectrum_db)

        # 5. Approximate near-field max (V/m at 0.3 m)
        near_max = 0.0
        for s in sources:
            near_max = max(near_max, s.amplitude_v * 3.3)
        far_at_10m_uv = (10 ** (worst_db / 20.0)) * (3.0 / 10.0) if worst_db > 0 else 0.0

        runtime = time.time() - start
        return EmiResult(
            sources=sources,
            near_field_max_v_per_m=near_max,
            far_field_at_10m_uv_per_m=far_at_10m_uv,
            fcc_class_b_compliant=fcc_ok,
            ce_compliant=ce_ok,
            worst_frequency_mhz=worst_f,
            worst_emission_db_uv_per_m=worst_db,
            spectrum=spectrum_db,
            runtime_s=runtime,
        )

    # ------------------------------------------------------------------
    def compute_spectrum(
        self, clock_mhz: float, harmonics: int = 10
    ) -> list[tuple[float, float]]:
        """Compute the harmonic spectrum of a square-wave clock signal.

        For a 50% duty cycle square wave, only odd harmonics exist with
        amplitude 4*A/(n*pi).
        """
        out: list[tuple[float, float]] = []
        a = 1.0  # normalized amplitude
        for n in range(1, harmonics + 1):
            if n % 2 == 0:
                continue
            f = clock_mhz * n
            mag = (4.0 * a) / (n * math.pi)
            out.append((f, mag))
        return out

    # ------------------------------------------------------------------
    def check_fcc_class_b(self, spectrum: list[tuple[float, float]]) -> bool:
        for f, db in spectrum:
            limit = self._lookup_limit(f, self.fcc_limits_dbuv)
            if db > limit:
                return False
        return True

    def check_ce_class_b(self, spectrum: list[tuple[float, float]]) -> bool:
        for f, db in spectrum:
            limit = self._lookup_limit(f, self.ce_limits_dbuv)
            if db > limit:
                return False
        return True

    def _lookup_limit(self, freq_mhz: float, table: dict[int, float]) -> float:
        last = 100.0
        for upper, val in sorted(table.items()):
            if freq_mhz <= upper:
                return val
            last = val
        return last

    # ------------------------------------------------------------------
    def get_violations(
        self, result: EmiResult, standard: str = "fcc"
    ) -> list[tuple[float, float, float]]:
        """Return list of (freq, emission_db, limit_db) violations."""
        table = self.fcc_limits_dbuv if standard == "fcc" else self.ce_limits_dbuv
        out: list[tuple[float, float, float]] = []
        for f, db in result.spectrum:
            limit = self._lookup_limit(f, table)
            if db > limit:
                out.append((f, db, limit))
        return out

    # ------------------------------------------------------------------
    def margin_db(self, result: EmiResult) -> float:
        """Return the worst-case margin (positive == passing)."""
        worst_margin = 1e9
        for f, db in result.spectrum:
            limit = self._lookup_limit(f, self.fcc_limits_dbuv)
            m = limit - db
            if m < worst_margin:
                worst_margin = m
        if worst_margin == 1e9:
            return 0.0
        return worst_margin

    # ------------------------------------------------------------------
    def generate_emi_report(self, result: EmiResult, output: Path) -> Path:
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("OpenForge EMI/EMC Pre-screening Report")
        lines.append("=" * 70)
        lines.append(f"Sources analyzed:    {len(result.sources)}")
        lines.append(f"Spectrum points:     {len(result.spectrum)}")
        lines.append(f"Worst frequency:     {result.worst_frequency_mhz:.1f} MHz")
        lines.append(f"Worst emission:      {result.worst_emission_db_uv_per_m:.1f} dBuV/m")
        lines.append(f"Near-field max:      {result.near_field_max_v_per_m:.3f} V/m")
        lines.append(f"Far-field @10m:      {result.far_field_at_10m_uv_per_m:.2f} uV/m")
        lines.append("")
        lines.append("Compliance")
        lines.append("-" * 70)
        lines.append(
            f"FCC Part 15 Class B: {'PASS' if result.fcc_class_b_compliant else 'FAIL'}"
        )
        lines.append(
            f"CISPR 22 Class B:    {'PASS' if result.ce_compliant else 'FAIL'}"
        )
        lines.append(f"Worst margin:        {self.margin_db(result):+.2f} dB")
        lines.append("")
        lines.append("Top 15 spectral lines")
        lines.append("-" * 70)
        for i, (f, db) in enumerate(
            sorted(result.spectrum, key=lambda x: x[1], reverse=True)[:15], 1
        ):
            limit = self._lookup_limit(f, self.fcc_limits_dbuv)
            mark = "FAIL" if db > limit else "ok"
            lines.append(
                f"  {i:2d}. {f:8.2f} MHz  {db:6.1f} dBuV/m  "
                f"(limit {limit:5.1f}) [{mark}]"
            )
        lines.append("")
        lines.append(f"Runtime: {result.runtime_s:.3f} s")
        lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines))
        return output


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def estimate_trace_length(net_pins: Iterable[tuple[float, float]]) -> float:
    """Half-perimeter wirelength estimate for a net's pin set."""
    pins = list(net_pins)
    if not pins:
        return 0.0
    xs = [p[0] for p in pins]
    ys = [p[1] for p in pins]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def quick_emi_screen(clock_mhz: float, max_current_a: float = 0.05) -> bool:
    """Single-clock convenience screen.  Returns True if likely compliant."""
    a = EmiEmcAnalyzer()
    res = a.analyze(
        clock_frequencies_mhz=[clock_mhz],
        signal_currents={"clk": max_current_a},
        trace_lengths={"clk": 0.01},
    )
    return res.is_compliant
