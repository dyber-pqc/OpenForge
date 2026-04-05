"""Waveform viewer panel for VCD / simulation results."""

from __future__ import annotations

from enum import Enum
from typing import Final

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSplitter,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Catppuccin Mocha signal colours -- cycle through these
_SIGNAL_COLORS: Final[list[str]] = [
    "#89b4fa",  # blue
    "#a6e3a1",  # green
    "#f9e2af",  # yellow
    "#f38ba8",  # red
    "#cba6f7",  # mauve
    "#94e2d5",  # teal
    "#fab387",  # peach
    "#f5c2e7",  # pink
    "#74c7ec",  # sapphire
    "#eba0ac",  # maroon
]

_BG: Final[str] = "#1e1e2e"
_GRID: Final[str] = "#313244"
_TEXT: Final[str] = "#cdd6f4"
_CURSOR: Final[str] = "#f5e0dc"  # rosewater
_RULER_BG: Final[str] = "#181825"
_RULER_TICK: Final[str] = "#585b70"

_RULER_HEIGHT: Final[int] = 24
_SIGNAL_ROW_HEIGHT: Final[int] = 32
_LEFT_MARGIN: Final[int] = 8


class Radix(Enum):
    BINARY = "bin"
    HEX = "hex"
    DECIMAL = "dec"


class _SignalData:
    """Internal storage for one waveform signal."""

    __slots__ = ("name", "values", "timestamps", "color", "radix")

    def __init__(
        self,
        name: str,
        values: list[str],
        timestamps: list[float],
        color: str,
    ) -> None:
        self.name = name
        self.values = values
        self.timestamps = timestamps
        self.color = color
        self.radix: Radix = Radix.HEX


def _format_value(val: str, radix: Radix) -> str:
    """Format a binary value string according to the selected radix."""
    if radix == Radix.BINARY:
        return val
    try:
        n = int(val, 2)
    except (ValueError, TypeError):
        return val
    if radix == Radix.HEX:
        return f"0x{n:X}"
    return str(n)


def _format_time(t: float) -> str:
    """Format a time value with appropriate units."""
    if t >= 1e-3:
        return f"{t * 1e3:.1f} ms"
    if t >= 1e-6:
        return f"{t * 1e6:.1f} us"
    if t >= 1e-9:
        return f"{t * 1e9:.1f} ns"
    return f"{t * 1e12:.1f} ps"


# ---------------------------------------------------------------------------
# Custom paint widget for waveforms
# ---------------------------------------------------------------------------


class _WaveformCanvas(QWidget):
    """Custom widget that renders waveform traces using QPainter."""

    cursor_moved = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMouseTracking(True)

        self._signals: list[_SignalData] = []
        self._time_start: float = 0.0
        self._time_end: float = 1.0
        self._cursor_time: float = 0.0
        self._cursor_visible: bool = True

        self._font = QFont("JetBrains Mono", 10)
        self._font.setStyleHint(QFont.StyleHint.Monospace)

    def set_signals(self, signals: list[_SignalData]) -> None:
        self._signals = signals
        self._recalc_time_range()
        self.update()

    def set_time_range(self, start: float, end: float) -> None:
        if end > start:
            self._time_start = start
            self._time_end = end
            self.update()

    def zoom_in(self) -> None:
        mid = (self._time_start + self._time_end) / 2.0
        span = (self._time_end - self._time_start) / 2.0
        new_span = span * 0.7
        self.set_time_range(mid - new_span, mid + new_span)

    def zoom_out(self) -> None:
        mid = (self._time_start + self._time_end) / 2.0
        span = (self._time_end - self._time_start) / 2.0
        new_span = span * 1.4
        self.set_time_range(mid - new_span, mid + new_span)

    def zoom_fit(self) -> None:
        self._recalc_time_range()
        self.update()

    # ── Painting ───────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor(_BG))

        # Time ruler
        self._draw_ruler(painter, w)

        # Waveform area
        wave_top = _RULER_HEIGHT
        for idx, sig in enumerate(self._signals):
            y0 = wave_top + idx * _SIGNAL_ROW_HEIGHT
            self._draw_signal(painter, sig, y0, w)

        # Cursor
        if self._cursor_visible and self._time_end > self._time_start:
            cx = self._time_to_x(self._cursor_time, w)
            if 0 <= cx <= w:
                pen = QPen(QColor(_CURSOR), 1.0, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(int(cx), 0, int(cx), h)

        painter.end()

    def _draw_ruler(self, painter: QPainter, width: int) -> None:
        painter.fillRect(0, 0, width, _RULER_HEIGHT, QColor(_RULER_BG))

        pen = QPen(QColor(_RULER_TICK), 1.0)
        painter.setPen(pen)

        # Draw ticks
        duration = self._time_end - self._time_start
        if duration <= 0:
            return

        # Aim for roughly 10 ticks
        tick_step = duration / 10.0
        t = self._time_start
        while t <= self._time_end:
            x = self._time_to_x(t, width)
            painter.drawLine(int(x), _RULER_HEIGHT - 6, int(x), _RULER_HEIGHT)
            label = _format_time(t)
            painter.drawText(int(x) + 2, _RULER_HEIGHT - 8, label)
            t += tick_step

        # Bottom line
        pen2 = QPen(QColor(_GRID), 1.0)
        painter.setPen(pen2)
        painter.drawLine(0, _RULER_HEIGHT, width, _RULER_HEIGHT)

    def _draw_signal(
        self, painter: QPainter, sig: _SignalData, y0: int, width: int
    ) -> None:
        row_h = _SIGNAL_ROW_HEIGHT
        mid_y = y0 + row_h // 2
        high_y = y0 + 4
        low_y = y0 + row_h - 4

        # Row separator
        pen_grid = QPen(QColor(_GRID), 0.5)
        painter.setPen(pen_grid)
        painter.drawLine(0, y0 + row_h, width, y0 + row_h)

        color = QColor(sig.color)
        pen = QPen(color, 1.5)
        painter.setPen(pen)

        is_bus = any(len(v) > 1 for v in sig.values if v not in ("x", "z", "X", "Z"))

        for i in range(len(sig.timestamps)):
            t = sig.timestamps[i]
            val = sig.values[i]
            x = self._time_to_x(t, width)

            # Next timestamp
            if i + 1 < len(sig.timestamps):
                t_next = sig.timestamps[i + 1]
            else:
                t_next = self._time_end
            x_next = self._time_to_x(t_next, width)

            if is_bus:
                # Bus waveform: diamond transitions with value label
                painter.setPen(pen)
                # Top line
                painter.drawLine(int(x) + 3, high_y, int(x_next) - 3, high_y)
                # Bottom line
                painter.drawLine(int(x) + 3, low_y, int(x_next) - 3, low_y)
                # Left diamond
                painter.drawLine(int(x), mid_y, int(x) + 3, high_y)
                painter.drawLine(int(x), mid_y, int(x) + 3, low_y)
                # Right diamond
                painter.drawLine(int(x_next) - 3, high_y, int(x_next), mid_y)
                painter.drawLine(int(x_next) - 3, low_y, int(x_next), mid_y)

                # Value text
                text = _format_value(val, sig.radix)
                text_w = x_next - x - 8
                if text_w > 20:
                    painter.setPen(QPen(color, 1.0))
                    fm = QFontMetrics(self._font)
                    elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(text_w))
                    painter.drawText(int(x) + 6, mid_y + 4, elided)
            else:
                # Single-bit: digital waveform
                if val == "1":
                    y = high_y
                elif val == "0":
                    y = low_y
                else:
                    y = mid_y  # X/Z

                painter.setPen(pen)
                # Horizontal line
                painter.drawLine(int(x), y, int(x_next), y)

                # Vertical transition
                if i > 0:
                    prev_val = sig.values[i - 1]
                    if prev_val == "1":
                        prev_y = high_y
                    elif prev_val == "0":
                        prev_y = low_y
                    else:
                        prev_y = mid_y
                    if prev_y != y:
                        painter.drawLine(int(x), prev_y, int(x), y)

    def _time_to_x(self, t: float, width: int) -> float:
        duration = self._time_end - self._time_start
        if duration <= 0:
            return 0.0
        return ((t - self._time_start) / duration) * width

    def _x_to_time(self, x: float, width: int) -> float:
        duration = self._time_end - self._time_start
        return self._time_start + (x / width) * duration

    def _recalc_time_range(self) -> None:
        if not self._signals:
            self._time_start = 0.0
            self._time_end = 1.0
            return
        t_min = min(s.timestamps[0] for s in self._signals if s.timestamps)
        t_max = max(s.timestamps[-1] for s in self._signals if s.timestamps)
        margin = (t_max - t_min) * 0.05 if t_max > t_min else 0.5
        self._time_start = t_min - margin
        self._time_end = t_max + margin

    # ── Mouse interaction ──────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._cursor_time = self._x_to_time(event.position().x(), self.width())
            self._snap_cursor()
            self.cursor_moved.emit(self._cursor_time)
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._cursor_time = self._x_to_time(event.position().x(), self.width())
            self._snap_cursor()
            self.cursor_moved.emit(self._cursor_time)
            self.update()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _snap_cursor(self) -> None:
        """Snap cursor to the nearest signal edge within a pixel threshold."""
        snap_px = 5
        best_dist = float("inf")
        best_t = self._cursor_time
        w = self.width()

        cursor_x = self._time_to_x(self._cursor_time, w)

        for sig in self._signals:
            for t in sig.timestamps:
                tx = self._time_to_x(t, w)
                dist = abs(tx - cursor_x)
                if dist < snap_px and dist < best_dist:
                    best_dist = dist
                    best_t = t

        self._cursor_time = best_t


# ---------------------------------------------------------------------------
# Signal list tree
# ---------------------------------------------------------------------------


class _SignalListTree(QTreeWidget):
    """Tree widget listing all loaded signals with radix selectors."""

    radix_changed = Signal(int, str)  # signal index, radix value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Signal", "Value", "Radix"])
        self.setColumnWidth(0, 160)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 60)
        self.setIndentation(12)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(
            "QTreeWidget { alternate-background-color: #1a1a2e; }"
        )

    def set_signals(self, signals: list[_SignalData]) -> None:
        self.clear()
        for idx, sig in enumerate(signals):
            item = QTreeWidgetItem([sig.name, "", ""])
            item.setForeground(0, QColor(sig.color))
            self.addTopLevelItem(item)

            combo = QComboBox()
            combo.addItems(["hex", "bin", "dec"])
            combo.setCurrentText(sig.radix.value)
            combo.currentTextChanged.connect(
                lambda text, i=idx: self.radix_changed.emit(i, text)
            )
            self.setItemWidget(item, 2, combo)

    def update_cursor_values(self, signals: list[_SignalData], cursor_time: float) -> None:
        for idx in range(self.topLevelItemCount()):
            if idx >= len(signals):
                break
            sig = signals[idx]
            # Find value at cursor time
            val = ""
            for i, t in enumerate(sig.timestamps):
                if t <= cursor_time:
                    val = sig.values[i]
                else:
                    break
            item = self.topLevelItem(idx)
            if item is not None:
                item.setText(1, _format_value(val, sig.radix))


# ---------------------------------------------------------------------------
# Waveform panel dock widget
# ---------------------------------------------------------------------------


class WaveformPanel(QDockWidget):
    """Dock widget combining signal list and waveform canvas."""

    def __init__(self, title: str = "Waveform Viewer", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            "QToolBar { background-color: #181825; border-bottom: 1px solid #313244; padding: 2px; }"
        )

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setToolTip("Zoom In")
        btn_zoom_in.setFixedSize(28, 28)
        btn_zoom_in.clicked.connect(lambda: self._canvas.zoom_in())
        toolbar.addWidget(btn_zoom_in)

        btn_zoom_out = QPushButton("\u2013")
        btn_zoom_out.setToolTip("Zoom Out")
        btn_zoom_out.setFixedSize(28, 28)
        btn_zoom_out.clicked.connect(lambda: self._canvas.zoom_out())
        toolbar.addWidget(btn_zoom_out)

        btn_fit = QPushButton("Fit")
        btn_fit.setToolTip("Fit All")
        btn_fit.setFixedSize(40, 28)
        btn_fit.clicked.connect(lambda: self._canvas.zoom_fit())
        toolbar.addWidget(btn_fit)

        layout.addWidget(toolbar)

        # Splitter: signal list | waveform canvas
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._signal_list = _SignalListTree()
        splitter.addWidget(self._signal_list)

        self._canvas = _WaveformCanvas()
        splitter.addWidget(self._canvas)

        splitter.setSizes([250, 600])
        layout.addWidget(splitter)

        self.setWidget(container)

        # Internal signal storage
        self._signals: list[_SignalData] = []
        self._color_idx: int = 0

        # Wire signals
        self._canvas.cursor_moved.connect(self._on_cursor_moved)
        self._signal_list.radix_changed.connect(self._on_radix_changed)

    # ── Public API ─────────────────────────────────────────────────

    def load_vcd(self, path: str) -> None:
        """Load a VCD file and display its signals.

        Currently a stub -- actual VCD parsing is not yet implemented.
        """
        self.clear()
        # TODO: integrate VCD parser

    def add_signal(
        self, name: str, values: list[str], timestamps: list[float]
    ) -> None:
        """Add a signal trace to the viewer."""
        color = _SIGNAL_COLORS[self._color_idx % len(_SIGNAL_COLORS)]
        self._color_idx += 1
        sig = _SignalData(name, values, timestamps, color)
        self._signals.append(sig)
        self._canvas.set_signals(self._signals)
        self._signal_list.set_signals(self._signals)

    def clear(self) -> None:
        """Remove all signals from the viewer."""
        self._signals.clear()
        self._color_idx = 0
        self._canvas.set_signals([])
        self._signal_list.clear()

    # ── Internal ───────────────────────────────────────────────────

    def _on_cursor_moved(self, t: float) -> None:
        self._signal_list.update_cursor_values(self._signals, t)

    def _on_radix_changed(self, idx: int, radix_text: str) -> None:
        if 0 <= idx < len(self._signals):
            radix_map = {"bin": Radix.BINARY, "hex": Radix.HEX, "dec": Radix.DECIMAL}
            self._signals[idx].radix = radix_map.get(radix_text, Radix.HEX)
            self._canvas.update()
