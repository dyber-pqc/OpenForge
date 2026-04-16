"""Multi-Mode Multi-Corner (MMMC) configuration and results panel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.mmmc import (
        Corner,
        MmmcConfig,
        MmmcRunner,
        Mode,
        Scenario,
    )
    from openforge.physical.sta_parser import StaReport
except Exception:  # pragma: no cover
    Corner = None  # type: ignore[assignment]
    MmmcConfig = None  # type: ignore[assignment]
    MmmcRunner = None  # type: ignore[assignment]
    Mode = None  # type: ignore[assignment]
    Scenario = None  # type: ignore[assignment]
    StaReport = None  # type: ignore[assignment]


_BG = QColor("#1e1e2e")
_PANEL = QColor("#181825")
_SURFACE = QColor("#313244")
_TEXT = QColor("#cdd6f4")
_SUBTLE = QColor("#a6adc8")
_BLUE = QColor("#89b4fa")
_GREEN = QColor("#a6e3a1")
_RED = QColor("#f38ba8")
_YELLOW = QColor("#f9e2af")


class MmmcPanel(QDockWidget):
    """Dock for MMMC configuration, execution, and cross-corner diff view."""

    run_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("MMMC", parent)
        self.setObjectName("mmmc_dock")
        self._config: Optional["MmmcConfig"] = None
        self._results: dict[str, "StaReport"] = {}
        self._build_ui()
        if MmmcConfig is not None:
            try:
                self.set_config(MmmcConfig.sky130_default())
            except Exception:
                pass

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setStyleSheet(
            f"background:{_BG.name()}; color:{_TEXT.name()};"
            "QLabel { color:#cdd6f4; }"
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Toolbar ----------------------------------------------------
        tb = QToolBar()
        tb.setStyleSheet(
            f"QToolBar {{ background:{_PANEL.name()}; border:1px solid #313244; }}"
        )
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(["sky130", "asap7"])
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        tb.addWidget(QLabel("Preset: "))
        tb.addWidget(self._preset_combo)
        tb.addSeparator()

        run_btn = QPushButton("Run All Scenarios")
        run_btn.setStyleSheet(
            "QPushButton { background:#89b4fa; color:#1e1e2e; padding:4px 10px; "
            "border-radius:4px; font-weight:600; }"
        )
        run_btn.clicked.connect(self._on_run)
        tb.addWidget(run_btn)

        export_btn = QPushButton("Export Tcl")
        export_btn.clicked.connect(self._on_export_tcl)
        tb.addWidget(export_btn)

        reports_btn = QPushButton("Export Reports")
        reports_btn.clicked.connect(self._on_export_reports)
        tb.addWidget(reports_btn)
        layout.addWidget(tb)

        # --- Tabs -------------------------------------------------------
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabBar::tab {{ background:{_PANEL.name()}; color:{_SUBTLE.name()}; "
            f"padding:6px 14px; }}"
            f"QTabBar::tab:selected {{ background:{_SURFACE.name()}; color:{_TEXT.name()}; }}"
            f"QTabWidget::pane {{ border:1px solid #313244; background:{_BG.name()}; }}"
        )

        self._corners_table = self._make_corners_table()
        self._tabs.addTab(self._corners_table, "Corners")

        self._modes_table = self._make_modes_table()
        self._tabs.addTab(self._modes_table, "Modes")

        self._scenarios_matrix = QTableWidget(0, 0)
        self._scenarios_matrix.setStyleSheet(self._table_qss())
        self._tabs.addTab(self._scenarios_matrix, "Scenarios")

        self._heatmap = QTableWidget(0, 0)
        self._heatmap.setStyleSheet(self._table_qss())
        self._tabs.addTab(self._heatmap, "Worst Slack Heatmap")

        self._diff_widget = self._make_diff_widget()
        self._tabs.addTab(self._diff_widget, "Cross-corner Diff")

        layout.addWidget(self._tabs, 1)

        self.setWidget(root)

    def _table_qss(self) -> str:
        return (
            f"QTableWidget {{ background:{_PANEL.name()}; color:{_TEXT.name()}; "
            f"gridline-color:#313244; }}"
            f"QHeaderView::section {{ background:{_SURFACE.name()}; color:{_TEXT.name()}; "
            f"padding:4px; border:0; }}"
        )

    def _make_corners_table(self) -> QTableWidget:
        t = QTableWidget(0, 7)
        t.setHorizontalHeaderLabels(
            ["Name", "P", "V", "T", "Lib files", "RC corner", "Derate"]
        )
        t.setStyleSheet(self._table_qss())
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        return t

    def _make_modes_table(self) -> QTableWidget:
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Name", "SDC file", "Active clocks", "Case analysis"])
        t.setStyleSheet(self._table_qss())
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return t

    def _make_diff_widget(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("A:"))
        self._diff_a = QComboBox()
        ctrl.addWidget(self._diff_a, 1)
        ctrl.addWidget(QLabel("B:"))
        self._diff_b = QComboBox()
        ctrl.addWidget(self._diff_b, 1)
        go = QPushButton("Compute Diff")
        go.clicked.connect(self._on_diff)
        ctrl.addWidget(go)
        lay.addLayout(ctrl)
        self._diff_text = QTextEdit()
        self._diff_text.setReadOnly(True)
        self._diff_text.setStyleSheet(
            f"background:{_PANEL.name()}; color:{_TEXT.name()}; "
            "font-family: Consolas, monospace;"
        )
        lay.addWidget(self._diff_text, 1)
        return w

    # ------------------------------------------------------------------

    def set_config(self, config: "MmmcConfig") -> None:
        self._config = config
        self._populate_corners()
        self._populate_modes()
        self._populate_scenarios()
        self._rebuild_heatmap()
        self._diff_a.clear()
        self._diff_b.clear()
        for sc in config.scenarios:
            self._diff_a.addItem(sc.name)
            self._diff_b.addItem(sc.name)

    def _populate_corners(self) -> None:
        if self._config is None:
            return
        t = self._corners_table
        t.setRowCount(len(self._config.corners))
        for r, c in enumerate(self._config.corners):
            t.setItem(r, 0, QTableWidgetItem(c.name))
            t.setItem(r, 1, QTableWidgetItem(c.process))
            t.setItem(r, 2, QTableWidgetItem(f"{c.voltage:.3f}"))
            t.setItem(r, 3, QTableWidgetItem(f"{c.temperature:.1f}"))
            t.setItem(r, 4, QTableWidgetItem(", ".join(str(p.name) for p in c.lib_files)))
            t.setItem(r, 5, QTableWidgetItem(c.rc_corner))
            t.setItem(r, 6, QTableWidgetItem(f"{c.derate:.3f}"))

    def _populate_modes(self) -> None:
        if self._config is None:
            return
        t = self._modes_table
        t.setRowCount(len(self._config.modes))
        for r, m in enumerate(self._config.modes):
            t.setItem(r, 0, QTableWidgetItem(m.name))
            t.setItem(r, 1, QTableWidgetItem(str(m.sdc_file)))
            t.setItem(r, 2, QTableWidgetItem(", ".join(m.active_clocks)))
            t.setItem(r, 3, QTableWidgetItem(str(m.case_analysis)))

    def _populate_scenarios(self) -> None:
        if self._config is None:
            return
        modes = self._config.modes
        corners = self._config.corners
        t = self._scenarios_matrix
        t.setRowCount(len(modes))
        t.setColumnCount(len(corners))
        t.setHorizontalHeaderLabels([c.name for c in corners])
        t.setVerticalHeaderLabels([m.name for m in modes])
        for i, m in enumerate(modes):
            for j, c in enumerate(corners):
                sc = self._find_scenario(m.name, c.name)
                text = sc.check_type if sc else "-"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, j, item)
        t.resizeColumnsToContents()

    def _rebuild_heatmap(self) -> None:
        if self._config is None:
            return
        modes = self._config.modes
        corners = self._config.corners
        t = self._heatmap
        t.setRowCount(len(modes))
        t.setColumnCount(len(corners))
        t.setHorizontalHeaderLabels([c.name for c in corners])
        t.setVerticalHeaderLabels([m.name for m in modes])

        all_slacks: list[float] = []
        for sc_name, report in self._results.items():
            all_slacks.append(report.wns)
        lo = min(all_slacks, default=-1.0)
        hi = max(all_slacks, default=1.0)

        for i, m in enumerate(modes):
            for j, c in enumerate(corners):
                sc = self._find_scenario(m.name, c.name)
                if sc is None or sc.name not in self._results:
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    t.setItem(i, j, item)
                    continue
                wns = self._results[sc.name].wns
                item = QTableWidgetItem(f"{wns:.3f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(QBrush(_slack_color(wns, lo, hi)))
                item.setForeground(QBrush(QColor("#1e1e2e")))
                t.setItem(i, j, item)
        t.resizeColumnsToContents()

    def _find_scenario(self, mode_name: str, corner_name: str):
        if self._config is None:
            return None
        for sc in self._config.scenarios:
            if sc.mode.name == mode_name and sc.corner.name == corner_name:
                return sc
        return None

    # ------------------------------------------------------------------

    def _on_preset_changed(self, preset: str) -> None:
        if MmmcConfig is None:
            return
        try:
            if preset == "sky130":
                self.set_config(MmmcConfig.sky130_default())
            elif preset == "asap7":
                self.set_config(MmmcConfig.asap7_default())
        except Exception as exc:
            QMessageBox.warning(self, "MMMC", f"Preset failed: {exc}")

    def _on_run(self) -> None:
        if MmmcRunner is None or self._config is None:
            return
        self.run_requested.emit()
        try:
            runner = MmmcRunner(self._config, Path("./mmmc_runs"))
            # Without a real design we just create empty reports to show the flow
            for sc in self._config.scenarios:
                if StaReport is not None:
                    self._results[sc.name] = StaReport()
        except Exception as exc:
            QMessageBox.warning(self, "MMMC", f"Run failed: {exc}")
        self._rebuild_heatmap()

    def set_results(self, results: dict[str, "StaReport"]) -> None:
        self._results = dict(results)
        self._rebuild_heatmap()

    def _on_export_tcl(self) -> None:
        if self._config is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export MMMC Tcl", "mmmc.tcl", "Tcl (*.tcl)"
        )
        if not path:
            return
        Path(path).write_text(self._config.to_openroad_tcl())

    def _on_export_reports(self) -> None:
        path, _ = QFileDialog.getExistingDirectory(
            self, "Choose export directory"
        ) if False else QFileDialog.getSaveFileName(
            self, "Export reports bundle", "mmmc_reports.txt", "Text (*.txt)"
        )
        if not path:
            return
        with open(path, "w") as fh:
            for name, report in self._results.items():
                fh.write(f"# {name}\n")
                fh.write(f"  WNS={report.wns:.3f}  TNS={report.tns:.3f}\n")
                fh.write(f"  WHS={report.whs:.3f}  THS={report.ths:.3f}\n")
                fh.write(f"  violations={report.num_violations}\n\n")

    def _on_diff(self) -> None:
        a = self._diff_a.currentText()
        b = self._diff_b.currentText()
        if not a or not b or a == b:
            return
        ra = self._results.get(a)
        rb = self._results.get(b)
        if ra is None or rb is None:
            self._diff_text.setPlainText(
                f"No results available for {a} or {b}. Run scenarios first."
            )
            return
        lines = [f"Paths whose slack sign flips between {a} and {b}:", ""]
        by_endpoint_a = {p.endpoint: p for p in ra.paths}
        by_endpoint_b = {p.endpoint: p for p in rb.paths}
        shared = set(by_endpoint_a) & set(by_endpoint_b)
        for ep in sorted(shared):
            pa = by_endpoint_a[ep]
            pb = by_endpoint_b[ep]
            if (pa.slack_ns < 0) != (pb.slack_ns < 0):
                lines.append(
                    f"  {ep:40s}  {a}={pa.slack_ns:+.3f}  {b}={pb.slack_ns:+.3f}"
                )
        if len(lines) == 2:
            lines.append("  (no sign flips)")
        self._diff_text.setPlainText("\n".join(lines))


def _slack_color(wns: float, lo: float, hi: float) -> QColor:
    if wns >= 0:
        return QColor("#a6e3a1")
    if lo >= hi:
        return QColor("#f38ba8")
    t = (wns - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    # interpolate red -> yellow
    r = int(243 + (249 - 243) * t)
    g = int(139 + (226 - 139) * t)
    b = int(168 + (175 - 168) * t)
    return QColor(r, g, b)
