"""SPICE simulator GUI panel - Virtuoso ADE replacement.

A QDockWidget that lets the user select a netlist, choose a SPICE analysis
type (op / dc / tran / ac / noise), configure analysis parameters, choose
which nets to save, run ngspice, and view the resulting waveforms in a
custom QPainter-based plot widget. Results may also be exported to CSV.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Plot widget
# ---------------------------------------------------------------------------

# Catppuccin Mocha palette
_BG = QColor("#1e1e2e")
_SURFACE = QColor("#313244")
_TEXT = QColor("#cdd6f4")
_SUBTEXT = QColor("#a6adc8")
_MAUVE = QColor("#cba6f7")
_BLUE = QColor("#89b4fa")
_GREEN = QColor("#a6e3a1")
_RED = QColor("#f38ba8")
_PEACH = QColor("#fab387")
_YELLOW = QColor("#f9e2af")
_TEAL = QColor("#94e2d5")
_PINK = QColor("#f5c2e7")

_TRACE_COLORS = [_MAUVE, _BLUE, _GREEN, _PEACH, _YELLOW, _TEAL, _PINK, _RED]


@dataclass
class Trace:
    name: str
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    color: QColor = field(default_factory=lambda: _MAUVE)
    visible: bool = True


class WaveformPlot(QWidget):
    """Lightweight QPainter-based waveform viewer.

    Designed for SPICE-style traces (one X axis, many Y traces). Supports
    zoom-to-fit, mouse hover crosshair, log/linear toggle on Y, and
    optional gridlines.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._traces: list[Trace] = []
        self._x_label: str = "time"
        self._y_label: str = "value"
        self._title: str = ""
        self._log_y: bool = False
        self._log_x: bool = False
        self._show_grid: bool = True
        self._x_min: float = 0.0
        self._x_max: float = 1.0
        self._y_min: float = 0.0
        self._y_max: float = 1.0
        self._cursor: QPointF | None = None
        self._plot_rect: QRectF = QRectF()
        # Zoom/pan state: view window in data coordinates. None = auto.
        self._view_x: tuple[float, float] | None = None
        self._view_y: tuple[float, float] | None = None
        self._pan_anchor: QPointF | None = None
        self._pan_view: tuple[float, float, float, float] | None = None
        self._legend_hitboxes: list[tuple[QRectF, int]] = []

    # -- API ---------------------------------------------------------------
    def clear(self) -> None:
        self._traces.clear()
        self._view_x = None
        self._view_y = None
        self.update()

    def set_data(
        self,
        signals: dict[str, list[tuple[float, float]]],
        x_label: str = "Time (s)",
        y_label: str = "Voltage (V)",
        log_x: bool = False,
        log_y: bool = False,
    ) -> None:
        """Replace all traces with ``signals`` (name -> list[(x, y)])."""
        self._traces.clear()
        for i, (name, pts) in enumerate(signals.items()):
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            color = _TRACE_COLORS[i % len(_TRACE_COLORS)]
            self._traces.append(Trace(name=name, x=xs, y=ys, color=color))
        self._x_label = x_label
        self._y_label = y_label
        self._log_x = log_x
        self._log_y = log_y
        self._view_x = None
        self._view_y = None
        self._recompute_extents()
        self.update()

    def add_signal(
        self,
        name: str,
        points: list[tuple[float, float]],
        color: str | None = None,
    ) -> None:
        col = QColor(color) if color else _TRACE_COLORS[len(self._traces) % len(_TRACE_COLORS)]
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        self._traces.append(Trace(name=name, x=xs, y=ys, color=col))
        self._recompute_extents()
        self.update()

    def remove_signal(self, name: str) -> None:
        self._traces = [t for t in self._traces if t.name != name]
        self._recompute_extents()
        self.update()

    def set_x_log(self, on: bool) -> None:
        self._log_x = on
        self.update()

    def set_y_log(self, on: bool) -> None:
        self._log_y = on
        self.update()

    def auto_scale(self) -> None:
        self._view_x = None
        self._view_y = None
        self._recompute_extents()
        self.update()

    def export_png(self, path) -> None:
        pm = QPixmap(self.size())
        pm.fill(_BG)
        self.render(pm)
        pm.save(str(path), "PNG")

    def add_trace(self, name: str, x: list[float], y: list[float]) -> None:
        color = _TRACE_COLORS[len(self._traces) % len(_TRACE_COLORS)]
        self._traces.append(Trace(name=name, x=list(x), y=list(y), color=color))
        self._recompute_extents()
        self.update()

    def set_axis_labels(self, x_label: str, y_label: str) -> None:
        self._x_label = x_label
        self._y_label = y_label
        self.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_log_y(self, on: bool) -> None:
        self._log_y = on
        self.update()

    def set_log_x(self, on: bool) -> None:
        self._log_x = on
        self.update()

    def visible_traces(self) -> list[Trace]:
        return [t for t in self._traces if t.visible]

    def trace_by_name(self, name: str) -> Trace | None:
        for t in self._traces:
            if t.name == name:
                return t
        return None

    # -- Internals ---------------------------------------------------------
    def _recompute_extents(self) -> None:
        xs: list[float] = []
        ys: list[float] = []
        for t in self.visible_traces():
            xs.extend(t.x)
            ys.extend(t.y)
        if not xs or not ys:
            self._x_min, self._x_max = 0.0, 1.0
            self._y_min, self._y_max = 0.0, 1.0
            return
        self._x_min, self._x_max = min(xs), max(xs)
        self._y_min, self._y_max = min(ys), max(ys)
        if self._x_max == self._x_min:
            self._x_max = self._x_min + 1.0
        if self._y_max == self._y_min:
            self._y_max = self._y_min + 1.0
        # Add 5% margin
        dy = (self._y_max - self._y_min) * 0.05
        self._y_min -= dy
        self._y_max += dy

    def _view_bounds(self) -> tuple[float, float, float, float]:
        x_min, x_max = self._view_x if self._view_x else (self._x_min, self._x_max)
        y_min, y_max = self._view_y if self._view_y else (self._y_min, self._y_max)
        if x_max == x_min:
            x_max = x_min + 1.0
        if y_max == y_min:
            y_max = y_min + 1.0
        return x_min, x_max, y_min, y_max

    def _data_to_pix(self, x: float, y: float, plot_rect: QRectF) -> QPointF:
        x_min, x_max, y_min, y_max = self._view_bounds()
        if self._log_x and x > 0 and x_min > 0 and x_max > 0:
            xn = (math.log10(x) - math.log10(x_min)) / max(
                math.log10(x_max) - math.log10(x_min), 1e-30
            )
        else:
            xn = (x - x_min) / max(x_max - x_min, 1e-30)
        if self._log_y and y > 0 and y_min > 0 and y_max > 0:
            yn = (math.log10(y) - math.log10(y_min)) / max(
                math.log10(y_max) - math.log10(y_min), 1e-30
            )
        else:
            yn = (y - y_min) / max(y_max - y_min, 1e-30)
        px = plot_rect.left() + xn * plot_rect.width()
        py = plot_rect.bottom() - yn * plot_rect.height()
        return QPointF(px, py)

    def _pix_to_data(self, px: float, py: float) -> tuple[float, float]:
        plot = self._plot_rect
        if plot.width() <= 0 or plot.height() <= 0:
            return 0.0, 0.0
        x_min, x_max, y_min, y_max = self._view_bounds()
        xn = (px - plot.left()) / plot.width()
        yn = (plot.bottom() - py) / plot.height()
        if self._log_x and x_min > 0 and x_max > 0:
            x = 10 ** (math.log10(x_min) + xn * (math.log10(x_max) - math.log10(x_min)))
        else:
            x = x_min + xn * (x_max - x_min)
        if self._log_y and y_min > 0 and y_max > 0:
            y = 10 ** (math.log10(y_min) + yn * (math.log10(y_max) - math.log10(y_min)))
        else:
            y = y_min + yn * (y_max - y_min)
        return x, y

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, _BG)

        margin_left = 56
        margin_right = 16
        margin_top = 28 if self._title else 12
        margin_bottom = 36
        plot = QRectF(
            margin_left,
            margin_top,
            max(10, rect.width() - margin_left - margin_right),
            max(10, rect.height() - margin_top - margin_bottom),
        )
        self._plot_rect = plot
        x_min, x_max, y_min, y_max = self._view_bounds()

        # Title
        if self._title:
            painter.setPen(_TEXT)
            painter.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            painter.drawText(plot.left(), 18, self._title)

        # Frame
        painter.setPen(QPen(_SUBTEXT, 1))
        painter.drawRect(plot)

        # Grid (minor + major)
        if self._show_grid:
            painter.setPen(QPen(QColor("#262637"), 1, Qt.PenStyle.DotLine))
            for i in range(1, 20):
                x = plot.left() + plot.width() * i / 20.0
                painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
                y = plot.top() + plot.height() * i / 20.0
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QPen(_SURFACE, 1, Qt.PenStyle.SolidLine))
            for i in range(1, 5):
                x = plot.left() + plot.width() * i / 5.0
                painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
                y = plot.top() + plot.height() * i / 5.0
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        # Axis ticks/labels
        painter.setPen(_SUBTEXT)
        painter.setFont(QFont("Inter", 8))
        for i in range(6):
            xv = x_min + (x_max - x_min) * i / 5
            yv = y_min + (y_max - y_min) * i / 5
            xp = plot.left() + plot.width() * i / 5
            yp = plot.bottom() - plot.height() * i / 5
            painter.drawText(QPointF(xp - 18, plot.bottom() + 14), _fmt_eng(xv))
            painter.drawText(QPointF(4, yp + 4), _fmt_eng(yv))

        # Axis titles
        painter.drawText(int(plot.center().x() - 20), int(rect.height() - 4), self._x_label)
        painter.save()
        painter.translate(12, plot.center().y())
        painter.rotate(-90)
        painter.drawText(0, 0, self._y_label)
        painter.restore()

        # Traces (clipped to plot area)
        painter.save()
        painter.setClipRect(plot)
        for t in self.visible_traces():
            if not t.x or not t.y:
                continue
            painter.setPen(QPen(t.color, 1.6))
            path = QPainterPath()
            first = True
            for x, y in zip(t.x, t.y, strict=False):
                if self._log_x and x <= 0:
                    first = True
                    continue
                if self._log_y and y <= 0:
                    first = True
                    continue
                p = self._data_to_pix(x, y, plot)
                if first:
                    path.moveTo(p)
                    first = False
                else:
                    path.lineTo(p)
            painter.drawPath(path)
        painter.restore()

        # Legend (clickable hitboxes)
        painter.setFont(QFont("Inter", 8))
        legend_y = int(plot.top() + 4)
        legend_x = int(plot.right() - 140)
        self._legend_hitboxes = []
        for idx, t in enumerate(self._traces):
            hit = QRectF(legend_x - 4, legend_y, 140, 14)
            self._legend_hitboxes.append((hit, idx))
            pen_color = t.color if t.visible else _SURFACE
            painter.setPen(QPen(pen_color, 2))
            painter.drawLine(legend_x, legend_y + 7, legend_x + 16, legend_y + 7)
            painter.setPen(_TEXT if t.visible else _SUBTEXT)
            painter.drawText(legend_x + 22, legend_y + 11, t.name)
            legend_y += 14

        # Crosshair + readout
        if self._cursor and plot.contains(self._cursor):
            painter.setPen(QPen(_PEACH, 1, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(self._cursor.x(), plot.top()),
                QPointF(self._cursor.x(), plot.bottom()),
            )
            painter.drawLine(
                QPointF(plot.left(), self._cursor.y()),
                QPointF(plot.right(), self._cursor.y()),
            )
            dx, dy = self._pix_to_data(self._cursor.x(), self._cursor.y())
            painter.setPen(_PEACH)
            painter.setFont(QFont("Inter", 8))
            painter.drawText(
                int(self._cursor.x() + 6),
                int(self._cursor.y() - 6),
                f"{_fmt_eng(dx)}, {_fmt_eng(dy)}",
            )

        painter.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = QPointF(event.position().x(), event.position().y())
        self._cursor = pos
        if self._pan_anchor is not None and self._pan_view is not None:
            plot = self._plot_rect
            if plot.width() > 0 and plot.height() > 0:
                x_min, x_max, y_min, y_max = self._pan_view
                dx = (pos.x() - self._pan_anchor.x()) / plot.width() * (x_max - x_min)
                dy = (pos.y() - self._pan_anchor.y()) / plot.height() * (y_max - y_min)
                self._view_x = (x_min - dx, x_max - dx)
                self._view_y = (y_min + dy, y_max + dy)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = QPointF(event.position().x(), event.position().y())
            self._pan_view = self._view_bounds()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = QPointF(event.position().x(), event.position().y())
            for rect, idx in self._legend_hitboxes:
                if rect.contains(pos):
                    self._traces[idx].visible = not self._traces[idx].visible
                    self.update()
                    return

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = None
            self._pan_view = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        plot = self._plot_rect
        if plot.width() <= 0 or plot.height() <= 0:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 0.85 if delta > 0 else 1.18
        pos = event.position()
        cx, cy = self._pix_to_data(pos.x(), pos.y())
        x_min, x_max, y_min, y_max = self._view_bounds()
        self._view_x = (cx - (cx - x_min) * factor, cx + (x_max - cx) * factor)
        self._view_y = (cy - (cy - y_min) * factor, cy + (y_max - cy) * factor)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.auto_scale()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._cursor = None
        self.update()


# Alias for task spec API name.
_SpicePlot = WaveformPlot


def _fmt_eng(x: float) -> str:
    if x == 0:
        return "0"
    abs_x = abs(x)
    units = [
        (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"),
        (1.0, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n"),
        (1e-12, "p"), (1e-15, "f"),
    ]
    for scale, suffix in units:
        if abs_x >= scale:
            return f"{x / scale:.3g}{suffix}"
    return f"{x:.3g}"


# ---------------------------------------------------------------------------
# Analysis param widgets
# ---------------------------------------------------------------------------


class _AnalysisOpForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.addRow(QLabel("Operating point analysis takes no parameters."))

    def params(self) -> dict[str, Any]:
        return {}


class _AnalysisDcForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.source = QLineEdit("V1")
        self.start = QDoubleSpinBox()
        self.start.setRange(-1000, 1000)
        self.start.setValue(0.0)
        self.stop = QDoubleSpinBox()
        self.stop.setRange(-1000, 1000)
        self.stop.setValue(5.0)
        self.step = QDoubleSpinBox()
        self.step.setRange(0.0001, 1000)
        self.step.setValue(0.1)
        self.step.setDecimals(4)
        layout.addRow("Source:", self.source)
        layout.addRow("Start (V):", self.start)
        layout.addRow("Stop (V):", self.stop)
        layout.addRow("Step (V):", self.step)

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source.text().strip(),
            "start": self.start.value(),
            "stop": self.stop.value(),
            "step": self.step.value(),
        }


class _AnalysisTranForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.tstop = QLineEdit("1m")
        self.tstep = QLineEdit("1u")
        layout.addRow("Stop time:", self.tstop)
        layout.addRow("Step:", self.tstep)

    def params(self) -> dict[str, Any]:
        return {
            "tstop": _parse_eng(self.tstop.text()),
            "tstep": _parse_eng(self.tstep.text()),
        }


class _AnalysisAcForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.fstart = QLineEdit("1")
        self.fstop = QLineEdit("1G")
        self.npoints = QSpinBox()
        self.npoints.setRange(1, 1000)
        self.npoints.setValue(10)
        self.variation = QComboBox()
        self.variation.addItems(["dec", "oct", "lin"])
        layout.addRow("F start (Hz):", self.fstart)
        layout.addRow("F stop (Hz):", self.fstop)
        layout.addRow("Points/decade:", self.npoints)
        layout.addRow("Variation:", self.variation)

    def params(self) -> dict[str, Any]:
        return {
            "fstart": _parse_eng(self.fstart.text()),
            "fstop": _parse_eng(self.fstop.text()),
            "npoints": self.npoints.value(),
            "variation": self.variation.currentText(),
        }


class _AnalysisNoiseForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.output = QLineEdit("out")
        self.source = QLineEdit("V1")
        self.fstart = QLineEdit("1")
        self.fstop = QLineEdit("1G")
        self.pts = QSpinBox()
        self.pts.setRange(1, 1000)
        self.pts.setValue(10)
        layout.addRow("Output node:", self.output)
        layout.addRow("Input source:", self.source)
        layout.addRow("F start:", self.fstart)
        layout.addRow("F stop:", self.fstop)
        layout.addRow("Points/dec:", self.pts)

    def params(self) -> dict[str, Any]:
        return {
            "output": self.output.text(),
            "src": self.source.text(),
            "fstart": _parse_eng(self.fstart.text()),
            "fstop": _parse_eng(self.fstop.text()),
            "pts": self.pts.value(),
            "variation": "dec",
        }


_EXAMPLE_NETLISTS: dict[str, str] = {
    "RC Low-Pass": (
        "* RC Low-Pass Filter\n"
        "V1 in 0 PULSE(0 1.8 0 1n 1n 5n 10n)\n"
        "R1 in out 1k\n"
        "C1 out 0 1p\n"
        ".tran 0.1n 50n\n"
        ".end\n"
    ),
    "CMOS Inverter": (
        "* CMOS Inverter\n"
        "V1 in 0 PULSE(0 1.8 5n 0.1n 0.1n 5n 10n)\n"
        "Vdd vdd 0 1.8\n"
        ".model nm nmos vto=0.4\n"
        ".model pm pmos vto=-0.4\n"
        "M1 out in 0 0 nm w=2u l=0.13u\n"
        "M2 out in vdd vdd pm w=4u l=0.13u\n"
        ".tran 0.1n 30n\n"
        ".end\n"
    ),
    "Op-Amp Non-Inverting": (
        "* Op-amp non-inverting amplifier\n"
        "V1 in 0 SIN(0 0.1 1k)\n"
        "Vdd vdd 0 5\n"
        "Vss vss 0 -5\n"
        "R1 inv 0 1k\n"
        "R2 inv out 9k\n"
        "X1 in inv vdd vss out opamp\n"
        ".subckt opamp vp vn vp- vn- out\n"
        "E1 out 0 vp vn 1e6\n"
        ".ends\n"
        ".tran 1u 5m\n"
        ".end\n"
    ),
}


def _parse_eng(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    suffixes = {
        "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
        "k": 1e3, "K": 1e3, "meg": 1e6, "g": 1e9, "G": 1e9, "t": 1e12,
    }
    low = s.lower()
    if low.endswith("meg"):
        return float(low[:-3]) * 1e6
    last = s[-1]
    if last in suffixes:
        try:
            return float(s[:-1]) * suffixes[last]
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class SpiceSimulatorPanel(QDockWidget):
    """SPICE simulation control panel (Virtuoso ADE replacement)."""

    simulation_started = Signal(str)
    simulation_finished = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SPICE Simulator")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._netlist_path: Path | None = None
        self._last_results: dict[str, Any] = {}

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QToolBar(root)
        toolbar.setMovable(False)
        toolbar.addAction(QAction("Open", self, triggered=self._on_open_netlist))
        toolbar.addAction(QAction("Reload", self, triggered=self._on_reload))
        toolbar.addAction(QAction("Load Example", self, triggered=self._on_load_example))
        toolbar.addSeparator()
        toolbar.addAction(QAction("Run", self, triggered=self._on_run))
        toolbar.addAction(QAction("Stop", self, triggered=self._on_stop))
        toolbar.addSeparator()
        toolbar.addAction(QAction("Reset Zoom", self, triggered=self._on_reset_zoom))
        toolbar.addAction(QAction("Log X", self, triggered=self._on_toggle_log_x))
        toolbar.addAction(QAction("Log Y", self, triggered=self._on_toggle_log_y))
        toolbar.addSeparator()
        toolbar.addAction(QAction("Export CSV", self, triggered=self._on_export_csv))
        toolbar.addAction(QAction("Export PNG", self, triggered=self._on_save_plot))
        layout.addWidget(toolbar)

        # Top row: netlist + analysis selector
        top_row = QHBoxLayout()
        self.netlist_edit = QLineEdit()
        self.netlist_edit.setPlaceholderText("No netlist loaded")
        self.netlist_edit.setReadOnly(True)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._on_open_netlist)
        top_row.addWidget(QLabel("Netlist:"))
        top_row.addWidget(self.netlist_edit, 1)
        top_row.addWidget(browse)
        layout.addLayout(top_row)

        analysis_row = QHBoxLayout()
        self.analysis_combo = QComboBox()
        self.analysis_combo.addItems(["op", "dc", "tran", "ac", "noise"])
        self.analysis_combo.currentIndexChanged.connect(self._on_analysis_changed)
        analysis_row.addWidget(QLabel("Analysis:"))
        analysis_row.addWidget(self.analysis_combo)
        analysis_row.addStretch(1)
        layout.addLayout(analysis_row)

        # Splitter: params + saves on top, plot on bottom
        splitter = QSplitter(Qt.Orientation.Vertical, root)

        upper = QWidget(splitter)
        upper_layout = QHBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)

        params_group = QGroupBox("Analysis parameters", upper)
        pg_layout = QVBoxLayout(params_group)
        self.param_stack = QStackedWidget(params_group)
        self._op_form = _AnalysisOpForm()
        self._dc_form = _AnalysisDcForm()
        self._tran_form = _AnalysisTranForm()
        self._ac_form = _AnalysisAcForm()
        self._noise_form = _AnalysisNoiseForm()
        self.param_stack.addWidget(self._op_form)
        self.param_stack.addWidget(self._dc_form)
        self.param_stack.addWidget(self._tran_form)
        self.param_stack.addWidget(self._ac_form)
        self.param_stack.addWidget(self._noise_form)
        pg_layout.addWidget(self.param_stack)
        upper_layout.addWidget(params_group, 1)

        signals_group = QGroupBox("Save signals", upper)
        sg_layout = QVBoxLayout(signals_group)
        self.signal_edit = QLineEdit()
        self.signal_edit.setPlaceholderText("v(out)")
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._on_add_signal)
        rm_btn = QPushButton("Remove")
        rm_btn.clicked.connect(self._on_remove_signal)
        sg_buttons = QHBoxLayout()
        sg_buttons.addWidget(self.signal_edit)
        sg_buttons.addWidget(add_btn)
        sg_buttons.addWidget(rm_btn)
        self.signals_list = QListWidget()
        self.signals_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        sg_layout.addLayout(sg_buttons)
        sg_layout.addWidget(self.signals_list, 1)
        upper_layout.addWidget(signals_group, 1)

        splitter.addWidget(upper)

        # Plot area
        plot_tabs = QTabWidget(splitter)
        self.plot = WaveformPlot()
        self.plot.set_axis_labels("time (s)", "value")
        plot_tabs.addTab(self.plot, "Waveform")

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "QTextEdit { background: #181825; color: #cdd6f4; "
            "font-family: 'JetBrains Mono', monospace; font-size: 10pt; }"
        )
        plot_tabs.addTab(self.log_view, "Log")
        splitter.addWidget(plot_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.status = QStatusBar(root)
        self.status.showMessage("Ready")
        layout.addWidget(self.status)

        self.setWidget(root)
        self._apply_theme()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_open_netlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open SPICE netlist",
            "",
            "SPICE files (*.cir *.sp *.spice *.net);;All files (*)",
        )
        if path:
            self._netlist_path = Path(path)
            self.netlist_edit.setText(path)
            self.status.showMessage(f"Loaded {Path(path).name}")
            self._populate_signals_from_netlist()

    def _on_reload(self) -> None:
        if not self._netlist_path:
            return
        self.status.showMessage(f"Reloaded {self._netlist_path.name}")
        self._populate_signals_from_netlist()

    def _populate_signals_from_netlist(self) -> None:
        if not self._netlist_path or not self._netlist_path.exists():
            return
        nets: set[str] = set()
        try:
            text = self._netlist_path.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("*") or stripped.startswith("."):
                    continue
                tokens = stripped.split()
                # Heuristic: tokens[1:n] are nodes for common devices.
                if tokens and tokens[0][0].upper() in "RCLVID":
                    for tok in tokens[1:3]:
                        if not tok.replace(".", "").replace("-", "").isdigit():
                            nets.add(tok)
        except OSError:
            return
        for n in sorted(nets):
            if n != "0":
                self._add_signal_str(f"v({n})")

    def _on_analysis_changed(self, idx: int) -> None:
        self.param_stack.setCurrentIndex(idx)
        labels = {
            0: ("nodes", "voltage (V)"),
            1: ("sweep", "voltage (V)"),
            2: ("time (s)", "value"),
            3: ("frequency (Hz)", "magnitude"),
            4: ("frequency (Hz)", "noise"),
        }
        x, y = labels.get(idx, ("x", "y"))
        self.plot.set_axis_labels(x, y)
        if idx in (3, 4):
            self.plot.set_log_x(True)
            self.plot.set_log_y(True)
        else:
            self.plot.set_log_x(False)
            self.plot.set_log_y(False)

    def _on_add_signal(self) -> None:
        text = self.signal_edit.text().strip()
        if text:
            self._add_signal_str(text)
            self.signal_edit.clear()

    def _add_signal_str(self, text: str) -> None:
        for i in range(self.signals_list.count()):
            if self.signals_list.item(i).text() == text:
                return
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.signals_list.addItem(item)

    def _on_remove_signal(self) -> None:
        for item in self.signals_list.selectedItems():
            self.signals_list.takeItem(self.signals_list.row(item))

    def _save_signals(self) -> list[str]:
        out: list[str] = []
        for i in range(self.signals_list.count()):
            item = self.signals_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def _on_run(self) -> None:
        if not self._netlist_path:
            QMessageBox.warning(self, "No netlist", "Please open a SPICE netlist first.")
            return
        analysis = self.analysis_combo.currentText()
        params = self._current_params()
        self.simulation_started.emit(analysis)
        self.status.showMessage(f"Running {analysis} on {self._netlist_path.name}...")
        self.log_view.append(f"=> ngspice {analysis} {params}")
        try:
            results = self._invoke_ngspice(analysis, params)
        except Exception as e:
            self.log_view.append(f"ERROR: {e}")
            self.status.showMessage(f"Failed: {e}")
            self.simulation_finished.emit(False)
            return
        self._last_results = results
        self._populate_plot(analysis, results)
        self.status.showMessage(f"Done ({analysis})")
        self.simulation_finished.emit(True)

    def _on_stop(self) -> None:
        self.status.showMessage("Stop requested (no active simulation)")

    def _on_reset_zoom(self) -> None:
        self.plot.auto_scale()

    def _on_toggle_log_x(self) -> None:
        self.plot.set_x_log(not self.plot._log_x)

    def _on_toggle_log_y(self) -> None:
        self.plot.set_y_log(not self.plot._log_y)

    def _on_load_example(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        names = list(_EXAMPLE_NETLISTS.keys())
        name, ok = QInputDialog.getItem(
            self, "Load Example", "Choose example netlist:", names, 0, False
        )
        if not ok or not name:
            return
        import tempfile

        text = _EXAMPLE_NETLISTS[name]
        tmp = Path(tempfile.gettempdir()) / f"openforge_example_{name.replace(' ', '_')}.cir"
        tmp.write_text(text, encoding="utf-8")
        self._netlist_path = tmp
        self.netlist_edit.setText(str(tmp))
        self.status.showMessage(f"Loaded example: {name}")
        self.signals_list.clear()
        self._populate_signals_from_netlist()

    def _current_params(self) -> dict[str, Any]:
        forms: list[Any] = [
            self._op_form,
            self._dc_form,
            self._tran_form,
            self._ac_form,
            self._noise_form,
        ]
        return forms[self.analysis_combo.currentIndex()].params()

    def _invoke_ngspice(self, analysis: str, params: dict[str, Any]) -> dict[str, Any]:
        # Lazy import so the panel can be loaded even if core isn't on the path
        from openforge.engine.ngspice import NgspiceEngine

        eng = NgspiceEngine()
        netlist = self._netlist_path
        assert netlist
        if analysis == "op":
            return {"op": eng.run_op_analysis(netlist)}
        if analysis == "tran":
            return {
                "tran": eng.run_transient(
                    netlist,
                    tstep=params["tstep"],
                    tstop=params["tstop"],
                )
            }
        if analysis == "dc":
            return {
                "dc": eng.run_dc_sweep(
                    netlist,
                    params["source"],
                    params["start"],
                    params["stop"],
                    params["step"],
                )
            }
        if analysis == "ac":
            return {
                "ac": eng.run_ac_analysis(
                    netlist,
                    sweep=params.get("variation", "dec"),
                    points_per_dec=params["npoints"],
                    fstart=params["fstart"],
                    fstop=params["fstop"],
                )
            }
        if analysis == "noise":
            return {
                "noise": eng.run_noise_analysis(
                    netlist,
                    output=params["output"],
                    source=params["src"],
                    fstart=params["fstart"],
                    fstop=params["fstop"],
                    points_per_dec=params["pts"],
                )
            }
        return {}

    def _populate_plot(self, analysis: str, results: dict[str, Any]) -> None:
        self.plot.clear()
        if analysis == "tran" and "tran" in results:
            data = results["tran"] or {}
            if data.get("error"):
                self.log_view.append(f"ngspice error: {data['error']}")
            time_axis = data.get("time", []) or []
            sigs: dict[str, list[tuple[float, float]]] = {}
            for name, ys in data.get("signals", {}).items():
                n = min(len(time_axis), len(ys))
                if n == 0:
                    continue
                sigs[name] = list(zip(time_axis[:n], ys[:n], strict=False))
            self.plot.set_data(sigs, x_label="Time (s)", y_label="Voltage (V)")
            self.status.showMessage(f"Transient: {len(time_axis)} points, {len(sigs)} signals")
        elif analysis == "dc" and "dc" in results:
            data = results["dc"] or {}
            if data.get("error"):
                self.log_view.append(f"ngspice error: {data['error']}")
            sweep = data.get("sweep", []) or []
            sigs = {}
            for name, ys in data.get("signals", {}).items():
                n = min(len(sweep), len(ys))
                if n == 0:
                    continue
                sigs[name] = list(zip(sweep[:n], ys[:n], strict=False))
            self.plot.set_data(sigs, x_label=data.get("sweep_var", "V"), y_label="Voltage (V)")
            self.status.showMessage(f"DC sweep: {len(sweep)} points")
        elif analysis == "ac" and "ac" in results:
            data = results["ac"] or {}
            if data.get("error"):
                self.log_view.append(f"ngspice error: {data['error']}")
            freq = data.get("freq", []) or []
            sigs = {}
            for name, ys in data.get("signals", {}).items():
                n = min(len(freq), len(ys))
                if n == 0:
                    continue
                sigs[name] = list(zip(freq[:n], ys[:n], strict=False))
            self.plot.set_data(
                sigs,
                x_label="Frequency (Hz)",
                y_label="Magnitude",
                log_x=True,
                log_y=True,
            )
            self.status.showMessage(f"AC: {len(freq)} points")
        elif analysis == "noise" and "noise" in results:
            data = results["noise"] or {}
            if data.get("error"):
                self.log_view.append(f"ngspice error: {data['error']}")
            freq = data.get("freq", []) or []
            sigs = {}
            for name, ys in data.get("signals", {}).items():
                n = min(len(freq), len(ys))
                if n == 0:
                    continue
                sigs[name] = list(zip(freq[:n], ys[:n], strict=False))
            self.plot.set_data(
                sigs,
                x_label="Frequency (Hz)",
                y_label="Noise (V/sqrt(Hz))",
                log_x=True,
                log_y=True,
            )
        elif analysis == "op":
            data = results.get("op", {}) or {}
            if data.get("error"):
                self.log_view.append(f"ngspice error: {data['error']}")
            for name, val in (data.get("node_voltages") or {}).items():
                try:
                    self.log_view.append(f"  {name} = {float(val):.6g}")
                except (TypeError, ValueError):
                    self.log_view.append(f"  {name} = {val}")

    def _on_export_csv(self) -> None:
        if not self._last_results:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "results.csv", "CSV (*.csv)")
        if not path:
            return
        rows: list[list[Any]] = []
        traces = self.plot.visible_traces()
        if not traces:
            return
        max_len = max(len(t.x) for t in traces)
        header = ["x"] + [t.name for t in traces]
        rows.append(header)
        for i in range(max_len):
            row: list[Any] = [traces[0].x[i] if i < len(traces[0].x) else ""]
            for t in traces:
                row.append(t.y[i] if i < len(t.y) else "")
            rows.append(row)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        self.status.showMessage(f"Exported {path}")

    def _on_save_plot(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save plot", "plot.png", "PNG (*.png)")
        if not path:
            return
        try:
            self.plot.export_png(Path(path))
        except Exception as e:
            self.log_view.append(f"PNG export failed: {e}")
            return
        self.status.showMessage(f"Saved {path}")

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QDockWidget { background: #1e1e2e; color: #cdd6f4; }
            QGroupBox { border: 1px solid #45475a; border-radius: 6px;
                        margin-top: 10px; padding: 8px;
                        color: #cdd6f4; background: #181825; }
            QGroupBox::title { left: 10px; padding: 0 4px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTextEdit {
                background: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 4px; padding: 3px;
            }
            QPushButton {
                background: #45475a; color: #cdd6f4;
                border: 1px solid #585b70; border-radius: 4px; padding: 4px 10px;
            }
            QPushButton:hover { background: #585b70; }
            QToolBar { background: #181825; border: none; }
            QStatusBar { background: #181825; color: #a6adc8; }
            QLabel { color: #cdd6f4; }
            """
        )
