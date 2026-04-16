"""Power side-channel analysis simulator.

Generates simulated power traces from gate-level activity, then runs
TVLA (Test Vector Leakage Assessment) and CPA (Correlation Power Analysis).

This module is designed for rapid pre-silicon side-channel vulnerability
assessment. It does not model transistor-level effects but captures
switching activity correlated with data values - sufficient to flag
first-order leakage.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PowerTrace:
    """A single simulated power trace."""

    samples: list[float]
    sample_rate_ns: float
    label: int = 0
    seed: int = 0
    input_bytes: bytes = b""
    metadata: dict = field(default_factory=dict)

    @property
    def num_samples(self) -> int:
        return len(self.samples)

    @property
    def duration_ns(self) -> float:
        return self.num_samples * self.sample_rate_ns

    def downsample(self, factor: int) -> PowerTrace:
        new_samples = [
            sum(self.samples[i : i + factor]) / factor
            for i in range(0, len(self.samples), factor)
        ]
        return PowerTrace(
            samples=new_samples,
            sample_rate_ns=self.sample_rate_ns * factor,
            label=self.label,
            seed=self.seed,
            input_bytes=self.input_bytes,
        )

    def normalize(self) -> PowerTrace:
        if not self.samples:
            return self
        mn = min(self.samples)
        mx = max(self.samples)
        if mx == mn:
            return self
        norm = [(s - mn) / (mx - mn) for s in self.samples]
        return PowerTrace(
            samples=norm,
            sample_rate_ns=self.sample_rate_ns,
            label=self.label,
            seed=self.seed,
            input_bytes=self.input_bytes,
        )


@dataclass
class TvlaResult:
    """Result of a TVLA fixed-vs-random test."""

    t_statistic: list[float]
    threshold: float = 4.5
    leakage_points: list[int] = field(default_factory=list)
    max_t: float = 0.0
    leak_score: int = 0
    n_traces_fixed: int = 0
    n_traces_random: int = 0

    @property
    def has_leakage(self) -> bool:
        return self.leak_score > 0

    def summary(self) -> str:
        return (
            f"TVLA: max |t|={self.max_t:.2f}, "
            f"{len(self.leakage_points)} leaking points, "
            f"leak_score={self.leak_score}/100, "
            f"n_fixed={self.n_traces_fixed}, n_random={self.n_traces_random}"
        )


@dataclass
class CpaResult:
    """Result of a correlation power analysis attack."""

    correlations: dict[int, float]
    best_candidate: int
    best_correlation: float
    n_traces: int

    def ranked(self) -> list[tuple[int, float]]:
        return sorted(self.correlations.items(), key=lambda kv: -abs(kv[1]))


@dataclass
class GateActivity:
    """Recorded switching activity for a single gate."""

    cell_type: str
    switches: int = 0
    inputs_seen: int = 0
    name: str = ""


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class PowerTraceSimulator:
    """Simulates power consumption from gate-level activity.

    The model: each gate has a per-switch energy cost. Given an input
    vector, we simulate the netlist (or synthesize a simple activity
    profile based on Hamming weight/distance of the inputs), accumulate
    the switching energy per cycle, and add Gaussian noise.
    """

    def __init__(self, technology: str = "sky130"):
        self.tech = technology
        # Per-cell switching energy in joules (rough estimates, 1.8V class)
        self._cell_power: dict[str, float] = {
            "AND": 1.2e-15,
            "NAND": 1.0e-15,
            "OR": 1.3e-15,
            "NOR": 1.1e-15,
            "XOR": 1.8e-15,
            "XNOR": 1.8e-15,
            "DFF": 3.5e-15,
            "LATCH": 2.0e-15,
            "INV": 0.6e-15,
            "BUF": 0.7e-15,
            "MUX2": 1.5e-15,
            "ADD": 4.0e-15,
            "MULT": 12.0e-15,
            "SBOX": 8.0e-15,
        }
        self._rng = random.Random()

    def set_cell_power(self, cell: str, joules: float) -> None:
        self._cell_power[cell] = joules

    # -- Netlist helpers -----------------------------------------------------

    def _load_netlist(self, netlist_json: Path) -> list[dict]:
        if not netlist_json.exists():
            return []
        try:
            data = json.loads(netlist_json.read_text(encoding="utf-8"))
        except Exception:
            return []
        modules = data.get("modules", {}) or {}
        cells: list[dict] = []
        for _mod_name, mod in modules.items():
            mod_cells = mod.get("cells", {}) or {}
            for name, c in mod_cells.items():
                cells.append({"name": name, "type": c.get("type", "UNKNOWN")})
        return cells

    def _cell_energy(self, cell_type: str) -> float:
        t = cell_type.upper()
        for key, energy in self._cell_power.items():
            if key in t:
                return energy
        return 1.0e-15  # default

    # -- Activity model ------------------------------------------------------

    def _hamming_weight(self, data: bytes) -> int:
        return sum(bin(b).count("1") for b in data)

    def _hamming_distance(self, a: bytes, b: bytes) -> int:
        n = min(len(a), len(b))
        return sum(bin(a[i] ^ b[i]).count("1") for i in range(n))

    def _simulate_cycle_activity(
        self,
        cells: list[dict],
        input_bytes: bytes,
        prev_bytes: bytes,
        cycle: int,
    ) -> float:
        """Compute the total switching energy for a single cycle.

        Uses a lightweight model: the number of switching gates is
        proportional to the Hamming distance between current and previous
        inputs, scaled by gate count.
        """
        if not cells:
            # Synthesize a fake netlist from input width
            width = max(1, len(input_bytes) * 8)
            cells = [{"name": f"g{i}", "type": "XOR"} for i in range(width)]
        total = 0.0
        hd = self._hamming_distance(input_bytes, prev_bytes) if prev_bytes else self._hamming_weight(input_bytes)
        activity_ratio = min(1.0, (hd + 1) / max(1, len(input_bytes) * 8))
        # Cycle-dependent modulation (e.g. pipeline warmup)
        cycle_mod = 0.5 + 0.5 * math.cos(cycle / 13.0)
        for cell in cells:
            e = self._cell_energy(cell["type"])
            # Each gate switches with probability `activity_ratio`
            if self._rng.random() < activity_ratio:
                total += e * cycle_mod
        return total

    # -- Public API ----------------------------------------------------------

    def simulate_trace(
        self,
        netlist_json: Path,
        input_vector: bytes,
        clock_period_ns: float = 10.0,
        num_cycles: int = 100,
        noise_amplitude: float = 0.05,
        seed: int = 0,
        label: int = 0,
    ) -> PowerTrace:
        """Generate a simulated power trace for a given input vector."""
        self._rng.seed(seed)
        cells = self._load_netlist(netlist_json) if netlist_json else []
        samples: list[float] = []
        prev = b""
        base_power = 1e-12  # quiescent
        # Data-dependent leakage term: sensitive byte drives per-cycle energy
        sensitive = input_vector[:16] if input_vector else b"\x00"
        for cycle in range(num_cycles):
            # Rotate sensitive bytes so different bytes leak in different cycles
            if sensitive:
                rot = bytes(
                    sensitive[(i + cycle) % len(sensitive)] for i in range(len(sensitive))
                )
            else:
                rot = b""
            energy = self._simulate_cycle_activity(cells, rot, prev, cycle)
            prev = rot
            # Add leakage proportional to Hamming weight (this is what TVLA detects)
            hw = self._hamming_weight(rot)
            leak = hw * 1.5e-15
            sample = base_power + energy + leak
            # Gaussian noise
            noise = self._rng.gauss(0.0, noise_amplitude * (base_power + energy + 1e-15))
            sample += noise
            samples.append(sample)
        return PowerTrace(
            samples=samples,
            sample_rate_ns=clock_period_ns,
            label=label,
            seed=seed,
            input_bytes=input_vector,
        )

    def collect_traces(
        self,
        netlist_json: Path,
        n_traces: int = 1000,
        random_seed: int = 0,
        on_progress: Callable[[int, int], None] | None = None,
        clock_period_ns: float = 10.0,
        num_cycles: int = 100,
        input_length: int = 16,
        fixed_input: bytes | None = None,
        noise_amplitude: float = 0.05,
    ) -> list[PowerTrace]:
        """Collect N power traces with random (or fixed) inputs."""
        master = random.Random(random_seed)
        traces: list[PowerTrace] = []
        for i in range(n_traces):
            if fixed_input is not None:
                inp = fixed_input
                label = 0
            else:
                inp = bytes(master.randint(0, 255) for _ in range(input_length))
                label = 1
            trace = self.simulate_trace(
                netlist_json=netlist_json,
                input_vector=inp,
                clock_period_ns=clock_period_ns,
                num_cycles=num_cycles,
                noise_amplitude=noise_amplitude,
                seed=master.randint(0, 2**31 - 1),
                label=label,
            )
            traces.append(trace)
            if on_progress is not None and (i % max(1, n_traces // 20) == 0):
                on_progress(i + 1, n_traces)
        if on_progress is not None:
            on_progress(n_traces, n_traces)
        return traces


# ---------------------------------------------------------------------------
# TVLA
# ---------------------------------------------------------------------------


class TvlaAnalyzer:
    """Test Vector Leakage Assessment - first-order TVLA."""

    def __init__(self, threshold: float = 4.5):
        self.threshold = threshold

    # -- Welch's t-test ------------------------------------------------------

    @staticmethod
    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    @staticmethod
    def _variance(xs: list[float], mean: float | None = None) -> float:
        if len(xs) < 2:
            return 0.0
        m = mean if mean is not None else TvlaAnalyzer._mean(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)

    @staticmethod
    def _welch_t(
        a: list[float], b: list[float]
    ) -> float:
        na = len(a)
        nb = len(b)
        if na < 2 or nb < 2:
            return 0.0
        ma = TvlaAnalyzer._mean(a)
        mb = TvlaAnalyzer._mean(b)
        va = TvlaAnalyzer._variance(a, ma)
        vb = TvlaAnalyzer._variance(b, mb)
        denom = math.sqrt(va / na + vb / nb)
        if denom == 0.0:
            return 0.0
        return (ma - mb) / denom

    def fixed_vs_random_test(
        self,
        traces_fixed: list[PowerTrace],
        traces_random: list[PowerTrace],
    ) -> TvlaResult:
        """Run a TVLA fixed-vs-random t-test.

        For each sample index, compute Welch's t-test between the fixed and
        random groups. Points where |t| > threshold indicate statistically
        significant first-order leakage.
        """
        if not traces_fixed or not traces_random:
            return TvlaResult(t_statistic=[], threshold=self.threshold)
        n_samples = min(t.num_samples for t in traces_fixed + traces_random)
        t_stats: list[float] = []
        leak_points: list[int] = []
        for i in range(n_samples):
            a = [t.samples[i] for t in traces_fixed]
            b = [t.samples[i] for t in traces_random]
            t = self._welch_t(a, b)
            t_stats.append(t)
            if abs(t) > self.threshold:
                leak_points.append(i)
        max_t = max((abs(t) for t in t_stats), default=0.0)
        # Map max |t| to 0..100 "leak score"
        score = 0 if max_t <= self.threshold else min(100, int((max_t - self.threshold) * 10))
        return TvlaResult(
            t_statistic=t_stats,
            threshold=self.threshold,
            leakage_points=leak_points,
            max_t=max_t,
            leak_score=score,
            n_traces_fixed=len(traces_fixed),
            n_traces_random=len(traces_random),
        )

    # -- CPA -----------------------------------------------------------------

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float:
        n = min(len(xs), len(ys))
        if n < 2:
            return 0.0
        mx = sum(xs[:n]) / n
        my = sum(ys[:n]) / n
        num = 0.0
        dx2 = 0.0
        dy2 = 0.0
        for i in range(n):
            dx = xs[i] - mx
            dy = ys[i] - my
            num += dx * dy
            dx2 += dx * dx
            dy2 += dy * dy
        den = math.sqrt(dx2 * dy2)
        if den == 0.0:
            return 0.0
        return num / den

    def correlation_attack(
        self,
        traces: list[PowerTrace],
        hypothesized_intermediate: Callable[[bytes, int], int],
        key_candidates: list[int],
    ) -> CpaResult:
        """Run a CPA (Correlation Power Analysis) attack.

        Args:
            traces: list of collected traces.
            hypothesized_intermediate: function (input, key) -> intermediate
                value whose Hamming weight is hypothesized to be leaked.
            key_candidates: candidate key bytes to rank.

        Returns:
            CpaResult with ranked correlations.
        """
        if not traces:
            return CpaResult(correlations={}, best_candidate=-1, best_correlation=0.0, n_traces=0)
        n_samples = min(t.num_samples for t in traces)
        correlations: dict[int, float] = {}
        # For each key, compute correlation with the max of per-sample correlations
        for k in key_candidates:
            model = [
                float(bin(hypothesized_intermediate(t.input_bytes, k)).count("1"))
                for t in traces
            ]
            best_for_key = 0.0
            for i in range(n_samples):
                sample_col = [t.samples[i] for t in traces]
                r = self._pearson(model, sample_col)
                if abs(r) > abs(best_for_key):
                    best_for_key = r
            correlations[k] = best_for_key
        best = max(correlations.items(), key=lambda kv: abs(kv[1]))
        return CpaResult(
            correlations=correlations,
            best_candidate=best[0],
            best_correlation=best[1],
            n_traces=len(traces),
        )

    # -- Reporting -----------------------------------------------------------

    def summary_report(self, result: TvlaResult) -> str:
        lines: list[str] = []
        lines.append("# TVLA Report")
        lines.append("")
        lines.append(f"- Traces (fixed): {result.n_traces_fixed}")
        lines.append(f"- Traces (random): {result.n_traces_random}")
        lines.append(f"- Threshold |t|: {result.threshold}")
        lines.append(f"- Max |t|: {result.max_t:.3f}")
        lines.append(f"- Leaking sample points: {len(result.leakage_points)}")
        lines.append(f"- Leak score: {result.leak_score}/100")
        lines.append("")
        if result.has_leakage:
            lines.append(
                "RESULT: Statistically significant first-order leakage detected."
            )
        else:
            lines.append("RESULT: No significant first-order leakage detected.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Leakage models (for CPA)
# ---------------------------------------------------------------------------


def aes_sbox_leakage(input_bytes: bytes, key: int) -> int:
    """AES S-box leakage model: first byte XOR key -> S-box output."""
    if not input_bytes:
        return 0
    sbox = _AES_SBOX
    return sbox[(input_bytes[0] ^ key) & 0xFF]


def xor_leakage(input_bytes: bytes, key: int) -> int:
    """Simple XOR leakage: first byte XOR key."""
    if not input_bytes:
        return 0
    return (input_bytes[0] ^ key) & 0xFF


_AES_SBOX = [
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
]


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------


def run_tvla_campaign(
    netlist_json: Path,
    n_traces: int = 1000,
    clock_period_ns: float = 10.0,
    num_cycles: int = 100,
    fixed_input: bytes | None = None,
    threshold: float = 4.5,
    on_progress: Callable[[int, int], None] | None = None,
    seed: int = 0,
) -> TvlaResult:
    """Run a full TVLA campaign: collect traces, analyze, return result."""
    sim = PowerTraceSimulator()
    fi = fixed_input or (b"\xA5" * 16)
    half = n_traces // 2
    fixed_traces = sim.collect_traces(
        netlist_json,
        n_traces=half,
        random_seed=seed,
        clock_period_ns=clock_period_ns,
        num_cycles=num_cycles,
        fixed_input=fi,
        on_progress=None,
    )
    random_traces = sim.collect_traces(
        netlist_json,
        n_traces=half,
        random_seed=seed + 1,
        clock_period_ns=clock_period_ns,
        num_cycles=num_cycles,
        fixed_input=None,
        on_progress=on_progress,
    )
    analyzer = TvlaAnalyzer(threshold=threshold)
    return analyzer.fixed_vs_random_test(fixed_traces, random_traces)


def save_traces(traces: list[PowerTrace], path: Path) -> None:
    """Save traces to a JSON file."""
    data = [
        {
            "samples": t.samples,
            "sample_rate_ns": t.sample_rate_ns,
            "label": t.label,
            "seed": t.seed,
            "input_bytes": t.input_bytes.hex(),
        }
        for t in traces
    ]
    path.write_text(json.dumps(data), encoding="utf-8")


def load_traces(path: Path) -> list[PowerTrace]:
    """Load traces from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        PowerTrace(
            samples=list(d["samples"]),
            sample_rate_ns=d["sample_rate_ns"],
            label=d.get("label", 0),
            seed=d.get("seed", 0),
            input_bytes=bytes.fromhex(d.get("input_bytes", "")),
        )
        for d in data
    ]


__all__ = [
    "PowerTrace",
    "TvlaResult",
    "CpaResult",
    "GateActivity",
    "PowerTraceSimulator",
    "TvlaAnalyzer",
    "aes_sbox_leakage",
    "xor_leakage",
    "run_tvla_campaign",
    "save_traces",
    "load_traces",
]
