"""Density fill / tap / decap / antenna diode panel.

Presents per-layer density bars, a matplotlib heatmap, and buttons to
insert fill cells, tap cells, decoupling capacitors and antenna diodes
via the :mod:`openforge.physical.density_fill`, ``tap_decap`` and
``antenna`` fixers.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.antenna import AntennaChecker, AntennaFixer
    from openforge.physical.density_fill import SKY130_FILL_RULES, DensityFiller
    from openforge.physical.tap_decap import (
        SKY130_DECAP_CELLS,
        DecapInserter,
        TapInserter,
    )
    _HAS_CORE = True
except Exception:  # pragma: no cover
    DensityFiller = None  # type: ignore[assignment]
    SKY130_FILL_RULES = []  # type: ignore[assignment]
    TapInserter = None  # type: ignore[assignment]
    DecapInserter = None  # type: ignore[assignment]
    SKY130_DECAP_CELLS = {}  # type: ignore[assignment]
    AntennaChecker = None  # type: ignore[assignment]
    AntennaFixer = None  # type: ignore[assignment]
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


class DensityFillPanel(QWidget):
    """UI driver for fill / tap / decap / diode insertion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("densityFillPanel")
        self.setStyleSheet(panel_tab_qss(True))

        self._def_path: Path | None = None
        self._lef_path: Path | None = None
        self._filler: DensityFiller | None = None
        self._bars: dict[str, QProgressBar] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Paths toolbar ─────────────────────────────────────────────
        paths = QHBoxLayout()
        self._def_btn = QPushButton("Open DEF…")
        self._def_btn.clicked.connect(self._on_open_def)
        paths.addWidget(self._def_btn)
        self._lef_btn = QPushButton("Open LEF…")
        self._lef_btn.clicked.connect(self._on_open_lef)
        paths.addWidget(self._lef_btn)
        self._measure_btn = QPushButton("Measure Density")
        self._measure_btn.clicked.connect(self._on_measure)
        paths.addWidget(self._measure_btn)
        paths.addStretch(1)
        root.addLayout(paths)

        # ── Density bars ──────────────────────────────────────────────
        bars_box = QGroupBox("Per-layer density")
        bars_form = QFormLayout(bars_box)
        for rule in SKY130_FILL_RULES:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFormat(f"{rule.layer}: %v%  (min {int(rule.min_density_pct)}%)")
            bars_form.addRow(QLabel(rule.layer), bar)
            self._bars[rule.layer] = bar
        root.addWidget(bars_box)

        # ── Heatmap ───────────────────────────────────────────────────
        heat_box = QGroupBox("Density heatmap")
        heat_layout = QVBoxLayout(heat_box)
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Layer:"))
        self._layer_combo = QComboBox()
        for rule in SKY130_FILL_RULES:
            self._layer_combo.addItem(rule.layer)
        self._layer_combo.currentTextChanged.connect(self._on_layer_changed)
        layer_row.addWidget(self._layer_combo)
        layer_row.addStretch(1)
        heat_layout.addLayout(layer_row)
        if _HAS_MPL:
            self._fig = Figure(figsize=(4.0, 2.4), tight_layout=True)
            self._canvas = FigureCanvasQTAgg(self._fig)
            heat_layout.addWidget(self._canvas)
        else:
            heat_layout.addWidget(QLabel("(matplotlib not available)"))
        root.addWidget(heat_box, 1)

        # ── Action buttons ────────────────────────────────────────────
        actions = QGroupBox("Actions")
        a_layout = QHBoxLayout(actions)
        self._fill_btn = QPushButton("Insert Fill (all)")
        self._fill_btn.clicked.connect(self._on_insert_fill)
        a_layout.addWidget(self._fill_btn)

        self._tap_btn = QPushButton("Insert Tap Cells")
        self._tap_btn.clicked.connect(self._on_insert_taps)
        a_layout.addWidget(self._tap_btn)
        self._tap_interval = QDoubleSpinBox()
        self._tap_interval.setRange(5.0, 100.0)
        self._tap_interval.setValue(25.0)
        self._tap_interval.setSuffix(" µm")
        a_layout.addWidget(self._tap_interval)

        self._decap_btn = QPushButton("Insert Decaps")
        self._decap_btn.clicked.connect(self._on_insert_decaps)
        a_layout.addWidget(self._decap_btn)
        self._decap_pct = QDoubleSpinBox()
        self._decap_pct.setRange(0.5, 30.0)
        self._decap_pct.setValue(5.0)
        self._decap_pct.setSuffix(" %")
        a_layout.addWidget(self._decap_pct)

        self._diode_btn = QPushButton("Insert Antenna Diodes")
        self._diode_btn.clicked.connect(self._on_insert_diodes)
        a_layout.addWidget(self._diode_btn)
        a_layout.addStretch(1)
        root.addWidget(actions)

        # ── Results table ─────────────────────────────────────────────
        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(
            ["Operation", "Layer/Row", "Before", "After", "Cells inserted"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._table)

    # ------------------------------------------------------------------ api

    def set_files(self, def_path: str | Path, lef_path: str | Path) -> None:
        self._def_path = Path(def_path)
        self._lef_path = Path(lef_path)
        if DensityFiller is not None:
            try:
                self._filler = DensityFiller(self._def_path, self._lef_path)
            except Exception:
                self._filler = None
        self._on_measure()

    # --------------------------------------------------------------- slots

    def _on_open_def(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DEF", "", "DEF (*.def);;All Files (*)"
        )
        if path:
            self._def_path = Path(path)

    def _on_open_lef(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open LEF", "", "LEF (*.lef *.tlef);;All Files (*)"
        )
        if path:
            self._lef_path = Path(path)

    def _ensure_filler(self) -> bool:
        if self._filler is not None:
            return True
        if DensityFiller is None or not self._def_path or not self._lef_path:
            return False
        try:
            self._filler = DensityFiller(self._def_path, self._lef_path)
            return True
        except Exception:
            return False

    def _on_measure(self) -> None:
        if not self._ensure_filler():
            return
        assert self._filler is not None
        for rule in SKY130_FILL_RULES:
            try:
                d = self._filler.overall_density(rule.layer)
            except Exception:
                d = 0.0
            bar = self._bars.get(rule.layer)
            if bar is not None:
                bar.setValue(int(round(d)))
        self._on_layer_changed(self._layer_combo.currentText())

    def _on_layer_changed(self, layer: str) -> None:
        if not _HAS_MPL or self._filler is None or not layer:
            return
        try:
            density_map = self._filler.measure_density(layer, window_size_um=20.0)
        except Exception:
            return
        if not density_map:
            return
        xs = sorted({x for (x, _y) in density_map})
        ys = sorted({y for (_x, y) in density_map})
        grid = [[density_map.get((x, y), 0.0) for x in xs] for y in ys]
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        if grid and grid[0]:
            ax.imshow(
                grid,
                origin="lower",
                aspect="auto",
                cmap="viridis",
                vmin=0,
                vmax=100,
            )
            ax.set_title(f"{layer} density (%)")
        self._canvas.draw_idle()

    def _append_row(
        self, op: str, label: str, before: str, after: str, inserted: int
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(op))
        self._table.setItem(row, 1, QTableWidgetItem(label))
        self._table.setItem(row, 2, QTableWidgetItem(before))
        self._table.setItem(row, 3, QTableWidgetItem(after))
        self._table.setItem(row, 4, QTableWidgetItem(str(inserted)))

    def _on_insert_fill(self) -> None:
        if not self._ensure_filler():
            return
        assert self._filler is not None
        results = self._filler.fill_all()
        for layer, res in results.items():
            self._append_row(
                "Fill",
                layer,
                f"{res.pre_density_pct:.1f}%",
                f"{res.post_density_pct:.1f}%",
                res.cells_inserted,
            )
            bar = self._bars.get(layer)
            if bar is not None:
                bar.setValue(int(round(res.post_density_pct)))

    def _on_insert_taps(self) -> None:
        if TapInserter is None or not self._def_path or not self._lef_path:
            return
        try:
            t = TapInserter(self._def_path, self._lef_path)
            res = t.insert_taps(interval_um=self._tap_interval.value())
        except Exception:
            self._append_row("Tap", "-", "-", "ERROR", 0)
            return
        self._append_row(
            "Tap",
            f"{res.max_distance_um:.1f} µm max",
            "-",
            "OK" if res.valid else "CHECK",
            res.cells_inserted,
        )

    def _on_insert_decaps(self) -> None:
        if DecapInserter is None or not self._def_path or not self._lef_path:
            return
        try:
            d = DecapInserter(self._def_path, self._lef_path)
            res = d.insert_decaps(
                SKY130_DECAP_CELLS, target_per_row_pct=self._decap_pct.value()
            )
        except Exception:
            self._append_row("Decap", "-", "-", "ERROR", 0)
            return
        self._append_row(
            "Decap",
            f"{res.total_decap_pf:.3f} pF",
            "-",
            "OK",
            res.cells_inserted,
        )

    def _on_insert_diodes(self) -> None:
        if (
            AntennaChecker is None
            or AntennaFixer is None
            or not self._def_path
            or not self._lef_path
        ):
            return
        try:
            chk = AntennaChecker.sky130_rules()
            violations = chk.check(self._def_path, self._lef_path)
            fixer = AntennaFixer(violations, self._def_path, self._lef_path)
            fixes = fixer.insert_diodes()
        except Exception:
            self._append_row("Diodes", "-", "-", "ERROR", 0)
            return
        self._append_row(
            "Diodes",
            f"{len(violations)} violations",
            "-",
            "FIXED",
            len(fixes),
        )


__all__ = ["DensityFillPanel"]
