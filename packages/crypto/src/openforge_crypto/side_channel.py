"""Side-channel simulation with power models and statistical tests.

Provides Hamming weight / Hamming distance power models and implements
TVLA (Test Vector Leakage Assessment) and CPA (Correlation Power Analysis)
for pre-silicon leakage evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class PowerTrace:
    """A single simulated power trace."""

    samples: NDArray[np.float64]
    plaintext: NDArray[np.uint8]
    key: NDArray[np.uint8]
    label: str = ""


@dataclass(slots=True)
class TVLAResult:
    """Result of a TVLA (Welch's t-test) leakage assessment."""

    t_statistic: NDArray[np.float64]
    threshold: float = 4.5
    num_traces_group0: int = 0
    num_traces_group1: int = 0

    @property
    def leaking_samples(self) -> NDArray[np.bool_]:
        """Boolean mask of sample indices that exceed the TVLA threshold."""
        return np.abs(self.t_statistic) > self.threshold

    @property
    def max_t_value(self) -> float:
        return float(np.max(np.abs(self.t_statistic)))

    @property
    def is_leaking(self) -> bool:
        return bool(np.any(self.leaking_samples))


@dataclass(slots=True)
class CPAResult:
    """Result of a CPA (Correlation Power Analysis) attack."""

    correlation_matrix: NDArray[np.float64]
    best_key_byte: int
    best_correlation: float
    key_byte_index: int
    all_candidates: NDArray[np.float64]

    @property
    def is_successful(self) -> bool:
        """Whether the attack recovered the key byte with high confidence."""
        sorted_corr = np.sort(self.all_candidates)[::-1]
        if len(sorted_corr) < 2:
            return False
        # Success if best guess is significantly better than second best
        return float(sorted_corr[0] - sorted_corr[1]) > 0.01


class SideChannelSimulator:
    """Simulate power consumption and run side-channel analysis.

    Power models:
        - **Hamming weight**: models power proportional to the number
          of set bits in the intermediate value.
        - **Hamming distance**: models power proportional to the number
          of bit transitions between consecutive register states.
    """

    def __init__(
        self,
        *,
        noise_stddev: float = 0.5,
        num_samples: int = 200,
        rng_seed: int | None = None,
    ) -> None:
        self._noise_std: float = noise_stddev
        self._num_samples: int = num_samples
        self._rng: np.random.Generator = np.random.default_rng(rng_seed)

    # ── Power models ───────────────────────────────────────────────

    @staticmethod
    def hamming_weight(values: NDArray[np.uint8]) -> NDArray[np.int32]:
        """Compute Hamming weight (popcount) of each byte value."""
        # Lookup table for byte popcount
        lut = np.array([bin(i).count("1") for i in range(256)], dtype=np.int32)
        return lut[values]

    @staticmethod
    def hamming_distance(
        prev_values: NDArray[np.uint8],
        curr_values: NDArray[np.uint8],
    ) -> NDArray[np.int32]:
        """Compute Hamming distance between consecutive register states."""
        xor = np.bitwise_xor(prev_values, curr_values)
        lut = np.array([bin(i).count("1") for i in range(256)], dtype=np.int32)
        return lut[xor]

    # ── Trace generation ───────────────────────────────────────────

    def simulate_with_power(
        self,
        plaintexts: NDArray[np.uint8],
        key: NDArray[np.uint8],
        *,
        model: Literal["hamming_weight", "hamming_distance"] = "hamming_weight",
        target_byte: int = 0,
    ) -> list[PowerTrace]:
        """Generate simulated power traces for a set of encryptions.

        Parameters
        ----------
        plaintexts:
            2-D array of shape ``(num_traces, block_size)`` with input
            plaintext bytes.
        key:
            1-D array representing the secret key.
        model:
            Power model to use.
        target_byte:
            Which key/plaintext byte to target for the leakage injection.

        Returns
        -------
        list[PowerTrace]
            One trace per plaintext, each containing ``num_samples``
            sample points.
        """
        num_traces = plaintexts.shape[0]
        traces: list[PowerTrace] = []

        # Compute the intermediate value (SubBytes output byte)
        sbox = self._aes_sbox()
        intermediate = sbox[plaintexts[:, target_byte] ^ key[target_byte]]

        if model == "hamming_weight":
            leakage = self.hamming_weight(intermediate).astype(np.float64)
        else:
            # Hamming distance from zero initial state
            prev = np.zeros_like(intermediate)
            leakage = self.hamming_distance(prev, intermediate).astype(np.float64)

        # Build power traces: inject leakage at a specific sample point
        leak_point = self._num_samples // 3  # leakage appears at ~1/3 of trace
        leak_width = 5

        for i in range(num_traces):
            base_noise = self._rng.normal(0.0, self._noise_std, self._num_samples)
            # Inject leakage as a small bump
            for offset in range(leak_width):
                idx = leak_point + offset
                if idx < self._num_samples:
                    weight = 1.0 - abs(offset - leak_width // 2) / (leak_width // 2 + 1)
                    base_noise[idx] += leakage[i] * weight

            traces.append(
                PowerTrace(
                    samples=base_noise,
                    plaintext=plaintexts[i],
                    key=key,
                    label=f"trace_{i:05d}",
                )
            )

        return traces

    # ── TVLA (Test Vector Leakage Assessment) ──────────────────────

    def run_tvla(
        self,
        traces_fixed: list[PowerTrace],
        traces_random: list[PowerTrace],
        *,
        threshold: float = 4.5,
    ) -> TVLAResult:
        """Run Welch's t-test (fixed vs. random) TVLA.

        Parameters
        ----------
        traces_fixed:
            Traces encrypted with a fixed plaintext.
        traces_random:
            Traces encrypted with random plaintexts.
        threshold:
            Absolute t-value threshold for declaring leakage (default 4.5).

        Returns
        -------
        TVLAResult
            Contains the t-statistic vector and leakage information.
        """
        mat_fixed = np.array([t.samples for t in traces_fixed], dtype=np.float64)
        mat_random = np.array([t.samples for t in traces_random], dtype=np.float64)

        n0 = mat_fixed.shape[0]
        n1 = mat_random.shape[0]

        mean0 = np.mean(mat_fixed, axis=0)
        mean1 = np.mean(mat_random, axis=0)
        var0 = np.var(mat_fixed, axis=0, ddof=1)
        var1 = np.var(mat_random, axis=0, ddof=1)

        # Welch's t-statistic (per sample point)
        denominator = np.sqrt(var0 / n0 + var1 / n1)
        # Avoid division by zero
        denominator = np.where(denominator == 0.0, 1e-15, denominator)
        t_stat = (mean0 - mean1) / denominator

        return TVLAResult(
            t_statistic=t_stat,
            threshold=threshold,
            num_traces_group0=n0,
            num_traces_group1=n1,
        )

    # ── CPA (Correlation Power Analysis) ───────────────────────────

    def run_cpa(
        self,
        traces: list[PowerTrace],
        plaintexts: NDArray[np.uint8],
        *,
        target_byte: int = 0,
    ) -> CPAResult:
        """Run a CPA attack on the first SubBytes output byte.

        Parameters
        ----------
        traces:
            List of power traces from simulated or captured measurements.
        plaintexts:
            Corresponding plaintext array of shape ``(num_traces, block_size)``.
        target_byte:
            Which key byte to attack.

        Returns
        -------
        CPAResult
            Contains the correlation matrix and best key guess.
        """
        trace_matrix = np.array([t.samples for t in traces], dtype=np.float64)
        num_traces, num_samples = trace_matrix.shape
        sbox = self._aes_sbox()

        # Hypothetical power model for all 256 key candidates
        correlations = np.zeros(256, dtype=np.float64)
        corr_matrix = np.zeros((256, num_samples), dtype=np.float64)

        for key_guess in range(256):
            # Hypothetical intermediate: SBox[plaintext_byte XOR key_guess]
            hyp_intermediate = sbox[plaintexts[:, target_byte] ^ key_guess]
            hyp_power = self.hamming_weight(hyp_intermediate).astype(np.float64)

            # Pearson correlation between hypothetical power and each sample
            hp_centered = hyp_power - np.mean(hyp_power)
            hp_std = np.std(hyp_power, ddof=1)
            if hp_std < 1e-15:
                continue

            for s in range(num_samples):
                col = trace_matrix[:, s]
                col_centered = col - np.mean(col)
                col_std = np.std(col, ddof=1)
                if col_std < 1e-15:
                    continue
                r = np.dot(hp_centered, col_centered) / ((num_traces - 1) * hp_std * col_std)
                corr_matrix[key_guess, s] = r

            correlations[key_guess] = float(np.max(np.abs(corr_matrix[key_guess])))

        best_key = int(np.argmax(correlations))
        best_corr = float(correlations[best_key])

        return CPAResult(
            correlation_matrix=corr_matrix,
            best_key_byte=best_key,
            best_correlation=best_corr,
            key_byte_index=target_byte,
            all_candidates=correlations,
        )

    # ── AES S-Box lookup table ─────────────────────────────────────

    @staticmethod
    def _aes_sbox() -> NDArray[np.uint8]:
        """Return the standard AES S-Box as a 256-element uint8 array."""
        return np.array(
            [
                0x63,
                0x7C,
                0x77,
                0x7B,
                0xF2,
                0x6B,
                0x6F,
                0xC5,
                0x30,
                0x01,
                0x67,
                0x2B,
                0xFE,
                0xD7,
                0xAB,
                0x76,
                0xCA,
                0x82,
                0xC9,
                0x7D,
                0xFA,
                0x59,
                0x47,
                0xF0,
                0xAD,
                0xD4,
                0xA2,
                0xAF,
                0x9C,
                0xA4,
                0x72,
                0xC0,
                0xB7,
                0xFD,
                0x93,
                0x26,
                0x36,
                0x3F,
                0xF7,
                0xCC,
                0x34,
                0xA5,
                0xE5,
                0xF1,
                0x71,
                0xD8,
                0x31,
                0x15,
                0x04,
                0xC7,
                0x23,
                0xC3,
                0x18,
                0x96,
                0x05,
                0x9A,
                0x07,
                0x12,
                0x80,
                0xE2,
                0xEB,
                0x27,
                0xB2,
                0x75,
                0x09,
                0x83,
                0x2C,
                0x1A,
                0x1B,
                0x6E,
                0x5A,
                0xA0,
                0x52,
                0x3B,
                0xD6,
                0xB3,
                0x29,
                0xE3,
                0x2F,
                0x84,
                0x53,
                0xD1,
                0x00,
                0xED,
                0x20,
                0xFC,
                0xB1,
                0x5B,
                0x6A,
                0xCB,
                0xBE,
                0x39,
                0x4A,
                0x4C,
                0x58,
                0xCF,
                0xD0,
                0xEF,
                0xAA,
                0xFB,
                0x43,
                0x4D,
                0x33,
                0x85,
                0x45,
                0xF9,
                0x02,
                0x7F,
                0x50,
                0x3C,
                0x9F,
                0xA8,
                0x51,
                0xA3,
                0x40,
                0x8F,
                0x92,
                0x9D,
                0x38,
                0xF5,
                0xBC,
                0xB6,
                0xDA,
                0x21,
                0x10,
                0xFF,
                0xF3,
                0xD2,
                0xCD,
                0x0C,
                0x13,
                0xEC,
                0x5F,
                0x97,
                0x44,
                0x17,
                0xC4,
                0xA7,
                0x7E,
                0x3D,
                0x64,
                0x5D,
                0x19,
                0x73,
                0x60,
                0x81,
                0x4F,
                0xDC,
                0x22,
                0x2A,
                0x90,
                0x88,
                0x46,
                0xEE,
                0xB8,
                0x14,
                0xDE,
                0x5E,
                0x0B,
                0xDB,
                0xE0,
                0x32,
                0x3A,
                0x0A,
                0x49,
                0x06,
                0x24,
                0x5C,
                0xC2,
                0xD3,
                0xAC,
                0x62,
                0x91,
                0x95,
                0xE4,
                0x79,
                0xE7,
                0xC8,
                0x37,
                0x6D,
                0x8D,
                0xD5,
                0x4E,
                0xA9,
                0x6C,
                0x56,
                0xF4,
                0xEA,
                0x65,
                0x7A,
                0xAE,
                0x08,
                0xBA,
                0x78,
                0x25,
                0x2E,
                0x1C,
                0xA6,
                0xB4,
                0xC6,
                0xE8,
                0xDD,
                0x74,
                0x1F,
                0x4B,
                0xBD,
                0x8B,
                0x8A,
                0x70,
                0x3E,
                0xB5,
                0x66,
                0x48,
                0x03,
                0xF6,
                0x0E,
                0x61,
                0x35,
                0x57,
                0xB9,
                0x86,
                0xC1,
                0x1D,
                0x9E,
                0xE1,
                0xF8,
                0x98,
                0x11,
                0x69,
                0xD9,
                0x8E,
                0x94,
                0x9B,
                0x1E,
                0x87,
                0xE9,
                0xCE,
                0x55,
                0x28,
                0xDF,
                0x8C,
                0xA1,
                0x89,
                0x0D,
                0xBF,
                0xE6,
                0x42,
                0x68,
                0x41,
                0x99,
                0x2D,
                0x0F,
                0xB0,
                0x54,
                0xBB,
                0x16,
            ],
            dtype=np.uint8,
        )
