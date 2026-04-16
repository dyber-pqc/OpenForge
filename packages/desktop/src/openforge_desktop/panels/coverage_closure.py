"""Metric-driven verification dashboard (vManager replacement).

A coverage-closure dock that reads coverage data, displays a project-wide
"big donut" plus per-module breakdowns, identifies coverage holes,
visualises trend/burndown, and lets the user link tests to coverage goals.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Catppuccin Mocha
_BG = QColor("#1e1e2e")
_SURFACE = QColor("#313244")
_OVERLAY = QColor("#45475a")
_TEXT = QColor("#cdd6f4")
_SUBTEXT = QColor("#a6adc8")
_GREEN = QColor("#a6e3a1")
_YELLOW = QColor("#f9e2af")
_RED = QColor("#f38ba8")
_BLUE = QColor("#89b4fa")
_MAUVE = QColor("#cba6f7")
_PEACH = QColor("#fab387")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ModuleCoverage:
    name: str
    line: float = 0.0
    branch: float = 0.0
    toggle: float = 0.0
    fsm: float = 0.0
    functional: float = 0.0
    assertions: float = 0.0
    holes: list[tuple[str, int, str]] = field(default_factory=list)

    def overall(self) -> float:
        metrics = [self.line, self.branch, self.toggle, self.fsm,
                   self.functional, self.assertions]
        nonzero = [m for m in metrics if m > 0]
        if not nonzero:
            return 0.0
        return sum(nonzero) / len(nonzero)


@dataclass
class CoverageSnapshot:
    timestamp: datetime
    modules: list[ModuleCoverage]

    def overall(self) -> float:
        if not self.modules:
            return 0.0
        return sum(m.overall() for m in self.modules) / len(self.modules)


@dataclass
class TestPlanGoal:
    name: str
    tests: list[str] = field(default_factory=list)
    target: float = 100.0
    delivered: float = 0.0
    status: str = "open"  # open / passing / blocked / done


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------


class DonutChart(QWidget):
    """Single big donut showing overall coverage %."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value: float = 0.0
        self._title: str = "Coverage"
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_value(self, v: float) -> None:
        self._value = max(0.0, min(100.0, v))
        self.update()

    def set_title(self, t: str) -> None:
        self._title = t
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG)
        side = min(self.width(), self.height()) - 24
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        # Background ring
        p.setPen(QPen(_OVERLAY, side * 0.12))
        p.drawArc(rect.adjusted(side * 0.06, side * 0.06, -side * 0.06, -side * 0.06),
                  0, 360 * 16)
        # Foreground arc
        if self._value >= 80:
            color = _GREEN
        elif self._value >= 50:
            color = _YELLOW
        else:
            color = _RED
        pen = QPen(color, side * 0.12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        span = int(-self._value / 100 * 360 * 16)
        p.drawArc(
            rect.adjusted(side * 0.06, side * 0.06, -side * 0.06, -side * 0.06),
            90 * 16, span,
        )
        # Center text
        p.setPen(_TEXT)
        f = QFont("Inter", int(side * 0.18), QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._value:.1f}%")
        f2 = QFont("Inter", 9)
        p.setFont(f2)
        p.setPen(_SUBTEXT)
        p.drawText(
            QRectF(rect.x(), rect.bottom() - 18, rect.width(), 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self._title,
        )
        p.end()


class TrendChart(QWidget):
    """Sparkline-style trend chart for coverage over recent runs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: list[float] = []
        self._title: str = "Trend"
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_series(self, data: list[float]) -> None:
        self._series = list(data)
        self.update()

    def set_title(self, t: str) -> None:
        self._title = t
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG)
        margin = 24
        plot = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        p.setPen(_SUBTEXT)
        p.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        p.drawText(QPointF(margin, margin - 6), self._title)
        p.setPen(QPen(_OVERLAY, 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()),
                   QPointF(plot.right(), plot.bottom()))
        for i in range(1, 5):
            y = plot.top() + plot.height() * i / 5
            p.setPen(QPen(_OVERLAY, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        if len(self._series) < 2:
            p.end()
            return
        path = QPainterPath()
        max_v = 100.0
        for i, v in enumerate(self._series):
            x = plot.left() + plot.width() * i / max(len(self._series) - 1, 1)
            y = plot.bottom() - plot.height() * (v / max_v)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(QPen(_BLUE, 2))
        p.drawPath(path)
        # Fill underneath
        fill = QPainterPath(path)
        fill.lineTo(plot.right(), plot.bottom())
        fill.lineTo(plot.left(), plot.bottom())
        fill.closeSubpath()
        p.fillPath(fill, QColor(137, 180, 250, 60))
        p.end()


class BurndownChart(QWidget):
    """Predicted closure burndown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actual: list[float] = []
        self._target: list[float] = []
        self.setMinimumHeight(120)

    def set_data(self, actual: list[float], target: list[float]) -> None:
        self._actual = list(actual)
        self._target = list(target)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG)
        margin = 24
        plot = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        p.setPen(_SUBTEXT)
        p.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        p.drawText(QPointF(margin, margin - 6), "Burndown")
        p.setPen(QPen(_OVERLAY, 1))
        p.drawRect(plot)
        self._draw_series(p, plot, self._target, _OVERLAY, dashed=True)
        self._draw_series(p, plot, self._actual, _MAUVE)
        p.end()

    @staticmethod
    def _draw_series(p: QPainter, plot: QRectF, data: list[float],
                     color: QColor, dashed: bool = False) -> None:
        if len(data) < 2:
            return
        max_v = max(data) if data else 1.0
        if max_v == 0:
            max_v = 1.0
        pen = QPen(color, 2)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        path = QPainterPath()
        for i, v in enumerate(data):
            x = plot.left() + plot.width() * i / max(len(data) - 1, 1)
            y = plot.bottom() - plot.height() * (v / max_v)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.drawPath(path)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class CoverageClosurePanel(QDockWidget):
    """Coverage closure dashboard - track verification progress."""

    test_added = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coverage Closure")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._snapshots: list[CoverageSnapshot] = []
        self._goals: list[TestPlanGoal] = []
        self._modules: list[ModuleCoverage] = []

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Toolbar
        tb = QToolBar()
        tb.setMovable(False)
        tb.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.addItems(["(default)"])
        tb.addWidget(self.project_combo)
        tb.addSeparator()
        tb.addAction(QAction("Refresh", self, triggered=self._on_refresh))
        tb.addAction(QAction("Load JSON", self, triggered=self._on_load_json))
        tb.addAction(QAction("Demo data", self, triggered=self._load_demo))
        tb.addSeparator()
        tb.addAction(QAction("Export report", self, triggered=self._on_export_report))
        layout.addWidget(tb)

        # Main splitter: dashboard | sidebar
        main_split = QSplitter(Qt.Orientation.Horizontal, root)

        # ----- Dashboard tabs -----
        tabs = QTabWidget()

        # Overview tab
        overview = QWidget()
        ov = QVBoxLayout(overview)

        top_row = QHBoxLayout()
        self.donut = DonutChart()
        self.donut.set_title("Overall coverage")
        top_row.addWidget(self.donut, 1)
        self.trend = TrendChart()
        self.trend.set_title("Coverage % over recent runs")
        top_row.addWidget(self.trend, 2)
        ov.addLayout(top_row)

        breakdown_group = QGroupBox("Module breakdown")
        bg = QVBoxLayout(breakdown_group)
        self.breakdown_table = QTableWidget(0, 8)
        self.breakdown_table.setHorizontalHeaderLabels(
            ["Module", "Line%", "Branch%", "Toggle%", "FSM%",
             "Functional%", "Assertions%", "Overall%"]
        )
        self.breakdown_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.breakdown_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.breakdown_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        bg.addWidget(self.breakdown_table)
        ov.addWidget(breakdown_group, 1)

        tabs.addTab(overview, "Overview")

        # Holes tab
        holes_widget = QWidget()
        hl = QVBoxLayout(holes_widget)
        hl.addWidget(QLabel("Uncovered code locations"))
        self.holes_tree = QTreeWidget()
        self.holes_tree.setHeaderLabels(["Module", "File", "Line", "Reason"])
        self.holes_tree.setRootIsDecorated(False)
        hl.addWidget(self.holes_tree)
        tabs.addTab(holes_widget, "Holes")

        # Test plan tab
        plan_widget = QWidget()
        pl = QVBoxLayout(plan_widget)
        pl.addWidget(QLabel("Test plan goals"))
        self.plan_table = QTableWidget(0, 4)
        self.plan_table.setHorizontalHeaderLabels(["Goal", "Tests", "Status", "Coverage delivered"])
        self.plan_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        pl.addWidget(self.plan_table)

        plan_buttons = QHBoxLayout()
        add_goal = QPushButton("Add goal")
        add_goal.clicked.connect(self._on_add_goal)
        plan_buttons.addWidget(add_goal)
        plan_buttons.addStretch(1)
        pl.addLayout(plan_buttons)
        tabs.addTab(plan_widget, "Test plan")

        main_split.addWidget(tabs)

        # ----- Sidebar -----
        sidebar = QWidget()
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 8)

        eta_group = QGroupBox("Closure forecast")
        eg = QVBoxLayout(eta_group)
        self.eta_label = QLabel("ETA: --")
        self.eta_label.setStyleSheet("font-size: 16pt; color: #cba6f7;")
        eg.addWidget(self.eta_label)
        self.eta_detail = QLabel("Awaiting trend data")
        eg.addWidget(self.eta_detail)
        sl.addWidget(eta_group)

        burn_group = QGroupBox("Burndown")
        bgl = QVBoxLayout(burn_group)
        self.burndown = BurndownChart()
        bgl.addWidget(self.burndown)
        sl.addWidget(burn_group)

        contrib_group = QGroupBox("Top contributors")
        cgl = QVBoxLayout(contrib_group)
        self.contributors = QListWidget()
        cgl.addWidget(self.contributors)
        sl.addWidget(contrib_group, 1)

        main_split.addWidget(sidebar)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)
        layout.addWidget(main_split, 1)

        self.status = QStatusBar(root)
        self.status.showMessage("Ready")
        layout.addWidget(self.status)

        self.setWidget(root)
        self._apply_theme()

    # ------------------------------------------------------------------
    # Public data API
    # ------------------------------------------------------------------
    def set_modules(self, modules: list[ModuleCoverage]) -> None:
        self._modules = list(modules)
        self._refresh_breakdown()
        self._refresh_overall()
        self._refresh_holes()
        self._refresh_contributors()

    def add_snapshot(self, snapshot: CoverageSnapshot) -> None:
        self._snapshots.append(snapshot)
        self._refresh_trend()
        self._refresh_eta()
        self._refresh_burndown()

    def set_goals(self, goals: list[TestPlanGoal]) -> None:
        self._goals = list(goals)
        self._refresh_plan()

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------
    def _refresh_overall(self) -> None:
        if not self._modules:
            self.donut.set_value(0.0)
            return
        overall = sum(m.overall() for m in self._modules) / len(self._modules)
        self.donut.set_value(overall)

    def _refresh_breakdown(self) -> None:
        self.breakdown_table.setRowCount(len(self._modules))
        for r, m in enumerate(self._modules):
            cells = [
                m.name,
                f"{m.line:.1f}",
                f"{m.branch:.1f}",
                f"{m.toggle:.1f}",
                f"{m.fsm:.1f}",
                f"{m.functional:.1f}",
                f"{m.assertions:.1f}",
                f"{m.overall():.1f}",
            ]
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if c >= 1:
                    val = float(txt) if txt else 0.0
                    if val >= 80:
                        item.setForeground(_GREEN)
                    elif val >= 50:
                        item.setForeground(_YELLOW)
                    else:
                        item.setForeground(_RED)
                self.breakdown_table.setItem(r, c, item)

    def _refresh_holes(self) -> None:
        self.holes_tree.clear()
        for m in self._modules:
            for file, line, reason in m.holes:
                node = QTreeWidgetItem([m.name, file, str(line), reason])
                self.holes_tree.addTopLevelItem(node)

    def _refresh_trend(self) -> None:
        series = [s.overall() for s in self._snapshots]
        self.trend.set_series(series)

    def _refresh_eta(self) -> None:
        if len(self._snapshots) < 2:
            self.eta_label.setText("ETA: --")
            self.eta_detail.setText("Need at least 2 snapshots")
            return
        first = self._snapshots[0].overall()
        last = self._snapshots[-1].overall()
        days = (self._snapshots[-1].timestamp - self._snapshots[0].timestamp).days or 1
        rate = (last - first) / days
        if rate <= 0:
            self.eta_label.setText("ETA: stalled")
            self.eta_detail.setText("Coverage is not increasing")
            return
        remaining = max(0.0, 100.0 - last)
        days_to_close = remaining / rate
        eta_date = (self._snapshots[-1].timestamp + timedelta(days=days_to_close)).date()
        self.eta_label.setText(f"ETA: {eta_date.isoformat()}")
        self.eta_detail.setText(
            f"Rate {rate:.2f} %/day · {remaining:.1f}% remaining"
        )

    def _refresh_burndown(self) -> None:
        if not self._snapshots:
            return
        actual = [100.0 - s.overall() for s in self._snapshots]
        n = len(actual)
        target = [actual[0] * (1 - i / max(n - 1, 1)) for i in range(n)] if n >= 2 else list(actual)
        self.burndown.set_data(actual, target)

    def _refresh_contributors(self) -> None:
        self.contributors.clear()
        sorted_mods = sorted(self._modules, key=lambda m: m.overall(), reverse=True)
        for m in sorted_mods[:8]:
            item = QListWidgetItem(f"{m.name}  —  {m.overall():.1f}%")
            self.contributors.addItem(item)

    def _refresh_plan(self) -> None:
        self.plan_table.setRowCount(len(self._goals))
        for r, g in enumerate(self._goals):
            self.plan_table.setItem(r, 0, QTableWidgetItem(g.name))
            self.plan_table.setItem(r, 1, QTableWidgetItem(", ".join(g.tests)))
            self.plan_table.setItem(r, 2, QTableWidgetItem(g.status))
            self.plan_table.setItem(r, 3, QTableWidgetItem(f"{g.delivered:.1f}%"))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_refresh(self) -> None:
        self.refresh_requested.emit()
        self.status.showMessage("Refresh requested")

    def _on_load_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load coverage", "", "JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as e:
            self.status.showMessage(f"Load failed: {e}")
            return
        modules: list[ModuleCoverage] = []
        for entry in data.get("modules", []):
            modules.append(
                ModuleCoverage(
                    name=entry.get("name", "?"),
                    line=float(entry.get("line", 0)),
                    branch=float(entry.get("branch", 0)),
                    toggle=float(entry.get("toggle", 0)),
                    fsm=float(entry.get("fsm", 0)),
                    functional=float(entry.get("functional", 0)),
                    assertions=float(entry.get("assertions", 0)),
                    holes=[tuple(h) for h in entry.get("holes", [])],
                )
            )
        self.set_modules(modules)
        self.add_snapshot(CoverageSnapshot(timestamp=datetime.now(), modules=modules))
        self.status.showMessage(f"Loaded {len(modules)} modules")

    def _load_demo(self) -> None:
        modules = [
            ModuleCoverage("cpu_core", line=92.5, branch=88.0, toggle=85.0,
                           fsm=100.0, functional=78.0, assertions=95.0,
                           holes=[("cpu_core.v", 142, "branch not taken"),
                                  ("cpu_core.v", 233, "uncovered FSM transition")]),
            ModuleCoverage("alu", line=98.0, branch=96.0, toggle=92.0,
                           fsm=100.0, functional=88.0, assertions=100.0),
            ModuleCoverage("decoder", line=84.0, branch=72.0, toggle=78.0,
                           fsm=90.0, functional=68.0, assertions=80.0,
                           holes=[("decoder.v", 56, "missing illegal-op test")]),
            ModuleCoverage("regfile", line=100.0, branch=100.0, toggle=98.0,
                           fsm=0.0, functional=95.0, assertions=100.0),
            ModuleCoverage("uart", line=70.0, branch=58.0, toggle=64.0,
                           fsm=80.0, functional=50.0, assertions=72.0,
                           holes=[("uart.v", 89, "parity error path"),
                                  ("uart.v", 113, "break detect")]),
        ]
        self.set_modules(modules)
        # Fake history of 8 snapshots increasing toward closure
        base_time = datetime.now() - timedelta(days=14)
        for i in range(8):
            scaled = []
            for m in modules:
                scaled.append(
                    ModuleCoverage(
                        name=m.name,
                        line=m.line * (0.6 + 0.05 * i),
                        branch=m.branch * (0.55 + 0.06 * i),
                        toggle=m.toggle * (0.6 + 0.05 * i),
                        fsm=m.fsm * (0.7 + 0.04 * i),
                        functional=m.functional * (0.5 + 0.07 * i),
                        assertions=m.assertions * (0.65 + 0.05 * i),
                    )
                )
            self.add_snapshot(
                CoverageSnapshot(timestamp=base_time + timedelta(days=i * 2), modules=scaled)
            )
        self.set_goals(
            [
                TestPlanGoal("Boot sequence", ["test_boot", "test_reset"], 100.0, 92.0, "passing"),
                TestPlanGoal("ALU corner cases", ["test_alu_overflow"], 100.0, 88.0, "passing"),
                TestPlanGoal("UART parity", ["test_uart_parity"], 100.0, 50.0, "open"),
                TestPlanGoal("Illegal opcodes", ["test_illegal_op"], 100.0, 70.0, "blocked"),
            ]
        )
        self.status.showMessage("Loaded demo coverage data")

    def _on_export_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", "coverage_report.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                ["module", "line", "branch", "toggle", "fsm",
                 "functional", "assertions", "overall"]
            )
            for m in self._modules:
                w.writerow(
                    [
                        m.name, f"{m.line:.2f}", f"{m.branch:.2f}",
                        f"{m.toggle:.2f}", f"{m.fsm:.2f}",
                        f"{m.functional:.2f}", f"{m.assertions:.2f}",
                        f"{m.overall():.2f}",
                    ]
                )
        self.status.showMessage(f"Exported {path}")

    def _on_add_goal(self) -> None:
        goal = TestPlanGoal(name=f"goal_{len(self._goals) + 1}", tests=[], target=100.0)
        self._goals.append(goal)
        self._refresh_plan()
        self.test_added.emit(goal.name)

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QDockWidget { background: #1e1e2e; color: #cdd6f4; }
            QWidget { color: #cdd6f4; }
            QToolBar { background: #181825; border: none; spacing: 4px; }
            QGroupBox { border: 1px solid #45475a; border-radius: 6px;
                        margin-top: 12px; padding: 8px; background: #181825; }
            QGroupBox::title { left: 10px; padding: 0 4px; color: #cdd6f4; }
            QTableWidget, QTreeWidget, QListWidget {
                background: #181825; border: 1px solid #313244;
                gridline-color: #313244; color: #cdd6f4;
            }
            QHeaderView::section {
                background: #313244; color: #cdd6f4;
                border: none; padding: 4px;
            }
            QTabWidget::pane { border: 1px solid #313244; background: #1e1e2e; }
            QTabBar::tab { background: #313244; color: #cdd6f4;
                           padding: 6px 12px; border: 1px solid #45475a; }
            QTabBar::tab:selected { background: #cba6f7; color: #1e1e2e; }
            QPushButton { background: #45475a; color: #cdd6f4;
                          border: 1px solid #585b70; border-radius: 4px;
                          padding: 4px 10px; }
            QPushButton:hover { background: #585b70; }
            QStatusBar { background: #181825; color: #a6adc8; }
            QLabel { color: #cdd6f4; }
            QComboBox { background: #313244; color: #cdd6f4;
                        border: 1px solid #45475a; border-radius: 4px;
                        padding: 3px; }
            """
        )
