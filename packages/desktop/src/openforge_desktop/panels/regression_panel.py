"""Regression dashboard dock widget for the OpenForge desktop app.

The :class:`RegressionPanel` is a :class:`QDockWidget` that lets the user
discover, run, monitor and inspect regression tests in a project. Tests
are executed in a background :class:`QThread` so the UI never blocks.
Results stream into the table row by row as each test completes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.verification.regression import (
        RegressionRunner,
        TestCase,
        TestResult,
    )
except Exception:  # pragma: no cover - allow standalone import
    RegressionRunner = None  # type: ignore
    TestCase = None  # type: ignore
    TestResult = None  # type: ignore


# Status colors required by the spec.
STATUS_COLORS = {
    "passed": "#a6e3a1",
    "failed": "#f38ba8",
    "error": "#fab387",
    "running": "#f9e2af",
    "skipped": "#6c7086",
    "pending": "#cdd6f4",
    "timeout": "#fab387",
}

STATUS_ICONS = {
    "passed": "\u2713",
    "failed": "\u2717",
    "error": "!",
    "running": "\u25b6",
    "skipped": "\u2298",
    "pending": "\u22ef",
    "timeout": "\u29d6",
}


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


class RegressionWorker(QThread):
    """Background worker that runs the regression suite."""

    test_started = Signal(str)
    test_completed = Signal(object)  # TestResult
    progress = Signal(int, int)  # done, total
    finished_all = Signal(list)  # list[TestResult]
    error = Signal(str)

    def __init__(
        self,
        runner: RegressionRunner,
        tests: list,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._tests = tests
        self._results: list = []
        self._cancel = False
        self._done = 0

    def cancel(self) -> None:
        self._cancel = True

    def _on_complete(self, result) -> None:
        self._done += 1
        self._results.append(result)
        self.test_completed.emit(result)
        self.progress.emit(self._done, len(self._tests))

    def _is_cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:  # pragma: no cover - thread loop
        try:
            self.progress.emit(0, len(self._tests))
            results = self._runner.run(
                self._tests,
                on_test_complete=self._on_complete,
                cancellation_check=self._is_cancelled,
            )
            self.finished_all.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _PanelState:
    test_dir: Path | None = None
    tests: list = field(default_factory=list)
    results: dict = field(default_factory=dict)  # name -> TestResult
    history: dict = field(default_factory=dict)  # name -> list[str]
    dark: bool = True


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class RegressionPanel(QDockWidget):
    """Dockable regression dashboard."""

    test_selected = Signal(str)
    open_log_requested = Signal(str)
    open_waveform_requested = Signal(str)

    COL_NAME = 0
    COL_STATUS = 1
    COL_DURATION = 2
    COL_COVERAGE = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Regression")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setObjectName("RegressionPanel")

        self._state = _PanelState()
        self._worker: RegressionWorker | None = None

        self._build_ui()
        self.set_theme(True)

    # ------------------------------------------------------------------
    # UI assembly
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget(self)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        outer.addWidget(self._build_toolbar())
        outer.addWidget(self._build_stats_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal, container)
        splitter.addWidget(self._build_left_pane())
        splitter.addWidget(self._build_right_pane())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)

        outer.addWidget(self._build_progress_bar())

        self.setWidget(container)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar("Regression", self)
        tb.setIconSize(tb.iconSize())

        self.act_discover = QAction("Discover", tb)
        self.act_discover.setToolTip("Scan a directory for tests")
        self.act_discover.triggered.connect(self._on_discover)
        tb.addAction(self.act_discover)

        self.act_run_all = QAction("Run All", tb)
        self.act_run_all.triggered.connect(self.run_all)
        tb.addAction(self.act_run_all)

        self.act_run_sel = QAction("Run Selected", tb)
        self.act_run_sel.triggered.connect(self._run_selected)
        tb.addAction(self.act_run_sel)

        self.act_stop = QAction("Stop", tb)
        self.act_stop.triggered.connect(self.stop)
        self.act_stop.setEnabled(False)
        tb.addAction(self.act_stop)

        tb.addSeparator()

        self.filter_edit = QLineEdit(tb)
        self.filter_edit.setPlaceholderText("Filter by name or tag\u2026")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        tb.addWidget(self.filter_edit)

        self.group_combo = QComboBox(tb)
        self.group_combo.addItems(["Group by tag", "Flat list"])
        self.group_combo.currentIndexChanged.connect(self._rebuild_tree)
        tb.addWidget(self.group_combo)

        self.act_export = QAction("Export Report", tb)
        self.act_export.triggered.connect(self._on_export_report)
        tb.addAction(self.act_export)

        return tb

    def _build_stats_bar(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("StatsBar")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(16)

        self.lbl_total = QLabel("Total: 0")
        self.lbl_passed = QLabel("Passed: 0")
        self.lbl_failed = QLabel("Failed: 0")
        self.lbl_errors = QLabel("Errors: 0")
        self.lbl_skipped = QLabel("Skipped: 0")
        self.lbl_coverage = QLabel("Coverage: \u2014")

        self.lbl_passed.setStyleSheet(f"color: {STATUS_COLORS['passed']};")
        self.lbl_failed.setStyleSheet(f"color: {STATUS_COLORS['failed']};")
        self.lbl_errors.setStyleSheet(f"color: {STATUS_COLORS['error']};")
        self.lbl_skipped.setStyleSheet(f"color: {STATUS_COLORS['skipped']};")

        for w in (
            self.lbl_total,
            self.lbl_passed,
            self.lbl_failed,
            self.lbl_errors,
            self.lbl_skipped,
            self.lbl_coverage,
        ):
            f = QFont(w.font())
            f.setBold(True)
            w.setFont(f)
            layout.addWidget(w)
        layout.addStretch(1)
        return frame

    def _build_left_pane(self) -> QWidget:
        wrap = QWidget(self)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget(wrap)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Name", "Status", "Duration", "Coverage"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(False)
        self.tree.setRootIsDecorated(True)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        v.addWidget(self.tree)
        return wrap

    def _build_right_pane(self) -> QWidget:
        self.tabs = QTabWidget(self)

        # Log tab
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.log_view, "Log")

        # Coverage tab
        self.cov_view = QTextEdit()
        self.cov_view.setReadOnly(True)
        self.cov_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.cov_view, "Coverage")

        # History tab
        self.hist_view = QTextEdit()
        self.hist_view.setReadOnly(True)
        self.hist_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.hist_view, "History")

        # Plot tab (textual ascii sparkline placeholder)
        self.plot_view = QTextEdit()
        self.plot_view.setReadOnly(True)
        self.plot_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.plot_view, "Plot")

        return self.tabs

    def _build_progress_bar(self) -> QWidget:
        wrap = QWidget(self)
        h = QHBoxLayout(wrap)
        h.setContentsMargins(8, 2, 8, 2)
        self.progress = QProgressBar(wrap)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m tests")
        h.addWidget(self.progress, 1)
        return wrap

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def set_theme(self, dark: bool) -> None:
        self._state.dark = dark
        if dark:
            qss = """
                QDockWidget { color: #cdd6f4; }
                QWidget { background: #1e1e2e; color: #cdd6f4; }
                QFrame#StatsBar { background: #181825; border:1px solid #313244;
                                  border-radius:4px; }
                QToolBar { background: #181825; border: none; spacing: 4px; }
                QLineEdit { background:#11111b; border:1px solid #313244;
                            border-radius:3px; padding:2px 4px; color:#cdd6f4; }
                QComboBox { background:#11111b; border:1px solid #313244;
                            color:#cdd6f4; padding:2px 4px; }
                QTreeWidget { background:#11111b; alternate-background-color:#181825;
                              border:1px solid #313244; }
                QHeaderView::section { background:#181825; color:#94a3b8;
                                       border:0; padding:4px; }
                QTabBar::tab { background:#181825; padding:4px 10px; color:#94a3b8; }
                QTabBar::tab:selected { background:#1e1e2e; color:#cdd6f4; }
                QTextEdit { background:#11111b; color:#cdd6f4;
                            border:1px solid #313244; }
                QProgressBar { background:#11111b; border:1px solid #313244;
                               border-radius:3px; text-align:center; color:#cdd6f4; }
                QProgressBar::chunk { background:#89b4fa; }
            """
        else:
            qss = """
                QWidget { background:#fafafa; color:#1e1e2e; }
                QFrame#StatsBar { background:#ececec; border:1px solid #d0d0d0;
                                  border-radius:4px; }
                QTreeWidget { background:#ffffff; alternate-background-color:#f4f4f4; }
                QTextEdit { background:#ffffff; color:#1e1e2e; border:1px solid #d0d0d0; }
                QProgressBar::chunk { background:#1e66f5; }
            """
        self.setStyleSheet(qss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_test_directory(self, path: Path) -> None:
        if RegressionRunner is None:
            QMessageBox.warning(self, "Regression", "openforge.verification not available")
            return
        path = Path(path)
        runner = RegressionRunner()
        tests = runner.discover_tests(path)
        self._state.test_dir = path
        self._state.tests = tests
        self._state.results.clear()
        self._rebuild_tree()
        self._update_stats()

    def run_all(self) -> None:
        if not self._state.tests:
            QMessageBox.information(self, "Regression", "No tests discovered yet.")
            return
        self._launch_worker(self._state.tests)

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.act_stop.setEnabled(False)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------
    @Slot()
    def _on_discover(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select test directory")
        if d:
            self.load_test_directory(Path(d))

    @Slot()
    def _run_selected(self) -> None:
        names = self._selected_test_names()
        if not names:
            QMessageBox.information(self, "Regression", "Select at least one test.")
            return
        tests = [t for t in self._state.tests if t.name in names]
        if tests:
            self._launch_worker(tests)

    def _launch_worker(self, tests: list) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(self, "Regression", "A run is already in progress.")
            return
        runner = RegressionRunner()
        self._worker = RegressionWorker(runner, tests, self)
        self._worker.test_completed.connect(self._on_test_completed)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self.progress.setRange(0, len(tests))
        self.progress.setValue(0)
        self.act_stop.setEnabled(True)
        self.act_run_all.setEnabled(False)
        self.act_run_sel.setEnabled(False)
        # Mark them running in tree
        for t in tests:
            item = self._find_item(t.name)
            if item is not None:
                self._set_item_status(item, "running", 0.0, None)
        self._worker.start()

    @Slot(object)
    def _on_test_completed(self, result) -> None:
        self._state.results[result.test.name] = result
        history = self._state.history.setdefault(result.test.name, [])
        history.append(result.status)
        if len(history) > 50:
            del history[:-50]
        item = self._find_item(result.test.name)
        if item is not None:
            cov_pct = result.coverage.overall_pct if result.coverage else None
            self._set_item_status(item, result.status, result.duration_s, cov_pct)
        self._update_stats()

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)

    @Slot(list)
    def _on_finished(self, results) -> None:
        self.act_stop.setEnabled(False)
        self.act_run_all.setEnabled(True)
        self.act_run_sel.setEnabled(True)
        self._worker = None

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Regression", f"Worker error: {msg}")
        self.act_stop.setEnabled(False)
        self.act_run_all.setEnabled(True)
        self.act_run_sel.setEnabled(True)
        self._worker = None

    @Slot()
    def _on_selection_changed(self) -> None:
        names = self._selected_test_names()
        if not names:
            return
        name = next(iter(names))
        self.test_selected.emit(name)
        result = self._state.results.get(name)
        if result is None:
            self.log_view.setPlainText("(no run yet)")
            self.cov_view.setPlainText("")
            self.hist_view.setPlainText("")
            self.plot_view.setPlainText("")
            return
        self._show_log(result)
        self._show_coverage(result)
        self._show_history(name)
        self._show_plot(name)

    @Slot()
    def _on_tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, Qt.ItemDataRole.UserRole) is None:
            return
        name = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self.tree)
        act_run = menu.addAction("Run")
        act_run_seed = menu.addAction("Run with seed\u2026")
        act_log = menu.addAction("Open log")
        act_wave = menu.addAction("Open waveform")
        act_copy = menu.addAction("Copy command")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        result = self._state.results.get(name)
        test = next((t for t in self._state.tests if t.name == name), None)
        if chosen is act_run and test is not None:
            self._launch_worker([test])
        elif chosen is act_run_seed and test is not None:
            from random import randint

            self._launch_worker([test.with_seed(randint(1, 2**31 - 1))])
        elif chosen is act_log and result is not None and result.artifact_dir is not None:
            self.open_log_requested.emit(str(result.artifact_dir / "test.log"))
        elif chosen is act_wave and result is not None and result.waveform is not None:
            self.open_waveform_requested.emit(str(result.waveform))
        elif chosen is act_copy and test is not None:
            from PySide6.QtWidgets import QApplication

            cmd = "iverilog -g2012 " + " ".join(str(s) for s in test.sources)
            QApplication.clipboard().setText(cmd)

    @Slot()
    def _on_export_report(self) -> None:
        if not self._state.results:
            QMessageBox.information(self, "Regression", "No results to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", "regression-report.html", "HTML (*.html)"
        )
        if not path:
            return
        runner = RegressionRunner()
        runner.generate_html_report(list(self._state.results.values()), Path(path))
        QMessageBox.information(self, "Regression", f"Report written to {path}")

    # ------------------------------------------------------------------
    # Tree management
    # ------------------------------------------------------------------
    def _rebuild_tree(self) -> None:
        self.tree.clear()
        if not self._state.tests:
            return
        group_by_tag = self.group_combo.currentIndex() == 0
        if group_by_tag:
            groups: dict[str, list] = {}
            for t in self._state.tests:
                tags = t.tags or ["untagged"]
                for tag in tags:
                    groups.setdefault(tag, []).append(t)
            for tag in sorted(groups):
                parent = QTreeWidgetItem([tag, "", "", ""])
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                self.tree.addTopLevelItem(parent)
                for t in groups[tag]:
                    child = QTreeWidgetItem([t.name, "pending", "", ""])
                    child.setData(0, Qt.ItemDataRole.UserRole, t.name)
                    parent.addChild(child)
                    self._set_item_status(child, "pending", 0.0, None)
                parent.setExpanded(True)
        else:
            for t in self._state.tests:
                item = QTreeWidgetItem([t.name, "pending", "", ""])
                item.setData(0, Qt.ItemDataRole.UserRole, t.name)
                self.tree.addTopLevelItem(item)
                self._set_item_status(item, "pending", 0.0, None)
        # Re-apply existing results.
        for name, res in self._state.results.items():
            item = self._find_item(name)
            if item is not None:
                cov = res.coverage.overall_pct if res.coverage else None
                self._set_item_status(item, res.status, res.duration_s, cov)
        self._apply_filter(self.filter_edit.text())

    def _set_item_status(
        self,
        item: QTreeWidgetItem,
        status: str,
        duration: float,
        coverage: float | None,
    ) -> None:
        icon = STATUS_ICONS.get(status, "?")
        color = QColor(STATUS_COLORS.get(status, "#cdd6f4"))
        item.setText(self.COL_STATUS, f"{icon} {status}")
        item.setForeground(self.COL_STATUS, QBrush(color))
        item.setText(self.COL_DURATION, f"{duration:.2f}s" if duration else "")
        item.setText(self.COL_COVERAGE, f"{coverage:.1f}%" if coverage is not None else "")

    def _find_item(self, name: str) -> QTreeWidgetItem | None:
        def walk(parent: QTreeWidgetItem) -> QTreeWidgetItem | None:
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if ch.data(0, Qt.ItemDataRole.UserRole) == name:
                    return ch
                found = walk(ch)
                if found is not None:
                    return found
            return None

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, Qt.ItemDataRole.UserRole) == name:
                return top
            found = walk(top)
            if found is not None:
                return found
        return None

    def _selected_test_names(self) -> set[str]:
        out: set[str] = set()
        for item in self.tree.selectedItems():
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name:
                out.add(name)
            else:
                for i in range(item.childCount()):
                    ch = item.child(i)
                    cn = ch.data(0, Qt.ItemDataRole.UserRole)
                    if cn:
                        out.add(cn)
        return out

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip().lower()

        def match(item: QTreeWidgetItem) -> bool:
            if not text:
                return True
            if text in item.text(0).lower():
                return True
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name:
                test = next((t for t in self._state.tests if t.name == name), None)
                if test is not None and any(text in tag.lower() for tag in test.tags):
                    return True
            return False

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(top.childCount()):
                ch = top.child(j)
                visible = match(ch)
                ch.setHidden(not visible)
                any_visible = any_visible or visible
            if top.childCount() == 0:
                top.setHidden(not match(top))
            else:
                top.setHidden(not any_visible)

    # ------------------------------------------------------------------
    # Detail panes
    # ------------------------------------------------------------------
    def _show_log(self, result) -> None:
        self.log_view.clear()
        cursor = self.log_view.textCursor()
        for raw in (result.log or "").splitlines():
            fmt = QTextCharFormat()
            upper = raw.upper()
            if "PASS" in upper:
                fmt.setForeground(QColor(STATUS_COLORS["passed"]))
            elif "FAIL" in upper:
                fmt.setForeground(QColor(STATUS_COLORS["failed"]))
            elif "ERROR" in upper or "FATAL" in upper:
                fmt.setForeground(QColor(STATUS_COLORS["error"]))
            else:
                fmt.setForeground(QColor("#cdd6f4"))
            cursor.insertText(raw + "\n", fmt)
        self.log_view.moveCursor(QTextCursor.MoveOperation.Start)

    def _show_coverage(self, result) -> None:
        if result.coverage is None:
            self.cov_view.setPlainText("(no coverage data)")
            return
        cov = result.coverage
        text = (
            f"Overall:    {cov.overall_pct:6.2f}%\n"
            f"Line:       {cov.line_pct:6.2f}%  ({cov.line_covered}/{cov.line_total})\n"
            f"Toggle:     {cov.toggle_pct:6.2f}%  ({cov.toggle_covered}/{cov.toggle_total})\n"
            f"Branch:     {cov.branch_pct:6.2f}%  ({cov.branch_covered}/{cov.branch_total})\n"
            f"Functional: {cov.functional_pct:6.2f}%  "
            f"({cov.functional_covered}/{cov.functional_total})\n"
        )
        self.cov_view.setPlainText(text)

    def _show_history(self, name: str) -> None:
        history = self._state.history.get(name) or []
        if not history:
            self.hist_view.setPlainText("(no history)")
            return
        lines = [f"Run {i + 1:>3}: {s}" for i, s in enumerate(history)]
        self.hist_view.setPlainText("\n".join(lines))

    def _show_plot(self, name: str) -> None:
        history = self._state.history.get(name) or []
        if not history:
            self.plot_view.setPlainText("(no data)")
            return
        glyphs = {
            "passed": "\u2588",
            "failed": "\u2581",
            "error": "\u2582",
            "timeout": "\u2583",
            "skipped": "\u2584",
            "running": "\u2591",
        }
        spark = "".join(glyphs.get(s, " ") for s in history)
        passed = sum(1 for s in history if s == "passed")
        rate = (passed / len(history) * 100.0) if history else 0.0
        self.plot_view.setPlainText(f"{spark}\n\nLast {len(history)} runs, pass rate {rate:.1f}%")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def _update_stats(self) -> None:
        total = len(self._state.tests)
        results = list(self._state.results.values())
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        errors = sum(1 for r in results if r.status in ("error", "timeout"))
        skipped = sum(1 for r in results if r.status == "skipped")
        cov_vals = [r.coverage.overall_pct for r in results if r.coverage is not None]
        cov_text = "\u2014"
        if cov_vals:
            cov_text = f"{sum(cov_vals) / len(cov_vals):.1f}%"
        self.lbl_total.setText(f"Total: {total}")
        self.lbl_passed.setText(f"Passed: {passed}")
        self.lbl_failed.setText(f"Failed: {failed}")
        self.lbl_errors.setText(f"Errors: {errors}")
        self.lbl_skipped.setText(f"Skipped: {skipped}")
        self.lbl_coverage.setText(f"Coverage: {cov_text}")
