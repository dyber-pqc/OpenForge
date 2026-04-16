"""Tests for the run engine DAG executor."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from openforge.runner.engine import RunEngine, RunGraph, RunStage

if TYPE_CHECKING:
    from pathlib import Path


def _echo(msg: str) -> list[str]:
    # cross-platform: use the current Python as a portable echo
    return [sys.executable, "-c", f"print({msg!r})"]


def _sleep(sec: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({sec})"]


def _fail() -> list[str]:
    return [sys.executable, "-c", "import sys; sys.exit(3)"]


def test_two_stage_dag_executes_in_order(tmp_path: Path) -> None:
    eng = RunEngine(tmp_path, max_parallel=2)
    g = RunGraph()
    g.add_stage(RunStage(id="a", name="A", tool="py", command=_echo("hello")))
    g.add_stage(
        RunStage(
            id="b", name="B", tool="py", command=_echo("world"), depends_on=["a"]
        )
    )
    rid = eng.submit(g)
    res = eng.wait(rid, timeout=30)
    assert res["found"]
    statuses = {s["id"]: s["status"] for s in res["stages"]}
    assert statuses == {"a": "success", "b": "success"}
    # verify logs on disk
    log_a = tmp_path / "runs" / rid / "a" / "stage.log"
    assert log_a.exists()
    assert b"hello" in log_a.read_bytes()
    eng.shutdown()


def test_failing_stage_skips_downstream(tmp_path: Path) -> None:
    eng = RunEngine(tmp_path)
    g = RunGraph()
    g.add_stage(RunStage(id="a", name="A", tool="py", command=_fail()))
    g.add_stage(
        RunStage(id="b", name="B", tool="py", command=_echo("hi"), depends_on=["a"])
    )
    rid = eng.submit(g)
    res = eng.wait(rid, timeout=30)
    st = {s["id"]: s["status"] for s in res["stages"]}
    assert st["a"] == "failed"
    assert st["b"] == "skipped"
    eng.shutdown()


def test_cancel(tmp_path: Path) -> None:
    eng = RunEngine(tmp_path)
    g = RunGraph()
    g.add_stage(RunStage(id="a", name="A", tool="py", command=_sleep(5)))
    rid = eng.submit(g)
    time.sleep(0.3)
    eng.cancel(rid)
    res = eng.wait(rid, timeout=10)
    st = {s["id"]: s["status"] for s in res["stages"]}
    assert st["a"] in ("cancelled", "failed")
    eng.shutdown()


def test_rerun_from(tmp_path: Path) -> None:
    eng = RunEngine(tmp_path, max_parallel=2)
    g = RunGraph()
    g.add_stage(RunStage(id="a", name="A", tool="py", command=_echo("aa")))
    g.add_stage(
        RunStage(id="b", name="B", tool="py", command=_echo("bb"), depends_on=["a"])
    )
    g.add_stage(
        RunStage(id="c", name="C", tool="py", command=_echo("cc"), depends_on=["b"])
    )
    rid = eng.submit(g)
    eng.wait(rid, timeout=30)
    new_rid = eng.rerun_from(rid, "b")
    eng.wait(new_rid, timeout=30)
    res = eng.status(new_rid)
    st = {s["id"]: s["status"] for s in res["stages"]}
    assert st == {"a": "success", "b": "success", "c": "success"}
    eng.shutdown()


def test_topological_cycle_detected(tmp_path: Path) -> None:
    g = RunGraph()
    g.add_stage(RunStage(id="a", name="A", tool="t", command=[], depends_on=["b"]))
    g.add_stage(RunStage(id="b", name="B", tool="t", command=[], depends_on=["a"]))
    try:
        g.topological_order()
    except ValueError as e:
        assert "cycle" in str(e)
    else:
        raise AssertionError("expected cycle error")
