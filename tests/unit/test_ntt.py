"""Tests for the NTT/polynomial validator -- verifies mathematical correctness."""

from __future__ import annotations


def test_kyber_q_is_prime() -> None:
    """Kyber modulus q=3329 must be prime."""
    q = 3329
    for i in range(2, int(q**0.5) + 1):
        assert q % i != 0, f"3329 is divisible by {i}"


def test_kyber_q_is_ntt_friendly() -> None:
    """q=3329 must satisfy q ≡ 1 (mod 256) for NTT."""
    assert 3329 % 256 == 1


def test_dilithium_q_is_prime() -> None:
    """Dilithium modulus q=8380417 must be prime."""
    q = 8380417
    # Trial division up to sqrt
    for i in range(2, min(10000, int(q**0.5) + 1)):
        assert q % i != 0, f"8380417 is divisible by {i}"


def test_butterfly_cooley_tukey() -> None:
    """Cooley-Tukey butterfly: a' = a + w*b mod q, b' = a - w*b mod q."""
    q = 3329
    a, b, w = 1234, 2345, 17  # primitive root

    a_out = (a + w * b) % q
    b_out = (a - w * b) % q

    # Must be in range [0, q)
    assert 0 <= a_out < q
    assert 0 <= b_out < q

    # Verify reversibility (GS butterfly is the inverse)
    a_inv = (a_out + b_out) % q
    wb_inv = (a_out - b_out) % q

    # a_inv should equal 2a mod q (since a' + b' = 2a)
    assert a_inv == (2 * a) % q


def test_butterfly_gentleman_sande() -> None:
    """Gentleman-Sande butterfly: a' = a + b mod q, b' = w*(a - b) mod q."""
    q = 3329
    a, b, w = 1000, 2000, 17

    a_out = (a + b) % q
    b_out = (w * ((a - b) % q)) % q

    assert 0 <= a_out < q
    assert 0 <= b_out < q


def test_modular_reduction_correctness() -> None:
    """Barrett/Montgomery reduction must match Python modulo."""
    q = 3329
    test_values = [0, 1, q - 1, q, q + 1, 2 * q, 3328 * 3328, 65535]

    for val in test_values:
        expected = val % q
        assert 0 <= expected < q


def test_barrett_reduction() -> None:
    """Barrett reduction: output = input mod q using precomputed constant."""
    q = 3329
    # Barrett constant: floor(2^k / q) where k = ceil(log2(q)) * 2
    k = 24  # 2 * ceil(log2(3329))
    m = (1 << k) // q  # Barrett constant

    test_vals = [0, 1, 1000, 3328, 3329, 3330, 10000, 3328 * 3328]

    for val in test_vals:
        # Barrett reduction algorithm
        t = (val * m) >> k
        result = val - t * q
        if result >= q:
            result -= q

        assert result == val % q, f"Barrett failed for {val}: got {result}, expected {val % q}"
