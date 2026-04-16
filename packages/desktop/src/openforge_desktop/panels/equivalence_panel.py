"""Phase 4 equivalence checking panel (Yosys eqy).

Two file lists for gold (RTL) and gate (post-synth / post-pnr), a match
strategy selector, a run button, and a result summary with drill-in on
a non-equivalent pair to show its witness.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from ._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""

try:
    from openforge.verification.equivalence import EqyConfig, EqyResult, EqyRunner
except Exception:  # pragma: no cover
    EqyConfig = None  # type: ignore
    EqyResult = None  # type: ignore
    EqyRunner = None  # type: ignore


STATUS_COLOURS = {
    "equivalent": "#a6e3a1",
    "not_equivalent": "#f38ba8",
    "partial": "#f9e2af",
    "error": "#fab387",
}


class _Bridge(QObject):
    finished = Signal(object)


class EquivalencePanel(QWidget):
    """Equivalence-checking UI."""

    openWaveform = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result = None
        self._thread: threading.Thread | None = None
        self._bridge = _Bridge()
        self._bridge.finished.connect(self._on_done)
        self._build_ui()
        self.setStyleSheet(panel_tab_qss(True))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Top:"))
        self._top_edit = QLineEdit()
        self._top_edit.setPlaceholderText("top module")
        top_row.addWidget(self._top_edit, 1)
        top_row.addWidget(QLabel("Match:"))
        self._match = QComboBox()
        self._match.addItems(["auto", "name", "gate_to_gold", "fuzzy"])
        top_row.addWidget(self._match)
        self._run_btn = QPushButton("Run eqy")
        self._run_btn.clicked.connect(self._on_run)
        top_row.addWidget(self._run_btn)
        root.addLayout(top_row)

        split = QSplitter(Qt.Orientation.Horizontal)

        gold_box = QGroupBox("Gold (RTL)")
        gl = QVBoxLayout(gold_box)
        self._gold = QListWidget()
        gl.addWidget(self._gold, 1)
        g_row = QHBoxLayout()
        g_add = QPushButton("Add…")
        g_rm = QPushButton("Remove")
        g_add.clicked.connect(lambda: self._add_files(self._gold))
        g_rm.clicked.connect(lambda: self._remove_selected(self._gold))
        g_row.addWidget(g_add)
        g_row.addWidget(g_rm)
        gl.addLayout(g_row)
        split.addWidget(gold_box)

        gate_box = QGroupBox("Gate (post-synth)")
        xl = QVBoxLayout(gate_box)
        self._gate = QListWidget()
        xl.addWidget(self._gate, 1)
        x_row = QHBoxLayout()
        x_add = QPushButton("Add…")
        x_rm = QPushButton("Remove")
        x_add.clicked.connect(lambda: self._add_files(self._gate))
        x_rm.clicked.connect(lambda: self._remove_selected(self._gate))
        x_row.addWidget(x_add)
        x_row.addWidget(x_rm)
        xl.addLayout(x_row)
        split.addWidget(gate_box)

        root.addWidget(split, 1)

        result_box = QGroupBox("Result")
        rl = QVBoxLayout(result_box)
        self._status_lbl = QLabel("No run yet")
        self._status_lbl.setStyleSheet("font-size:16px; font-weight:600;")
        rl.addWidget(self._status_lbl)
        self._summary = QLabel("")
        rl.addWidget(self._summary)
        self._witness = QPlainTextEdit()
        self._witness.setReadOnly(True)
        rl.addWidget(self._witness, 1)
        self._witness_btn = QPushButton("Open Witness in Waveform")
        self._witness_btn.setEnabled(False)
        self._witness_btn.clicked.connect(self._on_open_witness)
        rl.addWidget(self._witness_btn)
        root.addWidget(result_box, 1)

    # ------------------------------------------------------------------
    def _add_files(self, lst: QListWidget) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select", "", "Verilog/Netlist (*.v *.sv *.vg)"
        )
        for p in paths:
            lst.addItem(QListWidgetItem(p))

    def _remove_selected(self, lst: QListWidget) -> None:
        for item in lst.selectedItems():
            lst.takeItem(lst.row(item))

    def _list_paths(self, lst: QListWidget) -> list[str]:
        return [lst.item(i).text() for i in range(lst.count())]

    # ------------------------------------------------------------------
    def _on_run(self) -> None:
        if EqyRunner is None or EqyConfig is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        cfg = EqyConfig(
            gold_files=self._list_paths(self._gold),
            gate_files=self._list_paths(self._gate),
            top=self._top_edit.text().strip() or "top",
            match_strategy=self._match.currentText(),
        )
        work = Path.cwd() / "eqy_work" / cfg.top
        runner = EqyRunner(cfg, work)

        def _thr() -> None:
            try:
                r = runner.run()
            except Exception as exc:  # pragma: no cover
                r = EqyResult(status="error", log=str(exc)) if EqyResult else None
            self._bridge.finished.emit(r)

        self._thread = threading.Thread(target=_thr, daemon=True)
        self._thread.start()
        self._status_lbl.setText("Running…")
        self._status_lbl.setStyleSheet("color:#89b4fa; font-size:16px;")

    @Slot(object)
    def _on_done(self, result) -> None:
        self._result = result
        if result is None:
            self._status_lbl.setText("ERROR")
            return
        colour = STATUS_COLOURS.get(result.status, "#cdd6f4")
        label_text = {
            "equivalent": "EQUIVALENT",
            "not_equivalent": "NOT EQUIVALENT",
            "partial": "PARTIAL",
            "error": "ERROR",
        }.get(result.status, result.status.upper())
        self._status_lbl.setText(label_text)
        self._status_lbl.setStyleSheet(
            f"color:{colour}; font-size:16px; font-weight:600;"
        )
        self._summary.setText(
            f"Matched: {result.matched_pairs}   Proven: {result.proven_pairs}"
        )
        self._witness.setPlainText(result.log[-4000:])
        self._witness_btn.setEnabled(bool(result.counterexample))

    def _on_open_witness(self) -> None:
        if self._result and self._result.counterexample:
            self.openWaveform.emit(self._result.counterexample)
