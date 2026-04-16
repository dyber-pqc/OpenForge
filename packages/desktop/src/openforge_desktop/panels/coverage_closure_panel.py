"""Qt dock panel for vManager-style coverage closure tracking.

The :class:`CoverageClosurePanel` visualises a
:class:`openforge.verification.coverage_closure.CoverageClosureManager`:
total coverage card, per-metric progress bars, custom QPainter trend
chart, hole drill-down with right-click test suggestion, editable goals
table, ETA forecast page, and snapshot history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Palette:
    bg: str
    panel: str
    text: str
    subtle: str
    accent: str
    accent2: str
    good: str
    warn: str
    bad: str
    grid: str
    series: tuple[str, ...]


_DARK = _Palette(
    bg="#1e1e2e",
    panel="#181825",
    text="#cdd6f4",
    subtle="#9399b2",
    accent="#89b4fa",
    accent2="#f5c2e7",
    good="#a6e3a1",
    warn="#f9e2af",
    bad="#f38ba8",
    grid="#313244",
    series=("#89b4fa", "#f5c2e7", "#a6e3a1", "#fab387", "#f9e2af", "#94e2d5"),
)
_LIGHT = _Palette(
    bg="#eff1f5",
    panel="#e6e9ef",
    text="#4c4f69",
    subtle="#6c6f85",
    accent="#1e66f5",
    accent2="#ea76cb",
    good="#40a02b",
    warn="#df8e1d",
    bad="#d20f39",
    grid="#bcc0cc",
    series=("#1e66f5", "#ea76cb", "#40a02b", "#fe640b", "#df8e1d", "#179299"),
)


_METRIC_LABELS = {
    "line": "Line",
    "branch": "Branch",
    "toggle": "Toggle",
    "fsm": "FSM",
    "functional": "Functional",
    "assertion": "Assertion",
    "total": "Total",
}


# ---------------------------------------------------------------------------
# Custom trend chart widget
# ---------------------------------------------------------------------------


class _TrendChart(QWidget):
    """Multi-series line chart drawn with QPainter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._series: list[tuple[str, list[tuple[datetime, float]]]] = []
        self._palette: _Palette = _DARK

    def set_palette(self, p: _Palette) -> None:
        self._palette = p
        self.update()

    def clear(self) -> None:
        self._series.clear()
        self.update()

    def add_series(self, name: str, points: list[tuple[datetime, float]]) -> None:
        if points:
            self._series.append((name, list(points)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        p.fillRect(rect, QColor(self._palette.panel))

        margin_l = 50
        margin_b = 36
        margin_t = 24
        margin_r = 130
        plot = QRectF(
            margin_l,
            margin_t,
            max(rect.width() - margin_l - margin_r, 10),
            max(rect.height() - margin_t - margin_b, 10),
        )

        if not self._series:
            p.setPen(QColor(self._palette.subtle))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No coverage history yet")
            p.end()
            return

        all_pts = [pt for _, pts in self._series for pt in pts]
        t_min = min(t for t, _ in all_pts)
        t_max = max(t for t, _ in all_pts)
        if t_min == t_max:
            t_max = datetime.fromtimestamp(t_min.timestamp() + 1)
        v_min = 0.0
        v_max = 100.0

        # Grid
        grid_pen = QPen(QColor(self._palette.grid))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for i in range(6):
            y = plot.top() + plot.height() * i / 5
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            x = plot.left() + plot.width() * i / 5
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        p.setPen(QColor(self._palette.text))
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        for i in range(6):
            v = v_max - (v_max - v_min) * i / 5
            ypx = plot.top() + plot.height() * i / 5
            p.drawText(QRectF(0, ypx - 7, margin_l - 4, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{v:.0f}%")
        # X axis ticks
        span_s = (t_max - t_min).total_seconds() or 1.0
        for i in range(6):
            xpx = plot.left() + plot.width() * i / 5
            t = datetime.fromtimestamp(t_min.timestamp() + span_s * i / 5)
            p.drawText(QRectF(xpx - 40, plot.bottom() + 2, 80, 14),
                       Qt.AlignmentFlag.AlignCenter, t.strftime("%m-%d"))

        def to_px(t: datetime, v: float) -> QPointF:
            tx = (t.timestamp() - t_min.timestamp()) / span_s
            px = plot.left() + tx * plot.width()
            py = plot.bottom() - (v - v_min) / (v_max - v_min) * plot.height()
            return QPointF(px, py)

        # Series
        for idx, (name, pts) in enumerate(self._series):
            color = QColor(self._palette.series[idx % len(self._palette.series)])
            pen = QPen(color)
            pen.setWidthF(2.0)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(to_px(*pts[0]))
            for pt in pts[1:]:
                path.lineTo(to_px(*pt))
            p.drawPath(path)
            for pt in pts:
                pp = to_px(*pt)
                p.fillRect(QRectF(pp.x() - 2, pp.y() - 2, 4, 4), color)
            # Legend
            ly = plot.top() + 4 + idx * 16
            lx = plot.right() + 8
            p.fillRect(QRectF(lx, ly + 2, 14, 10), color)
            p.setPen(QColor(self._palette.text))
            p.drawText(QRectF(lx + 18, ly, 110, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.end()


# ---------------------------------------------------------------------------
# Goal editor dialog
# ---------------------------------------------------------------------------


class _GoalDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        name: str = "",
        metric: str = "line",
        target: float = 95.0,
        weight: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coverage Goal")
        form = QFormLayout(self)
        self.name_edit = QLineEdit(name)
        form.addRow("Name", self.name_edit)
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(list(_METRIC_LABELS))
        if metric in _METRIC_LABELS:
            self.metric_combo.setCurrentText(metric)
        form.addRow("Metric", self.metric_combo)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.0, 100.0)
        self.target_spin.setSuffix(" %")
        self.target_spin.setValue(target)
        form.addRow("Target", self.target_spin)
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(0.0, 10.0)
        self.weight_spin.setSingleStep(0.1)
        self.weight_spin.setValue(weight)
        form.addRow("Weight", self.weight_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class CoverageClosurePanel(QDockWidget):
    """vManager-style coverage closure dashboard."""

    test_run_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coverage Closure")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._manager: Any = None
        self._palette: _Palette = _DARK

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ---- Big summary card ----------------------------------------------
        self._summary_frame = QFrame()
        self._summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        sl = QHBoxLayout(self._summary_frame)
        self._total_label = QLabel("--%")
        f = self._total_label.font()
        f.setPointSize(36)
        f.setBold(True)
        self._total_label.setFont(f)
        sl.addWidget(self._total_label)
        right_box = QVBoxLayout()
        self._total_caption = QLabel("Total coverage")
        self._target_caption = QLabel("Target: -")
        right_box.addWidget(self._total_caption)
        right_box.addWidget(self._target_caption)
        right_box.addStretch(1)
        sl.addLayout(right_box, 1)
        layout.addWidget(self._summary_frame)

        # ---- Per-metric progress bars --------------------------------------
        self._metric_bars: dict[str, QProgressBar] = {}
        self._metric_value_labels: dict[str, QLabel] = {}
        metrics_box = QFrame()
        mlayout = QFormLayout(metrics_box)
        for key, label in _METRIC_LABELS.items():
            if key == "total":
                continue
            row = QHBoxLayout()
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            self._metric_bars[key] = bar
            row.addWidget(bar, 1)
            value = QLabel("--% / --%")
            value.setMinimumWidth(110)
            self._metric_value_labels[key] = value
            row.addWidget(value)
            wrap = QWidget()
            wrap.setLayout(row)
            mlayout.addRow(label, wrap)
        layout.addWidget(metrics_box)

        # ---- Tabs ----------------------------------------------------------
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_trend_tab(), "Trend")
        self._tabs.addTab(self._build_holes_tab(), "Holes")
        self._tabs.addTab(self._build_goals_tab(), "Goals")
        self._tabs.addTab(self._build_forecast_tab(), "Forecast")
        self._tabs.addTab(self._build_history_tab(), "History")
        layout.addWidget(self._tabs, 1)

        # ---- Bottom row ----------------------------------------------------
        bottom = QHBoxLayout()
        self._run_btn = QPushButton("Run Tests")
        self._run_btn.clicked.connect(self.test_run_requested.emit)
        bottom.addWidget(self._run_btn)
        self._eta_label = QLabel("ETA: -")
        bottom.addWidget(self._eta_label)
        bottom.addStretch(1)
        layout.addLayout(bottom)

        self._status = QStatusBar()
        layout.addWidget(self._status)

        self.setWidget(root)
        self.set_theme(True)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------
    def _build_trend_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        controls = QHBoxLayout()
        self._trend_metric = QComboBox()
        self._trend_metric.addItems(["all"] + list(_METRIC_LABELS))
        self._trend_metric.currentTextChanged.connect(self._refresh_trend)
        controls.addWidget(QLabel("Metric:"))
        controls.addWidget(self._trend_metric)
        self._trend_days = QComboBox()
        self._trend_days.addItems(["7", "14", "30", "60", "90", "365"])
        self._trend_days.setCurrentText("30")
        self._trend_days.currentTextChanged.connect(self._refresh_trend)
        controls.addWidget(QLabel("Days:"))
        controls.addWidget(self._trend_days)
        controls.addStretch(1)
        layout.addLayout(controls)
        self._trend_chart = _TrendChart()
        layout.addWidget(self._trend_chart, 1)
        return w

    def _build_holes_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._holes_tree = QTreeWidget()
        self._holes_tree.setHeaderLabels(["File", "Line", "Type", "Description"])
        self._holes_tree.header().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._holes_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._holes_tree.customContextMenuRequested.connect(self._on_hole_context_menu)
        self._holes_tree.itemSelectionChanged.connect(self._on_hole_selected)
        splitter.addWidget(self._holes_tree)
        self._hole_suggestion = QTextEdit()
        self._hole_suggestion.setReadOnly(True)
        self._hole_suggestion.setPlaceholderText(
            "Right-click a hole to generate a suggested test stub"
        )
        splitter.addWidget(self._hole_suggestion)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        return w

    def _build_goals_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self._goals_table = QTableWidget(0, 6)
        self._goals_table.setHorizontalHeaderLabels(
            ["Name", "Metric", "Target", "Weight", "Current", "Met?"]
        )
        self._goals_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._goals_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self._goals_table, 1)
        row = QHBoxLayout()
        self._add_goal_btn = QPushButton("Add Goal")
        self._add_goal_btn.clicked.connect(self._on_add_goal)
        row.addWidget(self._add_goal_btn)
        self._edit_goal_btn = QPushButton("Edit")
        self._edit_goal_btn.clicked.connect(self._on_edit_goal)
        row.addWidget(self._edit_goal_btn)
        self._del_goal_btn = QPushButton("Remove")
        self._del_goal_btn.clicked.connect(self._on_remove_goal)
        row.addWidget(self._del_goal_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return w

    def _build_forecast_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self._forecast_list = QListWidget()
        layout.addWidget(self._forecast_list, 1)
        self._forecast_help = QLabel(
            "Forecast assumes coverage continues to improve at the recent linear rate."
        )
        self._forecast_help.setWordWrap(True)
        layout.addWidget(self._forecast_help)
        return w

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self._history_table = QTableWidget(0, 8)
        self._history_table.setHorizontalHeaderLabels(
            ["Timestamp", "Tests", "Total", "Line", "Branch", "Toggle", "FSM", "Funct"]
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self._history_table)
        return w

    # ------------------------------------------------------------------
    # Manager binding
    # ------------------------------------------------------------------
    def update_from_manager(self, manager: Any) -> None:
        self._manager = manager
        latest = manager.latest() if hasattr(manager, "latest") else None
        if latest is None:
            self._total_label.setText("--%")
            self._target_caption.setText("Target: -")
            for key, bar in self._metric_bars.items():
                bar.setValue(0)
                self._metric_value_labels[key].setText("--% / --%")
            self._refresh_trend()
            self._refresh_goals()
            self._refresh_forecast()
            self._refresh_history()
            return

        self._total_label.setText(f"{latest.total_pct:.1f}%")
        # Pick a target: highest target across goals on "total" else 100.
        target = 100.0
        if hasattr(manager, "goals"):
            totals = [g.target_pct for g in manager.goals if g.metric_type == "total"]
            if totals:
                target = max(totals)
        self._target_caption.setText(f"Target: {target:.0f}%")
        self._color_total_label(latest.total_pct, target)

        per_metric = {
            "line": latest.line_pct,
            "branch": latest.branch_pct,
            "toggle": latest.toggle_pct,
            "fsm": latest.fsm_pct,
            "functional": latest.functional_pct,
            "assertion": latest.assertion_pct,
        }
        goal_targets = {g.metric_type: g.target_pct for g in getattr(manager, "goals", [])}
        for key, val in per_metric.items():
            bar = self._metric_bars[key]
            bar.setValue(int(val))
            t = goal_targets.get(key, 95.0)
            self._metric_value_labels[key].setText(f"{val:.1f}% / {t:.0f}%")
            self._color_bar(bar, val, t)

        self._refresh_trend()
        self._refresh_goals()
        self._refresh_forecast()
        self._refresh_history()
        self._refresh_holes(latest)

        forecast = manager.compute_closure_estimate() if hasattr(manager, "compute_closure_estimate") else {}
        unmet = [(name, info) for name, info in forecast.items() if not info.get("met")]
        if not unmet:
            self._eta_label.setText("ETA: all goals met")
        else:
            soonest = min((u[1].get("eta_days") or 9999, u[0]) for u in unmet)
            days, name = soonest
            self._eta_label.setText(f"ETA: '{name}' in ~{days} days")
        self._status.showMessage(f"Loaded {len(getattr(manager, 'snapshots', []))} snapshots")

    def _color_total_label(self, value: float, target: float) -> None:
        color = self._palette.bad
        if value >= target:
            color = self._palette.good
        elif value >= target * 0.85:
            color = self._palette.warn
        self._total_label.setStyleSheet(f"color: {color};")

    def _color_bar(self, bar: QProgressBar, value: float, target: float) -> None:
        color = self._palette.bad
        if value >= target:
            color = self._palette.good
        elif value >= target * 0.85:
            color = self._palette.warn
        bar.setStyleSheet(
            f"QProgressBar {{ background: {self._palette.panel}; "
            f"border: 1px solid {self._palette.grid}; }}"
            f"QProgressBar::chunk {{ background: {color}; }}"
        )

    # ------------------------------------------------------------------
    # Trend
    # ------------------------------------------------------------------
    def _refresh_trend(self) -> None:
        self._trend_chart.clear()
        if not self._manager or not hasattr(self._manager, "get_trend"):
            return
        days = int(self._trend_days.currentText())
        choice = self._trend_metric.currentText()
        if choice == "all":
            for metric, label in _METRIC_LABELS.items():
                pts = self._manager.get_trend(metric, days=days)
                if pts:
                    self._trend_chart.add_series(label, pts)
        else:
            pts = self._manager.get_trend(choice, days=days)
            self._trend_chart.add_series(_METRIC_LABELS.get(choice, choice), pts)

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------
    def _refresh_goals(self) -> None:
        self._goals_table.setRowCount(0)
        if not self._manager:
            return
        goals = getattr(self._manager, "goals", [])
        evaluated = self._manager.evaluate_goals() if hasattr(self._manager, "evaluate_goals") else {}
        for g in goals:
            row = self._goals_table.rowCount()
            self._goals_table.insertRow(row)
            self._goals_table.setItem(row, 0, QTableWidgetItem(g.name))
            self._goals_table.setItem(row, 1, QTableWidgetItem(g.metric_type))
            self._goals_table.setItem(row, 2, QTableWidgetItem(f"{g.target_pct:.1f}%"))
            self._goals_table.setItem(row, 3, QTableWidgetItem(f"{g.weight:.2f}"))
            self._goals_table.setItem(row, 4, QTableWidgetItem(f"{g.current_pct:.1f}%"))
            met = evaluated.get(g.name, g.current_pct >= g.target_pct)
            item = QTableWidgetItem("YES" if met else "NO")
            item.setForeground(QColor(self._palette.good if met else self._palette.bad))
            self._goals_table.setItem(row, 5, item)

    def _selected_goal_name(self) -> str | None:
        items = self._goals_table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        name_item = self._goals_table.item(row, 0)
        return name_item.text() if name_item else None

    def _on_add_goal(self) -> None:
        if not self._manager:
            return
        dlg = _GoalDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            from openforge.verification.coverage_closure import CoverageGoal
        except Exception as exc:  # pragma: no cover
            QMessageBox.warning(self, "Add goal", f"Cannot import CoverageGoal: {exc}")
            return
        goal = CoverageGoal(
            name=dlg.name_edit.text() or "goal",
            target_pct=dlg.target_spin.value(),
            weight=dlg.weight_spin.value(),
            metric_type=dlg.metric_combo.currentText(),
        )
        self._manager.add_goal(goal)
        self.update_from_manager(self._manager)

    def _on_edit_goal(self) -> None:
        if not self._manager:
            return
        name = self._selected_goal_name()
        if not name:
            return
        target = next((g for g in self._manager.goals if g.name == name), None)
        if target is None:
            return
        dlg = _GoalDialog(
            self,
            name=target.name,
            metric=target.metric_type,
            target=target.target_pct,
            weight=target.weight,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            from openforge.verification.coverage_closure import CoverageGoal
        except Exception:  # pragma: no cover
            return
        self._manager.remove_goal(target.name)
        self._manager.add_goal(
            CoverageGoal(
                name=dlg.name_edit.text() or target.name,
                target_pct=dlg.target_spin.value(),
                weight=dlg.weight_spin.value(),
                metric_type=dlg.metric_combo.currentText(),
            )
        )
        self.update_from_manager(self._manager)

    def _on_remove_goal(self) -> None:
        if not self._manager:
            return
        name = self._selected_goal_name()
        if not name:
            return
        self._manager.remove_goal(name)
        self.update_from_manager(self._manager)

    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------
    def _refresh_forecast(self) -> None:
        self._forecast_list.clear()
        if not self._manager or not hasattr(self._manager, "compute_closure_estimate"):
            return
        forecast = self._manager.compute_closure_estimate()
        for name, info in forecast.items():
            if info.get("met"):
                txt = f"[OK] {name}: met ({info['current']:.1f}% / {info['target']:.1f}%)"
                color = self._palette.good
            else:
                eta_days = info.get("eta_days")
                eta_date = info.get("eta_date") or "unknown"
                if eta_days is None:
                    txt = (
                        f"[??] {name}: not improving "
                        f"({info['current']:.1f}% -> {info['target']:.1f}%)"
                    )
                    color = self._palette.bad
                else:
                    txt = (
                        f"[..] {name}: ETA {eta_days} days ({eta_date}) "
                        f"current {info['current']:.1f}% target {info['target']:.1f}%"
                    )
                    color = self._palette.warn
            item = QListWidgetItem(txt)
            item.setForeground(QColor(color))
            self._forecast_list.addItem(item)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _refresh_history(self) -> None:
        self._history_table.setRowCount(0)
        if not self._manager:
            return
        snaps = getattr(self._manager, "snapshots", [])
        for s in reversed(snaps[-200:]):
            row = self._history_table.rowCount()
            self._history_table.insertRow(row)
            self._history_table.setItem(row, 0, QTableWidgetItem(s.timestamp.isoformat(timespec="seconds")))
            self._history_table.setItem(row, 1, QTableWidgetItem(str(s.test_count)))
            self._history_table.setItem(row, 2, QTableWidgetItem(f"{s.total_pct:.1f}%"))
            self._history_table.setItem(row, 3, QTableWidgetItem(f"{s.line_pct:.1f}%"))
            self._history_table.setItem(row, 4, QTableWidgetItem(f"{s.branch_pct:.1f}%"))
            self._history_table.setItem(row, 5, QTableWidgetItem(f"{s.toggle_pct:.1f}%"))
            self._history_table.setItem(row, 6, QTableWidgetItem(f"{s.fsm_pct:.1f}%"))
            self._history_table.setItem(row, 7, QTableWidgetItem(f"{s.functional_pct:.1f}%"))

    # ------------------------------------------------------------------
    # Holes
    # ------------------------------------------------------------------
    def _refresh_holes(self, latest_snapshot: Any) -> None:
        self._holes_tree.clear()
        self._hole_suggestion.clear()
        holes = latest_snapshot.coverage_holes if latest_snapshot else []
        # Group by file.
        by_file: dict[str, list[dict]] = {}
        for h in holes:
            f = h.get("file", "?")
            by_file.setdefault(f, []).append(h)
        for fname in sorted(by_file):
            parent = QTreeWidgetItem([fname, "", "", f"{len(by_file[fname])} holes"])
            for h in by_file[fname]:
                child = QTreeWidgetItem(
                    [
                        "",
                        str(h.get("line", "")),
                        str(h.get("type", "")),
                        str(h.get("description", "")),
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, h)
                parent.addChild(child)
            self._holes_tree.addTopLevelItem(parent)
        self._holes_tree.expandAll()

    def _on_hole_selected(self) -> None:
        items = self._holes_tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data and "suggestion" in data:
            self._hole_suggestion.setPlainText(data.get("suggestion") or "")

    def _on_hole_context_menu(self, pos) -> None:
        item = self._holes_tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        menu = QMenu(self)
        gen = QAction("Generate test for this hole", menu)
        gen.triggered.connect(lambda: self._generate_test_for_hole(data))
        menu.addAction(gen)
        menu.exec(self._holes_tree.viewport().mapToGlobal(pos))

    def _generate_test_for_hole(self, hole: dict) -> None:
        try:
            from openforge.verification.coverage_closure import (
                CoverageClosureManager,
                CoverageHole,
            )
        except Exception as exc:  # pragma: no cover
            self._hole_suggestion.setPlainText(f"Cannot import: {exc}")
            return
        ch = CoverageHole(
            file=str(hole.get("file", "?")),
            line=int(hole.get("line", 0)),
            type=str(hole.get("type", "uncovered_line")),
            description=str(hole.get("description", "")),
            suggestion=str(hole.get("suggestion", "")),
        )
        manager = self._manager or CoverageClosureManager(Path("."))
        suggestions = manager.suggest_tests_for_holes([ch], max_suggestions=1)
        if suggestions:
            self._hole_suggestion.setPlainText(suggestions[0])

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def set_theme(self, dark: bool) -> None:
        self._palette = _DARK if dark else _LIGHT
        self._trend_chart.set_palette(self._palette)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(self._palette.bg))
        pal.setColor(QPalette.ColorRole.Base, QColor(self._palette.panel))
        pal.setColor(QPalette.ColorRole.Text, QColor(self._palette.text))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(self._palette.text))
        self.setPalette(pal)
        self.setStyleSheet(
            f"""
            QDockWidget {{ background: {self._palette.bg}; color: {self._palette.text}; }}
            QWidget {{ background: {self._palette.bg}; color: {self._palette.text}; }}
            QFrame {{ background: {self._palette.panel}; border: 1px solid {self._palette.grid}; }}
            QLineEdit, QTreeWidget, QListWidget, QTableWidget, QComboBox, QDoubleSpinBox, QTextEdit {{
                background: {self._palette.panel};
                color: {self._palette.text};
                border: 1px solid {self._palette.grid};
                selection-background-color: {self._palette.accent};
            }}
            QPushButton {{
                background: {self._palette.panel};
                color: {self._palette.text};
                border: 1px solid {self._palette.grid};
                padding: 4px 10px;
            }}
            QPushButton:hover {{ background: {self._palette.grid}; }}
            QHeaderView::section {{
                background: {self._palette.panel};
                color: {self._palette.subtle};
                border: 1px solid {self._palette.grid};
                padding: 4px;
            }}
            QTabWidget::pane {{ border: 1px solid {self._palette.grid}; }}
            QTabBar::tab {{
                background: {self._palette.panel};
                color: {self._palette.subtle};
                padding: 6px 12px;
            }}
            QTabBar::tab:selected {{
                color: {self._palette.text};
                border-bottom: 2px solid {self._palette.accent};
            }}
            QStatusBar {{ background: {self._palette.panel}; color: {self._palette.subtle}; }}
            """
        )
        # Re-apply per-metric bar colors so they keep current/target.
        if self._manager and hasattr(self._manager, "latest"):
            latest = self._manager.latest()
            if latest is not None:
                self._color_total_label(latest.total_pct, 100.0)


__all__ = ["CoverageClosurePanel"]
