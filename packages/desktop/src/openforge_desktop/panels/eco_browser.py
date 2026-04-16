"""ECO script browser and editor."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.eco import (
        EcoCommand,
        EcoCommandKind,
        EcoEngine,
        EcoScript,
    )
    from openforge.physical.sta_parser import StaReport
except Exception:  # pragma: no cover
    EcoCommand = None  # type: ignore[assignment]
    EcoCommandKind = None  # type: ignore[assignment]
    EcoEngine = None  # type: ignore[assignment]
    EcoScript = None  # type: ignore[assignment]
    StaReport = None  # type: ignore[assignment]


_BG = "#1e1e2e"
_PANEL = "#181825"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_SUBTLE = "#a6adc8"
_BLUE = "#89b4fa"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"


class EcoBrowserPanel(QDockWidget):
    """Browse STA violations and build an ECO script."""

    apply_requested = Signal(str)  # tcl text

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ECO Browser", parent)
        self.setObjectName("eco_browser_dock")
        self._dark = True
        self._script: EcoScript | None = None  # type: ignore[valid-type]
        self._engine: EcoEngine | None = None  # type: ignore[valid-type]
        self._sta_report: StaReport | None = None  # type: ignore[valid-type]

        root = QWidget(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Toolbar
        self._toolbar = QToolBar("ECO", root)
        self._act_fix_setup = self._toolbar.addAction("Fix Setup")
        self._act_fix_hold = self._toolbar.addAction("Fix Hold")
        self._act_leakage = self._toolbar.addAction("Reduce Leakage")
        self._toolbar.addSeparator()
        self._act_save = self._toolbar.addAction("Save .tcl")
        self._act_apply = self._toolbar.addAction("Apply ECO")
        outer.addWidget(self._toolbar)

        self._act_fix_setup.triggered.connect(self._auto_fix_setup)
        self._act_fix_hold.triggered.connect(self._auto_fix_hold)
        self._act_leakage.triggered.connect(self._auto_leakage)
        self._act_save.triggered.connect(self._save_script)
        self._act_apply.triggered.connect(self._apply_script)

        # Target dialect + metal-only toggle
        options = QHBoxLayout()
        options.addWidget(QLabel("Dialect:"))
        self._dialect = QComboBox()
        self._dialect.addItems(["OpenROAD", "Innovus"])
        self._dialect.currentIndexChanged.connect(self._refresh_preview)
        options.addWidget(self._dialect)
        self._metal_only = QCheckBox("Metal-only filter")
        self._metal_only.toggled.connect(self._refresh_script_table)
        options.addWidget(self._metal_only)
        options.addStretch(1)
        self._disturb_label = QLabel(
            "cells=0 added=0 nets=0 area=0.0 runtime=0.0s"
        )
        self._disturb_label.setStyleSheet(f"color: {_SUBTLE};")
        options.addWidget(self._disturb_label)
        outer.addLayout(options)

        # Splitters
        vsplit = QSplitter(Qt.Orientation.Vertical, root)
        hsplit = QSplitter(Qt.Orientation.Horizontal, vsplit)

        # Left: violation list
        left = QWidget(hsplit)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Violations"))
        self._violations = QTableWidget(0, 4, left)
        self._violations.setHorizontalHeaderLabels(
            ["Endpoint", "Check", "Slack (ns)", "Clock"]
        )
        self._violations.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._violations.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._violations.itemDoubleClicked.connect(self._auto_fix_selected)
        ll.addWidget(self._violations)
        hsplit.addWidget(left)

        # Right: script table
        right = QWidget(hsplit)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("ECO script"))
        self._script_table = QTableWidget(0, 5, right)
        self._script_table.setHorizontalHeaderLabels(
            ["#", "Kind", "Target", "Net / New", "Notes"]
        )
        self._script_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._script_table.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self._script_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        rl.addWidget(self._script_table)

        row_btns = QHBoxLayout()
        remove_btn = QPushButton("Remove row")
        remove_btn.clicked.connect(self._remove_selected_row)
        clear_btn = QPushButton("Clear script")
        clear_btn.clicked.connect(self._clear_script)
        row_btns.addWidget(remove_btn)
        row_btns.addWidget(clear_btn)
        row_btns.addStretch(1)
        rl.addLayout(row_btns)
        hsplit.addWidget(right)
        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 2)
        vsplit.addWidget(hsplit)

        # Bottom: preview + slack diff
        bottom = QWidget(vsplit)
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("Preview (Tcl)"))
        self._preview = QPlainTextEdit(bottom)
        self._preview.setReadOnly(True)
        bl.addWidget(self._preview)
        self._slack_diff = QLabel("Slack before/after: -")
        self._slack_diff.setStyleSheet(f"color: {_SUBTLE};")
        bl.addWidget(self._slack_diff)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 2)
        vsplit.setStretchFactor(1, 1)
        outer.addWidget(vsplit)

        self.setWidget(root)
        self._apply_style()

    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_style()

    def set_engine(self, engine: EcoEngine) -> None:
        self._engine = engine

    def load_sta(self, report: StaReport) -> None:
        self._sta_report = report
        self._refresh_violations()

    def load_script(self, script: EcoScript) -> None:
        self._script = script
        self._refresh_script_table()
        self._refresh_preview()

    # ------------------------------------------------------------------

    def _apply_style(self) -> None:
        bg = _BG if self._dark else "#eff1f5"
        fg = _TEXT if self._dark else "#4c4f69"
        panel = _PANEL if self._dark else "#e6e9ef"
        surface = _SURFACE if self._dark else "#dce0e8"
        self.setStyleSheet(
            f"""
            QDockWidget {{ color: {fg}; }}
            QWidget {{ background-color: {bg}; color: {fg}; }}
            QTableWidget, QPlainTextEdit {{
                background-color: {panel}; color: {fg};
                border: 1px solid {surface};
            }}
            QPushButton {{
                background-color: {surface}; color: {fg};
                border: 1px solid {surface}; padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {_BLUE}; color: black; }}
            QToolBar {{ background: {panel}; border: none; spacing: 2px; }}
            """
        )

    def _refresh_violations(self) -> None:
        self._violations.setRowCount(0)
        if self._sta_report is None:
            return
        paths = self._sta_report.violating_paths()
        self._violations.setRowCount(len(paths))
        for row, p in enumerate(paths):
            self._violations.setItem(row, 0, QTableWidgetItem(p.endpoint))
            self._violations.setItem(row, 1, QTableWidgetItem(p.check_type or p.path_type))
            slack_item = QTableWidgetItem(f"{p.slack_ns:.3f}")
            if p.slack_ns < 0:
                slack_item.setForeground(QBrush(QColor(_RED)))
            self._violations.setItem(row, 2, slack_item)
            self._violations.setItem(
                row, 3, QTableWidgetItem(p.endpoint_clock or "-")
            )

    def _ensure_script(self) -> None:
        if self._script is None and EcoScript is not None:
            self._script = EcoScript()

    def _auto_fix_setup(self) -> None:
        if self._engine is None or self._sta_report is None:
            QMessageBox.information(self, "ECO", "Load STA report and engine first.")
            return
        script = self._engine.fix_setup_violations(self._sta_report, -0.01, 64)
        self._merge_script(script)

    def _auto_fix_hold(self) -> None:
        if self._engine is None or self._sta_report is None:
            QMessageBox.information(self, "ECO", "Load STA report and engine first.")
            return
        script = self._engine.fix_hold_violations(self._sta_report, 0.0, 64)
        self._merge_script(script)

    def _auto_leakage(self) -> None:
        QMessageBox.information(
            self,
            "ECO",
            "Use the Multi-Vt panel for leakage optimization; it writes an ECO script here.",
        )

    def _auto_fix_selected(self) -> None:
        self._auto_fix_setup()

    def _merge_script(self, new: EcoScript) -> None:
        self._ensure_script()
        if self._script is None:
            return
        self._script.commands.extend(new.commands)
        self._script.metadata.update(new.metadata)
        self._refresh_script_table()
        self._refresh_preview()

    def _refresh_script_table(self) -> None:
        self._script_table.setRowCount(0)
        if self._script is None:
            self._update_disturbance()
            return
        commands = self._script.commands
        if self._metal_only.isChecked() and self._engine is not None:
            forbidden = {
                EcoCommandKind.CHANGE_CELL,
                EcoCommandKind.ADD_BUFFER,
                EcoCommandKind.ADD_REPEATER,
                EcoCommandKind.DELETE_INSTANCE,
            }
            commands = [c for c in commands if c.kind not in forbidden]
        for row, cmd in enumerate(commands):
            self._script_table.insertRow(row)
            self._script_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self._script_table.setItem(
                row, 1, QTableWidgetItem(cmd.kind.value)
            )
            self._script_table.setItem(
                row, 2, QTableWidgetItem(cmd.target_inst or "-")
            )
            rhs = cmd.new_cell or cmd.net or "-"
            self._script_table.setItem(row, 3, QTableWidgetItem(rhs))
            self._script_table.setItem(
                row, 4, QTableWidgetItem(cmd.notes or "")
            )
        self._update_disturbance()
        self._refresh_preview()

    def _remove_selected_row(self) -> None:
        if self._script is None:
            return
        rows = sorted({i.row() for i in self._script_table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._script.commands):
                del self._script.commands[r]
        self._refresh_script_table()

    def _clear_script(self) -> None:
        if self._script is not None:
            self._script.commands.clear()
        self._refresh_script_table()

    def _update_disturbance(self) -> None:
        if self._script is None or self._engine is None:
            self._disturb_label.setText("cells=0 added=0 nets=0 area=0.0 runtime=0.0s")
            return
        d = self._engine.estimate_disturbance(self._script)
        self._disturb_label.setText(
            "cells=%d added=%d nets=%d area=%.2f runtime=%.1fs metal_only=%s"
            % (
                d["cells_changed"],
                d["cells_added"],
                d["nets_rerouted"],
                d["area_delta"],
                d["estimated_runtime"],
                d["metal_only"],
            )
        )
        # Slack what-if: sum of slack_before vs slack_after on commands
        before = sum(
            c.slack_before_ns or 0.0 for c in self._script.commands
            if c.slack_before_ns is not None
        )
        after = sum(
            c.slack_after_ns or (c.slack_before_ns or 0.0) + 0.05
            for c in self._script.commands
            if c.slack_before_ns is not None
        )
        if self._script.commands:
            self._slack_diff.setText(
                f"Slack before: {before:.3f} ns  after (est): {after:.3f} ns"
            )

    def _refresh_preview(self) -> None:
        if self._script is None:
            self._preview.setPlainText("")
            return
        if self._dialect.currentText() == "OpenROAD":
            self._preview.setPlainText(self._script.to_openroad_tcl())
        else:
            self._preview.setPlainText(self._script.to_innovus_tcl())

    def _save_script(self) -> None:
        if self._script is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ECO script", "eco.tcl", "Tcl (*.tcl)"
        )
        if not path:
            return
        Path(path).write_text(self._preview.toPlainText())

    def _apply_script(self) -> None:
        if self._script is None:
            return
        tcl = self._preview.toPlainText()
        self.apply_requested.emit(tcl)


__all__ = ["EcoBrowserPanel"]
