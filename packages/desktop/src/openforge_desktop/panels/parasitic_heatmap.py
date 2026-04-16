"""Parasitic (SPEF) heatmap and net browser panel."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
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
except Exception:  # pragma: no cover - matplotlib optional at import time
    _HAVE_MPL = False
    FigureCanvas = object  # type: ignore[assignment,misc]
    Figure = object  # type: ignore[assignment,misc]

try:
    from openforge.format.spef_parser import SpefFile, SpefNet
except Exception:  # pragma: no cover
    SpefFile = None  # type: ignore[assignment,misc]
    SpefNet = None  # type: ignore[assignment,misc]

try:
    from openforge.format.def_parser import parse_def, DefDesign
except Exception:  # pragma: no cover
    parse_def = None  # type: ignore[assignment]
    DefDesign = None  # type: ignore[assignment]


class ParasiticHeatmapPanel(QWidget):
    """Visualise SPEF parasitics: heatmap, histograms and net browser."""

    netSelected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("parasitic_heatmap_panel")
        self._spef: Optional[SpefFile] = None
        self._def: Optional[DefDesign] = None
        self._build_ui()

    # ------------------------------------------------------------------ ui

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # -- toolbar ------------------------------------------------------
        bar = QHBoxLayout()
        self._load_btn = QPushButton("Load SPEF…")
        self._load_btn.clicked.connect(self._on_load_spef)
        bar.addWidget(self._load_btn)

        self._load_def_btn = QPushButton("Load DEF…")
        self._load_def_btn.clicked.connect(self._on_load_def)
        bar.addWidget(self._load_def_btn)

        self._auto_btn = QPushButton("Auto-load latest")
        self._auto_btn.clicked.connect(self._on_auto_load)
        bar.addWidget(self._auto_btn)

        bar.addStretch(1)

        self._metric_box = QComboBox()
        self._metric_box.addItems(["Total Cap (pF)", "Total Res (Ω)"])
        self._metric_box.currentIndexChanged.connect(self._refresh_heatmap)
        bar.addWidget(QLabel("Metric:"))
        bar.addWidget(self._metric_box)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.clicked.connect(self._on_export_csv)
        bar.addWidget(self._export_btn)

        root.addLayout(bar)

        self._summary = QLabel("No SPEF loaded.")
        self._summary.setStyleSheet("color: #999; padding: 2px 4px;")
        root.addWidget(self._summary)

        # -- splitter: tabs (left) | net browser (right) ------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # tabs
        self._tabs = QTabWidget()
        if _HAVE_MPL:
            self._fig_heat = Figure(figsize=(5, 4), tight_layout=True)
            self._canvas_heat = FigureCanvas(self._fig_heat)
            self._tabs.addTab(self._canvas_heat, "Heatmap")

            self._fig_hist = Figure(figsize=(5, 4), tight_layout=True)
            self._canvas_hist = FigureCanvas(self._fig_hist)
            self._tabs.addTab(self._canvas_hist, "Histograms")
        else:
            placeholder = QLabel("matplotlib is not available")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tabs.addTab(placeholder, "Heatmap")
        splitter.addWidget(self._tabs)

        # right column: net browser + aggressors
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        browser_box = QGroupBox("Net Browser")
        bv = QVBoxLayout(browser_box)

        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter:"))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("substring…")
        self._filter.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._filter)
        bv.addLayout(filter_bar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Net", "Cap (pF)", "Res (Ω)", "Max C (pF)", "Aggr."]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        bv.addWidget(self._table)
        rv.addWidget(browser_box)

        agg_box = QGroupBox("Aggressors for selected net")
        av = QVBoxLayout(agg_box)
        self._agg_table = QTableWidget(0, 2)
        self._agg_table.setHorizontalHeaderLabels(["Aggressor Net", "Cc (pF)"])
        self._agg_table.horizontalHeader().setStretchLastSection(True)
        self._agg_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        av.addWidget(self._agg_table)
        rv.addWidget(agg_box)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, 1)

    # --------------------------------------------------------------- actions

    def _on_load_spef(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load SPEF", "", "SPEF (*.spef *.dspef *.rspef);;All files (*)"
        )
        if path:
            self.load_spef(Path(path))

    def _on_load_def(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load DEF (optional)", "", "DEF (*.def);;All files (*)"
        )
        if path:
            self.load_def(Path(path))

    def _on_auto_load(self) -> None:
        cwd = Path.cwd()
        candidates = sorted(cwd.rglob("*.spef"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            QMessageBox.information(self, "Auto-load", "No .spef files found under cwd.")
            return
        self.load_spef(candidates[0])

    def _on_export_csv(self) -> None:
        if not self._spef:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export nets CSV", "nets.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["net", "cap_pf", "res_ohm", "max_cap_pf", "max_res_ohm", "aggressors"])
            for n in self._spef.nets:
                w.writerow([
                    n.name,
                    f"{n.total_cap_pf:.6g}",
                    f"{n.total_res_ohm:.6g}",
                    f"{n.max_cap_pf:.6g}",
                    f"{n.max_res_ohm:.6g}",
                    n.aggressor_count,
                ])

    # -------------------------------------------------------------- loaders

    def load_spef(self, path: Path) -> None:
        if SpefFile is None:
            QMessageBox.warning(self, "SPEF", "SPEF parser not available.")
            return
        try:
            self._spef = SpefFile.parse(path)
        except Exception as exc:
            QMessageBox.critical(self, "SPEF parse error", str(exc))
            return
        self._populate_table()
        self._refresh_heatmap()
        self._refresh_histograms()
        n = len(self._spef.nets)
        self._summary.setText(
            f"{path.name}: {n} nets · "
            f"ΣC = {self._spef.total_cap():.3f} pF · "
            f"ΣR = {self._spef.total_res():.3f} Ω"
        )

    def load_def(self, path: Path) -> None:
        if parse_def is None:
            return
        try:
            self._def = parse_def(path)
        except Exception as exc:
            QMessageBox.critical(self, "DEF parse error", str(exc))
            return
        self._refresh_heatmap()

    # -------------------------------------------------------------- helpers

    def _populate_table(self) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        if not self._spef:
            return
        nets = self._spef.nets
        if not nets:
            return
        max_cap = max((n.total_cap_pf for n in nets), default=0.0)

        self._table.setRowCount(len(nets))
        for row, net in enumerate(nets):
            is_worst = net.total_cap_pf > 0.8 * max_cap and max_cap > 0
            name = QTableWidgetItem(net.name)
            cap = _num_item(net.total_cap_pf)
            res = _num_item(net.total_res_ohm)
            mc = _num_item(net.max_cap_pf)
            agg = _num_item(net.aggressor_count)
            if is_worst:
                red = QColor("#c0392b")
                for it in (name, cap, res, mc, agg):
                    it.setForeground(red)
            self._table.setItem(row, 0, name)
            self._table.setItem(row, 1, cap)
            self._table.setItem(row, 2, res)
            self._table.setItem(row, 3, mc)
            self._table.setItem(row, 4, agg)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text: str) -> None:
        text = (text or "").lower()
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            hide = bool(text) and (item is None or text not in item.text().lower())
            self._table.setRowHidden(r, hide)

    def _on_row_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows or not self._spef:
            return
        row = rows[0].row()
        item = self._table.item(row, 0)
        if item is None:
            return
        name = item.text()
        net = self._spef.find_net(name)
        if net is None:
            return
        self.netSelected.emit(name)
        self._populate_aggressors(net)

    def _populate_aggressors(self, net: "SpefNet") -> None:
        aggs = sorted(net.aggressors().items(), key=lambda kv: kv[1], reverse=True)
        self._agg_table.setRowCount(len(aggs))
        for r, (nm, cc) in enumerate(aggs):
            self._agg_table.setItem(r, 0, QTableWidgetItem(nm))
            self._agg_table.setItem(r, 1, _num_item(cc))

    # --------------------------------------------------------------- plots

    def _refresh_heatmap(self) -> None:
        if not _HAVE_MPL or not self._spef:
            return
        fig = self._fig_heat
        fig.clear()
        ax = fig.add_subplot(111)
        use_res = self._metric_box.currentIndex() == 1
        values = [n.total_res_ohm if use_res else n.total_cap_pf for n in self._spef.nets]

        if self._def is not None and self._def.nets:
            # real per-bin heatmap over die area using DEF coordinates
            grid, extent = self._build_die_grid(values, use_res)
            im = ax.pcolormesh(
                np.linspace(extent[0], extent[1], grid.shape[1] + 1),
                np.linspace(extent[2], extent[3], grid.shape[0] + 1),
                grid,
                cmap="inferno",
                shading="flat",
            )
            fig.colorbar(im, ax=ax, label="Σ Ω" if use_res else "Σ pF")
            ax.set_xlabel("x (µm)")
            ax.set_ylabel("y (µm)")
            ax.set_title("Parasitic density over die")
        else:
            # fallback: sorted bar of worst offenders
            top = sorted(
                self._spef.nets,
                key=lambda n: (n.total_res_ohm if use_res else n.total_cap_pf),
                reverse=True,
            )[:25]
            ax.barh(
                [n.name[-28:] for n in top][::-1],
                [(n.total_res_ohm if use_res else n.total_cap_pf) for n in top][::-1],
                color="#e67e22",
            )
            ax.set_xlabel("Ω" if use_res else "pF")
            ax.set_title("Top 25 worst nets (load DEF for spatial heatmap)")

        self._canvas_heat.draw_idle()

    def _build_die_grid(
        self, values: list[float], use_res: bool
    ) -> tuple["np.ndarray", tuple[float, float, float, float]]:
        assert self._def is not None
        w = max(self._def.width_um, 1.0)
        h = max(self._def.height_um, 1.0)
        bins_x = 32
        bins_y = max(1, int(bins_x * h / w))
        grid = np.zeros((bins_y, bins_x), dtype=float)
        for i, net in enumerate(self._spef.nets or []):
            dn = self._def.nets.get(net.name)
            if dn is None or not dn.routes:
                continue
            # crude: take first point of first segment
            seg0 = dn.routes[0]
            if not seg0.points:
                continue
            x_db, y_db, _ = seg0.points[0]
            x_um = self._def.to_um(x_db)
            y_um = self._def.to_um(y_db)
            ix = min(int(x_um / w * bins_x), bins_x - 1)
            iy = min(int(y_um / h * bins_y), bins_y - 1)
            if ix < 0 or iy < 0:
                continue
            grid[iy, ix] += values[i]
        return grid, (0.0, w, 0.0, h)

    def _refresh_histograms(self) -> None:
        if not _HAVE_MPL or not self._spef:
            return
        fig = self._fig_hist
        fig.clear()
        ax1 = fig.add_subplot(211)
        ax2 = fig.add_subplot(212)
        cap_edges, cap_counts = self._spef.histogram_cap(bins=30)
        res_edges, res_counts = self._spef.histogram_res(bins=30)
        if cap_counts:
            ax1.bar(cap_edges[:-1], cap_counts,
                    width=[cap_edges[i + 1] - cap_edges[i] for i in range(len(cap_counts))],
                    align="edge", color="#3498db")
            ax1.set_title("Capacitance distribution")
            ax1.set_xlabel("pF")
            ax1.set_ylabel("nets")
        if res_counts:
            ax2.bar(res_edges[:-1], res_counts,
                    width=[res_edges[i + 1] - res_edges[i] for i in range(len(res_counts))],
                    align="edge", color="#2ecc71")
            ax2.set_title("Resistance distribution")
            ax2.set_xlabel("Ω")
            ax2.set_ylabel("nets")
        self._canvas_hist.draw_idle()


def _num_item(value: float | int) -> QTableWidgetItem:
    it = QTableWidgetItem()
    it.setData(Qt.ItemDataRole.DisplayRole, float(value))
    return it


__all__ = ["ParasiticHeatmapPanel"]
