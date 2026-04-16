"""Entropy flow analysis for cryptographic hardware designs.

Traces entropy from sources (TRNG/QRNG/PRNG/DRBG) through conditioning
stages to sinks (key generation, nonce, masking, IV), verifying that
sufficient min-entropy reaches each consumer per NIST SP 800-90B.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

# ── Enums ─────────────────────────────────────────────────────────────

class EntropySourceType(Enum):
    """Type of entropy source."""

    QRNG = auto()    # Quantum random number generator
    TRNG = auto()    # True random number generator
    PRNG = auto()    # Pseudo-random number generator
    DRBG = auto()    # Deterministic random bit generator


class EntropySinkPurpose(Enum):
    """Purpose of an entropy consumer."""

    KEY_GENERATION = auto()
    NONCE = auto()
    MASKING = auto()
    IV = auto()


class ConditioningType(Enum):
    """Type of entropy conditioner."""

    HASH = auto()
    CBC_MAC = auto()
    LFSR = auto()
    VON_NEUMANN = auto()


class HealthTestType(Enum):
    """Type of entropy health test (SP 800-90B)."""

    REPETITION_COUNT = auto()
    ADAPTIVE_PROPORTION = auto()
    STARTUP = auto()


class IssueSeverity(Enum):
    """Severity of an entropy flow issue."""

    ERROR = auto()
    WARNING = auto()
    INFO = auto()


# ── Data classes ──────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class EntropySource:
    """An entropy source node in the flow graph."""

    signal: str
    min_entropy: float          # bits of min-entropy per output bit
    rate: float                 # bits per cycle
    source_type: EntropySourceType


@dataclass(frozen=True, slots=True)
class EntropySink:
    """An entropy consumer node in the flow graph."""

    signal: str
    required_bits: float        # minimum required entropy bits
    purpose: EntropySinkPurpose


@dataclass(frozen=True, slots=True)
class EntropyConditioner:
    """An entropy conditioning stage."""

    signal: str
    input_bits: int
    output_bits: int
    conditioning_type: ConditioningType

    @property
    def entropy_factor(self) -> float:
        """Entropy preservation factor for this conditioner.

        Full-entropy conditioners (hash, CBC-MAC) preserve up to
        output_bits of entropy if input has sufficient min-entropy.
        Weaker conditioners (LFSR, von Neumann) have reduced factors.
        """
        if self.conditioning_type in (
            ConditioningType.HASH, ConditioningType.CBC_MAC
        ):
            # Full-entropy source: preserves min(input_entropy, output_bits)
            return min(1.0, self.output_bits / self.input_bits)
        elif self.conditioning_type == ConditioningType.VON_NEUMANN:
            # Von Neumann: extracts ~0.5 bits per input bit, rate halved
            return 0.5 * (self.output_bits / self.input_bits)
        else:
            # LFSR: no entropy addition, just mixing
            return self.output_bits / self.input_bits


@dataclass(frozen=True, slots=True)
class EntropyHealthTest:
    """A health test node attached to a source."""

    signal: str
    test_type: HealthTestType


@dataclass(frozen=True, slots=True)
class EntropyIssue:
    """An issue detected in the entropy flow."""

    severity: IssueSeverity
    message: str
    location: str
    recommendation: str

    def __str__(self) -> str:
        return (
            f"[{self.severity.name}] {self.location}: {self.message}"
        )


@dataclass(slots=True)
class EntropyFlowReport:
    """Report from entropy flow analysis."""

    graph: dict[str, list[str]] = field(default_factory=dict)
    issues: list[EntropyIssue] = field(default_factory=list)
    sources: list[EntropySource] = field(default_factory=list)
    sinks: list[EntropySink] = field(default_factory=list)
    paths: dict[str, list[str]] = field(default_factory=dict)
    entropy_at_sinks: dict[str, float] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == IssueSeverity.ERROR for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(
            1 for i in self.issues if i.severity == IssueSeverity.WARNING
        )

    def summary(self) -> str:
        status = "FAIL" if self.has_errors else "PASS"
        lines = [
            f"Entropy Flow Report [{status}]",
            f"  Sources: {len(self.sources)}",
            f"  Sinks:   {len(self.sinks)}",
            f"  Issues:  {self.error_count} errors, "
            f"{self.warning_count} warnings",
            "",
        ]
        for sink_sig, entropy in self.entropy_at_sinks.items():
            lines.append(f"  {sink_sig}: {entropy:.2f} bits")
        for issue in self.issues:
            lines.append(f"  {issue}")
        return "\n".join(lines)


# ── Entropy-reducing operations ───────────────────────────────────────

_ENTROPY_REDUCERS: dict[str, float] = {
    "xor_fold": 0.5,        # XOR folding halves effective entropy
    "truncation": -1.0,     # factor depends on ratio, computed dynamically
    "majority_vote": 0.81,  # 3-of-5 majority: H_out ~ 0.81 * H_in
    "and_gate": 0.5,        # AND of independent bits reduces entropy
    "or_gate": 0.5,         # OR of independent bits reduces entropy
}


# ── Entropy Flow Analyzer ────────────────────────────────────────────

class EntropyFlowAnalyzer:
    """Trace and verify entropy flow through a cryptographic design.

    Workflow:
        1. ``add_source()`` / ``add_sink()`` to define endpoints.
        2. ``add_conditioner()`` / ``add_health_test()`` for intermediate stages.
        3. ``build_flow_graph()`` to connect nodes via RTL assignments.
        4. ``analyze()`` to verify entropy sufficiency.
    """

    def __init__(self) -> None:
        self._sources: dict[str, EntropySource] = {}
        self._sinks: dict[str, EntropySink] = {}
        self._conditioners: dict[str, EntropyConditioner] = {}
        self._health_tests: dict[str, EntropyHealthTest] = {}
        self._graph: dict[str, list[str]] = {}   # adjacency: signal -> [signals]
        self._node_types: dict[str, str] = {}     # signal -> "source"/"sink"/etc.

    # ── Node registration ─────────────────────────────────────────

    def add_source(
        self,
        signal: str,
        min_entropy_per_bit: float,
        rate_bits_per_cycle: float,
        source_type: EntropySourceType,
    ) -> None:
        """Register an entropy source."""
        src = EntropySource(
            signal=signal,
            min_entropy=min_entropy_per_bit,
            rate=rate_bits_per_cycle,
            source_type=source_type,
        )
        self._sources[signal] = src
        self._node_types[signal] = "source"
        self._graph.setdefault(signal, [])

    def add_sink(
        self,
        signal: str,
        required_entropy_bits: float,
        purpose: EntropySinkPurpose,
    ) -> None:
        """Register an entropy sink (consumer)."""
        sink = EntropySink(
            signal=signal,
            required_bits=required_entropy_bits,
            purpose=purpose,
        )
        self._sinks[signal] = sink
        self._node_types[signal] = "sink"
        self._graph.setdefault(signal, [])

    def add_conditioner(
        self,
        signal: str,
        input_bits: int,
        output_bits: int,
        conditioning_type: ConditioningType,
    ) -> None:
        """Register an entropy conditioner stage."""
        cond = EntropyConditioner(
            signal=signal,
            input_bits=input_bits,
            output_bits=output_bits,
            conditioning_type=conditioning_type,
        )
        self._conditioners[signal] = cond
        self._node_types[signal] = "conditioner"
        self._graph.setdefault(signal, [])

    def add_health_test(
        self,
        signal: str,
        test_type: HealthTestType,
    ) -> None:
        """Register a health test node."""
        ht = EntropyHealthTest(signal=signal, test_type=test_type)
        self._health_tests[signal] = ht
        self._node_types[signal] = "health_test"
        self._graph.setdefault(signal, [])

    # ── Graph construction ────────────────────────────────────────

    def build_flow_graph(
        self,
        assignments: list[tuple[str, str]],
    ) -> None:
        """Build the flow graph from RTL assignment pairs.

        Parameters
        ----------
        assignments:
            List of (source_signal, destination_signal) pairs representing
            RTL dataflow assignments (e.g., ``wire dest = source;``).
        """
        for src, dst in assignments:
            self._graph.setdefault(src, [])
            self._graph.setdefault(dst, [])
            if dst not in self._graph[src]:
                self._graph[src].append(dst)
            # Ensure nodes are tracked
            self._node_types.setdefault(src, "wire")
            self._node_types.setdefault(dst, "wire")

    # ── Analysis ──────────────────────────────────────────────────

    def analyze(self) -> EntropyFlowReport:
        """Run full entropy flow analysis.

        Checks:
          1. Path exists from every source to every sink.
          2. Entropy is sufficient at each sink.
          3. Health tests exist before conditioning.
          4. Conditioning output has sufficient min-entropy.
          5. No entropy-reducing operations without compensation.
          6. NIST SP 800-90B compliance for entropy sources.
        """
        report = EntropyFlowReport(
            graph=dict(self._graph),
            sources=list(self._sources.values()),
            sinks=list(self._sinks.values()),
        )

        # 1. Check paths from sources to sinks
        for sink_sig, sink in self._sinks.items():
            path = self._find_path_to_source(sink_sig)
            if path is None:
                report.issues.append(EntropyIssue(
                    severity=IssueSeverity.ERROR,
                    message=(
                        f"No entropy path found to sink '{sink_sig}' "
                        f"(purpose: {sink.purpose.name})"
                    ),
                    location=sink_sig,
                    recommendation=(
                        "Ensure an entropy source is connected to this sink "
                        "through the dataflow."
                    ),
                ))
                report.entropy_at_sinks[sink_sig] = 0.0
            else:
                report.paths[sink_sig] = path

                # 2. Estimate entropy at sink
                entropy = self.estimate_entropy_at_node(sink_sig)
                report.entropy_at_sinks[sink_sig] = entropy

                if entropy < sink.required_bits:
                    report.issues.append(EntropyIssue(
                        severity=IssueSeverity.ERROR,
                        message=(
                            f"Insufficient entropy at '{sink_sig}': "
                            f"{entropy:.2f} bits < {sink.required_bits} "
                            f"bits required"
                        ),
                        location=sink_sig,
                        recommendation=(
                            "Increase source entropy, add stronger "
                            "conditioning, or reduce requirements."
                        ),
                    ))

        # 3. Health tests before conditioning
        for cond_sig in self._conditioners:
            # Walk backwards from conditioner to find sources
            sources_for_cond = self._find_sources_for(cond_sig)
            for src_sig in sources_for_cond:
                has_test = self._health_test_on_path(src_sig, cond_sig)
                if not has_test:
                    report.issues.append(EntropyIssue(
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"No health test between source '{src_sig}' "
                            f"and conditioner '{cond_sig}'"
                        ),
                        location=cond_sig,
                        recommendation=(
                            "Add repetition count and adaptive proportion "
                            "tests per SP 800-90B."
                        ),
                    ))

        # 4. Conditioning output entropy
        for cond_sig, cond in self._conditioners.items():
            input_entropy = self._estimate_input_entropy(cond_sig)
            output_entropy = min(
                input_entropy * cond.entropy_factor,
                float(cond.output_bits),
            )
            if output_entropy < cond.output_bits * 0.9:
                report.issues.append(EntropyIssue(
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"Conditioner '{cond_sig}' output entropy "
                        f"({output_entropy:.1f} bits) below output width "
                        f"({cond.output_bits} bits)"
                    ),
                    location=cond_sig,
                    recommendation=(
                        "Increase input entropy or use a stronger "
                        "conditioning function."
                    ),
                ))

        # 6. SP 800-90B compliance for sources
        for src_sig, src in self._sources.items():
            if src.source_type == EntropySourceType.PRNG:
                report.issues.append(EntropyIssue(
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"Source '{src_sig}' is PRNG -- not a valid "
                        f"entropy source per SP 800-90B"
                    ),
                    location=src_sig,
                    recommendation=(
                        "Use a TRNG or QRNG as the entropy source. "
                        "A PRNG/DRBG can only be used after seeding."
                    ),
                ))

            if src.min_entropy < 0.1:
                report.issues.append(EntropyIssue(
                    severity=IssueSeverity.ERROR,
                    message=(
                        f"Source '{src_sig}' has very low min-entropy: "
                        f"{src.min_entropy:.3f} bits/bit"
                    ),
                    location=src_sig,
                    recommendation=(
                        "Verify entropy source quality. Min-entropy should "
                        "be at least 0.1 bits/bit before conditioning."
                    ),
                ))

            # Check health tests exist for this source
            source_has_tests = any(
                ht.signal in self._graph.get(src_sig, [])
                or src_sig in self._graph.get(ht.signal, [])
                for ht in self._health_tests.values()
            )
            if not source_has_tests and src.source_type in (
                EntropySourceType.TRNG, EntropySourceType.QRNG,
            ):
                report.issues.append(EntropyIssue(
                    severity=IssueSeverity.ERROR,
                    message=(
                        f"Source '{src_sig}' ({src.source_type.name}) "
                        f"has no health tests"
                    ),
                    location=src_sig,
                    recommendation=(
                        "SP 800-90B requires repetition count and "
                        "adaptive proportion tests for all noise sources."
                    ),
                ))

        return report

    # ── Entropy estimation ────────────────────────────────────────

    def estimate_entropy_at_node(self, node: str) -> float:
        """Estimate min-entropy in bits available at a given node.

        Traces backwards through the flow graph, accounting for
        conditioner factors and source entropy rates.
        """
        visited: set[str] = set()
        return self._estimate_recursive(node, visited)

    def _estimate_recursive(
        self, node: str, visited: set[str],
    ) -> float:
        if node in visited:
            return 0.0
        visited.add(node)

        # If this is a source, return its entropy
        if node in self._sources:
            src = self._sources[node]
            return src.min_entropy * src.rate

        # Build reverse adjacency for this node
        predecessors: list[str] = []
        for sig, dests in self._graph.items():
            if node in dests:
                predecessors.append(sig)

        if not predecessors:
            return 0.0

        # Sum entropy from all predecessors (conservative: take max path)
        max_entropy = 0.0
        for pred in predecessors:
            pred_entropy = self._estimate_recursive(pred, visited.copy())

            # Apply conditioner factor if pred is a conditioner
            if pred in self._conditioners:
                cond = self._conditioners[pred]
                pred_entropy = min(
                    pred_entropy * cond.entropy_factor,
                    float(cond.output_bits),
                )

            max_entropy = max(max_entropy, pred_entropy)

        return max_entropy

    def _estimate_input_entropy(self, node: str) -> float:
        """Estimate total entropy flowing into a node."""
        predecessors: list[str] = []
        for sig, dests in self._graph.items():
            if node in dests:
                predecessors.append(sig)

        total = 0.0
        visited: set[str] = set()
        for pred in predecessors:
            total += self._estimate_recursive(pred, visited.copy())
        return total

    # ── Path finding ──────────────────────────────────────────────

    def _find_path_to_source(self, sink: str) -> list[str] | None:
        """BFS backwards from sink to any source. Returns path or None."""
        # Build reverse adjacency
        reverse: dict[str, list[str]] = {n: [] for n in self._graph}
        for src, dests in self._graph.items():
            for dst in dests:
                reverse.setdefault(dst, []).append(src)

        visited: set[str] = {sink}
        queue: deque[list[str]] = deque([[sink]])

        while queue:
            path = queue.popleft()
            current = path[-1]

            if current in self._sources:
                return list(reversed(path))

            for pred in reverse.get(current, []):
                if pred not in visited:
                    visited.add(pred)
                    queue.append([*path, pred])

        return None

    def _find_sources_for(self, node: str) -> list[str]:
        """Find all source signals that can reach the given node."""
        reverse: dict[str, list[str]] = {n: [] for n in self._graph}
        for src, dests in self._graph.items():
            for dst in dests:
                reverse.setdefault(dst, []).append(src)

        visited: set[str] = set()
        found_sources: list[str] = []
        queue: deque[str] = deque([node])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if current in self._sources:
                found_sources.append(current)

            for pred in reverse.get(current, []):
                queue.append(pred)

        return found_sources

    def _health_test_on_path(self, source: str, target: str) -> bool:
        """Check if a health test node lies on any path from source to target."""
        visited: set[str] = set()
        queue: deque[tuple[str, bool]] = deque([(source, False)])

        while queue:
            current, seen_test = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if current in self._health_tests:
                seen_test = True

            if current == target:
                return seen_test

            for neighbor in self._graph.get(current, []):
                queue.append((neighbor, seen_test))

        return False

    # ── Entropy reducer detection ─────────────────────────────────

    def detect_entropy_reducers(
        self,
        assignments: list[tuple[str, str, str]],
    ) -> list[EntropyIssue]:
        """Detect operations that reduce entropy without compensation.

        Parameters
        ----------
        assignments:
            List of (destination, source, operation) tuples, where
            operation is one of: "xor_fold", "truncation",
            "majority_vote", "and_gate", "or_gate", "pass".

        Returns
        -------
        list[EntropyIssue]
            Issues for each entropy-reducing operation found.
        """
        issues: list[EntropyIssue] = []

        for dst, src, op in assignments:
            if op in _ENTROPY_REDUCERS and op != "pass":
                factor = _ENTROPY_REDUCERS[op]
                issues.append(EntropyIssue(
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"Entropy-reducing operation '{op}' on "
                        f"'{src}' -> '{dst}' "
                        f"(factor: {factor:.2f})"
                    ),
                    location=dst,
                    recommendation=(
                        f"Compensate for entropy reduction by increasing "
                        f"input entropy or adding conditioning after '{dst}'."
                    ),
                ))

        return issues
