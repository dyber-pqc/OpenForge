"""Cryptographic hardware security analysis suite.

Provides six analysis passes for RTL-level crypto verification:
1. Constant-time verification
2. Power side-channel resistance
3. Fault injection resistance
4. FIPS 140-3 compliance
5. NTT validation
6. Entropy / TRNG analysis
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConstantTimeViolation:
    """A timing side-channel vulnerability in the RTL."""

    file: str
    line: int
    signal: str
    description: str


@dataclass(frozen=True, slots=True)
class ConstantTimeResult:
    """Result of constant-time verification."""

    violations: list[ConstantTimeViolation] = field(default_factory=list)
    passed: bool = True


@dataclass(frozen=True, slots=True)
class ScaResult:
    """Power side-channel analysis result."""

    risk_score: float = 0.0          # 0 (safe) to 100 (vulnerable)
    has_masking: bool = False
    has_hiding: bool = False
    sbox_type: str = ""              # "table_lookup", "boolean", "composite"
    recommendations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FaultResistance:
    """Fault injection resistance analysis result."""

    has_tmr: bool = False
    has_dual_rail: bool = False
    has_error_detection: bool = False
    fsm_encoding: str = ""           # "one_hot", "binary", "gray"
    redundancy_score: float = 0.0    # 0-100
    recommendations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FipsCheckItem:
    """Single FIPS 140-3 compliance check."""

    requirement: str
    status: str = "N/A"              # "pass", "fail", "N/A"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FipsResult:
    """FIPS 140-3 compliance checklist."""

    checks: list[FipsCheckItem] = field(default_factory=list)
    overall_passed: bool = False


@dataclass(frozen=True, slots=True)
class NttValidation:
    """NTT (Number Theoretic Transform) validation result."""

    has_butterfly: bool = False
    has_modular_reduction: bool = False
    geometry_type: str = ""          # "constant_geometry", "in_place"
    issues: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass(frozen=True, slots=True)
class EntropyResult:
    """Entropy / TRNG analysis result."""

    has_trng: bool = False
    has_prng: bool = False
    has_health_tests: bool = False
    has_proper_seeding: bool = False
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RTL source reader helper
# ---------------------------------------------------------------------------


def _read_sources(
    sources: Sequence[str | PathLike[str]],
) -> list[tuple[str, str]]:
    """Read source files, returning list of (filename, content)."""
    results: list[tuple[str, str]] = []
    for src in sources:
        p = Path(src)
        if p.exists():
            results.append((str(p), p.read_text(errors="replace")))
    return results


def _find_pattern_in_sources(
    file_contents: list[tuple[str, str]],
    pattern: str,
    flags: int = re.IGNORECASE | re.MULTILINE,
) -> list[tuple[str, int, str]]:
    """Search for a regex in all source files.

    Returns list of (filename, line_number, matched_line).
    """
    results: list[tuple[str, int, str]] = []
    compiled = re.compile(pattern, flags)
    for filename, content in file_contents:
        for i, line in enumerate(content.splitlines(), 1):
            if compiled.search(line):
                results.append((filename, i, line.strip()))
    return results


# ---------------------------------------------------------------------------
# CryptoAnalyzer
# ---------------------------------------------------------------------------


class CryptoAnalyzer:
    """RTL-level cryptographic security analysis suite.

    Typical workflow::

        analyzer = CryptoAnalyzer()
        ct = analyzer.check_constant_time(["aes.v"], secret_signals=["key", "plaintext"])
        sca = analyzer.check_power_sca(["aes.v"])
        fips = analyzer.check_fips_compliance(["aes.v", "sha256.v"])
    """

    # ------------------------------------------------------------------
    # 1. Constant-Time Verification
    # ------------------------------------------------------------------

    def check_constant_time(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        secret_signals: Sequence[str] = (),
    ) -> ConstantTimeResult:
        """Check for data-dependent timing behaviour in crypto RTL.

        Scans for:
        - ``if``/``case`` statements conditioned on secret data
        - Variable-latency operations (multiply, divide)
        - Memory access patterns dependent on secret data

        Parameters
        ----------
        sources:
            Verilog/SystemVerilog source files.
        secret_signals:
            Signal names considered secret (e.g. "key", "plaintext").
        """
        file_contents = _read_sources(sources)
        violations: list[ConstantTimeViolation] = []

        # Default secret signal patterns if none provided
        secret_pats = list(secret_signals) if secret_signals else [
            "key", "secret", "plaintext", "plain_text", "pt",
            "private", "priv_key", "seed", "nonce",
        ]
        secret_re = "|".join(re.escape(s) for s in secret_pats)

        # Check 1: if/case conditioned on secret data
        for filename, content in file_contents:
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # Skip comments
                if stripped.startswith("//") or stripped.startswith("/*"):
                    continue

                # if (<secret>)
                if re.search(
                    rf"\bif\s*\(.*\b({secret_re})\b",
                    stripped,
                    re.IGNORECASE,
                ):
                    signal = re.search(
                        rf"\b({secret_re})\b", stripped, re.IGNORECASE,
                    )
                    violations.append(ConstantTimeViolation(
                        file=filename,
                        line=i,
                        signal=signal.group(1) if signal else "?",
                        description=(
                            "Conditional branch depends on potentially secret "
                            "data -- may leak timing information."
                        ),
                    ))

                # case (<secret>)
                if re.search(
                    rf"\bcase\s*\(.*\b({secret_re})\b",
                    stripped,
                    re.IGNORECASE,
                ):
                    signal = re.search(
                        rf"\b({secret_re})\b", stripped, re.IGNORECASE,
                    )
                    violations.append(ConstantTimeViolation(
                        file=filename,
                        line=i,
                        signal=signal.group(1) if signal else "?",
                        description=(
                            "Case statement on secret data -- variable-time "
                            "multiplexing may create a timing side channel."
                        ),
                    ))

        # Check 2: Variable-latency operations with secret operands
        for filename, content in file_contents:
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue

                # Multiply or divide with secret operand
                if re.search(r"[*/]", stripped) and re.search(
                    rf"\b({secret_re})\b", stripped, re.IGNORECASE,
                ):
                    signal = re.search(
                        rf"\b({secret_re})\b", stripped, re.IGNORECASE,
                    )
                    if signal and ("*" in stripped or "/" in stripped or "%" in stripped):
                        violations.append(ConstantTimeViolation(
                            file=filename,
                            line=i,
                            signal=signal.group(1),
                            description=(
                                "Variable-latency arithmetic (multiply/divide) "
                                "on secret data -- timing may depend on operand "
                                "values."
                            ),
                        ))

        # Check 3: Memory indexed by secret data (array[secret])
        for filename, content in file_contents:
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue

                if re.search(
                    rf"\w+\s*\[.*\b({secret_re})\b.*\]",
                    stripped,
                    re.IGNORECASE,
                ):
                    signal = re.search(
                        rf"\b({secret_re})\b", stripped, re.IGNORECASE,
                    )
                    violations.append(ConstantTimeViolation(
                        file=filename,
                        line=i,
                        signal=signal.group(1) if signal else "?",
                        description=(
                            "Memory/array access indexed by secret data -- "
                            "may create cache-timing side channel."
                        ),
                    ))

        return ConstantTimeResult(
            violations=violations,
            passed=len(violations) == 0,
        )

    # ------------------------------------------------------------------
    # 2. Power SCA Resistance
    # ------------------------------------------------------------------

    def check_power_sca(
        self,
        sources: Sequence[str | PathLike[str]],
    ) -> ScaResult:
        """Analyze power side-channel resistance of crypto RTL.

        Checks for:
        - Balanced/complementary logic (masking, hiding)
        - S-box implementation style (table lookup vs boolean)
        - Masking countermeasures
        """
        file_contents = _read_sources(sources)
        recommendations: list[str] = []
        risk = 50.0  # Start at medium risk

        # Check for masking: look for XOR with random/mask signals
        mask_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(mask|rand|random|rng|share[_\d]|masked)\b",
        )
        has_masking = len(mask_patterns) > 0
        if has_masking:
            risk -= 20.0
        else:
            recommendations.append(
                "No masking countermeasure detected. Consider adding "
                "Boolean masking (d+1 shares) to protect against DPA."
            )

        # Check for hiding: look for dual-rail / complementary logic
        hiding_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(dual_rail|complement|wddl|sabl|hiding|precharge)\b",
        )
        has_hiding = len(hiding_patterns) > 0
        if has_hiding:
            risk -= 15.0
        else:
            recommendations.append(
                "No hiding countermeasure detected. Consider dual-rail "
                "logic (WDDL/SABL) for additional protection."
            )

        # Check S-box implementation
        sbox_type = "unknown"
        table_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(sbox|s_box|sub_bytes|subbytes)\b.*\[",
        )
        boolean_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(sbox|s_box|sub_bytes)\b.*(\^|&|\|)",
        )

        if table_patterns and not boolean_patterns:
            sbox_type = "table_lookup"
            risk += 10.0
            recommendations.append(
                "S-box uses table lookup -- vulnerable to cache-timing "
                "attacks. Consider a Boolean (gate-level) implementation."
            )
        elif boolean_patterns:
            sbox_type = "boolean"
            risk -= 5.0
        elif table_patterns and boolean_patterns:
            sbox_type = "composite"

        # Check for unprotected XOR chains (typical in unmasked AES)
        xor_chains = _find_pattern_in_sources(
            file_contents,
            r"\^.*\^.*\^",
        )
        if xor_chains and not has_masking:
            risk += 10.0
            recommendations.append(
                "Long XOR chains without masking detected -- Hamming "
                "weight leakage likely exploitable via CPA."
            )

        risk = max(0.0, min(100.0, risk))

        return ScaResult(
            risk_score=risk,
            has_masking=has_masking,
            has_hiding=has_hiding,
            sbox_type=sbox_type,
            recommendations=recommendations,
        )

    # ------------------------------------------------------------------
    # 3. Fault Injection Resistance
    # ------------------------------------------------------------------

    def check_fault_injection(
        self,
        sources: Sequence[str | PathLike[str]],
    ) -> FaultResistance:
        """Analyze fault injection resistance of crypto RTL.

        Checks for:
        - Triple Modular Redundancy (TMR)
        - Dual-rail logic
        - Error detection codes (parity, ECC)
        - FSM encoding style
        """
        file_contents = _read_sources(sources)
        recommendations: list[str] = []
        score = 0.0

        # TMR detection
        tmr_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(tmr|triple|voter|majority|redundan)",
        )
        has_tmr = len(tmr_patterns) > 0
        if has_tmr:
            score += 30.0
        else:
            recommendations.append(
                "No TMR detected. Consider adding triple modular "
                "redundancy for critical state registers."
            )

        # Dual-rail
        dr_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(dual_rail|complement|wddl)\b",
        )
        has_dual_rail = len(dr_patterns) > 0
        if has_dual_rail:
            score += 15.0

        # Error detection
        ecc_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(parity|ecc|hamming|crc|error_detect|err_det)\b",
        )
        has_error_detection = len(ecc_patterns) > 0
        if has_error_detection:
            score += 25.0
        else:
            recommendations.append(
                "No error detection codes found. Add parity or ECC "
                "on critical registers to detect fault injection."
            )

        # FSM encoding analysis
        fsm_encoding = "unknown"

        # Look for localparam/parameter state definitions
        onehot_patterns = _find_pattern_in_sources(
            file_contents,
            r"(?:localparam|parameter).*\b\d+'b[01]*1[01]*0{2,}|0{2,}[01]*1\b",
        )
        if onehot_patterns:
            fsm_encoding = "one_hot"
            score += 10.0
        else:
            # Check for sequential encoding
            seq_patterns = _find_pattern_in_sources(
                file_contents,
                r"(?:localparam|parameter).*\b\d+'[bdh]\d+\b",
            )
            if seq_patterns:
                fsm_encoding = "binary"
                recommendations.append(
                    "FSM uses binary encoding. Consider one-hot encoding "
                    "for better fault detection (single-bit faults cause "
                    "invalid states)."
                )

        # Check for safe FSM handling (default case)
        default_patterns = _find_pattern_in_sources(
            file_contents,
            r"\bdefault\s*:",
        )
        if default_patterns:
            score += 10.0
        else:
            recommendations.append(
                "No default case in FSMs detected. Always include a "
                "default case that transitions to a safe/error state."
            )

        score = min(100.0, score)

        return FaultResistance(
            has_tmr=has_tmr,
            has_dual_rail=has_dual_rail,
            has_error_detection=has_error_detection,
            fsm_encoding=fsm_encoding,
            redundancy_score=score,
            recommendations=recommendations,
        )

    # ------------------------------------------------------------------
    # 4. FIPS 140-3 Compliance
    # ------------------------------------------------------------------

    def check_fips_compliance(
        self,
        sources: Sequence[str | PathLike[str]],
    ) -> FipsResult:
        """Check FIPS 140-3 compliance requirements against RTL.

        Checks:
        - No hardcoded keys
        - Key zeroization logic exists
        - Self-test / BIST capability
        - Approved algorithms only
        """
        file_contents = _read_sources(sources)
        checks: list[FipsCheckItem] = []

        # 1. Key storage -- check for hardcoded keys (Verilog hex literal: 8'hAB)
        hardcoded = _find_pattern_in_sources(
            file_contents,
            r"(?:key|secret)\s*(?:=|<=)\s*\d+'h[0-9a-fA-F]{16,}",
        )
        if hardcoded:
            checks.append(FipsCheckItem(
                requirement="No hardcoded cryptographic keys",
                status="fail",
                detail=f"Found {len(hardcoded)} potential hardcoded key(s). "
                       f"First at: {hardcoded[0][0]}:{hardcoded[0][1]}",
            ))
        else:
            checks.append(FipsCheckItem(
                requirement="No hardcoded cryptographic keys",
                status="pass",
                detail="No hardcoded key patterns detected.",
            ))

        # 2. Zeroization -- check for key clearing logic
        zeroize_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(zeroiz|zero_key|key_clear|wipe|scrub|purge)\b",
        )
        key_zero_assign = _find_pattern_in_sources(
            file_contents,
            r"(?:key|secret)\s*(?:<=|=)\s*(?:\d+'[hbdo])?0+\s*;",
        )
        has_zeroize = len(zeroize_patterns) > 0 or len(key_zero_assign) > 0
        checks.append(FipsCheckItem(
            requirement="Key zeroization capability",
            status="pass" if has_zeroize else "fail",
            detail="Key clearing logic detected." if has_zeroize
                   else "No key zeroization mechanism found.",
        ))

        # 3. Self-test / BIST
        bist_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(bist|self_test|selftest|kat|known_answer|health_check)\b",
        )
        has_bist = len(bist_patterns) > 0
        checks.append(FipsCheckItem(
            requirement="Self-test / BIST capability",
            status="pass" if has_bist else "fail",
            detail="BIST/self-test logic detected." if has_bist
                   else "No self-test mechanism found. FIPS requires "
                        "known-answer tests for approved algorithms.",
        ))

        # 4. Approved algorithms
        approved_algos = {
            "AES": r"\b(aes|rijndael|sub_bytes|mix_columns|shift_rows)\b",
            "SHA-2/3": r"\b(sha256|sha512|sha3|keccak|sha_256|sha_512)\b",
            "ECDSA": r"\b(ecdsa|ecc|point_mul|scalar_mul|secp256)\b",
            "ML-KEM": r"\b(ml_kem|kyber|mlkem|crystals)\b",
            "RSA": r"\b(rsa|mod_exp|montgomery)\b",
        }
        found_algos: list[str] = []
        for algo_name, pattern in approved_algos.items():
            matches = _find_pattern_in_sources(file_contents, pattern)
            if matches:
                found_algos.append(algo_name)

        if found_algos:
            checks.append(FipsCheckItem(
                requirement="Uses FIPS-approved algorithms",
                status="pass",
                detail=f"Detected: {', '.join(found_algos)}",
            ))
        else:
            checks.append(FipsCheckItem(
                requirement="Uses FIPS-approved algorithms",
                status="N/A",
                detail="No recognized cryptographic algorithm patterns found.",
            ))

        # 5. Key wrapping / export protection
        wrap_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(key_wrap|kwp|aes_wrap|export_key)\b",
        )
        checks.append(FipsCheckItem(
            requirement="Key export protection (wrapping)",
            status="pass" if wrap_patterns else "N/A",
            detail="Key wrapping detected." if wrap_patterns
                   else "No key export logic detected (may not be applicable).",
        ))

        overall = all(
            c.status in ("pass", "N/A") for c in checks
        )

        return FipsResult(checks=checks, overall_passed=overall)

    # ------------------------------------------------------------------
    # 5. NTT Validation
    # ------------------------------------------------------------------

    def validate_ntt(
        self,
        sources: Sequence[str | PathLike[str]],
    ) -> NttValidation:
        """Validate NTT (Number Theoretic Transform) implementation.

        Checks:
        - Butterfly structure present
        - Modular reduction implementation
        - Constant-geometry vs in-place architecture
        """
        file_contents = _read_sources(sources)
        issues: list[str] = []

        # Check for butterfly structure
        butterfly_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(butterfly|bfu|ntt_stage|twiddle|omega|root_of_unity)\b",
        )
        has_butterfly = len(butterfly_patterns) > 0

        if not has_butterfly:
            issues.append(
                "No butterfly unit detected. NTT requires a butterfly "
                "computation structure (a +/- b * twiddle)."
            )

        # Check for modular reduction
        mod_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(mod_red|modular_red|barrett|montgomery|mod_q|mod_p|reduce)\b",
        )
        mod_op = _find_pattern_in_sources(file_contents, r"\s%\s")
        has_mod_reduction = len(mod_patterns) > 0 or len(mod_op) > 0

        if not has_mod_reduction:
            issues.append(
                "No modular reduction detected. NTT requires modular "
                "arithmetic (Barrett, Montgomery, or direct %)."
            )

        # Determine geometry type
        geometry = ""
        const_geo = _find_pattern_in_sources(
            file_contents,
            r"\b(constant.geometry|const.geo|gentleman.sande|cooley.tukey)\b",
        )
        inplace = _find_pattern_in_sources(
            file_contents,
            r"\b(in.place|inplace|dit|dif)\b",
        )

        if const_geo:
            geometry = "constant_geometry"
        elif inplace:
            geometry = "in_place"
        else:
            geometry = "unknown"
            issues.append(
                "Cannot determine NTT geometry (constant-geometry vs "
                "in-place). Annotate the architecture for clarity."
            )

        # Check for proper twiddle factor ROM
        twiddle_rom = _find_pattern_in_sources(
            file_contents,
            r"\b(twiddle|omega|w_rom|tw_rom|roots)\s*\[",
        )
        if not twiddle_rom and has_butterfly:
            issues.append(
                "No twiddle factor ROM/table detected. Ensure "
                "pre-computed roots of unity are stored correctly."
            )

        passed = len(issues) == 0

        return NttValidation(
            has_butterfly=has_butterfly,
            has_modular_reduction=has_mod_reduction,
            geometry_type=geometry,
            issues=issues,
            passed=passed,
        )

    # ------------------------------------------------------------------
    # 6. Entropy Analysis
    # ------------------------------------------------------------------

    def check_entropy(
        self,
        sources: Sequence[str | PathLike[str]],
    ) -> EntropyResult:
        """Analyze TRNG/PRNG implementations in crypto RTL.

        Checks for:
        - TRNG presence (ring oscillator, metastability, jitter)
        - PRNG presence (LFSR, ChaCha, AES-CTR-DRBG)
        - Health tests
        - Proper seeding
        """
        file_contents = _read_sources(sources)
        recommendations: list[str] = []

        # TRNG detection
        trng_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(trng|ring_osc|ring_oscillator|ro_entropy|"
            r"metastab|jitter|entropy_source|true_random)\b",
        )
        has_trng = len(trng_patterns) > 0

        # PRNG detection
        prng_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(prng|lfsr|drbg|ctr_drbg|chacha|pseudo_random|"
            r"aes_ctr|xorshift|mersenne)\b",
        )
        has_prng = len(prng_patterns) > 0

        if not has_trng and not has_prng:
            recommendations.append(
                "No random number generator detected. Cryptographic "
                "implementations require a TRNG or seeded PRNG."
            )

        # Health test detection
        health_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(health_test|repetition_count|adaptive_proportion|"
            r"chi_squared|monobit|poker_test|ais31|sp800_90b)\b",
        )
        has_health_tests = len(health_patterns) > 0

        if has_trng and not has_health_tests:
            recommendations.append(
                "TRNG detected but no health tests found. NIST SP "
                "800-90B requires repetition count and adaptive "
                "proportion tests."
            )

        # Seeding check
        seed_patterns = _find_pattern_in_sources(
            file_contents,
            r"\b(seed|reseed|re_seed|entropy_input|personalization)\b",
        )
        has_seeding = len(seed_patterns) > 0

        if has_prng and not has_seeding:
            recommendations.append(
                "PRNG detected but no seeding mechanism found. "
                "Ensure PRNG is seeded from a TRNG or secure source."
            )

        if has_prng and not has_trng:
            recommendations.append(
                "PRNG without TRNG detected. For FIPS compliance, "
                "the PRNG must be seeded from an approved entropy source."
            )

        return EntropyResult(
            has_trng=has_trng,
            has_prng=has_prng,
            has_health_tests=has_health_tests,
            has_proper_seeding=has_seeding,
            recommendations=recommendations,
        )
