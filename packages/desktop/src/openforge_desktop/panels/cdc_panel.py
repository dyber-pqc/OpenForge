"""CDC panel: drives :class:`openforge.verification.cdc.CdcChecker`."""

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
    QListWidget,
    QListWidgetItem,
    QProgressBar,
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
    from openforge.verification.cdc import CdcChecker, CdcReport
except Exception:  # pragma: no cover
    CdcChecker = None  # type: ignore
    CdcReport = None  # type: ignore


_SEVERITY_COLOR = {
    "critical": QColor("#f38ba8"),
    "warning": QColor("#f9e2af"),
    "info": QColor("#a6e3a1"),
}


class CdcPanel(QWidget):
    """Dockable CDC analyser panel."""

    source_navigate = Signal(str, int)  # file path, line

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cdc_panel")
        self.setStyleSheet(panel_tab_qss(True))

        self._rtl_files: list[Path] = []
        self._top: str = ""
        self._report: CdcReport | None = None

        # ── Top bar ─────────────────────────────────────────────────
        top = QHBoxLayout()
        self._add_btn = QPushButton("Add RTL...")
        self._run_btn = QPushButton("Run CDC")
        self._export_btn = QPushButton("Export HTML")
        self._top_box = QLabel("top: -")
        self._severity = QComboBox()
        self._severity.addItems(["all", "critical", "warning", "info"])
        self._severity.currentTextChanged.connect(self._refresh_crossings)
        top.addWidget(self._add_btn)
        top.addWidget(self._run_btn)
        top.addWidget(self._export_btn)
        top.addSpacing(20)
        top.addWidget(self._top_box)
        top.addStretch(1)
        top.addWidget(QLabel("Severity:"))
        top.addWidget(self._severity)

        self._add_btn.clicked.connect(self._on_add_rtl)
        self._run_btn.clicked.connect(self._on_run)
        self._export_btn.clicked.connect(self._on_export)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        # ── Left: clock domains ─────────────────────────────────────
        self._domain_list = QListWidget()
        dbox = QGroupBox("Clock Domains")
        dv = QVBoxLayout(dbox)
        dv.addWidget(self._domain_list)

        # ── Center: crossings ───────────────────────────────────────
        self._crossings_table = QTableWidget(0, 7)
        self._crossings_table.setHorizontalHeaderLabels(
            ["src signal", "dst signal", "src dom", "dst dom", "type", "severity", "suggestion"]
        )
        h = self._crossings_table.horizontalHeader()
        for i in range(7):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._crossings_table.cellDoubleClicked.connect(self._on_cell_double)
        cbox = QGroupBox("Crossings")
        cv = QVBoxLayout(cbox)
        cv.addWidget(self._crossings_table)

        # ── Right: text graph ───────────────────────────────────────
        self._graph = QListWidget()
        gbox = QGroupBox("Domain Graph")
        gv = QVBoxLayout(gbox)
        gv.addWidget(self._graph)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(dbox)
        split.addWidget(cbox)
        split.addWidget(gbox)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._progress)
        layout.addWidget(split, 1)

    # -- slots --------------------------------------------------

    def set_top(self, top: str) -> None:
        self._top = top
        self._top_box.setText(f"top: {top or '-'}")

    def set_rtl_files(self, files: list[Path]) -> None:
        self._rtl_files = [Path(f) for f in files]

    def _on_add_rtl(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add RTL files", "", "Verilog (*.v *.sv *.vh *.svh)"
        )
        self._rtl_files.extend(Path(f) for f in files)

    def _on_run(self) -> None:
        if CdcChecker is None or not self._rtl_files or not self._top:
            return
        self._progress.setVisible(True)
        try:
            checker = CdcChecker(self._rtl_files, self._top)
            self._report = checker.report()
        finally:
            self._progress.setVisible(False)
        self._refresh_all()

    def _on_export(self) -> None:
        if CdcChecker is None or self._report is None or not self._rtl_files or not self._top:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CDC HTML", "cdc_report.html", "HTML (*.html)"
        )
        if not path:
            return
        checker = CdcChecker(self._rtl_files, self._top)
        checker.to_html(Path(path))

    def _on_cell_double(self, row: int, _col: int) -> None:
        if self._report is None or row >= len(self._report.crossings):
            return
        crossing = self._report.crossings[row]
        if self._rtl_files:
            self.source_navigate.emit(str(self._rtl_files[0]), 1)
        _ = crossing  # reserved for future use

    # -- refresh ------------------------------------------------

    def _refresh_all(self) -> None:
        self._domain_list.clear()
        self._graph.clear()
        if self._report is None:
            self._crossings_table.setRowCount(0)
            return
        for d in self._report.domains:
            self._domain_list.addItem(
                QListWidgetItem(f"{d.name}  period={d.period_ns:.2f}ns  src={d.source}")
            )
        seen: set[tuple[str, str]] = set()
        for c in self._report.crossings:
            key = (c.src_domain, c.dst_domain)
            if key in seen:
                continue
            seen.add(key)
            arrow = "<->" if (c.dst_domain, c.src_domain) in seen else "->"
            self._graph.addItem(QListWidgetItem(f"{c.src_domain} {arrow} {c.dst_domain}"))
        self._refresh_crossings()

    def _refresh_crossings(self) -> None:
        if self._report is None:
            self._crossings_table.setRowCount(0)
            return
        wanted = self._severity.currentText()
        rows = [c for c in self._report.crossings if wanted == "all" or c.severity == wanted]
        self._crossings_table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            vals = [
                c.src_signal,
                c.dst_signal,
                c.src_domain,
                c.dst_domain,
                c.crossing_type,
                c.severity,
                c.suggestion,
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                colour = _SEVERITY_COLOR.get(c.severity)
                if colour is not None:
                    item.setForeground(QBrush(colour))
                self._crossings_table.setItem(r, col, item)
