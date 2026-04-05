"""Vivado-quality waveform viewer panel for VCD / simulation results.

Provides a three-pane layout (signal tree, value column, waveform canvas)
with dual cursors, markers, minimap, analog traces, X/Z hatch patterns,
bus diamond transitions, and a full toolbar/statusbar -- all themed with
Catppuccin Mocha colours.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Final

from PySide6.QtCore import (
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

# ── Catppuccin Mocha palette ──────────────────────────────────────────────

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
_SUBTEXT: Final[str] = "#a6adc8"
_SURFACE0: Final[str] = "#313244"
_SURFACE1: Final[str] = "#45475a"
_SURFACE2: Final[str] = "#585b70"
_OVERLAY0: Final[str] = "#6c7086"
_CRUST: Final[str] = "#11111b"
_MANTLE: Final[str] = "#181825"
_CURSOR_COLOR: Final[str] = "#f5e0dc"  # rosewater
_CURSOR2_COLOR: Final[str] = "#f5c2e7"  # pink
_SELECTION_COLOR: Final[str] = "#45475a"
_HIGH_COLOR: Final[str] = "#a6e3a1"  # green
_LOW_COLOR: Final[str] = "#585b70"  # surface2
_XZ_COLOR: Final[str] = "#f38ba8"  # red
_MARKER_COLOR: Final[str] = "#fab387"  # peach

_RULER_HEIGHT: Final[int] = 30
_SIGNAL_ROW_HEIGHT: Final[int] = 28
_MINIMAP_HEIGHT: Final[int] = 20
_SCROLLBAR_HEIGHT: Final[int] = 14


# ── Enums & data classes ──────────────────────────────────────────────────


class Radix(Enum):
    BINARY = "Binary"
    OCTAL = "Octal"
    HEX = "Hex"
    UNSIGNED = "Unsigned"
    SIGNED = "Signed"
    ASCII = "ASCII"
    ENUM = "Enum"


class SignalKind(Enum):
    SINGLE_BIT = "bit"
    BUS = "bus"
    ANALOG = "analog"
    CLOCK = "clock"


_RADIX_LIST: Final[list[str]] = [r.value for r in Radix]

_ICON_COLORS: Final[dict[SignalKind, str]] = {
    SignalKind.CLOCK: "#f9e2af",
    SignalKind.BUS: "#89b4fa",
    SignalKind.SINGLE_BIT: "#a6e3a1",
    SignalKind.ANALOG: "#cba6f7",
}


@dataclass
class SignalData:
    """Storage for one waveform signal."""

    name: str
    values: list[str]
    timestamps: list[float]
    color: str
    kind: SignalKind = SignalKind.SINGLE_BIT
    radix: Radix = Radix.HEX
    group: str = ""
    visible: bool = True
    analog_min: float = 0.0
    analog_max: float = 1.0
    analog_auto: bool = True


@dataclass
class Marker:
    """Named vertical marker on the waveform."""

    name: str
    time: float
    color: str = _MARKER_COLOR


# ── Helpers ───────────────────────────────────────────────────────────────


def _format_value(val: str, radix: Radix) -> str:
    """Format a binary value string according to the selected radix."""
    if not val or val in ("x", "z", "X", "Z"):
        return val.upper()
    if radix == Radix.BINARY:
        return f"0b{val}"
    try:
        n = int(val, 2)
    except (ValueError, TypeError):
        return val
    if radix == Radix.HEX:
        width = max(1, (len(val) + 3) // 4)
        return f"0x{n:0{width}X}"
    if radix == Radix.OCTAL:
        return f"0o{oct(n)[2:]}"
    if radix == Radix.UNSIGNED:
        return str(n)
    if radix == Radix.SIGNED:
        bits = len(val)
        if n >= (1 << (bits - 1)):
            n -= 1 << bits
        return str(n)
    if radix == Radix.ASCII:
        try:
            return repr(chr(n)) if 0x20 <= n < 0x7F else f"\\x{n:02x}"
        except (ValueError, OverflowError):
            return val
    return val


def _format_time(t: float) -> str:
    """Format a time value with smart unit scaling."""
    if t < 0:
        return f"-{_format_time(-t)}"
    if t == 0:
        return "0"
    if t >= 1.0:
        return f"{t:.3f} s"
    if t >= 1e-3:
        return f"{t * 1e3:.3f} ms"
    if t >= 1e-6:
        return f"{t * 1e6:.3f} us"
    if t >= 1e-9:
        return f"{t * 1e9:.3f} ns"
    return f"{t * 1e12:.3f} ps"


def _nice_tick_step(rough: float) -> float:
    """Round a rough tick interval to a 'nice' human-readable step."""
    if rough <= 0:
        return 1.0
    exp = math.floor(math.log10(rough))
    frac = rough / (10 ** exp)
    if frac <= 1.5:
        nice = 1.0
    elif frac <= 3.5:
        nice = 2.0
    elif frac <= 7.5:
        nice = 5.0
    else:
        nice = 10.0
    return nice * (10 ** exp)


def _make_signal_icon(color: str, kind: SignalKind) -> QPixmap:
    """Create a small coloured icon pixmap for a signal kind."""
    px = QPixmap(16, 16)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    p.setPen(QPen(c, 1.5))
    if kind == SignalKind.CLOCK:
        # Square wave icon
        p.drawPolyline([QPoint(1, 12), QPoint(1, 4), QPoint(5, 4),
                         QPoint(5, 12), QPoint(9, 12), QPoint(9, 4),
                         QPoint(13, 4), QPoint(13, 12)])
    elif kind == SignalKind.BUS:
        # Bus diamond icon
        p.drawPolygon([QPoint(2, 8), QPoint(5, 3), QPoint(11, 3),
                        QPoint(14, 8), QPoint(11, 13), QPoint(5, 13)])
    elif kind == SignalKind.ANALOG:
        # Sine-ish icon
        path = QPainterPath()
        path.moveTo(1, 10)
        path.cubicTo(4, 2, 8, 14, 15, 6)
        p.drawPath(path)
    else:
        # Digital step icon
        p.drawPolyline([QPoint(1, 12), QPoint(1, 4), QPoint(8, 4),
                         QPoint(8, 12), QPoint(15, 12)])
    p.end()
    return px


def _value_at_time(sig: SignalData, t: float) -> str:
    """Return the signal value at a given time via binary search."""
    ts = sig.timestamps
    if not ts:
        return ""
    lo, hi = 0, len(ts) - 1
    if t < ts[0]:
        return ""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ts[mid] <= t:
            lo = mid
        else:
            hi = mid - 1
    return sig.values[lo]


# ── Waveform Canvas ──────────────────────────────────────────────────────


class _WaveformCanvas(QWidget):
    """Custom QPainter widget that renders the time ruler, waveform traces,
    cursors, markers, selection highlight, and minimap."""

    cursor_moved = Signal(float)
    cursor2_moved = Signal(float)
    selection_changed = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 100)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._signals: list[SignalData] = []
        self._markers: list[Marker] = []

        # View state
        self._time_start: float = 0.0
        self._time_end: float = 1.0
        self._full_start: float = 0.0
        self._full_end: float = 1.0
        self._cursor_time: float = 0.0
        self._cursor2_time: float | None = None
        self._cursor2_active: bool = False
        self._sel_start: float | None = None
        self._sel_end: float | None = None
        self._scroll_offset: int = 0  # vertical pixel offset for virtual scroll

        # Interaction state
        self._dragging: bool = False
        self._panning: bool = False
        self._pan_origin_x: float = 0.0
        self._pan_time_start: float = 0.0
        self._pan_time_end: float = 0.0
        self._selecting: bool = False

        # Repaint throttle
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(16)  # ~60 fps cap
        self._repaint_timer.timeout.connect(self.update)

        # Fonts
        self._font = QFont("JetBrains Mono", 9)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font_small = QFont("JetBrains Mono", 7)
        self._font_small.setStyleHint(QFont.StyleHint.Monospace)
        self._fm = QFontMetrics(self._font)
        self._fm_small = QFontMetrics(self._font_small)

        # Hatch pattern for X/Z states
        self._xz_hatch = self._make_hatch_pattern()

    @staticmethod
    def _make_hatch_pattern() -> QPixmap:
        sz = 8
        img = QImage(sz, sz, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setPen(QPen(QColor(_XZ_COLOR), 1.0))
        p.drawLine(0, sz, sz, 0)
        p.end()
        return QPixmap.fromImage(img)

    # ── Public interface ──────────────────────────────────────────────

    def set_signals(self, signals: list[SignalData]) -> None:
        self._signals = signals
        self._recalc_full_range()
        self.zoom_fit()

    def set_markers(self, markers: list[Marker]) -> None:
        self._markers = markers
        self._schedule_repaint()

    def set_scroll_offset(self, offset: int) -> None:
        self._scroll_offset = offset
        self._schedule_repaint()

    @property
    def total_content_height(self) -> int:
        return _RULER_HEIGHT + len(self._signals) * _SIGNAL_ROW_HEIGHT + _MINIMAP_HEIGHT

    @property
    def cursor_time(self) -> float:
        return self._cursor_time

    @property
    def cursor2_time(self) -> float | None:
        return self._cursor2_time

    def zoom_in(self) -> None:
        self._zoom_around(self._cursor_time, 0.7)

    def zoom_out(self) -> None:
        self._zoom_around(self._cursor_time, 1.4)

    def zoom_fit(self) -> None:
        margin = (self._full_end - self._full_start) * 0.05
        self._time_start = self._full_start - margin
        self._time_end = self._full_end + margin
        self._schedule_repaint()

    def zoom_selection(self) -> None:
        if self._sel_start is not None and self._sel_end is not None:
            lo = min(self._sel_start, self._sel_end)
            hi = max(self._sel_start, self._sel_end)
            if hi > lo:
                margin = (hi - lo) * 0.05
                self._time_start = lo - margin
                self._time_end = hi + margin
                self._schedule_repaint()

    def go_to_start(self) -> None:
        span = self._time_end - self._time_start
        self._time_start = self._full_start
        self._time_end = self._full_start + span
        self._schedule_repaint()

    def go_to_end(self) -> None:
        span = self._time_end - self._time_start
        self._time_end = self._full_end
        self._time_start = self._full_end - span
        self._schedule_repaint()

    def go_to_cursor(self) -> None:
        span = self._time_end - self._time_start
        self._time_start = self._cursor_time - span / 2
        self._time_end = self._cursor_time + span / 2
        self._schedule_repaint()

    def find_edge(self, sig_index: int, direction: int, edge: str = "any") -> None:
        """Navigate to the next/previous edge of the given signal.

        Args:
            sig_index: Index into self._signals.
            direction: +1 for next, -1 for previous.
            edge: 'rising', 'falling', or 'any'.
        """
        if sig_index < 0 or sig_index >= len(self._signals):
            return
        sig = self._signals[sig_index]
        ct = self._cursor_time
        candidates: list[float] = []
        for i in range(1, len(sig.timestamps)):
            t = sig.timestamps[i]
            prev_v = sig.values[i - 1]
            cur_v = sig.values[i]
            if prev_v == cur_v:
                continue
            if edge == "rising" and not (prev_v == "0" and cur_v == "1"):
                continue
            if edge == "falling" and not (prev_v == "1" and cur_v == "0"):
                continue
            if direction > 0 and t > ct + 1e-18:
                candidates.append(t)
                break
            elif direction < 0 and t < ct - 1e-18:
                candidates.append(t)
        if direction < 0:
            # We want the last candidate before cursor
            candidates.clear()
            for i in range(len(sig.timestamps) - 1, 0, -1):
                t = sig.timestamps[i]
                if t < ct - 1e-18 and sig.values[i] != sig.values[i - 1]:
                    prev_v = sig.values[i - 1]
                    cur_v = sig.values[i]
                    if edge == "rising" and not (prev_v == "0" and cur_v == "1"):
                        continue
                    if edge == "falling" and not (prev_v == "1" and cur_v == "0"):
                        continue
                    candidates.append(t)
                    break
        if candidates:
            self._cursor_time = candidates[0]
            self.cursor_moved.emit(self._cursor_time)
            self.go_to_cursor()

    def save_snapshot(self, path: str) -> None:
        """Render the current view to a PNG file."""
        pixmap = QPixmap(self.size())
        self.render(pixmap)
        pixmap.save(path, "PNG")

    def add_marker_at_cursor(self, name: str | None = None) -> Marker:
        idx = len(self._markers) + 1
        m = Marker(name=name or f"M{idx}", time=self._cursor_time)
        self._markers.append(m)
        self._schedule_repaint()
        return m

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(_BG))

        # Clipping: only draw visible signals
        wave_top = _RULER_HEIGHT - self._scroll_offset
        visible_sigs = self._visible_signal_range(h)

        # Grid lines (aligned to ruler ticks)
        self._draw_grid(p, w, h, wave_top, visible_sigs)

        # Selection highlight
        if self._sel_start is not None and self._sel_end is not None:
            self._draw_selection(p, w, h)

        # Waveform traces
        for idx in range(visible_sigs[0], visible_sigs[1]):
            if idx >= len(self._signals):
                break
            sig = self._signals[idx]
            if not sig.visible:
                continue
            y0 = wave_top + idx * _SIGNAL_ROW_HEIGHT
            self._draw_signal(p, sig, y0, w)

        # Row separators
        pen_grid = QPen(QColor(_GRID), 0.5)
        p.setPen(pen_grid)
        for idx in range(visible_sigs[0], min(visible_sigs[1] + 1, len(self._signals) + 1)):
            y = wave_top + idx * _SIGNAL_ROW_HEIGHT
            if _RULER_HEIGHT <= y < h - _MINIMAP_HEIGHT:
                p.drawLine(0, y, w, y)

        # Markers
        for m in self._markers:
            mx = self._time_to_x(m.time, w)
            if 0 <= mx <= w:
                pen_m = QPen(QColor(m.color), 1.0, Qt.PenStyle.DashLine)
                p.setPen(pen_m)
                p.drawLine(int(mx), _RULER_HEIGHT, int(mx), h - _MINIMAP_HEIGHT)
                p.setFont(self._font_small)
                p.setPen(QPen(QColor(m.color)))
                p.drawText(int(mx) + 3, _RULER_HEIGHT + 10, m.name)

        # Secondary cursor
        if self._cursor2_time is not None:
            c2x = self._time_to_x(self._cursor2_time, w)
            if 0 <= c2x <= w:
                pen2 = QPen(QColor(_CURSOR2_COLOR), 1.0, Qt.PenStyle.DashDotLine)
                p.setPen(pen2)
                p.drawLine(int(c2x), _RULER_HEIGHT, int(c2x), h - _MINIMAP_HEIGHT)

        # Primary cursor
        cx = self._time_to_x(self._cursor_time, w)
        if 0 <= cx <= w:
            pen_c = QPen(QColor(_CURSOR_COLOR), 1.5)
            p.setPen(pen_c)
            p.drawLine(int(cx), _RULER_HEIGHT, int(cx), h - _MINIMAP_HEIGHT)

        # Ruler (drawn on top of everything)
        self._draw_ruler(p, w)

        # Cursor time label on ruler
        p.setFont(self._font)
        p.setPen(QPen(QColor(_CURSOR_COLOR)))
        label = _format_time(self._cursor_time)
        lbl_w = self._fm.horizontalAdvance(label) + 8
        lbl_x = max(0, min(int(cx) - lbl_w // 2, w - lbl_w))
        p.fillRect(lbl_x, 1, lbl_w, 14, QColor(_MANTLE))
        p.drawText(lbl_x + 4, 12, label)

        # Delta label
        if self._cursor2_time is not None:
            delta = abs(self._cursor_time - self._cursor2_time)
            dlbl = f"\u0394 {_format_time(delta)}"
            p.setPen(QPen(QColor(_CURSOR2_COLOR)))
            dl_w = self._fm.horizontalAdvance(dlbl) + 8
            mid_x = int((cx + self._time_to_x(self._cursor2_time, w)) / 2)
            dl_x = max(0, min(mid_x - dl_w // 2, w - dl_w))
            p.fillRect(dl_x, 15, dl_w, 14, QColor(_MANTLE))
            p.drawText(dl_x + 4, 26, dlbl)

        # Minimap
        self._draw_minimap(p, w, h)

        p.end()

    def _draw_ruler(self, p: QPainter, w: int) -> None:
        p.fillRect(0, 0, w, _RULER_HEIGHT, QColor(_MANTLE))
        duration = self._time_end - self._time_start
        if duration <= 0:
            return

        rough_step = duration / max(1, w // 100)
        step = _nice_tick_step(rough_step)
        minor_step = step / 5.0

        t0 = math.floor(self._time_start / minor_step) * minor_step

        p.setFont(self._font_small)
        t = t0
        while t <= self._time_end:
            x = self._time_to_x(t, w)
            # Is this a major tick?
            is_major = abs(t / step - round(t / step)) < 1e-9
            if is_major:
                p.setPen(QPen(QColor(_TEXT), 1.0))
                p.drawLine(int(x), _RULER_HEIGHT - 10, int(x), _RULER_HEIGHT)
                lbl = _format_time(t)
                p.drawText(int(x) + 2, _RULER_HEIGHT - 12, lbl)
            else:
                p.setPen(QPen(QColor(_SURFACE2), 0.5))
                p.drawLine(int(x), _RULER_HEIGHT - 4, int(x), _RULER_HEIGHT)
            t += minor_step

        # Bottom border
        p.setPen(QPen(QColor(_SURFACE0), 1.0))
        p.drawLine(0, _RULER_HEIGHT, w, _RULER_HEIGHT)

    def _draw_grid(self, p: QPainter, w: int, h: int, wave_top: int,
                   vis: tuple[int, int]) -> None:
        duration = self._time_end - self._time_start
        if duration <= 0:
            return
        rough_step = duration / max(1, w // 100)
        step = _nice_tick_step(rough_step)
        t = math.floor(self._time_start / step) * step
        pen = QPen(QColor(_GRID), 0.3)
        p.setPen(pen)
        while t <= self._time_end:
            x = int(self._time_to_x(t, w))
            p.drawLine(x, _RULER_HEIGHT, x, h - _MINIMAP_HEIGHT)
            t += step

    def _draw_selection(self, p: QPainter, w: int, h: int) -> None:
        x0 = int(self._time_to_x(min(self._sel_start, self._sel_end), w))
        x1 = int(self._time_to_x(max(self._sel_start, self._sel_end), w))
        sel_color = QColor(_SELECTION_COLOR)
        sel_color.setAlpha(76)  # ~30%
        p.fillRect(x0, _RULER_HEIGHT, x1 - x0, h - _RULER_HEIGHT - _MINIMAP_HEIGHT, sel_color)

    def _draw_signal(self, p: QPainter, sig: SignalData, y0: int, w: int) -> None:
        row_h = _SIGNAL_ROW_HEIGHT
        mid_y = y0 + row_h // 2
        high_y = y0 + 5
        low_y = y0 + row_h - 5
        color = QColor(sig.color)

        if sig.kind == SignalKind.ANALOG:
            self._draw_analog(p, sig, y0, row_h, w)
            return

        is_bus = sig.kind == SignalKind.BUS or any(
            len(v) > 1 for v in sig.values if v not in ("x", "z", "X", "Z")
        )

        for i in range(len(sig.timestamps)):
            t = sig.timestamps[i]
            val = sig.values[i]
            t_next = sig.timestamps[i + 1] if i + 1 < len(sig.timestamps) else self._time_end
            x = self._time_to_x(t, w)
            x_next = self._time_to_x(t_next, w)

            # Cull off-screen segments
            if x_next < 0 or x > w:
                continue

            is_xz = val.lower() in ("x", "z")

            if is_bus:
                self._draw_bus_segment(p, sig, val, x, x_next, high_y, low_y, mid_y, color, is_xz)
            else:
                self._draw_bit_segment(p, val, x, x_next, high_y, low_y, mid_y, color,
                                       is_xz, i, sig)

    def _draw_bus_segment(self, p: QPainter, sig: SignalData, val: str,
                          x: float, x_next: float, high_y: int, low_y: int,
                          mid_y: int, color: QColor, is_xz: bool) -> None:
        dx = min(4.0, (x_next - x) / 3.0)
        ix, ix_next = int(x), int(x_next)

        if is_xz:
            # Hatched fill for X/Z
            clip_rect = QRect(ix, high_y, ix_next - ix, low_y - high_y)
            p.save()
            p.setClipRect(clip_rect)
            brush = QBrush(self._xz_hatch)
            p.fillRect(clip_rect, brush)
            p.restore()
            p.setPen(QPen(QColor(_XZ_COLOR), 1.5))
            label = val.upper()
        else:
            # Fill background with signal color at 15% opacity
            fill_c = QColor(color)
            fill_c.setAlpha(38)
            fill_rect = QRectF(x + dx, high_y, x_next - x - 2 * dx, low_y - high_y)
            p.fillRect(fill_rect, fill_c)
            p.setPen(QPen(color, 1.5))
            label = _format_value(val, sig.radix)

        # Diamond transitions and top/bottom rails
        pts_top = [QPoint(int(x + dx), high_y), QPoint(int(x_next - dx), high_y)]
        pts_bot = [QPoint(int(x + dx), low_y), QPoint(int(x_next - dx), low_y)]
        p.drawLine(pts_top[0], pts_top[1])
        p.drawLine(pts_bot[0], pts_bot[1])
        # Left diamond
        p.drawLine(QPoint(ix, mid_y), QPoint(int(x + dx), high_y))
        p.drawLine(QPoint(ix, mid_y), QPoint(int(x + dx), low_y))
        # Right diamond
        p.drawLine(QPoint(int(x_next - dx), high_y), QPoint(ix_next, mid_y))
        p.drawLine(QPoint(int(x_next - dx), low_y), QPoint(ix_next, mid_y))

        # Value text centred in stable region
        text_space = x_next - x - 2 * dx - 4
        if text_space > 12:
            p.setFont(self._font)
            fm = self._fm
            elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(text_space))
            tw = fm.horizontalAdvance(elided)
            tx = int(x + (x_next - x) / 2 - tw / 2)
            p.setPen(QPen(QColor(_TEXT), 1.0))
            p.drawText(tx, mid_y + fm.ascent() // 2 - 1, elided)

    def _draw_bit_segment(self, p: QPainter, val: str, x: float, x_next: float,
                          high_y: int, low_y: int, mid_y: int, color: QColor,
                          is_xz: bool, i: int, sig: SignalData) -> None:
        if is_xz:
            # Hatched region
            clip_rect = QRect(int(x), high_y, int(x_next - x), low_y - high_y)
            p.save()
            p.setClipRect(clip_rect)
            p.fillRect(clip_rect, QBrush(self._xz_hatch))
            p.restore()
            p.setPen(QPen(QColor(_XZ_COLOR), 1.5))
            p.drawLine(int(x), mid_y, int(x_next), mid_y)
            return

        if val == "1":
            y = high_y
            line_color = QColor(_HIGH_COLOR)
        else:
            y = low_y
            line_color = QColor(_LOW_COLOR)

        p.setPen(QPen(line_color, 1.5))
        p.drawLine(int(x), y, int(x_next), y)

        # Vertical transition from previous
        if i > 0:
            prev_val = sig.values[i - 1]
            if prev_val == "1":
                prev_y = high_y
            elif prev_val == "0":
                prev_y = low_y
            else:
                prev_y = mid_y
            if prev_y != y:
                p.setPen(QPen(color, 1.5))
                p.drawLine(int(x), prev_y, int(x), y)

    def _draw_analog(self, p: QPainter, sig: SignalData, y0: int,
                     row_h: int, w: int) -> None:
        if not sig.timestamps:
            return
        color = QColor(sig.color)
        pen = QPen(color, 1.5)
        p.setPen(pen)

        lo = sig.analog_min
        hi = sig.analog_max
        if sig.analog_auto and sig.values:
            try:
                nums = [float(v) for v in sig.values if v not in ("x", "z", "X", "Z")]
                if nums:
                    lo = min(nums)
                    hi = max(nums)
            except ValueError:
                pass
        rng = hi - lo if hi > lo else 1.0
        margin = 4

        prev_px: int | None = None
        prev_py: int | None = None
        for i in range(len(sig.timestamps)):
            t = sig.timestamps[i]
            x = int(self._time_to_x(t, w))
            try:
                v = float(sig.values[i])
            except (ValueError, TypeError):
                prev_px = None
                continue
            frac = (v - lo) / rng
            frac = max(0.0, min(1.0, frac))
            py = y0 + row_h - margin - int(frac * (row_h - 2 * margin))
            if prev_px is not None:
                p.drawLine(prev_px, prev_py, x, py)
            prev_px, prev_py = x, py

    def _draw_minimap(self, p: QPainter, w: int, h: int) -> None:
        my = h - _MINIMAP_HEIGHT
        p.fillRect(0, my, w, _MINIMAP_HEIGHT, QColor(_CRUST))

        full_dur = self._full_end - self._full_start
        if full_dur <= 0:
            return

        # Draw simplified waveform overview for first few signals
        for idx, sig in enumerate(self._signals[:8]):
            if not sig.timestamps:
                continue
            mc = QColor(sig.color)
            mc.setAlpha(100)
            p.setPen(QPen(mc, 0.5))
            for i in range(len(sig.timestamps)):
                t = sig.timestamps[i]
                fx = int(((t - self._full_start) / full_dur) * w)
                val = sig.values[i]
                if val == "1":
                    p.drawLine(fx, my + 2, fx, my + _MINIMAP_HEIGHT - 2)

        # Viewport indicator
        vx0 = int(((self._time_start - self._full_start) / full_dur) * w)
        vx1 = int(((self._time_end - self._full_start) / full_dur) * w)
        vx0 = max(0, min(vx0, w))
        vx1 = max(0, min(vx1, w))
        vc = QColor(_SURFACE1)
        vc.setAlpha(100)
        p.fillRect(vx0, my, vx1 - vx0, _MINIMAP_HEIGHT, vc)
        p.setPen(QPen(QColor(_OVERLAY0), 1.0))
        p.drawRect(vx0, my, vx1 - vx0, _MINIMAP_HEIGHT)

    # ── Coordinate helpers ────────────────────────────────────────────

    def _time_to_x(self, t: float, w: int) -> float:
        dur = self._time_end - self._time_start
        if dur <= 0:
            return 0.0
        return ((t - self._time_start) / dur) * w

    def _x_to_time(self, x: float) -> float:
        dur = self._time_end - self._time_start
        return self._time_start + (x / max(1, self.width())) * dur

    def _visible_signal_range(self, h: int) -> tuple[int, int]:
        """Return (first, past-last) indices of signals visible in the viewport."""
        wave_top = _RULER_HEIGHT - self._scroll_offset
        first = max(0, int((_RULER_HEIGHT - wave_top) / _SIGNAL_ROW_HEIGHT))
        last = min(len(self._signals),
                   int((h - _MINIMAP_HEIGHT - wave_top) / _SIGNAL_ROW_HEIGHT) + 1)
        return (first, last)

    def _recalc_full_range(self) -> None:
        if not self._signals:
            self._full_start = 0.0
            self._full_end = 1.0
            return
        ts_min = min((s.timestamps[0] for s in self._signals if s.timestamps), default=0.0)
        ts_max = max((s.timestamps[-1] for s in self._signals if s.timestamps), default=1.0)
        self._full_start = ts_min
        self._full_end = ts_max if ts_max > ts_min else ts_min + 1.0

    def _snap_cursor(self, t: float) -> float:
        """Snap a time to the nearest signal edge within a pixel threshold."""
        snap_px = 5.0
        w = self.width()
        target_x = self._time_to_x(t, w)
        best_dist = snap_px
        best_t = t
        for sig in self._signals:
            for ts in sig.timestamps:
                tx = self._time_to_x(ts, w)
                dist = abs(tx - target_x)
                if dist < best_dist:
                    best_dist = dist
                    best_t = ts
        return best_t

    def _zoom_around(self, center: float, factor: float) -> None:
        left = center - self._time_start
        right = self._time_end - center
        self._time_start = center - left * factor
        self._time_end = center + right * factor
        self._schedule_repaint()

    def _schedule_repaint(self) -> None:
        if not self._repaint_timer.isActive():
            self._repaint_timer.start()

    # ── Mouse / keyboard events ───────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_origin_x = event.position().x()
            self._pan_time_start = self._time_start
            self._pan_time_end = self._time_end
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            t = self._x_to_time(event.position().x())
            t = self._snap_cursor(t)

            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._cursor2_time = t
                self._cursor2_active = True
                self.cursor2_moved.emit(t)
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Start selection
                self._selecting = True
                self._sel_start = t
                self._sel_end = t
            else:
                self._cursor_time = t
                self._dragging = True
                self.cursor_moved.emit(t)
            self._schedule_repaint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            dx_pixels = event.position().x() - self._pan_origin_x
            dur = self._pan_time_end - self._pan_time_start
            dt = -(dx_pixels / max(1, self.width())) * dur
            self._time_start = self._pan_time_start + dt
            self._time_end = self._pan_time_end + dt
            self._schedule_repaint()
        elif self._dragging:
            t = self._x_to_time(event.position().x())
            t = self._snap_cursor(t)
            self._cursor_time = t
            self.cursor_moved.emit(t)
            self._schedule_repaint()
        elif self._selecting:
            self._sel_end = self._x_to_time(event.position().x())
            self.selection_changed.emit(self._sel_start, self._sel_end)
            self._schedule_repaint()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._selecting = False

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        pos_x = event.position().x()
        center_t = self._x_to_time(pos_x)
        delta = event.angleDelta().y()
        if delta == 0:
            return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 0.95 if delta > 0 else 1.05  # fine zoom
        else:
            factor = 0.8 if delta > 0 else 1.25

        self._zoom_around(center_t, factor)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        t = self._x_to_time(event.position().x())

        add_marker_act = menu.addAction("Add Marker Here")
        clear_cursor2_act = menu.addAction("Clear Secondary Cursor")
        clear_sel_act = menu.addAction("Clear Selection")
        menu.addSeparator()
        zoom_sel_act = menu.addAction("Zoom to Selection")

        action = menu.exec(event.globalPos())
        if action == add_marker_act:
            name, ok = QInputDialog.getText(self, "Marker Name", "Name:", text=f"M{len(self._markers) + 1}")
            if ok and name:
                self._markers.append(Marker(name=name, time=t))
                self._schedule_repaint()
        elif action == clear_cursor2_act:
            self._cursor2_time = None
            self._schedule_repaint()
        elif action == clear_sel_act:
            self._sel_start = None
            self._sel_end = None
            self._schedule_repaint()
        elif action == zoom_sel_act:
            self.zoom_selection()


# ── Signal Name Tree ─────────────────────────────────────────────────────


class _SignalTree(QTreeWidget):
    """Hierarchical signal tree with module grouping, icons, radix selectors,
    context menu, and drag-and-drop reordering."""

    radix_changed = Signal(int, str)
    signal_reordered = Signal(int, int)  # from_index, to_index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Signal", "Value", "Radix"])
        self.setColumnWidth(0, 170)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 70)
        self.setIndentation(16)
        self.setAlternatingRowColors(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

        mono = QFont("JetBrains Mono", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(mono)

        self.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {_BG};
                alternate-background-color: {_CRUST};
                color: {_TEXT};
                border: none;
                outline: none;
            }}
            QTreeWidget::item {{
                height: {_SIGNAL_ROW_HEIGHT}px;
                border-bottom: 1px solid {_GRID};
            }}
            QTreeWidget::item:selected {{
                background-color: {_SURFACE1};
            }}
            QHeaderView::section {{
                background-color: {_MANTLE};
                color: {_SUBTEXT};
                border: 1px solid {_GRID};
                padding: 3px;
                font-size: 10px;
            }}
        """)

        self._signals: list[SignalData] = []
        self._group_items: dict[str, QTreeWidgetItem] = {}

    def set_signals(self, signals: list[SignalData]) -> None:
        self._signals = signals
        self.clear()
        self._group_items.clear()

        for idx, sig in enumerate(signals):
            # Determine parent (group or module hierarchy)
            parts = sig.name.rsplit(".", 1)
            parent: QTreeWidgetItem | QTreeWidget
            if sig.group:
                parent = self._get_or_create_group(sig.group)
            elif len(parts) > 1:
                parent = self._get_or_create_group(parts[0])
            else:
                parent = self

            item = QTreeWidgetItem(parent, [sig.name.split(".")[-1], "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            item.setForeground(0, QColor(sig.color))
            icon_color = _ICON_COLORS.get(sig.kind, sig.color)
            item.setIcon(0, QIcon(_make_signal_icon(icon_color, sig.kind)))

            # Radix combo
            combo = QComboBox()
            combo.addItems(_RADIX_LIST)
            combo.setCurrentText(sig.radix.value)
            combo.setFixedHeight(22)
            combo.setStyleSheet(f"""
                QComboBox {{
                    background: {_SURFACE0};
                    color: {_TEXT};
                    border: 1px solid {_GRID};
                    font-size: 9px;
                    padding: 1px 4px;
                }}
            """)
            combo.currentTextChanged.connect(lambda text, i=idx: self.radix_changed.emit(i, text))
            if isinstance(parent, QTreeWidgetItem):
                self.setItemWidget(item, 2, combo)
            else:
                self.setItemWidget(item, 2, combo)

        self.expandAll()

    def _get_or_create_group(self, name: str) -> QTreeWidgetItem:
        if name in self._group_items:
            return self._group_items[name]
        item = QTreeWidgetItem(self, [name, "", ""])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
        item.setExpanded(True)
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        item.setForeground(0, QColor(_SUBTEXT))
        self._group_items[name] = item
        return item

    def update_cursor_values(self, signals: list[SignalData], cursor_time: float) -> None:
        """Update the Value column for all signal items."""
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            idx = item.data(0, Qt.ItemDataRole.UserRole)
            if idx is not None and 0 <= idx < len(signals):
                sig = signals[idx]
                val = _value_at_time(sig, cursor_time)
                display = _format_value(val, sig.radix) if val else ""
                item.setText(1, display)
                item.setForeground(1, QColor(sig.color))
            it += 1

    def _context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        menu = QMenu(self)

        add_group = menu.addAction("Add to Group...")
        remove_act = menu.addAction("Remove Signal")
        menu.addSeparator()
        color_act = menu.addAction("Change Color...")
        radix_menu = menu.addMenu("Change Radix")
        for r in Radix:
            radix_menu.addAction(r.value)
        menu.addSeparator()
        divider_act = menu.addAction("Insert Divider")
        copy_act = menu.addAction("Copy Name")

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if action is None:
            return
        if item is None:
            return

        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if action == copy_act and idx is not None and idx < len(self._signals):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._signals[idx].name)
        elif action == remove_act and idx is not None:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                self.takeTopLevelItem(self.indexOfTopLevelItem(item))
        elif action == add_group:
            name, ok = QInputDialog.getText(self, "Group Name", "Group:")
            if ok and name and idx is not None and idx < len(self._signals):
                self._signals[idx].group = name
                self.set_signals(self._signals)
        elif action.text() in _RADIX_LIST and idx is not None:
            self.radix_changed.emit(idx, action.text())




# ── Value Panel ──────────────────────────────────────────────────────────


class _ValuePanel(QWidget):
    """Thin middle column showing the current value at cursor for each signal."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._values: list[tuple[str, str]] = []  # (display_value, color_hex)
        self._scroll_offset: int = 0
        self._font = QFont("JetBrains Mono", 9)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._fm = QFontMetrics(self._font)

    def set_values(self, values: list[tuple[str, str]]) -> None:
        self._values = values
        # Auto-size width to fit longest value
        max_w = 80
        for v, _ in values:
            w = self._fm.horizontalAdvance(v) + 16
            if w > max_w:
                max_w = w
        self.setFixedWidth(min(max_w, 250))
        self.update()

    def set_scroll_offset(self, offset: int) -> None:
        self._scroll_offset = offset
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_MANTLE))
        p.setFont(self._font)

        # Header
        p.fillRect(0, 0, w, _RULER_HEIGHT, QColor(_CRUST))
        p.setPen(QPen(QColor(_SUBTEXT)))
        p.drawText(8, _RULER_HEIGHT - 10, "Value")
        p.setPen(QPen(QColor(_GRID)))
        p.drawLine(0, _RULER_HEIGHT, w, _RULER_HEIGHT)

        y_base = _RULER_HEIGHT - self._scroll_offset
        for i, (val, color) in enumerate(self._values):
            y = y_base + i * _SIGNAL_ROW_HEIGHT
            if y + _SIGNAL_ROW_HEIGHT < _RULER_HEIGHT or y > h:
                continue
            p.setPen(QPen(QColor(color)))
            p.drawText(8, y + _SIGNAL_ROW_HEIGHT // 2 + self._fm.ascent() // 2 - 1, val)
            p.setPen(QPen(QColor(_GRID), 0.5))
            p.drawLine(0, y + _SIGNAL_ROW_HEIGHT, w, y + _SIGNAL_ROW_HEIGHT)

        # Right border
        p.setPen(QPen(QColor(_GRID), 1.0))
        p.drawLine(w - 1, 0, w - 1, h)
        p.end()


# ── Main WaveformPanel dock widget ───────────────────────────────────────


class WaveformPanel(QDockWidget):
    """Dock widget combining signal tree, value panel, waveform canvas,
    toolbar, and status bar into a Vivado-quality waveform viewer."""

    def __init__(self, title: str = "Waveform Viewer", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setMinimumSize(600, 300)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────
        self._toolbar = self._build_toolbar()
        root.addWidget(self._toolbar)

        # ── Main body: signal tree | value panel | canvas ─────────────
        body = QSplitter(Qt.Orientation.Horizontal)

        self._signal_tree = _SignalTree()
        body.addWidget(self._signal_tree)

        self._value_panel = _ValuePanel()
        body.addWidget(self._value_panel)

        # Canvas + vertical scrollbar
        canvas_area = QWidget()
        canvas_layout = QHBoxLayout(canvas_area)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self._canvas = _WaveformCanvas()
        canvas_layout.addWidget(self._canvas)

        self._vscroll = QScrollBar(Qt.Orientation.Vertical)
        self._vscroll.setStyleSheet(f"""
            QScrollBar:vertical {{
                background: {_CRUST};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background: {_SURFACE1};
                min-height: 20px;
                border-radius: 4px;
            }}
        """)
        canvas_layout.addWidget(self._vscroll)

        body.addWidget(canvas_area)
        body.setSizes([200, 120, 600])
        body.setStretchFactor(2, 1)
        root.addWidget(body)

        # ── Status bar ────────────────────────────────────────────────
        self._statusbar = QStatusBar()
        self._statusbar.setStyleSheet(f"""
            QStatusBar {{
                background: {_MANTLE};
                color: {_SUBTEXT};
                border-top: 1px solid {_GRID};
                font-size: 10px;
                padding: 2px 8px;
            }}
        """)
        self._status_cursor = QLabel("Cursor: 0")
        self._status_delta = QLabel("")
        self._status_freq = QLabel("")
        self._status_count = QLabel("Signals: 0")
        self._status_file = QLabel("")

        for lbl in (self._status_cursor, self._status_delta, self._status_freq,
                     self._status_count, self._status_file):
            lbl.setStyleSheet(f"color: {_SUBTEXT}; padding: 0 8px;")
            self._statusbar.addWidget(lbl)

        root.addWidget(self._statusbar)
        self.setWidget(container)

        # ── Internal state ────────────────────────────────────────────
        self._signals: list[SignalData] = []
        self._color_idx: int = 0
        self._selected_signal: int = -1
        self._loaded_file: str = ""

        # ── Wire signals ──────────────────────────────────────────────
        self._canvas.cursor_moved.connect(self._on_cursor_moved)
        self._canvas.cursor2_moved.connect(self._on_cursor2_moved)
        self._signal_tree.radix_changed.connect(self._on_radix_changed)
        self._signal_tree.currentItemChanged.connect(self._on_signal_selected)
        self._vscroll.valueChanged.connect(self._on_vscroll)

    # ── Toolbar construction ──────────────────────────────────────────

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setStyleSheet(f"""
            QToolBar {{
                background: {_MANTLE};
                border-bottom: 1px solid {_GRID};
                padding: 2px 4px;
                spacing: 2px;
            }}
            QToolButton {{
                background: {_SURFACE0};
                color: {_TEXT};
                border: 1px solid {_GRID};
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 11px;
                min-width: 24px;
            }}
            QToolButton:hover {{
                background: {_SURFACE1};
            }}
            QToolButton:pressed {{
                background: {_SURFACE2};
            }}
        """)

        def _btn(text: str, tip: str, slot) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tb.addWidget(b)
            return b

        _btn("+", "Zoom In (scroll up)", lambda: self._canvas.zoom_in())
        _btn("\u2013", "Zoom Out (scroll down)", lambda: self._canvas.zoom_out())
        _btn("Fit", "Zoom to Fit All", lambda: self._canvas.zoom_fit())
        _btn("Sel", "Zoom to Selection", lambda: self._canvas.zoom_selection())
        tb.addSeparator()
        _btn("|<", "Go to Start", lambda: self._canvas.go_to_start())
        _btn(">|", "Go to End", lambda: self._canvas.go_to_end())
        _btn("C", "Go to Cursor", lambda: self._canvas.go_to_cursor())
        tb.addSeparator()
        _btn("<E", "Previous Edge", lambda: self._navigate_edge(-1))
        _btn("E>", "Next Edge", lambda: self._navigate_edge(1))
        _btn("<R", "Previous Rising Edge", lambda: self._navigate_edge(-1, "rising"))
        _btn("F>", "Next Falling Edge", lambda: self._navigate_edge(1, "falling"))
        tb.addSeparator()
        _btn("Snap", "Save Snapshot (PNG)", self._save_snapshot)
        _btn("Save", "Save Config (.wcfg)", self._save_config)
        _btn("Load", "Load Config (.wcfg)", self._load_config)
        tb.addSeparator()
        _btn("+ Sig", "Add Signals", self._add_signals_dialog)

        return tb

    # ── Public API ────────────────────────────────────────────────────

    def load_vcd(self, path: str) -> None:
        """Load a VCD/FST file and display its signals."""
        from openforge.waveform.loader import load_waveform, SignalType
        from pathlib import Path

        file_path = Path(path)
        if not file_path.exists():
            return

        try:
            data = load_waveform(file_path)
        except Exception:
            # Parsing failed -- leave the viewer in its current state
            return

        self.clear()

        for sig in data.signals:
            values = [vc.value for vc in sig.changes]
            timestamps = [float(vc.time * data.timescale_magnitude) for vc in sig.changes]

            if not values or not timestamps:
                continue

            # Determine signal kind
            if sig.signal_type == SignalType.REAL:
                self.add_analog_signal(
                    name=sig.full_name,
                    values=values,
                    timestamps=timestamps,
                    group=sig.scope,
                )
            elif sig.width > 1:
                self.add_signal(
                    name=sig.full_name,
                    values=values,
                    timestamps=timestamps,
                    kind=SignalKind.BUS,
                    group=sig.scope,
                )
            else:
                self.add_signal(
                    name=sig.full_name,
                    values=values,
                    timestamps=timestamps,
                    kind=SignalKind.SINGLE_BIT,
                    group=sig.scope,
                )

        # Update status
        self._loaded_file = str(file_path)
        self._status_file.setText(file_path.name)

    def add_signal(
        self,
        name: str,
        values: list[str],
        timestamps: list[float],
        kind: SignalKind = SignalKind.SINGLE_BIT,
        group: str = "",
    ) -> None:
        """Add a signal trace to the viewer."""
        color = _SIGNAL_COLORS[self._color_idx % len(_SIGNAL_COLORS)]
        self._color_idx += 1

        # Auto-detect kind if not specified
        if kind == SignalKind.SINGLE_BIT:
            if any(len(v) > 1 for v in values if v not in ("x", "z", "X", "Z")):
                kind = SignalKind.BUS

        sig = SignalData(
            name=name, values=values, timestamps=timestamps,
            color=color, kind=kind, group=group,
        )
        self._signals.append(sig)
        self._refresh()

    def add_analog_signal(
        self,
        name: str,
        values: list[str],
        timestamps: list[float],
        group: str = "",
        y_min: float = 0.0,
        y_max: float = 1.0,
        auto_scale: bool = True,
    ) -> None:
        """Add an analog signal trace."""
        color = _SIGNAL_COLORS[self._color_idx % len(_SIGNAL_COLORS)]
        self._color_idx += 1
        sig = SignalData(
            name=name, values=values, timestamps=timestamps,
            color=color, kind=SignalKind.ANALOG, group=group,
            analog_min=y_min, analog_max=y_max, analog_auto=auto_scale,
        )
        self._signals.append(sig)
        self._refresh()

    def clear(self) -> None:
        """Remove all signals from the viewer."""
        self._signals.clear()
        self._color_idx = 0
        self._selected_signal = -1
        self._canvas.set_signals([])
        self._signal_tree.set_signals([])
        self._value_panel.set_values([])
        self._update_statusbar()

    # ── Internal ──────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._canvas.set_signals(self._signals)
        self._signal_tree.set_signals(self._signals)
        self._update_vscroll()
        self._update_statusbar()
        self._update_values()

    def _update_values(self) -> None:
        ct = self._canvas.cursor_time
        vals: list[tuple[str, str]] = []
        for sig in self._signals:
            raw = _value_at_time(sig, ct)
            display = _format_value(raw, sig.radix) if raw else ""
            vals.append((display, sig.color))
        self._value_panel.set_values(vals)

    def _update_vscroll(self) -> None:
        content_h = self._canvas.total_content_height
        view_h = self._canvas.height()
        self._vscroll.setRange(0, max(0, content_h - view_h))
        self._vscroll.setPageStep(view_h)

    def _update_statusbar(self) -> None:
        ct = self._canvas.cursor_time
        self._status_cursor.setText(f"Cursor: {_format_time(ct)}")
        self._status_count.setText(f"Signals: {len(self._signals)}")

        c2 = self._canvas.cursor2_time
        if c2 is not None:
            delta = abs(ct - c2)
            self._status_delta.setText(f"\u0394: {_format_time(delta)}")
            if delta > 0:
                freq = 1.0 / delta
                if freq >= 1e9:
                    self._status_freq.setText(f"f: {freq/1e9:.3f} GHz")
                elif freq >= 1e6:
                    self._status_freq.setText(f"f: {freq/1e6:.3f} MHz")
                elif freq >= 1e3:
                    self._status_freq.setText(f"f: {freq/1e3:.3f} kHz")
                else:
                    self._status_freq.setText(f"f: {freq:.3f} Hz")
            else:
                self._status_freq.setText("")
        else:
            self._status_delta.setText("")
            self._status_freq.setText("")

    def _on_cursor_moved(self, t: float) -> None:
        self._update_values()
        self._signal_tree.update_cursor_values(self._signals, t)
        self._update_statusbar()

    def _on_cursor2_moved(self, t: float) -> None:
        self._update_statusbar()

    def _on_radix_changed(self, idx: int, radix_text: str) -> None:
        if 0 <= idx < len(self._signals):
            radix_map = {r.value: r for r in Radix}
            self._signals[idx].radix = radix_map.get(radix_text, Radix.HEX)
            self._canvas.update()
            self._update_values()

    def _on_signal_selected(self, current, _previous) -> None:
        if current is not None:
            idx = current.data(0, Qt.ItemDataRole.UserRole)
            if idx is not None:
                self._selected_signal = idx

    def _on_vscroll(self, value: int) -> None:
        self._canvas.set_scroll_offset(value)
        self._value_panel.set_scroll_offset(value)

    def _navigate_edge(self, direction: int, edge: str = "any") -> None:
        self._canvas.find_edge(self._selected_signal, direction, edge)
        self._update_values()
        self._update_statusbar()

    def _save_snapshot(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Snapshot", "waveform.png", "PNG Images (*.png)"
        )
        if path:
            self._canvas.save_snapshot(path)

    def _save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Waveform Config", "waveform.wcfg",
            "Waveform Config (*.wcfg)"
        )
        if path:
            import json
            cfg = {
                "signals": [
                    {"name": s.name, "color": s.color, "radix": s.radix.value,
                     "kind": s.kind.value, "group": s.group}
                    for s in self._signals
                ],
                "markers": [
                    {"name": m.name, "time": m.time, "color": m.color}
                    for m in self._canvas._markers
                ],
                "view": {
                    "time_start": self._canvas._time_start,
                    "time_end": self._canvas._time_end,
                },
            }
            with open(path, "w") as f:
                json.dump(cfg, f, indent=2)

    def _load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Waveform Config", "",
            "Waveform Config (*.wcfg)"
        )
        if path:
            import json
            with open(path) as f:
                cfg = json.load(f)
            # Restore signal display settings
            for sc in cfg.get("signals", []):
                for sig in self._signals:
                    if sig.name == sc["name"]:
                        sig.color = sc.get("color", sig.color)
                        radix_map = {r.value: r for r in Radix}
                        sig.radix = radix_map.get(sc.get("radix", ""), sig.radix)
                        sig.group = sc.get("group", "")
            # Restore markers
            self._canvas._markers = [
                Marker(name=m["name"], time=m["time"], color=m.get("color", _MARKER_COLOR))
                for m in cfg.get("markers", [])
            ]
            # Restore view
            view = cfg.get("view", {})
            if "time_start" in view and "time_end" in view:
                self._canvas._time_start = view["time_start"]
                self._canvas._time_end = view["time_end"]
            self._refresh()

    def _add_signals_dialog(self) -> None:
        """Placeholder for signal browser dialog."""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Add Signals",
            "Signal browser not yet connected to VCD parser.\n"
            "Use add_signal() API to add signals programmatically."
        )
