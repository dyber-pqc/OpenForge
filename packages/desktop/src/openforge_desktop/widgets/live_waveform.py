"""Live streaming waveform widget for OpenForge.

Reads VCD as it is being written by the simulator and renders waveforms in
real-time, similar to the live waveform view in commercial tools such as
Synopsys VCS or Cadence Xcelium. The widget is intentionally a plain
``QWidget`` (not a dock) so it can be embedded inside the simulation panel,
inside a tab, or used standalone.

Catppuccin Mocha colours are used by default; ``set_theme(dark=False)``
switches to a light Catppuccin Latte palette.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QFileSystemWatcher,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Catppuccin palettes
# ---------------------------------------------------------------------------

MOCHA = {
    "base": "#1e1e2e",
    "mantle": "#181825",
    "crust": "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "text": "#cdd6f4",
    "subtext1": "#bac2de",
    "subtext0": "#a6adc8",
    "overlay0": "#6c7086",
    "blue": "#89b4fa",
    "lavender": "#b4befe",
    "sapphire": "#74c7ec",
    "sky": "#89dceb",
    "teal": "#94e2d5",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "peach": "#fab387",
    "maroon": "#eba0ac",
    "red": "#f38ba8",
    "mauve": "#cba6f7",
    "pink": "#f5c2e7",
}

LATTE = {
    "base": "#eff1f5",
    "mantle": "#e6e9ef",
    "crust": "#dce0e8",
    "surface0": "#ccd0da",
    "surface1": "#bcc0cc",
    "surface2": "#acb0be",
    "text": "#4c4f69",
    "subtext1": "#5c5f77",
    "subtext0": "#6c6f85",
    "overlay0": "#9ca0b0",
    "blue": "#1e66f5",
    "lavender": "#7287fd",
    "sapphire": "#209fb5",
    "sky": "#04a5e5",
    "teal": "#179299",
    "green": "#40a02b",
    "yellow": "#df8e1d",
    "peach": "#fe640b",
    "maroon": "#e64553",
    "red": "#d20f39",
    "mauve": "#8839ef",
    "pink": "#ea76cb",
}


# ---------------------------------------------------------------------------
# Streaming VCD parser
# ---------------------------------------------------------------------------


@dataclass
class VcdSignal:
    """Represents one VCD signal."""

    identifier: str
    name: str
    width: int = 1
    scope: str = ""
    # List of (time_ns, value_str) transitions, kept sorted by time.
    transitions: list[tuple[float, str]] = field(default_factory=list)
    visible: bool = True
    color: str = "#89b4fa"

    @property
    def full_name(self) -> str:
        return f"{self.scope}.{self.name}" if self.scope else self.name

    def value_at(self, time_ns: float) -> str:
        """Return the value of the signal at the given time."""
        if not self.transitions:
            return "x"
        # Binary search would be faster but linear is fine for live view.
        last = self.transitions[0][1]
        for t, v in self.transitions:
            if t > time_ns:
                break
            last = v
        return last

    def add_transition(self, t_ns: float, value: str) -> None:
        if self.transitions and self.transitions[-1][1] == value:
            return
        self.transitions.append((t_ns, value))


class StreamingVcdParser:
    """Incremental VCD parser.

    Tracks the file position so that calling :meth:`parse_new_data` only
    consumes lines that have been appended since the previous call. The
    parser is intentionally tolerant of half-written files - any partial
    final line is held back until more data arrives.
    """

    _SCALE = {
        "s": 1e9,
        "ms": 1e6,
        "us": 1e3,
        "ns": 1.0,
        "ps": 1e-3,
        "fs": 1e-6,
    }

    _VAR_RE = re.compile(
        r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]+\])?\s+\$end"
    )

    def __init__(self) -> None:
        self.signals: dict[str, VcdSignal] = {}
        self.name_to_id: dict[str, str] = {}
        self.timescale_ns: float = 1.0
        self.current_time_ns: float = 0.0
        self.max_time_ns: float = 0.0
        self._scope_stack: list[str] = []
        self._buffer: str = ""
        self._file_pos: int = 0
        self._in_definitions: bool = True

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.signals.clear()
        self.name_to_id.clear()
        self.current_time_ns = 0.0
        self.max_time_ns = 0.0
        self._scope_stack.clear()
        self._buffer = ""
        self._file_pos = 0
        self._in_definitions = True

    # ------------------------------------------------------------------
    def parse_new_data(self, path: Path) -> bool:
        """Read any new bytes from ``path`` and parse them.

        Returns True if any new transitions were appended.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size < self._file_pos:
            # File was truncated / restarted.
            self.reset()
        if size == self._file_pos:
            return False

        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._file_pos)
                chunk = fh.read()
                self._file_pos = fh.tell()
        except OSError:
            return False

        self._buffer += chunk
        # Hold back the last partial line.
        if "\n" in self._buffer:
            text, _, tail = self._buffer.rpartition("\n")
            self._buffer = tail
        else:
            text = ""

        if not text:
            return False

        had_data = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if self._in_definitions:
                if self._handle_definition(line):
                    continue
                if line == "$enddefinitions $end":
                    self._in_definitions = False
                    continue
            else:
                if self._handle_simulation(line):
                    had_data = True
        return had_data

    # ------------------------------------------------------------------
    def _handle_definition(self, line: str) -> bool:
        if line.startswith("$timescale"):
            # Could be on same line or following lines; we accept formats like
            # "$timescale 1ns $end" or "$timescale" alone.
            m = re.search(r"(\d+)\s*(fs|ps|ns|us|ms|s)", line)
            if m:
                num = float(m.group(1))
                unit = m.group(2)
                self.timescale_ns = num * self._SCALE[unit]
            return True
        if line.startswith("$scope"):
            parts = line.split()
            if len(parts) >= 3:
                self._scope_stack.append(parts[2])
            return True
        if line.startswith("$upscope"):
            if self._scope_stack:
                self._scope_stack.pop()
            return True
        if line.startswith("$var"):
            m = self._VAR_RE.search(line)
            if m:
                width = int(m.group(1))
                ident = m.group(2)
                name = m.group(3)
                scope = ".".join(self._scope_stack)
                sig = VcdSignal(
                    identifier=ident,
                    name=name,
                    width=width,
                    scope=scope,
                )
                self.signals[ident] = sig
                self.name_to_id[sig.full_name] = ident
            return True
        if line.startswith("$"):
            return True
        return False

    def _handle_simulation(self, line: str) -> bool:
        if line.startswith("#"):
            try:
                self.current_time_ns = float(line[1:]) * self.timescale_ns
                if self.current_time_ns > self.max_time_ns:
                    self.max_time_ns = self.current_time_ns
            except ValueError:
                pass
            return False
        if line[0] in "01xzXZ" and len(line) >= 2:
            value = line[0].lower()
            ident = line[1:]
            sig = self.signals.get(ident)
            if sig is not None:
                sig.add_transition(self.current_time_ns, value)
                return True
            return False
        if line[0] in "bB":
            # Bus value: "b1010 ident"
            parts = line[1:].split(" ", 1)
            if len(parts) == 2:
                bits = parts[0]
                ident = parts[1]
                sig = self.signals.get(ident)
                if sig is not None:
                    try:
                        clean = bits.replace("x", "0").replace("z", "0")
                        hex_val = format(int(clean, 2), "x") if clean else "0"
                    except ValueError:
                        hex_val = bits
                    sig.add_transition(self.current_time_ns, f"h{hex_val}")
                    return True
            return False
        return False


# ---------------------------------------------------------------------------
# The widget
# ---------------------------------------------------------------------------


class LiveWaveformWidget(QWidget):
    """A streaming waveform display."""

    signal_clicked = Signal(str)
    time_clicked = Signal(float)

    ROW_HEIGHT = 28
    NAME_COL_WIDTH = 220
    VALUE_COL_WIDTH = 90
    HEADER_HEIGHT = 26
    MIN_PX_PER_NS = 0.05
    MAX_PX_PER_NS = 200.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveWaveformWidget")
        self.setMinimumSize(640, 240)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._palette = MOCHA
        self._dark = True

        self.parser = StreamingVcdParser()
        self.vcd_path: Optional[Path] = None

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        # Refresh timer for batched repaint at 30 FPS.
        self._refresh = QTimer(self)
        self._refresh.setInterval(33)
        self._refresh.timeout.connect(self._tick)

        # Pending parse flag (set by file watcher / fallback poll).
        self._pending_parse = False
        self._poll = QTimer(self)
        self._poll.setInterval(150)
        self._poll.timeout.connect(self._poll_file)

        self._visible_signals: list[str] = []  # full names
        self._view_start_ns = 0.0
        self._px_per_ns = 4.0
        self._lock_view = False
        self._cursor_x: int = -1
        self._last_render_count = 0
        self._streaming = False
        self._fps_count = 0
        self._fps_last = time.monotonic()
        self._fps = 0.0

        self._build_ui()
        self._apply_palette()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.toolbar = QToolBar(self)
        self.toolbar.setIconSize(QSize(16, 16))

        self.act_start = QAction("Start", self)
        self.act_stop = QAction("Stop", self)
        self.act_open = QAction("Open VCD", self)
        self.act_lock = QAction("Lock View", self)
        self.act_lock.setCheckable(True)
        self.act_zoom_in = QAction("Zoom In", self)
        self.act_zoom_out = QAction("Zoom Out", self)
        self.act_zoom_fit = QAction("Fit", self)
        self.act_export = QAction("Export PNG", self)

        self.toolbar.addAction(self.act_open)
        self.toolbar.addAction(self.act_start)
        self.toolbar.addAction(self.act_stop)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_zoom_in)
        self.toolbar.addAction(self.act_zoom_out)
        self.toolbar.addAction(self.act_zoom_fit)
        self.toolbar.addAction(self.act_lock)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_export)
        outer.addWidget(self.toolbar)

        self.status = QLabel("Idle")
        self.status.setContentsMargins(8, 2, 8, 2)
        outer.addWidget(self.status)

        # Drawing area is the rest of the widget; we paint directly on self.
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(spacer, 1)
        self._draw_area = spacer
        self._draw_area.installEventFilter(self)
        self._draw_area.setMouseTracking(True)

        self.act_open.triggered.connect(self._on_open_clicked)
        self.act_start.triggered.connect(self._on_start_clicked)
        self.act_stop.triggered.connect(self.stop_streaming)
        self.act_zoom_in.triggered.connect(lambda: self._zoom(1.25))
        self.act_zoom_out.triggered.connect(lambda: self._zoom(0.8))
        self.act_zoom_fit.triggered.connect(self._zoom_fit)
        self.act_lock.toggled.connect(self._on_lock_toggled)
        self.act_export.triggered.connect(self._on_export_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start_streaming(self, vcd_path: Path) -> None:
        vcd_path = Path(vcd_path)
        self.vcd_path = vcd_path
        self.parser.reset()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if vcd_path.exists():
            self._watcher.addPath(str(vcd_path))
        self._streaming = True
        self._refresh.start()
        self._poll.start()
        self.status.setText(f"Streaming {vcd_path.name}")
        self.update()

    def stop_streaming(self) -> None:
        self._streaming = False
        self._refresh.stop()
        self._poll.stop()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        self.status.setText("Stopped")
        self.update()

    def add_signal(self, name: str) -> None:
        if name not in self._visible_signals:
            self._visible_signals.append(name)
            self.update()

    def remove_signal(self, name: str) -> None:
        if name in self._visible_signals:
            self._visible_signals.remove(name)
            self.update()

    def set_time_range(self, start_ns: float, end_ns: float) -> None:
        if end_ns <= start_ns:
            return
        self._view_start_ns = max(0.0, start_ns)
        wave_w = max(1, self._wave_width())
        self._px_per_ns = wave_w / (end_ns - start_ns)
        self._px_per_ns = max(self.MIN_PX_PER_NS, min(self.MAX_PX_PER_NS, self._px_per_ns))
        self.update()

    def export_to_image(self, path: Path) -> None:
        img = QImage(self.size(), QImage.Format_ARGB32)
        img.fill(QColor(self._palette["base"]))
        p = QPainter(img)
        self._render(p)
        p.end()
        img.save(str(path))

    def set_theme(self, dark: bool = True) -> None:
        self._dark = dark
        self._palette = MOCHA if dark else LATTE
        self._apply_palette()
        self.update()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _apply_palette(self) -> None:
        p = self._palette
        self.setStyleSheet(
            f"""
            QWidget#LiveWaveformWidget {{
                background: {p['base']};
                color: {p['text']};
            }}
            QToolBar {{
                background: {p['mantle']};
                border: none;
                padding: 4px;
                spacing: 4px;
            }}
            QToolBar QToolButton {{
                color: {p['text']};
                background: {p['surface0']};
                border: 1px solid {p['surface1']};
                border-radius: 4px;
                padding: 3px 8px;
            }}
            QToolBar QToolButton:hover {{
                background: {p['surface1']};
            }}
            QToolBar QToolButton:checked {{
                background: {p['blue']};
                color: {p['base']};
            }}
            QLabel {{
                color: {p['subtext1']};
                background: {p['mantle']};
            }}
            """
        )

    def _wave_width(self) -> int:
        return max(0, self._draw_area.width() - self.NAME_COL_WIDTH - self.VALUE_COL_WIDTH)

    def _wave_x_for_time(self, t_ns: float) -> int:
        return int(self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH + (t_ns - self._view_start_ns) * self._px_per_ns)

    def _time_for_x(self, x: int) -> float:
        return self._view_start_ns + (x - self.NAME_COL_WIDTH - self.VALUE_COL_WIDTH) / self._px_per_ns

    def _zoom(self, factor: float) -> None:
        self._px_per_ns = max(self.MIN_PX_PER_NS, min(self.MAX_PX_PER_NS, self._px_per_ns * factor))
        self.update()

    def _zoom_fit(self) -> None:
        if self.parser.max_time_ns <= 0:
            return
        wave_w = max(1, self._wave_width())
        self._view_start_ns = 0.0
        self._px_per_ns = wave_w / max(1.0, self.parser.max_time_ns)
        self._px_per_ns = max(self.MIN_PX_PER_NS, min(self.MAX_PX_PER_NS, self._px_per_ns))
        self.update()

    # ------------------------------------------------------------------
    # Streaming plumbing
    # ------------------------------------------------------------------
    @Slot(str)
    def _on_file_changed(self, _path: str) -> None:
        self._pending_parse = True
        # Re-add: Qt removes the watch when the file shrinks.
        if self.vcd_path and str(self.vcd_path) not in self._watcher.files():
            self._watcher.addPath(str(self.vcd_path))

    def _poll_file(self) -> None:
        if self.vcd_path and self.vcd_path.exists():
            self._pending_parse = True

    def _tick(self) -> None:
        if not self._streaming or not self.vcd_path:
            return
        if self._pending_parse:
            self._pending_parse = False
            changed = self.parser.parse_new_data(self.vcd_path)
            if changed:
                self._fps_count += 1
                now = time.monotonic()
                if now - self._fps_last >= 1.0:
                    self._fps = self._fps_count / (now - self._fps_last)
                    self._fps_count = 0
                    self._fps_last = now
                if not self._lock_view:
                    self._follow_latest()
                self.status.setText(
                    f"Streaming {self.vcd_path.name}  |  t={self.parser.max_time_ns:.1f} ns"
                    f"  |  signals={len(self.parser.signals)}  |  ~{self._fps:.0f} Hz"
                )
                self.update()

    def _follow_latest(self) -> None:
        wave_w = max(1, self._wave_width())
        view_span = wave_w / self._px_per_ns
        if self.parser.max_time_ns > self._view_start_ns + view_span:
            self._view_start_ns = max(0.0, self.parser.max_time_ns - view_span * 0.9)

    # ------------------------------------------------------------------
    # Toolbar handlers
    # ------------------------------------------------------------------
    def _on_open_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open VCD", "", "VCD Files (*.vcd);;All Files (*)"
        )
        if path:
            self.start_streaming(Path(path))

    def _on_start_clicked(self) -> None:
        if self.vcd_path:
            self.start_streaming(self.vcd_path)
        else:
            self._on_open_clicked()

    def _on_lock_toggled(self, checked: bool) -> None:
        self._lock_view = checked

    def _on_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Waveform", "waveform.png", "PNG Files (*.png)"
        )
        if path:
            self.export_to_image(Path(path))

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self._draw_area:
            if event.type() == event.Type.Paint:
                self._paint_area(event)
                return True
            if event.type() == event.Type.MouseMove:
                self._on_mouse_move(event)
                return True
            if event.type() == event.Type.MouseButtonPress:
                self._on_mouse_press(event)
                return True
            if event.type() == event.Type.Wheel:
                self._on_wheel(event)
                return True
            if event.type() == event.Type.ContextMenu:
                self._on_context_menu(event)
                return True
        return super().eventFilter(obj, event)

    def _paint_area(self, _event: QPaintEvent) -> None:
        p = QPainter(self._draw_area)
        try:
            self._render(p)
        finally:
            p.end()

    def _render(self, p: QPainter) -> None:
        pal = self._palette
        rect = self._draw_area.rect()
        p.fillRect(rect, QColor(pal["base"]))

        # Header
        header = QRect(0, 0, rect.width(), self.HEADER_HEIGHT)
        p.fillRect(header, QColor(pal["mantle"]))
        p.setPen(QColor(pal["surface2"]))
        p.drawLine(0, self.HEADER_HEIGHT, rect.width(), self.HEADER_HEIGHT)

        # Column dividers
        p.drawLine(self.NAME_COL_WIDTH, 0, self.NAME_COL_WIDTH, rect.height())
        p.drawLine(
            self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH,
            0,
            self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH,
            rect.height(),
        )

        # Header labels
        p.setPen(QColor(pal["subtext1"]))
        font = QFont("Segoe UI", 8, QFont.Bold)
        p.setFont(font)
        p.drawText(QRect(8, 0, self.NAME_COL_WIDTH - 8, self.HEADER_HEIGHT), Qt.AlignVCenter, "Signal")
        p.drawText(
            QRect(self.NAME_COL_WIDTH + 4, 0, self.VALUE_COL_WIDTH - 8, self.HEADER_HEIGHT),
            Qt.AlignVCenter,
            "Value",
        )

        self._draw_time_axis(p, rect)

        # Determine signals to draw
        if not self._visible_signals and self.parser.signals:
            self._visible_signals = [s.full_name for s in list(self.parser.signals.values())[:8]]

        y = self.HEADER_HEIGHT + 4
        for full_name in self._visible_signals:
            ident = self.parser.name_to_id.get(full_name)
            if ident is None:
                y += self.ROW_HEIGHT
                continue
            sig = self.parser.signals.get(ident)
            if sig is None:
                y += self.ROW_HEIGHT
                continue
            self._draw_signal_row(p, sig, y)
            y += self.ROW_HEIGHT
            if y > rect.height():
                break

        # Cursor
        if self._cursor_x >= self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH:
            p.setPen(QPen(QColor(pal["yellow"]), 1, Qt.DashLine))
            p.drawLine(self._cursor_x, self.HEADER_HEIGHT, self._cursor_x, rect.height())
            t = self._time_for_x(self._cursor_x)
            label = f"{t:.2f} ns"
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(label) + 8
            tr = QRect(self._cursor_x + 4, self.HEADER_HEIGHT + 2, tw, 16)
            p.fillRect(tr, QColor(pal["surface1"]))
            p.setPen(QColor(pal["yellow"]))
            p.drawText(tr, Qt.AlignCenter, label)

    def _draw_time_axis(self, p: QPainter, rect: QRect) -> None:
        pal = self._palette
        wave_x0 = self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH
        wave_w = rect.width() - wave_x0
        if wave_w <= 0:
            return
        # Choose tick spacing
        target_px = 80
        ns_per_tick = target_px / max(self._px_per_ns, 1e-6)
        # Round to a nice number
        magnitude = 10 ** int(max(0, len(str(int(ns_per_tick))) - 1))
        for m in (1, 2, 5, 10):
            step = m * magnitude
            if step >= ns_per_tick:
                ns_per_tick = step
                break

        p.setPen(QColor(pal["overlay0"]))
        font = QFont("Segoe UI", 7)
        p.setFont(font)
        t = (int(self._view_start_ns / ns_per_tick) + 1) * ns_per_tick
        while True:
            x = self._wave_x_for_time(t)
            if x > rect.width():
                break
            p.drawLine(x, 0, x, self.HEADER_HEIGHT)
            p.setPen(QColor(pal["subtext0"]))
            p.drawText(x + 2, self.HEADER_HEIGHT - 4, f"{t:.0f}ns")
            p.setPen(QColor(pal["surface0"]))
            p.drawLine(x, self.HEADER_HEIGHT + 1, x, rect.height())
            p.setPen(QColor(pal["overlay0"]))
            t += ns_per_tick

    def _draw_signal_row(self, p: QPainter, sig: VcdSignal, y: int) -> None:
        pal = self._palette
        rect = self._draw_area.rect()
        # Name
        p.setPen(QColor(pal["text"]))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRect(8, y, self.NAME_COL_WIDTH - 12, self.ROW_HEIGHT), Qt.AlignVCenter, sig.full_name)

        # Current value
        cursor_t = self._time_for_x(self._cursor_x) if self._cursor_x > 0 else self.parser.max_time_ns
        cur_val = sig.value_at(cursor_t)
        p.setPen(QColor(pal["yellow"]))
        p.setFont(QFont("Consolas", 9))
        p.drawText(
            QRect(self.NAME_COL_WIDTH + 4, y, self.VALUE_COL_WIDTH - 8, self.ROW_HEIGHT),
            Qt.AlignVCenter,
            cur_val,
        )

        # Waveform
        wave_x0 = self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH
        wave_x1 = rect.width()
        top = y + 4
        bot = y + self.ROW_HEIGHT - 6
        mid = (top + bot) // 2

        if not sig.transitions:
            p.setPen(QPen(QColor(pal["overlay0"]), 1, Qt.DashLine))
            p.drawLine(wave_x0, mid, wave_x1, mid)
            return

        pen = QPen(QColor(pal["green"]), 1.5)
        p.setPen(pen)

        last_x = wave_x0
        last_v = sig.value_at(self._view_start_ns)
        for t, v in sig.transitions:
            if t < self._view_start_ns:
                continue
            x = self._wave_x_for_time(t)
            if x > wave_x1:
                break
            self._draw_segment(p, last_x, x, last_v, top, mid, bot, pal)
            last_x = x
            last_v = v
        # Trailing segment
        self._draw_segment(p, last_x, wave_x1, last_v, top, mid, bot, pal)

    def _draw_segment(
        self,
        p: QPainter,
        x0: int,
        x1: int,
        value: str,
        top: int,
        mid: int,
        bot: int,
        pal: dict,
    ) -> None:
        if x1 <= x0:
            return
        if value == "0":
            p.setPen(QPen(QColor(pal["green"]), 1.5))
            p.drawLine(x0, bot, x1, bot)
        elif value == "1":
            p.setPen(QPen(QColor(pal["green"]), 1.5))
            p.drawLine(x0, top, x1, top)
        elif value in ("x", "X"):
            p.fillRect(QRect(x0, top, x1 - x0, bot - top), QColor(pal["red"] + "55"))
            p.setPen(QPen(QColor(pal["red"]), 1.5))
            p.drawLine(x0, top, x1, bot)
            p.drawLine(x0, bot, x1, top)
        elif value in ("z", "Z"):
            p.setPen(QPen(QColor(pal["yellow"]), 1.5))
            p.drawLine(x0, mid, x1, mid)
        elif value.startswith("h"):
            # Bus value drawn as a hex hexagon
            p.setPen(QPen(QColor(pal["sapphire"]), 1.5))
            p.drawLine(x0 + 2, top, x1 - 2, top)
            p.drawLine(x0 + 2, bot, x1 - 2, bot)
            p.drawLine(x0, mid, x0 + 2, top)
            p.drawLine(x0, mid, x0 + 2, bot)
            p.drawLine(x1 - 2, top, x1, mid)
            p.drawLine(x1 - 2, bot, x1, mid)
            text = value[1:]
            fm = QFontMetrics(p.font())
            if fm.horizontalAdvance(text) < (x1 - x0 - 8):
                p.setPen(QColor(pal["text"]))
                p.drawText(
                    QRect(x0 + 4, top, x1 - x0 - 8, bot - top),
                    Qt.AlignCenter,
                    text,
                )
        else:
            p.setPen(QPen(QColor(pal["overlay0"]), 1, Qt.DashLine))
            p.drawLine(x0, mid, x1, mid)

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------
    def _on_mouse_move(self, event: QMouseEvent) -> None:
        self._cursor_x = int(event.position().x())
        self._draw_area.update()

    def _on_mouse_press(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        y = int(event.position().y())
        if event.button() == Qt.LeftButton:
            if x > self.NAME_COL_WIDTH + self.VALUE_COL_WIDTH:
                t = self._time_for_x(x)
                self.time_clicked.emit(t)
            elif x < self.NAME_COL_WIDTH:
                row = (y - self.HEADER_HEIGHT - 4) // self.ROW_HEIGHT
                if 0 <= row < len(self._visible_signals):
                    self.signal_clicked.emit(self._visible_signals[row])

    def _on_wheel(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier:
            self._zoom(1.2 if delta > 0 else 0.8)
        else:
            wave_w = max(1, self._wave_width())
            shift_ns = (wave_w / self._px_per_ns) * 0.1
            if delta > 0:
                self._view_start_ns = max(0.0, self._view_start_ns - shift_ns)
            else:
                self._view_start_ns += shift_ns
            self.update()

    def _on_context_menu(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("Add signal...", self._prompt_add_signal)
        menu.addAction("Remove signal...", self._prompt_remove_signal)
        menu.addSeparator()
        menu.addAction("Zoom in", lambda: self._zoom(1.25))
        menu.addAction("Zoom out", lambda: self._zoom(0.8))
        menu.addAction("Zoom to fit", self._zoom_fit)
        menu.addAction("Reset view", self._reset_view)
        menu.addSeparator()
        menu.addAction("Export PNG...", self._on_export_clicked)
        menu.exec(event.globalPos())

    def _prompt_add_signal(self) -> None:
        names = list(self.parser.name_to_id.keys())
        if not names:
            QMessageBox.information(self, "Add Signal", "No signals available yet.")
            return
        name, ok = QInputDialog.getItem(self, "Add Signal", "Signal:", names, 0, False)
        if ok and name:
            self.add_signal(name)

    def _prompt_remove_signal(self) -> None:
        if not self._visible_signals:
            return
        name, ok = QInputDialog.getItem(
            self, "Remove Signal", "Signal:", self._visible_signals, 0, False
        )
        if ok and name:
            self.remove_signal(name)

    def _reset_view(self) -> None:
        self._view_start_ns = 0.0
        self._px_per_ns = 4.0
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._draw_area.update()

    def sizeHint(self) -> QSize:
        return QSize(900, 360)
