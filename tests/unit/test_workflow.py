"""Tests for the DAG-based flow workflow engine."""

from __future__ import annotations

from openforge.flow.workflow import FlowEngine, FlowResult, FlowStep, StepStatus


def _pass_step(context: dict) -> FlowResult:
    return FlowResult(status=StepStatus.PASSED, output="ok")


def _fail_step(context: dict) -> FlowResult:
    return FlowResult(status=StepStatus.FAILED, errors=["intentional failure"])


def _crash_step(context: dict) -> FlowResult:
    raise RuntimeError("boom")


def test_single_step_pass() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="lint", description="Lint", execute_fn=_pass_step))

    results = engine.run()
    assert results["lint"].status == StepStatus.PASSED


def test_single_step_fail() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="lint", description="Lint", execute_fn=_fail_step))

    results = engine.run()
    assert results["lint"].status == StepStatus.FAILED


def test_exception_becomes_failure() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="crash", description="Crash", execute_fn=_crash_step))

    results = engine.run()
    assert results["crash"].status == StepStatus.FAILED
    assert "boom" in results["crash"].errors[0]


def test_dependency_chain() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="lint", description="Lint", execute_fn=_pass_step))
    engine.add_step(
        FlowStep(name="sim", description="Sim", execute_fn=_pass_step, dependencies=["lint"])
    )
    engine.add_step(
        FlowStep(name="synth", description="Synth", execute_fn=_pass_step, dependencies=["lint"])
    )

    results = engine.run()
    assert all(r.status == StepStatus.PASSED for r in results.values())


def test_dependency_failure_skips_downstream() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="lint", description="Lint", execute_fn=_fail_step))
    engine.add_step(
        FlowStep(name="sim", description="Sim", execute_fn=_pass_step, dependencies=["lint"])
    )

    results = engine.run()
    assert results["lint"].status == StepStatus.FAILED
    assert results["sim"].status == StepStatus.SKIPPED


def test_execution_order_is_topological() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="a", description="A", execute_fn=_pass_step))
    engine.add_step(FlowStep(name="b", description="B", execute_fn=_pass_step, dependencies=["a"]))
    engine.add_step(FlowStep(name="c", description="C", execute_fn=_pass_step, dependencies=["b"]))

    order = engine.get_execution_order()
    assert order.index("a") < order.index("b") < order.index("c")


def test_duration_is_recorded() -> None:
    engine = FlowEngine()
    engine.add_step(FlowStep(name="step", description="Step", execute_fn=_pass_step))

    results = engine.run()
    assert results["step"].duration_seconds >= 0
