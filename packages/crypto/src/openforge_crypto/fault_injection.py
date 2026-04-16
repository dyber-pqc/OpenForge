"""Fault injection simulation for testing cryptographic hardware resilience.

Provides fault models (clock glitch, voltage glitch, bit-flip, stuck-at,
laser) and analysis methods (differential fault analysis, safe error
detection, redundancy checking) to evaluate design resilience against
hardware attacks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

# ── Enums ─────────────────────────────────────────────────────────────

class FaultModel(Enum):
    """Types of hardware fault injection."""

    CLOCK_GLITCH = auto()
    VOLTAGE_GLITCH = auto()
    BIT_FLIP = auto()
    MULTI_BIT = auto()
    STUCK_AT = auto()
    LASER = auto()


class FaultClassification(Enum):
    """Classification of a fault injection result."""

    SAFE_ERROR = auto()       # Fault did not affect output
    DETECTED = auto()         # Fault was detected by countermeasures
    UNDETECTED = auto()       # Fault changed output, not detected
    CRITICAL = auto()         # Fault leaked key information


# ── Data classes ──────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class FaultConfig:
    """Configuration for a single fault injection."""

    model: FaultModel
    target_signal: str
    target_cycle: int
    parameters: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        params = ", ".join(f"{k}={v}" for k, v in self.parameters.items())
        return (
            f"{self.model.name} on {self.target_signal} "
            f"at cycle {self.target_cycle}"
            + (f" ({params})" if params else "")
        )


@dataclass(frozen=True, slots=True)
class FaultResult:
    """Result from a single fault injection campaign."""

    config: FaultConfig
    detected: bool
    output_affected: bool
    key_leaked: bool

    @property
    def classification(self) -> FaultClassification:
        if self.key_leaked:
            return FaultClassification.CRITICAL
        if not self.output_affected:
            return FaultClassification.SAFE_ERROR
        if self.detected:
            return FaultClassification.DETECTED
        return FaultClassification.UNDETECTED


@dataclass(frozen=True, slots=True)
class DFAResult:
    """Result of a differential fault analysis."""

    vulnerable: bool
    key_recovery_possible: bool
    min_faults_needed: int
    analysis_details: str


@dataclass(slots=True)
class FaultResilienceReport:
    """Aggregate report from multiple fault injection campaigns."""

    total_campaigns: int = 0
    results: list[FaultResult] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    @property
    def detected_count(self) -> int:
        return sum(
            1 for r in self.results
            if r.classification == FaultClassification.DETECTED
        )

    @property
    def safe_error_count(self) -> int:
        return sum(
            1 for r in self.results
            if r.classification == FaultClassification.SAFE_ERROR
        )

    @property
    def undetected_count(self) -> int:
        return sum(
            1 for r in self.results
            if r.classification == FaultClassification.UNDETECTED
        )

    @property
    def critical_count(self) -> int:
        return sum(
            1 for r in self.results
            if r.classification == FaultClassification.CRITICAL
        )

    @property
    def detected_pct(self) -> float:
        if not self.results:
            return 0.0
        return 100.0 * self.detected_count / len(self.results)

    @property
    def safe_error_pct(self) -> float:
        if not self.results:
            return 0.0
        return 100.0 * self.safe_error_count / len(self.results)

    @property
    def critical_pct(self) -> float:
        if not self.results:
            return 0.0
        return 100.0 * self.critical_count / len(self.results)

    @property
    def overall_score(self) -> int:
        """Resilience score from 0 (worst) to 100 (best).

        Scoring:
          - Safe errors contribute fully (weight 1.0)
          - Detected faults contribute well (weight 0.8)
          - Undetected faults contribute nothing
          - Critical faults penalize (weight -1.0)
        """
        if not self.results:
            return 0
        total = len(self.results)
        score = (
            self.safe_error_count * 1.0
            + self.detected_count * 0.8
            + self.undetected_count * 0.0
            + self.critical_count * -1.0
        )
        normalized = max(0.0, min(1.0, score / total))
        return round(normalized * 100)

    def summary(self) -> str:
        lines = [
            f"Fault Resilience Report (score: {self.overall_score}/100)",
            f"  Total campaigns: {self.total_campaigns}",
            f"  Safe errors:  {self.safe_error_count} "
            f"({self.safe_error_pct:.1f}%)",
            f"  Detected:     {self.detected_count} "
            f"({self.detected_pct:.1f}%)",
            f"  Undetected:   {self.undetected_count}",
            f"  Critical:     {self.critical_count} "
            f"({self.critical_pct:.1f}%)",
        ]
        if self.recommendations:
            lines.append("  Recommendations:")
            for rec in self.recommendations:
                lines.append(f"    - {rec}")
        return "\n".join(lines)


# ── Fault Injection Simulator ─────────────────────────────────────────

class FaultInjectionSimulator:
    """Simulate hardware fault injection and evaluate design resilience.

    Workflow:
        1. Instantiate with design signals and clock period.
        2. Generate fault configs with ``inject_*()`` methods.
        3. Analyse results with ``run_differential_fault_analysis()``,
           ``check_safe_error()``, ``check_redundancy()``.
        4. Run ``evaluate_fault_resilience()`` for aggregate scoring.
        5. Generate cocotb testbenches or countermeasure reports.
    """

    def __init__(
        self,
        design_signals: list[str],
        clock_period_ns: float = 10.0,
    ) -> None:
        self._signals: list[str] = list(design_signals)
        self._clock_period_ns: float = clock_period_ns
        self._fault_log: list[FaultConfig] = []

    # ── Fault injection methods ───────────────────────────────────

    def inject_clock_glitch(
        self,
        target_cycle: int,
        glitch_width_ns: float,
        glitch_offset_ns: float = 0.0,
    ) -> FaultConfig:
        """Generate a clock glitch fault.

        The glitch shortens or inserts an extra clock edge within a
        single cycle, potentially causing setup/hold violations.
        """
        config = FaultConfig(
            model=FaultModel.CLOCK_GLITCH,
            target_signal="clk",
            target_cycle=target_cycle,
            parameters={
                "glitch_width_ns": glitch_width_ns,
                "glitch_offset_ns": glitch_offset_ns,
                "clock_period_ns": self._clock_period_ns,
            },
        )
        self._fault_log.append(config)
        return config

    def inject_voltage_glitch(
        self,
        target_cycle: int,
        drop_voltage: float,
        duration_ns: float,
    ) -> FaultConfig:
        """Generate a voltage glitch (power supply perturbation).

        A voltage drop can cause logic gates to mis-evaluate,
        flipping one or more bits in registers.
        """
        config = FaultConfig(
            model=FaultModel.VOLTAGE_GLITCH,
            target_signal="vdd",
            target_cycle=target_cycle,
            parameters={
                "drop_voltage": drop_voltage,
                "duration_ns": duration_ns,
                "affected_signals": self._estimate_affected_signals(
                    drop_voltage
                ),
            },
        )
        self._fault_log.append(config)
        return config

    def inject_bit_flip(
        self,
        signal: str,
        bit_index: int,
        cycle: int,
    ) -> FaultConfig:
        """Inject a single-bit fault (bit flip) in a register."""
        config = FaultConfig(
            model=FaultModel.BIT_FLIP,
            target_signal=signal,
            target_cycle=cycle,
            parameters={
                "bit_index": bit_index,
                "mask": 1 << bit_index,
            },
        )
        self._fault_log.append(config)
        return config

    def inject_multi_bit_fault(
        self,
        signal: str,
        bit_mask: int,
        cycle: int,
    ) -> FaultConfig:
        """Inject a multi-bit fault using a bitmask."""
        config = FaultConfig(
            model=FaultModel.MULTI_BIT,
            target_signal=signal,
            target_cycle=cycle,
            parameters={
                "bit_mask": bit_mask,
                "num_bits_affected": bin(bit_mask).count("1"),
            },
        )
        self._fault_log.append(config)
        return config

    def inject_stuck_at(
        self,
        signal: str,
        bit_index: int,
        value: int,
        start_cycle: int,
        end_cycle: int,
    ) -> FaultConfig:
        """Inject a stuck-at fault (bit held at 0 or 1)."""
        config = FaultConfig(
            model=FaultModel.STUCK_AT,
            target_signal=signal,
            target_cycle=start_cycle,
            parameters={
                "bit_index": bit_index,
                "stuck_value": value & 1,
                "start_cycle": start_cycle,
                "end_cycle": end_cycle,
                "duration_cycles": end_cycle - start_cycle,
            },
        )
        self._fault_log.append(config)
        return config

    def inject_laser_fault(
        self,
        x_um: float,
        y_um: float,
        radius_um: float,
        cycle: int,
    ) -> FaultConfig:
        """Inject a laser fault affecting all registers within a spatial radius.

        In a real flow, register coordinates come from placed layout data.
        This method models the spatial fault for simulation purposes.
        """
        config = FaultConfig(
            model=FaultModel.LASER,
            target_signal="spatial",
            target_cycle=cycle,
            parameters={
                "x_um": x_um,
                "y_um": y_um,
                "radius_um": radius_um,
                "affected_area_um2": math.pi * radius_um ** 2,
            },
        )
        self._fault_log.append(config)
        return config

    # ── Analysis methods ──────────────────────────────────────────

    def run_differential_fault_analysis(
        self,
        correct_output: list[int],
        faulty_outputs: list[list[int]],
        algorithm: str = "AES",
    ) -> DFAResult:
        """Run differential fault analysis (DFA).

        Compares correct and faulty ciphertext outputs to determine if
        faults reveal key information. Based on the Piret-Quisquater
        and Giraud attacks for AES.

        Parameters
        ----------
        correct_output:
            The correct (unfaulted) ciphertext as a list of byte values.
        faulty_outputs:
            List of faulty ciphertexts, one per fault injection.
        algorithm:
            The algorithm being attacked (for selecting DFA strategy).
        """
        if not faulty_outputs:
            return DFAResult(
                vulnerable=False,
                key_recovery_possible=False,
                min_faults_needed=0,
                analysis_details="No faulty outputs provided.",
            )

        # Compute differential bytes between correct and each faulty output
        differentials: list[list[int]] = []
        for faulty in faulty_outputs:
            diff = [
                c ^ f for c, f in zip(correct_output, faulty, strict=False)
            ]
            differentials.append(diff)

        # Count how many bytes differ per fault
        affected_byte_counts = [
            sum(1 for d in diff if d != 0) for diff in differentials
        ]

        # DFA vulnerability heuristics
        single_byte_faults = sum(1 for c in affected_byte_counts if c == 1)
        four_byte_faults = sum(1 for c in affected_byte_counts if c == 4)

        # For AES, a single-byte fault in round 9 affects 4 bytes of output
        # (after MixColumns). 2 such faults can recover a full key column.
        if algorithm.upper() in ("AES", "AES-128", "AES-256"):
            if four_byte_faults >= 2:
                return DFAResult(
                    vulnerable=True,
                    key_recovery_possible=True,
                    min_faults_needed=2,
                    analysis_details=(
                        f"Piret-Quisquater DFA: {four_byte_faults} faults "
                        f"affect 4 bytes each (round 8/9 fault pattern). "
                        f"Key recovery possible with 2 faults."
                    ),
                )
            if single_byte_faults >= 1:
                return DFAResult(
                    vulnerable=True,
                    key_recovery_possible=True,
                    min_faults_needed=max(1, 4 - single_byte_faults),
                    analysis_details=(
                        f"Giraud DFA: {single_byte_faults} single-byte "
                        f"faults detected (round 10 fault pattern). "
                        f"Partial key recovery possible."
                    ),
                )

        # Generic analysis for other algorithms
        if any(c > 0 for c in affected_byte_counts):
            return DFAResult(
                vulnerable=True,
                key_recovery_possible=False,
                min_faults_needed=len(faulty_outputs),
                analysis_details=(
                    f"Faults affect output: {affected_byte_counts}. "
                    f"Further analysis needed for {algorithm}."
                ),
            )

        return DFAResult(
            vulnerable=False,
            key_recovery_possible=False,
            min_faults_needed=0,
            analysis_details="All faults resulted in safe errors.",
        )

    def check_safe_error(
        self,
        correct_output: list[int],
        faulty_output: list[int],
    ) -> bool:
        """Check if a fault resulted in a safe error (no output change)."""
        return correct_output == faulty_output

    def check_redundancy(
        self,
        signal_a: str,
        signal_b: str,
        voter_signal: str,
    ) -> CheckResult:
        """Verify TMR/dual-rail redundancy logic.

        Returns a description of the redundancy check and SVA properties
        for verifying that the voter correctly selects the majority.
        """
        sva = (
            f"// TMR Redundancy Check: {signal_a}, {signal_b}, {voter_signal}\n"
            f"property tmr_voter_correct;\n"
            f"  @(posedge clk) disable iff (!rst_n)\n"
            f"  ({signal_a} == {signal_b}) |-> "
            f"({voter_signal} == {signal_a});\n"
            f"endproperty\n"
            f"assert property (tmr_voter_correct)\n"
            f"  else $error(\"TMR: voter output disagrees with "
            f"matching inputs\");\n"
            f"\n"
            f"// Detect disagreement\n"
            f"property tmr_detect_fault;\n"
            f"  @(posedge clk) disable iff (!rst_n)\n"
            f"  ({signal_a} != {signal_b}) |-> "
            f"(fault_detected == 1'b1);\n"
            f"endproperty\n"
            f"assert property (tmr_detect_fault)\n"
            f"  else $error(\"TMR: fault not detected on disagreement\");\n"
        )

        return CheckResult(
            name="redundancy_check",
            description=(
                f"TMR/dual-rail: {signal_a}, {signal_b} -> {voter_signal}"
            ),
            sva_property=sva,
            detected=True,
        )

    def evaluate_fault_resilience(
        self,
        num_campaigns: int,
        fault_model: FaultModel,
        *,
        results: list[FaultResult] | None = None,
    ) -> FaultResilienceReport:
        """Evaluate overall fault resilience from campaign results.

        If *results* is provided, uses those directly. Otherwise, creates
        a report template for the specified number of campaigns.
        """
        report = FaultResilienceReport(total_campaigns=num_campaigns)

        if results:
            report.results = list(results)
        report.total_campaigns = max(
            num_campaigns, len(report.results)
        )

        # Generate recommendations based on results
        report.recommendations = self.generate_countermeasure_report(
            report.results
        )

        return report

    # ── Testbench generation ──────────────────────────────────────

    def generate_fault_testbench(
        self,
        fault_config: FaultConfig,
        *,
        module_name: str = "crypto_top",
        clock_signal: str = "clk",
        reset_signal: str = "rst_n",
    ) -> str:
        """Generate a cocotb testbench that injects the specified fault.

        Returns Python source code for a cocotb test function.
        """
        lines: list[str] = [
            '"""Auto-generated fault injection testbench (cocotb)."""',
            "",
            "import cocotb",
            "from cocotb.clock import Clock",
            "from cocotb.triggers import (",
            "    ClockCycles, FallingEdge, RisingEdge, Timer,",
            ")",
            "",
            "",
        ]

        if fault_config.model == FaultModel.BIT_FLIP:
            bit_idx = fault_config.parameters.get("bit_index", 0)
            lines.extend([
                "@cocotb.test()",
                f"async def test_bit_flip_{fault_config.target_signal}"
                f"_b{bit_idx}(dut):",
                f'    """Inject single-bit flip on '
                f'{fault_config.target_signal}[{bit_idx}] at cycle '
                f'{fault_config.target_cycle}."""',
                f"    clock = Clock(dut.{clock_signal}, "
                f"{self._clock_period_ns}, units='ns')",
                "    cocotb.start_soon(clock.start())",
                "",
                "    # Reset",
                f"    dut.{reset_signal}.value = 0",
                f"    await ClockCycles(dut.{clock_signal}, 5)",
                f"    dut.{reset_signal}.value = 1",
                f"    await ClockCycles(dut.{clock_signal}, 5)",
                "",
                "    # Run to target cycle",
                f"    await ClockCycles(dut.{clock_signal}, "
                f"{fault_config.target_cycle})",
                "",
                "    # Capture correct value",
                f"    correct = int(dut.{fault_config.target_signal}.value)",
                "",
                "    # Inject bit flip",
                f"    faulty = correct ^ (1 << {bit_idx})",
                f"    dut.{fault_config.target_signal}.value = faulty",
                f"    await RisingEdge(dut.{clock_signal})",
                "",
                "    # Restore (transient fault)",
                f"    dut.{fault_config.target_signal}.value = correct",
                "",
                "    # Continue and capture output",
                f"    await ClockCycles(dut.{clock_signal}, 100)",
                "    # TODO: Check output and fault detection signals",
                "",
            ])

        elif fault_config.model == FaultModel.CLOCK_GLITCH:
            width = fault_config.parameters.get("glitch_width_ns", 1.0)
            offset = fault_config.parameters.get("glitch_offset_ns", 0.0)
            lines.extend([
                "@cocotb.test()",
                f"async def test_clock_glitch_cycle"
                f"_{fault_config.target_cycle}(dut):",
                f'    """Inject clock glitch at cycle '
                f'{fault_config.target_cycle}."""',
                f"    clock = Clock(dut.{clock_signal}, "
                f"{self._clock_period_ns}, units='ns')",
                "    cocotb.start_soon(clock.start())",
                "",
                "    # Reset",
                f"    dut.{reset_signal}.value = 0",
                f"    await ClockCycles(dut.{clock_signal}, 5)",
                f"    dut.{reset_signal}.value = 1",
                "",
                "    # Run to target cycle",
                f"    await ClockCycles(dut.{clock_signal}, "
                f"{fault_config.target_cycle})",
                "",
                "    # Inject glitch: extra rising edge within the cycle",
                f"    await Timer({offset}, units='ns')",
                f"    dut.{clock_signal}.value = 1",
                f"    await Timer({width}, units='ns')",
                f"    dut.{clock_signal}.value = 0",
                "",
                "    # Continue normal operation",
                f"    await ClockCycles(dut.{clock_signal}, 100)",
                "    # TODO: Check output and fault detection signals",
                "",
            ])

        elif fault_config.model == FaultModel.STUCK_AT:
            bit_idx = fault_config.parameters.get("bit_index", 0)
            stuck_val = fault_config.parameters.get("stuck_value", 0)
            end_cycle = fault_config.parameters.get(
                "end_cycle", fault_config.target_cycle + 10
            )
            duration = end_cycle - fault_config.target_cycle
            lines.extend([
                "@cocotb.test()",
                f"async def test_stuck_at_{fault_config.target_signal}"
                f"_b{bit_idx}_v{stuck_val}(dut):",
                f'    """Inject stuck-at-{stuck_val} on '
                f'{fault_config.target_signal}[{bit_idx}]."""',
                f"    clock = Clock(dut.{clock_signal}, "
                f"{self._clock_period_ns}, units='ns')",
                "    cocotb.start_soon(clock.start())",
                "",
                "    # Reset",
                f"    dut.{reset_signal}.value = 0",
                f"    await ClockCycles(dut.{clock_signal}, 5)",
                f"    dut.{reset_signal}.value = 1",
                "",
                "    # Run to target cycle",
                f"    await ClockCycles(dut.{clock_signal}, "
                f"{fault_config.target_cycle})",
                "",
                f"    # Apply stuck-at fault for {duration} cycles",
                f"    for _ in range({duration}):",
                f"        val = int(dut.{fault_config.target_signal}.value)",
                f"        if {stuck_val}:",
                f"            val = val | (1 << {bit_idx})",
                "        else:",
                f"            val = val & ~(1 << {bit_idx})",
                f"        dut.{fault_config.target_signal}.value = val",
                f"        await RisingEdge(dut.{clock_signal})",
                "",
                "    # Continue normal operation",
                f"    await ClockCycles(dut.{clock_signal}, 100)",
                "    # TODO: Check output and fault detection signals",
                "",
            ])

        else:
            # Generic template for other fault models
            lines.extend([
                "@cocotb.test()",
                f"async def test_{fault_config.model.name.lower()}_"
                f"{fault_config.target_cycle}(dut):",
                f'    """Inject {fault_config.model.name} fault at cycle '
                f'{fault_config.target_cycle}."""',
                f"    clock = Clock(dut.{clock_signal}, "
                f"{self._clock_period_ns}, units='ns')",
                "    cocotb.start_soon(clock.start())",
                "",
                "    # Reset",
                f"    dut.{reset_signal}.value = 0",
                f"    await ClockCycles(dut.{clock_signal}, 5)",
                f"    dut.{reset_signal}.value = 1",
                "",
                f"    await ClockCycles(dut.{clock_signal}, "
                f"{fault_config.target_cycle})",
                "",
                f"    # TODO: Implement {fault_config.model.name} injection",
                f"    # Parameters: {fault_config.parameters}",
                "",
                f"    await ClockCycles(dut.{clock_signal}, 100)",
                "",
            ])

        return "\n".join(lines)

    # ── Countermeasure recommendations ────────────────────────────

    def generate_countermeasure_report(
        self,
        results: list[FaultResult],
    ) -> list[str]:
        """Generate countermeasure recommendations based on fault results.

        Returns a list of recommendation strings.
        """
        recommendations: list[str] = []

        if not results:
            recommendations.append(
                "Run fault injection campaigns to generate recommendations."
            )
            return recommendations

        critical = [
            r for r in results
            if r.classification == FaultClassification.CRITICAL
        ]
        undetected = [
            r for r in results
            if r.classification == FaultClassification.UNDETECTED
        ]

        # TMR recommendation
        if critical or undetected:
            affected_signals = set()
            for r in critical + undetected:
                affected_signals.add(r.config.target_signal)

            recommendations.append(
                f"Add Triple Modular Redundancy (TMR) for critical "
                f"registers: {', '.join(sorted(affected_signals))}"
            )

        # Dual-rail logic
        if any(
            r.config.model in (FaultModel.BIT_FLIP, FaultModel.MULTI_BIT)
            for r in critical
        ):
            recommendations.append(
                "Implement dual-rail logic with complementary signals "
                "and precharge for fault detection."
            )

        # Error detection codes
        if undetected:
            recommendations.append(
                "Add parity or ECC (error-correcting codes) on "
                "datapath registers to detect bit flips."
            )

        # Infection countermeasure
        if critical:
            recommendations.append(
                "Apply infection countermeasure: propagate faults to "
                "all output bytes to prevent differential fault analysis."
            )

        # Clock glitch detection
        clock_faults = [
            r for r in results
            if r.config.model == FaultModel.CLOCK_GLITCH
            and r.classification != FaultClassification.SAFE_ERROR
        ]
        if clock_faults:
            recommendations.append(
                "Add clock glitch detector (monitoring clock period "
                "and duty cycle) with alarm output."
            )

        # Voltage glitch detection
        voltage_faults = [
            r for r in results
            if r.config.model == FaultModel.VOLTAGE_GLITCH
            and r.classification != FaultClassification.SAFE_ERROR
        ]
        if voltage_faults:
            recommendations.append(
                "Add voltage glitch detector (brown-out detector, "
                "voltage monitor) on the power supply."
            )

        # Laser fault protection
        laser_faults = [
            r for r in results
            if r.config.model == FaultModel.LASER
            and r.classification != FaultClassification.SAFE_ERROR
        ]
        if laser_faults:
            recommendations.append(
                "Add active mesh/shield layer over sensitive logic "
                "to detect laser fault injection."
            )

        if not recommendations:
            recommendations.append(
                "Design shows good fault resilience. Continue monitoring."
            )

        return recommendations

    # ── Internal helpers ──────────────────────────────────────────

    def _estimate_affected_signals(self, drop_voltage: float) -> int:
        """Estimate number of signals affected by a voltage drop.

        Higher voltage drops affect more signals. This is a simplified
        model; real analysis requires SPICE simulation.
        """
        # Rough model: 10% of signals affected per 0.1V drop
        fraction = min(1.0, abs(drop_voltage) / 1.0)
        return max(1, round(len(self._signals) * fraction * 0.1))


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Lightweight result for redundancy checks."""

    name: str
    description: str
    sva_property: str | None = None
    detected: bool = False
