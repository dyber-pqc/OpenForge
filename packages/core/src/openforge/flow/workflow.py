"""DAG-based workflow engine for OpenForge verification and design flows."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:
    from collections.abc import Callable


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FlowResult:
    status: StepStatus
    duration_seconds: float = 0.0
    output: str = ""
    errors: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class FlowStep:
    name: str
    description: str
    execute_fn: Callable[..., FlowResult]
    dependencies: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: FlowResult | None = None


class FlowEngine:
    """DAG-based flow engine that resolves dependencies and executes steps in order."""

    def __init__(self) -> None:
        self.steps: dict[str, FlowStep] = {}
        self.graph = nx.DiGraph()

    def add_step(self, step: FlowStep) -> None:
        self.steps[step.name] = step
        self.graph.add_node(step.name)
        for dep in step.dependencies:
            self.graph.add_edge(dep, step.name)

    def get_execution_order(self) -> list[str]:
        """Return topologically sorted execution order."""
        if not nx.is_directed_acyclic_graph(self.graph):
            raise ValueError("Flow graph contains cycles")
        return list(nx.topological_sort(self.graph))

    def run(self, context: dict[str, Any] | None = None) -> dict[str, FlowResult]:
        """Execute all steps in dependency order."""
        context = context or {}
        results: dict[str, FlowResult] = {}
        order = self.get_execution_order()

        for step_name in order:
            step = self.steps[step_name]

            # Check if all dependencies passed
            deps_ok = all(
                results.get(dep, FlowResult(status=StepStatus.PASSED)).status == StepStatus.PASSED
                for dep in step.dependencies
            )

            if not deps_ok:
                step.status = StepStatus.SKIPPED
                step.result = FlowResult(
                    status=StepStatus.SKIPPED, output="Skipped: dependency failed"
                )
                results[step_name] = step.result
                continue

            step.status = StepStatus.RUNNING
            start = time.monotonic()

            try:
                result = step.execute_fn(context)
                result.duration_seconds = time.monotonic() - start
                step.result = result
                step.status = result.status
            except Exception as e:
                step.status = StepStatus.FAILED
                step.result = FlowResult(
                    status=StepStatus.FAILED,
                    duration_seconds=time.monotonic() - start,
                    errors=[str(e)],
                )

            results[step_name] = step.result

        return results

    def run_step(self, step_name: str, context: dict[str, Any] | None = None) -> FlowResult:
        """Execute a single step (ignoring dependencies)."""
        step = self.steps[step_name]
        context = context or {}

        step.status = StepStatus.RUNNING
        start = time.monotonic()

        try:
            result = step.execute_fn(context)
            result.duration_seconds = time.monotonic() - start
            step.result = result
            step.status = result.status
        except Exception as e:
            step.status = StepStatus.FAILED
            step.result = FlowResult(
                status=StepStatus.FAILED,
                duration_seconds=time.monotonic() - start,
                errors=[str(e)],
            )

        return step.result
