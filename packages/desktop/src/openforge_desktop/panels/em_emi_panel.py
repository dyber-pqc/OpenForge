"""Combined EM (electromigration) + EMI/EMC + ESD analysis dock panel."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPen
    from PySide6.QtWidgets import (
        QDockWidget,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QSizePolicy,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    Qt = None  # type: ignore
    QDockWidget = object  # type: ignore


# ----------------------------------------------------------------------------
# Catppuccin Mocha theme
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
# Spectrum chart widget
# ----------------------------------------------------------------------------


class _SpectrumChart(QWidget):
    """Simple spectrum bar chart with FCC limit overlay."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spectrum: list[tuple[float, float]] = []
        self._limits: dict[int, float] = {}
        self._theme = _DARK
        self.setMinimumSize(420, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_spectrum(self, spectrum: list[tuple[float, float]]) -> None:
        self._spectrum = sorted(spectrum, key=lambda x: x[0])
        self.update()

    def set_limits(self, limits: dict[int, float]) -> None:
        self._limits = limits
        self.update()

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(self._theme.bg))

        margin_l = 50
        margin_r = 12
        margin_t = 14
        margin_b = 30
        w = self.width() - margin_l - margin_r
        h = self.height() - margin_t - margin_b
        if w <= 0 or h <= 0:
            p.end()
            return

        # Axes
        p.setPen(QPen(QColor(self._theme.subtext), 1))
        p.drawLine(margin_l, margin_t + h, margin_l + w, margin_t + h)
        p.drawLine(margin_l, margin_t, margin_l, margin_t + h)

        if not self._spectrum:
            p.setPen(QColor(self._theme.subtext))
            p.drawText(self.rect(), Qt.AlignCenter, "No spectrum data")
            p.end()
            return

        f_max = max(f for f, _ in self._spectrum) or 1.0
        db_max = max(60.0, max(d for _, d in self._spectrum))
        db_min = min(0.0, min(d for _, d in self._spectrum))

        def to_x(f: float) -> int:
            return margin_l + int((f / f_max) * w)

        def to_y(db: float) -> int:
            return margin_t + int((1.0 - (db - db_min) / (db_max - db_min)) * h)

        # Bars
        bar_w = max(1, w // max(len(self._spectrum), 1))
        for f, db in self._spectrum:
            x = to_x(f)
            y = to_y(db)
            color = QColor(self._theme.green)
            limit = self._lookup_limit(f)
            if db > limit:
                color = QColor(self._theme.red)
            elif db > limit - 6:
                color = QColor(self._theme.yellow)
            p.fillRect(x - bar_w // 2, y, bar_w, margin_t + h - y, color)

        # Limit line
        p.setPen(QPen(QColor(self._theme.peach), 2, Qt.DashLine))
        prev = None
        steps = 80
        for i in range(steps + 1):
            f = (i / steps) * f_max
            l = self._lookup_limit(f)
            x = to_x(f)
            y = to_y(l)
            if prev is not None:
                p.drawLine(prev[0], prev[1], x, y)
            prev = (x, y)

        # Y-axis ticks
        p.setPen(QColor(self._theme.subtext))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            db = db_min + frac * (db_max - db_min)
            yy = to_y(db)
            p.drawText(2, yy + 4, f"{db:5.0f}")
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            xv = frac * f_max
            xx = to_x(xv)
            p.drawText(xx - 18, margin_t + h + 16, f"{xv:.0f}MHz")

        p.end()

    def _lookup_limit(self, f_mhz: float) -> float:
        if not self._limits:
            return 40.0
        last = 100.0
        for upper, val in sorted(self._limits.items()):
            if f_mhz <= upper:
                return val
            last = val
        return last


# ----------------------------------------------------------------------------
# EM and EMI tab widgets
# ----------------------------------------------------------------------------


class _EmTab(QWidget):
    run_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self._run_btn = QPushButton("Run EM Analysis")
        self._run_btn.clicked.connect(lambda: self.run_requested.emit())
        top.addWidget(self._run_btn)
        top.addStretch(1)
        layout.addLayout(top)

        stats = QFrame()
        sg = QGridLayout(stats)
        self._wires_lbl = QLabel("--")
        self._viol_lbl = QLabel("--")
        self._crit_lbl = QLabel("--")
        self._avg_lbl = QLabel("--")
        for i, (k, v) in enumerate(
            [
                ("Wires checked", self._wires_lbl),
                ("Violations", self._viol_lbl),
                ("Critical", self._crit_lbl),
                ("Avg density", self._avg_lbl),
            ]
        ):
            sg.addWidget(QLabel(k), i // 2, (i % 2) * 2)
            sg.addWidget(v, i // 2, (i % 2) * 2 + 1)
        layout.addWidget(stats)

        layout.addWidget(QLabel("Top violations"))
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Net", "Layer", "Density (mA/um)", "Limit", "Margin %"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self._table, 1)

        layout.addWidget(QLabel("Per-layer violations"))
        self._layer_list = QListWidget()
        self._layer_list.setMaximumHeight(140)
        layout.addWidget(self._layer_list)

    def show_em_result(self, result) -> None:
        if result is None:
            return
        self._wires_lbl.setText(str(result.wires_checked))
        self._viol_lbl.setText(str(len(result.violations)))
        self._crit_lbl.setText(str(result.critical_count))
        self._avg_lbl.setText(f"{result.avg_density*1e3:.3f} mA/um")

        viol = sorted(
            result.violations, key=lambda v: v.current_density_a_per_um2, reverse=True
        )[:50]
        self._table.setRowCount(len(viol))
        for i, v in enumerate(viol):
            self._table.setItem(i, 0, QTableWidgetItem(v.wire.net))
            self._table.setItem(i, 1, QTableWidgetItem(v.wire.layer))
            self._table.setItem(
                i,
                2,
                QTableWidgetItem(f"{v.current_density_a_per_um2*1e3:.3f}"),
            )
            self._table.setItem(
                i, 3, QTableWidgetItem(f"{v.limit_a_per_um2*1e3:.3f}")
            )
            self._table.setItem(i, 4, QTableWidgetItem(f"{v.margin_pct:+.1f}"))

        self._layer_list.clear()
        from collections import Counter

        c: Counter = Counter(v.wire.layer for v in result.violations)
        for layer, n in sorted(c.items()):
            self._layer_list.addItem(QListWidgetItem(f"{layer}: {n} violations"))


class _EmiTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._chart = _SpectrumChart()
        layout.addWidget(self._chart, 1)

        info = QFrame()
        ig = QGridLayout(info)
        self._worst_freq = QLabel("--")
        self._worst_db = QLabel("--")
        self._fcc = QLabel("--")
        self._ce = QLabel("--")
        self._margin = QLabel("--")
        for i, (k, v) in enumerate(
            [
                ("Worst freq", self._worst_freq),
                ("Worst emission", self._worst_db),
                ("FCC Class B", self._fcc),
                ("CISPR 22", self._ce),
                ("Margin", self._margin),
            ]
        ):
            ig.addWidget(QLabel(k), i, 0)
            ig.addWidget(v, i, 1)
        layout.addWidget(info)

    def set_theme(self, theme: _Theme) -> None:
        self._chart.set_theme(theme)

    def show_emi_result(self, result) -> None:
        if result is None:
            return
        self._chart.set_spectrum(result.spectrum)
        self._worst_freq.setText(f"{result.worst_frequency_mhz:.1f} MHz")
        self._worst_db.setText(f"{result.worst_emission_db_uv_per_m:.1f} dBuV/m")
        self._fcc.setText("PASS" if result.fcc_class_b_compliant else "FAIL")
        self._ce.setText("PASS" if result.ce_compliant else "FAIL")
        # Find worst margin
        worst = 1e9
        for f, db in result.spectrum:
            limit = self._chart._lookup_limit(f)
            m = limit - db
            if m < worst:
                worst = m
        if worst == 1e9:
            worst = 0.0
        self._margin.setText(f"{worst:+.2f} dB")


class _EsdTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        stats = QFrame()
        sg = QGridLayout(stats)
        self._pins = QLabel("--")
        self._paths = QLabel("--")
        self._viol = QLabel("--")
        self._hbm = QLabel("--")
        self._cdm = QLabel("--")
        for i, (k, v) in enumerate(
            [
                ("Pins checked", self._pins),
                ("Paths analyzed", self._paths),
                ("Violations", self._viol),
                ("HBM compliance", self._hbm),
                ("CDM compliance", self._cdm),
            ]
        ):
            sg.addWidget(QLabel(k), i, 0)
            sg.addWidget(v, i, 1)
        layout.addWidget(stats)

        layout.addWidget(QLabel("Pin discharge paths"))
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Pin", "Direction", "R (ohm)", "Distance (um)", "Status"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self._table, 1)

        layout.addWidget(QLabel("Violations"))
        self._violation_list = QListWidget()
        self._violation_list.setMaximumHeight(140)
        layout.addWidget(self._violation_list)

    def show_esd_result(self, result) -> None:
        if result is None:
            return
        self._pins.setText(str(result.pins_checked))
        self._paths.setText(str(len(result.paths)))
        self._viol.setText(str(len(result.violations)))
        self._hbm.setText("PASS" if result.hbm_compliant else "FAIL")
        self._cdm.setText("PASS" if result.cdm_compliant else "FAIL")

        rows = sorted(
            result.paths, key=lambda p: p.total_resistance, reverse=True
        )[:50]
        self._table.setRowCount(len(rows))
        for i, p in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(p.source_pin))
            self._table.setItem(i, 1, QTableWidgetItem(p.dest_pin))
            self._table.setItem(i, 2, QTableWidgetItem(f"{p.total_resistance:.3f}"))
            self._table.setItem(i, 3, QTableWidgetItem(f"{p.distance_um:.1f}"))
            self._table.setItem(
                i, 4, QTableWidgetItem("ok" if p.breakdown_ok else "FAIL")
            )

        self._violation_list.clear()
        for v in result.violations[:50]:
            self._violation_list.addItem(QListWidgetItem(str(v)))


# ----------------------------------------------------------------------------
# Main panel
# ----------------------------------------------------------------------------


class EmEmiPanel(QDockWidget):
    """Combined EM (electromigration), EMI/EMC and ESD analysis."""

    em_run_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("EM / EMI")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._theme = _DARK

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)

        self._tabs = QTabWidget()
        self._em_tab = _EmTab()
        self._em_tab.run_requested.connect(lambda: self.em_run_requested.emit())
        self._emi_tab = _EmiTab()
        self._esd_tab = _EsdTab()

        self._tabs.addTab(self._em_tab, "Electromigration")
        self._tabs.addTab(self._emi_tab, "EMI Spectrum")
        self._tabs.addTab(self._esd_tab, "ESD Paths")

        layout.addWidget(self._tabs, 1)

        self._status = QLabel("Ready")
        layout.addWidget(self._status)

        self.setWidget(root)

        # Default FCC limits
        self._emi_tab._chart.set_limits(
            {30: 40, 88: 40, 216: 43, 960: 46, 1000: 54}
        )
        self._apply_theme()

    # ------------------------------------------------------------------
    def set_theme(self, dark: bool) -> None:
        self._theme = _DARK if dark else _LIGHT
        self._apply_theme()
        self._emi_tab.set_theme(self._theme)

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
            f"QTabWidget::pane {{ background:{t.bg}; border:1px solid {t.overlay}; }}"
            f"QTabBar::tab {{ background:{t.surface}; color:{t.text};"
            f" padding:6px 14px; border:1px solid {t.overlay}; }}"
            f"QTabBar::tab:selected {{ background:{t.mauve}; color:{t.bg}; }}"
            f"QTableWidget {{ background:{t.surface}; color:{t.text};"
            f" gridline-color:{t.overlay}; }}"
            f"QHeaderView::section {{ background:{t.overlay}; color:{t.text};"
            f" padding:4px; border:0; }}"
            f"QListWidget {{ background:{t.surface}; border:1px solid {t.overlay}; }}"
            f"QLabel {{ color:{t.text}; }}"
        )
        self.setStyleSheet(css)

    # ------------------------------------------------------------------
    def show_em_result(self, result) -> None:
        self._em_tab.show_em_result(result)
        self._tabs.setCurrentIndex(0)
        self._status.setText(
            f"EM: {len(result.violations)} violations / {result.wires_checked} wires"
        )

    def show_emi_result(self, result) -> None:
        self._emi_tab.show_emi_result(result)
        self._status.setText(
            f"EMI: worst {result.worst_emission_db_uv_per_m:.1f} dBuV/m "
            f"@ {result.worst_frequency_mhz:.1f} MHz"
        )

    def show_esd_result(self, result) -> None:
        self._esd_tab.show_esd_result(result)
        self._status.setText(
            f"ESD: {len(result.violations)} violations across {result.pins_checked} pins"
        )
