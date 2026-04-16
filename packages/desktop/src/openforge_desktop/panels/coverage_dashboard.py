"""Phase 4 coverage dashboard panel.

Visualises :class:`openforge.verification.coverage.CoverageReportV2`
runs with summary tiles, a file tree, a source viewer coloured by hit
count, a heatmap / trend tab, filters, diff mode and HTML/LCOV export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
    from openforge.verification.coverage import (
        CoverageDb,
        CoverageKind,
        CoverageReportV2,
        FileCoverage,
    )
except Exception:  # pragma: no cover - allow standalone import
    CoverageDb = None  # type: ignore
    CoverageKind = None  # type: ignore
    CoverageReportV2 = None  # type: ignore
    FileCoverage = None  # type: ignore


# ---------------------------------------------------------------------------
# Metric tile
# ---------------------------------------------------------------------------


class MetricCard(QFrame):
    """A small tile showing a coverage kind, percent, and a coloured bar."""

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._label = QLabel(label)
        self._label.setStyleSheet("color:#94a3b8; font-size:11px;")
        self._value = QLabel("—")
        self._value.setStyleSheet("font-size:20px; font-weight:600;")
        self._bar = QFrame()
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            "background:#313244; border-radius:3px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        lay.addWidget(self._label)
        lay.addWidget(self._value)
        lay.addWidget(self._bar)
        self.set_percent(None)

    @staticmethod
    def _colour_for(pct: float) -> str:
        if pct < 70.0:
            return "#f38ba8"
        if pct < 90.0:
            return "#f9e2af"
        return "#a6e3a1"

    def set_percent(self, pct: Optional[float]) -> None:
        if pct is None:
            self._value.setText("—")
            self._bar.setStyleSheet("background:#313244; border-radius:3px;")
            return
        self._value.setText(f"{pct:.1f}%")
        colour = self._colour_for(pct)
        self._bar.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {colour}, stop:{max(0.001, pct/100.0)} {colour},"
            f"stop:{min(1.0, pct/100.0 + 0.0001)} #313244, stop:1 #313244);"
            f"border-radius:3px;"
        )


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class CoverageDashboardPanel(QWidget):
    """Coverage dashboard."""

    coverageLoaded = Signal(object)  # emits CoverageReportV2

    KINDS: list[str] = [
        "line",
        "toggle",
        "branch",
        "condition",
        "fsm",
        "functional",
        "assertion",
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._report: Optional["CoverageReportV2"] = None
        self._compare: Optional["CoverageReportV2"] = None
        self._db: Optional["CoverageDb"] = None
        self._build_ui()
        self.setStyleSheet(panel_tab_qss(True))

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Toolbar
        bar = QHBoxLayout()
        self._load_btn = QPushButton("Load LCOV/DAT")
        self._load_btn.clicked.connect(self._on_load)
        self._diff_btn = QPushButton("Diff with…")
        self._diff_btn.clicked.connect(self._on_diff)
        self._export_html_btn = QPushButton("Export HTML")
        self._export_html_btn.clicked.connect(lambda: self._export("html"))
        self._export_lcov_btn = QPushButton("Export LCOV")
        self._export_lcov_btn.clicked.connect(lambda: self._export("lcov"))
        bar.addWidget(self._load_btn)
        bar.addWidget(self._diff_btn)
        bar.addStretch(1)
        bar.addWidget(self._export_html_btn)
        bar.addWidget(self._export_lcov_btn)
        root.addLayout(bar)

        # Metric tiles
        tiles_box = QGroupBox("Coverage Summary")
        tiles = QGridLayout(tiles_box)
        tiles.setSpacing(6)
        self._cards: dict[str, MetricCard] = {}
        for idx, kind in enumerate(self.KINDS):
            card = MetricCard(kind.title())
            self._cards[kind] = card
            tiles.addWidget(card, idx // 4, idx % 4)
        root.addWidget(tiles_box)

        # Filter row
        flt = QHBoxLayout()
        flt.addWidget(QLabel("Filter:"))
        self._file_filter = QLineEdit()
        self._file_filter.setPlaceholderText("file glob / substring")
        self._file_filter.textChanged.connect(self._refresh_tree)
        flt.addWidget(self._file_filter, 2)
        flt.addWidget(QLabel("Min %:"))
        self._min_pct = QSpinBox()
        self._min_pct.setRange(0, 100)
        self._min_pct.valueChanged.connect(self._refresh_tree)
        flt.addWidget(self._min_pct)
        self._hide_full = QCheckBox("Hide 100%")
        self._hide_full.stateChanged.connect(self._refresh_tree)
        flt.addWidget(self._hide_full)
        root.addLayout(flt)

        # Main splitter
        split = QSplitter(Qt.Orientation.Horizontal)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["File", "Covered", "%"])
        self._tree.setRootIsDecorated(True)
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._tree.itemSelectionChanged.connect(self._on_tree_select)
        split.addWidget(self._tree)

        self._tabs = QTabWidget()

        self._source = QPlainTextEdit()
        self._source.setReadOnly(True)
        mono = QFont("Consolas, 'Courier New', monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._source.setFont(mono)
        self._tabs.addTab(self._source, "Source")

        self._heatmap = QTableWidget(0, 3)
        self._heatmap.setHorizontalHeaderLabels(["File", "Lines", "%"])
        self._heatmap.horizontalHeader().setStretchLastSection(True)
        self._tabs.addTab(self._heatmap, "Heatmap")

        self._trend = QTableWidget(0, 2)
        self._trend.setHorizontalHeaderLabels(["Run", "Line %"])
        self._trend.horizontalHeader().setStretchLastSection(True)
        self._tabs.addTab(self._trend, "Trend")

        self._diff_view = QPlainTextEdit()
        self._diff_view.setReadOnly(True)
        self._tabs.addTab(self._diff_view, "Diff")

        # ── Wave 2 Phase 11 additions ───────────────────────────────
        # Functional coverage tab
        self._fcov_tab = QWidget()
        _fcov_lay = QVBoxLayout(self._fcov_tab)
        _fcov_lay.setContentsMargins(4, 4, 4, 4)
        self._fcov_table = QTableWidget(0, 4)
        self._fcov_table.setHorizontalHeaderLabels(
            ["Covergroup", "Point", "Hit Bins", "Total"]
        )
        self._fcov_table.horizontalHeader().setStretchLastSection(True)
        _fcov_lay.addWidget(self._fcov_table, 1)
        self._fcov_cross_table = QTableWidget(0, 3)
        self._fcov_cross_table.setHorizontalHeaderLabels(
            ["Point A", "Point B", "Cross Hits"]
        )
        self._fcov_cross_table.horizontalHeader().setStretchLastSection(True)
        _fcov_lay.addWidget(QLabel("Cross coverage"))
        _fcov_lay.addWidget(self._fcov_cross_table, 1)
        self._tabs.addTab(self._fcov_tab, "Functional")

        # Gap finder tab
        self._gap_tab = QWidget()
        _gap_lay = QVBoxLayout(self._gap_tab)
        _gap_lay.setContentsMargins(4, 4, 4, 4)
        _gap_bar = QHBoxLayout()
        self._gap_button = QPushButton("Run gap finder")
        self._gap_button.clicked.connect(self._on_run_gap_finder)
        _gap_bar.addWidget(self._gap_button)
        _gap_bar.addStretch(1)
        _gap_lay.addLayout(_gap_bar)
        self._gap_table = QTableWidget(0, 3)
        self._gap_table.setHorizontalHeaderLabels(
            ["Coverpoint", "Expression", "Suggested test"]
        )
        self._gap_table.horizontalHeader().setStretchLastSection(True)
        _gap_lay.addWidget(self._gap_table, 1)
        self._tabs.addTab(self._gap_tab, "Gap finder")

        # Closure projection tab
        self._proj_tab = QWidget()
        _proj_lay = QVBoxLayout(self._proj_tab)
        _proj_lay.setContentsMargins(4, 4, 4, 4)
        self._proj_label = QLabel("No trend data loaded.")
        _proj_lay.addWidget(self._proj_label)
        self._proj_table = QTableWidget(0, 3)
        self._proj_table.setHorizontalHeaderLabels(
            ["Run", "Coverage %", "Delta"]
        )
        self._proj_table.horizontalHeader().setStretchLastSection(True)
        _proj_lay.addWidget(self._proj_table, 1)
        self._tabs.addTab(self._proj_tab, "Closure")

        # Cross-test merge tab
        self._merge_tab = QWidget()
        _merge_lay = QVBoxLayout(self._merge_tab)
        _merge_lay.setContentsMargins(4, 4, 4, 4)
        _merge_bar = QHBoxLayout()
        self._merge_button = QPushButton("Add runs...")
        self._merge_button.clicked.connect(self._on_merge_runs)
        _merge_bar.addWidget(self._merge_button)
        self._merge_clear = QPushButton("Clear")
        self._merge_clear.clicked.connect(self._on_merge_clear)
        _merge_bar.addWidget(self._merge_clear)
        _merge_bar.addStretch(1)
        _merge_lay.addLayout(_merge_bar)
        self._merge_files: list[Path] = []
        self._merge_table = QTableWidget(0, 3)
        self._merge_table.setHorizontalHeaderLabels(
            ["Run file", "Groups", "%"]
        )
        self._merge_table.horizontalHeader().setStretchLastSection(True)
        _merge_lay.addWidget(self._merge_table, 1)
        self._merge_summary = QLabel("Merged: 0 groups, 0 bins")
        _merge_lay.addWidget(self._merge_summary)
        self._tabs.addTab(self._merge_tab, "Merge")

        split.addWidget(self._tabs)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    # Data binding
    # ------------------------------------------------------------------
    def set_report(self, report: "CoverageReportV2") -> None:
        self._report = report
        self._refresh_cards()
        self._refresh_tree()
        self._refresh_heatmap()
        self.coverageLoaded.emit(report)

    def set_db(self, db: "CoverageDb") -> None:
        self._db = db
        self._refresh_trend()

    def _refresh_cards(self) -> None:
        if self._report is None or CoverageKind is None:
            for c in self._cards.values():
                c.set_percent(None)
            return
        overall = self._report.overall or {}
        for kind_name, card in self._cards.items():
            try:
                k = CoverageKind(kind_name)
                pct = overall.get(k)
            except Exception:
                pct = None
            card.set_percent(pct)

    def _refresh_tree(self) -> None:
        self._tree.clear()
        if self._report is None:
            return
        flt = self._file_filter.text().strip().lower()
        min_pct = float(self._min_pct.value())
        hide_full = self._hide_full.isChecked()
        for path, fc in sorted(self._report.files.items()):
            if flt and flt not in path.lower():
                continue
            if fc.percent < min_pct:
                continue
            if hide_full and fc.percent >= 100.0:
                continue
            item = QTreeWidgetItem([
                path,
                f"{fc.covered_lines}/{fc.total_lines}",
                f"{fc.percent:.1f}%",
            ])
            colour = QColor(self._pct_colour(fc.percent))
            item.setForeground(2, QBrush(colour))
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            self._tree.addTopLevelItem(item)

    def _refresh_heatmap(self) -> None:
        self._heatmap.setRowCount(0)
        if self._report is None:
            return
        items = sorted(
            self._report.files.items(), key=lambda kv: kv[1].total_lines, reverse=True
        )
        self._heatmap.setRowCount(len(items))
        for row, (path, fc) in enumerate(items):
            self._heatmap.setItem(row, 0, QTableWidgetItem(path))
            self._heatmap.setItem(row, 1, QTableWidgetItem(str(fc.total_lines)))
            cell = QTableWidgetItem(f"{fc.percent:.1f}%")
            cell.setForeground(QBrush(QColor(self._pct_colour(fc.percent))))
            self._heatmap.setItem(row, 2, cell)

    def _refresh_trend(self) -> None:
        self._trend.setRowCount(0)
        if self._db is None or CoverageKind is None:
            return
        try:
            series = self._db.trend(CoverageKind.LINE, last_n=20)
        except Exception:
            series = []
        self._trend.setRowCount(len(series))
        for row, v in enumerate(series):
            self._trend.setItem(row, 0, QTableWidgetItem(f"#{row + 1}"))
            cell = QTableWidgetItem(f"{v:.1f}%")
            cell.setForeground(QBrush(QColor(self._pct_colour(v))))
            self._trend.setItem(row, 1, cell)

    # ------------------------------------------------------------------
    # Source view
    # ------------------------------------------------------------------
    def _on_tree_select(self) -> None:
        items = self._tree.selectedItems()
        if not items or self._report is None:
            return
        path = items[0].data(0, Qt.ItemDataRole.UserRole)
        fc = self._report.files.get(path)
        if fc is None:
            return
        self._render_source(path, fc)

    def _render_source(self, path: str, fc: "FileCoverage") -> None:
        src = Path(path)
        lines: list[str]
        if src.exists():
            try:
                lines = src.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                lines = []
        else:
            max_line = max(fc.line_hits.keys(), default=0)
            lines = [""] * max_line
        self._source.clear()
        cursor = self._source.textCursor()
        default_fmt = QTextCharFormat()
        for i, text in enumerate(lines, start=1):
            hits = fc.line_hits.get(i)
            fmt = QTextCharFormat()
            if hits is None:
                fmt.setForeground(QBrush(QColor("#6c7086")))
                prefix = "     "
            elif hits == 0:
                fmt.setBackground(QBrush(QColor("#3a1a22")))
                fmt.setForeground(QBrush(QColor("#f38ba8")))
                prefix = "  0  "
            elif hits < 5:
                fmt.setForeground(QBrush(QColor("#f9e2af")))
                prefix = f"{hits:>4} "
            else:
                fmt.setForeground(QBrush(QColor("#a6e3a1")))
                prefix = f"{hits:>4} "
            cursor.insertText(f"{i:>5} {prefix}| {text}\n", fmt)
            cursor.setCharFormat(default_fmt)
        self._source.moveCursor(QTextCursor.MoveOperation.Start)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Coverage File",
            "",
            "Coverage (*.info *.lcov *.dat);;All files (*)",
        )
        if not path:
            return
        self.load_file(path)

    def load_file(self, path: str) -> None:
        if CoverageReportV2 is None:
            return
        p = Path(path)
        try:
            if p.suffix.lower() in (".info", ".lcov"):
                report = CoverageReportV2.from_verilator_lcov(p)
            else:
                report = CoverageReportV2.from_verilator_dat(p)
        except Exception:
            return
        self.set_report(report)

    def _on_diff(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pick Baseline Coverage",
            "",
            "Coverage (*.info *.lcov *.dat);;All files (*)",
        )
        if not path or CoverageReportV2 is None or self._report is None:
            return
        p = Path(path)
        try:
            if p.suffix.lower() in (".info", ".lcov"):
                base = CoverageReportV2.from_verilator_lcov(p)
            else:
                base = CoverageReportV2.from_verilator_dat(p)
        except Exception:
            return
        self._compare = base
        self._render_diff()
        self._tabs.setCurrentWidget(self._diff_view)

    def _render_diff(self) -> None:
        if self._report is None or self._compare is None:
            return
        lines: list[str] = []
        lines.append(
            f"Baseline: {self._compare.test_name}  →  Current: {self._report.test_name}"
        )
        lines.append("-" * 60)
        all_files = set(self._report.files) | set(self._compare.files)
        for f in sorted(all_files):
            cur = self._report.files.get(f)
            base = self._compare.files.get(f)
            cur_pct = cur.percent if cur else 0.0
            base_pct = base.percent if base else 0.0
            delta = cur_pct - base_pct
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"{f:<60} {base_pct:>6.1f}% -> {cur_pct:>6.1f}%  ({sign}{delta:.1f})"
            )
        self._diff_view.setPlainText("\n".join(lines))

    def _export(self, kind: str) -> None:
        if self._report is None:
            return
        if kind == "html":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export HTML", "coverage.html", "HTML (*.html)"
            )
            if not path:
                return
            Path(path).write_text(self._to_html(), encoding="utf-8")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export LCOV", "coverage.info", "LCOV (*.info *.lcov)"
            )
            if not path:
                return
            Path(path).write_text(self._report.to_lcov(), encoding="utf-8")

    def _to_html(self) -> str:
        if self._report is None:
            return ""
        rows = []
        for path, fc in sorted(self._report.files.items()):
            rows.append(
                f"<tr><td>{path}</td><td>{fc.covered_lines}/{fc.total_lines}</td>"
                f"<td style='color:{self._pct_colour(fc.percent)}'>{fc.percent:.1f}%</td></tr>"
            )
        return (
            "<!doctype html><html><body style='background:#11111b;color:#cdd6f4;"
            "font-family:sans-serif'><h1>Coverage</h1><table border=1>"
            "<tr><th>File</th><th>Lines</th><th>%</th></tr>"
            + "".join(rows)
            + "</table></body></html>"
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _pct_colour(pct: float) -> str:
        if pct < 70.0:
            return "#f38ba8"
        if pct < 90.0:
            return "#f9e2af"
        return "#a6e3a1"

    # ------------------------------------------------------------------
    # Wave 2 Phase 11: functional coverage, gap finder, merge, closure
    # ------------------------------------------------------------------
    def set_functional_coverage(self, groups: list) -> None:
        """Populate the Functional tab from a list of ``CoverGroup`` dicts."""
        self._fcov_table.setRowCount(0)
        self._fcov_cross_table.setRowCount(0)
        for g in groups or []:
            gname = g.get("name", "") if isinstance(g, dict) else getattr(g, "name", "")
            points = g.get("points", []) if isinstance(g, dict) else getattr(g, "points", [])
            for p in points:
                pname = p.get("name", "") if isinstance(p, dict) else getattr(p, "name", "")
                bins = p.get("bins", []) if isinstance(p, dict) else getattr(p, "bins", [])
                hit = sum(
                    1
                    for b in bins
                    if (b.get("hits", 0) if isinstance(b, dict) else getattr(b, "hits", 0)) > 0
                )
                total = max(len(bins), 1)
                row = self._fcov_table.rowCount()
                self._fcov_table.insertRow(row)
                self._fcov_table.setItem(row, 0, QTableWidgetItem(gname))
                self._fcov_table.setItem(row, 1, QTableWidgetItem(pname))
                self._fcov_table.setItem(row, 2, QTableWidgetItem(str(hit)))
                self._fcov_table.setItem(row, 3, QTableWidgetItem(str(total)))
            crosses = g.get("crosses", []) if isinstance(g, dict) else getattr(g, "crosses", [])
            for cx in crosses:
                try:
                    a, b = cx
                except Exception:
                    continue
                row = self._fcov_cross_table.rowCount()
                self._fcov_cross_table.insertRow(row)
                self._fcov_cross_table.setItem(row, 0, QTableWidgetItem(str(a)))
                self._fcov_cross_table.setItem(row, 1, QTableWidgetItem(str(b)))
                self._fcov_cross_table.setItem(row, 2, QTableWidgetItem("0"))

    def _on_run_gap_finder(self) -> None:
        self._gap_table.setRowCount(0)
        try:
            from openforge.verification.uvm_lite.coverage import (
                FunctionalCoverageMerger,
            )
        except Exception:
            return
        merger = FunctionalCoverageMerger()
        if self._merge_files:
            merger.merge_runs(list(self._merge_files))
        gaps = merger.gap_finder()
        for p in gaps:
            row = self._gap_table.rowCount()
            self._gap_table.insertRow(row)
            self._gap_table.setItem(row, 0, QTableWidgetItem(getattr(p, "name", "")))
            self._gap_table.setItem(row, 1, QTableWidgetItem(getattr(p, "expression", "")))
            self._gap_table.setItem(
                row, 2, QTableWidgetItem(f"test_{getattr(p, 'name', 'x')}_seed_random")
            )

    def _on_merge_runs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select coverage JSON runs", "", "JSON (*.json)"
        )
        if not files:
            return
        try:
            from openforge.verification.uvm_lite.coverage import (
                FunctionalCoverageMerger,
            )
        except Exception:
            return
        for f in files:
            self._merge_files.append(Path(f))
        merger = FunctionalCoverageMerger()
        summary = merger.merge_runs(list(self._merge_files)).get("summary", {})
        self._merge_table.setRowCount(0)
        for f in self._merge_files:
            row = self._merge_table.rowCount()
            self._merge_table.insertRow(row)
            self._merge_table.setItem(row, 0, QTableWidgetItem(str(f)))
            self._merge_table.setItem(row, 1, QTableWidgetItem(str(summary.get("groups", 0))))
            self._merge_table.setItem(
                row, 2, QTableWidgetItem(f"{summary.get('percent', 0.0):.1f}")
            )
        self._merge_summary.setText(
            f"Merged: {summary.get('groups', 0)} groups, "
            f"{summary.get('hit_bins', 0)}/{summary.get('total_bins', 0)} bins "
            f"({summary.get('percent', 0.0):.1f}%)"
        )
        self._update_closure_projection()

    def _on_merge_clear(self) -> None:
        self._merge_files = []
        self._merge_table.setRowCount(0)
        self._merge_summary.setText("Merged: 0 groups, 0 bins")
        self._proj_table.setRowCount(0)
        self._proj_label.setText("No trend data loaded.")

    def _update_closure_projection(self) -> None:
        if not self._merge_files:
            self._proj_label.setText("No trend data loaded.")
            return
        try:
            from openforge.verification.uvm_lite.coverage import (
                FunctionalCoverageMerger,
            )
        except Exception:
            return
        self._proj_table.setRowCount(0)
        last_pct = 0.0
        for i, f in enumerate(self._merge_files):
            merger = FunctionalCoverageMerger()
            summary = merger.merge_runs(
                list(self._merge_files[: i + 1])
            ).get("summary", {})
            pct = float(summary.get("percent", 0.0))
            delta = pct - last_pct
            row = self._proj_table.rowCount()
            self._proj_table.insertRow(row)
            self._proj_table.setItem(row, 0, QTableWidgetItem(f.name))
            self._proj_table.setItem(row, 1, QTableWidgetItem(f"{pct:.2f}"))
            self._proj_table.setItem(row, 2, QTableWidgetItem(f"{delta:+.2f}"))
            last_pct = pct
        # Project remaining runs needed to hit 100%
        if len(self._merge_files) >= 2:
            first_pct = 0.0  # before any runs
            slope = (last_pct - first_pct) / max(1, len(self._merge_files))
            if slope > 0.0:
                remaining = (100.0 - last_pct) / slope
                self._proj_label.setText(
                    f"At current slope {slope:.2f}%/run, "
                    f"{remaining:.0f} more runs needed to reach 100%."
                )
            else:
                self._proj_label.setText(
                    "Coverage is flat or decreasing -- add stimulus diversity."
                )
        else:
            self._proj_label.setText(
                f"Current coverage: {last_pct:.1f}% "
                f"(need at least 2 runs to project)."
            )
