"""Reliability dashboard - IR drop, EM, thermal, EMI, ESD.

This panel wires the real reliability backends in
``openforge.physical`` into a Qt dashboard.  Each tool runs on a
background ``QThread`` so the UI never blocks, and results are rendered
as matplotlib heatmaps plus populated violation tables.

Catppuccin Mocha colors are used for the widgets.
"""

from __future__ import annotations

import contextlib
import math
import traceback
from dataclasses import is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Matplotlib Qt canvas for real heatmaps
try:
    import numpy as np  # noqa: F401 (used by matplotlib canvas paths)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # type: ignore
    from matplotlib.figure import Figure  # type: ignore

    _MPL_OK = True
except Exception:  # pragma: no cover - matplotlib optional
    FigureCanvasQTAgg = None  # type: ignore
    Figure = None  # type: ignore
    _MPL_OK = False


# ---------------------------------------------------------------------------
# Catppuccin Mocha palette (small subset used by the panel)
# ---------------------------------------------------------------------------
MOCHA = {
    "base": "#1e1e2e",
    "mantle": "#181825",
    "surface0": "#313244",
    "surface1": "#45475a",
    "text": "#cdd6f4",
    "subtext0": "#a6adc8",
    "blue": "#89b4fa",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "peach": "#fab387",
    "red": "#f38ba8",
    "mauve": "#cba6f7",
    "teal": "#94e2d5",
}


# ---------------------------------------------------------------------------
# Reliability radar chart (header widget)
# ---------------------------------------------------------------------------
class _ReliabilityRadar(QWidget):
    """A small five-axis radar chart for the reliability score."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMinimumWidth(240)
        self._scores: dict[str, float] = {
            "IR Drop": 0.0,
            "EM": 0.0,
            "Thermal": 0.0,
            "EMI": 0.0,
            "ESD": 0.0,
        }

    def set_scores(self, scores: dict[str, float]) -> None:
        for key in self._scores:
            if key in scores:
                self._scores[key] = max(0.0, min(100.0, scores[key]))
        self.update()

    def overall(self) -> float:
        if not self._scores:
            return 0.0
        return sum(self._scores.values()) / len(self._scores)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(20, 20, -20, -20)
        cx = rect.center().x()
        cy = rect.center().y()
        radius = min(rect.width(), rect.height()) / 2.0 - 10

        labels = list(self._scores.keys())
        n = len(labels)
        p.setPen(QPen(QColor(MOCHA["surface1"]), 1))
        for ring in (0.25, 0.5, 0.75, 1.0):
            r = radius * ring
            poly = QPolygonF()
            for i in range(n):
                a = -math.pi / 2 + 2 * math.pi * i / n
                poly.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
            p.drawPolygon(poly)

        p.setPen(QPen(QColor(MOCHA["subtext0"]), 1))
        font = QFont(self.font())
        font.setPointSize(8)
        p.setFont(font)
        for i, label in enumerate(labels):
            a = -math.pi / 2 + 2 * math.pi * i / n
            x = cx + radius * math.cos(a)
            y = cy + radius * math.sin(a)
            p.drawLine(QPointF(cx, cy), QPointF(x, y))
            tx = cx + (radius + 14) * math.cos(a) - 22
            ty = cy + (radius + 14) * math.sin(a) + 4
            p.drawText(QPointF(tx, ty), label)

        poly = QPolygonF()
        for i, key in enumerate(labels):
            a = -math.pi / 2 + 2 * math.pi * i / n
            r = radius * (self._scores[key] / 100.0)
            poly.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        gradient = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
        gradient.setColorAt(0.0, QColor(166, 227, 161, 160))  # green
        gradient.setColorAt(1.0, QColor(137, 180, 250, 160))  # blue
        p.setBrush(QBrush(gradient))
        p.setPen(QPen(QColor(MOCHA["teal"]), 2))
        p.drawPolygon(poly)

        font.setPointSize(14)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor(MOCHA["text"])))
        overall = f"{self.overall():.0f}"
        p.drawText(QRectF(cx - 30, cy - 12, 60, 24), Qt.AlignmentFlag.AlignCenter, overall)
        p.end()


# ---------------------------------------------------------------------------
# Matplotlib heatmap canvas (with pure-Qt fallback)
# ---------------------------------------------------------------------------
if _MPL_OK:

    class _HeatmapCanvas(FigureCanvasQTAgg):  # type: ignore[misc]
        """Matplotlib pcolormesh canvas used for IR-drop and thermal maps."""

        def __init__(self, parent: QWidget | None = None) -> None:
            self._fig = Figure(figsize=(5, 4), tight_layout=True, facecolor=MOCHA["base"])
            super().__init__(self._fig)
            if parent is not None:
                self.setParent(parent)
            self._ax = self._fig.add_subplot(111)
            self._cbar = None
            self._style_axes()
            self.setMinimumHeight(260)

        def _style_axes(self) -> None:
            self._ax.set_facecolor(MOCHA["mantle"])
            for spine in self._ax.spines.values():
                spine.set_color(MOCHA["surface1"])
            self._ax.tick_params(colors=MOCHA["subtext0"], labelsize=8)
            self._ax.xaxis.label.set_color(MOCHA["text"])
            self._ax.yaxis.label.set_color(MOCHA["text"])
            self._ax.title.set_color(MOCHA["text"])

        def show_grid(
            self,
            grid: list[list[float]],
            extent_um: tuple[float, float],
            title: str,
            cmap: str = "inferno",
            units: str = "",
        ) -> None:
            import numpy as np  # local import to keep module import fast

            self._ax.clear()
            self._style_axes()
            if not grid or not grid[0]:
                self._ax.text(
                    0.5,
                    0.5,
                    "No data",
                    color=MOCHA["subtext0"],
                    ha="center",
                    va="center",
                    transform=self._ax.transAxes,
                )
                self.draw_idle()
                return
            arr = np.asarray(grid, dtype=float)
            rows, cols = arr.shape
            w_um, h_um = extent_um
            xs = np.linspace(0, w_um, cols + 1)
            ys = np.linspace(0, h_um, rows + 1)
            mesh = self._ax.pcolormesh(xs, ys, arr, cmap=cmap, shading="auto")
            self._ax.set_title(title)
            self._ax.set_xlabel("X (um)")
            self._ax.set_ylabel("Y (um)")
            self._ax.set_aspect("equal", adjustable="box")
            if self._cbar is not None:
                with contextlib.suppress(Exception):
                    self._cbar.remove()
            self._cbar = self._fig.colorbar(mesh, ax=self._ax)
            if units:
                self._cbar.set_label(units, color=MOCHA["text"])
            self._cbar.ax.yaxis.set_tick_params(color=MOCHA["subtext0"])
            for t in self._cbar.ax.get_yticklabels():
                t.set_color(MOCHA["subtext0"])
            self.draw_idle()

        def show_spectrum(
            self,
            freqs_mhz: list[float],
            mags_db: list[float],
            limit_curve: list[tuple[float, float]],
            title: str,
        ) -> None:
            import numpy as np

            self._ax.clear()
            self._style_axes()
            if not freqs_mhz:
                self._ax.text(
                    0.5,
                    0.5,
                    "Run EMI/EMC analysis to view spectrum",
                    color=MOCHA["subtext0"],
                    ha="center",
                    va="center",
                    transform=self._ax.transAxes,
                )
                self.draw_idle()
                return
            f = np.asarray(freqs_mhz, dtype=float)
            m = np.asarray(mags_db, dtype=float)
            self._ax.stem(
                f,
                m,
                linefmt=MOCHA["teal"],
                markerfmt=" ",
                basefmt=" ",
            )
            if limit_curve:
                lf = [pt[0] for pt in limit_curve]
                lm = [pt[1] for pt in limit_curve]
                self._ax.plot(lf, lm, color=MOCHA["red"], linestyle="--", label="FCC limit")
                self._ax.legend(
                    facecolor=MOCHA["surface0"],
                    edgecolor=MOCHA["surface1"],
                    labelcolor=MOCHA["text"],
                )
            self._ax.set_xscale("log")
            self._ax.set_xlabel("Frequency (MHz)")
            self._ax.set_ylabel("dBuV/m")
            self._ax.set_title(title)
            if self._cbar is not None:
                try:
                    self._cbar.remove()
                    self._cbar = None
                except Exception:
                    pass
            self.draw_idle()

else:  # matplotlib missing - tiny Qt stub so the panel still loads

    class _HeatmapCanvas(QWidget):  # type: ignore[no-redef]
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setMinimumHeight(260)
            self._label = QLabel("matplotlib not installed - heatmap unavailable", self)
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._label.setStyleSheet(f"color: {MOCHA['subtext0']};")
            lay = QVBoxLayout(self)
            lay.addWidget(self._label)

        def show_grid(self, *args, **kwargs) -> None:  # noqa: D401
            return

        def show_spectrum(self, *args, **kwargs) -> None:  # noqa: D401
            return


# ---------------------------------------------------------------------------
# Worker: runs a blocking analyzer callable off the UI thread
# ---------------------------------------------------------------------------
class _AnalysisWorker(QObject):
    """Runs a zero-arg callable and reports progress/result via signals."""

    progress = Signal(float, str)
    finished = Signal(str, object)  # kind, result
    failed = Signal(str, str)  # kind, traceback

    def __init__(self, kind: str, fn: Callable[[Callable[[float, str], None]], Any]) -> None:
        super().__init__()
        self._kind = kind
        self._fn = fn

    def run(self) -> None:
        def _progress(frac: float, msg: str) -> None:
            with contextlib.suppress(Exception):
                self.progress.emit(float(frac), str(msg))

        try:
            result = self._fn(_progress)
        except Exception:
            self.failed.emit(self._kind, traceback.format_exc())
            return
        self.finished.emit(self._kind, result)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
class ReliabilityPanel(QDockWidget):
    """Reliability dashboard - IR drop, EM, thermal, EMI, ESD."""

    analysis_completed = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Reliability", parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setObjectName("ReliabilityPanel")

        self._last_results: dict[str, Any] = {}
        self._workers: dict[str, tuple[QThread, _AnalysisWorker]] = {}

        root = QWidget(self)
        root.setStyleSheet(
            f"QWidget {{ background: {MOCHA['base']}; color: {MOCHA['text']}; }}"
            f"QGroupBox {{ border: 1px solid {MOCHA['surface1']}; border-radius: 6px;"
            f" margin-top: 10px; padding: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;"
            f" color: {MOCHA['mauve']}; }}"
            f"QPushButton {{ background: {MOCHA['surface0']}; color: {MOCHA['text']};"
            f" border: 1px solid {MOCHA['surface1']}; padding: 4px 10px; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {MOCHA['surface1']}; }}"
            f"QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit, QListWidget, QTableWidget"
            f" {{ background: {MOCHA['mantle']}; color: {MOCHA['text']};"
            f" border: 1px solid {MOCHA['surface1']}; }}"
            f"QProgressBar {{ background: {MOCHA['mantle']}; border: 1px solid"
            f" {MOCHA['surface1']}; color: {MOCHA['text']}; text-align: center; }}"
            f"QProgressBar::chunk {{ background: {MOCHA['green']}; }}"
            f"QHeaderView::section {{ background: {MOCHA['surface0']}; color: {MOCHA['text']};"
            f" padding: 2px; border: none; }}"
            f"QTabWidget::pane {{ border: 1px solid {MOCHA['surface1']}; }}"
            f"QTabBar::tab {{ background: {MOCHA['mantle']}; color: {MOCHA['subtext0']};"
            f" padding: 6px 12px; }}"
            f"QTabBar::tab:selected {{ background: {MOCHA['surface0']}; color: {MOCHA['text']}; }}"
        )
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # ----- Header: radar + summary --------------------------------
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header_layout = QHBoxLayout(header)

        self.radar = _ReliabilityRadar()
        header_layout.addWidget(self.radar, 0)

        summary_box = QGroupBox("Reliability Score")
        summary_layout = QFormLayout(summary_box)
        self.lbl_overall = QLabel("--")
        self.lbl_overall.setStyleSheet(
            f"font-size: 22px; color: {MOCHA['green']}; font-weight: bold;"
        )
        self.lbl_ir = QLabel("--")
        self.lbl_em = QLabel("--")
        self.lbl_thermal = QLabel("--")
        self.lbl_emi = QLabel("--")
        self.lbl_esd = QLabel("--")
        summary_layout.addRow("Overall:", self.lbl_overall)
        summary_layout.addRow("IR Drop:", self.lbl_ir)
        summary_layout.addRow("EM:", self.lbl_em)
        summary_layout.addRow("Thermal:", self.lbl_thermal)
        summary_layout.addRow("EMI:", self.lbl_emi)
        summary_layout.addRow("ESD:", self.lbl_esd)
        header_layout.addWidget(summary_box, 1)

        actions_box = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout(actions_box)
        self.btn_run_all = QPushButton("Run All Analyses")
        self.btn_export_report = QPushButton("Export Combined Report")
        self.btn_clear = QPushButton("Clear Results")
        actions_layout.addWidget(self.btn_run_all)
        actions_layout.addWidget(self.btn_export_report)
        actions_layout.addWidget(self.btn_clear)
        actions_layout.addStretch()
        header_layout.addWidget(actions_box, 0)

        root_layout.addWidget(header)

        # ----- Tabs ----------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_ir_tab(), "IR Drop")
        self.tabs.addTab(self._build_em_tab(), "Electromigration")
        self.tabs.addTab(self._build_thermal_tab(), "Thermal")
        self.tabs.addTab(self._build_emi_tab(), "EMI / EMC")
        self.tabs.addTab(self._build_esd_tab(), "ESD")
        root_layout.addWidget(self.tabs, 1)

        # ----- Global status + progress --------------------------------
        status_row = QHBoxLayout()
        self.status = QLabel("Idle")
        self.status.setStyleSheet(f"color: {MOCHA['subtext0']}; padding: 4px;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(260)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.progress, 0)
        root_layout.addLayout(status_row)

        self.setWidget(root)

        # Wire up
        self.btn_run_all.clicked.connect(self._run_all)
        self.btn_export_report.clicked.connect(self._export_report)
        self.btn_clear.clicked.connect(self._clear_results)

    # ==================================================================
    # Tab builders
    # ==================================================================
    def _row(self, *widgets: QWidget) -> QWidget:
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            h.addWidget(w)
        return c

    def _browse(self, target: QLineEdit, filt: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", filt)
        if path:
            target.setText(path)

    # ------------------------------------------------------------------
    def _build_ir_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        self.ir_def_path = QLineEdit()
        btn_def = QPushButton("Browse...")
        btn_def.clicked.connect(lambda: self._browse(self.ir_def_path, "DEF (*.def)"))
        form.addRow("DEF:", self._row(self.ir_def_path, btn_def))

        self.ir_voltage = QDoubleSpinBox()
        self.ir_voltage.setRange(0.5, 5.0)
        self.ir_voltage.setValue(1.8)
        self.ir_voltage.setDecimals(3)
        self.ir_voltage.setSuffix(" V")

        self.ir_sheet_r = QDoubleSpinBox()
        self.ir_sheet_r.setRange(0.001, 10.0)
        self.ir_sheet_r.setValue(0.1)
        self.ir_sheet_r.setDecimals(3)
        self.ir_sheet_r.setSuffix(" ohm/sq")

        self.ir_grid_um = QDoubleSpinBox()
        self.ir_grid_um.setRange(0.5, 100.0)
        self.ir_grid_um.setValue(5.0)
        self.ir_grid_um.setSuffix(" um")

        self.ir_threshold_pct = QDoubleSpinBox()
        self.ir_threshold_pct.setRange(1.0, 50.0)
        self.ir_threshold_pct.setValue(10.0)
        self.ir_threshold_pct.setSuffix(" %")

        form.addRow("Nominal VDD:", self.ir_voltage)
        form.addRow("Sheet R:", self.ir_sheet_r)
        form.addRow("Grid pitch:", self.ir_grid_um)
        form.addRow("Violation threshold:", self.ir_threshold_pct)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.ir_run_btn = QPushButton("Run IR Drop")
        self.ir_export_btn = QPushButton("Export CSV")
        controls.addWidget(self.ir_run_btn)
        controls.addWidget(self.ir_export_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.ir_canvas = _HeatmapCanvas()
        layout.addWidget(self.ir_canvas, 1)

        self.ir_table = QTableWidget(0, 4)
        self.ir_table.setHorizontalHeaderLabels(["X (um)", "Y (um)", "Drop (mV)", "V (V)"])
        self.ir_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ir_table.setMaximumHeight(160)
        layout.addWidget(self.ir_table)

        self.ir_summary = QTextEdit()
        self.ir_summary.setReadOnly(True)
        self.ir_summary.setMaximumHeight(90)
        layout.addWidget(self.ir_summary)

        self.ir_run_btn.clicked.connect(self._run_ir_drop)
        self.ir_export_btn.clicked.connect(lambda: self._export_csv("ir_drop"))
        return w

    # ------------------------------------------------------------------
    def _build_em_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.em_def_path = QLineEdit()
        b1 = QPushButton("Browse...")
        b1.clicked.connect(lambda: self._browse(self.em_def_path, "DEF (*.def)"))
        form.addRow("DEF:", self._row(self.em_def_path, b1))

        self.em_temperature = QDoubleSpinBox()
        self.em_temperature.setRange(-40.0, 200.0)
        self.em_temperature.setValue(110.0)
        self.em_temperature.setSuffix(" C")
        form.addRow("Junction T:", self.em_temperature)

        self.em_default_i_ma = QDoubleSpinBox()
        self.em_default_i_ma.setRange(0.001, 1000.0)
        self.em_default_i_ma.setValue(0.5)
        self.em_default_i_ma.setSuffix(" mA")
        form.addRow("Default I per net:", self.em_default_i_ma)

        layout.addLayout(form)

        controls = QHBoxLayout()
        self.em_run_btn = QPushButton("Run EM")
        self.em_export_btn = QPushButton("Export CSV")
        controls.addWidget(self.em_run_btn)
        controls.addWidget(self.em_export_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.em_table = QTableWidget(0, 6)
        self.em_table.setHorizontalHeaderLabels(
            ["Net", "Layer", "Width (um)", "Density (mA/um)", "Limit (mA/um)", "Severity"]
        )
        self.em_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.em_table, 1)

        self.em_summary = QTextEdit()
        self.em_summary.setReadOnly(True)
        self.em_summary.setMaximumHeight(110)
        layout.addWidget(self.em_summary)

        self.em_run_btn.clicked.connect(self._run_em)
        self.em_export_btn.clicked.connect(lambda: self._export_csv("em"))
        return w

    # ------------------------------------------------------------------
    def _build_thermal_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.th_def_path = QLineEdit()
        b = QPushButton("Browse...")
        b.clicked.connect(lambda: self._browse(self.th_def_path, "DEF (*.def)"))
        form.addRow("DEF:", self._row(self.th_def_path, b))

        self.th_ambient = QDoubleSpinBox()
        self.th_ambient.setRange(-40.0, 125.0)
        self.th_ambient.setValue(25.0)
        self.th_ambient.setSuffix(" C")

        self.th_rja = QDoubleSpinBox()
        self.th_rja.setRange(0.01, 200.0)
        self.th_rja.setValue(10.0)
        self.th_rja.setSuffix(" K/W")

        self.th_total_power = QDoubleSpinBox()
        self.th_total_power.setRange(0.001, 500.0)
        self.th_total_power.setValue(0.5)
        self.th_total_power.setDecimals(3)
        self.th_total_power.setSuffix(" W")

        self.th_grid_um = QDoubleSpinBox()
        self.th_grid_um.setRange(1.0, 200.0)
        self.th_grid_um.setValue(10.0)
        self.th_grid_um.setSuffix(" um")

        self.th_iterations = QSpinBox()
        self.th_iterations.setRange(10, 5000)
        self.th_iterations.setValue(200)

        form.addRow("Ambient:", self.th_ambient)
        form.addRow("Package R:", self.th_rja)
        form.addRow("Total power:", self.th_total_power)
        form.addRow("Grid pitch:", self.th_grid_um)
        form.addRow("Max iters:", self.th_iterations)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.th_run_btn = QPushButton("Run Steady State")
        self.th_export_btn = QPushButton("Export CSV")
        controls.addWidget(self.th_run_btn)
        controls.addWidget(self.th_export_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.th_canvas = _HeatmapCanvas()
        layout.addWidget(self.th_canvas, 1)

        self.th_hotspots = QListWidget()
        self.th_hotspots.setMaximumHeight(120)
        layout.addWidget(self.th_hotspots)

        self.th_summary = QTextEdit()
        self.th_summary.setReadOnly(True)
        self.th_summary.setMaximumHeight(100)
        layout.addWidget(self.th_summary)

        self.th_run_btn.clicked.connect(self._run_thermal)
        self.th_export_btn.clicked.connect(lambda: self._export_csv("thermal"))
        return w

    # ------------------------------------------------------------------
    def _build_emi_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.emi_freq = QDoubleSpinBox()
        self.emi_freq.setRange(1.0, 5000.0)
        self.emi_freq.setValue(100.0)
        self.emi_freq.setSuffix(" MHz")
        self.emi_current = QDoubleSpinBox()
        self.emi_current.setRange(0.1, 1000.0)
        self.emi_current.setValue(10.0)
        self.emi_current.setSuffix(" mA")
        self.emi_pkg_l = QDoubleSpinBox()
        self.emi_pkg_l.setRange(0.1, 100.0)
        self.emi_pkg_l.setValue(5.0)
        self.emi_pkg_l.setSuffix(" nH")
        self.emi_trace_len = QDoubleSpinBox()
        self.emi_trace_len.setRange(0.001, 10.0)
        self.emi_trace_len.setValue(0.05)
        self.emi_trace_len.setDecimals(3)
        self.emi_trace_len.setSuffix(" m")
        form.addRow("Clock frequency:", self.emi_freq)
        form.addRow("Switching current:", self.emi_current)
        form.addRow("Package L:", self.emi_pkg_l)
        form.addRow("Trace length:", self.emi_trace_len)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.emi_run_btn = QPushButton("Run EMI/EMC")
        self.emi_export_btn = QPushButton("Export CSV")
        controls.addWidget(self.emi_run_btn)
        controls.addWidget(self.emi_export_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.emi_canvas = _HeatmapCanvas()
        layout.addWidget(self.emi_canvas, 1)

        self.emi_summary = QTextEdit()
        self.emi_summary.setReadOnly(True)
        self.emi_summary.setMaximumHeight(120)
        layout.addWidget(self.emi_summary)

        self.emi_run_btn.clicked.connect(self._run_emi)
        self.emi_export_btn.clicked.connect(lambda: self._export_csv("emi"))
        return w

    # ------------------------------------------------------------------
    def _build_esd_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.esd_def_path = QLineEdit()
        b = QPushButton("Browse...")
        b.clicked.connect(lambda: self._browse(self.esd_def_path, "DEF (*.def)"))
        form.addRow("DEF:", self._row(self.esd_def_path, b))

        self.esd_netlist = QLineEdit()
        b2 = QPushButton("Browse...")
        b2.clicked.connect(lambda: self._browse(self.esd_netlist, "Verilog (*.v)"))
        form.addRow("Netlist:", self._row(self.esd_netlist, b2))

        self.esd_clamp_keywords = QLineEdit("esd,clamp,diode")
        form.addRow("Clamp cell keywords:", self.esd_clamp_keywords)

        self.esd_model = QComboBox()
        self.esd_model.addItems(["HBM 2.0 kV", "HBM 4.0 kV", "HBM 8.0 kV", "CDM 500 V"])
        form.addRow("Model:", self.esd_model)

        self.esd_max_dist = QDoubleSpinBox()
        self.esd_max_dist.setRange(1.0, 2000.0)
        self.esd_max_dist.setValue(100.0)
        self.esd_max_dist.setSuffix(" um")
        form.addRow("Max clamp distance:", self.esd_max_dist)

        layout.addLayout(form)

        controls = QHBoxLayout()
        self.esd_run_btn = QPushButton("Run ESD")
        self.esd_export_btn = QPushButton("Export CSV")
        controls.addWidget(self.esd_run_btn)
        controls.addWidget(self.esd_export_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.esd_table = QTableWidget(0, 5)
        self.esd_table.setHorizontalHeaderLabels(
            ["Pin", "Target", "Distance (um)", "R (ohm)", "Status"]
        )
        self.esd_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.esd_table, 1)

        self.esd_summary = QTextEdit()
        self.esd_summary.setReadOnly(True)
        self.esd_summary.setMaximumHeight(110)
        layout.addWidget(self.esd_summary)

        self.esd_run_btn.clicked.connect(self._run_esd)
        self.esd_export_btn.clicked.connect(lambda: self._export_csv("esd"))
        return w

    # ==================================================================
    # Worker plumbing
    # ==================================================================
    def _set_status(self, msg: str) -> None:
        self.status.setText(msg)

    def _require_file(self, line: QLineEdit, label: str) -> Path | None:
        txt = line.text().strip()
        if not txt:
            QMessageBox.information(self, "Missing Input", f"Load {label} first")
            return None
        p = Path(txt)
        if not p.exists():
            QMessageBox.warning(self, "File Not Found", f"{label} path does not exist:\n{p}")
            return None
        return p

    def _start_worker(
        self,
        kind: str,
        run_button: QPushButton,
        fn: Callable[[Callable[[float, str], None]], Any],
    ) -> None:
        # Prevent double-dispatch
        if kind in self._workers:
            QMessageBox.information(self, "Busy", f"{kind} is already running")
            return

        thread = QThread(self)
        worker = _AnalysisWorker(kind, fn)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda k=kind: self._cleanup_worker(k))

        self._workers[kind] = (thread, worker)
        run_button.setEnabled(False)
        self.progress.setValue(0)
        self._set_status(f"Running {kind}...")
        thread.start()

    def _cleanup_worker(self, kind: str) -> None:
        pair = self._workers.pop(kind, None)
        if pair is None:
            return
        thread, worker = pair
        with contextlib.suppress(Exception):
            worker.deleteLater()
        with contextlib.suppress(Exception):
            thread.deleteLater()
        for btn in (
            getattr(self, "ir_run_btn", None),
            getattr(self, "em_run_btn", None),
            getattr(self, "th_run_btn", None),
            getattr(self, "emi_run_btn", None),
            getattr(self, "esd_run_btn", None),
        ):
            if btn is not None:
                btn.setEnabled(True)

    def _on_worker_progress(self, frac: float, msg: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 100))
        if msg:
            self._set_status(msg)

    def _on_worker_failed(self, kind: str, tb: str) -> None:
        self.progress.setValue(0)
        self._set_status(f"{kind} failed")
        QMessageBox.critical(self, f"{kind} failed", tb)

    def _on_worker_finished(self, kind: str, result: Any) -> None:
        self.progress.setValue(100)
        self._last_results[kind] = result
        try:
            handler = {
                "ir_drop": self._present_ir,
                "em": self._present_em,
                "thermal": self._present_thermal,
                "emi": self._present_emi,
                "esd": self._present_esd,
            }[kind]
            handler(result)
        except Exception as exc:
            QMessageBox.warning(self, "Display Error", f"{kind}: {exc}")
        self._update_radar()
        self._set_status(f"{kind} complete")
        summary: dict[str, Any] = {}
        if is_dataclass(result):
            for attr in (
                "max_drop_mv",
                "max_temp_c",
                "critical_count",
                "hbm_compliant",
                "fcc_class_b_compliant",
            ):
                if hasattr(result, attr):
                    summary[attr] = getattr(result, attr)
        self.analysis_completed.emit(kind, summary)

    # ==================================================================
    # Run dispatchers
    # ==================================================================
    def _run_ir_drop(self) -> None:
        def_path = self._require_file(self.ir_def_path, "DEF")
        if def_path is None:
            return
        try:
            from openforge.physical.ir_drop import IrDropEstimator
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Cannot load IR backend: {exc}")
            return

        vdd = self.ir_voltage.value()
        sheet_r = self.ir_sheet_r.value()
        grid_um = self.ir_grid_um.value()

        def fn(progress: Callable[[float, str], None]) -> Any:
            progress(0.05, "Parsing DEF...")
            est = IrDropEstimator(vdd=vdd, sheet_resistance_ohm_per_sq=sheet_r)
            progress(0.25, "Solving IR grid...")
            result = est.estimate(def_path, cell_powers={}, grid_resolution_um=grid_um)
            progress(1.0, "IR drop done")
            return result

        self._start_worker("ir_drop", self.ir_run_btn, fn)

    def _run_em(self) -> None:
        def_path = self._require_file(self.em_def_path, "DEF")
        if def_path is None:
            return
        try:
            from openforge.physical.electromigration import ElectromigrationAnalyzer
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Cannot load EM backend: {exc}")
            return

        temperature = self.em_temperature.value()
        default_i = self.em_default_i_ma.value() * 1e-3  # A

        def fn(progress: Callable[[float, str], None]) -> Any:
            # Parse the DEF up front so we can populate a real per-net current
            # map (the backend falls back to 1e-5 A for unknown nets, which
            # hides realistic violations).
            from openforge.physical import electromigration as em_mod

            progress(0.05, "Parsing DEF routes...")
            parser = em_mod._DefRouteParser(def_path)
            wires = parser.parse()
            net_currents = {w.net: default_i for w in wires}
            analyzer = ElectromigrationAnalyzer(temperature_c=temperature)
            return analyzer.analyze(def_path, net_currents, on_progress=progress)

        self._start_worker("em", self.em_run_btn, fn)

    def _run_thermal(self) -> None:
        def_path = self._require_file(self.th_def_path, "DEF")
        if def_path is None:
            return
        try:
            from openforge.physical.ir_drop import _parse_def as _parse_def_for_thermal
            from openforge.physical.thermal import ThermalAnalyzer, uniform_power_grid
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Cannot load thermal backend: {exc}")
            return

        ambient = self.th_ambient.value()
        rja = self.th_rja.value()
        total_p = self.th_total_power.value()
        grid_um = self.th_grid_um.value()
        iters = self.th_iterations.value()

        def fn(progress: Callable[[float, str], None]) -> Any:
            progress(0.02, "Parsing DEF for die extents...")
            info = _parse_def_for_thermal(def_path)
            if info.cells:
                p_per_cell = total_p / max(1, len(info.cells))
                cell_powers = {(c.x_um, c.y_um): p_per_cell for c in info.cells}
            else:
                cell_powers = uniform_power_grid(
                    info.width_um, info.height_um, total_p, grid_step_um=grid_um
                )
            analyzer = ThermalAnalyzer(ambient_c=ambient, package_thermal_r=rja)
            return analyzer.analyze(
                info.width_um,
                info.height_um,
                cell_powers,
                grid_resolution_um=grid_um,
                max_iterations=iters,
                on_progress=progress,
            )

        self._start_worker("thermal", self.th_run_btn, fn)

    def _run_emi(self) -> None:
        try:
            from openforge.physical.emi_emc import EmiEmcAnalyzer
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Cannot load EMI backend: {exc}")
            return

        freq_mhz = self.emi_freq.value()
        cur_a = self.emi_current.value() * 1e-3
        pkg_l = self.emi_pkg_l.value()
        length_m = self.emi_trace_len.value()

        def fn(progress: Callable[[float, str], None]) -> Any:
            progress(0.1, "Building harmonic spectrum...")
            analyzer = EmiEmcAnalyzer()
            res = analyzer.analyze(
                clock_frequencies_mhz=[freq_mhz],
                signal_currents={"clk": cur_a},
                trace_lengths={"clk": length_m},
                package_inductance_nh=pkg_l,
            )
            progress(1.0, "EMI analysis done")
            return res

        self._start_worker("emi", self.emi_run_btn, fn)

    def _run_esd(self) -> None:
        def_path = self._require_file(self.esd_def_path, "DEF")
        if def_path is None:
            return
        netlist_txt = self.esd_netlist.text().strip()
        netlist_path = Path(netlist_txt) if netlist_txt else def_path
        try:
            from openforge.physical.esd import EsdAnalyzer
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Cannot load ESD backend: {exc}")
            return

        kv_map = {
            "HBM 2.0 kV": 2.0,
            "HBM 4.0 kV": 4.0,
            "HBM 8.0 kV": 8.0,
            "CDM 500 V": 0.5,
        }
        target_kv = kv_map.get(self.esd_model.currentText(), 2.0)
        max_dist = self.esd_max_dist.value()
        clamp_keywords = [
            s.strip() for s in self.esd_clamp_keywords.text().split(",") if s.strip()
        ] or None

        def fn(progress: Callable[[float, str], None]) -> Any:
            progress(0.1, "Parsing IO pins...")
            analyzer = EsdAnalyzer(hbm_kv=target_kv, max_clamp_distance_um=max_dist)
            progress(0.5, "Tracing clamp paths...")
            res = analyzer.analyze(def_path, netlist_path, clamp_cells=clamp_keywords)
            progress(1.0, "ESD analysis done")
            return res

        self._start_worker("esd", self.esd_run_btn, fn)

    def _run_all(self) -> None:
        # Each dispatcher is non-blocking; fire them sequentially by tabs
        for runner in (
            self._run_ir_drop,
            self._run_em,
            self._run_thermal,
            self._run_emi,
            self._run_esd,
        ):
            try:
                runner()
            except Exception as exc:
                self._set_status(f"Step failed: {exc}")

    # ==================================================================
    # Result presenters
    # ==================================================================
    def _present_ir(self, result: Any) -> None:
        self.ir_canvas.show_grid(
            result.grid,
            (result.width_um, result.height_um),
            f"IR Drop Map - max {result.max_drop_mv:.1f} mV",
            cmap="inferno",
            units="Drop (mV)",
        )
        self.ir_table.setRowCount(0)
        for hp in result.hotspots[:200]:
            r = self.ir_table.rowCount()
            self.ir_table.insertRow(r)
            self.ir_table.setItem(r, 0, QTableWidgetItem(f"{hp.x:.2f}"))
            self.ir_table.setItem(r, 1, QTableWidgetItem(f"{hp.y:.2f}"))
            item = QTableWidgetItem(f"{hp.drop_mv:.2f}")
            item.setForeground(QBrush(QColor(MOCHA["red"])))
            self.ir_table.setItem(r, 2, item)
            self.ir_table.setItem(r, 3, QTableWidgetItem(f"{hp.voltage:.4f}"))

        vdd_mv = result.vdd * 1000.0
        threshold_mv = vdd_mv * (self.ir_threshold_pct.value() / 100.0)
        violators = sum(1 for row in result.grid for v in row if v > threshold_mv)
        total = result.num_rows * result.num_cols
        self.ir_summary.setPlainText(
            f"VDD={result.vdd:.3f}V  die={result.width_um:.0f}x{result.height_um:.0f} um  "
            f"grid={result.num_cols}x{result.num_rows}\n"
            f"Max drop: {result.max_drop_mv:.2f} mV   "
            f"Avg drop: {result.avg_drop_mv:.2f} mV\n"
            f"Min V: {result.vdd - result.max_drop_mv / 1000:.4f} V\n"
            f"Hotspots >= {threshold_mv:.1f} mV "
            f"(= {self.ir_threshold_pct.value():.1f}% of VDD): {violators}/{total}"
        )
        score = max(
            0.0,
            100.0 - (result.max_drop_mv / max(vdd_mv * 0.1, 1e-6)) * 40.0,
        )
        self.lbl_ir.setText(f"{score:.0f} / 100")

    def _present_em(self, result: Any) -> None:
        self.em_table.setRowCount(0)
        for v in sorted(
            result.violations,
            key=lambda x: x.current_density_a_per_um2,
            reverse=True,
        )[:500]:
            r = self.em_table.rowCount()
            self.em_table.insertRow(r)
            self.em_table.setItem(r, 0, QTableWidgetItem(v.wire.net))
            self.em_table.setItem(r, 1, QTableWidgetItem(v.wire.layer))
            self.em_table.setItem(r, 2, QTableWidgetItem(f"{v.wire.width:.3f}"))
            self.em_table.setItem(
                r, 3, QTableWidgetItem(f"{v.current_density_a_per_um2 * 1e3:.3f}")
            )
            self.em_table.setItem(r, 4, QTableWidgetItem(f"{v.limit_a_per_um2 * 1e3:.3f}"))
            sev_item = QTableWidgetItem(v.severity.upper())
            sev_item.setForeground(
                QBrush(QColor(MOCHA["red" if v.severity == "critical" else "yellow"]))
            )
            self.em_table.setItem(r, 5, sev_item)

        worst = result.worst_violation
        worst_str = (
            f"{worst.wire.net} @ {worst.wire.layer} "
            f"{worst.current_density_a_per_um2 * 1e3:.3f} mA/um"
            if worst
            else "(none)"
        )
        self.em_summary.setPlainText(
            f"Wires checked: {result.wires_checked}\n"
            f"Critical: {result.critical_count}   Warnings: {result.warning_count}\n"
            f"Avg density: {result.avg_density * 1e3:.3f} mA/um\n"
            f"Worst: {worst_str}\n"
            f"Runtime: {result.runtime_s:.2f}s"
        )
        score = max(0.0, 100.0 - result.critical_count * 5.0 - result.warning_count * 1.0)
        self.lbl_em.setText(f"{score:.0f} / 100")

    def _present_thermal(self, result: Any) -> None:
        self.th_canvas.show_grid(
            result.grid,
            (result.width_um, result.height_um),
            f"Temperature - max {result.max_temp_c:.1f} C",
            cmap="hot",
            units="Temperature (C)",
        )
        self.th_hotspots.clear()
        for h in result.hotspots[:100]:
            self.th_hotspots.addItem(
                QListWidgetItem(
                    f"{h.temperature_c:6.2f} C @ ({h.x:7.1f}, {h.y:7.1f}) um  "
                    f"P={h.power_w * 1e3:6.2f} mW"
                )
            )
        self.th_summary.setPlainText(
            f"Grid: {result.cols}x{result.rows}   "
            f"Iterations: {result.iterations_run} (converged={result.converged})\n"
            f"Max: {result.max_temp_c:.2f} C   "
            f"Avg: {result.avg_temp_c:.2f} C   "
            f"Min: {result.min_temp_c:.2f} C\n"
            f"Gradient: {result.gradient_c:.2f} C   "
            f"Hotspots (>85C): {len(result.hotspots)}"
        )
        score = max(0.0, 100.0 - max(0.0, result.max_temp_c - 85.0) * 3.0)
        self.lbl_thermal.setText(f"{score:.0f} / 100")

    def _present_emi(self, result: Any) -> None:
        freqs = [f for f, _ in result.spectrum]
        mags = [m for _, m in result.spectrum]
        self.emi_canvas.show_spectrum(
            freqs,
            mags,
            [(30, 40), (88, 40), (216, 43.5), (960, 46), (1000, 54)],
            f"Radiated emission - worst {result.worst_emission_db_uv_per_m:.1f} dBuV/m",
        )
        self.emi_summary.setPlainText(
            f"Sources: {len(result.sources)}   Points: {len(result.spectrum)}\n"
            f"Worst:   {result.worst_frequency_mhz:.1f} MHz  "
            f"{result.worst_emission_db_uv_per_m:.1f} dBuV/m\n"
            f"FCC Part 15 Class B: "
            f"{'PASS' if result.fcc_class_b_compliant else 'FAIL'}\n"
            f"CISPR 22 Class B:    {'PASS' if result.ce_compliant else 'FAIL'}\n"
            f"Near-field max: {result.near_field_max_v_per_m:.3f} V/m"
        )
        score = (
            100.0
            if result.is_compliant
            else max(0.0, 100.0 - max(0.0, result.worst_emission_db_uv_per_m - 40.0) * 2.0)
        )
        self.lbl_emi.setText(f"{score:.0f} / 100")

    def _present_esd(self, result: Any) -> None:
        self.esd_table.setRowCount(0)
        for p in sorted(result.paths, key=lambda x: x.total_resistance, reverse=True)[:500]:
            r = self.esd_table.rowCount()
            self.esd_table.insertRow(r)
            self.esd_table.setItem(r, 0, QTableWidgetItem(p.source_pin))
            self.esd_table.setItem(r, 1, QTableWidgetItem(p.dest_pin))
            self.esd_table.setItem(r, 2, QTableWidgetItem(f"{p.distance_um:.1f}"))
            self.esd_table.setItem(r, 3, QTableWidgetItem(f"{p.total_resistance:.2f}"))
            status = QTableWidgetItem("OK" if p.breakdown_ok else "FAIL")
            status.setForeground(QBrush(QColor(MOCHA["green" if p.breakdown_ok else "red"])))
            self.esd_table.setItem(r, 4, status)

        self.esd_summary.setPlainText(
            f"Pins checked: {result.pins_checked}   Paths: {len(result.paths)}\n"
            f"Violations: {len(result.violations)} "
            f"({result.critical_count} critical, {result.warning_count} warning)\n"
            f"HBM ({result.hbm_voltage_kv:.1f} kV): "
            f"{'PASS' if result.hbm_compliant else 'FAIL'}\n"
            f"CDM ({result.cdm_voltage_v:.0f} V):   "
            f"{'PASS' if result.cdm_compliant else 'FAIL'}"
        )
        score = (
            100.0
            if result.is_clean
            else max(0.0, 100.0 - result.critical_count * 10.0 - result.warning_count * 2.0)
        )
        self.lbl_esd.setText(f"{score:.0f} / 100")

    # ==================================================================
    # Exports
    # ==================================================================
    def _export_csv(self, kind: str) -> None:
        if kind not in self._last_results:
            QMessageBox.information(self, "No Data", f"Run {kind} first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", f"{kind}.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                self._write_csv(f, kind, self._last_results[kind])
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return
        self._set_status(f"Wrote {path}")

    def _write_csv(self, f, kind: str, result: Any) -> None:
        if kind == "ir_drop":
            f.write("# IR drop map (mV)\n")
            f.write(f"# vdd={result.vdd} grid_um={result.grid_size_um}\n")
            f.write(f"# max_drop_mv={result.max_drop_mv:.3f}\n")
            for row in result.grid:
                f.write(",".join(f"{v:.3f}" for v in row) + "\n")
        elif kind == "em":
            f.write("net,layer,width_um,density_ma_per_um,limit_ma_per_um,severity\n")
            for v in result.violations:
                f.write(
                    f"{v.wire.net},{v.wire.layer},{v.wire.width:.3f},"
                    f"{v.current_density_a_per_um2 * 1e3:.4f},"
                    f"{v.limit_a_per_um2 * 1e3:.4f},{v.severity}\n"
                )
        elif kind == "thermal":
            f.write("ix,iy,temperature_c\n")
            for iy, row in enumerate(result.grid):
                for ix, t in enumerate(row):
                    f.write(f"{ix},{iy},{t:.3f}\n")
        elif kind == "emi":
            f.write("frequency_mhz,magnitude_dbuv_per_m\n")
            for fr, mg in result.spectrum:
                f.write(f"{fr:.3f},{mg:.3f}\n")
        elif kind == "esd":
            f.write("source_pin,dest_pin,distance_um,resistance_ohm,ok\n")
            for p in result.paths:
                f.write(
                    f"{p.source_pin},{p.dest_pin},{p.distance_um:.2f},"
                    f"{p.total_resistance:.3f},{p.breakdown_ok}\n"
                )

    def _export_report(self) -> None:
        if not self._last_results:
            QMessageBox.information(self, "No Data", "Run an analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Report", "reliability_report.txt", "Text (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("OpenForge Reliability Report\n")
                f.write("============================\n\n")
                f.write(f"Overall score: {self.radar.overall():.1f} / 100\n\n")
                for key in ("ir_drop", "em", "thermal", "emi", "esd"):
                    if key in self._last_results:
                        f.write(f"--- {key.upper()} ---\n")
                        f.write(str(self._last_results[key]))
                        f.write("\n\n")
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return
        self._set_status(f"Report written to {path}")

    # ==================================================================
    # Misc
    # ==================================================================
    def _update_radar(self) -> None:
        scores: dict[str, float] = {}
        for _key, lbl, name in (
            ("ir_drop", self.lbl_ir, "IR Drop"),
            ("em", self.lbl_em, "EM"),
            ("thermal", self.lbl_thermal, "Thermal"),
            ("emi", self.lbl_emi, "EMI"),
            ("esd", self.lbl_esd, "ESD"),
        ):
            txt = lbl.text()
            if "/" in txt:
                with contextlib.suppress(ValueError):
                    scores[name] = float(txt.split("/")[0].strip())
        self.radar.set_scores(scores)
        if scores:
            self.lbl_overall.setText(f"{self.radar.overall():.0f}")

    def _clear_results(self) -> None:
        self._last_results.clear()
        for lbl in (
            self.lbl_ir,
            self.lbl_em,
            self.lbl_thermal,
            self.lbl_emi,
            self.lbl_esd,
        ):
            lbl.setText("--")
        self.lbl_overall.setText("--")
        self.radar.set_scores({k: 0 for k in ("IR Drop", "EM", "Thermal", "EMI", "ESD")})
        self.ir_summary.clear()
        self.em_summary.clear()
        self.th_summary.clear()
        self.emi_summary.clear()
        self.esd_summary.clear()
        self.em_table.setRowCount(0)
        self.esd_table.setRowCount(0)
        self.ir_table.setRowCount(0)
        self.th_hotspots.clear()
        self.ir_canvas.show_grid([], (1.0, 1.0), "", units="Drop (mV)")
        self.th_canvas.show_grid([], (1.0, 1.0), "", units="Temperature (C)")
        self.emi_canvas.show_spectrum([], [], [], "")
        self.progress.setValue(0)
        self._set_status("Cleared")


__all__ = ["ReliabilityPanel"]
