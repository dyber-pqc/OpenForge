"""Phase 4 regression runner panel.

Drives :class:`openforge.verification.regression_v2.RegressionRunner` with
a live results table, a seed×test pass/fail matrix, a flake-rate column,
filters by tag/status, and JSON export.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ._theme import panel_tab_qss
except Exception:  # pragma: no cover

    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""


try:
    from openforge.verification.regression_v2 import (
        RegressionRunner,
        TestResult,
        TestSpec,
        TestSuite,
    )
except Exception:  # pragma: no cover
    RegressionRunner = None  # type: ignore
    TestResult = None  # type: ignore
    TestSpec = None  # type: ignore
    TestSuite = None  # type: ignore


STATUS_COLOURS = {
    "pass": "#a6e3a1",
    "fail": "#f38ba8",
    "error": "#fab387",
    "timeout": "#f9e2af",
    "skip": "#6c7086",
    "running": "#89b4fa",
}


class _Bridge(QObject):
    started = Signal(str, int)
    finished = Signal(object)


class RegressionRunnerPanel(QWidget):
    """Interactive regression UI."""

    openLog = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suite: TestSuite | None = None
        self._results: dict[str, TestResult] = {}
        self._flake: dict[str, float] = {}
        self._runner_thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._bridge = _Bridge()
        self._bridge.started.connect(self._on_started)
        self._bridge.finished.connect(self._on_finished)
        self._build_ui()
        self.setStyleSheet(panel_tab_qss(True))
        if TestSuite is not None:
            self._suite = TestSuite(name="default", tests=[], parallel=4)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Controls row
        ctrl = QHBoxLayout()
        self._run_all = QPushButton("Run All")
        self._run_sel = QPushButton("Run Selected")
        self._run_fail = QPushButton("Run Failures")
        self._reseed = QPushButton("Reseed + Rerun")
        self._stop = QPushButton("Stop")
        self._run_all.clicked.connect(self._on_run_all)
        self._run_sel.clicked.connect(self._on_run_selected)
        self._run_fail.clicked.connect(self._on_run_failures)
        self._reseed.clicked.connect(self._on_reseed)
        self._stop.clicked.connect(self._on_stop)
        for b in (
            self._run_all,
            self._run_sel,
            self._run_fail,
            self._reseed,
            self._stop,
        ):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        self._export_btn = QPushButton("Export JSON")
        self._export_btn.clicked.connect(self._on_export)
        ctrl.addWidget(self._export_btn)
        root.addLayout(ctrl)

        # Filters
        flt = QHBoxLayout()
        flt.addWidget(QLabel("Tag:"))
        self._tag_filter = QLineEdit()
        self._tag_filter.textChanged.connect(self._refresh_results)
        flt.addWidget(self._tag_filter, 1)
        flt.addWidget(QLabel("Status:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["all", "pass", "fail", "error", "timeout", "skip"])
        self._status_filter.currentTextChanged.connect(self._refresh_results)
        flt.addWidget(self._status_filter)
        root.addLayout(flt)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        split = QSplitter(Qt.Orientation.Horizontal)

        # Suite editor
        self._suite_tree = QTreeWidget()
        self._suite_tree.setHeaderLabels(["Test", "Seeds", "Tags"])
        self._suite_tree.itemDoubleClicked.connect(self._on_edit_inline)
        add_btn = QPushButton("+ Add Test")
        rm_btn = QPushButton("- Remove")
        add_btn.clicked.connect(self._on_add_test)
        rm_btn.clicked.connect(self._on_remove_test)
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.addWidget(self._suite_tree, 1)
        row = QHBoxLayout()
        row.addWidget(add_btn)
        row.addWidget(rm_btn)
        llay.addLayout(row)
        split.addWidget(left)

        # Results tabs
        tabs = QTabWidget()

        self._results_tbl = QTableWidget(0, 6)
        self._results_tbl.setHorizontalHeaderLabels(
            ["Test", "Seed", "Status", "Runtime", "Flake", "Error"]
        )
        self._results_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._results_tbl.itemDoubleClicked.connect(self._on_open_log)
        tabs.addTab(self._results_tbl, "Results")

        self._matrix = QTableWidget(0, 0)
        tabs.addTab(self._matrix, "Seed Matrix")

        split.addWidget(tabs)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    # Suite mutation
    # ------------------------------------------------------------------
    def set_suite(self, suite: TestSuite) -> None:
        self._suite = suite
        self._refresh_suite_tree()

    def _refresh_suite_tree(self) -> None:
        self._suite_tree.clear()
        if self._suite is None:
            return
        for t in self._suite.tests:
            item = QTreeWidgetItem([t.name, str(t.seed_count), ",".join(t.tags)])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._suite_tree.addTopLevelItem(item)

    def _on_add_test(self) -> None:
        if self._suite is None or TestSpec is None:
            return
        self._suite.tests.append(
            TestSpec(
                name=f"test_{len(self._suite.tests) + 1}",
                rtl_files=[],
                tb_file="",
                seed_count=1,
            )
        )
        self._refresh_suite_tree()

    def _on_remove_test(self) -> None:
        if self._suite is None:
            return
        item = self._suite_tree.currentItem()
        if item is None:
            return
        idx = self._suite_tree.indexOfTopLevelItem(item)
        if 0 <= idx < len(self._suite.tests):
            self._suite.tests.pop(idx)
            self._refresh_suite_tree()

    def _on_edit_inline(self, item: QTreeWidgetItem, column: int) -> None:
        if self._suite is None:
            return
        idx = self._suite_tree.indexOfTopLevelItem(item)
        if not (0 <= idx < len(self._suite.tests)):
            return
        spec = self._suite.tests[idx]
        if column == 0:
            spec.name = item.text(0)
        elif column == 1:
            try:
                spec.seed_count = max(1, int(item.text(1)))
            except ValueError:
                item.setText(1, str(spec.seed_count))
        elif column == 2:
            spec.tags = [t.strip() for t in item.text(2).split(",") if t.strip()]

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------
    def _on_run_all(self) -> None:
        if self._suite is None:
            return
        self._start_run(self._suite.tests)

    def _on_run_selected(self) -> None:
        if self._suite is None:
            return
        items = self._suite_tree.selectedItems()
        picks: list[TestSpec] = []
        for it in items:
            idx = self._suite_tree.indexOfTopLevelItem(it)
            if 0 <= idx < len(self._suite.tests):
                picks.append(self._suite.tests[idx])
        if picks:
            self._start_run(picks)

    def _on_run_failures(self) -> None:
        if self._suite is None:
            return
        failed = {r.test_name for r in self._results.values() if r.status != "pass"}
        picks = [t for t in self._suite.tests if t.name in failed]
        if picks:
            self._start_run(picks)

    def _on_reseed(self) -> None:
        # Re-run all tests with new seeds (just runs all again, the runner
        # chooses fresh seeds deterministically from a new instance).
        self._on_run_all()

    def _on_stop(self) -> None:
        self._cancel.set()

    def _start_run(self, tests: list) -> None:
        if RegressionRunner is None or TestSuite is None or not tests:
            return
        if self._runner_thread is not None and self._runner_thread.is_alive():
            return
        self._cancel.clear()
        suite = TestSuite(
            name=self._suite.name if self._suite else "run",
            tests=list(tests),
            parallel=self._suite.parallel if self._suite else 4,
        )
        output_dir = Path.cwd() / "regression_v2_results"
        runner = RegressionRunner(suite, output_dir, sim="verilator")

        def _started_cb(name: str, seed: int) -> None:
            self._bridge.started.emit(name, seed)

        def _finished_cb(result) -> None:
            self._bridge.finished.emit(result)

        runner.on_test_start = _started_cb
        runner.on_test_finish = _finished_cb
        total = sum(max(1, t.seed_count) for t in tests)
        self._progress.setRange(0, total)
        self._progress.setValue(0)

        def _thread() -> None:
            try:
                runner.run()
            except Exception:  # pragma: no cover - defensive
                pass

        self._runner_thread = threading.Thread(target=_thread, daemon=True)
        self._runner_thread.start()

    @Slot(str, int)
    def _on_started(self, name: str, seed: int) -> None:
        key = f"{name}#{seed}"
        if key in self._results:
            return
        # Provisional "running" row
        row = self._results_tbl.rowCount()
        self._results_tbl.insertRow(row)
        self._results_tbl.setItem(row, 0, QTableWidgetItem(name))
        self._results_tbl.setItem(row, 1, QTableWidgetItem(str(seed)))
        status = QTableWidgetItem("running")
        status.setForeground(QBrush(QColor(STATUS_COLOURS["running"])))
        self._results_tbl.setItem(row, 2, status)

    @Slot(object)
    def _on_finished(self, result) -> None:
        if result is None:
            return
        key = f"{result.test_name}#{result.seed}"
        self._results[key] = result
        self._progress.setValue(self._progress.value() + 1)
        self._refresh_results()
        self._refresh_matrix()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def _refresh_results(self) -> None:
        tag_flt = self._tag_filter.text().strip().lower()
        status_flt = self._status_filter.currentText()
        self._results_tbl.setRowCount(0)
        by_test: dict[str, list] = {}
        for r in self._results.values():
            by_test.setdefault(r.test_name, []).append(r)
        tag_lookup: dict[str, list[str]] = {}
        if self._suite is not None:
            tag_lookup = {t.name: t.tags for t in self._suite.tests}
        for name, runs in sorted(by_test.items()):
            tags = tag_lookup.get(name, [])
            if tag_flt and not any(tag_flt in t.lower() for t in tags):
                continue
            runs_total = len(runs)
            fails = sum(1 for r in runs if r.status != "pass")
            flake_rate = fails / runs_total if runs_total else 0.0
            self._flake[name] = flake_rate
            for r in runs:
                if status_flt != "all" and r.status != status_flt:
                    continue
                row = self._results_tbl.rowCount()
                self._results_tbl.insertRow(row)
                self._results_tbl.setItem(row, 0, QTableWidgetItem(name))
                self._results_tbl.setItem(row, 1, QTableWidgetItem(str(r.seed)))
                status_cell = QTableWidgetItem(r.status)
                status_cell.setForeground(QBrush(QColor(STATUS_COLOURS.get(r.status, "#cdd6f4"))))
                self._results_tbl.setItem(row, 2, status_cell)
                self._results_tbl.setItem(row, 3, QTableWidgetItem(f"{r.runtime_s:.2f}s"))
                self._results_tbl.setItem(row, 4, QTableWidgetItem(f"{flake_rate * 100:.0f}%"))
                err_item = QTableWidgetItem(r.error_msg[:160])
                err_item.setData(Qt.ItemDataRole.UserRole, r.log_path)
                self._results_tbl.setItem(row, 5, err_item)

    def _refresh_matrix(self) -> None:
        tests = sorted({r.test_name for r in self._results.values()})
        seeds = sorted({r.seed for r in self._results.values()})
        self._matrix.setRowCount(len(tests))
        self._matrix.setColumnCount(len(seeds))
        self._matrix.setHorizontalHeaderLabels([str(s) for s in seeds])
        self._matrix.setVerticalHeaderLabels(tests)
        for i, t in enumerate(tests):
            for j, s in enumerate(seeds):
                key = f"{t}#{s}"
                r = self._results.get(key)
                cell = QTableWidgetItem("")
                if r is not None:
                    cell.setText(r.status[:1].upper())
                    cell.setBackground(QBrush(QColor(STATUS_COLOURS.get(r.status, "#1e1e2e"))))
                self._matrix.setItem(i, j, cell)

    # ------------------------------------------------------------------
    def _on_open_log(self, item: QTableWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(path, str) and path:
            self.openLog.emit(path)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.json", "JSON (*.json)"
        )
        if not path:
            return
        payload = {k: v.model_dump() for k, v in self._results.items()}
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
