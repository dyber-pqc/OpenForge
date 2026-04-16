"""LEC results panel for the OpenForge desktop app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

CATPPUCCIN_DARK = """
QWidget { background: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', sans-serif; }
QLineEdit, QPlainTextEdit, QTableWidget {
    background: #181825; color: #cdd6f4; border: 1px solid #313244;
    selection-background-color: #585b70;
}
QPushButton {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    padding: 6px 14px; border-radius: 4px;
}
QPushButton:hover { background: #45475a; }
QPushButton:pressed { background: #585b70; }
QHeaderView::section { background: #313244; color: #cdd6f4; padding: 4px; border: none; }
QTabWidget::pane { border: 1px solid #313244; }
QTabBar::tab { background: #181825; color: #cdd6f4; padding: 6px 14px; }
QTabBar::tab:selected { background: #313244; }
QProgressBar { background: #181825; border: 1px solid #313244; text-align: center; }
QProgressBar::chunk { background: #89b4fa; }
"""

CATPPUCCIN_LIGHT = """
QWidget { background: #eff1f5; color: #4c4f69; font-family: 'Segoe UI', sans-serif; }
QLineEdit, QPlainTextEdit, QTableWidget {
    background: #ffffff; color: #4c4f69; border: 1px solid #ccd0da;
}
QPushButton { background: #ccd0da; color: #4c4f69; border: 1px solid #bcc0cc;
              padding: 6px 14px; border-radius: 4px; }
QPushButton:hover { background: #bcc0cc; }
"""


class LecPanel(QDockWidget):
    """Logical Equivalence Checking results panel."""

    runRequested = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LEC")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dark = True
        self._build_ui()
        self.set_theme(True)

    # ---------- ui construction ----------

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        # design selectors
        form = QFormLayout()
        self._gold_edit = QLineEdit()
        self._gold_top = QLineEdit()
        self._gold_top.setPlaceholderText("top module")
        self._rev_edit = QLineEdit()
        self._rev_top = QLineEdit()
        self._rev_top.setPlaceholderText("top module")

        gold_row = QHBoxLayout()
        gold_row.addWidget(self._gold_edit, 4)
        gold_browse = QPushButton("Browse")
        gold_browse.clicked.connect(self._pick_gold)
        gold_row.addWidget(gold_browse, 1)
        gold_row.addWidget(self._gold_top, 2)
        gw = QWidget()
        gw.setLayout(gold_row)
        form.addRow("Gold sources:", gw)

        rev_row = QHBoxLayout()
        rev_row.addWidget(self._rev_edit, 4)
        rev_browse = QPushButton("Browse")
        rev_browse.clicked.connect(self._pick_rev)
        rev_row.addWidget(rev_browse, 1)
        rev_row.addWidget(self._rev_top, 2)
        rw = QWidget()
        rw.setLayout(rev_row)
        form.addRow("Revised sources:", rw)
        layout.addLayout(form)

        # run button + progress
        ctl_row = QHBoxLayout()
        self._run_btn = QPushButton("Run LEC")
        self._run_btn.clicked.connect(self._on_run_clicked)
        ctl_row.addWidget(self._run_btn)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        ctl_row.addWidget(self._progress, 1)
        layout.addLayout(ctl_row)

        # big status
        self._status_label = QLabel("UNKNOWN")
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self._status_label.setFont(f)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("background:#313244; padding:14px; border-radius:6px;")
        layout.addWidget(self._status_label)

        # stats row
        stats_row = QHBoxLayout()
        self._lbl_points = QLabel("Points: 0")
        self._lbl_matched = QLabel("Matched: 0")
        self._lbl_diff = QLabel("Differences: 0")
        self._lbl_dur = QLabel("Duration: 0.00 s")
        for w in (self._lbl_points, self._lbl_matched, self._lbl_diff, self._lbl_dur):
            w.setStyleSheet("padding:4px 12px;")
            stats_row.addWidget(w)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        # tabs - differences + log
        self._tabs = QTabWidget()
        self._diff_table = QTableWidget(0, 4)
        self._diff_table.setHorizontalHeaderLabels(["Type", "Gold Signal", "Rev Signal", "Reason"])
        self._diff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._diff_table.verticalHeader().setVisible(False)
        self._tabs.addTab(self._diff_table, "Differences")

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 9))
        self._tabs.addTab(self._log_view, "Log")

        layout.addWidget(self._tabs, 1)
        self.setWidget(root)

    # ---------- public api ----------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self.setStyleSheet(CATPPUCCIN_DARK if dark else CATPPUCCIN_LIGHT)

    def show_result(self, result: Any) -> None:
        """Populate the panel from an LecResult."""
        self._progress.setVisible(False)
        if result is None:
            return
        equiv = getattr(result, "equivalent", False)
        success = getattr(result, "success", False)
        if not success:
            self._status_label.setText("ERROR")
            self._status_label.setStyleSheet(
                "background:#f38ba8; color:#1e1e2e; padding:14px; border-radius:6px;"
            )
        elif equiv:
            self._status_label.setText("EQUIVALENT")
            self._status_label.setStyleSheet(
                "background:#a6e3a1; color:#1e1e2e; padding:14px; border-radius:6px;"
            )
        else:
            self._status_label.setText("NOT EQUIVALENT")
            self._status_label.setStyleSheet(
                "background:#f38ba8; color:#1e1e2e; padding:14px; border-radius:6px;"
            )

        self._lbl_points.setText(f"Points: {getattr(result, 'point_count', 0)}")
        self._lbl_matched.setText(f"Matched: {getattr(result, 'matched', 0)}")
        diffs = getattr(result, "diff_points", []) or []
        self._lbl_diff.setText(f"Differences: {len(diffs)}")
        self._lbl_dur.setText(f"Duration: {getattr(result, 'duration', 0.0):.2f} s")

        self._diff_table.setRowCount(0)
        for diff in diffs:
            row = self._diff_table.rowCount()
            self._diff_table.insertRow(row)
            self._diff_table.setItem(row, 0, QTableWidgetItem(str(diff.get("type", ""))))
            self._diff_table.setItem(row, 1, QTableWidgetItem(str(diff.get("signal", ""))))
            self._diff_table.setItem(row, 2, QTableWidgetItem(str(diff.get("rev_signal", ""))))
            self._diff_table.setItem(row, 3, QTableWidgetItem(str(diff.get("reason", ""))))

        self._log_view.setPlainText(getattr(result, "log", "") or "")

    def append_log(self, line: str) -> None:
        self._log_view.appendPlainText(line)

    def set_running(self, running: bool) -> None:
        self._progress.setVisible(running)
        self._run_btn.setEnabled(not running)
        if running:
            self._status_label.setText("RUNNING...")
            self._status_label.setStyleSheet(
                "background:#f9e2af; color:#1e1e2e; padding:14px; border-radius:6px;"
            )

    # ---------- slots ----------

    def _pick_gold(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select gold sources", "", "Verilog (*.v *.sv);;All (*)"
        )
        if files:
            self._gold_edit.setText(";".join(files))

    def _pick_rev(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select revised sources", "", "Verilog (*.v *.sv);;All (*)"
        )
        if files:
            self._rev_edit.setText(";".join(files))

    def _on_run_clicked(self) -> None:
        params = {
            "gold_sources": [Path(p) for p in self._gold_edit.text().split(";") if p],
            "gold_top": self._gold_top.text().strip() or "top",
            "rev_sources": [Path(p) for p in self._rev_edit.text().split(";") if p],
            "rev_top": self._rev_top.text().strip() or "top",
        }
        self.set_running(True)
        self.runRequested.emit(params)
