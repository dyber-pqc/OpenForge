"""Parallel regression test runner for OpenForge.

The :class:`RegressionRunner` discovers SystemVerilog/Verilog testbenches
in a directory tree, runs them in parallel through a configured simulator
backend (Icarus by default, Verilator optional), and produces both a text
summary and a self contained HTML report.

Per-test artefacts are written under ``regression_results/<test_name>/``
including the simulator command, full log, and any waveform produced by
the test.
"""

from __future__ import annotations

import concurrent.futures
import html
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

try:  # pragma: no cover - optional yaml
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

import contextlib

from .coverage import CoverageParser, CoverageReport

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    """A single regression test definition."""

    name: str
    sources: list[Path] = field(default_factory=list)
    testbench: Path = field(default_factory=Path)
    top_module: str = ""
    timeout_seconds: int = 60
    expected_result: str = "pass"  # pass / fail / error
    seed: int | None = None
    plusargs: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def with_seed(self, seed: int) -> TestCase:
        return TestCase(
            name=self.name,
            sources=list(self.sources),
            testbench=self.testbench,
            top_module=self.top_module,
            timeout_seconds=self.timeout_seconds,
            expected_result=self.expected_result,
            seed=seed,
            plusargs=dict(self.plusargs),
            tags=list(self.tags),
        )


@dataclass
class TestResult:
    """Outcome of a single test run."""

    test: TestCase
    status: str = "pending"  # passed / failed / error / timeout / skipped
    duration_s: float = 0.0
    log: str = ""
    coverage: CoverageReport | None = None
    seed_used: int | None = None
    error_message: str = ""
    artifact_dir: Path | None = None
    waveform: Path | None = None

    @property
    def is_pass(self) -> bool:
        return self.status == "passed"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


_TAG_RE = re.compile(r"//\s*(?:tags?|TAGS?)\s*:\s*([\w,\s\-]+)")
_TOP_RE = re.compile(r"//\s*(?:top|TOP)\s*:\s*(\w+)")
_TIMEOUT_RE = re.compile(r"//\s*(?:timeout|TIMEOUT)\s*:\s*(\d+)")
_EXPECT_RE = re.compile(r"//\s*(?:expect|EXPECT)\s*:\s*(pass|fail|error)")
_MODULE_RE = re.compile(r"\bmodule\s+(\w+)")


class RegressionRunner:
    """Run a regression suite of tests in parallel."""

    def __init__(self, max_workers: int = 4, simulator: str = "icarus") -> None:
        self.max_workers = max(1, int(max_workers))
        self.simulator = simulator
        self.results_dir = Path("regression_results")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover_tests(self, test_dir: Path) -> list[TestCase]:
        """Discover tests in *test_dir*.

        A file is considered a test if its name matches ``test_*.v``,
        ``test_*.sv`` or ``*_tb.v`` / ``*_tb.sv``. Header comments may
        provide ``// tags: a,b``, ``// top: module``, ``// timeout: N``
        and ``// expect: pass|fail|error``.
        """
        test_dir = Path(test_dir)
        out: list[TestCase] = []
        if not test_dir.exists():
            return out

        patterns = ("test_*.v", "test_*.sv", "*_tb.v", "*_tb.sv")
        seen: set[Path] = set()
        for pat in patterns:
            for p in test_dir.rglob(pat):
                if p in seen:
                    continue
                seen.add(p)
                tc = self._test_from_file(p, test_dir)
                if tc is not None:
                    out.append(tc)
        out.sort(key=lambda t: t.name)
        return out

    def _test_from_file(self, path: Path, root: Path) -> TestCase | None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        header = "\n".join(text.splitlines()[:30])
        tags: list[str] = []
        m = _TAG_RE.search(header)
        if m:
            tags = [t.strip() for t in m.group(1).split(",") if t.strip()]
        top_match = _TOP_RE.search(header)
        if top_match:
            top = top_match.group(1)
        else:
            mods = _MODULE_RE.findall(text)
            top = mods[-1] if mods else path.stem
        timeout = 60
        tm = _TIMEOUT_RE.search(header)
        if tm:
            with contextlib.suppress(ValueError):
                timeout = int(tm.group(1))
        expect = "pass"
        em = _EXPECT_RE.search(header)
        if em:
            expect = em.group(1)

        rel = path.relative_to(root) if path.is_relative_to(root) else path
        name = str(rel).replace("\\", "/").rsplit(".", 1)[0]

        return TestCase(
            name=name,
            sources=[path],
            testbench=path,
            top_module=top,
            timeout_seconds=timeout,
            expected_result=expect,
            tags=tags,
        )

    # ------------------------------------------------------------------
    # YAML loading
    # ------------------------------------------------------------------
    def load_from_yaml(self, regression_yaml: Path) -> list[TestCase]:
        """Load test definitions from a ``regression.yaml`` file."""
        regression_yaml = Path(regression_yaml)
        if yaml is None:
            raise RuntimeError("PyYAML not installed; cannot load regression yaml")
        data = yaml.safe_load(regression_yaml.read_text(encoding="utf-8")) or {}
        items = data.get("tests", []) if isinstance(data, dict) else data
        base = regression_yaml.parent
        out: list[TestCase] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("id") or "test"
            sources_raw = entry.get("sources") or entry.get("files") or []
            sources = [base / s for s in sources_raw]
            tb = entry.get("testbench") or (sources[0] if sources else "")
            tb_path = base / tb if tb else Path()
            top = entry.get("top") or entry.get("top_module") or ""
            tc = TestCase(
                name=name,
                sources=sources,
                testbench=tb_path,
                top_module=top,
                timeout_seconds=int(entry.get("timeout", 60)),
                expected_result=entry.get("expect", "pass"),
                seed=entry.get("seed"),
                plusargs=dict(entry.get("plusargs") or {}),
                tags=list(entry.get("tags") or []),
            )
            out.append(tc)
        return out

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(
        self,
        tests: list[TestCase],
        on_test_complete: Callable[[TestResult], None] | None = None,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> list[TestResult]:
        """Run *tests* in parallel and return their results."""
        results: list[TestResult] = []
        if not tests:
            return results

        self.results_dir.mkdir(parents=True, exist_ok=True)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            future_map = {executor.submit(self.run_single, t): t for t in tests}
            try:
                for fut in concurrent.futures.as_completed(future_map):
                    if cancellation_check and cancellation_check():
                        for f in future_map:
                            f.cancel()
                        break
                    try:
                        result = fut.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        tc = future_map[fut]
                        result = TestResult(
                            test=tc,
                            status="error",
                            error_message=str(exc),
                        )
                    results.append(result)
                    if on_test_complete is not None:
                        with contextlib.suppress(Exception):
                            on_test_complete(result)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        results.sort(key=lambda r: r.test.name)
        return results

    # ------------------------------------------------------------------
    # Single test
    # ------------------------------------------------------------------
    def run_single(self, test: TestCase) -> TestResult:
        """Run a single test case using the configured simulator."""
        start = time.monotonic()
        artifact = self.results_dir / self._safe(test.name)
        artifact.mkdir(parents=True, exist_ok=True)

        seed = test.seed if test.seed is not None else random.randint(1, 2**31 - 1)
        result = TestResult(
            test=test,
            status="error",
            duration_s=0.0,
            seed_used=seed,
            artifact_dir=artifact,
        )

        try:
            if self.simulator == "icarus":
                status, log, wave = self._run_icarus(test, artifact, seed)
            elif self.simulator == "verilator":
                status, log, wave = self._run_verilator(test, artifact, seed)
            else:
                status, log, wave = "error", f"Unknown simulator: {self.simulator}", None
        except subprocess.TimeoutExpired:
            status, log, wave = "timeout", "Test exceeded timeout", None
        except FileNotFoundError as exc:
            status = "error"
            log = f"Simulator not found: {exc}"
            wave = None
        except Exception as exc:  # pragma: no cover - defensive
            status = "error"
            log = f"Exception: {exc}"
            wave = None

        result.status = self._reconcile(status, test.expected_result)
        result.log = log
        result.waveform = wave
        result.duration_s = time.monotonic() - start

        (artifact / "test.log").write_text(log, encoding="utf-8")
        (artifact / "status.txt").write_text(
            f"{result.status}\nseed={seed}\nduration={result.duration_s:.3f}\n",
            encoding="utf-8",
        )

        # Try to ingest coverage if present.
        cov_file = artifact / "coverage.dat"
        if cov_file.exists():
            with contextlib.suppress(Exception):
                result.coverage = CoverageParser().parse_verilator_dat(cov_file)

        return result

    # ------------------------------------------------------------------
    # Simulator backends
    # ------------------------------------------------------------------
    def _run_icarus(
        self, test: TestCase, artifact: Path, seed: int
    ) -> tuple[str, str, Path | None]:
        iverilog = shutil.which("iverilog")
        vvp = shutil.which("vvp")
        if not iverilog or not vvp:
            return "error", "iverilog/vvp not found in PATH", None

        out_vvp = artifact / "sim.vvp"
        cmd_compile = [iverilog, "-g2012", "-o", str(out_vvp)]
        if test.top_module:
            cmd_compile += ["-s", test.top_module]
        for src in test.sources:
            cmd_compile.append(str(src))

        log_lines: list[str] = []
        log_lines.append("$ " + " ".join(cmd_compile))
        cp = subprocess.run(
            cmd_compile,
            capture_output=True,
            text=True,
            timeout=test.timeout_seconds,
        )
        log_lines.append(cp.stdout)
        log_lines.append(cp.stderr)
        if cp.returncode != 0:
            return "error", "\n".join(log_lines), None

        cmd_run = [vvp, str(out_vvp)]
        for k, v in test.plusargs.items():
            cmd_run.append(f"+{k}={v}")
        cmd_run.append(f"+seed={seed}")
        log_lines.append("$ " + " ".join(cmd_run))

        cp2 = subprocess.run(
            cmd_run,
            capture_output=True,
            text=True,
            timeout=test.timeout_seconds,
            cwd=str(artifact),
        )
        log_lines.append(cp2.stdout)
        log_lines.append(cp2.stderr)

        log_text = "\n".join(log_lines)
        wave: Path | None = None
        for cand in ("dump.vcd", "wave.vcd", f"{test.top_module}.vcd"):
            p = artifact / cand
            if p.exists():
                wave = p
                break

        if cp2.returncode != 0:
            return "failed", log_text, wave
        if "$fatal" in log_text or "FATAL" in log_text:
            return "failed", log_text, wave
        if re.search(r"\bERROR\b", log_text):
            return "failed", log_text, wave
        return "passed", log_text, wave

    def _run_verilator(
        self, test: TestCase, artifact: Path, seed: int
    ) -> tuple[str, str, Path | None]:
        verilator = shutil.which("verilator")
        if not verilator:
            return "error", "verilator not found in PATH", None
        cmd = [
            verilator,
            "--binary",
            "--coverage",
            "-Mdir",
            str(artifact / "obj_dir"),
            "--top-module",
            test.top_module or test.testbench.stem,
        ]
        for src in test.sources:
            cmd.append(str(src))
        cp = subprocess.run(
            cmd, capture_output=True, text=True, timeout=test.timeout_seconds
        )
        log = "$ " + " ".join(cmd) + "\n" + cp.stdout + cp.stderr
        if cp.returncode != 0:
            return "error", log, None
        binary = artifact / "obj_dir" / f"V{test.top_module}"
        if not binary.exists():
            return "error", log + "\nVerilator binary not produced", None
        cp2 = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
            timeout=test.timeout_seconds,
            cwd=str(artifact),
        )
        log += cp2.stdout + cp2.stderr
        wave = artifact / "dump.vcd"
        return ("passed" if cp2.returncode == 0 else "failed"), log, wave if wave.exists() else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", name)

    @staticmethod
    def _reconcile(actual: str, expected: str) -> str:
        if expected == "pass":
            return actual
        if expected == "fail":
            if actual == "failed":
                return "passed"
            if actual == "passed":
                return "failed"
            return actual
        if expected == "error":
            if actual == "error":
                return "passed"
            return "failed"
        return actual

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def generate_summary(self, results: list[TestResult]) -> str:
        total = len(results)
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        errors = sum(1 for r in results if r.status == "error")
        timeouts = sum(1 for r in results if r.status == "timeout")
        skipped = sum(1 for r in results if r.status == "skipped")
        total_time = sum(r.duration_s for r in results)

        lines = []
        lines.append("=" * 72)
        lines.append("OpenForge Regression Summary")
        lines.append("=" * 72)
        lines.append(f"Total:    {total}")
        lines.append(f"Passed:   {passed}")
        lines.append(f"Failed:   {failed}")
        lines.append(f"Errors:   {errors}")
        lines.append(f"Timeouts: {timeouts}")
        lines.append(f"Skipped:  {skipped}")
        lines.append(f"Time:     {total_time:.2f}s")
        lines.append("-" * 72)
        for r in results:
            mark = {
                "passed": "PASS",
                "failed": "FAIL",
                "error": "ERR ",
                "timeout": "TOUT",
                "skipped": "SKIP",
            }.get(r.status, "????")
            lines.append(f"  [{mark}] {r.test.name:<50} {r.duration_s:>7.2f}s")
        lines.append("=" * 72)
        return "\n".join(lines)

    def generate_html_report(
        self, results: list[TestResult], output: Path
    ) -> Path:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        total = len(results)
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        errors = sum(1 for r in results if r.status == "error")
        pct = (passed / total * 100.0) if total else 0.0

        rows = []
        for r in results:
            color = {
                "passed": "#a6e3a1",
                "failed": "#f38ba8",
                "error": "#fab387",
                "timeout": "#f9e2af",
                "skipped": "#6c7086",
            }.get(r.status, "#cdd6f4")
            tags = ", ".join(html.escape(t) for t in r.test.tags)
            rows.append(
                f"<tr><td>{html.escape(r.test.name)}</td>"
                f"<td style='color:{color}'>{r.status}</td>"
                f"<td class='num'>{r.duration_s:.2f}s</td>"
                f"<td>{tags}</td>"
                f"<td><pre>{html.escape(r.log[-400:])}</pre></td></tr>"
            )

        body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Regression Report</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
       background:#11111b; color:#cdd6f4; margin:0; }}
header {{ padding:1rem 2rem; background:#181825; border-bottom:1px solid #313244; }}
h1 {{ margin:0; color:#cba6f7; }}
.stats {{ display:flex; gap:2rem; padding:1rem 2rem; }}
.stat {{ background:#1e1e2e; padding:.75rem 1.25rem; border-radius:6px; }}
.stat .v {{ font-size:1.6rem; font-weight:600; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ padding:.4rem .75rem; text-align:left; border-bottom:1px solid #313244;
         vertical-align:top; }}
th {{ background:#181825; color:#94a3b8; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
pre {{ margin:0; max-height:6em; overflow:auto; font-size:.75rem;
      color:#94a3b8; background:#181825; padding:.4rem; border-radius:4px; }}
</style></head>
<body>
<header><h1>Regression Report</h1></header>
<div class='stats'>
  <div class='stat'><div>Total</div><div class='v'>{total}</div></div>
  <div class='stat'><div>Passed</div><div class='v' style='color:#a6e3a1'>{passed}</div></div>
  <div class='stat'><div>Failed</div><div class='v' style='color:#f38ba8'>{failed}</div></div>
  <div class='stat'><div>Errors</div><div class='v' style='color:#fab387'>{errors}</div></div>
  <div class='stat'><div>Pass %</div><div class='v'>{pct:.1f}%</div></div>
</div>
<table>
<thead><tr><th>Name</th><th>Status</th><th>Duration</th><th>Tags</th><th>Log Tail</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>
"""
        output.write_text(body, encoding="utf-8")
        return output

    # ------------------------------------------------------------------
    # CI templates
    # ------------------------------------------------------------------
    def generate_ci_templates(self, output_dir: Path) -> dict[str, Path]:
        """Drop GitHub Actions and GitLab CI templates into *output_dir*."""
        output_dir = Path(output_dir)
        gh_dir = output_dir / ".github" / "workflows"
        gh_dir.mkdir(parents=True, exist_ok=True)
        gh = gh_dir / "openforge-test.yml"
        gh.write_text(
            """name: OpenForge Tests
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup OpenForge
        run: |
          pip install openforge-cli
      - name: Install simulators
        run: |
          sudo apt-get update
          sudo apt-get install -y iverilog verilator
      - name: Run Regression
        run: |
          openforge regression run --parallel 4 --report results.html
      - uses: actions/upload-artifact@v4
        with:
          name: regression-results
          path: results.html
""",
            encoding="utf-8",
        )

        gl = output_dir / ".gitlab-ci.yml"
        gl.write_text(
            """stages:
  - verify

openforge-regression:
  stage: verify
  image: python:3.12-slim
  before_script:
    - apt-get update && apt-get install -y iverilog verilator
    - pip install openforge-cli
  script:
    - openforge regression run --parallel 4 --report results.html
  artifacts:
    when: always
    paths:
      - results.html
      - regression_results/
    reports:
      junit: regression_results/junit.xml
""",
            encoding="utf-8",
        )

        return {"github": gh, "gitlab": gl}
