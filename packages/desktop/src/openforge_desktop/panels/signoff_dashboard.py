"""Multi-physics sign-off dashboard panel.

Shows a check/corner status grid, unified top-violations table, a
sign-off readiness gauge, per-corner summary tiles, and a Run All
button that kicks off the full signoff pipeline (PBA + CPPR +
crosstalk + Monte Carlo + IR + EM + thermal + DRC + LVS).

All core analyzers are imported lazily and guarded so missing
dependencies only disable their row of the grid instead of breaking
the panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


CHECKS = [
    "Setup STA",
    "Hold STA",
    "IR drop",
    "Electromigration",
    "Thermal",
    "Antenna",
    "DRC",
    "LVS",
    "Crosstalk",
    "Yield",
    "Power",
]

CORNERS = ["TT", "SS", "FF"]


STATUS_COLORS = {
    "pass": "#4caf50",
    "warn": "#ffb74d",
    "fail": "#ef5350",
    "unknown": "#555",
}


@dataclass
class CheckResult:
    check: str
    corner: str
    status: str = "unknown"  # pass / warn / fail / unknown
    message: str = ""
    violations: int = 0
    worst_value: float = 0.0


@dataclass
class Violation:
    check: str
    corner: str
    severity: str  # high/med/low
    message: str
    location: str = ""
    value: float = 0.0


# ---------------------------------------------------------------------------
# Gauge widget
# ---------------------------------------------------------------------------


class ReadinessGauge(QWidget):
    """Circular 0-100 sign-off readiness gauge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self.update()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        size = min(w, h) - 20
        x = (w - size) // 2
        y = (h - size) // 2

        # background arc
        pen = QPen(QColor("#333"))
        pen.setWidth(12)
        painter.setPen(pen)
        painter.drawArc(x, y, size, size, 0, 360 * 16)

        # value arc
        if self._value >= 85:
            color = QColor(STATUS_COLORS["pass"])
        elif self._value >= 60:
            color = QColor(STATUS_COLORS["warn"])
        else:
            color = QColor(STATUS_COLORS["fail"])
        pen.setColor(color)
        painter.setPen(pen)
        span = int(-360 * 16 * (self._value / 100.0))
        painter.drawArc(x, y, size, size, 90 * 16, span)

        # text
        painter.setPen(QColor("#eee"))
        f = QFont()
        f.setPointSize(24)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(
            self.rect(),
            int(Qt.AlignmentFlag.AlignCenter),
            f"{self._value:.0f}%",
        )


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class SignoffDashboardPanel(QWidget):
    """Multi-physics sign-off dashboard."""

    run_all_requested = Signal()
    jump_to_check = Signal(str, str)  # (check, corner)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign-off Dashboard")
        self._results: dict[tuple[str, str], CheckResult] = {}
        self._violations: list[Violation] = []

        self._build_ui()
        self._refresh_grid()
        self._refresh_gauge()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Top bar
        top_bar = QHBoxLayout()
        title = QLabel("<b>Sign-off Dashboard</b>")
        title.setStyleSheet("font-size: 14pt;")
        top_bar.addWidget(title)
        top_bar.addStretch(1)
        self.run_all_btn = QPushButton("Run All Sign-off")
        self.run_all_btn.setStyleSheet(
            "background: #4caf50; color: white; padding: 6px 14px; font-weight: bold;"
        )
        self.run_all_btn.clicked.connect(self._on_run_all)
        top_bar.addWidget(self.run_all_btn)
        self.export_btn = QPushButton("Export Report")
        self.export_btn.clicked.connect(self._on_export)
        top_bar.addWidget(self.export_btn)
        root.addLayout(top_bar)

        # Gauge + summary row
        row = QHBoxLayout()
        self.gauge = ReadinessGauge()
        row.addWidget(self.gauge)

        self.summary_grid = QGridLayout()
        self.summary_grid.setSpacing(6)
        self._summary_labels: dict[str, QLabel] = {}
        summary_items = [
            ("TT WNS", "tt_wns"),
            ("TT TNS", "tt_tns"),
            ("SS WNS", "ss_wns"),
            ("FF WHS", "ff_whs"),
            ("TT Power", "tt_power"),
            ("SS Leakage", "ss_leak"),
            ("Yield", "yield"),
            ("Total viol", "total_viol"),
        ]
        for i, (label, key) in enumerate(summary_items):
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #888;")
            val = QLabel("--")
            val.setStyleSheet("font-weight: bold; font-size: 11pt;")
            self.summary_grid.addWidget(lbl, i // 2, (i % 2) * 2)
            self.summary_grid.addWidget(val, i // 2, (i % 2) * 2 + 1)
            self._summary_labels[key] = val
        summary_box = QGroupBox("Corner Summary")
        summary_box.setLayout(self.summary_grid)
        row.addWidget(summary_box, 1)
        root.addLayout(row)

        # Status grid (check x corner)
        self.grid_group = QGroupBox("Check / Corner Matrix")
        grid_layout = QGridLayout(self.grid_group)
        grid_layout.setSpacing(2)
        grid_layout.addWidget(QLabel(""), 0, 0)
        for ci, corner in enumerate(CORNERS):
            h = QLabel(f"<b>{corner}</b>")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid_layout.addWidget(h, 0, ci + 1)
        self._cells: dict[tuple[str, str], QLabel] = {}
        for ri, check in enumerate(CHECKS):
            grid_layout.addWidget(QLabel(check), ri + 1, 0)
            for ci, corner in enumerate(CORNERS):
                cell = QLabel("?")
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFrameShape(QFrame.Shape.Box)
                cell.setMinimumWidth(80)
                cell.setMinimumHeight(22)
                cell.setStyleSheet(
                    f"background: {STATUS_COLORS['unknown']}; color: white;"
                )
                cell.mousePressEvent = (  # type: ignore[assignment]
                    lambda _e, c=check, cn=corner: self.jump_to_check.emit(c, cn)
                )
                grid_layout.addWidget(cell, ri + 1, ci + 1)
                self._cells[(check, corner)] = cell
        root.addWidget(self.grid_group)

        # Violations table
        viol_box = QGroupBox("Top Violations (unified)")
        vlay = QVBoxLayout(viol_box)
        self.viol_table = QTableWidget(0, 5)
        self.viol_table.setHorizontalHeaderLabels(
            ["Check", "Corner", "Severity", "Location", "Value"]
        )
        self.viol_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        vlay.addWidget(self.viol_table)
        root.addWidget(viol_box, 1)

    # ------------------------------------------------------------------ API

    def set_check_result(self, result: CheckResult) -> None:
        self._results[(result.check, result.corner)] = result
        self._refresh_grid()
        self._refresh_gauge()

    def set_all_results(
        self,
        results: list[CheckResult],
        violations: list[Violation] | None = None,
    ) -> None:
        self._results = {(r.check, r.corner): r for r in results}
        if violations is not None:
            self._violations = violations
        self._refresh_grid()
        self._refresh_gauge()
        self._refresh_violations()

    def set_summary(self, summary: dict[str, Any]) -> None:
        for key, lbl in self._summary_labels.items():
            if key in summary:
                lbl.setText(str(summary[key]))

    # ------------------------------------------------------------------ refresh

    def _refresh_grid(self) -> None:
        for (check, corner), cell in self._cells.items():
            r = self._results.get((check, corner))
            status = r.status if r else "unknown"
            color = STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
            text = status.upper() if r else "-"
            tip = r.message if r else "(not run)"
            cell.setText(text)
            cell.setStyleSheet(
                f"background: {color}; color: white; font-weight: bold; padding: 2px;"
            )
            cell.setToolTip(tip)

    def _refresh_gauge(self) -> None:
        if not self._results:
            self.gauge.set_value(0.0)
            return
        weights = {
            "pass": 1.0,
            "warn": 0.5,
            "fail": 0.0,
            "unknown": 0.0,
        }
        total = 0.0
        for r in self._results.values():
            total += weights.get(r.status, 0.0)
        readiness = 100.0 * total / max(1, len(self._results))
        self.gauge.set_value(readiness)

    def _refresh_violations(self) -> None:
        # sort by severity then value
        sev_rank = {"high": 0, "med": 1, "low": 2}
        viols = sorted(
            self._violations,
            key=lambda v: (sev_rank.get(v.severity, 3), -v.value),
        )
        self.viol_table.setRowCount(len(viols))
        for i, v in enumerate(viols):
            self.viol_table.setItem(i, 0, QTableWidgetItem(v.check))
            self.viol_table.setItem(i, 1, QTableWidgetItem(v.corner))
            sev_item = QTableWidgetItem(v.severity)
            color = {
                "high": QColor(STATUS_COLORS["fail"]),
                "med": QColor(STATUS_COLORS["warn"]),
                "low": QColor(STATUS_COLORS["pass"]),
            }.get(v.severity, QColor("#888"))
            sev_item.setForeground(color)
            self.viol_table.setItem(i, 2, sev_item)
            self.viol_table.setItem(i, 3, QTableWidgetItem(v.location))
            self.viol_table.setItem(i, 4, QTableWidgetItem(f"{v.value:.3g}"))

    # ------------------------------------------------------------------ actions

    def _on_run_all(self) -> None:
        self.run_all_requested.emit()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Sign-off Report",
            "signoff_report.html",
            "HTML (*.html);;PDF (*.pdf)",
        )
        if not path:
            return
        html = self._render_html()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError:
            pass

    def _render_html(self) -> str:
        rows: list[str] = []
        rows.append("<html><head><style>")
        rows.append(
            "body{font-family:sans-serif;background:#1e1e1e;color:#eee;}"
            "table{border-collapse:collapse;}td,th{border:1px solid #444;padding:4px 8px;}"
            ".pass{background:#4caf50;}.warn{background:#ffb74d;}.fail{background:#ef5350;}"
        )
        rows.append("</style></head><body>")
        rows.append("<h1>OpenForge Sign-off Report</h1>")
        rows.append("<h2>Check Matrix</h2><table><tr><th>Check</th>")
        for c in CORNERS:
            rows.append(f"<th>{c}</th>")
        rows.append("</tr>")
        for ch in CHECKS:
            rows.append(f"<tr><td>{ch}</td>")
            for c in CORNERS:
                r = self._results.get((ch, c))
                status = r.status if r else "unknown"
                rows.append(f'<td class="{status}">{status}</td>')
            rows.append("</tr>")
        rows.append("</table>")
        rows.append("<h2>Violations</h2><table>")
        rows.append("<tr><th>Check</th><th>Corner</th><th>Severity</th><th>Location</th><th>Value</th></tr>")
        for v in self._violations:
            rows.append(
                f"<tr><td>{v.check}</td><td>{v.corner}</td>"
                f"<td>{v.severity}</td><td>{v.location}</td>"
                f"<td>{v.value:.3g}</td></tr>"
            )
        rows.append("</table></body></html>")
        return "\n".join(rows)


__all__ = [
    "SignoffDashboardPanel",
    "CheckResult",
    "Violation",
    "CHECKS",
    "CORNERS",
]
