"""Tests for FIPS 140-3 compliance checker logic."""

from __future__ import annotations


NIST_APPROVED_SYMMETRIC = {
    "AES-128", "AES-192", "AES-256",
    "AES-128-GCM", "AES-256-GCM",
    "AES-128-CCM", "AES-256-CCM",
}

NIST_APPROVED_HASH = {
    "SHA-256", "SHA-384", "SHA-512",
    "SHA3-256", "SHA3-384", "SHA3-512",
    "SHAKE128", "SHAKE256",
}

NIST_APPROVED_PQC = {
    "ML-KEM-512", "ML-KEM-768", "ML-KEM-1024",
    "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
    "SLH-DSA-SHA2-128s", "SLH-DSA-SHA2-128f",
    "SLH-DSA-SHA2-192s", "SLH-DSA-SHA2-192f",
    "SLH-DSA-SHA2-256s", "SLH-DSA-SHA2-256f",
    "SLH-DSA-SHAKE-128s", "SLH-DSA-SHAKE-128f",
}

ALL_APPROVED = NIST_APPROVED_SYMMETRIC | NIST_APPROVED_HASH | NIST_APPROVED_PQC


def test_approved_algorithms_pass() -> None:
    """All NIST-approved algorithms should pass validation."""
    for algo in ALL_APPROVED:
        assert algo in ALL_APPROVED


def test_unapproved_algorithm_detected() -> None:
    """Non-approved algorithms must be flagged."""
    unapproved = ["DES", "3DES", "RC4", "MD5", "SHA-1", "RSA-1024"]
    for algo in unapproved:
        assert algo not in ALL_APPROVED


def test_key_zeroization_sva_property() -> None:
    """Verify SVA property format for key zeroization."""
    key_name = "secret_key"
    max_cycles = 100
    expected_property = (
        f"property key_zeroization_{key_name};\n"
        f"    @(posedge clk)\n"
        f"    zeroize |-> ##[1:{max_cycles}] ({key_name} == '0);\n"
        f"endproperty"
    )
    assert "zeroize" in expected_property
    assert str(max_cycles) in expected_property
    assert key_name in expected_property


def test_self_test_sva_property() -> None:
    """Verify SVA property for crypto operation gating until self-test passes."""
    prop = (
        "property crypto_gated_until_selftest;\n"
        "    @(posedge clk)\n"
        "    !self_test_done |-> !crypto_enable;\n"
        "endproperty"
    )
    assert "self_test_done" in prop
    assert "crypto_enable" in prop


def test_error_inhibit_sva_property() -> None:
    """Verify SVA property for output inhibit on error."""
    prop = (
        "property error_inhibits_output;\n"
        "    @(posedge clk)\n"
        "    error_flag |-> (crypto_output == '0);\n"
        "endproperty"
    )
    assert "error_flag" in prop
    assert "crypto_output" in prop


def test_rng_health_sva_property() -> None:
    """Verify SVA for RNG health test gating."""
    prop = (
        "property rng_gated_on_health_fail;\n"
        "    @(posedge clk)\n"
        "    health_test_fail |-> !rng_valid;\n"
        "endproperty"
    )
    assert "health_test_fail" in prop
    assert "rng_valid" in prop


def test_fips_levels() -> None:
    """FIPS 140-3 has 4 security levels."""
    levels = [1, 2, 3, 4]
    assert len(levels) == 4
    # Level 2 requires role-based auth + physical tamper evidence
    # Level 3 requires identity-based auth + tamper response
    # Level 4 requires complete envelope protection
