"""Testbench manager panel with test discovery, execution, and results display."""

from __future__ import annotations

import re
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette constants
# ---------------------------------------------------------------------------

_CLR_GREEN: Final[str] = "#a6e3a1"
_CLR_RED: Final[str] = "#f38ba8"
_CLR_YELLOW: Final[str] = "#f9e2af"
_CLR_BLUE: Final[str] = "#89b4fa"
_CLR_GRAY: Final[str] = "#585b70"
_CLR_TEXT: Final[str] = "#cdd6f4"
_CLR_SUBTEXT: Final[str] = "#a6adc8"
_CLR_BG: Final[str] = "#1e1e2e"
_CLR_SURFACE0: Final[str] = "#313244"
_CLR_MANTLE: Final[str] = "#181825"
_CLR_PEACH: Final[str] = "#fab387"
_CLR_LAVENDER: Final[str] = "#b4befe"


# ---------------------------------------------------------------------------
# Test status
# ---------------------------------------------------------------------------


class TestStatus(StrEnum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


_STATUS_COLORS: dict[TestStatus, str] = {
    TestStatus.NOT_RUN: _CLR_GRAY,
    TestStatus.RUNNING: _CLR_YELLOW,
    TestStatus.PASSED: _CLR_GREEN,
    TestStatus.FAILED: _CLR_RED,
    TestStatus.ERROR: _CLR_RED,
    TestStatus.SKIPPED: _CLR_SUBTEXT,
}

_STATUS_ICONS: dict[TestStatus, str] = {
    TestStatus.NOT_RUN: "\u25cb",  # empty circle
    TestStatus.RUNNING: "\u25d4",  # circle with upper-right quadrant
    TestStatus.PASSED: "\u25cf",  # filled circle
    TestStatus.FAILED: "\u25cf",  # filled circle (red)
    TestStatus.ERROR: "\u2716",  # heavy multiplication x
    TestStatus.SKIPPED: "\u25cb",  # empty circle
}

_STATUS_LABELS: dict[TestStatus, str] = {
    TestStatus.NOT_RUN: "Not Run",
    TestStatus.RUNNING: "Running...",
    TestStatus.PASSED: "Pass",
    TestStatus.FAILED: "Fail",
    TestStatus.ERROR: "Error",
    TestStatus.SKIPPED: "Skip",
}


# ---------------------------------------------------------------------------
# Test item data
# ---------------------------------------------------------------------------


class TestItemData:
    """Metadata for a single discovered test."""

    __slots__ = ("name", "file_path", "test_type", "status", "duration", "log")

    def __init__(
        self,
        name: str,
        file_path: Path,
        test_type: str,
        status: TestStatus = TestStatus.NOT_RUN,
        duration: float = 0.0,
        log: str = "",
    ) -> None:
        self.name = name
        self.file_path = file_path
        self.test_type = test_type  # "cocotb" or "sv"
        self.status = status
        self.duration = duration
        self.log = log


# ---------------------------------------------------------------------------
# Test runner worker thread
# ---------------------------------------------------------------------------


class _TestRunnerWorker(QThread):
    """Worker thread that runs selected tests and reports progress."""

    test_started = Signal(str)  # test name
    test_finished = Signal(str, str, float, str)  # name, status, duration, log
    output_line = Signal(str)  # live output line
    all_finished = Signal()

    def __init__(
        self,
        test_items: list[TestItemData],
        project_path: Path,
        simulator: str,
        coverage: bool,
        wave_dump: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._test_items = test_items
        self._project_path = project_path
        self._simulator = simulator
        self._coverage = coverage
        self._wave_dump = wave_dump
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for item in self._test_items:
            if self._cancelled:
                break

            self.test_started.emit(item.name)
            start = time.monotonic()
            log_lines: list[str] = []

            try:
                if item.test_type == "cocotb":
                    status = self._run_cocotb_test(item, log_lines)
                else:
                    status = self._run_sv_test(item, log_lines)
            except Exception as exc:
                status = TestStatus.ERROR
                log_lines.append(f"Exception: {exc}")

            duration = time.monotonic() - start
            log = "\n".join(log_lines)
            self.test_finished.emit(item.name, status, duration, log)

        self.all_finished.emit()

    def _run_cocotb_test(
        self,
        item: TestItemData,
        log_lines: list[str],
    ) -> str:
        """Run a cocotb test module."""
        from openforge.config.loader import load_config
        from openforge.runner.simulation import SimulationRunner

        try:
            config = load_config(search_dir=self._project_path)
        except Exception:
            config = None

        try:
            runner = SimulationRunner(self._project_path, config=config)
            result = runner.run_cocotb(
                test_module=item.file_path.stem,
                simulator=self._simulator,
                on_output=lambda line: (
                    log_lines.append(line),
                    self.output_line.emit(line),
                ),
            )
            if result.success:
                return TestStatus.PASSED
            return TestStatus.FAILED
        except Exception as exc:
            log_lines.append(str(exc))
            return TestStatus.ERROR

    def _run_sv_test(
        self,
        item: TestItemData,
        log_lines: list[str],
    ) -> str:
        """Run a SystemVerilog testbench via compile + simulate."""
        from openforge.config.loader import load_config
        from openforge.config.schema import SimulationTool
        from openforge.runner.simulation import SimulationRunner

        tool_map = {
            "verilator": SimulationTool.VERILATOR,
            "icarus": SimulationTool.ICARUS,
            "ghdl": SimulationTool.GHDL,
        }
        tool = tool_map.get(self._simulator.lower(), SimulationTool.VERILATOR)

        try:
            config = load_config(search_dir=self._project_path)
        except Exception:
            config = None

        try:
            runner = SimulationRunner(self._project_path, config=config)

            # Compile with the testbench as an additional source
            sources = list(config.design.sources) if config else []
            sources.append(str(item.file_path))

            compile_result = runner.compile(
                tool=tool,
                sources=sources,
                coverage=self._coverage,
                trace=self._wave_dump,
                on_output=lambda line: (
                    log_lines.append(line),
                    self.output_line.emit(line),
                ),
            )
            if not compile_result.success:
                return TestStatus.FAILED

            sim_result = runner.simulate(
                tool=tool,
                on_output=lambda line: (
                    log_lines.append(line),
                    self.output_line.emit(line),
                ),
            )
            if sim_result.success:
                return TestStatus.PASSED
            return TestStatus.FAILED
        except Exception as exc:
            log_lines.append(str(exc))
            return TestStatus.ERROR


# ---------------------------------------------------------------------------
# Detail log formatting
# ---------------------------------------------------------------------------


def _make_format(color: str, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return fmt


# ---------------------------------------------------------------------------
# TestbenchPanel
# ---------------------------------------------------------------------------


class TestbenchPanel(QDockWidget):
    """Dock widget providing Vivado-style testbench management.

    Features test discovery, selective execution, live progress, and
    detailed result viewing.
    """

    open_file_requested = Signal(str)  # Emitted when user double-clicks a test

    def __init__(self, title: str = "Testbenches", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._project_path: Path | None = None
        self._test_items: dict[str, TestItemData] = {}
        self._worker: _TestRunnerWorker | None = None

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self._toolbar = self._build_toolbar()
        main_layout.addWidget(self._toolbar)

        # Splitter: tree (top) + detail (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Test discovery tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["", "Test Name", "Type", "Status", "Duration"])
        self._tree.setColumnWidth(0, 30)  # checkbox
        self._tree.setColumnWidth(1, 250)  # name
        self._tree.setColumnWidth(2, 60)  # type
        self._tree.setColumnWidth(3, 80)  # status
        self._tree.setColumnWidth(4, 80)  # duration
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(False)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.currentItemChanged.connect(self._on_current_changed)
        splitter.addWidget(self._tree)

        # Detail panel (log output)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(4, 4, 4, 4)
        detail_layout.setSpacing(2)

        self._detail_label = QLabel("Test Details")
        self._detail_label.setStyleSheet(
            f"color: {_CLR_BLUE}; font-weight: bold; font-size: 12px; padding: 2px;"
        )
        detail_layout.addWidget(self._detail_label)

        self._detail_output = QPlainTextEdit()
        self._detail_output.setReadOnly(True)
        self._detail_output.setMaximumBlockCount(50_000)
        font = QFont("JetBrains Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._detail_output.setFont(font)
        detail_layout.addWidget(self._detail_output)

        splitter.addWidget(detail_widget)
        splitter.setSizes([300, 200])
        main_layout.addWidget(splitter, stretch=1)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        main_layout.addWidget(self._progress)

        # Summary line
        self._summary = QLabel("No tests loaded")
        self._summary.setStyleSheet(f"color: {_CLR_SUBTEXT}; padding: 4px 8px; font-size: 12px;")
        main_layout.addWidget(self._summary)

        self.setWidget(container)

    # ── Toolbar ───────────────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        self._btn_run_selected = QPushButton("Run Selected")
        self._btn_run_selected.setStyleSheet(
            f"background: {_CLR_SURFACE0}; color: {_CLR_GREEN}; font-weight: bold;"
        )
        self._btn_run_selected.clicked.connect(self._on_run_selected)
        layout.addWidget(self._btn_run_selected)

        self._btn_run_all = QPushButton("Run All")
        self._btn_run_all.clicked.connect(self._on_run_all)
        layout.addWidget(self._btn_run_all)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setStyleSheet(f"color: {_CLR_RED};")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        layout.addWidget(self._btn_stop)

        layout.addWidget(self._separator())

        # Simulator dropdown
        layout.addWidget(QLabel("Simulator:"))
        self._sim_combo = QComboBox()
        self._sim_combo.addItems(["Verilator", "Icarus", "GHDL"])
        self._sim_combo.setFixedWidth(100)
        layout.addWidget(self._sim_combo)

        layout.addWidget(self._separator())

        # Coverage toggle
        self._chk_coverage = QCheckBox("Coverage")
        self._chk_coverage.setChecked(False)
        layout.addWidget(self._chk_coverage)

        # Waveform dump toggle
        self._chk_wave = QCheckBox("Waveforms")
        self._chk_wave.setChecked(True)
        layout.addWidget(self._chk_wave)

        layout.addWidget(self._separator())

        # Filter
        layout.addWidget(QLabel("Filter:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All", "Passed", "Failed", "Not Run"])
        self._filter_combo.setFixedWidth(80)
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_combo)

        layout.addStretch()

        # Refresh button
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.clicked.connect(self._on_refresh)
        layout.addWidget(self._btn_refresh)

        return toolbar

    @staticmethod
    def _separator() -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {_CLR_SURFACE0};")
        return sep

    # ── Public API ────────────────────────────────────────────────────

    def set_project_path(self, path: Path) -> None:
        """Set the project root and trigger test discovery."""
        self._project_path = path
        self.discover_tests()

    def discover_tests(self) -> None:
        """Scan the project ``tb/`` directory for testbenches."""
        self._tree.clear()
        self._test_items.clear()

        if self._project_path is None:
            self._summary.setText("No project loaded")
            return

        tb_dir = self._project_path / "tb"
        if not tb_dir.is_dir():
            # Also try testbench/ and tests/
            for alt in ("testbench", "tests", "test", "sim"):
                alt_dir = self._project_path / alt
                if alt_dir.is_dir():
                    tb_dir = alt_dir
                    break
            else:
                self._summary.setText(f"No testbench directory found in {self._project_path}")
                return

        self._discover_in_dir(tb_dir)
        self._update_summary()

    def run_selected_tests(self) -> None:
        """Run all tests whose checkboxes are checked."""
        self._on_run_selected()

    def run_all_tests(self) -> None:
        """Run all discovered tests."""
        self._on_run_all()

    def stop_tests(self) -> None:
        """Cancel running tests."""
        self._on_stop()

    def get_selected_tests(self) -> list[TestItemData]:
        """Return the list of checked test items."""
        selected: list[TestItemData] = []
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if group is None:
                continue
            for j in range(group.childCount()):
                child = group.child(j)
                if child is None:
                    continue
                if child.checkState(0) == Qt.CheckState.Checked:
                    name = child.data(1, Qt.ItemDataRole.UserRole)
                    if name and name in self._test_items:
                        selected.append(self._test_items[name])
        return selected

    # ── Discovery ─────────────────────────────────────────────────────

    def _discover_in_dir(self, directory: Path) -> None:
        """Recursively discover test files in *directory*."""
        # Group tests by file
        files: dict[Path, list[TestItemData]] = {}

        for py_file in sorted(directory.rglob("test_*.py")):
            tests = self._discover_cocotb_tests(py_file)
            if tests:
                files[py_file] = tests

        for sv_file in sorted(directory.rglob("*_tb.sv")):
            tests = self._discover_sv_tests(sv_file)
            if tests:
                files[sv_file] = tests

        for sv_file in sorted(directory.rglob("tb_*.sv")):
            if sv_file not in files:
                tests = self._discover_sv_tests(sv_file)
                if tests:
                    files[sv_file] = tests

        # Populate tree
        for file_path, tests in files.items():
            rel = file_path.relative_to(self._project_path) if self._project_path else file_path
            group_item = QTreeWidgetItem(self._tree)
            group_item.setText(1, str(rel))
            group_item.setForeground(1, QColor(_CLR_LAVENDER))
            group_item.setFlags(
                group_item.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            group_item.setCheckState(0, Qt.CheckState.Checked)

            for test in tests:
                self._test_items[test.name] = test
                child = QTreeWidgetItem(group_item)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setText(1, test.name)
                child.setData(1, Qt.ItemDataRole.UserRole, test.name)
                child.setText(2, test.test_type)
                child.setForeground(2, QColor(_CLR_PEACH))
                self._update_tree_item_status(child, test)

        self._tree.expandAll()

    def _discover_cocotb_tests(self, py_file: Path) -> list[TestItemData]:
        """Extract cocotb test function names from a Python file."""
        tests: list[TestItemData] = []
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return tests

        # Match @cocotb.test() decorated async functions
        for match in re.finditer(
            r"@cocotb\.test\b.*?\n\s*async\s+def\s+(\w+)",
            content,
            re.DOTALL,
        ):
            name = match.group(1)
            tests.append(
                TestItemData(
                    name=f"{py_file.stem}::{name}",
                    file_path=py_file,
                    test_type="cocotb",
                )
            )

        # If no decorated tests found, treat the file itself as a test module
        if not tests and "cocotb" in content:
            tests.append(
                TestItemData(
                    name=py_file.stem,
                    file_path=py_file,
                    test_type="cocotb",
                )
            )

        return tests

    def _discover_sv_tests(self, sv_file: Path) -> list[TestItemData]:
        """Extract testbench module names from a SystemVerilog file."""
        tests: list[TestItemData] = []
        try:
            content = sv_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return tests

        # Match module declarations (typically `module xxx_tb;` or `module tb_xxx;`)
        for match in re.finditer(r"\bmodule\s+(\w+)", content):
            mod_name = match.group(1)
            tests.append(
                TestItemData(
                    name=f"{sv_file.stem}::{mod_name}",
                    file_path=sv_file,
                    test_type="sv",
                )
            )

        if not tests:
            tests.append(
                TestItemData(
                    name=sv_file.stem,
                    file_path=sv_file,
                    test_type="sv",
                )
            )

        return tests

    # ── Tree item updating ────────────────────────────────────────────

    def _update_tree_item_status(
        self,
        item: QTreeWidgetItem,
        data: TestItemData,
    ) -> None:
        """Update the status icon, text, and duration columns."""
        status = data.status
        color = _STATUS_COLORS.get(status, _CLR_GRAY)
        icon = _STATUS_ICONS.get(status, "\u25cb")
        label = _STATUS_LABELS.get(status, "?")

        item.setText(3, f"{icon} {label}")
        item.setForeground(3, QColor(color))

        if data.duration > 0:
            item.setText(4, f"{data.duration:.2f}s")
        else:
            item.setText(4, "-")

    def _find_tree_item(self, test_name: str) -> QTreeWidgetItem | None:
        """Find the tree item for a given test name."""
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if group is None:
                continue
            for j in range(group.childCount()):
                child = group.child(j)
                if child is None:
                    continue
                if child.data(1, Qt.ItemDataRole.UserRole) == test_name:
                    return child
        return None

    # ── Test execution ────────────────────────────────────────────────

    def _on_run_selected(self) -> None:
        items = self.get_selected_tests()
        if not items:
            return
        self._run_tests(items)

    def _on_run_all(self) -> None:
        items = list(self._test_items.values())
        if not items:
            return
        # Check all
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if group is not None:
                group.setCheckState(0, Qt.CheckState.Checked)
        self._run_tests(items)

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._btn_stop.setEnabled(False)

    def _run_tests(self, items: list[TestItemData]) -> None:
        if self._project_path is None or self._worker is not None:
            return

        # Reset statuses
        for item in items:
            item.status = TestStatus.NOT_RUN
            item.duration = 0.0
            item.log = ""
            tree_item = self._find_tree_item(item.name)
            if tree_item:
                self._update_tree_item_status(tree_item, item)

        # Setup progress
        self._progress.setMaximum(len(items))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._tests_run = 0
        self._tests_passed = 0
        self._tests_failed = 0
        self._run_start = time.monotonic()

        # Disable run buttons, enable stop
        self._btn_run_selected.setEnabled(False)
        self._btn_run_all.setEnabled(False)
        self._btn_stop.setEnabled(True)

        simulator = self._sim_combo.currentText().lower()

        self._worker = _TestRunnerWorker(
            test_items=items,
            project_path=self._project_path,
            simulator=simulator,
            coverage=self._chk_coverage.isChecked(),
            wave_dump=self._chk_wave.isChecked(),
            parent=self,
        )
        self._worker.test_started.connect(self._on_test_started)
        self._worker.test_finished.connect(self._on_test_finished)
        self._worker.output_line.connect(self._on_output_line)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.start()

    @Slot(str)
    def _on_test_started(self, name: str) -> None:
        if name in self._test_items:
            self._test_items[name].status = TestStatus.RUNNING
            tree_item = self._find_tree_item(name)
            if tree_item:
                self._update_tree_item_status(tree_item, self._test_items[name])

    @Slot(str, str, float, str)
    def _on_test_finished(self, name: str, status: str, duration: float, log: str) -> None:
        if name in self._test_items:
            item = self._test_items[name]
            item.status = TestStatus(status)
            item.duration = duration
            item.log = log

            tree_item = self._find_tree_item(name)
            if tree_item:
                self._update_tree_item_status(tree_item, item)

        self._tests_run += 1
        if status == TestStatus.PASSED:
            self._tests_passed += 1
        elif status in (TestStatus.FAILED, TestStatus.ERROR):
            self._tests_failed += 1

        self._progress.setValue(self._tests_run)
        self._update_running_summary()

    @Slot(str)
    def _on_output_line(self, line: str) -> None:
        # Append to detail output if the current test is selected
        cursor = self._detail_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)

        # Color-code errors and warnings
        if re.search(r"(?i)\berror\b", line):
            cursor.insertText(line + "\n", _make_format(_CLR_RED))
        elif re.search(r"(?i)\bwarn", line):
            cursor.insertText(line + "\n", _make_format(_CLR_YELLOW))
        elif re.search(r"(?i)\bpass", line):
            cursor.insertText(line + "\n", _make_format(_CLR_GREEN))
        else:
            cursor.insertText(line + "\n", _make_format(_CLR_TEXT))

        self._detail_output.setTextCursor(cursor)
        self._detail_output.ensureCursorVisible()

    @Slot()
    def _on_all_finished(self) -> None:
        total_duration = time.monotonic() - self._run_start
        self._progress.setVisible(False)
        self._btn_run_selected.setEnabled(True)
        self._btn_run_all.setEnabled(True)
        self._btn_stop.setEnabled(False)

        total = self._tests_run
        pct = 100.0 * self._tests_passed / total if total else 0.0
        self._summary.setText(
            f"{self._tests_passed}/{total} tests passed ({pct:.1f}%) in {total_duration:.1f}s"
        )
        if self._tests_failed > 0:
            self._summary.setStyleSheet(f"color: {_CLR_RED}; padding: 4px 8px; font-size: 12px;")
        else:
            self._summary.setStyleSheet(f"color: {_CLR_GREEN}; padding: 4px 8px; font-size: 12px;")

        self._worker = None

    # ── Detail panel ──────────────────────────────────────────────────

    def _on_current_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return

        name = current.data(1, Qt.ItemDataRole.UserRole)
        if name and name in self._test_items:
            item = self._test_items[name]
            status_color = _STATUS_COLORS.get(item.status, _CLR_GRAY)
            self._detail_label.setText(
                f"Test: {item.name}  |  Status: {_STATUS_LABELS.get(item.status, '?')}  |  "
                f"Duration: {item.duration:.2f}s"
            )
            self._detail_label.setStyleSheet(
                f"color: {status_color}; font-weight: bold; font-size: 12px; padding: 2px;"
            )

            # Show the test log
            self._detail_output.clear()
            if item.log:
                cursor = self._detail_output.textCursor()
                for line in item.log.splitlines():
                    if re.search(r"(?i)\berror\b|traceback|assert", line):
                        cursor.insertText(line + "\n", _make_format(_CLR_RED))
                    elif re.search(r"(?i)\bwarn", line):
                        cursor.insertText(line + "\n", _make_format(_CLR_YELLOW))
                    elif re.search(r"(?i)\bpass\b|passed", line):
                        cursor.insertText(line + "\n", _make_format(_CLR_GREEN))
                    else:
                        cursor.insertText(line + "\n", _make_format(_CLR_TEXT))
                self._detail_output.setTextCursor(cursor)

    def _on_item_double_clicked(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        """Open the test file in the editor on double-click."""
        name = item.data(1, Qt.ItemDataRole.UserRole)
        if name and name in self._test_items:
            self.open_file_requested.emit(str(self._test_items[name].file_path))

    # ── Filter ────────────────────────────────────────────────────────

    def _apply_filter(self, filter_text: str) -> None:
        """Show or hide tree items based on the selected filter."""
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if group is None:
                continue
            any_visible = False
            for j in range(group.childCount()):
                child = group.child(j)
                if child is None:
                    continue
                name = child.data(1, Qt.ItemDataRole.UserRole)
                visible = True
                if name and name in self._test_items:
                    status = self._test_items[name].status
                    if (
                        filter_text == "Passed"
                        and status != TestStatus.PASSED
                        or filter_text == "Failed"
                        and status not in (TestStatus.FAILED, TestStatus.ERROR)
                        or filter_text == "Not Run"
                        and status != TestStatus.NOT_RUN
                    ):
                        visible = False
                child.setHidden(not visible)
                if visible:
                    any_visible = True
            group.setHidden(not any_visible)

    # ── Refresh ───────────────────────────────────────────────────────

    def _on_refresh(self) -> None:
        self.discover_tests()

    # ── Summary helpers ───────────────────────────────────────────────

    def _update_summary(self) -> None:
        total = len(self._test_items)
        if total == 0:
            self._summary.setText("No tests found")
        else:
            cocotb = sum(1 for t in self._test_items.values() if t.test_type == "cocotb")
            sv = total - cocotb
            self._summary.setText(f"{total} tests found ({cocotb} cocotb, {sv} SystemVerilog)")
            self._summary.setStyleSheet(
                f"color: {_CLR_SUBTEXT}; padding: 4px 8px; font-size: 12px;"
            )

    def _update_running_summary(self) -> None:
        elapsed = time.monotonic() - self._run_start
        total = self._progress.maximum()
        self._summary.setText(
            f"Running: {self._tests_run}/{total} "
            f"({self._tests_passed} passed, {self._tests_failed} failed) "
            f"[{elapsed:.1f}s]"
        )
        self._summary.setStyleSheet(f"color: {_CLR_YELLOW}; padding: 4px 8px; font-size: 12px;")
