"""Electrical Rules Check (ERC) panel.

Qt widget that runs :class:`openforge.pcb.erc.ErcChecker` against a
schematic and displays violations in a sortable table with inline
severity colouring, rule toggles, waivers and HTML report export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    from openforge.pcb.erc import (
        BUILTIN_RULES,
        ErcChecker,
        ErcWaiver,
    )

    _HAS_ERC = True
except Exception:  # pragma: no cover
    _HAS_ERC = False


_QSS = """
QFrame#ErcRoot {
    background: #1e1e2e;
    color: #cdd6f4;
}
QFrame#ErcRoot QLabel {
    color: #cdd6f4;
    background: transparent;
}
QFrame#ErcRoot QLabel#SectionTitle {
    font-weight: 700;
    color: #a6adc8;
    font-size: 10px;
    letter-spacing: 1px;
}
QFrame#ErcRoot QPushButton {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 12px;
}
QFrame#ErcRoot QPushButton:hover { background: #45475a; }
QFrame#ErcRoot QPushButton:pressed { background: #00d4ff; color: #11111b; }
QFrame#ErcRoot QPushButton#RunButton {
    background: #00d4ff;
    color: #11111b;
    font-weight: 700;
}
QFrame#ErcRoot QTableWidget,
QFrame#ErcRoot QTreeWidget {
    background: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    gridline-color: #313244;
    alternate-background-color: #1e1e2e;
}
QFrame#ErcRoot QHeaderView::section {
    background: #313244;
    color: #cdd6f4;
    border: 0;
    padding: 6px 8px;
    font-weight: 700;
}
QFrame#ErcRoot QComboBox {
    background: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 4px 8px;
}
"""


class ErcPanel(QWidget):
    """Interactive ERC panel.

    Signals
    -------
    violation_selected(component_refdes)
        Emitted when the user clicks a row, so the host panel can pan the
        schematic canvas to the offending component.
    """

    violation_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._schematic: Any = None
        self._checker: ErcChecker | None = None
        self._violations: list[Any] = []
        self._rules: list[Any] = list(BUILTIN_RULES) if _HAS_ERC else []
        self._waivers: list[Any] = []
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QFrame()
        root.setObjectName("ErcRoot")
        root.setStyleSheet(_QSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Top toolbar
        top = QHBoxLayout()
        top.setSpacing(6)
        title = QLabel("ELECTRICAL RULES CHECK")
        title.setObjectName("SectionTitle")
        top.addWidget(title)
        top.addStretch()
        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["All", "Error", "Warning", "Info"])
        self.severity_filter.currentTextChanged.connect(self._refresh_table)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self.severity_filter)

        self.run_btn = QPushButton("Run ERC")
        self.run_btn.setObjectName("RunButton")
        self.run_btn.clicked.connect(self.run_erc)
        top.addWidget(self.run_btn)

        self.fix_btn = QPushButton("Auto-Fix Hint")
        self.fix_btn.clicked.connect(self._show_fix)
        top.addWidget(self.fix_btn)

        self.waive_btn = QPushButton("Waive")
        self.waive_btn.clicked.connect(self._waive_selected)
        top.addWidget(self.waive_btn)

        self.export_btn = QPushButton("Export HTML")
        self.export_btn.clicked.connect(self._export_html)
        top.addWidget(self.export_btn)

        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Rule list
        self.rule_tree = QTreeWidget()
        self.rule_tree.setHeaderLabels(["Enabled", "ID", "Description"])
        self.rule_tree.setAlternatingRowColors(True)
        for rule in self._rules:
            itm = QTreeWidgetItem(
                [
                    "",
                    rule.id,
                    rule.description,
                ]
            )
            itm.setCheckState(0, Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            itm.setData(1, Qt.ItemDataRole.UserRole, rule.id)
            self.rule_tree.addTopLevelItem(itm)
        self.rule_tree.itemChanged.connect(self._on_rule_toggled)
        self.rule_tree.setColumnWidth(0, 60)
        self.rule_tree.setColumnWidth(1, 60)
        splitter.addWidget(self.rule_tree)

        # Violation table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Severity", "Rule", "Component", "Pin", "Net", "Message"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter, 1)

        # Status bar
        self.status = QLabel("No ERC run yet")
        self.status.setStyleSheet(
            "color: #a6adc8; padding: 4px 8px;"
            "background: #181825; border: 1px solid #313244; border-radius: 4px;"
        )
        layout.addWidget(self.status)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_schematic(self, schematic: Any) -> None:
        self._schematic = schematic

    def run_erc(self) -> None:
        if not _HAS_ERC:
            QMessageBox.warning(self, "ERC", "openforge.pcb.erc is not available")
            return
        if self._schematic is None:
            QMessageBox.information(self, "ERC", "No schematic loaded")
            return
        self._checker = ErcChecker(self._schematic, rules=self._rules, waivers=self._waivers)
        self._violations = self._checker.check_all()
        self._refresh_table()
        err = sum(1 for v in self._violations if v.severity == "error")
        warn = sum(1 for v in self._violations if v.severity == "warning")
        info = sum(1 for v in self._violations if v.severity == "info")
        self.status.setText(
            f"{len(self._violations)} violations: {err} errors, {warn} warnings, {info} info"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_rule_toggled(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0:
            return
        rid = item.data(1, Qt.ItemDataRole.UserRole)
        enabled = item.checkState(0) == Qt.CheckState.Checked
        for r in self._rules:
            if r.id == rid:
                r.enabled = enabled
                break

    def _refresh_table(self) -> None:
        filt = self.severity_filter.currentText().lower()
        self.table.setRowCount(0)
        for v in self._violations:
            if filt != "all" and v.severity != filt:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            color = {
                "error": QColor("#f38ba8"),
                "warning": QColor("#f9e2af"),
                "info": QColor("#89b4fa"),
            }.get(v.severity, QColor("#cdd6f4"))
            cells = [v.severity.upper(), v.rule, v.component, v.pin, v.net, v.message]
            for col, txt in enumerate(cells):
                itm = QTableWidgetItem(str(txt))
                if col == 0:
                    itm.setForeground(QBrush(color))
                    f = QFont()
                    f.setBold(True)
                    itm.setFont(f)
                if v.waived:
                    itm.setForeground(QBrush(QColor("#6c7086")))
                self.table.setItem(row, col, itm)

    def _selected_violation(self) -> Any | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        r = rows[0].row()
        if r >= len(self._violations):
            return None
        # Need to map displayed row back to violation when filtering.
        filt = self.severity_filter.currentText().lower()
        visible = [v for v in self._violations if filt == "all" or v.severity == filt]
        if r < len(visible):
            return visible[r]
        return None

    def _on_selection_changed(self) -> None:
        v = self._selected_violation()
        if v and v.component:
            self.violation_selected.emit(v.component)

    def _show_fix(self) -> None:
        v = self._selected_violation()
        if not v or not self._checker:
            return
        hint = self._checker.auto_fix(v) or "No auto-fix available"
        QMessageBox.information(self, f"Fix for {v.rule}", hint)

    def _waive_selected(self) -> None:
        if not _HAS_ERC:
            return
        v = self._selected_violation()
        if not v:
            return
        self._waivers.append(
            ErcWaiver(rule=v.rule, component=v.component, pin=v.pin, reason="User waiver")
        )
        v.waived = True
        self._refresh_table()

    def _export_html(self) -> None:
        if not self._checker:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export ERC Report", "erc_report.html", "HTML (*.html)"
        )
        if not path:
            return
        Path(path).write_text(self._checker.export_html(), encoding="utf-8")
        QMessageBox.information(self, "ERC", f"Report saved to {path}")


__all__ = ["ErcPanel"]
