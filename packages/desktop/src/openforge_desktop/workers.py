"""QThread workers for long-running EDA operations.

Each worker follows the same pattern established by ``_TestRunnerWorker``
in the testbench panel:

* QThread subclass with typed Signal attributes
* Constructor accepts all parameters needed for the run
* ``run()`` wraps the core library call in try/except
* ``on_output`` callback connected to an ``output_line`` signal
* ``cancel()`` sets a ``_cancelled`` flag checked between stages
"""

from __future__ import annotations

import time
from os import PathLike
from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget


# ═══════════════════════════════════════════════════════════════════════════
# SynthesisWorker
# ═══════════════════════════════════════════════════════════════════════════


class SynthesisWorker(QThread):
    """Run a full RTL-to-gate synthesis flow on a background thread."""

    output_line = Signal(str)
    finished = Signal(object)   # SynthesisResult
    error = Signal(str)
    progress = Signal(str)      # stage description

    def __init__(
        self,
        project_path: Path,
        config: Any,                       # OpenForgeConfig | None
        source_files: Sequence[str | PathLike[str]],
        top_module: str = "top",
        pdk: str = "sky130",
        output_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_path = project_path
        self._config = config
        self._source_files = list(source_files)
        self._top_module = top_module
        self._pdk = pdk
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from openforge.synthesis.runner import SynthesisRunner

            self.progress.emit("Initializing synthesis runner...")
            runner = SynthesisRunner(self._project_path, self._config)

            if self._cancelled:
                return

            self.progress.emit("Reading sources...")

            def _on_output(line: str) -> None:
                self.output_line.emit(line)
                # Detect Yosys stages and emit progress
                low = line.lower().strip()
                if "executing" in low and "read_verilog" in low:
                    self.progress.emit("Reading sources...")
                elif "hierarchy" in low:
                    self.progress.emit("Elaborating...")
                elif "techmap" in low or "abc" in low:
                    self.progress.emit("Mapping...")
                elif "opt" in low and "clean" in low:
                    self.progress.emit("Optimizing...")
                elif "write_verilog" in low or "write_json" in low:
                    self.progress.emit("Writing netlist...")

            result = runner.run_synthesis(
                sources=self._source_files,
                top_module=self._top_module,
                pdk=self._pdk,
                output_dir=self._output_dir,
                on_output=_on_output,
            )

            if not self._cancelled:
                self.progress.emit("Complete")
                self.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# SimulationWorker
# ═══════════════════════════════════════════════════════════════════════════


class SimulationWorker(QThread):
    """Compile and then simulate RTL on a background thread."""

    output_line = Signal(str)
    compile_finished = Signal(object)   # CompileResult
    sim_finished = Signal(object)       # SimResult
    error = Signal(str)

    def __init__(
        self,
        project_path: Path,
        config: Any,                       # OpenForgeConfig | None
        source_files: Sequence[str | PathLike[str]],
        top_module: str = "top",
        tool: str = "verilator",
        trace: bool = True,
        coverage: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_path = project_path
        self._config = config
        self._source_files = list(source_files)
        self._top_module = top_module
        self._tool = tool
        self._trace = trace
        self._coverage = coverage
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from openforge.runner.simulation import SimulationRunner
            from openforge.config.schema import SimulationTool

            tool_map = {
                "verilator": SimulationTool.VERILATOR,
                "icarus": SimulationTool.ICARUS,
                "ghdl": SimulationTool.GHDL,
            }
            tool = tool_map.get(self._tool.lower(), SimulationTool.VERILATOR)

            runner = SimulationRunner(self._project_path, config=self._config)

            def _on_output(line: str) -> None:
                self.output_line.emit(line)

            # Step 1: Compile
            compile_result = runner.compile(
                tool=tool,
                sources=self._source_files,
                top_module=self._top_module,
                trace=self._trace,
                coverage=self._coverage,
                on_output=_on_output,
            )

            if self._cancelled:
                return

            self.compile_finished.emit(compile_result)

            if not compile_result.success:
                self.error.emit(
                    f"Compilation failed with {compile_result.errors_count} error(s)"
                )
                return

            # Step 2: Simulate
            sim_result = runner.simulate(
                tool=tool,
                on_output=_on_output,
            )

            if not self._cancelled:
                self.sim_finished.emit(sim_result)

        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# FormalWorker
# ═══════════════════════════════════════════════════════════════════════════


class FormalWorker(QThread):
    """Run formal verification via SymbiYosys on a background thread."""

    output_line = Signal(str)
    finished = Signal(object)   # FlowResult
    error = Signal(str)

    def __init__(
        self,
        source_files: Sequence[str | PathLike[str]],
        top_module: str = "top",
        properties: Sequence[str] = (),
        depth: int = 20,
        cwd: Path | str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_files = [str(s) for s in source_files]
        self._top_module = top_module
        self._properties = list(properties)
        self._depth = depth
        self._cwd = str(cwd) if cwd else None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from openforge.flow.formal import run_formal

            context: dict[str, Any] = {
                "source_files": self._source_files,
                "top_module": self._top_module,
                "properties": self._properties,
                "formal_depth": self._depth,
                "cwd": self._cwd,
            }

            result = run_formal(context)

            if not self._cancelled:
                # Emit output lines from the result
                if result.output:
                    for line in result.output.splitlines():
                        self.output_line.emit(line)
                self.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# TimingWorker
# ═══════════════════════════════════════════════════════════════════════════


class TimingWorker(QThread):
    """Run static timing analysis via OpenSTA on a background thread."""

    output_line = Signal(str)
    finished = Signal(object)   # TimingResult
    error = Signal(str)

    def __init__(
        self,
        liberty_path: Path | str,
        netlist_path: Path | str,
        sdc_path: Path | str,
        top_module: str = "top",
        num_paths: int = 50,
        cwd: Path | str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._liberty_path = str(liberty_path)
        self._netlist_path = str(netlist_path)
        self._sdc_path = str(sdc_path)
        self._top_module = top_module
        self._num_paths = num_paths
        self._cwd = str(cwd) if cwd else None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from openforge.physical.timing import TimingAnalyzer

            analyzer = TimingAnalyzer()
            result = analyzer.run_analysis(
                liberty=self._liberty_path,
                netlist=self._netlist_path,
                sdc=self._sdc_path,
                top_module=self._top_module,
                num_paths=self._num_paths,
                cwd=self._cwd,
            )

            if not self._cancelled:
                self.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# LintWorker
# ═══════════════════════════════════════════════════════════════════════════


class LintWorker(QThread):
    """Run Verible linting on a background thread."""

    output_line = Signal(str)
    finished = Signal(object)   # ToolResult
    error = Signal(str)

    def __init__(
        self,
        source_files: Sequence[str | PathLike[str]],
        cwd: Path | str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_files = [str(s) for s in source_files]
        self._cwd = str(cwd) if cwd else None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from openforge.engine.verible import VeribleEngine

            engine = VeribleEngine()
            result = engine.lint(self._source_files, cwd=self._cwd)

            if not self._cancelled:
                # Stream lint output
                combined = result.stdout + result.stderr
                for line in combined.splitlines():
                    self.output_line.emit(line)
                self.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# ToolCheckWorker
# ═══════════════════════════════════════════════════════════════════════════


class ToolCheckWorker(QThread):
    """Check installed status and version of all EDA tool engines."""

    tool_checked = Signal(str, bool, str)  # engine_name, installed, version
    all_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from openforge.engine.verilator import VerilatorEngine
        from openforge.engine.icarus import IcarusEngine
        from openforge.engine.ghdl import GHDLEngine
        from openforge.engine.yosys import YosysEngine
        from openforge.engine.symbiyosys import SymbiYosysEngine
        from openforge.engine.opensta import OpenSTAEngine
        from openforge.engine.openroad import OpenROADEngine
        from openforge.engine.magic import MagicEngine
        from openforge.engine.netgen import NetgenEngine
        from openforge.engine.verible import VeribleEngine
        from openforge.engine.klayout import KLayoutEngine
        from openforge.engine.cocotb import CocotbEngine

        engines: list[tuple[str, Any]] = [
            ("Verilator", VerilatorEngine()),
            ("Icarus Verilog", IcarusEngine()),
            ("GHDL", GHDLEngine()),
            ("Yosys", YosysEngine()),
            ("SymbiYosys", SymbiYosysEngine()),
            ("OpenSTA", OpenSTAEngine()),
            ("OpenROAD", OpenROADEngine()),
            ("Magic", MagicEngine()),
            ("Netgen", NetgenEngine()),
            ("Verible", VeribleEngine()),
            ("KLayout", KLayoutEngine()),
            ("cocotb", CocotbEngine()),
        ]

        for name, engine in engines:
            if self._cancelled:
                break
            try:
                installed = engine.check_installed()
                ver = engine.version() if installed else ""
            except Exception:
                installed = False
                ver = ""
            self.tool_checked.emit(name, installed, ver)

        if not self._cancelled:
            self.all_finished.emit()
