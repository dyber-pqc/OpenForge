"""Unified Power Sign-off dashboard panel.

Runs :class:`openforge.physical.power_signoff.PowerSignoffOrchestrator`
in a background QThread, and shows the aggregated results as a
Vivado/PrimePower-style dashboard with per-corner table, per-mode
breakdown, hot-cell list, power density heatmap and time-domain trace.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    import numpy as np
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure

    _HAVE_MPL = True
except Exception:  # pragma: no cover
    _HAVE_MPL = False
    FigureCanvas = object  # type: ignore[assignment,misc]
    Figure = object  # type: ignore[assignment,misc]

try:
    from openforge.physical.power_signoff import (
        PowerSignoffConfig,
        PowerSignoffOrchestrator,
        PowerSignoffResult,
    )

    _HAVE_ENGINE = True
except Exception:  # pragma: no cover
    PowerSignoffConfig = None  # type: ignore[assignment,misc]
    PowerSignoffOrchestrator = None  # type: ignore[assignment,misc]
    PowerSignoffResult = None  # type: ignore[assignment,misc]
    _HAVE_ENGINE = False


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class _PowerSignoffWorker(QThread):
    progressed = Signal(str, float)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        cfg: PowerSignoffConfig,
        def_path: Path,
        lef_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._def = def_path
        self._lef = lef_path

    def run(self) -> None:  # type: ignore[override]
        try:
            orch = PowerSignoffOrchestrator(self._cfg, self._def, self._lef)
            result = orch.run(progress=lambda m, f: self.progressed.emit(m, f))
            self.finished_ok.emit(result)
        except Exception as exc:  # pragma: no cover - surfaced to UI
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Status tile
# ---------------------------------------------------------------------------


class _StatusTile(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #1a1a1a; border: 1px solid #333; border-radius: 6px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self._status = QLabel("IDLE")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("font-size: 28px; font-weight: bold; color: #888;")
        self._score = QLabel("--")
        self._score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._score.setStyleSheet("font-size: 48px; font-weight: bold; color: #7abaff;")
        self._sub = QLabel("no run yet")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setStyleSheet("color:#999; font-size:11px;")
        lay.addWidget(self._status)
        lay.addWidget(self._score)
        lay.addWidget(self._sub)

    def set_result(self, status: str, score: float, subtitle: str) -> None:
        color = {"PASS": "#2e8b57", "WARN": "#d48806", "FAIL": "#cf1322"}.get(status, "#888")
        self._status.setText(status)
        self._status.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
        self._score.setText(f"{score:.1f}")
        self._score.setStyleSheet(f"font-size: 48px; font-weight: bold; color: {color};")
        self._sub.setText(subtitle)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class PowerSignoffPanel(QWidget):
    """Unified power sign-off dashboard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _PowerSignoffWorker | None = None
        self._result: PowerSignoffResult | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Top: config form + status tile
        top = QHBoxLayout()
        cfg_box = QGroupBox("Sign-off Configuration")
        form = QFormLayout(cfg_box)

        self._def_edit = QLineEdit()
        self._lef_edit = QLineEdit()
        self._lib_edit = QLineEdit()
        self._corners_edit = QLineEdit("TT,SS,FF")
        self._modes_edit = QLineEdit("functional")
        self._vcd_edit = QLineEdit()
        self._duration = QDoubleSpinBox()
        self._duration.setRange(0.0, 1e9)
        self._duration.setDecimals(2)
        self._duration.setSuffix(" ns")
        self._duration.setValue(1000.0)
        self._vdd = QDoubleSpinBox()
        self._vdd.setRange(0.1, 5.0)
        self._vdd.setDecimals(3)
        self._vdd.setSingleStep(0.05)
        self._vdd.setValue(0.9)

        def _browse(edit: QLineEdit, title: str, flt: str) -> QPushButton:
            btn = QPushButton("Browse")
            btn.clicked.connect(lambda: self._pick(edit, title, flt))
            row = QHBoxLayout()
            w = QWidget()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(edit, 1)
            row.addWidget(btn)
            w.setLayout(row)
            form.addRow(title, w)
            return btn

        _browse(self._def_edit, "DEF", "DEF (*.def)")
        _browse(self._lef_edit, "LEF", "LEF (*.lef)")
        _browse(self._lib_edit, "Liberty", "Liberty (*.lib)")
        form.addRow("Corners (comma)", self._corners_edit)
        form.addRow("Modes (comma)", self._modes_edit)
        _browse(self._vcd_edit, "VCD (first mode)", "VCD (*.vcd *.fst)")
        form.addRow("Duration", self._duration)
        form.addRow("VDD (V)", self._vdd)

        self._run_btn = QPushButton("Run All")
        self._run_btn.clicked.connect(self._run)
        self._export_btn = QPushButton("Export HTML Report")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_html)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        form.addRow(self._progress)
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color:#888; font-size:11px;")
        form.addRow(self._progress_label)

        self._tile = _StatusTile(self)
        top.addWidget(cfg_box, 3)
        top.addWidget(self._tile, 1)
        root.addLayout(top)

        # Tabs
        self._tabs = QTabWidget()
        self._build_corner_tab()
        self._build_mode_tab()
        self._build_cells_tab()
        self._build_heatmap_tab()
        self._build_time_tab()
        root.addWidget(self._tabs, 1)

        if not _HAVE_ENGINE:
            warn = QLabel(
                "Power sign-off engine unavailable - install openforge.physical.power_signoff"
            )
            warn.setStyleSheet("color:#cf1322; padding:8px;")
            root.addWidget(warn)
            self._run_btn.setEnabled(False)

    def _pick(self, edit: QLineEdit, title: str, flt: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", flt)
        if path:
            edit.setText(path)

    # ------------------------------------------------------------------
    def _build_corner_tab(self) -> None:
        self._corner_table = QTableWidget(0, 8)
        self._corner_table.setHorizontalHeaderLabels(
            [
                "Corner",
                "Leakage mW",
                "Dynamic mW",
                "Total mW",
                "IR mV",
                "EM viol",
                "Temp C",
                "Status",
            ]
        )
        self._corner_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._corner_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._corner_table.horizontalHeader().setStretchLastSection(True)
        self._tabs.addTab(self._corner_table, "Corners")

    def _build_mode_tab(self) -> None:
        self._mode_table = QTableWidget(0, 7)
        self._mode_table.setHorizontalHeaderLabels(
            ["Mode", "Dynamic mW", "Leakage mW", "Total mW", "Peak mW", "Peak ns", "Duration ns"]
        )
        self._mode_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._mode_table.horizontalHeader().setStretchLastSection(True)
        self._tabs.addTab(self._mode_table, "Modes")

    def _build_cells_tab(self) -> None:
        self._cells_table = QTableWidget(0, 6)
        self._cells_table.setHorizontalHeaderLabels(
            ["Instance", "Cell", "Switch uW", "Internal uW", "Leakage uW", "Total uW"]
        )
        self._cells_table.setSortingEnabled(True)
        self._cells_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._cells_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tabs.addTab(self._cells_table, "Hot Cells")

    def _build_heatmap_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        if _HAVE_MPL:
            self._heat_fig = Figure(figsize=(5, 4), facecolor="#111")
            self._heat_canvas = FigureCanvas(self._heat_fig)
            self._heat_ax = self._heat_fig.add_subplot(111)
            self._heat_ax.set_facecolor("#111")
            lay.addWidget(self._heat_canvas)
        else:
            lay.addWidget(QLabel("matplotlib unavailable"))
            self._heat_fig = None
            self._heat_canvas = None
            self._heat_ax = None
        self._tabs.addTab(w, "Power Density")

    def _build_time_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        if _HAVE_MPL:
            self._time_fig = Figure(figsize=(5, 3), facecolor="#111")
            self._time_canvas = FigureCanvas(self._time_fig)
            self._time_ax = self._time_fig.add_subplot(111)
            self._time_ax.set_facecolor("#111")
            lay.addWidget(self._time_canvas)
        else:
            lay.addWidget(QLabel("matplotlib unavailable"))
            self._time_fig = None
            self._time_canvas = None
            self._time_ax = None
        self._tabs.addTab(w, "Time Domain")

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if not _HAVE_ENGINE:
            return
        def_path = Path(self._def_edit.text().strip())
        lef_path = Path(self._lef_edit.text().strip())
        if not def_path.exists() or not lef_path.exists():
            QMessageBox.warning(self, "Missing files", "DEF and LEF are required.")
            return

        corners = [c.strip() for c in self._corners_edit.text().split(",") if c.strip()]
        modes = [m.strip() for m in self._modes_edit.text().split(",") if m.strip()]
        vcd_files: dict[str, str] = {}
        vcd_first = self._vcd_edit.text().strip()
        if vcd_first and modes:
            vcd_files[modes[0]] = vcd_first

        cfg = PowerSignoffConfig(
            corners=corners or ["TT"],
            modes=modes or ["functional"],
            vcd_files=vcd_files,
            duration_ns=self._duration.value(),
            lib_path=self._lib_edit.text().strip() or None,
            vdd=self._vdd.value(),
        )
        self._run_btn.setEnabled(False)
        self._progress.setValue(0)
        self._progress_label.setText("starting")

        self._worker = _PowerSignoffWorker(cfg, def_path, lef_path, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(lambda: self._run_btn.setEnabled(True))
        self._worker.start()

    def _on_progress(self, msg: str, frac: float) -> None:
        self._progress.setValue(int(frac * 100))
        self._progress_label.setText(msg)

    def _on_fail(self, err: str) -> None:
        self._progress_label.setText(f"failed: {err}")
        QMessageBox.critical(self, "Sign-off failed", err)

    def _on_done(self, result: object) -> None:
        self._result = result  # type: ignore[assignment]
        self._export_btn.setEnabled(True)
        self._progress.setValue(100)
        self._progress_label.setText("done")

        self._tile.set_result(
            result.overall_status,  # type: ignore[attr-defined]
            result.score,  # type: ignore[attr-defined]
            f"IR {result.ir_drop_max_mv:.1f} mV | EM {result.em_violations} | "  # type: ignore[attr-defined]
            f"T {result.thermal_max_c:.0f}C",  # type: ignore[attr-defined]
        )

        # Corner table
        self._corner_table.setRowCount(0)
        for c in result.corner_summary:  # type: ignore[attr-defined]
            r = self._corner_table.rowCount()
            self._corner_table.insertRow(r)
            cells = [
                c.corner,
                f"{c.leakage_mw:.3f}",
                f"{c.dynamic_mw:.3f}",
                f"{c.total_mw:.3f}",
                f"{c.ir_drop_mv:.2f}",
                str(c.em_violations),
                f"{c.thermal_max_c:.1f}",
                c.status,
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if col == 7:
                    color = {
                        "PASS": QColor("#2e8b57"),
                        "WARN": QColor("#d48806"),
                        "FAIL": QColor("#cf1322"),
                    }.get(val, QColor("#888"))
                    item.setForeground(color)
                self._corner_table.setItem(r, col, item)

        # Mode table
        self._mode_table.setRowCount(0)
        for m in result.mode_summary:  # type: ignore[attr-defined]
            r = self._mode_table.rowCount()
            self._mode_table.insertRow(r)
            cells = [
                m.mode,
                f"{m.dynamic_mw:.3f}",
                f"{m.leakage_mw:.3f}",
                f"{m.total_mw:.3f}",
                f"{m.peak_mw:.3f}",
                f"{m.peak_time_ns:.2f}",
                f"{m.duration_ns:.1f}",
            ]
            for col, val in enumerate(cells):
                self._mode_table.setItem(r, col, QTableWidgetItem(val))

        # Cells table
        self._cells_table.setSortingEnabled(False)
        self._cells_table.setRowCount(0)
        for c in result.top_cells[:50]:  # type: ignore[attr-defined]
            r = self._cells_table.rowCount()
            self._cells_table.insertRow(r)
            vals = [
                c.get("instance", ""),
                c.get("cell_type", ""),
                f"{c.get('switching_uw', 0.0):.3f}",
                f"{c.get('internal_uw', 0.0):.3f}",
                f"{c.get('leakage_uw', 0.0):.3f}",
                f"{c.get('total_uw', 0.0):.3f}",
            ]
            for col, v in enumerate(vals):
                self._cells_table.setItem(r, col, QTableWidgetItem(v))
        self._cells_table.setSortingEnabled(True)

        # Heatmap
        if _HAVE_MPL and self._heat_ax is not None:
            self._heat_ax.clear()
            density = result.density_grid  # type: ignore[attr-defined]
            grid = density.get("grid") if isinstance(density, dict) else None
            if grid:
                arr = np.array(grid)
                ext = density.get("extent", (0, arr.shape[1], 0, arr.shape[0]))
                self._heat_ax.pcolormesh(
                    np.linspace(ext[0], ext[1], arr.shape[1] + 1),
                    np.linspace(ext[2], ext[3], arr.shape[0] + 1),
                    arr,
                    cmap="inferno",
                    shading="flat",
                )
                self._heat_ax.set_title("Power density (uW/um^2)", color="#eee")
                self._heat_ax.set_xlabel("x (um)", color="#ccc")
                self._heat_ax.set_ylabel("y (um)", color="#ccc")
                self._heat_ax.tick_params(colors="#ccc")
                for sp in self._heat_ax.spines.values():
                    sp.set_color("#444")
            else:
                self._heat_ax.text(
                    0.5,
                    0.5,
                    "no density data",
                    ha="center",
                    va="center",
                    color="#888",
                    transform=self._heat_ax.transAxes,
                )
            if self._heat_canvas is not None:
                self._heat_canvas.draw_idle()

        # Time-domain
        if _HAVE_MPL and self._time_ax is not None:
            self._time_ax.clear()
            inst = result.instantaneous  # type: ignore[attr-defined]
            if inst:
                ts = [p[0] for p in inst]
                ps = [p[1] for p in inst]
                self._time_ax.plot(ts, ps, color="#7abaff", lw=1.2)
                self._time_ax.fill_between(ts, ps, alpha=0.25, color="#7abaff")
                self._time_ax.set_title("Instantaneous power", color="#eee")
                self._time_ax.set_xlabel("time (ns)", color="#ccc")
                self._time_ax.set_ylabel("mW", color="#ccc")
                self._time_ax.tick_params(colors="#ccc")
                for sp in self._time_ax.spines.values():
                    sp.set_color("#444")
            else:
                self._time_ax.text(
                    0.5,
                    0.5,
                    "no VCD provided",
                    ha="center",
                    va="center",
                    color="#888",
                    transform=self._time_ax.transAxes,
                )
            if self._time_canvas is not None:
                self._time_canvas.draw_idle()

    # ------------------------------------------------------------------
    def _export_html(self) -> None:
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export power sign-off report", "power_signoff.html", "HTML (*.html)"
        )
        if not path:
            return
        try:
            orch = PowerSignoffOrchestrator(
                self._result.config,  # type: ignore[attr-defined]
                Path(self._def_edit.text().strip()),
                Path(self._lef_edit.text().strip()),
            )
            orch.to_html_report(self._result, Path(path))
            QMessageBox.information(self, "Exported", f"Report written to\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))


__all__ = ["PowerSignoffPanel"]
