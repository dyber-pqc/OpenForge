"""Lint panel: drives :class:`openforge.verification.lint.LintEngine`."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""

try:
    from openforge.verification.lint import LintEngine, LintViolation
except Exception:  # pragma: no cover
    LintEngine = None  # type: ignore
    LintViolation = None  # type: ignore


_SEVERITY_COLORS = {
    "error": QColor("#f38ba8"),
    "warning": QColor("#f9e2af"),
    "info": QColor("#a6e3a1"),
}


class LintPanel(QWidget):
    """Dockable lint panel."""

    source_navigate = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lint_panel")
        self.setStyleSheet(panel_tab_qss(True))

        self._rtl_files: list[Path] = []
        self._violations: list[LintViolation] = []  # type: ignore[valid-type]
        self._engine: LintEngine | None = None  # type: ignore[valid-type]

        # Top bar
        top = QHBoxLayout()
        self._add_btn = QPushButton("Add RTL...")
        self._run_btn = QPushButton("Run Lint")
        self._fix_btn = QPushButton("Auto-Fix Selected")
        top.addWidget(self._add_btn)
        top.addWidget(self._run_btn)
        top.addWidget(self._fix_btn)
        top.addStretch(1)

        # Filters
        filter_row = QHBoxLayout()
        self._sev_filter = QComboBox()
        self._sev_filter.addItems(["all", "error", "warning", "info"])
        self._sev_filter.currentTextChanged.connect(self._refresh_table)
        self._rule_filter = QComboBox()
        self._rule_filter.addItem("all rules")
        self._rule_filter.currentTextChanged.connect(self._refresh_table)
        self._file_filter = QLineEdit()
        self._file_filter.setPlaceholderText("file glob (e.g. *cpu*.sv)")
        self._file_filter.textChanged.connect(self._refresh_table)
        filter_row.addWidget(QLabel("Severity:"))
        filter_row.addWidget(self._sev_filter)
        filter_row.addWidget(QLabel("Rule:"))
        filter_row.addWidget(self._rule_filter)
        filter_row.addWidget(QLabel("File:"))
        filter_row.addWidget(self._file_filter, 1)

        # Violations table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Severity", "Rule", "File", "Line", "Message"])
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.cellDoubleClicked.connect(self._on_double)
        self._table.itemSelectionChanged.connect(self._on_row_selected)

        # Source preview
        self._source_view = QPlainTextEdit()
        self._source_view.setReadOnly(True)

        # Rule manager
        self._rule_list = QListWidget()
        self._rule_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        if LintEngine is not None:
            for rid in LintEngine.BUILTIN_RULES.keys():
                it = QListWidgetItem(rid)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked)
                self._rule_list.addItem(it)
                self._rule_filter.addItem(rid)
        rule_box = QGroupBox("Rules")
        rv = QVBoxLayout(rule_box)
        rv.addWidget(self._rule_list)
        apply_btn = QPushButton("Apply Rule Changes")
        apply_btn.clicked.connect(self._on_apply_rules)
        rv.addWidget(apply_btn)

        # Splitters
        left_split = QSplitter(Qt.Orientation.Vertical)
        left_split.addWidget(self._table)
        left_split.addWidget(self._source_view)
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.addWidget(left_split)
        main_split.addWidget(rule_box)
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 0)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(filter_row)
        layout.addWidget(main_split, 1)

        self._add_btn.clicked.connect(self._on_add_rtl)
        self._run_btn.clicked.connect(self._on_run)
        self._fix_btn.clicked.connect(self._on_auto_fix)

    # -- slots ------------------------------------------------

    def set_rtl_files(self, files: list[Path]) -> None:
        self._rtl_files = [Path(f) for f in files]

    def _on_add_rtl(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add RTL files", "", "Verilog (*.v *.sv *.vh *.svh)"
        )
        self._rtl_files.extend(Path(f) for f in files)

    def _on_run(self) -> None:
        if LintEngine is None or not self._rtl_files:
            return
        self._engine = LintEngine(self._rtl_files)
        self._on_apply_rules()
        self._violations = self._engine.run_all()
        self._refresh_table()

    def _on_apply_rules(self) -> None:
        if self._engine is None:
            return
        for i in range(self._rule_list.count()):
            it = self._rule_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                self._engine.enable(it.text())
            else:
                self._engine.disable(it.text())

    def _on_double(self, row: int, _col: int) -> None:
        v = self._current_filtered()
        if row >= len(v):
            return
        self.source_navigate.emit(v[row].file, v[row].line)
        self._load_source(v[row].file, v[row].line)

    def _on_row_selected(self) -> None:
        rows = {i.row() for i in self._table.selectedIndexes()}
        if not rows:
            return
        v = self._current_filtered()
        r = sorted(rows)[0]
        if r >= len(v):
            return
        self._load_source(v[r].file, v[r].line)

    def _on_auto_fix(self) -> None:
        if self._engine is None:
            return
        v = self._current_filtered()
        rows = sorted({i.row() for i in self._table.selectedIndexes()})
        for r in rows:
            if r >= len(v):
                continue
            fix = self._engine.auto_fix(v[r])
            if fix is not None:
                self._source_view.appendPlainText(
                    f"[auto-fix] {v[r].file}:{v[r].line} -> {fix}"
                )

    # -- helpers ----------------------------------------------

    def _load_source(self, path: str, line: int) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self._source_view.setPlainText(text)
        block = self._source_view.document().findBlockByLineNumber(max(0, line - 1))
        if block.isValid():
            cursor = self._source_view.textCursor()
            cursor.setPosition(block.position())
            self._source_view.setTextCursor(cursor)
            self._source_view.centerCursor()

    def _current_filtered(self) -> list["LintViolation"]:  # type: ignore[name-defined]
        sev = self._sev_filter.currentText()
        rule = self._rule_filter.currentText()
        glob = self._file_filter.text().strip()
        out = []
        for v in self._violations:
            if sev != "all" and v.severity != sev:
                continue
            if rule not in ("all rules", "all") and v.rule != rule:
                continue
            if glob and glob not in v.file:
                continue
            out.append(v)
        return out

    def _refresh_table(self) -> None:
        rows = self._current_filtered()
        self._table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            sev_item = QTableWidgetItem(v.severity)
            colour = _SEVERITY_COLORS.get(v.severity)
            if colour is not None:
                sev_item.setForeground(QBrush(colour))
            self._table.setItem(r, 0, sev_item)
            self._table.setItem(r, 1, QTableWidgetItem(v.rule))
            self._table.setItem(r, 2, QTableWidgetItem(v.file))
            self._table.setItem(r, 3, QTableWidgetItem(str(v.line)))
            self._table.setItem(r, 4, QTableWidgetItem(v.message))
