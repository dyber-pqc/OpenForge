"""Multi-Vt optimization panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from pathlib import Path

try:
    from openforge.physical.eco import EcoScript
    from openforge.physical.multi_vt import (
        MultiVtLibrary,
        MultiVtOptimizer,
        VtClass,
    )
    from openforge.physical.sta_parser import StaReport
except Exception:  # pragma: no cover
    EcoScript = None  # type: ignore[assignment]
    MultiVtLibrary = None  # type: ignore[assignment]
    MultiVtOptimizer = None  # type: ignore[assignment]
    VtClass = None  # type: ignore[assignment]
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
_MAUVE = "#cba6f7"


_VT_COLOR = {
    "ulvt": _RED,
    "lvt": _YELLOW,
    "rvt": _GREEN,
    "hvt": _BLUE,
}


class _VtBarChart(QWidget):
    """Simple horizontal bar chart for Vt distribution."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts: dict[str, int] = {}
        self.setMinimumHeight(80)

    def set_counts(self, counts: dict[str, int]) -> None:
        self._counts = counts
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        if not self._counts:
            painter.setPen(QColor(_SUBTLE))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No Vt data")
            return
        total = max(1, sum(self._counts.values()))
        bar_h = max(12, (rect.height() - 8) // max(1, len(self._counts)))
        y = rect.top()
        for vt, count in self._counts.items():
            color = QColor(_VT_COLOR.get(vt.lower() if isinstance(vt, str) else str(vt), _SUBTLE))
            frac = count / total
            width = int(rect.width() * frac)
            painter.fillRect(rect.left(), y, width, bar_h - 4, color)
            painter.setPen(QColor(_TEXT))
            painter.drawText(
                rect.left() + 4,
                y,
                rect.width(),
                bar_h - 4,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{vt}: {count} ({frac*100:.1f}%)",
            )
            y += bar_h


class MultiVtPanel(QDockWidget):
    """Dock that runs multi-Vt optimization and shows a diff."""

    script_ready = Signal(object)  # EcoScript

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Multi-Vt Optimizer", parent)
        self.setObjectName("multi_vt_dock")
        self._dark = True
        self._optimizer: MultiVtOptimizer | None = None  # type: ignore[valid-type]
        self._library: MultiVtLibrary | None = None  # type: ignore[valid-type]
        self._last_script: EcoScript | None = None  # type: ignore[valid-type]

        root = QWidget(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Toolbar
        self._toolbar = QToolBar("Multi-Vt", root)
        self._act_leakage = self._toolbar.addAction("Reduce Leakage")
        self._act_speed = self._toolbar.addAction("Recover Speed")
        self._toolbar.addSeparator()
        self._act_apply = self._toolbar.addAction("Apply (emit ECO)")
        outer.addWidget(self._toolbar)

        self._act_leakage.triggered.connect(self._run_leakage)
        self._act_speed.triggered.connect(self._run_speed)
        self._act_apply.triggered.connect(self._emit_script)

        # Splitter: left = distribution + controls, right = diff
        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        left = QWidget(splitter)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Vt distribution"))
        self._chart = _VtBarChart(left)
        ll.addWidget(self._chart)

        ll.addWidget(QLabel("Leakage heatmap (region)"))
        self._heatmap = QTableWidget(4, 4, left)
        self._heatmap.horizontalHeader().setVisible(False)
        self._heatmap.verticalHeader().setVisible(False)
        self._heatmap.setFixedHeight(150)
        ll.addWidget(self._heatmap)

        form_holder = QWidget(left)
        form = QFormLayout(form_holder)
        self._target_leakage = QSlider(Qt.Orientation.Horizontal)
        self._target_leakage.setRange(0, 1000)
        self._target_leakage.setValue(100)
        self._target_leakage_label = QLabel("100 pW")
        self._target_leakage.valueChanged.connect(
            lambda v: self._target_leakage_label.setText(f"{v} pW")
        )
        leak_row = QHBoxLayout()
        leak_row.addWidget(self._target_leakage)
        leak_row.addWidget(self._target_leakage_label)
        leak_holder = QWidget()
        leak_holder.setLayout(leak_row)
        form.addRow("Target leakage", leak_holder)

        self._target_speed = QSlider(Qt.Orientation.Horizontal)
        self._target_speed.setRange(-500, 500)
        self._target_speed.setValue(0)
        self._target_speed_label = QLabel("0.000 ns")
        self._target_speed.valueChanged.connect(
            lambda v: self._target_speed_label.setText(f"{v/1000.0:+.3f} ns")
        )
        speed_row = QHBoxLayout()
        speed_row.addWidget(self._target_speed)
        speed_row.addWidget(self._target_speed_label)
        speed_holder = QWidget()
        speed_holder.setLayout(speed_row)
        form.addRow("Target slack", speed_holder)

        ll.addWidget(form_holder)
        splitter.addWidget(left)

        # Right: diff view
        right = QWidget(splitter)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Cells before/after"))
        self._diff_table = QTableWidget(0, 5, right)
        self._diff_table.setHorizontalHeaderLabels(
            ["Instance", "Before", "After", "Slack impact", "Leakage impact"]
        )
        self._diff_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        rl.addWidget(self._diff_table)
        self._summary = QLabel("No optimization run yet.")
        self._summary.setStyleSheet(f"color: {_SUBTLE};")
        rl.addWidget(self._summary)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

        self.setWidget(root)
        self._apply_style()

    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_style()

    def load(
        self,
        lib: MultiVtLibrary,
        def_path: Path,
        sta_report: StaReport,
    ) -> None:
        self._library = lib
        if MultiVtOptimizer is not None:
            self._optimizer = MultiVtOptimizer(lib, def_path, sta_report)
            dist = self._optimizer.report_distribution()
            self._chart.set_counts({k.value: v for k, v in dist.items()})
            self._fill_heatmap_stub()

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
            QTableWidget {{
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

    def _fill_heatmap_stub(self) -> None:
        # Simple gradient stand-in for a real heatmap.
        import random

        rng = random.Random(0xC0FFEE)
        for row in range(self._heatmap.rowCount()):
            for col in range(self._heatmap.columnCount()):
                val = rng.random()
                cell = QTableWidgetItem(f"{val*10:.1f} pW")
                r = int(255 * val)
                cell.setBackground(QBrush(QColor(r, 40, 120 - int(80 * val))))
                cell.setForeground(QBrush(QColor(_TEXT)))
                self._heatmap.setItem(row, col, cell)

    def _run_leakage(self) -> None:
        if self._optimizer is None:
            return
        target = float(self._target_leakage.value())
        script = self._optimizer.reduce_leakage(target)
        self._last_script = script
        self._fill_diff(script)
        self._summary.setText(
            "Leakage run: swapped %d cells, est. savings %.1f pW"
            % (
                script.metadata.get("cells_swapped", 0),
                script.metadata.get("savings_pw", 0.0),
            )
        )

    def _run_speed(self) -> None:
        if self._optimizer is None:
            return
        target_ns = self._target_speed.value() / 1000.0
        script = self._optimizer.increase_speed(target_ns)
        self._last_script = script
        self._fill_diff(script)
        self._summary.setText(
            "Speed run: swapped %d cells, added leakage %.1f pW"
            % (
                script.metadata.get("cells_swapped", 0),
                script.metadata.get("added_leakage_pw", 0.0),
            )
        )

    def _fill_diff(self, script) -> None:
        self._diff_table.setRowCount(0)
        for row, cmd in enumerate(script.commands):
            self._diff_table.insertRow(row)
            self._diff_table.setItem(
                row, 0, QTableWidgetItem(cmd.target_inst or "-")
            )
            # Try to look up the original cell from the optimizer map
            before = "-"
            if self._optimizer is not None and cmd.target_inst:
                before = self._optimizer._instance_to_cell.get(  # noqa: SLF001
                    cmd.target_inst, "-"
                )
            self._diff_table.setItem(row, 1, QTableWidgetItem(before))
            self._diff_table.setItem(
                row, 2, QTableWidgetItem(cmd.new_cell or "-")
            )
            slack_impact = "-"
            if cmd.slack_before_ns is not None and cmd.slack_after_ns is not None:
                slack_impact = f"{cmd.slack_after_ns - cmd.slack_before_ns:+.3f}"
            self._diff_table.setItem(row, 3, QTableWidgetItem(slack_impact))
            self._diff_table.setItem(
                row, 4, QTableWidgetItem(cmd.notes or "")
            )

    def _emit_script(self) -> None:
        if self._last_script is None:
            return
        self.script_ready.emit(self._last_script)


__all__ = ["MultiVtPanel"]
