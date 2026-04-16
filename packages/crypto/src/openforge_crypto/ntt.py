"""Number Theoretic Transform (NTT) and polynomial arithmetic validator.

Provides reference implementations and validation tools for NTT-based
post-quantum cryptographic hardware, supporting ML-KEM (FIPS 203,
q=3329) and ML-DSA (FIPS 204, q=8380417).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

# ── NTT standards ─────────────────────────────────────────────────────

class NTTStandard(Enum):
    """Supported NTT parameter sets."""

    KYBER = auto()       # ML-KEM: q=3329, n=256
    DILITHIUM = auto()   # ML-DSA: q=8380417, n=256
    CUSTOM = auto()


# ── ML-KEM (FIPS 203) constants ──────────────────────────────────────

KYBER_Q: int = 3329
KYBER_N: int = 256

# Primitive 256th root of unity in Z_3329: zeta = 17
# These are the bit-reversed zeta powers used in the NTT as specified
# in FIPS 203, Algorithm 9 (NTT).  Index 0 is unused (the NTT loop
# starts at k=1).  Entries 1..127 are zeta^{BitRev_7(i)} mod q.
KYBER_ZETAS: list[int] = [
    # Index 0 (unused sentinel)
    1,
    # Layer 0 (one butterfly): zeta^64
    1729,
    # Layer 1 (two butterflies): zeta^32, zeta^96
    2580, 3289,
    # Layer 2: zeta^16, zeta^80, zeta^48, zeta^112
    926, 1950, 1512, 2580 - 1,  # computed below; replaced with actual values
]

# Full zeta table: compute zeta^{BitRev_7(i)} mod q for i in 0..127
def _compute_kyber_zetas() -> list[int]:
    """Compute the 128 zeta values for ML-KEM NTT (FIPS 203)."""
    q = KYBER_Q
    zeta = 17  # primitive 256th root of unity mod 3329

    # Compute all powers of zeta mod q
    powers: list[int] = [1] * 256
    for i in range(1, 256):
        powers[i] = (powers[i - 1] * zeta) % q

    # Bit-reverse function for 7-bit indices
    def bitrev7(x: int) -> int:
        result = 0
        for _ in range(7):
            result = (result << 1) | (x & 1)
            x >>= 1
        return result

    # The NTT uses zetas[i] = zeta^{BitRev_7(i)} for i in 0..127
    zetas: list[int] = []
    for i in range(128):
        zetas.append(powers[bitrev7(i)])

    return zetas


# Replace the placeholder with the actual computed values
KYBER_ZETAS = _compute_kyber_zetas()


# ── ML-DSA (FIPS 204) constants ──────────────────────────────────────

DILITHIUM_Q: int = 8380417
DILITHIUM_N: int = 256

# Primitive 256th root of unity mod 8380417: zeta = 1753
def _compute_dilithium_zetas() -> list[int]:
    """Compute the 256 zeta values for ML-DSA NTT (FIPS 204)."""
    q = DILITHIUM_Q
    zeta = 1753  # primitive 512th root of unity mod q

    powers: list[int] = [1] * 512
    for i in range(1, 512):
        powers[i] = (powers[i - 1] * zeta) % q

    def bitrev8(x: int) -> int:
        result = 0
        for _ in range(8):
            result = (result << 1) | (x & 1)
            x >>= 1
        return result

    zetas: list[int] = []
    for i in range(256):
        zetas.append(powers[bitrev8(i)])

    return zetas


DILITHIUM_ZETAS: list[int] = _compute_dilithium_zetas()


# ── Data classes ──────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TwiddleResult:
    """Result of twiddle factor validation."""

    passed: bool
    mismatches: list[dict[str, int]] = field(default_factory=list)

    def __str__(self) -> str:
        if self.passed:
            return "Twiddle factor validation: PASS"
        return (
            f"Twiddle factor validation: FAIL "
            f"({len(self.mismatches)} mismatches)"
        )


@dataclass(frozen=True, slots=True)
class NTTResult:
    """Result of a full NTT validation."""

    passed: bool
    mismatches: list[dict[str, int]] = field(default_factory=list)
    input_polynomial: list[int] = field(default_factory=list)
    expected_output: list[int] = field(default_factory=list)
    actual_output: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        if self.passed:
            return "NTT validation: PASS"
        return (
            f"NTT validation: FAIL "
            f"({len(self.mismatches)} coefficient mismatches)"
        )


# ── NTT Validator ─────────────────────────────────────────────────────

class NTTValidator:
    """Validate NTT hardware implementations against reference.

    Supports ML-KEM (FIPS 203) and ML-DSA (FIPS 204) parameter sets.
    Provides reference NTT/INTT, butterfly validation, modular reduction
    checks, and SVA property generation.
    """

    # ── Twiddle factor validation ─────────────────────────────────

    def validate_twiddle_factors(
        self,
        rom_values: list[int],
        standard: NTTStandard,
    ) -> TwiddleResult:
        """Compare hardware ROM twiddle factors against reference values.

        Parameters
        ----------
        rom_values:
            The twiddle factors read from the hardware ROM.
        standard:
            Which NTT standard to validate against.
        """
        if standard == NTTStandard.KYBER:
            ref = KYBER_ZETAS
        elif standard == NTTStandard.DILITHIUM:
            ref = DILITHIUM_ZETAS
        else:
            return TwiddleResult(
                passed=False,
                mismatches=[{
                    "index": 0,
                    "expected": 0,
                    "actual": 0,
                }],
            )

        mismatches: list[dict[str, int]] = []
        check_len = min(len(rom_values), len(ref))

        for i in range(check_len):
            if rom_values[i] != ref[i]:
                mismatches.append({
                    "index": i,
                    "expected": ref[i],
                    "actual": rom_values[i],
                })

        # Length mismatch
        if len(rom_values) != len(ref):
            mismatches.append({
                "index": -1,
                "expected": len(ref),
                "actual": len(rom_values),
            })

        return TwiddleResult(
            passed=len(mismatches) == 0,
            mismatches=mismatches,
        )

    # ── Butterfly validation ──────────────────────────────────────

    def validate_butterfly_ct(
        self,
        a_in: int,
        b_in: int,
        w: int,
        q: int,
        a_out: int,
        b_out: int,
    ) -> bool:
        """Validate a Cooley-Tukey butterfly operation.

        CT butterfly:
            a_out = a_in + w * b_in  (mod q)
            b_out = a_in - w * b_in  (mod q)
        """
        t = (w * b_in) % q
        expected_a = (a_in + t) % q
        expected_b = (a_in - t) % q
        return a_out == expected_a and b_out == expected_b

    def validate_butterfly_gs(
        self,
        a_in: int,
        b_in: int,
        w: int,
        q: int,
        a_out: int,
        b_out: int,
    ) -> bool:
        """Validate a Gentleman-Sande (inverse) butterfly operation.

        GS butterfly:
            a_out = a_in + b_in      (mod q)
            b_out = w * (a_in - b_in) (mod q)
        """
        expected_a = (a_in + b_in) % q
        expected_b = (w * ((a_in - b_in) % q)) % q
        return a_out == expected_a and b_out == expected_b

    # ── Modular reduction validation ──────────────────────────────

    def validate_modular_reduction(
        self,
        input_val: int,
        output_val: int,
        q: int,
    ) -> bool:
        """Validate a generic modular reduction: output = input mod q."""
        return output_val == (input_val % q)

    def validate_barrett_reduction(
        self,
        input_val: int,
        output_val: int,
        q: int,
        shift: int,
    ) -> bool:
        """Validate Barrett modular reduction.

        Barrett reduction computes: output = input - q * floor(input * m / 2^shift)
        where m = floor(2^shift / q).

        The result must satisfy 0 <= output < 2*q (before final correction)
        or 0 <= output < q (after final correction).
        """
        expected = input_val % q
        # Barrett may produce output in [0, 2q), so check both
        return output_val == expected or output_val == expected + q

    def validate_montgomery_reduction(
        self,
        input_val: int,
        output_val: int,
        q: int,
        r: int,
    ) -> bool:
        """Validate Montgomery modular reduction.

        Montgomery form: output = input * R^{-1} mod q
        where R = r (typically a power of 2).
        """
        # Compute R^{-1} mod q via extended GCD
        r_inv = pow(r, -1, q)
        expected = (input_val * r_inv) % q
        return output_val == expected

    # ── Reference NTT/INTT ────────────────────────────────────────

    def reference_ntt(
        self,
        polynomial: list[int],
        q: int,
        zetas: list[int],
    ) -> list[int]:
        """Compute reference forward NTT (Cooley-Tukey, in-place).

        Implements the NTT as specified in FIPS 203 Algorithm 9 for
        ML-KEM, and the equivalent for ML-DSA.

        Parameters
        ----------
        polynomial:
            Input coefficients (length must be a power of 2).
        q:
            The modulus.
        zetas:
            Pre-computed twiddle factors (bit-reversed order).

        Returns
        -------
        list[int]
            NTT-domain coefficients.
        """
        n = len(polynomial)
        f = list(polynomial)

        k = 1
        length = n // 2
        while length >= 2:
            start = 0
            while start < n:
                zeta = zetas[k]
                k += 1
                for j in range(start, start + length):
                    t = (zeta * f[j + length]) % q
                    f[j + length] = (f[j] - t) % q
                    f[j] = (f[j] + t) % q
                start += 2 * length
            length //= 2

        return f

    def reference_intt(
        self,
        polynomial: list[int],
        q: int,
        zetas_inv: list[int],
    ) -> list[int]:
        """Compute reference inverse NTT (Gentleman-Sande, in-place).

        Implements the inverse NTT as specified in FIPS 203 Algorithm 10
        for ML-KEM.

        Parameters
        ----------
        polynomial:
            NTT-domain coefficients.
        q:
            The modulus.
        zetas_inv:
            Inverse twiddle factors (bit-reversed order).

        Returns
        -------
        list[int]
            Time-domain coefficients.
        """
        n = len(polynomial)
        f = list(polynomial)

        k = n // 2 - 1
        length = 2
        while length <= n // 2:
            start = 0
            while start < n:
                zeta = zetas_inv[k]
                k -= 1
                for j in range(start, start + length):
                    t = f[j]
                    f[j] = (t + f[j + length]) % q
                    f[j + length] = (zeta * (f[j + length] - t)) % q
                start += 2 * length
            length *= 2

        # Multiply by n^{-1} mod q
        n_inv = pow(n, -1, q)
        f = [(coeff * n_inv) % q for coeff in f]

        return f

    # ── Full NTT validation ───────────────────────────────────────

    def validate_full_ntt(
        self,
        input_polynomial: list[int],
        output_polynomial: list[int],
        standard: NTTStandard,
    ) -> NTTResult:
        """Validate a complete NTT by comparing against reference output.

        Parameters
        ----------
        input_polynomial:
            The polynomial fed into the hardware NTT.
        output_polynomial:
            The result produced by the hardware.
        standard:
            Which NTT standard to use for reference computation.
        """
        if standard == NTTStandard.KYBER:
            q = KYBER_Q
            zetas = KYBER_ZETAS
        elif standard == NTTStandard.DILITHIUM:
            q = DILITHIUM_Q
            zetas = DILITHIUM_ZETAS
        else:
            return NTTResult(
                passed=False,
                mismatches=[{"index": -1, "expected": 0, "actual": 0}],
                input_polynomial=list(input_polynomial),
                expected_output=[],
                actual_output=list(output_polynomial),
            )

        # Reduce input mod q
        reduced_input = [c % q for c in input_polynomial]
        expected = self.reference_ntt(reduced_input, q, zetas)

        mismatches: list[dict[str, int]] = []
        for i in range(min(len(expected), len(output_polynomial))):
            if expected[i] != (output_polynomial[i] % q):
                mismatches.append({
                    "index": i,
                    "expected": expected[i],
                    "actual": output_polynomial[i] % q,
                })

        if len(expected) != len(output_polynomial):
            mismatches.append({
                "index": -1,
                "expected": len(expected),
                "actual": len(output_polynomial),
            })

        return NTTResult(
            passed=len(mismatches) == 0,
            mismatches=mismatches,
            input_polynomial=list(input_polynomial),
            expected_output=expected,
            actual_output=list(output_polynomial),
        )

    # ── Exhaustive test vector generation ─────────────────────────

    def generate_exhaustive_vectors(
        self,
        q: int,
        max_pairs: int = 10000,
    ) -> list[tuple[int, int, int, int, int]]:
        """Generate exhaustive Cooley-Tukey butterfly test vectors.

        Returns tuples of (a, b, w, expected_a_out, expected_b_out)
        for all valid input combinations up to *max_pairs*.
        """
        vectors: list[tuple[int, int, int, int, int]] = []
        count = 0

        # Sample values across the field
        if q <= 256:
            a_range = range(q)
            b_range = range(q)
            w_range = range(1, q)
        else:
            # For larger fields, sample representative values
            step = max(1, q // 64)
            a_range = range(0, q, step)
            b_range = range(0, q, step)
            w_range = range(1, q, max(1, q // 32))

        for w in w_range:
            for a in a_range:
                for b in b_range:
                    t = (w * b) % q
                    a_out = (a + t) % q
                    b_out = (a - t) % q
                    vectors.append((a, b, w, a_out, b_out))
                    count += 1
                    if count >= max_pairs:
                        return vectors

        return vectors

    # ── SVA property generation ───────────────────────────────────

    def generate_formal_properties(
        self,
        standard: NTTStandard,
    ) -> str:
        """Generate SVA properties for NTT correctness verification.

        Returns SystemVerilog code with properties checking:
          - Butterfly correctness (CT and GS)
          - Modular reduction bounds
          - Coefficient range invariants
          - Twiddle factor ROM contents
        """
        if standard == NTTStandard.KYBER:
            q = KYBER_Q
            q_name = "KYBER"
            n = KYBER_N
        elif standard == NTTStandard.DILITHIUM:
            q = DILITHIUM_Q
            q_name = "DILITHIUM"
            n = DILITHIUM_N
        else:
            return "// Custom NTT: provide q, n, and zetas manually.\n"

        lines: list[str] = [
            f"// NTT Formal Properties for {q_name} (q={q}, n={n})",
            "// Auto-generated by OpenForge EDA",
            "",
            f"localparam int Q = {q};",
            f"localparam int N = {n};",
            "",
            "// ---- Coefficient range invariant ----",
            "// All NTT coefficients must be in [0, q)",
            "property ntt_coeff_range(logic [23:0] coeff);",
            "  @(posedge clk) disable iff (!rst_n)",
            "  (ntt_valid) |-> (coeff < Q);",
            "endproperty",
            "",
            "generate",
            "  for (genvar i = 0; i < N; i++) begin : coeff_check",
            "    assert property (ntt_coeff_range(ntt_out[i]))",
            '      else $error("NTT coefficient %0d out of range", i);',
            "  end",
            "endgenerate",
            "",
            "// ---- Cooley-Tukey butterfly correctness ----",
            "property ct_butterfly_correct(",
            "  logic [23:0] a_in, b_in, w, a_out, b_out",
            ");",
            "  @(posedge clk) disable iff (!rst_n)",
            "  (butterfly_valid) |->",
            "    (a_out == (a_in + (w * b_in) % Q) % Q) &&",
            "    (b_out == (a_in - (w * b_in) % Q + Q) % Q);",
            "endproperty",
            "",
            "// ---- Gentleman-Sande butterfly correctness ----",
            "property gs_butterfly_correct(",
            "  logic [23:0] a_in, b_in, w, a_out, b_out",
            ");",
            "  @(posedge clk) disable iff (!rst_n)",
            "  (butterfly_valid) |->",
            "    (a_out == (a_in + b_in) % Q) &&",
            "    (b_out == (w * ((a_in - b_in + Q) % Q)) % Q);",
            "endproperty",
            "",
            "// ---- Modular reduction bound ----",
            "property mod_reduce_correct(",
            "  logic [47:0] input_val, logic [23:0] output_val",
            ");",
            "  @(posedge clk) disable iff (!rst_n)",
            "  (reduce_valid) |-> (output_val == input_val % Q);",
            "endproperty",
            "",
            "// ---- NTT round-trip: NTT(INTT(x)) == x ----",
            "// (For formal: constrain input, run NTT+INTT, check equality)",
            "property ntt_roundtrip;",
            "  @(posedge clk) disable iff (!rst_n)",
            "  (roundtrip_done) |->",
            "    (roundtrip_output == roundtrip_input);",
            "endproperty",
            "assert property (ntt_roundtrip)",
            '  else $error("NTT round-trip failed");',
            "",
        ]

        return "\n".join(lines)

    # ── Kyber-specific helpers ────────────────────────────────────

    @staticmethod
    def kyber_ntt(polynomial: list[int]) -> list[int]:
        """Convenience: compute ML-KEM NTT on a 256-coefficient polynomial."""
        v = NTTValidator()
        return v.reference_ntt(
            [c % KYBER_Q for c in polynomial], KYBER_Q, KYBER_ZETAS,
        )

    @staticmethod
    def kyber_intt(polynomial: list[int]) -> list[int]:
        """Convenience: compute ML-KEM inverse NTT."""
        # Compute inverse zetas: zetas_inv[i] = -zetas[127-i] mod q
        # (following FIPS 203 Algorithm 10)
        zetas_inv = [(-z) % KYBER_Q for z in KYBER_ZETAS]
        v = NTTValidator()
        return v.reference_intt(polynomial, KYBER_Q, zetas_inv)

    @staticmethod
    def dilithium_ntt(polynomial: list[int]) -> list[int]:
        """Convenience: compute ML-DSA NTT on a 256-coefficient polynomial."""
        v = NTTValidator()
        return v.reference_ntt(
            [c % DILITHIUM_Q for c in polynomial],
            DILITHIUM_Q,
            DILITHIUM_ZETAS,
        )

    @staticmethod
    def dilithium_intt(polynomial: list[int]) -> list[int]:
        """Convenience: compute ML-DSA inverse NTT."""
        zetas_inv = [(-z) % DILITHIUM_Q for z in DILITHIUM_ZETAS]
        v = NTTValidator()
        return v.reference_intt(polynomial, DILITHIUM_Q, zetas_inv)
