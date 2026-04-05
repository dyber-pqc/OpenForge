"""Reports panel showing flow results, timing, coverage, and security info."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Catppuccin Mocha palette
_CLR_PASS: Final[str] = "#a6e3a1"    # green
_CLR_FAIL: Final[str] = "#f38ba8"    # red
_CLR_WARN: Final[str] = "#f9e2af"    # yellow
_CLR_INFO: Final[str] = "#89b4fa"    # blue
_CLR_TEXT: Final[str] = "#cdd6f4"
_CLR_DIM: Final[str] = "#a6adc8"


def _status_item(status: str) -> QTableWidgetItem:
    """Create a coloured status cell."""
    item = QTableWidgetItem(status)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    status_lower = status.lower()
    if status_lower in ("pass", "passed", "ok", "success"):
        item.setForeground(QColor(_CLR_PASS))
    elif status_lower in ("fail", "failed", "error"):
        item.setForeground(QColor(_CLR_FAIL))
    elif status_lower in ("warn", "warning", "skipped"):
        item.setForeground(QColor(_CLR_WARN))
    else:
        item.setForeground(QColor(_CLR_INFO))
    font = QFont()
    font.setBold(True)
    item.setFont(font)
    return item


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(_CLR_TEXT))
    return item


class _SummaryTab(QWidget):
    """Summary tab showing flow step results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Step", "Status", "Duration"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { alternate-background-color: #1a1a2e; }"
        )
        self._table.setShowGrid(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def update_results(self, steps: list[dict[str, str]]) -> None:
        self._table.setRowCount(0)
        for step in steps:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, _text_item(step.get("name", "")))
            self._table.setItem(row, 1, _status_item(step.get("status", "")))
            self._table.setItem(row, 2, _text_item(step.get("duration", "")))


class _TimingTab(QWidget):
    """Timing analysis placeholder tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._label = QLabel("Run STA to see timing results")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(f"color: {_CLR_DIM}; font-size: 14px;")
        layout.addWidget(self._label)

        # Placeholder table for future timing paths
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Path", "Slack", "Delay", "Frequency"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        layout.addWidget(self._table)
        self._table.setVisible(False)


class _CoverageTab(QWidget):
    """Coverage results placeholder tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        metrics = [
            ("Line Coverage", 0),
            ("Branch Coverage", 0),
            ("Toggle Coverage", 0),
            ("FSM Coverage", 0),
            ("Assertion Coverage", 0),
        ]

        self._bars: dict[str, QProgressBar] = {}
        for name, value in metrics:
            group = QGroupBox(name)
            group_layout = QHBoxLayout(group)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(value)
            bar.setFormat("%v%")
            group_layout.addWidget(bar)
            layout.addWidget(group)
            self._bars[name] = bar

        layout.addStretch()

    def set_coverage(self, name: str, value: int) -> None:
        bar = self._bars.get(name)
        if bar is not None:
            bar.setValue(max(0, min(100, value)))


class _SecurityTab(QWidget):
    """Security / crypto verification placeholder tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Check", "Status", "Details"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { alternate-background-color: #1a1a2e; }"
        )
        self._table.setShowGrid(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        # Populate with placeholder checks
        checks = [
            ("Constant-Time Verification", "Pending", "Run verification to check"),
            ("Side-Channel Resistance", "Pending", "Run analysis to check"),
            ("NIST Test Vectors", "Pending", "Run validation to check"),
            ("Key Isolation", "Pending", "Run formal check"),
            ("Fault Injection Resistance", "Pending", "Run analysis to check"),
        ]
        for check_name, status, details in checks:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, _text_item(check_name))
            self._table.setItem(row, 1, _status_item(status))
            self._table.setItem(row, 2, _text_item(details))


class ReportsPanel(QDockWidget):
    """Dock widget with tabbed reports: Summary, Timing, Coverage, Security."""

    def __init__(self, title: str = "Reports", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._tabs = QTabWidget()
        self._summary = _SummaryTab()
        self._timing = _TimingTab()
        self._coverage = _CoverageTab()
        self._security = _SecurityTab()

        self._tabs.addTab(self._summary, "Summary")
        self._tabs.addTab(self._timing, "Timing")
        self._tabs.addTab(self._coverage, "Coverage")
        self._tabs.addTab(self._security, "Security")

        self.setWidget(self._tabs)

    # ── Public API ─────────────────────────────────────────────────

    def update_results(self, flow_results: dict) -> None:
        """Populate the reports panel from flow results.

        Expected *flow_results* keys:
            - ``steps``: list of dicts with keys ``name``, ``status``, ``duration``
            - ``coverage``: dict mapping coverage metric name to int percentage
            - ``security``: list of dicts with keys ``check``, ``status``, ``details``
        """
        # Summary
        steps = flow_results.get("steps", [])
        self._summary.update_results(steps)

        # Coverage
        coverage = flow_results.get("coverage", {})
        for name, value in coverage.items():
            self._coverage.set_coverage(name, value)

    @property
    def summary(self) -> _SummaryTab:
        return self._summary

    @property
    def timing(self) -> _TimingTab:
        return self._timing

    @property
    def coverage(self) -> _CoverageTab:
        return self._coverage

    @property
    def security(self) -> _SecurityTab:
        return self._security
