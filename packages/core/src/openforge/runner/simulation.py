"""Simulation runner -- compile, simulate, and run cocotb testbenches."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any, Sequence

from openforge.config.loader import load_config
from openforge.config.schema import OpenForgeConfig, SimulationTool
from openforge.engine.base import ExecutionBackend
from openforge.engine.cocotb import CocotbEngine
from openforge.engine.ghdl import GHDLEngine
from openforge.engine.icarus import IcarusEngine
from openforge.engine.verilator import VerilatorEngine
from openforge.runner.process import ProcessResult, ProcessRunner


def _auto_engine(cls, docker_image: str = ""):
    """Create an engine, falling back to Docker if native binary not found."""
    engine = cls()
    if not engine.check_installed() and docker_image:
        engine = cls(backend=ExecutionBackend.DOCKER)
        engine.docker_image = docker_image
    return engine


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Outcome of an RTL compilation step."""

    success: bool
    log: str = ""
    duration: float = 0.0
    warnings_count: int = 0
    errors_count: int = 0


@dataclass(frozen=True, slots=True)
class SimResult:
    """Outcome of an RTL simulation run."""

    success: bool
    log: str = ""
    duration: float = 0.0
    wave_file: str | None = None
    coverage_file: str | None = None
    test_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CocotbTestDetail:
    """Result details for a single cocotb test function."""

    name: str
    status: str  # "passed", "failed", "error", "skipped"
    duration: float = 0.0
    log: str = ""


@dataclass(frozen=True, slots=True)
class CocotbResult:
    """Outcome of a cocotb test run."""

    success: bool
    tests_passed: int = 0
    tests_failed: int = 0
    test_details: list[CocotbTestDetail] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_warnings(text: str) -> int:
    """Count warning-like lines in compiler output."""
    return len(re.findall(r"(?i)%?warning", text))


def _count_errors(text: str) -> int:
    """Count error-like lines in compiler output."""
    return len(re.findall(r"(?i)%?error", text))


def _find_wave_file(directory: Path, formats: Sequence[str] = ("fst", "vcd", "ghw")) -> str | None:
    """Locate the first waveform file in *directory*."""
    for fmt in formats:
        for f in directory.glob(f"*.{fmt}"):
            return str(f)
    return None


def _find_coverage_file(directory: Path) -> str | None:
    """Locate coverage data in *directory*."""
    for pattern in ("*.dat", "coverage.*", "*.cov"):
        for f in directory.glob(pattern):
            return str(f)
    return None


def _parse_cocotb_output(log: str) -> tuple[int, int, list[CocotbTestDetail]]:
    """Parse cocotb runner output into structured test results."""
    details: list[CocotbTestDetail] = []
    passed = 0
    failed = 0

    # cocotb summary lines look like:
    #   test_name                           PASS  (  0.12s)
    #   test_name                           FAIL  (  1.23s)
    for match in re.finditer(
        r"^\s*(\S+)\s+(PASS|FAIL|ERROR|SKIP)\s+\(\s*([\d.]+)s\)",
        log,
        re.MULTILINE,
    ):
        name = match.group(1)
        status_str = match.group(2).lower()
        dur = float(match.group(3))
        status = "passed" if status_str == "pass" else status_str.replace("fail", "failed")
        if status == "passed":
            passed += 1
        elif status in ("failed", "error"):
            failed += 1
        details.append(CocotbTestDetail(name=name, status=status, duration=dur))

    # Fallback: look for "N passed, M failed" summary line
    if not details:
        if m := re.search(r"(\d+)\s+passed", log):
            passed = int(m.group(1))
        if m := re.search(r"(\d+)\s+failed", log):
            failed = int(m.group(1))

    return passed, failed, details


# ---------------------------------------------------------------------------
# SimulationRunner
# ---------------------------------------------------------------------------


class SimulationRunner:
    """High-level simulation runner that orchestrates compile + simulate pipelines.

    Uses the engine wrappers from :mod:`openforge.engine` and streams
    output through :class:`ProcessRunner` for real-time feedback.
    """

    def __init__(
        self,
        project_path: str | PathLike[str],
        config: OpenForgeConfig | None = None,
    ) -> None:
        self._project_path = Path(project_path).resolve()
        if config is not None:
            self._config = config
        else:
            self._config = load_config(search_dir=self._project_path)

    @property
    def project_path(self) -> Path:
        return self._project_path

    @property
    def config(self) -> OpenForgeConfig:
        return self._config

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------

    def compile(
        self,
        tool: SimulationTool | str = SimulationTool.VERILATOR,
        sources: Sequence[str | PathLike[str]] = (),
        *,
        top_module: str | None = None,
        output_dir: str | PathLike[str] | None = None,
        includes: Sequence[str | PathLike[str]] = (),
        trace: bool = True,
        coverage: bool = False,
        timeout: float | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> CompileResult:
        """Compile RTL sources using the specified simulator.

        Parameters
        ----------
        tool:
            Simulator backend to use for compilation.
        sources:
            RTL source files. Falls back to ``config.design.sources`` when empty.
        top_module:
            Top-level module name. Falls back to ``config.project.top_module``.
        output_dir:
            Build artefact directory. Defaults to ``sim_build/``.
        includes:
            Include search paths.
        trace:
            Enable waveform tracing during simulation.
        coverage:
            Enable code-coverage instrumentation.
        timeout:
            Compilation timeout in seconds.
        on_output:
            Callback invoked with each line of compiler output.
        """
        tool = SimulationTool(tool) if isinstance(tool, str) else tool
        top = top_module or self._config.project.top_module
        out_dir = Path(output_dir) if output_dir else self._project_path / "sim_build"
        out_dir.mkdir(parents=True, exist_ok=True)
        # Use relative output dir for Docker compatibility
        try:
            rel_out_dir = out_dir.relative_to(self._project_path)
        except ValueError:
            rel_out_dir = out_dir

        resolved_sources = [Path(s).as_posix() for s in (sources or self._config.design.sources)]
        resolved_includes = [Path(i).as_posix() for i in (includes or self._config.design.includes)]

        start = time.monotonic()

        if tool == SimulationTool.VERILATOR:
            return self._compile_verilator(
                resolved_sources, top, rel_out_dir, resolved_includes,
                trace, coverage, timeout, on_output,
            )
        elif tool == SimulationTool.ICARUS:
            return self._compile_icarus(
                resolved_sources, top, rel_out_dir, resolved_includes,
                timeout, on_output,
            )
        elif tool == SimulationTool.GHDL:
            return self._compile_ghdl(
                resolved_sources, top, rel_out_dir, timeout, on_output,
            )
        else:
            return CompileResult(
                success=False,
                log=f"Unsupported simulation tool: {tool}",
                duration=time.monotonic() - start,
                errors_count=1,
            )

    def _compile_verilator(
        self,
        sources: list[str | PathLike[str]],
        top_module: str,
        output_dir: Path,
        includes: list[str | PathLike[str]],
        trace: bool,
        coverage: bool,
        timeout: float | None,
        on_output: Callable[[str], None] | None,
    ) -> CompileResult:
        engine = _auto_engine(VerilatorEngine, "hdlc/sim:latest")
        result = engine.compile(
            sources,
            top_module=top_module,
            output_dir=str(output_dir),
            includes=includes,
            trace=trace,
            coverage=coverage,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)
        return CompileResult(
            success=result.ok,
            log=combined,
            duration=result.duration,
            warnings_count=_count_warnings(combined),
            errors_count=_count_errors(combined),
        )

    def _compile_icarus(
        self,
        sources: list[str | PathLike[str]],
        top_module: str,
        output_dir: Path,
        includes: list[str | PathLike[str]],
        timeout: float | None,
        on_output: Callable[[str], None] | None,
    ) -> CompileResult:
        engine = _auto_engine(IcarusEngine, "hdlc/sim:latest")
        output_file = output_dir / f"{top_module}.vvp"
        result = engine.compile(
            sources,
            top_module=top_module,
            output=output_file.as_posix(),  # POSIX path for Docker
            includes=includes,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)
        return CompileResult(
            success=result.ok,
            log=combined,
            duration=result.duration,
            warnings_count=_count_warnings(combined),
            errors_count=_count_errors(combined),
        )

    def _compile_ghdl(
        self,
        sources: list[str | PathLike[str]],
        top_module: str,
        output_dir: Path,
        timeout: float | None,
        on_output: Callable[[str], None] | None,
    ) -> CompileResult:
        engine = _auto_engine(GHDLEngine, "hdlc/ghdl:latest")
        # GHDL has a two-step process: analyze + elaborate
        analyze_result = engine.analyze(
            sources,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        combined = analyze_result.stdout + analyze_result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        if not analyze_result.ok:
            return CompileResult(
                success=False,
                log=combined,
                duration=analyze_result.duration,
                warnings_count=_count_warnings(combined),
                errors_count=_count_errors(combined),
            )

        elab_result = engine.elaborate(
            top_module,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        elab_combined = elab_result.stdout + elab_result.stderr
        combined += elab_combined
        if on_output:
            for line in elab_combined.splitlines():
                on_output(line)

        return CompileResult(
            success=elab_result.ok,
            log=combined,
            duration=analyze_result.duration + elab_result.duration,
            warnings_count=_count_warnings(combined),
            errors_count=_count_errors(combined),
        )

    # ------------------------------------------------------------------
    # Simulate
    # ------------------------------------------------------------------

    def simulate(
        self,
        tool: SimulationTool | str = SimulationTool.VERILATOR,
        binary_or_top: str | PathLike[str] | None = None,
        *,
        testbenches: Sequence[str | PathLike[str]] = (),
        plusargs: dict[str, str] | None = None,
        timeout: float | None = None,
        wave_format: str = "fst",
        on_output: Callable[[str], None] | None = None,
    ) -> SimResult:
        """Run a simulation with a previously compiled binary or top module.

        Parameters
        ----------
        tool:
            Simulator backend.
        binary_or_top:
            For Verilator: path to the compiled binary.
            For Icarus: path to the ``.vvp`` file.
            For GHDL: top-level entity name.
        testbenches:
            Additional testbench files (unused for most simulators after compile).
        plusargs:
            Simulation plusargs passed as ``+key=value``.
        timeout:
            Simulation timeout in seconds.
        wave_format:
            Waveform dump format (``"fst"``, ``"vcd"``, ``"ghw"``).
        on_output:
            Callback invoked with each line of simulation output.
        """
        tool = SimulationTool(tool) if isinstance(tool, str) else tool
        sim_cfg = self._config.simulation
        resolved_plusargs = dict(plusargs) if plusargs else {}
        if sim_cfg and sim_cfg.plusargs:
            # Config plusargs are defaults; explicit ones override
            merged = dict(sim_cfg.plusargs)
            merged.update(resolved_plusargs)
            resolved_plusargs = merged

        effective_timeout = timeout or (sim_cfg.timeout_seconds if sim_cfg else 300)
        sim_dir = self._project_path / "sim_build"

        if tool == SimulationTool.VERILATOR:
            top = self._config.project.top_module
            binary = binary_or_top or str(sim_dir / f"V{top}")
            return self._simulate_verilator(
                binary, resolved_plusargs, effective_timeout, wave_format, on_output,
            )
        elif tool == SimulationTool.ICARUS:
            top = self._config.project.top_module
            if binary_or_top:
                vvp = str(binary_or_top)
                # If just a name (no path sep, no .vvp), resolve to sim_build
                if "/" not in vvp and "\\" not in vvp and not vvp.endswith(".vvp"):
                    vvp = str(sim_dir / f"{vvp}.vvp")
            else:
                vvp = str(sim_dir / f"{top}.vvp")
            # Use relative POSIX path for Docker compatibility
            try:
                vvp = Path(vvp).relative_to(self._project_path).as_posix()
            except ValueError:
                vvp = Path(vvp).as_posix()
            return self._simulate_icarus(
                vvp, resolved_plusargs, effective_timeout, on_output,
            )
        elif tool == SimulationTool.GHDL:
            top = str(binary_or_top) if binary_or_top else self._config.project.top_module
            return self._simulate_ghdl(
                top, effective_timeout, wave_format, on_output,
            )
        else:
            return SimResult(
                success=False,
                log=f"Unsupported simulation tool: {tool}",
            )

    def _simulate_verilator(
        self,
        binary: str | PathLike[str],
        plusargs: dict[str, str],
        timeout: float,
        wave_format: str,
        on_output: Callable[[str], None] | None,
    ) -> SimResult:
        engine = _auto_engine(VerilatorEngine, "hdlc/sim:latest")
        result = engine.simulate(
            binary,
            plusargs=plusargs,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        wave = _find_wave_file(self._project_path)
        cov = _find_coverage_file(self._project_path / "sim_build")

        return SimResult(
            success=result.ok,
            log=combined,
            duration=result.duration,
            wave_file=wave,
            coverage_file=cov,
        )

    def _simulate_icarus(
        self,
        vvp_file: str | PathLike[str],
        plusargs: dict[str, str],
        timeout: float,
        on_output: Callable[[str], None] | None,
    ) -> SimResult:
        engine = _auto_engine(IcarusEngine, "hdlc/sim:latest")
        result = engine.simulate(
            vvp_file,
            plusargs=plusargs,
            cwd=str(self._project_path),
            timeout=timeout,
        )
        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        wave = _find_wave_file(self._project_path)

        return SimResult(
            success=result.ok,
            log=combined,
            duration=result.duration,
            wave_file=wave,
        )

    def _simulate_ghdl(
        self,
        top_unit: str,
        timeout: float,
        wave_format: str,
        on_output: Callable[[str], None] | None,
    ) -> SimResult:
        engine = _auto_engine(GHDLEngine, "hdlc/ghdl:latest")
        wave_ext = "ghw" if wave_format == "ghw" else "vcd"
        wave_path = self._project_path / f"dump.{wave_ext}"

        kwargs: dict[str, Any] = {}
        if wave_ext == "ghw":
            kwargs["wave_file"] = str(wave_path)
        else:
            kwargs["vcd_file"] = str(wave_path)

        result = engine.simulate(
            top_unit,
            cwd=str(self._project_path),
            timeout=timeout,
            **kwargs,
        )
        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        return SimResult(
            success=result.ok,
            log=combined,
            duration=result.duration,
            wave_file=str(wave_path) if wave_path.exists() else None,
        )

    # ------------------------------------------------------------------
    # Cocotb
    # ------------------------------------------------------------------

    def run_cocotb(
        self,
        test_module: str,
        *,
        top_module: str | None = None,
        simulator: str = "icarus",
        sim_build_dir: str | PathLike[str] | None = None,
        sources: Sequence[str | PathLike[str]] = (),
        on_output: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> CocotbResult:
        """Run cocotb Python testbench(es) against an HDL design.

        Parameters
        ----------
        test_module:
            Python module containing cocotb tests (without ``.py``).
        top_module:
            Top-level HDL module. Falls back to ``config.project.top_module``.
        simulator:
            Underlying simulator (``"icarus"``, ``"verilator"``, ``"ghdl"``).
        sim_build_dir:
            Build directory for cocotb. Defaults to ``sim_build/``.
        sources:
            HDL source files. Falls back to ``config.design.sources``.
        on_output:
            Callback invoked with each line of cocotb output.
        timeout:
            Execution timeout in seconds.
        """
        engine = CocotbEngine()
        top = top_module or self._config.project.top_module
        build_dir = sim_build_dir or str(self._project_path / "sim_build")
        resolved_sources = list(sources) or self._config.design.sources

        result = engine.run_tests(
            test_module=test_module,
            top_module=top,
            simulator=simulator,
            sources=resolved_sources,
            sim_build_dir=str(build_dir),
            cwd=str(self._project_path),
            timeout=timeout,
        )

        combined = result.stdout + result.stderr
        if on_output:
            for line in combined.splitlines():
                on_output(line)

        passed, failed, details = _parse_cocotb_output(combined)

        return CocotbResult(
            success=result.ok and failed == 0,
            tests_passed=passed,
            tests_failed=failed,
            test_details=details,
        )
