"""Production-grade waveform viewer widget.

Implements a GTKWave / Surfer / SimVision style waveform viewer using
custom ``QPainter`` paint events for millions-of-transitions performance.

``WaveformView`` is the canvas; ``WaveformPanel`` is the parent widget with
toolbar, scope tree, signal list, and status bar.
"""

from __future__ import annotations

import bisect
import time as _time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QLineEdit,
    QMenu,
    QSplitter,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.format.bus_decoder import BusDecoder
    from openforge.format.waveform import SignalKind, Waveform, WaveSignal, WaveTransition

    _HAS_MODEL = True
except Exception:  # pragma: no cover
    Waveform = object  # type: ignore
    WaveSignal = object  # type: ignore
    WaveTransition = object  # type: ignore
    SignalKind = object  # type: ignore
    BusDecoder = object  # type: ignore
    _HAS_MODEL = False


# ───────── Theme ─────────
BG = QColor("#0b1020")
GRID = QColor("#18213b")
GRID_MAJOR = QColor("#263355")
AXIS = QColor("#8892b0")
SIG_HIGH = QColor("#5eead4")
SIG_LOW = QColor("#22c55e")
SIG_X = QColor("#ef4444")
SIG_Z = QColor("#eab308")
BUS = QColor("#7dd3fc")
BUS_TEXT = QColor("#e0f2fe")
NAME_BG = QColor("#11162a")
NAME_FG = QColor("#cdd6f4")
CURSOR_A = QColor("#f38ba8")
CURSOR_B = QColor("#89b4fa")
CURSOR_AUX = QColor("#f9e2af")
MARKER = QColor("#a6e3a1")
SELECTION = QColor(137, 180, 250, 60)

DEFAULT_SIG_COLORS = [
    QColor("#5eead4"),
    QColor("#fbbf24"),
    QColor("#f472b6"),
    QColor("#60a5fa"),
    QColor("#a78bfa"),
    QColor("#34d399"),
]


@dataclass
class DisplaySignal:
    full_path: str
    color: QColor = field(default_factory=lambda: QColor(SIG_HIGH))
    radix: str = "hex"  # hex / dec / bin / oct / ascii
    height: int = 26
    group: str = ""
    visible: bool = True


@dataclass
class Cursor:
    time: int = 0
    color: QColor = field(default_factory=lambda: QColor(CURSOR_AUX))
    name: str = ""


@dataclass
class Marker:
    time: int
    name: str
    color: QColor = field(default_factory=lambda: QColor(MARKER))


# ──────────────────── WaveformView ────────────────────
class WaveformView(QWidget):
    """Custom-painted waveform canvas."""

    cursorMoved = Signal(int)  # cursor A time
    statusChanged = Signal(str)

    NAME_COL_DEFAULT = 220
    TIME_AXIS_H = 26
    VALUE_COL_W = 90

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self._wf: Waveform | None = None
        self._signals: list[DisplaySignal] = []
        self._groups_collapsed: set[str] = set()
        self._decoder = BusDecoder() if _HAS_MODEL else None

        # viewport in *waveform time*
        self._t_start: float = 0.0
        self._t_end: float = 1000.0

        self._name_col_w = self.NAME_COL_DEFAULT
        self._cursor_a = Cursor(time=0, color=QColor(CURSOR_A), name="A")
        self._cursor_b = Cursor(time=0, color=QColor(CURSOR_B), name="B")
        self._aux_cursors: dict[int, Cursor] = {}
        self._markers: list[Marker] = []

        self._drag_mode: str = ""  # "cursor_a" "cursor_b" "pan" "select" "resize_name"
        self._drag_start: QPoint = QPoint()
        self._drag_start_t: float = 0.0
        self._selection: tuple[int, int] | None = None

        self._selected_signal_idx: int = -1
        self._drag_sig_from: int = -1

        self._font = QFont("Consolas", 9)
        self._fm = QFontMetrics(self._font)

        self._last_paint_ms = 0.0

    # ──────────── Data API ────────────
    def set_waveform(self, wf: Waveform | None) -> None:
        self._wf = wf
        self._signals = []
        if wf is not None:
            self._t_start = 0.0
            self._t_end = float(max(1, getattr(wf, "end_time", 1)))
        self.update()

    def add_signal(self, full_path: str) -> None:
        if self._wf is None or full_path not in getattr(self._wf, "signals", {}):
            return
        if any(s.full_path == full_path for s in self._signals):
            return
        color = DEFAULT_SIG_COLORS[len(self._signals) % len(DEFAULT_SIG_COLORS)]
        self._signals.append(DisplaySignal(full_path=full_path, color=QColor(color)))
        self.update()

    def remove_signal(self, full_path: str) -> None:
        self._signals = [s for s in self._signals if s.full_path != full_path]
        self.update()

    def clear_signals(self) -> None:
        self._signals = []
        self.update()

    # ──────────── Helpers ────────────
    def _canvas_rect(self) -> QRect:
        r = self.rect()
        return QRect(
            self._name_col_w + self.VALUE_COL_W,
            self.TIME_AXIS_H,
            max(1, r.width() - self._name_col_w - self.VALUE_COL_W),
            max(1, r.height() - self.TIME_AXIS_H),
        )

    def _t_to_x(self, t: float) -> int:
        cr = self._canvas_rect()
        span = max(1e-9, self._t_end - self._t_start)
        return cr.left() + int((t - self._t_start) / span * cr.width())

    def _x_to_t(self, x: int) -> float:
        cr = self._canvas_rect()
        if cr.width() <= 0:
            return self._t_start
        span = self._t_end - self._t_start
        return self._t_start + (x - cr.left()) / cr.width() * span

    def _signal_row_rect(self, i: int) -> QRect:
        cr = self._canvas_rect()
        y = cr.top() + 4 + sum(s.height + 2 for s in self._signals[:i])
        return QRect(0, y, self.width(), self._signals[i].height if i < len(self._signals) else 0)

    def _signal_at_y(self, y: int) -> int:
        cr = self._canvas_rect()
        yy = cr.top() + 4
        for i, s in enumerate(self._signals):
            if yy <= y < yy + s.height:
                return i
            yy += s.height + 2
        return -1

    # ──────────── Paint ────────────
    def paintEvent(self, ev) -> None:  # noqa: N802
        t0 = _time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), BG)
        self._paint_name_col(p)
        self._paint_time_axis(p)
        self._paint_grid(p)
        self._paint_signals(p)
        self._paint_cursors(p)
        self._paint_markers(p)
        self._paint_selection(p)
        p.end()
        self._last_paint_ms = (_time.perf_counter() - t0) * 1000.0

    def _paint_name_col(self, p: QPainter) -> None:
        r = QRect(0, 0, self._name_col_w + self.VALUE_COL_W, self.height())
        p.fillRect(r, NAME_BG)
        p.setPen(QPen(GRID_MAJOR))
        p.drawLine(self._name_col_w, 0, self._name_col_w, self.height())
        p.drawLine(
            self._name_col_w + self.VALUE_COL_W,
            0,
            self._name_col_w + self.VALUE_COL_W,
            self.height(),
        )
        p.setFont(self._font)
        cr = self._canvas_rect()
        y = cr.top() + 4
        for i, s in enumerate(self._signals):
            row = QRect(0, y, self._name_col_w, s.height)
            if i == self._selected_signal_idx:
                p.fillRect(row, QColor(255, 255, 255, 14))
            p.setPen(QPen(NAME_FG))
            name = s.full_path.rsplit(".", 1)[-1]
            sig = self._wf.signals.get(s.full_path) if self._wf else None
            if sig and getattr(sig, "width", 1) > 1:
                name = f"{name}[{sig.msb}:{sig.lsb}]"
            p.drawText(
                row.adjusted(6, 0, -4, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                name,
            )
            # Value at cursor A
            if self._wf and sig:
                val = self._wf.signal_at_time(s.full_path, int(self._cursor_a.time))
                txt = self._format_value(val, getattr(sig, "width", 1), s.radix)
                vrect = QRect(self._name_col_w, y, self.VALUE_COL_W, s.height)
                p.setPen(QPen(s.color))
                p.drawText(
                    vrect.adjusted(4, 0, -4, 0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    txt,
                )
            y += s.height + 2

    def _paint_time_axis(self, p: QPainter) -> None:
        cr = self._canvas_rect()
        axis = QRect(cr.left(), 0, cr.width(), self.TIME_AXIS_H)
        p.fillRect(axis, QColor("#0f1630"))
        p.setPen(QPen(GRID_MAJOR))
        p.drawLine(cr.left(), self.TIME_AXIS_H - 1, cr.right(), self.TIME_AXIS_H - 1)
        p.setFont(self._font)
        p.setPen(QPen(AXIS))
        span = self._t_end - self._t_start
        if span <= 0:
            return
        # pick a tick step ~ every 80 px
        target_px = 80
        raw_step = span * target_px / max(1, cr.width())
        step = self._nice_step(raw_step)
        t = (int(self._t_start // step)) * step
        while t <= self._t_end:
            x = self._t_to_x(t)
            p.drawLine(x, self.TIME_AXIS_H - 6, x, self.TIME_AXIS_H - 1)
            label = self._format_time(t)
            p.drawText(x + 3, self.TIME_AXIS_H - 8, label)
            t += step

    def _paint_grid(self, p: QPainter) -> None:
        cr = self._canvas_rect()
        p.setPen(QPen(GRID))
        span = self._t_end - self._t_start
        if span <= 0:
            return
        target_px = 80
        raw_step = span * target_px / max(1, cr.width())
        step = self._nice_step(raw_step)
        t = (int(self._t_start // step)) * step
        while t <= self._t_end:
            x = self._t_to_x(t)
            p.drawLine(x, cr.top(), x, cr.bottom())
            t += step

    def _paint_signals(self, p: QPainter) -> None:
        if self._wf is None:
            p.setPen(QPen(AXIS))
            p.setFont(self._font)
            p.drawText(
                self._canvas_rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Open a VCD or FST file to begin...",
            )
            return
        cr = self._canvas_rect()
        p.setClipRect(cr)
        y = cr.top() + 4
        for _i, disp in enumerate(self._signals):
            sig = self._wf.signals.get(disp.full_path)
            trs = self._wf.data.get(disp.full_path, [])
            if sig is None:
                y += disp.height + 2
                continue
            row = QRect(cr.left(), y, cr.width(), disp.height)
            if getattr(sig, "width", 1) == 1:
                self._paint_bit_signal(p, row, trs, disp)
            else:
                self._paint_bus_signal(p, row, trs, disp, sig)
            y += disp.height + 2
        p.setClipping(False)

    def _paint_bit_signal(self, p: QPainter, row: QRect, trs: list, disp: DisplaySignal) -> None:
        top = row.top() + 3
        bot = row.bottom() - 3
        mid = (top + bot) // 2
        pen = QPen(disp.color, 1.5)
        p.setPen(pen)
        if not trs:
            p.drawLine(row.left(), mid, row.right(), mid)
            return
        # find starting index via bisect on times
        times = [t.time for t in trs]
        start_idx = max(0, bisect.bisect_right(times, self._t_start) - 1)
        prev_x = row.left()
        prev_val = trs[start_idx].value
        prev_y = self._bit_y(prev_val, top, bot, mid)
        for j in range(start_idx + 1, len(trs)):
            t = trs[j]
            if t.time > self._t_end:
                break
            x = self._t_to_x(t.time)
            if x < row.left():
                prev_x = row.left()
                prev_val = t.value
                prev_y = self._bit_y(prev_val, top, bot, mid)
                continue
            # draw horizontal to new x at prev level
            self._draw_bit_seg(p, prev_x, x, prev_y, prev_val, top, bot, disp.color)
            # transition
            new_y = self._bit_y(t.value, top, bot, mid)
            p.setPen(QPen(disp.color, 1.5))
            p.drawLine(x, prev_y, x, new_y)
            prev_x = x
            prev_val = t.value
            prev_y = new_y
        self._draw_bit_seg(p, prev_x, row.right(), prev_y, prev_val, top, bot, disp.color)

    def _bit_y(self, val, top, bot, mid) -> int:
        if val == 1:
            return top
        if val == 0:
            return bot
        return mid

    def _draw_bit_seg(self, p, x1, x2, y, val, top, bot, color) -> None:
        if x2 <= x1:
            return
        if val in (0, 1):
            p.setPen(QPen(color, 1.5))
            p.drawLine(x1, y, x2, y)
        else:
            # X or Z: hatched band
            col = SIG_X if str(val).lower() == "x" else SIG_Z
            r = QRect(x1, top, max(1, x2 - x1), bot - top)
            p.fillRect(r, QColor(col.red(), col.green(), col.blue(), 60))
            p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
            p.drawLine(x1, top, x2, top)
            p.drawLine(x1, bot, x2, bot)

    def _paint_bus_signal(
        self, p: QPainter, row: QRect, trs: list, disp: DisplaySignal, sig
    ) -> None:
        top = row.top() + 3
        bot = row.bottom() - 3
        if not trs:
            p.setPen(QPen(disp.color))
            p.drawLine(row.left(), (top + bot) // 2, row.right(), (top + bot) // 2)
            return
        times = [t.time for t in trs]
        start_idx = max(0, bisect.bisect_right(times, self._t_start) - 1)
        diamond = 4
        min_box_w = 14
        p.setFont(self._font)
        for j in range(start_idx, len(trs)):
            t = trs[j]
            if t.time > self._t_end:
                break
            x1 = max(row.left(), self._t_to_x(t.time))
            if j + 1 < len(trs):
                x2 = min(row.right(), self._t_to_x(trs[j + 1].time))
            else:
                x2 = row.right()
            if x2 <= x1:
                continue
            # bus box with diamonds
            path = QPainterPath()
            path.moveTo(x1 + diamond, top)
            path.lineTo(x2 - diamond, top)
            path.lineTo(x2, (top + bot) // 2)
            path.lineTo(x2 - diamond, bot)
            path.lineTo(x1 + diamond, bot)
            path.lineTo(x1, (top + bot) // 2)
            path.closeSubpath()
            fill = QColor(disp.color.red(), disp.color.green(), disp.color.blue(), 40)
            val_is_xz = isinstance(t.value, str) and any(c in "xXzZ" for c in t.value)
            if val_is_xz:
                fill = QColor(SIG_X.red(), SIG_X.green(), SIG_X.blue(), 60)
            p.fillPath(path, QBrush(fill))
            p.setPen(QPen(disp.color, 1.2))
            p.drawPath(path)
            # label if room
            box_w = x2 - x1
            if box_w >= min_box_w:
                lbl = self._format_value(t.value, getattr(sig, "width", 1), disp.radix)
                elided = self._fm.elidedText(lbl, Qt.TextElideMode.ElideRight, box_w - 6)
                p.setPen(QPen(BUS_TEXT))
                p.drawText(
                    QRect(x1 + 3, top, box_w - 6, bot - top), Qt.AlignmentFlag.AlignCenter, elided
                )

    def _paint_cursors(self, p: QPainter) -> None:
        cr = self._canvas_rect()
        p.setClipRect(cr)
        for cur in [self._cursor_a, self._cursor_b, *self._aux_cursors.values()]:
            if cur.time < self._t_start or cur.time > self._t_end:
                continue
            x = self._t_to_x(cur.time)
            p.setPen(QPen(cur.color, 1.5, Qt.PenStyle.SolidLine))
            p.drawLine(x, cr.top(), x, cr.bottom())
            if cur.name:
                p.fillRect(QRect(x - 8, cr.top(), 16, 14), cur.color)
                p.setPen(QPen(Qt.GlobalColor.black))
                p.drawText(QRect(x - 8, cr.top(), 16, 14), Qt.AlignmentFlag.AlignCenter, cur.name)
        p.setClipping(False)

    def _paint_markers(self, p: QPainter) -> None:
        cr = self._canvas_rect()
        p.setClipRect(cr)
        for m in self._markers:
            if m.time < self._t_start or m.time > self._t_end:
                continue
            x = self._t_to_x(m.time)
            p.setPen(QPen(m.color, 1.0, Qt.PenStyle.DashLine))
            p.drawLine(x, cr.top(), x, cr.bottom())
            if m.name:
                p.setPen(QPen(m.color))
                p.drawText(x + 3, cr.top() + 12, m.name)
        p.setClipping(False)

    def _paint_selection(self, p: QPainter) -> None:
        if not self._selection:
            return
        cr = self._canvas_rect()
        x1 = self._t_to_x(self._selection[0])
        x2 = self._t_to_x(self._selection[1])
        r = QRect(min(x1, x2), cr.top(), abs(x2 - x1), cr.height())
        p.fillRect(r, SELECTION)

    # ──────────── Formatting ────────────
    def _format_value(self, val, width: int, radix: str) -> str:
        if isinstance(val, str):
            if any(c in "xXzZ" for c in val):
                return val
            try:
                iv = int(val, 2)
            except ValueError:
                return val
        else:
            iv = int(val)
        if radix == "hex":
            return f"{iv:0{max(1, (width + 3) // 4)}X}"
        if radix == "dec":
            return str(iv)
        if radix == "bin":
            return f"{iv:0{max(1, width)}b}"
        if radix == "oct":
            return f"{iv:0{max(1, (width + 2) // 3)}o}"
        if radix == "ascii":
            try:
                return chr(iv & 0xFF) if 32 <= (iv & 0xFF) < 127 else f"\\x{iv:02x}"
            except Exception:
                return str(iv)
        return str(iv)

    def _nice_step(self, raw: float) -> float:
        if raw <= 0:
            return 1.0
        import math

        e = math.floor(math.log10(raw))
        base = 10**e
        for m in (1, 2, 5, 10):
            if m * base >= raw:
                return m * base
        return 10 * base

    def _format_time(self, t: float) -> str:
        if self._wf is None:
            return f"{int(t)}"
        ps = int(t) * getattr(self._wf, "timescale_ps", 1000)
        if ps >= 1_000_000_000:
            return f"{ps / 1_000_000_000:.2f}ms"
        if ps >= 1_000_000:
            return f"{ps / 1_000_000:.2f}us"
        if ps >= 1_000:
            return f"{ps / 1_000:.2f}ns"
        return f"{ps}ps"

    # ──────────── Interaction ────────────
    def wheelEvent(self, ev: QWheelEvent) -> None:  # noqa: N802
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # vertical zoom (row height)
            delta = 1 if ev.angleDelta().y() > 0 else -1
            for s in self._signals:
                s.height = max(12, min(80, s.height + delta * 2))
            self.update()
            return
        # time zoom around cursor x
        zoom = 0.85 if ev.angleDelta().y() > 0 else 1.18
        anchor_t = self._x_to_t(ev.position().toPoint().x())
        span = (self._t_end - self._t_start) * zoom
        self._t_start = anchor_t - (anchor_t - self._t_start) * zoom
        self._t_end = self._t_start + span
        self._clamp_view()
        self.update()

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        x = ev.position().toPoint().x()
        y = ev.position().toPoint().y()
        if abs(x - self._name_col_w) <= 3:
            self._drag_mode = "resize_name"
            self._drag_start = ev.position().toPoint()
            return
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._drag_mode = "pan"
            self._drag_start = ev.position().toPoint()
            self._drag_start_t = self._t_start
            return
        if x < self._name_col_w:
            idx = self._signal_at_y(y)
            self._selected_signal_idx = idx
            self._drag_sig_from = idx
            self.update()
            return
        # canvas click
        t = int(self._x_to_t(x))
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._drag_mode = "select"
                self._selection = (t, t)
            else:
                self._drag_mode = "cursor_a"
                self._cursor_a.time = t
                self.cursorMoved.emit(t)
            self.update()
        elif ev.button() == Qt.MouseButton.RightButton:
            self._drag_mode = "cursor_b"
            self._cursor_b.time = t
            self.update()

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        x = ev.position().toPoint().x()
        if self._drag_mode == "resize_name":
            new_w = max(80, min(600, x))
            self._name_col_w = new_w
            self.update()
            return
        if self._drag_mode == "pan":
            dx = x - self._drag_start.x()
            span = self._t_end - self._t_start
            cr = self._canvas_rect()
            shift = -dx / max(1, cr.width()) * span
            self._t_start = self._drag_start_t + shift
            self._t_end = self._t_start + span
            self._clamp_view()
            self.update()
            return
        if self._drag_mode in ("cursor_a", "cursor_b", "select"):
            t = int(self._x_to_t(x))
            if self._drag_mode == "cursor_a":
                self._cursor_a.time = t
                self.cursorMoved.emit(t)
            elif self._drag_mode == "cursor_b":
                self._cursor_b.time = t
            elif self._drag_mode == "select" and self._selection:
                self._selection = (self._selection[0], t)
            self._emit_status()
            self.update()
            return
        self._emit_status(ev.position().toPoint())

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._drag_mode == "select" and self._selection:
            a, b = sorted(self._selection)
            if b > a:
                self._t_start = a
                self._t_end = b
                self._clamp_view()
            self._selection = None
        # drop drag on signal rows = reorder
        if self._drag_sig_from >= 0:
            y = ev.position().toPoint().y()
            dest = self._signal_at_y(y)
            if dest >= 0 and dest != self._drag_sig_from:
                s = self._signals.pop(self._drag_sig_from)
                self._signals.insert(dest, s)
        self._drag_sig_from = -1
        self._drag_mode = ""
        self.update()

    def contextMenuEvent(self, ev) -> None:  # noqa: N802
        idx = self._signal_at_y(ev.pos().y())
        if idx < 0 or ev.pos().x() > self._name_col_w:
            return
        menu = QMenu(self)
        for radix in ("hex", "dec", "bin", "oct", "ascii"):
            act = menu.addAction(f"Radix: {radix}")
            act.triggered.connect(lambda _=False, r=radix, i=idx: self._set_radix(i, r))
        menu.addSeparator()
        col_act = menu.addAction("Pick Color...")
        col_act.triggered.connect(lambda: self._pick_color(idx))
        menu.addSeparator()
        rm = menu.addAction("Remove Signal")
        rm.triggered.connect(lambda: self._remove_idx(idx))
        menu.exec(ev.globalPos())

    def _set_radix(self, i: int, r: str) -> None:
        if 0 <= i < len(self._signals):
            self._signals[i].radix = r
            self.update()

    def _pick_color(self, i: int) -> None:
        if not (0 <= i < len(self._signals)):
            return
        c = QColorDialog.getColor(self._signals[i].color, self, "Signal Color")
        if c.isValid():
            self._signals[i].color = c
            self.update()

    def _remove_idx(self, i: int) -> None:
        if 0 <= i < len(self._signals):
            self._signals.pop(i)
            self.update()

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        k = ev.key()
        mods = ev.modifiers()
        if k == Qt.Key.Key_Plus or k == Qt.Key.Key_Equal:
            self.zoom(0.8)
            return
        if k == Qt.Key.Key_Minus:
            self.zoom(1.25)
            return
        if k == Qt.Key.Key_F:
            self.zoom_fit()
            return
        if k == Qt.Key.Key_Left and mods & Qt.KeyboardModifier.ShiftModifier:
            self._step_edge(-1)
            return
        if k == Qt.Key.Key_Right and mods & Qt.KeyboardModifier.ShiftModifier:
            self._step_edge(1)
            return
        if k == Qt.Key.Key_Left:
            self.pan(-0.1)
            return
        if k == Qt.Key.Key_Right:
            self.pan(0.1)
            return
        if mods & Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_M:
            self.add_marker(int(self._cursor_a.time), f"M{len(self._markers) + 1}")
            return
        if mods & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_1 <= k <= Qt.Key.Key_8:
            n = k - Qt.Key.Key_0
            self._aux_cursors[n] = Cursor(
                time=int(self._cursor_a.time), color=QColor(CURSOR_AUX), name=str(n)
            )
            self.update()
            return
        super().keyPressEvent(ev)

    # ──────────── Ops ────────────
    def zoom(self, factor: float) -> None:
        anchor = (self._t_start + self._t_end) / 2
        span = (self._t_end - self._t_start) * factor
        self._t_start = anchor - span / 2
        self._t_end = anchor + span / 2
        self._clamp_view()
        self.update()

    def zoom_fit(self) -> None:
        if self._wf is None:
            return
        self._t_start = 0
        self._t_end = max(1, getattr(self._wf, "end_time", 1))
        self.update()

    def pan(self, frac: float) -> None:
        span = self._t_end - self._t_start
        self._t_start += span * frac
        self._t_end += span * frac
        self._clamp_view()
        self.update()

    def _clamp_view(self) -> None:
        if self._wf is None:
            return
        end = max(1, getattr(self._wf, "end_time", 1))
        if self._t_end - self._t_start < 2:
            self._t_end = self._t_start + 2
        if self._t_start < 0:
            self._t_end -= self._t_start
            self._t_start = 0
        if self._t_end > end * 1.05:
            shift = self._t_end - end * 1.05
            self._t_start -= shift
            self._t_end -= shift
            if self._t_start < 0:
                self._t_start = 0

    def add_marker(self, time: int, name: str) -> None:
        self._markers.append(Marker(time=time, name=name))
        self.update()

    def _step_edge(self, direction: int) -> None:
        if self._wf is None or not self._signals:
            return
        idx = max(0, self._selected_signal_idx)
        if idx >= len(self._signals):
            return
        trs = self._wf.data.get(self._signals[idx].full_path, [])
        if not trs:
            return
        times = [t.time for t in trs]
        i = bisect.bisect_right(times, int(self._cursor_a.time))
        if direction > 0 and i < len(times):
            self._cursor_a.time = times[i]
        elif direction < 0 and i - 2 >= 0:
            self._cursor_a.time = times[i - 2]
        self.cursorMoved.emit(int(self._cursor_a.time))
        self._emit_status()
        self.update()

    def _emit_status(self, pt: QPoint | None = None) -> None:
        delta = int(self._cursor_b.time - self._cursor_a.time)
        msg = (
            f"A={self._format_time(self._cursor_a.time)}  "
            f"B={self._format_time(self._cursor_b.time)}  "
            f"Δ={self._format_time(abs(delta))}  "
            f"paint={self._last_paint_ms:.1f}ms"
        )
        self.statusChanged.emit(msg)

    # search
    def find_signal_value(self, full_path: str, predicate) -> int | None:
        if self._wf is None:
            return None
        trs = self._wf.data.get(full_path, [])
        for t in trs:
            if predicate(t.value):
                return t.time
        return None


# ──────────────────── WaveformPanel (new) ────────────────────
class WaveformPanel(QWidget):
    """Parent panel with toolbar, scope tree, signal list, and canvas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wf: Waveform | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tb = QToolBar()
        tb.setIconSize(QSize(16, 16))
        root.addWidget(tb)
        act_open = tb.addAction("Open")
        act_open.triggered.connect(self._open_dialog)
        act_reload = tb.addAction("Reload")
        act_reload.triggered.connect(self._reload)
        tb.addSeparator()
        tb.addAction("Zoom Fit", lambda: self.view.zoom_fit())
        tb.addAction("Zoom +", lambda: self.view.zoom(0.8))
        tb.addAction("Zoom -", lambda: self.view.zoom(1.25))
        tb.addSeparator()
        tb.addAction(
            "+Cursor",
            lambda: self.view.add_marker(
                int(self.view._cursor_a.time), f"C{len(self.view._aux_cursors) + 1}"
            ),
        )
        tb.addAction(
            "+Marker",
            lambda: self.view.add_marker(
                int(self.view._cursor_a.time), f"M{len(self.view._markers) + 1}"
            ),
        )
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("Find signal...")
        self._find_edit.setMaximumWidth(240)
        self._find_edit.returnPressed.connect(self._do_find)
        tb.addWidget(self._find_edit)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        side = QWidget()
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(4, 4, 4, 4)
        side_l.setSpacing(4)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_tree_double)
        side_l.addWidget(self.tree, 1)
        splitter.addWidget(side)

        self.view = WaveformView()
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 900])

        self.status = QStatusBar()
        root.addWidget(self.status)
        self.view.statusChanged.connect(self.status.showMessage)

        self._current_path: Path | None = None

    # ──────────── File loading ────────────
    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Waveform",
            "",
            "Waveforms (*.vcd *.fst);;VCD (*.vcd);;FST (*.fst);;All Files (*)",
        )
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        if not _HAS_MODEL:
            self.status.showMessage("Waveform model unavailable")
            return
        try:
            if path.suffix.lower() == ".fst":
                wf = Waveform.parse_fst(str(path))
            else:
                wf = Waveform.parse_vcd(str(path))
        except Exception as e:
            self.status.showMessage(f"Failed to load: {e}")
            return
        self._wf = wf
        self._current_path = path
        self.view.set_waveform(wf)
        self._rebuild_tree()
        self.view.zoom_fit()
        self.status.showMessage(f"Loaded {path.name}: {len(wf.signals)} signals, end={wf.end_time}")

    def _reload(self) -> None:
        if self._current_path:
            self.load_file(self._current_path)

    def _rebuild_tree(self) -> None:
        self.tree.clear()
        if self._wf is None:
            return

        def add_scope(scope, parent_item):
            item = QTreeWidgetItem(parent_item, [scope.name])
            item.setData(0, Qt.ItemDataRole.UserRole, ("scope", scope.name))
            for child in scope.children:
                add_scope(child, item)
            for sig_path in scope.signals:
                sig = self._wf.signals.get(sig_path)
                if not sig:
                    continue
                label = sig.name
                if sig.width > 1:
                    label = f"{sig.name}[{sig.msb}:{sig.lsb}]"
                leaf = QTreeWidgetItem(item, [label])
                leaf.setData(0, Qt.ItemDataRole.UserRole, ("signal", sig_path))
            return item

        for s in self._wf.scopes:
            top = add_scope(s, self.tree)
            top.setExpanded(True)

    def _on_tree_double(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, val = data
        if kind == "signal":
            self.view.add_signal(val)

    def _do_find(self) -> None:
        q = self._find_edit.text().strip()
        if not q or self._wf is None:
            return
        hits = self._wf.search(q)
        if not hits:
            self.status.showMessage(f"No match for '{q}'")
            return
        # add first hit
        self.view.add_signal(hits[0])
        self.status.showMessage(f"Added {hits[0]} (+{len(hits) - 1} more matches)")
