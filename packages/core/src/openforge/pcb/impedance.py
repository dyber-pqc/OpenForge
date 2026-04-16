"""PCB impedance calculator and stackup validator.

Implements IPC-2141A (Hammerstad-Jensen) controlled impedance formulas
for microstrip, stripline, and coplanar traces, single-ended and
differential.

All dimensions are in millimetres; impedance in ohms.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

C0_MM_PER_NS = 299.792458  # speed of light in mm/ns


class StackupLayer(BaseModel):
    """A single physical layer in a PCB stackup."""

    name: str
    kind: Literal["signal", "plane", "dielectric", "mask", "silk", "paste"]
    thickness_mm: float
    material: str = "FR4"
    dielectric_constant: float | None = None
    loss_tangent: float | None = None
    copper_oz: float | None = None


class ImpedanceResult(BaseModel):
    """Result of a single impedance calculation."""

    impedance_ohm: float
    inductance_nh_per_mm: float
    capacitance_pf_per_mm: float
    propagation_ns_per_mm: float
    delay_ns_per_mm: float
    er_effective: float = Field(default=1.0)


# ----------------------------------------------------------------------
# Material presets (typical er @ 1 GHz, loss tangent)
MATERIAL_PRESETS: dict[str, dict[str, float]] = {
    "FR4": {"er": 4.4, "loss_tangent": 0.02},
    "FR4_HighTg": {"er": 4.3, "loss_tangent": 0.018},
    "Rogers4003C": {"er": 3.38, "loss_tangent": 0.0027},
    "Rogers4350B": {"er": 3.48, "loss_tangent": 0.0037},
    "Polyimide": {"er": 3.5, "loss_tangent": 0.008},
    "Megtron6": {"er": 3.4, "loss_tangent": 0.004},
    "copper": {"er": 1.0, "loss_tangent": 0.0},
}


def _effective_er_microstrip(w_mm: float, h_mm: float, er: float) -> float:
    """Hammerstad-Jensen effective dielectric constant for microstrip."""
    if h_mm <= 0:
        return er
    w_h = max(w_mm / h_mm, 1e-6)
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 / w_h) ** -0.5


def _z0_microstrip(w_mm: float, h_mm: float, er_eff: float) -> float:
    """IPC-2141A microstrip characteristic impedance."""
    if h_mm <= 0:
        return 0.0
    w_h = max(w_mm / h_mm, 1e-6)
    sqrt_eff = math.sqrt(er_eff)
    if w_h < 1.0:
        return (60.0 / sqrt_eff) * math.log(8.0 / w_h + w_h / 4.0)
    return (120.0 * math.pi) / (sqrt_eff * (w_h + 1.393 + 0.667 * math.log(w_h + 1.444)))


def _build_result(z0: float, er_eff: float) -> ImpedanceResult:
    """Build LC-derived fields from characteristic impedance and er_eff."""
    if z0 <= 0 or er_eff <= 0:
        return ImpedanceResult(
            impedance_ohm=0.0,
            inductance_nh_per_mm=0.0,
            capacitance_pf_per_mm=0.0,
            propagation_ns_per_mm=0.0,
            delay_ns_per_mm=0.0,
            er_effective=er_eff,
        )
    v_p_mm_per_ns = C0_MM_PER_NS / math.sqrt(er_eff)
    delay_ns_per_mm = 1.0 / v_p_mm_per_ns
    # Z0 = sqrt(L/C);  v = 1/sqrt(LC)
    # => L = Z0 / v   C = 1/(Z0 * v)
    l_nh_per_mm = z0 * delay_ns_per_mm  # ohm*ns/mm = nH/mm
    c_pf_per_mm = (delay_ns_per_mm / z0) * 1000.0  # ns/(ohm*mm) => pF/mm
    return ImpedanceResult(
        impedance_ohm=z0,
        inductance_nh_per_mm=l_nh_per_mm,
        capacitance_pf_per_mm=c_pf_per_mm,
        propagation_ns_per_mm=v_p_mm_per_ns,
        delay_ns_per_mm=delay_ns_per_mm,
        er_effective=er_eff,
    )


class ImpedanceCalculator:
    """IPC-2141A controlled impedance calculator."""

    @staticmethod
    def microstrip_se(width_mm: float, height_mm: float, t_mm: float, er: float) -> ImpedanceResult:
        """Single-ended microstrip (Hammerstad-Jensen, IPC-2141A)."""
        # Thickness correction (effective width grows with trace thickness)
        w_eff = width_mm
        if t_mm > 0 and height_mm > 0:
            w_eff = width_mm + (t_mm / math.pi) * (
                1.0 + math.log(2.0 * height_mm / max(t_mm, 1e-6))
            )
        er_eff = _effective_er_microstrip(w_eff, height_mm, er)
        z0 = _z0_microstrip(w_eff, height_mm, er_eff)
        return _build_result(z0, er_eff)

    @staticmethod
    def microstrip_diff(
        width_mm: float,
        gap_mm: float,
        height_mm: float,
        t_mm: float,
        er: float,
    ) -> ImpedanceResult:
        """Edge-coupled differential microstrip.

        Uses IPC-2141A correction: Zdiff = 2 * Zse * (1 - 0.48 * exp(-0.96 * s/h))
        """
        se = ImpedanceCalculator.microstrip_se(width_mm, height_mm, t_mm, er)
        s_h = gap_mm / max(height_mm, 1e-6)
        zdiff = 2.0 * se.impedance_ohm * (1.0 - 0.48 * math.exp(-0.96 * s_h))
        return _build_result(zdiff, se.er_effective)

    @staticmethod
    def stripline_se(
        width_mm: float,
        h1_mm: float,
        h2_mm: float,
        t_mm: float,
        er: float,
    ) -> ImpedanceResult:
        """Symmetric / offset stripline impedance (IPC-2141A)."""
        b = h1_mm + h2_mm + t_mm
        if b <= 0 or er <= 0:
            return _build_result(0.0, er)
        # Effective width correction for thickness
        w_eff = width_mm
        if t_mm > 0:
            x = t_mm / max(b, 1e-6)
            dw = (t_mm / math.pi) * (
                1.0
                - 0.5
                * math.log(
                    (x / (2.0 - x)) ** 2 + (0.0796 * x / (max(width_mm / b, 1e-6) + 1.1 * x)) ** 2
                )
            )
            w_eff = width_mm + dw
        denom = 0.8 * w_eff + t_mm
        if denom <= 0:
            return _build_result(0.0, er)
        z0 = (60.0 / math.sqrt(er)) * math.log(1.9 * b / max(denom, 1e-6))
        return _build_result(max(z0, 0.0), er)

    @staticmethod
    def stripline_diff(
        width_mm: float,
        gap_mm: float,
        h1_mm: float,
        h2_mm: float,
        t_mm: float,
        er: float,
    ) -> ImpedanceResult:
        """Edge-coupled symmetric differential stripline."""
        se = ImpedanceCalculator.stripline_se(width_mm, h1_mm, h2_mm, t_mm, er)
        b = h1_mm + h2_mm + t_mm
        s_b = gap_mm / max(b, 1e-6)
        zdiff = 2.0 * se.impedance_ohm * (1.0 - 0.347 * math.exp(-2.9 * s_b))
        return _build_result(zdiff, se.er_effective)

    @staticmethod
    def coplanar_se(
        width_mm: float,
        gap_mm: float,
        height_mm: float,
        t_mm: float,
        er: float,
    ) -> ImpedanceResult:
        """Grounded coplanar waveguide (Wheeler / Wadell approximation)."""
        if width_mm <= 0 or gap_mm <= 0 or height_mm <= 0:
            return _build_result(0.0, er)
        k = width_mm / (width_mm + 2.0 * gap_mm)
        kp = math.sqrt(max(1.0 - k * k, 1e-12))

        # K(k)/K(k') ratio via Hilberg approximation
        def _kk_ratio(kk: float) -> float:
            if kk < 1.0 / math.sqrt(2.0):
                kkp = math.sqrt(max(1.0 - kk * kk, 1e-12))
                return math.pi / math.log(2.0 * (1.0 + math.sqrt(kkp)) / (1.0 - math.sqrt(kkp)))
            return math.log(2.0 * (1.0 + math.sqrt(kk)) / (1.0 - math.sqrt(kk))) / math.pi

        k1 = math.tanh(math.pi * width_mm / (4.0 * height_mm)) / math.tanh(
            math.pi * (width_mm + 2.0 * gap_mm) / (4.0 * height_mm)
        )
        k1p = math.sqrt(max(1.0 - k1 * k1, 1e-12))
        rk = _kk_ratio(k)
        rk1 = _kk_ratio(k1)
        er_eff = (1.0 + er * (rk1 / max(rk, 1e-12))) / (1.0 + (rk1 / max(rk, 1e-12)))
        z0 = (60.0 * math.pi / math.sqrt(er_eff)) * (1.0 / max(rk + rk1, 1e-12))
        # clamp to a reasonable range
        return _build_result(max(z0, 0.0), er_eff)
        # (kp, k1p referenced for completeness; Wadell full form requires them)
        _ = (kp, k1p)

    @staticmethod
    def find_width_for_impedance(
        target_ohm: float,
        height_mm: float,
        er: float = 4.4,
        kind: str = "microstrip",
        t_mm: float = 0.035,
    ) -> float:
        """Bisection solve for trace width to hit a target impedance.

        kind: microstrip | stripline
        """
        if target_ohm <= 0 or height_mm <= 0:
            return 0.0
        lo, hi = 0.02, 20.0 * max(height_mm, 0.1)

        def _z(w: float) -> float:
            if kind == "stripline":
                return ImpedanceCalculator.stripline_se(
                    w, height_mm, height_mm, t_mm, er
                ).impedance_ohm
            return ImpedanceCalculator.microstrip_se(w, height_mm, t_mm, er).impedance_ohm

        # z decreases monotonically with w
        z_lo = _z(lo)
        z_hi = _z(hi)
        if z_lo < target_ohm:
            return lo
        if z_hi > target_ohm:
            return hi
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            zm = _z(mid)
            if abs(zm - target_ohm) < 0.01:
                return mid
            if zm > target_ohm:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


class StackupValidator:
    """Validation / reporting over a list of StackupLayer entries."""

    def __init__(self, stackup: list[StackupLayer]) -> None:
        self.stackup = stackup

    def total_thickness_mm(self) -> float:
        return sum(float(l.thickness_mm) for l in self.stackup)

    def signal_layer_count(self) -> int:
        return sum(1 for l in self.stackup if l.kind == "signal")

    def plane_layer_count(self) -> int:
        return sum(1 for l in self.stackup if l.kind == "plane")

    def dielectric_layer_count(self) -> int:
        return sum(1 for l in self.stackup if l.kind == "dielectric")

    def is_balanced(self) -> bool:
        """Symmetric stackup check (warpage mitigation).

        The layer list must be a palindrome of (kind, thickness) pairs.
        """
        if not self.stackup:
            return True
        seq = [(l.kind, round(l.thickness_mm, 6)) for l in self.stackup]
        return seq == list(reversed(seq))

    def report(self) -> dict:
        return {
            "total_thickness_mm": self.total_thickness_mm(),
            "layer_count": len(self.stackup),
            "signal_layers": self.signal_layer_count(),
            "plane_layers": self.plane_layer_count(),
            "dielectric_layers": self.dielectric_layer_count(),
            "balanced": self.is_balanced(),
            "layers": [l.model_dump() for l in self.stackup],
        }


def default_4layer_stackup() -> list[StackupLayer]:
    """A typical 1.6 mm 4-layer FR-4 stackup (JLCPCB JLC04161H-7628)."""
    return [
        StackupLayer(name="F.SilkS", kind="silk", thickness_mm=0.015, material="ink"),
        StackupLayer(name="F.Mask", kind="mask", thickness_mm=0.020, material="soldermask"),
        StackupLayer(
            name="F.Cu",
            kind="signal",
            thickness_mm=0.035,
            material="copper",
            dielectric_constant=1.0,
            copper_oz=1.0,
        ),
        StackupLayer(
            name="Prepreg",
            kind="dielectric",
            thickness_mm=0.2104,
            material="FR4",
            dielectric_constant=4.4,
            loss_tangent=0.02,
        ),
        StackupLayer(
            name="In1.Cu", kind="plane", thickness_mm=0.0152, material="copper", copper_oz=0.5
        ),
        StackupLayer(
            name="Core",
            kind="dielectric",
            thickness_mm=1.065,
            material="FR4",
            dielectric_constant=4.6,
            loss_tangent=0.02,
        ),
        StackupLayer(
            name="In2.Cu", kind="plane", thickness_mm=0.0152, material="copper", copper_oz=0.5
        ),
        StackupLayer(
            name="Prepreg",
            kind="dielectric",
            thickness_mm=0.2104,
            material="FR4",
            dielectric_constant=4.4,
            loss_tangent=0.02,
        ),
        StackupLayer(
            name="B.Cu",
            kind="signal",
            thickness_mm=0.035,
            material="copper",
            dielectric_constant=1.0,
            copper_oz=1.0,
        ),
        StackupLayer(name="B.Mask", kind="mask", thickness_mm=0.020, material="soldermask"),
        StackupLayer(name="B.SilkS", kind="silk", thickness_mm=0.015, material="ink"),
    ]


__all__ = [
    "StackupLayer",
    "ImpedanceResult",
    "ImpedanceCalculator",
    "StackupValidator",
    "MATERIAL_PRESETS",
    "default_4layer_stackup",
]
