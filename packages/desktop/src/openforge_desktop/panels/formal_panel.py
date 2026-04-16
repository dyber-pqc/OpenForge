"""Phase 4 formal verification panel.

Drives :class:`openforge.verification.formal.SbyRunner`, lists the
discovered assert/assume/cover properties, shows PASS/FAIL/UNKNOWN
badges, and emits a Qt signal when a counter-example VCD is ready to
load in the waveform panel.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from ._theme import panel_tab_qss
except Exception:  # pragma: no cover

    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""


try:
    from openforge.verification.formal import (
        FormalConfig,
        FormalEngine,
        FormalProperty,
        FormalResult,
        SbyRunner,
        scan_properties,
    )
except Exception:  # pragma: no cover
    FormalConfig = None  # type: ignore
    FormalEngine = None  # type: ignore
    FormalProperty = None  # type: ignore
    FormalResult = None  # type: ignore
    SbyRunner = None  # type: ignore
    scan_properties = None  # type: ignore


STATUS_COLOURS = {
    "PASS": "#a6e3a1",
    "FAIL": "#f38ba8",
    "UNKNOWN": "#f9e2af",
    "TIMEOUT": "#fab387",
}


class _Bridge(QObject):
    finished = Signal(list)


class FormalPanel(QWidget):
    """Formal verification UI."""

    counterexampleReady = Signal(str)  # path to cex VCD
    openWaveform = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rtl_files: list[str] = []
        self._results: list = []
        self._thread: threading.Thread | None = None
        self._bridge = _Bridge()
        self._bridge.finished.connect(self._on_run_done)
        self._build_ui()
        self.setStyleSheet(panel_tab_qss(True))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Config form
        cfg_box = QGroupBox("SymbiYosys Configuration")
        form = QFormLayout(cfg_box)
        self._top_edit = QLineEdit()
        self._top_edit.setPlaceholderText("top_module")
        form.addRow("Top module:", self._top_edit)

        self._engine = QComboBox()
        if FormalEngine is not None:
            for e in FormalEngine:
                self._engine.addItem(e.value)
        else:
            self._engine.addItems(["smtbmc", "abc pdr", "aiger", "btor", "avy"])
        form.addRow("Engine:", self._engine)

        self._mode = QComboBox()
        self._mode.addItems(["bmc", "prove", "cover", "live"])
        form.addRow("Mode:", self._mode)

        self._depth = QSpinBox()
        self._depth.setRange(1, 10000)
        self._depth.setValue(50)
        form.addRow("Depth:", self._depth)

        self._timeout = QSpinBox()
        self._timeout.setRange(1, 100000)
        self._timeout.setValue(600)
        self._timeout.setSuffix(" s")
        form.addRow("Timeout:", self._timeout)

        rtl_row = QHBoxLayout()
        self._rtl_edit = QLineEdit()
        self._rtl_edit.setReadOnly(True)
        add_btn = QPushButton("Add RTL…")
        add_btn.clicked.connect(self._on_add_rtl)
        scan_btn = QPushButton("Scan Properties")
        scan_btn.clicked.connect(self._on_scan)
        rtl_row.addWidget(self._rtl_edit, 1)
        rtl_row.addWidget(add_btn)
        rtl_row.addWidget(scan_btn)
        form.addRow("RTL files:", rtl_row)

        root.addWidget(cfg_box)

        # Run / load cex
        run_row = QHBoxLayout()
        self._run_btn = QPushButton("Run")
        self._run_btn.clicked.connect(self._on_run)
        self._replay_btn = QPushButton("Replay Counterexample")
        self._replay_btn.clicked.connect(self._on_replay)
        self._replay_btn.setEnabled(False)
        run_row.addWidget(self._run_btn)
        run_row.addWidget(self._replay_btn)
        run_row.addStretch(1)
        root.addLayout(run_row)

        # Tabs
        split = QSplitter(Qt.Orientation.Horizontal)
        self._props = QTableWidget(0, 4)
        self._props.setHorizontalHeaderLabels(["Kind", "Name", "File:Line", "Status"])
        self._props.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._props.itemSelectionChanged.connect(self._on_prop_select)
        split.addWidget(self._props)

        self._right = QTabWidget()
        self._cex_view = QPlainTextEdit()
        self._cex_view.setReadOnly(True)
        self._right.addTab(self._cex_view, "Counterexample")
        self._cover_tbl = QTableWidget(0, 3)
        self._cover_tbl.setHorizontalHeaderLabels(["Cover", "Status", "File:Line"])
        self._right.addTab(self._cover_tbl, "Cover Points")
        split.addWidget(self._right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    def _on_add_rtl(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select RTL", "", "Verilog (*.v *.sv *.vh *.svh)"
        )
        if not paths:
            return
        self._rtl_files.extend(paths)
        self._rtl_edit.setText("; ".join(self._rtl_files))

    def _on_scan(self) -> None:
        if scan_properties is None:
            return
        props = scan_properties(self._rtl_files)
        self._props.setRowCount(len(props))
        for row, p in enumerate(props):
            self._props.setItem(row, 0, QTableWidgetItem(p.kind))
            self._props.setItem(row, 1, QTableWidgetItem(p.name))
            self._props.setItem(row, 2, QTableWidgetItem(f"{Path(p.file).name}:{p.line}"))
            st = QTableWidgetItem("PENDING")
            st.setForeground(QBrush(QColor("#94a3b8")))
            self._props.setItem(row, 3, st)

    def _on_run(self) -> None:
        if SbyRunner is None or FormalConfig is None or FormalEngine is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            engine = FormalEngine(self._engine.currentText())
        except Exception:
            engine = FormalEngine.SMTBMC
        cfg = FormalConfig(
            top_module=self._top_edit.text().strip() or "top",
            rtl_files=list(self._rtl_files),
            engine=engine,
            depth=self._depth.value(),
            mode=self._mode.currentText(),
            timeout_s=self._timeout.value(),
        )
        work = Path.cwd() / "formal_work" / cfg.top_module
        runner = SbyRunner(cfg, work)

        def _thread() -> None:
            try:
                res = runner.run()
            except Exception:
                res = []
            self._bridge.finished.emit(res)

        self._thread = threading.Thread(target=_thread, daemon=True)
        self._thread.start()

    @Slot(list)
    def _on_run_done(self, results: list) -> None:
        self._results = results
        self._props.setRowCount(len(results))
        for row, r in enumerate(results):
            p = r.property
            self._props.setItem(row, 0, QTableWidgetItem(p.kind))
            self._props.setItem(row, 1, QTableWidgetItem(p.name))
            self._props.setItem(row, 2, QTableWidgetItem(f"{Path(p.file).name}:{p.line}"))
            cell = QTableWidgetItem(r.status)
            cell.setForeground(QBrush(QColor(STATUS_COLOURS.get(r.status, "#cdd6f4"))))
            self._props.setItem(row, 3, cell)
        # Populate cover table
        covers = [r for r in results if r.property.kind == "cover"]
        self._cover_tbl.setRowCount(len(covers))
        for row, r in enumerate(covers):
            p = r.property
            self._cover_tbl.setItem(row, 0, QTableWidgetItem(p.name))
            self._cover_tbl.setItem(row, 1, QTableWidgetItem(r.status))
            self._cover_tbl.setItem(row, 2, QTableWidgetItem(f"{Path(p.file).name}:{p.line}"))

    def _on_prop_select(self) -> None:
        rows = self._props.selectionModel().selectedRows()
        if not rows or not self._results:
            self._replay_btn.setEnabled(False)
            return
        idx = rows[0].row()
        if idx >= len(self._results):
            return
        r = self._results[idx]
        self._cex_view.setPlainText(
            f"Property: {r.property.name}\n"
            f"Kind:     {r.property.kind}\n"
            f"File:     {r.property.file}:{r.property.line}\n"
            f"Expr:     {r.property.expr}\n"
            f"Status:   {r.status}\n"
            f"Runtime:  {r.runtime_s:.2f}s\n"
            f"CEX VCD:  {r.cex_vcd or '-'}\n"
        )
        self._replay_btn.setEnabled(bool(r.cex_vcd))

    def _on_replay(self) -> None:
        rows = self._props.selectionModel().selectedRows()
        if not rows or not self._results:
            return
        idx = rows[0].row()
        r = self._results[idx]
        if r.cex_vcd:
            self.counterexampleReady.emit(r.cex_vcd)
            self.openWaveform.emit(r.cex_vcd)
