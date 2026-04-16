"""Hold-fix panel.

Lists hold violations from an STA report and lets the user preview /
apply buffer-chain or useful-skew fixes produced by
:class:`openforge.physical.hold_fix.HoldFixer`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.hold_fix import HoldFixer, HoldFixSuggestion
    from openforge.physical.sta_parser import StaReport, parse_sta_report_file
    _HAS_CORE = True
except Exception:  # pragma: no cover
    HoldFixer = None  # type: ignore[assignment]
    HoldFixSuggestion = None  # type: ignore[assignment]
    StaReport = None  # type: ignore[assignment]
    parse_sta_report_file = None  # type: ignore[assignment]
    _HAS_CORE = False

try:
    from openforge_desktop.panels._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore[misc]
        return ""


class HoldFixPanel(QWidget):
    """Show hold violations and generated ECO fixes."""

    eco_script_ready = Signal(object)  # emits EcoScript

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("holdFixPanel")
        self.setStyleSheet(panel_tab_qss(True))

        self._report: Optional["StaReport"] = None
        self._fixer: Optional["HoldFixer"] = None
        self._suggestions: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── toolbar ───────────────────────────────────────────────────
        tools = QHBoxLayout()
        self._load_btn = QPushButton("Load STA Report…")
        self._load_btn.clicked.connect(self._on_load)
        tools.addWidget(self._load_btn)

        self._target_ps = QDoubleSpinBox()
        self._target_ps.setRange(10.0, 1000.0)
        self._target_ps.setValue(50.0)
        self._target_ps.setSuffix(" ps/buf")
        tools.addWidget(QLabel("Buffer delay:"))
        tools.addWidget(self._target_ps)

        self._skew_chk = QCheckBox("Use Useful Skew")
        tools.addWidget(self._skew_chk)

        self._analyse_btn = QPushButton("Analyse")
        self._analyse_btn.clicked.connect(self._on_analyse)
        tools.addWidget(self._analyse_btn)

        self._apply_btn = QPushButton("Apply All Fixes")
        self._apply_btn.clicked.connect(self._on_apply)
        tools.addWidget(self._apply_btn)
        tools.addStretch(1)
        root.addLayout(tools)

        # ── violation table ───────────────────────────────────────────
        self._table = QTableWidget(0, 6, self)
        self._table.setHorizontalHeaderLabels(
            ["Path", "Slack (ns)", "Need (ns)", "Buffers", "Cell", "Notes"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        root.addWidget(self._table, 1)

        # ── diff view ─────────────────────────────────────────────────
        self._diff = QTextEdit(self)
        self._diff.setReadOnly(True)
        self._diff.setPlaceholderText(
            "Slack before/after and ECO script preview will appear here."
        )
        self._diff.setMaximumHeight(180)
        root.addWidget(self._diff)

    # ------------------------------------------------------------------ api

    def set_report(self, report: "StaReport") -> None:
        self._report = report
        if HoldFixer is not None:
            self._fixer = HoldFixer(report)
        self._on_analyse()

    def load_report_file(self, path: Path | str) -> None:
        if parse_sta_report_file is None:
            return
        try:
            rep = parse_sta_report_file(str(path))
        except Exception as exc:  # pragma: no cover
            self._diff.setPlainText(f"Failed to parse STA report: {exc}")
            return
        self.set_report(rep)

    # --------------------------------------------------------------- slots

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open STA Report", "", "Reports (*.rpt *.txt);;All Files (*)"
        )
        if path:
            self.load_report_file(path)

    def _on_analyse(self) -> None:
        if self._fixer is None:
            self._diff.setPlainText("No STA report loaded.")
            return
        suggestions = self._fixer.suggest_fixes(
            target_buffer_delay_ps=self._target_ps.value()
        )
        self._suggestions = suggestions
        self._table.setRowCount(len(suggestions))
        for r, s in enumerate(suggestions):
            self._table.setItem(r, 0, QTableWidgetItem(s.path))
            self._table.setItem(r, 1, QTableWidgetItem(f"{s.slack_ns:+.3f}"))
            self._table.setItem(r, 2, QTableWidgetItem(f"{s.delay_needed_ns:.3f}"))
            self._table.setItem(r, 3, QTableWidgetItem(str(s.buffers_needed)))
            self._table.setItem(r, 4, QTableWidgetItem(s.buffer_cell))
            self._table.setItem(r, 5, QTableWidgetItem(s.notes))
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._diff.setPlainText(
            f"{len(suggestions)} hold violation(s) analysed. "
            f"Area overhead ≈ "
            f"{sum(s.estimated_area_overhead_um2 for s in suggestions):.1f} µm²."
        )

    def _on_apply(self) -> None:
        if self._fixer is None or not self._suggestions:
            return
        if self._skew_chk.isChecked():
            skews = self._fixer.useful_skew_for_hold()
            self._diff.setPlainText(
                "Useful-skew suggestions:\n"
                + "\n".join(
                    f"  {s.endpoint}: Δ={s.delta_ns:+.3f} ns ({s.notes})"
                    for s in skews
                )
            )
            return
        script = self._fixer.to_eco_script()
        try:
            tcl = script.to_openroad_tcl()
        except Exception:
            tcl = f"ECO script with {len(script.commands)} commands"
        self._diff.setPlainText(tcl)
        self.eco_script_ready.emit(script)


__all__ = ["HoldFixPanel"]
