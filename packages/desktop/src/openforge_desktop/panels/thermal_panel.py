"""Thermal map visualization panel for the OpenForge desktop app."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PySide6.QtCore import QPoint, Qt, Signal
    from PySide6.QtGui import (
        QColor,
        QFont,
        QMouseEvent,
        QPainter,
        QPen,
    )
    from PySide6.QtWidgets import (
        QComboBox,
        QDockWidget,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QSizePolicy,
        QSlider,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover - desktop deps optional in CI
    Qt = None  # type: ignore
    QDockWidget = object  # type: ignore


# ----------------------------------------------------------------------------
# Catppuccin Mocha color palette
# ----------------------------------------------------------------------------


@dataclass
class _Theme:
    bg: str = "#1e1e2e"
    surface: str = "#313244"
    overlay: str = "#45475a"
    text: str = "#cdd6f4"
    subtext: str = "#a6adc8"
    blue: str = "#89b4fa"
    green: str = "#a6e3a2"
    yellow: str = "#f9e2af"
    peach: str = "#fab387"
    red: str = "#f38ba8"
    mauve: str = "#cba6f7"


_DARK = _Theme()
_LIGHT = _Theme(
    bg="#eff1f5",
    surface="#e6e9ef",
    overlay="#dce0e8",
    text="#4c4f69",
    subtext="#5c5f77",
    blue="#1e66f5",
    green="#40a02b",
    yellow="#df8e1d",
    peach="#fe640b",
    red="#d20f39",
    mauve="#8839ef",
)


# ----------------------------------------------------------------------------
# Heatmap renderer widget
# ----------------------------------------------------------------------------


def _temp_to_color(t: float, t_min: float, t_max: float) -> QColor:
    """Map temperature to a blue->green->yellow->red gradient."""
    f = 0.0 if t_max <= t_min else (t - t_min) / (t_max - t_min)
    f = max(0.0, min(1.0, f))
    # 4-stop interpolation
    if f < 0.33:
        k = f / 0.33
        r = int(0 * (1 - k) + 0 * k)
        g = int(120 * (1 - k) + 220 * k)
        b = int(255 * (1 - k) + 80 * k)
    elif f < 0.66:
        k = (f - 0.33) / 0.33
        r = int(0 * (1 - k) + 240 * k)
        g = int(220 * (1 - k) + 220 * k)
        b = int(80 * (1 - k) + 0 * k)
    else:
        k = (f - 0.66) / 0.34
        r = int(240 * (1 - k) + 220 * k)
        g = int(220 * (1 - k) + 30 * k)
        b = int(0 * (1 - k) + 30 * k)
    return QColor(r, g, b)


class _HeatmapView(QWidget):
    """Renders a 2D thermal grid into a paintable widget."""

    cursor_moved = Signal(float, float, float)  # x_um, y_um, temp_c

    def __init__(self, parent=None):
        super().__init__(parent)
        self._map = None
        self._theme = _DARK
        self._show_hotspots = True
        self.setMouseTracking(True)
        self.setMinimumSize(420, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_map(self, thermal_map) -> None:
        self._map = thermal_map
        self.update()

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.update()

    def set_show_hotspots(self, show: bool) -> None:
        self._show_hotspots = show
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor(self._theme.bg))

        m = self._map
        if m is None or not getattr(m, "grid", None):
            p.setPen(QColor(self._theme.subtext))
            p.drawText(self.rect(), Qt.AlignCenter, "No thermal map - click Run")
            p.end()
            return

        rows = m.rows
        cols = m.cols
        if rows == 0 or cols == 0:
            p.end()
            return

        margin = 20
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        scale = min(avail_w / cols, avail_h / rows)
        cw = max(1.0, scale)
        ch = max(1.0, scale)

        for r in range(rows):
            for c in range(cols):
                t = m.grid[r][c]
                color = _temp_to_color(t, m.min_temp_c, m.max_temp_c)
                x = margin + c * cw
                y = margin + r * ch
                p.fillRect(int(x), int(y), int(cw + 0.5), int(ch + 0.5), color)

        # Hotspot markers
        if self._show_hotspots and m.hotspots:
            p.setPen(QPen(QColor(self._theme.red), 2))
            for h in m.hotspots[:20]:
                cx = margin + (h.x / m.grid_size_um) * cw
                cy = margin + (h.y / m.grid_size_um) * ch
                p.drawEllipse(QPoint(int(cx), int(cy)), 5, 5)
                p.drawLine(int(cx) - 8, int(cy), int(cx) + 8, int(cy))
                p.drawLine(int(cx), int(cy) - 8, int(cx), int(cy) + 8)

        # Border
        p.setPen(QPen(QColor(self._theme.overlay), 1))
        p.drawRect(margin - 1, margin - 1, int(cols * cw) + 2, int(rows * ch) + 2)

        p.end()

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        m = self._map
        if m is None or not m.grid:
            return
        margin = 20
        cols, rows = m.cols, m.rows
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        scale = min(avail_w / cols, avail_h / rows)
        cw = max(1.0, scale)
        ch = max(1.0, scale)
        x = (event.position().x() - margin) / cw
        y = (event.position().y() - margin) / ch
        if 0 <= x < cols and 0 <= y < rows:
            t = m.grid[int(y)][int(x)]
            self.cursor_moved.emit(x * m.grid_size_um, y * m.grid_size_um, t)


# ----------------------------------------------------------------------------
# Color legend widget
# ----------------------------------------------------------------------------


class _ColorLegend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._t_min = 25.0
        self._t_max = 100.0
        self._theme = _DARK
        self.setFixedHeight(160)
        self.setMinimumWidth(70)

    def set_range(self, t_min: float, t_max: float) -> None:
        self._t_min = t_min
        self._t_max = t_max
        self.update()

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._theme.surface))
        bar_x = 8
        bar_w = 18
        bar_y = 8
        bar_h = self.height() - 16
        steps = 60
        for i in range(steps):
            f = i / (steps - 1)
            t = self._t_min + f * (self._t_max - self._t_min)
            color = _temp_to_color(t, self._t_min, self._t_max)
            yy = bar_y + bar_h - int((i / steps) * bar_h)
            p.fillRect(bar_x, yy, bar_w, max(2, bar_h // steps + 1), color)

        p.setPen(QColor(self._theme.text))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        for frac, label_t in (
            (0.0, self._t_min),
            (0.5, (self._t_min + self._t_max) / 2.0),
            (1.0, self._t_max),
        ):
            yy = bar_y + bar_h - int(frac * bar_h)
            p.drawText(bar_x + bar_w + 4, yy + 4, f"{label_t:.0f} C")
        p.end()


# ----------------------------------------------------------------------------
# Main thermal panel
# ----------------------------------------------------------------------------


class ThermalPanel(QDockWidget):
    """Visualizes chip thermal analysis."""

    run_requested = Signal(float)  # ambient temperature

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thermal Analysis")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._theme = _DARK
        self._thermal_map = None

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # Toolbar -----------------------------------------------------------
        toolbar_w = QWidget()
        tb = QHBoxLayout(toolbar_w)
        tb.setContentsMargins(2, 2, 2, 2)
        self._run_btn = QPushButton("Run Thermal")
        self._run_btn.clicked.connect(self._on_run_clicked)
        tb.addWidget(self._run_btn)

        tb.addWidget(QLabel("Ambient:"))
        self._ambient_slider = QSlider(Qt.Horizontal)
        self._ambient_slider.setRange(0, 85)
        self._ambient_slider.setValue(25)
        self._ambient_slider.setFixedWidth(140)
        tb.addWidget(self._ambient_slider)
        self._ambient_label = QLabel("25 C")
        self._ambient_slider.valueChanged.connect(
            lambda v: self._ambient_label.setText(f"{v} C")
        )
        tb.addWidget(self._ambient_label)

        tb.addWidget(QLabel("Scale:"))
        self._scale_combo = QComboBox()
        self._scale_combo.addItems(["Full range", "0-125 C", "25-100 C", "Custom..."])
        tb.addWidget(self._scale_combo)

        self._show_hotspots_btn = QPushButton("Hotspots")
        self._show_hotspots_btn.setCheckable(True)
        self._show_hotspots_btn.setChecked(True)
        self._show_hotspots_btn.toggled.connect(self._on_hotspots_toggled)
        tb.addWidget(self._show_hotspots_btn)

        tb.addStretch(1)
        root_layout.addWidget(toolbar_w)

        # Splitter: heatmap + sidebar --------------------------------------
        splitter = QSplitter(Qt.Horizontal)
        self._heatmap = _HeatmapView()
        self._heatmap.cursor_moved.connect(self._on_cursor_moved)
        splitter.addWidget(self._heatmap)

        # Sidebar
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(4, 4, 4, 4)
        side.setSpacing(8)

        stats_box = QFrame()
        stats_box.setFrameShape(QFrame.StyledPanel)
        sg = QGridLayout(stats_box)
        sg.setContentsMargins(8, 8, 8, 8)
        self._stat_max = QLabel("--")
        self._stat_avg = QLabel("--")
        self._stat_min = QLabel("--")
        self._stat_grad = QLabel("--")
        self._stat_hotspots = QLabel("--")
        self._stat_lifetime = QLabel("--")
        for i, (lbl, w) in enumerate(
            [
                ("Max temp", self._stat_max),
                ("Avg temp", self._stat_avg),
                ("Min temp", self._stat_min),
                ("Gradient", self._stat_grad),
                ("Hotspots", self._stat_hotspots),
                ("Est life", self._stat_lifetime),
            ]
        ):
            sg.addWidget(QLabel(lbl), i, 0)
            sg.addWidget(w, i, 1)
        side.addWidget(stats_box)

        side.addWidget(QLabel("Hotspots"))
        self._hotspot_list = QListWidget()
        self._hotspot_list.setMaximumHeight(170)
        side.addWidget(self._hotspot_list)

        side.addWidget(QLabel("Legend"))
        self._legend = _ColorLegend()
        side.addWidget(self._legend)

        side.addStretch(1)
        sidebar.setMinimumWidth(220)
        splitter.addWidget(sidebar)
        splitter.setSizes([700, 240])
        root_layout.addWidget(splitter, 1)

        # Status bar --------------------------------------------------------
        self._status = QLabel("Ready")
        self._status.setStyleSheet("padding: 4px;")
        root_layout.addWidget(self._status)

        self.setWidget(root)
        self._apply_theme()

    # ------------------------------------------------------------------
    def set_theme(self, dark: bool) -> None:
        self._theme = _DARK if dark else _LIGHT
        self._apply_theme()
        self._heatmap.set_theme(self._theme)
        self._legend.set_theme(self._theme)

    def _apply_theme(self) -> None:
        t = self._theme
        css = (
            f"QDockWidget {{ background:{t.bg}; color:{t.text}; }}"
            f"QWidget {{ background:{t.bg}; color:{t.text}; }}"
            f"QFrame {{ background:{t.surface}; border:1px solid {t.overlay};"
            f" border-radius:4px; }}"
            f"QPushButton {{ background:{t.surface}; color:{t.text};"
            f" border:1px solid {t.overlay}; border-radius:4px; padding:4px 10px; }}"
            f"QPushButton:hover {{ background:{t.overlay}; }}"
            f"QPushButton:checked {{ background:{t.mauve}; color:{t.bg}; }}"
            f"QListWidget {{ background:{t.surface}; border:1px solid {t.overlay}; }}"
            f"QComboBox {{ background:{t.surface}; border:1px solid {t.overlay};"
            f" border-radius:4px; padding:2px 6px; }}"
            f"QLabel {{ color:{t.text}; }}"
        )
        self.setStyleSheet(css)

    # ------------------------------------------------------------------
    def show_thermal_map(self, thermal_map) -> None:
        self._thermal_map = thermal_map
        self._heatmap.set_map(thermal_map)
        if thermal_map is None:
            return

        self._stat_max.setText(f"{thermal_map.max_temp_c:.2f} C")
        self._stat_min.setText(f"{thermal_map.min_temp_c:.2f} C")
        self._stat_avg.setText(f"{thermal_map.avg_temp_c:.2f} C")
        self._stat_grad.setText(f"{thermal_map.gradient_c:.2f} C")
        self._stat_hotspots.setText(str(len(thermal_map.hotspots)))
        # rough Arrhenius estimate
        try:
            import math

            Ea = 0.7
            k = 8.617e-5
            T = thermal_map.max_temp_c + 273.15
            ref = 85.0 + 273.15
            life = 10.0 * math.exp((Ea / k) * (1.0 / T - 1.0 / ref))
            self._stat_lifetime.setText(f"{life:.1f} y")
        except Exception:
            self._stat_lifetime.setText("--")

        self._legend.set_range(thermal_map.min_temp_c, thermal_map.max_temp_c)

        self._hotspot_list.clear()
        for h in thermal_map.hotspots[:50]:
            item = QListWidgetItem(
                f"({h.x:6.1f},{h.y:6.1f}) {h.temperature_c:6.2f} C"
            )
            self._hotspot_list.addItem(item)

        self._status.setText(
            f"Loaded thermal map: {thermal_map.rows}x{thermal_map.cols}, "
            f"max {thermal_map.max_temp_c:.1f} C"
        )

    # ------------------------------------------------------------------
    def _on_run_clicked(self) -> None:
        self.run_requested.emit(float(self._ambient_slider.value()))
        self._status.setText("Running thermal analysis...")

    def _on_hotspots_toggled(self, checked: bool) -> None:
        self._heatmap.set_show_hotspots(checked)

    def _on_cursor_moved(self, x: float, y: float, t: float) -> None:
        self._status.setText(f"({x:.1f}, {y:.1f}) um  T={t:.2f} C")
