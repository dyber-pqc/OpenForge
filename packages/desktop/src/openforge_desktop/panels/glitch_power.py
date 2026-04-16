"""Glitch power analysis panel.

Loads a VCD, runs :class:`openforge.physical.glitch_power.GlitchPowerAnalyzer`,
and shows the top glitchy signals, a glitch-width histogram and the
total glitch power.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.glitch_power import (
        GlitchPowerAnalyzer,
        GlitchPowerResult,
    )
    _HAS_CORE = True
except Exception:  # pragma: no cover
    GlitchPowerAnalyzer = None  # type: ignore[assignment]
    GlitchPowerResult = None  # type: ignore[assignment]
    _HAS_CORE = False

try:
    from openforge_desktop.panels._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore[misc]
        return ""

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    _HAS_MPL = True
except Exception:  # pragma: no cover
    FigureCanvasQTAgg = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]
    _HAS_MPL = False


class GlitchPowerPanel(QWidget):
    """Interactive glitch power analyser."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("glitchPowerPanel")
        self.setStyleSheet(panel_tab_qss(True))

        self._vcd_path: Path | None = None
        self._analyzer: GlitchPowerAnalyzer | None = None
        self._result: GlitchPowerResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── toolbar ───────────────────────────────────────────────────
        tools = QHBoxLayout()
        self._load_btn = QPushButton("Load VCD…")
        self._load_btn.clicked.connect(self._on_load)
        tools.addWidget(self._load_btn)
        self._vcd_label = QLineEdit()
        self._vcd_label.setReadOnly(True)
        tools.addWidget(self._vcd_label, 1)
        tools.addWidget(QLabel("Min pulse:"))
        self._min_pulse = QDoubleSpinBox()
        self._min_pulse.setRange(0.01, 10.0)
        self._min_pulse.setValue(0.5)
        self._min_pulse.setSuffix(" ns")
        tools.addWidget(self._min_pulse)
        tools.addWidget(QLabel("VDD:"))
        self._vdd = QDoubleSpinBox()
        self._vdd.setRange(0.5, 5.0)
        self._vdd.setValue(1.8)
        self._vdd.setSuffix(" V")
        tools.addWidget(self._vdd)
        self._run_btn = QPushButton("Run Analysis")
        self._run_btn.clicked.connect(self._on_run)
        tools.addWidget(self._run_btn)
        root.addLayout(tools)

        # ── summary tile ──────────────────────────────────────────────
        self._summary = QLabel("Load a VCD to begin.")
        self._summary.setStyleSheet(
            "font-size: 14pt; padding: 8px; background: #313244; "
            "color: #cdd6f4; border-radius: 4px;"
        )
        root.addWidget(self._summary)

        # ── tables + histogram ────────────────────────────────────────
        body = QHBoxLayout()

        table_box = QGroupBox("Top glitchy signals")
        tbl_layout = QVBoxLayout(table_box)
        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(
            ["Signal", "Glitches", "Energy (pJ)"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl_layout.addWidget(self._table)
        body.addWidget(table_box, 1)

        hist_box = QGroupBox("Glitch width distribution")
        hist_layout = QVBoxLayout(hist_box)
        if _HAS_MPL:
            self._fig = Figure(figsize=(4.0, 2.4), tight_layout=True)
            self._canvas = FigureCanvasQTAgg(self._fig)
            hist_layout.addWidget(self._canvas)
        else:
            hist_layout.addWidget(QLabel("(matplotlib not available)"))
        body.addWidget(hist_box, 1)

        root.addLayout(body, 1)

    # ------------------------------------------------------------------ api

    def load_vcd(self, path: str | Path) -> None:
        self._vcd_path = Path(path)
        self._vcd_label.setText(str(path))
        if GlitchPowerAnalyzer is not None:
            try:
                self._analyzer = GlitchPowerAnalyzer(path)
            except Exception as exc:  # pragma: no cover
                self._summary.setText(f"Failed to load VCD: {exc}")
                self._analyzer = None

    # --------------------------------------------------------------- slots

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open VCD", "", "VCD (*.vcd);;All Files (*)"
        )
        if path:
            self.load_vcd(path)

    def _on_run(self) -> None:
        if self._analyzer is None:
            self._summary.setText("No VCD loaded.")
            return
        try:
            self._analyzer.detect_glitches(
                min_pulse_width_ns=self._min_pulse.value()
            )
            result = self._analyzer.estimate_power(vdd=self._vdd.value())
        except Exception as exc:  # pragma: no cover
            self._summary.setText(f"Analysis failed: {exc}")
            return
        self._result = result

        self._summary.setText(
            f"Glitch power: {result.total_glitch_power_mw*1000:.2f} µW   "
            f"Glitches: {result.glitch_count}   "
            f"Energy: {result.total_energy_pj:.3f} pJ   "
            f"Duration: {result.simulation_duration_ns:.1f} ns"
        )

        self._table.setRowCount(len(result.top_glitchy_signals))
        for r, (sig, n, energy) in enumerate(result.top_glitchy_signals):
            self._table.setItem(r, 0, QTableWidgetItem(sig))
            self._table.setItem(r, 1, QTableWidgetItem(str(n)))
            self._table.setItem(r, 2, QTableWidgetItem(f"{energy:.4f}"))
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)

        if _HAS_MPL:
            widths: list[float] = []
            for _sig, ev_list in result.events_by_signal.items():
                widths.extend(e.duration_ns for e in ev_list)
            self._fig.clear()
            ax = self._fig.add_subplot(111)
            if widths:
                ax.hist(widths, bins=20, color="#89b4fa", edgecolor="#1e1e2e")
                ax.set_xlabel("pulse width (ns)")
                ax.set_ylabel("count")
                ax.set_title(f"{len(widths)} glitches")
            else:
                ax.text(0.5, 0.5, "no glitches", ha="center", va="center")
            self._canvas.draw_idle()


__all__ = ["GlitchPowerPanel"]
