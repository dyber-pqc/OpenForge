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
    QScrollArea,
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


def _scrollable(widget: QWidget) -> QScrollArea:
    """Wrap a widget in a scroll area so tab content never clips."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    return scroll


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
    """Timing analysis results tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Summary metrics row
        metrics_layout = QHBoxLayout()
        self._wns_label = QLabel("WNS: --")
        self._wns_label.setStyleSheet(f"color: {_CLR_DIM}; font-size: 13px; font-weight: bold; padding: 4px 8px;")
        self._tns_label = QLabel("TNS: --")
        self._tns_label.setStyleSheet(f"color: {_CLR_DIM}; font-size: 13px; font-weight: bold; padding: 4px 8px;")
        self._fmax_label = QLabel("Fmax: --")
        self._fmax_label.setStyleSheet(f"color: {_CLR_DIM}; font-size: 13px; font-weight: bold; padding: 4px 8px;")
        metrics_layout.addWidget(self._wns_label)
        metrics_layout.addWidget(self._tns_label)
        metrics_layout.addWidget(self._fmax_label)
        metrics_layout.addStretch()
        layout.addLayout(metrics_layout)

        self._label = QLabel("Run STA to see timing results")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(f"color: {_CLR_DIM}; font-size: 14px;")
        layout.addWidget(self._label)

        # Timing paths table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Path", "Slack (ns)", "Delay (ns)", "Endpoint"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("QTableWidget { alternate-background-color: #1a1a2e; }")
        self._table.setShowGrid(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)
        self._table.setVisible(False)

    def update_timing(self, wns: float, tns: float, fmax: float = 0.0,
                      paths: list[dict[str, str]] | None = None) -> None:
        """Update timing results."""
        wns_color = _CLR_PASS if wns >= 0 else _CLR_FAIL
        tns_color = _CLR_PASS if tns >= 0 else _CLR_FAIL
        self._wns_label.setText(f"WNS: {wns:.3f} ns")
        self._wns_label.setStyleSheet(f"color: {wns_color}; font-size: 13px; font-weight: bold; padding: 4px 8px;")
        self._tns_label.setText(f"TNS: {tns:.3f} ns")
        self._tns_label.setStyleSheet(f"color: {tns_color}; font-size: 13px; font-weight: bold; padding: 4px 8px;")
        if fmax > 0:
            self._fmax_label.setText(f"Fmax: {fmax:.1f} MHz")
            self._fmax_label.setStyleSheet(f"color: {_CLR_INFO}; font-size: 13px; font-weight: bold; padding: 4px 8px;")

        self._label.setVisible(False)
        self._table.setVisible(True)

        if paths:
            self._table.setRowCount(0)
            for p in paths:
                row = self._table.rowCount()
                self._table.insertRow(row)
                self._table.setItem(row, 0, _text_item(p.get("path", "")))
                slack = p.get("slack", "")
                slack_item = QTableWidgetItem(slack)
                try:
                    slack_item.setForeground(QColor(_CLR_PASS if float(slack) >= 0 else _CLR_FAIL))
                except (ValueError, TypeError):
                    slack_item.setForeground(QColor(_CLR_DIM))
                font = QFont()
                font.setBold(True)
                slack_item.setFont(font)
                self._table.setItem(row, 1, slack_item)
                self._table.setItem(row, 2, _text_item(p.get("delay", "")))
                self._table.setItem(row, 3, _text_item(p.get("endpoint", "")))


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
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._summary = _SummaryTab()
        self._timing = _TimingTab()
        self._coverage = _CoverageTab()
        self._security = _SecurityTab()

        self._tabs.addTab(_scrollable(self._summary), "Summary")
        self._tabs.addTab(_scrollable(self._timing), "Timing")
        self._tabs.addTab(_scrollable(self._coverage), "Coverage")
        self._tabs.addTab(_scrollable(self._security), "Security")

        self.setWidget(self._tabs)

    # ── Public API ─────────────────────────────────────────────────

    def update_results(self, flow_results: dict) -> None:
        """Populate the reports panel from flow results.

        Expected *flow_results* keys:
            - ``steps``: list of dicts with keys ``name``, ``status``, ``duration``
            - ``coverage``: dict mapping coverage metric name to int percentage
            - ``security``: list of dicts with keys ``check``, ``status``, ``details``
            - ``timing``: dict with ``wns``, ``tns``, ``fmax``, ``paths``
        """
        # Summary
        steps = flow_results.get("steps", [])
        self._summary.update_results(steps)

        # Timing
        timing = flow_results.get("timing", {})
        if timing:
            self._timing.update_timing(
                wns=timing.get("wns", 0.0),
                tns=timing.get("tns", 0.0),
                fmax=timing.get("fmax", 0.0),
                paths=timing.get("paths"),
            )

        # Coverage
        coverage = flow_results.get("coverage", {})
        for name, value in coverage.items():
            self._coverage.set_coverage(name, value)

    def add_flow_step(self, name: str, status: str, duration: str = "") -> None:
        """Add a single flow step result to the summary tab."""
        table = self._summary._table
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, _text_item(name))
        table.setItem(row, 1, _status_item(status))
        table.setItem(row, 2, _text_item(duration))

    def update_timing_results(self, wns: float, tns: float, fmax: float = 0.0,
                               paths: list[dict[str, str]] | None = None) -> None:
        """Convenience method to update just the timing tab."""
        self._timing.update_timing(wns, tns, fmax, paths)

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
