"""Phase 4 Pydantic v2 regression runner.

A parallel test-suite runner with the spec-compliant API:
``TestSpec`` / ``TestResult`` / ``TestSuite`` / ``RegressionRunner``.

Runs each (test, seed) pair through Verilator or Icarus in a
:class:`concurrent.futures.ProcessPoolExecutor`, records per-run
artefacts, and can detect flaky tests by re-running N times.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Callable


class TestStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIP = "skip"


class TestSpec(BaseModel):
    name: str
    rtl_files: list[str] = Field(default_factory=list)
    tb_file: str = ""
    sim_args: list[str] = Field(default_factory=list)
    expected_output: str = ""
    timeout_s: int = 60
    tags: list[str] = Field(default_factory=list)
    seed_count: int = 1


class TestResult(BaseModel):
    test_name: str
    seed: int
    status: str  # pass | fail | error | timeout | skip
    runtime_s: float = 0.0
    log_path: str = ""
    coverage_path: str = ""
    error_msg: str = ""


class TestSuite(BaseModel):
    name: str
    tests: list[TestSpec] = Field(default_factory=list)
    parallel: int = 4


# ---------------------------------------------------------------------------
# Worker (top-level so it is picklable for ProcessPoolExecutor)
# ---------------------------------------------------------------------------


def _run_one_worker(
    spec_json: str,
    seed: int,
    output_dir: str,
    sim: str,
) -> dict:
    spec = TestSpec.model_validate_json(spec_json)
    out = Path(output_dir)
    work = out / _safe(spec.name) / f"seed_{seed}"
    work.mkdir(parents=True, exist_ok=True)
    log_path = work / "run.log"
    cov_path = work / "coverage.dat"
    start = time.monotonic()
    status = "error"
    err = ""
    log_text = ""
    try:
        if sim == "verilator":
            status, log_text = _run_verilator(spec, seed, work, cov_path)
        elif sim == "icarus":
            status, log_text = _run_icarus(spec, seed, work)
        else:
            status = "error"
            err = f"Unknown simulator: {sim}"
    except subprocess.TimeoutExpired:
        status = "timeout"
        err = "timeout expired"
    except FileNotFoundError as exc:
        status = "error"
        err = f"simulator not found: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        status = "error"
        err = f"exception: {exc}"
    runtime = time.monotonic() - start
    with contextlib.suppress(OSError):
        log_path.write_text(log_text or "", encoding="utf-8")
    return TestResult(
        test_name=spec.name,
        seed=seed,
        status=status,
        runtime_s=runtime,
        log_path=str(log_path),
        coverage_path=str(cov_path) if cov_path.exists() else "",
        error_msg=err,
    ).model_dump()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _run_verilator(
    spec: TestSpec, seed: int, work: Path, cov_path: Path
) -> tuple[str, str]:
    verilator = shutil.which("verilator")
    if not verilator:
        return "error", "verilator not found in PATH"
    obj_dir = work / "obj_dir"
    tb = spec.tb_file or (spec.rtl_files[0] if spec.rtl_files else "")
    top = Path(tb).stem or "top"
    cmd = [
        verilator,
        "--binary",
        "--coverage",
        "-Mdir",
        str(obj_dir),
        "--top-module",
        top,
    ]
    cmd.extend(spec.sim_args)
    for rtl in spec.rtl_files:
        cmd.append(rtl)
    if tb and tb not in spec.rtl_files:
        cmd.append(tb)
    cp = subprocess.run(
        cmd, capture_output=True, text=True, timeout=spec.timeout_s
    )
    log = "$ " + " ".join(cmd) + "\n" + cp.stdout + cp.stderr
    if cp.returncode != 0:
        return "error", log
    binary = obj_dir / f"V{top}"
    if not binary.exists():
        return "error", log + "\nverilator binary missing"
    env = os.environ.copy()
    env["SEED"] = str(seed)
    cp2 = subprocess.run(
        [str(binary), f"+seed={seed}"],
        capture_output=True,
        text=True,
        timeout=spec.timeout_s,
        cwd=str(work),
        env=env,
    )
    log += cp2.stdout + cp2.stderr
    # Verilator writes logs/coverage.dat by default
    produced = work / "logs" / "coverage.dat"
    if produced.exists():
        with contextlib.suppress(OSError):
            shutil.copy(produced, cov_path)
    if cp2.returncode != 0:
        return "fail", log
    if spec.expected_output and spec.expected_output not in log:
        return "fail", log + f"\nexpected output not found: {spec.expected_output}"
    if "$fatal" in log or re.search(r"\bFATAL\b", log):
        return "fail", log
    return "pass", log


def _run_icarus(spec: TestSpec, seed: int, work: Path) -> tuple[str, str]:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        return "error", "iverilog/vvp not found in PATH"
    out_vvp = work / "sim.vvp"
    tb = spec.tb_file or (spec.rtl_files[0] if spec.rtl_files else "")
    top = Path(tb).stem or "top"
    cmd_c = [iverilog, "-g2012", "-o", str(out_vvp), "-s", top]
    cmd_c.extend(spec.sim_args)
    for rtl in spec.rtl_files:
        cmd_c.append(rtl)
    if tb and tb not in spec.rtl_files:
        cmd_c.append(tb)
    cp = subprocess.run(
        cmd_c, capture_output=True, text=True, timeout=spec.timeout_s
    )
    log = "$ " + " ".join(cmd_c) + "\n" + cp.stdout + cp.stderr
    if cp.returncode != 0:
        return "error", log
    cp2 = subprocess.run(
        [vvp, str(out_vvp), f"+seed={seed}"],
        capture_output=True,
        text=True,
        timeout=spec.timeout_s,
        cwd=str(work),
    )
    log += cp2.stdout + cp2.stderr
    if cp2.returncode != 0:
        return "fail", log
    if spec.expected_output and spec.expected_output not in log:
        return "fail", log
    if "$fatal" in log or re.search(r"\bERROR\b", log):
        return "fail", log
    return "pass", log


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class RegressionRunner:
    """Pydantic-driven regression runner."""

    def __init__(
        self,
        suite: TestSuite,
        output_dir: Path,
        sim: str = "verilator",
    ) -> None:
        self.suite = suite
        self.output_dir = Path(output_dir)
        self.sim = sim
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.on_test_start: Callable[[str, int], None] | None = None
        self.on_test_finish: Callable[[TestResult], None] | None = None

    def _jobs(self) -> list[tuple[TestSpec, int]]:
        out: list[tuple[TestSpec, int]] = []
        rng = random.Random(0xC0FFEE)
        for spec in self.suite.tests:
            for _i in range(max(1, spec.seed_count)):
                out.append((spec, rng.randint(1, 2**31 - 1)))
        return out

    def run(self) -> dict[str, TestResult]:
        """Run every (test, seed) pair in parallel and return results."""
        results: dict[str, TestResult] = {}
        jobs = self._jobs()
        if not jobs:
            return results
        workers = max(1, self.suite.parallel)
        # Use ProcessPoolExecutor for true parallelism; fall back if unsupported.
        try:
            executor_cls: type = concurrent.futures.ProcessPoolExecutor
            pool = executor_cls(max_workers=workers)
        except Exception:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        with pool as ex:
            fut_map = {}
            for spec, seed in jobs:
                if self.on_test_start:
                    with contextlib.suppress(Exception):
                        self.on_test_start(spec.name, seed)
                fut = ex.submit(
                    _run_one_worker,
                    spec.model_dump_json(),
                    seed,
                    str(self.output_dir),
                    self.sim,
                )
                fut_map[fut] = (spec, seed)
            for fut in concurrent.futures.as_completed(fut_map):
                spec, seed = fut_map[fut]
                try:
                    data = fut.result()
                    result = TestResult.model_validate(data)
                except Exception as exc:
                    result = TestResult(
                        test_name=spec.name,
                        seed=seed,
                        status="error",
                        error_msg=str(exc),
                    )
                results[f"{spec.name}#{seed}"] = result
                if self.on_test_finish:
                    with contextlib.suppress(Exception):
                        self.on_test_finish(result)
        return results

    def run_one(self, spec: TestSpec, seed: int) -> TestResult:
        data = _run_one_worker(
            spec.model_dump_json(), seed, str(self.output_dir), self.sim
        )
        return TestResult.model_validate(data)

    def detect_flake(self, test_name: str, runs: int = 5) -> float:
        """Re-run *test_name* *runs* times and return its failure rate."""
        spec = next((t for t in self.suite.tests if t.name == test_name), None)
        if spec is None:
            return 0.0
        failures = 0
        for _i in range(runs):
            r = self.run_one(spec, random.randint(1, 2**31 - 1))
            if r.status != "pass":
                failures += 1
        return failures / runs if runs else 0.0

    def export_json(self, results: dict[str, TestResult], path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v.model_dump() for k, v in results.items()}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
