"""DRC violation browser panel."""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    _HAVE_MPL = True
except Exception:  # pragma: no cover
    _HAVE_MPL = False
    FigureCanvas = object  # type: ignore[assignment,misc]
    Figure = object  # type: ignore[assignment,misc]

try:
    from openforge.physical.drc_parser import DrcReport, DrcViolation
except Exception:  # pragma: no cover
    DrcReport = None  # type: ignore[assignment,misc]
    DrcViolation = None  # type: ignore[assignment,misc]


# Rule ID -> fix suggestion
FIX_HINTS: dict[str, str] = {
    "spacing": "Increase spacing or move one shape; check min-spacing rule.",
    "min width": "Widen shape to meet min-width; check WIDTH rule.",
    "min area": "Fill shape to meet min-area.",
    "short": "Break short — re-route one of the overlapping nets.",
    "open": "Unrouted pin — invoke detailed router again.",
    "antenna": "Insert diode or jog to upper layer.",
    "density": "Add metal/OD fill to satisfy density.",
    "enclosure": "Enlarge enclosing layer around via.",
    "overlap": "Remove overlap or legalize placement.",
    "off grid": "Snap shape to manufacturing grid.",
}


def _fix_for_rule(rule: str) -> str:
    key = rule.lower()
    for token, hint in FIX_HINTS.items():
        if token in key:
            return hint
    return "Review rule deck for details."


class DrcBrowserPanel(QWidget):
    """Tree + table + density map for DRC reports."""

    violationActivated = Signal(float, float, str)  # (x, y, layer)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drc_browser_panel")
        self._report: DrcReport | None = None
        self._filtered: list[DrcViolation] = []
        self._build_ui()

    # ------------------------------------------------------------------ ui

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        bar = QHBoxLayout()
        self._load_btn = QPushButton("Load DRC Report…")
        self._load_btn.clicked.connect(self._on_load)
        bar.addWidget(self._load_btn)

        bar.addWidget(QLabel("Rule filter:"))
        self._rule_filter = QLineEdit()
        self._rule_filter.setPlaceholderText("substring…")
        self._rule_filter.textChanged.connect(self._refresh)
        bar.addWidget(self._rule_filter)

        bar.addWidget(QLabel("Layer:"))
        self._layer_filter = QComboBox()
        self._layer_filter.addItem("<all>")
        self._layer_filter.currentIndexChanged.connect(self._refresh)
        bar.addWidget(self._layer_filter)

        bar.addWidget(QLabel("Severity:"))
        self._sev_filter = QComboBox()
        self._sev_filter.addItems(["<all>", "error", "warning", "info"])
        self._sev_filter.currentIndexChanged.connect(self._refresh)
        bar.addWidget(self._sev_filter)

        bar.addStretch(1)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._export_btn)

        self._waive_btn = QPushButton("Add Waiver")
        self._waive_btn.clicked.connect(self._on_waive)
        bar.addWidget(self._waive_btn)

        root.addLayout(bar)

        self._summary = QLabel("No report loaded.")
        self._summary.setStyleSheet("color: #999; padding: 2px 4px;")
        root.addWidget(self._summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: rule tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Rule / Instance", "Count"])
        self._tree.itemSelectionChanged.connect(self._on_tree_select)
        splitter.addWidget(self._tree)

        # Center: table
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Rule", "Layer", "Severity", "X (µm)", "Y (µm)", "Fix", "Message"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._table.itemDoubleClicked.connect(self._on_double)
        splitter.addWidget(self._table)

        # Right: density mini map
        right_box = QGroupBox("Severity heatmap")
        rv = QVBoxLayout(right_box)
        if _HAVE_MPL:
            self._fig = Figure(figsize=(3, 4), tight_layout=True)
            self._canvas = FigureCanvas(self._fig)
            rv.addWidget(self._canvas)
        else:
            rv.addWidget(QLabel("matplotlib unavailable"))
        splitter.addWidget(right_box)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)

        root.addWidget(splitter, 1)

    # ------------------------------------------------------------------ actions

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DRC report", "",
            "DRC reports (*.rpt *.json *.xml *.lyrdb *.rve *.drc);;All files (*)",
        )
        if path:
            self.load_report(Path(path))

    def load_report(self, path: Path) -> None:
        if DrcReport is None:
            QMessageBox.warning(self, "DRC", "DRC parser not available.")
            return
        try:
            self._report = DrcReport.auto_load(path)
        except Exception as exc:
            QMessageBox.critical(self, "DRC parse error", str(exc))
            return
        self._populate_layers()
        self._refresh()
        n = len(self._report.violations)
        self._summary.setText(
            f"{path.name}: {n} violations [{self._report.tool}]"
        )

    def _populate_layers(self) -> None:
        self._layer_filter.blockSignals(True)
        self._layer_filter.clear()
        self._layer_filter.addItem("<all>")
        if self._report:
            layers = sorted({v.layer for v in self._report.violations if v.layer})
            for l in layers:
                self._layer_filter.addItem(l)
        self._layer_filter.blockSignals(False)

    # ------------------------------------------------------------------ filter

    def _passes(self, v: DrcViolation) -> bool:
        rf = self._rule_filter.text().strip().lower()
        if rf and rf not in v.rule.lower():
            return False
        lf = self._layer_filter.currentText()
        if lf and lf != "<all>" and v.layer != lf:
            return False
        sf = self._sev_filter.currentText()
        return not (sf and sf != "<all>" and v.severity != sf)

    def _refresh(self) -> None:
        if not self._report:
            return
        self._filtered = [v for v in self._report.violations if self._passes(v)]
        self._populate_tree()
        self._populate_table()
        self._refresh_heatmap()

    def _populate_tree(self) -> None:
        self._tree.clear()
        groups: dict[str, list[DrcViolation]] = {}
        for v in self._filtered:
            groups.setdefault(v.rule, []).append(v)
        for rule, items in sorted(groups.items()):
            top = QTreeWidgetItem([rule, str(len(items))])
            if any(v.severity == "error" for v in items):
                top.setForeground(0, QBrush(QColor("#c0392b")))
            for v in items[:200]:
                child = QTreeWidgetItem([
                    f"{v.layer} @ ({v.x_um:.3f}, {v.y_um:.3f})",
                    "",
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, v)
                top.addChild(child)
            self._tree.addTopLevelItem(top)

    def _populate_table(self) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._filtered))
        for r, v in enumerate(self._filtered):
            items = [
                QTableWidgetItem(v.rule),
                QTableWidgetItem(v.layer),
                QTableWidgetItem(v.severity),
                _num(v.x_um),
                _num(v.y_um),
                QTableWidgetItem(_fix_for_rule(v.rule)),
                QTableWidgetItem(v.message),
            ]
            if v.severity == "error":
                for it in items:
                    it.setForeground(QBrush(QColor("#e74c3c")))
            for c, it in enumerate(items):
                self._table.setItem(r, c, it)
        self._table.setSortingEnabled(True)

    def _refresh_heatmap(self) -> None:
        if not _HAVE_MPL or not self._report:
            return
        fig = self._fig
        fig.clear()
        ax = fig.add_subplot(111)
        if self._filtered:
            # Use filtered report for the density grid
            grid = DrcReport(
                tool=self._report.tool,
                violations=self._filtered,
            ).density_grid(grid_size_um=10.0)
            ax.imshow(grid, origin="lower", cmap="hot", aspect="auto")
            ax.set_title(f"{len(self._filtered)} DRCs")
        else:
            ax.text(0.5, 0.5, "no data", ha="center", va="center")
            ax.set_xticks([])
            ax.set_yticks([])
        self._canvas.draw_idle()

    # ------------------------------------------------------------------ signals

    def _on_tree_select(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        v = items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(v, DrcViolation) if DrcViolation else False:
            self.violationActivated.emit(float(v.x_um), float(v.y_um), v.layer)

    def _on_double(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._filtered):
            return
        v = self._filtered[row]
        self.violationActivated.emit(float(v.x_um), float(v.y_um), v.layer)

    # ------------------------------------------------------------------ io

    def _on_export(self) -> None:
        if not self._filtered:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DRC CSV", "drc.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["rule", "layer", "severity", "x_um", "y_um", "x2_um", "y2_um", "message"])
            for v in self._filtered:
                w.writerow([v.rule, v.layer, v.severity, v.x_um, v.y_um, v.x2_um, v.y2_um, v.message])

    def _on_waive(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedItems()})
        if not rows:
            QMessageBox.information(self, "Waiver", "Select at least one violation.")
            return
        selected = [self._filtered[r] for r in rows if 0 <= r < len(self._filtered)]
        path, _ = QFileDialog.getSaveFileName(
            self, "Waiver file", "drc.waivers", "Waiver (*.waivers);;All files (*)"
        )
        if not path:
            return
        with open(path, "a", encoding="utf-8") as fh:
            for v in selected:
                fh.write(
                    f"waive rule={v.rule!r} layer={v.layer} "
                    f"bbox=({v.x_um},{v.y_um},{v.x2_um},{v.y2_um}) "
                    f"reason=\"manual waiver\"\n"
                )
        QMessageBox.information(self, "Waiver", f"Wrote {len(selected)} waivers to {path}.")


def _num(value: float) -> QTableWidgetItem:
    it = QTableWidgetItem()
    it.setData(Qt.ItemDataRole.DisplayRole, float(value))
    return it


__all__ = ["DrcBrowserPanel"]
