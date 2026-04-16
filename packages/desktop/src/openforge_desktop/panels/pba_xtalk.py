"""PBA + Crosstalk + Statistical timing panel.

Four tabs:
  - PBA: GBA vs PBA slack column, pessimism reduction tile
  - CPPR: per-path common-segment view and credit
  - Crosstalk: top victim nets, aggressor list, delta delay/slew
  - Statistical: Monte Carlo histograms, yield, sigma corner table

Everything is populated by calling the ``set_*`` methods. The panel
does not run analyses itself - it displays the results produced by the
core ``physical.pba`` / ``physical.cppr`` / ``physical.crosstalk`` /
``physical.statistical_timing`` modules.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:  # histogram plotting is nice-to-have
    from PySide6.QtCharts import (
        QBarCategoryAxis,
        QBarSeries,
        QBarSet,
        QChart,
        QChartView,
        QValueAxis,
    )

    HAS_CHARTS = True
except Exception:  # pragma: no cover
    HAS_CHARTS = False


class _PbaTab(QWidget):
    apply_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.reduction_label = QLabel("Total pessimism reduction: --")
        self.reduction_label.setStyleSheet(
            "font-weight: bold; font-size: 12pt; color: #4caf50;"
        )
        bar.addWidget(self.reduction_label)
        bar.addStretch(1)
        self.apply_btn = QPushButton("Apply PBA to STA")
        self.apply_btn.clicked.connect(self.apply_requested.emit)
        bar.addWidget(self.apply_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Endpoint", "GBA slack (ns)", "PBA slack (ns)", "GBA delay (ns)", "PBA delay (ns)"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        lay.addWidget(self.table, 1)

    def set_results(self, results: list[Any]) -> None:
        self.table.setRowCount(len(results))
        total = 0.0
        for i, r in enumerate(results):
            self.table.setItem(i, 0, QTableWidgetItem(getattr(r, "endpoint", "")))
            gba_s = float(getattr(r, "slack_gba_ns", 0.0))
            pba_s = float(getattr(r, "slack_pba_ns", 0.0))
            self.table.setItem(i, 1, QTableWidgetItem(f"{gba_s:.3f}"))
            item = QTableWidgetItem(f"{pba_s:.3f}")
            if pba_s < 0:
                item.setForeground(QColor("#ef5350"))
            else:
                item.setForeground(QColor("#4caf50"))
            self.table.setItem(i, 2, item)
            self.table.setItem(
                i, 3, QTableWidgetItem(f"{float(getattr(r, 'gba_delay', 0.0)):.3f}")
            )
            self.table.setItem(
                i, 4, QTableWidgetItem(f"{float(getattr(r, 'pba_delay', 0.0)):.3f}")
            )
            total += float(getattr(r, "pessimism_reduction_ps", 0.0))
        self.reduction_label.setText(
            f"Total pessimism reduction: {total:.1f} ps across {len(results)} paths"
        )


class _CpprTab(QWidget):
    apply_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.total_label = QLabel("Total CPPR credit: --")
        self.total_label.setStyleSheet(
            "font-weight: bold; font-size: 12pt; color: #4caf50;"
        )
        bar.addWidget(self.total_label)
        bar.addStretch(1)
        self.apply_btn = QPushButton("Apply CPPR to STA")
        self.apply_btn.clicked.connect(self.apply_requested.emit)
        bar.addWidget(self.apply_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Endpoint", "Common segment", "Common delay (ps)", "Credit (ps)"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        lay.addWidget(self.table, 1)

    def set_results(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        total = 0.0
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("endpoint", ""))))
            self.table.setItem(
                i, 1, QTableWidgetItem(" > ".join(r.get("common_segment", [])))
            )
            self.table.setItem(
                i, 2, QTableWidgetItem(f"{r.get('common_delay_ps', 0.0):.1f}")
            )
            credit = float(r.get("credit_ps", 0.0))
            self.table.setItem(i, 3, QTableWidgetItem(f"{credit:.1f}"))
            total += credit
        self.total_label.setText(f"Total CPPR credit: {total:.1f} ps")


class _XtalkTab(QWidget):
    apply_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.summary_label = QLabel("Crosstalk: --")
        self.summary_label.setStyleSheet(
            "font-weight: bold; font-size: 12pt; color: #ffb74d;"
        )
        bar.addWidget(self.summary_label)
        bar.addStretch(1)
        self.apply_btn = QPushButton("Apply Crosstalk to STA")
        self.apply_btn.clicked.connect(self.apply_requested.emit)
        bar.addWidget(self.apply_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                "Victim net",
                "Aggressors",
                "Coupling (fF)",
                "Delta delay (ps)",
                "Glitch (V)",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.table, 1)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(160)
        self.detail.setPlaceholderText("Select a victim net to see aggressor details...")
        lay.addWidget(self.detail)

        self._results: list[Any] = []

    def set_results(self, results: list[Any]) -> None:
        self._results = results
        self.table.setRowCount(len(results))
        total_delta = 0.0
        for i, r in enumerate(results):
            self.table.setItem(i, 0, QTableWidgetItem(getattr(r, "victim_net", "")))
            self.table.setItem(i, 1, QTableWidgetItem(str(len(getattr(r, "aggressors", [])))))
            self.table.setItem(
                i, 2, QTableWidgetItem(f"{float(getattr(r, 'total_coupling_ff', 0.0)):.2f}")
            )
            dd = float(getattr(r, "delta_delay_ps", 0.0))
            self.table.setItem(i, 3, QTableWidgetItem(f"{dd:.1f}"))
            self.table.setItem(
                i, 4, QTableWidgetItem(f"{float(getattr(r, 'glitch_voltage_v', 0.0)):.3f}")
            )
            total_delta += dd
        self.summary_label.setText(
            f"Crosstalk: {len(results)} victims, total delta-delay {total_delta:.0f} ps"
        )

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._results):
            return
        r = self._results[idx]
        lines = [f"Victim: {getattr(r, 'victim_net', '')}"]
        lines.append(f"Total coupling: {getattr(r, 'total_coupling_ff', 0.0):.2f} fF")
        lines.append(f"Delta delay:    {getattr(r, 'delta_delay_ps', 0.0):.1f} ps")
        lines.append(f"Delta slew:     {getattr(r, 'delta_slew_ps', 0.0):.1f} ps")
        lines.append(f"Glitch voltage: {getattr(r, 'glitch_voltage_v', 0.0):.3f} V")
        lines.append("")
        lines.append("Aggressors:")
        for a in getattr(r, "aggressors", []):
            lines.append(
                f"  {a.aggressor_net:40s}  {a.coupling_cap_ff:6.2f} fF  "
                f"{a.switching_direction:7s}  "
                f"win=({a.switching_window_ns[0]:.2f},{a.switching_window_ns[1]:.2f}) ns"
            )
        self.detail.setPlainText("\n".join(lines))


class _StatTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.yield_label = QLabel("Yield: --")
        self.yield_label.setStyleSheet(
            "font-weight: bold; font-size: 14pt; color: #4caf50;"
        )
        bar.addWidget(self.yield_label)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Endpoint", "Mean slack (ns)", "Std (ns)", "P1 (ns)", "Yield (%)"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        lay.addWidget(self.table, 1)

        corner_box = QGroupBox("Sigma Corners")
        cl = QVBoxLayout(corner_box)
        self.sigma_table = QTableWidget(0, 2)
        self.sigma_table.setHorizontalHeaderLabels(["Sigma", "Worst slack (ns)"])
        self.sigma_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        cl.addWidget(self.sigma_table)
        lay.addWidget(corner_box)

        if HAS_CHARTS:
            self.chart_view: QChartView | None = QChartView()
            self.chart_view.setMinimumHeight(160)
            lay.addWidget(self.chart_view)
        else:
            self.chart_view = None

    def set_distributions(
        self,
        distributions: list[Any],
        yield_pct: float = 0.0,
        sigma_corners: dict[str, float] | None = None,
    ) -> None:
        self.table.setRowCount(len(distributions))
        for i, d in enumerate(distributions):
            self.table.setItem(i, 0, QTableWidgetItem(getattr(d, "endpoint", "")))
            self.table.setItem(
                i, 1, QTableWidgetItem(f"{float(getattr(d, 'mean_slack', 0.0)):.3f}")
            )
            self.table.setItem(
                i, 2, QTableWidgetItem(f"{float(getattr(d, 'std_slack', 0.0)):.3f}")
            )
            self.table.setItem(
                i, 3, QTableWidgetItem(f"{float(getattr(d, 'p01_slack', 0.0)):.3f}")
            )
            y = float(getattr(d, "yield_pct", 0.0))
            item = QTableWidgetItem(f"{y:.1f}")
            if y < 90:
                item.setForeground(QColor("#ef5350"))
            elif y < 99:
                item.setForeground(QColor("#ffb74d"))
            else:
                item.setForeground(QColor("#4caf50"))
            self.table.setItem(i, 4, item)
        self.yield_label.setText(f"Yield: {yield_pct:.2f}%")

        # sigma corner table
        if sigma_corners:
            self.sigma_table.setRowCount(len(sigma_corners))
            for i, (sig, slack) in enumerate(sigma_corners.items()):
                self.sigma_table.setItem(i, 0, QTableWidgetItem(sig))
                self.sigma_table.setItem(i, 1, QTableWidgetItem(f"{slack:.3f}"))

        if HAS_CHARTS and self.chart_view is not None and distributions:
            # Build histogram of mean-slack across paths
            import math

            slacks = [float(getattr(d, "mean_slack", 0.0)) for d in distributions]
            if slacks:
                lo = min(slacks)
                hi = max(slacks)
                if hi <= lo:
                    hi = lo + 1.0
                nbins = 20
                step = (hi - lo) / nbins
                counts = [0] * nbins
                for s in slacks:
                    idx = min(nbins - 1, max(0, int((s - lo) / step)))
                    counts[idx] += 1
                chart = QChart()
                chart.setTitle("Path slack distribution")
                bset = QBarSet("paths")
                for c in counts:
                    bset.append(c)
                series = QBarSeries()
                series.append(bset)
                chart.addSeries(series)
                cats = [
                    f"{lo + i * step:.2f}" for i in range(nbins)
                ]
                ax_x = QBarCategoryAxis()
                ax_x.append(cats)
                ax_y = QValueAxis()
                ax_y.setRange(0, max(counts) if counts else 1)
                chart.addAxis(ax_x, Qt.AlignmentFlag.AlignBottom)
                chart.addAxis(ax_y, Qt.AlignmentFlag.AlignLeft)
                series.attachAxis(ax_x)
                series.attachAxis(ax_y)
                self.chart_view.setChart(chart)
                _ = math  # silence


class PbaXtalkPanel(QWidget):
    """Parent panel with PBA / CPPR / Crosstalk / Statistical tabs."""

    sta_updated = Signal(object)  # emits a corrected StaReport
    load_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PBA / Crosstalk")
        self._sta_report: Any = None
        self._spef_file: Any = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Path-based / Crosstalk analysis</b>"))
        bar.addStretch(1)
        self.load_sta_btn = QPushButton("Load STA report...")
        self.load_sta_btn.clicked.connect(self._on_load_sta)
        bar.addWidget(self.load_sta_btn)
        self.load_spef_btn = QPushButton("Load SPEF...")
        self.load_spef_btn.clicked.connect(self._on_load_spef)
        bar.addWidget(self.load_spef_btn)
        root.addLayout(bar)

        self.tabs = QTabWidget()
        self.pba_tab = _PbaTab()
        self.cppr_tab = _CpprTab()
        self.xtalk_tab = _XtalkTab()
        self.stat_tab = _StatTab()
        self.tabs.addTab(self.pba_tab, "PBA")
        self.tabs.addTab(self.cppr_tab, "CPPR")
        self.tabs.addTab(self.xtalk_tab, "Crosstalk")
        self.tabs.addTab(self.stat_tab, "Statistical")
        root.addWidget(self.tabs, 1)

        self.pba_tab.apply_requested.connect(self._on_apply_pba)
        self.cppr_tab.apply_requested.connect(self._on_apply_cppr)
        self.xtalk_tab.apply_requested.connect(self._on_apply_xtalk)

    # ------------------------------------------------------------------ data

    def set_sta_report(self, report: Any) -> None:
        self._sta_report = report
        self._refresh_all()

    def set_spef(self, spef: Any) -> None:
        self._spef_file = spef
        self._refresh_all()

    # ------------------------------------------------------------------ actions

    def _on_load_sta(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load STA report", "", "Text (*.txt *.rpt);;All files (*)"
        )
        if not path:
            return
        try:
            from openforge.physical.sta_parser import parse_sta_report_file

            self._sta_report = parse_sta_report_file(path)
            self._refresh_all()
        except Exception:
            pass

    def _on_load_spef(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load SPEF", "", "SPEF (*.spef);;All files (*)"
        )
        if not path:
            return
        try:
            from openforge.format.spef_parser import SpefFile

            self._spef_file = SpefFile.parse(path)
            self._refresh_all()
        except Exception:
            pass

    def _refresh_all(self) -> None:
        if self._sta_report is None:
            return
        try:
            from openforge.physical.cppr import CpprAnalyzer
            from openforge.physical.pba import PbaAnalyzer
            from openforge.physical.statistical_timing import (
                MonteCarloTiming,
                ProcessVariation,
            )

            pba = PbaAnalyzer(self._sta_report)
            pba_results = pba.analyze_all_critical_paths()
            self.pba_tab.set_results(pba_results)

            cppr = CpprAnalyzer(self._sta_report)
            rows: list[dict] = []
            for p in self._sta_report.paths:
                cp = cppr.find_common(p)
                rows.append(
                    {
                        "endpoint": p.endpoint,
                        "common_segment": cp.common_segment,
                        "common_delay_ps": cp.common_delay_ps,
                        "credit_ps": cppr.cppr_credit_ps(p),
                    }
                )
            self.cppr_tab.set_results(rows)

            mc = MonteCarloTiming(
                self._sta_report,
                ProcessVariation(),
                samples=500,
            )
            dists = mc.run()
            self.stat_tab.set_distributions(
                dists,
                mc.yield_estimate(),
                mc.sigma_corner_report(),
            )
        except Exception:
            pass

        if self._spef_file is not None and self._sta_report is not None:
            try:
                from openforge.physical.crosstalk import CrosstalkAnalyzer

                xt = CrosstalkAnalyzer(self._spef_file, self._sta_report)
                self.xtalk_tab.set_results(xt.analyze_top_n(50))
            except Exception:
                pass

    def _on_apply_pba(self) -> None:
        if self._sta_report is None:
            return
        try:
            from openforge.physical.pba import PbaAnalyzer

            pba = PbaAnalyzer(self._sta_report)
            results = pba.analyze_all_critical_paths()
            # Fold PBA slack into report
            import copy

            new_report = copy.copy(self._sta_report)
            new_report.paths = []
            for p, r in zip(self._sta_report.paths, results, strict=False):
                np_ = copy.copy(p)
                np_.slack_ns = r.slack_pba_ns
                new_report.paths.append(np_)
            self._sta_report = new_report
            self.sta_updated.emit(new_report)
            self._refresh_all()
        except Exception:
            pass

    def _on_apply_cppr(self) -> None:
        if self._sta_report is None:
            return
        try:
            from openforge.physical.cppr import CpprAnalyzer

            cppr = CpprAnalyzer(self._sta_report)
            self._sta_report = cppr.apply_to_report()
            self.sta_updated.emit(self._sta_report)
            self._refresh_all()
        except Exception:
            pass

    def _on_apply_xtalk(self) -> None:
        if self._sta_report is None or self._spef_file is None:
            return
        try:
            from openforge.physical.crosstalk import CrosstalkAnalyzer

            xt = CrosstalkAnalyzer(self._spef_file, self._sta_report)
            self._sta_report = xt.apply_xtalk_to_sta(self._sta_report)
            self.sta_updated.emit(self._sta_report)
            self._refresh_all()
        except Exception:
            pass


__all__ = ["PbaXtalkPanel"]
