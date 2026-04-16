"""Constant-time verification via taint propagation and dataflow analysis.

Detects timing side-channel vulnerabilities where secret-dependent values
influence control flow (branches, variable-latency instructions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class TaintLevel(Enum):
    """Classification of data sensitivity."""

    PUBLIC = auto()
    SECRET = auto()
    MIXED = auto()


class ViolationKind(Enum):
    """Types of constant-time violations."""

    SECRET_BRANCH = auto()           # Branch condition depends on secret
    SECRET_INDEX = auto()            # Array index depends on secret
    VARIABLE_LATENCY_OP = auto()     # Variable-latency op on secret data
    SECRET_LOOP_BOUND = auto()       # Loop iteration count depends on secret


@dataclass(frozen=True, slots=True)
class Violation:
    """A single constant-time violation found during analysis."""

    kind: ViolationKind
    signal_name: str
    location: str
    message: str
    taint_path: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        path_str = " -> ".join(self.taint_path) if self.taint_path else "N/A"
        return (
            f"[{self.kind.name}] {self.signal_name} at {self.location}: "
            f"{self.message} (path: {path_str})"
        )


@dataclass(slots=True)
class CTReport:
    """Report produced by the constant-time verifier."""

    module_name: str
    violations: list[Violation] = field(default_factory=list)
    signals_analyzed: int = 0
    branches_analyzed: int = 0
    taint_graph_nodes: int = 0

    @property
    def is_constant_time(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        status = "PASS" if self.is_constant_time else "FAIL"
        lines = [
            f"Constant-Time Report: {self.module_name} [{status}]",
            f"  Signals analyzed:  {self.signals_analyzed}",
            f"  Branches analyzed: {self.branches_analyzed}",
            f"  Taint graph nodes: {self.taint_graph_nodes}",
            f"  Violations:        {len(self.violations)}",
        ]
        for v in self.violations:
            lines.append(f"    - {v}")
        return "\n".join(lines)


@dataclass(slots=True)
class _DFGNode:
    """Node in the internal dataflow graph."""

    name: str
    taint: TaintLevel = TaintLevel.PUBLIC
    dependents: list[_DFGNode] = field(default_factory=list)
    is_branch_condition: bool = False
    is_array_index: bool = False
    is_variable_latency: bool = False
    is_loop_bound: bool = False
    location: str = ""


class ConstantTimeVerifier:
    """Verifies that a hardware module operates in constant time.

    Workflow:
        1. ``mark_secret()`` / ``mark_public()`` to annotate signals.
        2. Register dataflow edges via ``add_dependency()``.
        3. Annotate control-flow sensitive nodes.
        4. Call ``verify()`` to propagate taint and check for violations.
    """

    def __init__(self, module_name: str) -> None:
        self._module_name: str = module_name
        self._nodes: dict[str, _DFGNode] = {}

    # ── Signal annotation ──────────────────────────────────────────

    def _get_or_create(self, name: str) -> _DFGNode:
        if name not in self._nodes:
            self._nodes[name] = _DFGNode(name=name)
        return self._nodes[name]

    def mark_secret(self, *names: str, location: str = "") -> None:
        """Mark one or more signals as secret (sensitive) data."""
        for name in names:
            node = self._get_or_create(name)
            node.taint = TaintLevel.SECRET
            if location:
                node.location = location

    def mark_public(self, *names: str, location: str = "") -> None:
        """Mark one or more signals as public (non-sensitive) data."""
        for name in names:
            node = self._get_or_create(name)
            node.taint = TaintLevel.PUBLIC
            if location:
                node.location = location

    # ── Dataflow graph construction ────────────────────────────────

    def add_dependency(self, source: str, sink: str) -> None:
        """Register a dataflow edge: *sink* depends on *source*."""
        src_node = self._get_or_create(source)
        snk_node = self._get_or_create(sink)
        src_node.dependents.append(snk_node)

    def mark_branch_condition(self, name: str, location: str = "") -> None:
        """Mark a signal as being used in a branch/mux select condition."""
        node = self._get_or_create(name)
        node.is_branch_condition = True
        if location:
            node.location = location

    def mark_array_index(self, name: str, location: str = "") -> None:
        """Mark a signal as being used as an array/memory index."""
        node = self._get_or_create(name)
        node.is_array_index = True
        if location:
            node.location = location

    def mark_variable_latency(self, name: str, location: str = "") -> None:
        """Mark a signal as input to a variable-latency operation (e.g. division)."""
        node = self._get_or_create(name)
        node.is_variable_latency = True
        if location:
            node.location = location

    def mark_loop_bound(self, name: str, location: str = "") -> None:
        """Mark a signal as controlling a loop iteration count."""
        node = self._get_or_create(name)
        node.is_loop_bound = True
        if location:
            node.location = location

    # ── Taint propagation and verification ─────────────────────────

    def verify(self) -> CTReport:
        """Propagate taint through the dataflow graph and report violations."""
        report = CTReport(
            module_name=self._module_name,
            taint_graph_nodes=len(self._nodes),
        )

        # Phase 1: propagate taint to fixpoint
        self._propagate_taint()

        # Phase 2: check control-flow dependencies
        violations: list[Violation] = []
        branches_analyzed: int = 0

        for node in self._nodes.values():
            report.signals_analyzed += 1
            is_tainted = node.taint in (TaintLevel.SECRET, TaintLevel.MIXED)

            if node.is_branch_condition:
                branches_analyzed += 1
                if is_tainted:
                    path = self._trace_taint_path(node)
                    violations.append(Violation(
                        kind=ViolationKind.SECRET_BRANCH,
                        signal_name=node.name,
                        location=node.location,
                        message="Branch condition depends on secret data",
                        taint_path=path,
                    ))

            if node.is_array_index and is_tainted:
                path = self._trace_taint_path(node)
                violations.append(Violation(
                    kind=ViolationKind.SECRET_INDEX,
                    signal_name=node.name,
                    location=node.location,
                    message="Array index depends on secret data (cache timing)",
                    taint_path=path,
                ))

            if node.is_variable_latency and is_tainted:
                path = self._trace_taint_path(node)
                violations.append(Violation(
                    kind=ViolationKind.VARIABLE_LATENCY_OP,
                    signal_name=node.name,
                    location=node.location,
                    message="Variable-latency operation on secret data",
                    taint_path=path,
                ))

            if node.is_loop_bound and is_tainted:
                path = self._trace_taint_path(node)
                violations.append(Violation(
                    kind=ViolationKind.SECRET_LOOP_BOUND,
                    signal_name=node.name,
                    location=node.location,
                    message="Loop bound depends on secret data",
                    taint_path=path,
                ))

        report.violations = violations
        report.branches_analyzed = branches_analyzed
        return report

    def _propagate_taint(self) -> None:
        """Propagate SECRET taint forward through the DFG until fixpoint."""
        changed = True
        while changed:
            changed = False
            for node in self._nodes.values():
                if node.taint not in (TaintLevel.SECRET, TaintLevel.MIXED):
                    continue
                for dep in node.dependents:
                    if dep.taint == TaintLevel.PUBLIC:
                        dep.taint = TaintLevel.SECRET
                        changed = True
                    elif dep.taint == TaintLevel.SECRET and node.taint == TaintLevel.MIXED:
                        # Already tainted -- no change needed
                        pass

    def _trace_taint_path(self, target: _DFGNode) -> list[str]:
        """BFS backwards through the DFG to find the shortest secret source path."""
        # Build reverse adjacency
        reverse: dict[str, list[str]] = {n: [] for n in self._nodes}
        for node in self._nodes.values():
            for dep in node.dependents:
                reverse[dep.name].append(node.name)

        # BFS from target back to a SECRET source
        visited: set[str] = {target.name}
        queue: list[list[str]] = [[target.name]]

        while queue:
            path = queue.pop(0)
            current_name = path[-1]
            current_node = self._nodes[current_name]

            if current_node.taint == TaintLevel.SECRET and current_name != target.name:
                return list(reversed(path))

            for pred_name in reverse.get(current_name, []):
                if pred_name not in visited:
                    visited.add(pred_name)
                    queue.append([*path, pred_name])

        return [target.name]
