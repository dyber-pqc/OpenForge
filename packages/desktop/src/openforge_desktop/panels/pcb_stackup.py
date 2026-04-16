"""PCB stackup editor panel with live impedance calculator."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.pcb.impedance import (
        ImpedanceCalculator,
        MATERIAL_PRESETS,
        StackupLayer,
        StackupValidator,
        default_4layer_stackup,
    )
    _HAS_IMPEDANCE = True
except Exception:  # noqa: BLE001
    _HAS_IMPEDANCE = False

try:
    from openforge_desktop.widgets.pcb_3d_viewer import Pcb3dViewer
    _HAS_3D = True
except Exception:  # noqa: BLE001
    _HAS_3D = False


LAYER_KINDS = ["signal", "plane", "dielectric", "mask", "silk", "paste"]


class PcbStackupPanel(QWidget):
    """Interactive stackup editor with impedance solver."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layers: list = []
        if _HAS_IMPEDANCE:
            self._layers = list(default_4layer_stackup())
        self._build_ui()
        self._refresh_table()
        self._recompute_impedance()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # -------- Left: stackup table --------
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("<b>Stackup</b>"))
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(list(MATERIAL_PRESETS.keys()) if _HAS_IMPEDANCE else [])
        header_row.addWidget(QLabel("Material preset:"))
        header_row.addWidget(self._preset_combo)
        header_row.addStretch(1)
        llay.addLayout(header_row)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Kind", "Thickness (mm)", "Material", "er", "tan delta", "Cu oz"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        llay.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add Layer")
        self._del_btn = QPushButton("Remove")
        self._up_btn = QPushButton("Move Up")
        self._down_btn = QPushButton("Move Down")
        for b in (self._add_btn, self._del_btn, self._up_btn, self._down_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        llay.addLayout(btn_row)

        self._summary_label = QLabel()
        self._summary_label.setStyleSheet("color: #ccc;")
        llay.addWidget(self._summary_label)

        save_row = QHBoxLayout()
        self._save_btn = QPushButton("Save JSON")
        self._load_btn = QPushButton("Load JSON")
        save_row.addWidget(self._save_btn)
        save_row.addWidget(self._load_btn)
        save_row.addStretch(1)
        llay.addLayout(save_row)

        splitter.addWidget(left)

        # -------- Right: impedance + 3D preview --------
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)

        imp_group = QGroupBox("Impedance Calculator")
        form = QFormLayout(imp_group)
        self._imp_kind = QComboBox()
        self._imp_kind.addItems(
            ["microstrip (SE)", "microstrip (diff)", "stripline (SE)",
             "stripline (diff)", "coplanar (SE)"]
        )
        form.addRow("Type:", self._imp_kind)

        self._trace_width = QDoubleSpinBox()
        self._trace_width.setRange(0.05, 10.0)
        self._trace_width.setDecimals(4)
        self._trace_width.setValue(0.2)
        self._trace_width.setSuffix(" mm")
        form.addRow("Trace width:", self._trace_width)

        self._trace_gap = QDoubleSpinBox()
        self._trace_gap.setRange(0.05, 10.0)
        self._trace_gap.setDecimals(4)
        self._trace_gap.setValue(0.2)
        self._trace_gap.setSuffix(" mm")
        form.addRow("Diff gap:", self._trace_gap)

        self._dielectric_h = QDoubleSpinBox()
        self._dielectric_h.setRange(0.01, 5.0)
        self._dielectric_h.setDecimals(4)
        self._dielectric_h.setValue(0.21)
        self._dielectric_h.setSuffix(" mm")
        form.addRow("Dielectric h:", self._dielectric_h)

        self._er_spin = QDoubleSpinBox()
        self._er_spin.setRange(1.0, 20.0)
        self._er_spin.setDecimals(3)
        self._er_spin.setValue(4.4)
        form.addRow("Dielectric er:", self._er_spin)

        self._copper_t = QDoubleSpinBox()
        self._copper_t.setRange(0.005, 1.0)
        self._copper_t.setDecimals(4)
        self._copper_t.setValue(0.035)
        self._copper_t.setSuffix(" mm")
        form.addRow("Copper thickness:", self._copper_t)

        self._impedance_label = QLabel()
        self._impedance_label.setStyleSheet(
            "font-size: 16px; color: #9cdcfe; font-weight: bold;"
        )
        form.addRow("Z0:", self._impedance_label)

        self._extra_label = QLabel()
        self._extra_label.setStyleSheet("color: #bbb;")
        form.addRow(" ", self._extra_label)

        target_row = QHBoxLayout()
        self._target_z = QDoubleSpinBox()
        self._target_z.setRange(10.0, 200.0)
        self._target_z.setValue(50.0)
        self._target_z.setSuffix(" \u03a9")
        target_row.addWidget(self._target_z)
        self._find_width_btn = QPushButton("Find Width")
        target_row.addWidget(self._find_width_btn)
        form.addRow("Target:", target_row)

        rlay.addWidget(imp_group)

        if _HAS_3D:
            prev_group = QGroupBox("Stackup Preview")
            pg_lay = QVBoxLayout(prev_group)
            self._preview = Pcb3dViewer()
            self._preview.setMinimumHeight(220)
            pg_lay.addWidget(self._preview)
            rlay.addWidget(prev_group, 1)
        else:
            self._preview = None
            rlay.addStretch(1)

        splitter.addWidget(right)
        splitter.setSizes([500, 400])

        # Signals
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn.clicked.connect(self._on_remove)
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn.clicked.connect(lambda: self._move(1))
        self._save_btn.clicked.connect(self._on_save)
        self._load_btn.clicked.connect(self._on_load)
        for w in (
            self._imp_kind,
            self._trace_width,
            self._trace_gap,
            self._dielectric_h,
            self._er_spin,
            self._copper_t,
        ):
            if hasattr(w, "valueChanged"):
                w.valueChanged.connect(self._recompute_impedance)
            if hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self._recompute_impedance)
        self._find_width_btn.clicked.connect(self._on_find_width)
        self._preset_combo.currentTextChanged.connect(self._on_preset)
        self._table.itemChanged.connect(self._on_item_changed)

    # ------------------------------------------------------------------
    def _refresh_table(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._layers))
        for row, layer in enumerate(self._layers):
            self._table.setItem(row, 0, QTableWidgetItem(layer.name))
            self._table.setItem(row, 1, QTableWidgetItem(layer.kind))
            self._table.setItem(row, 2, QTableWidgetItem(f"{layer.thickness_mm:.4f}"))
            self._table.setItem(row, 3, QTableWidgetItem(layer.material or ""))
            self._table.setItem(
                row, 4,
                QTableWidgetItem(
                    "" if layer.dielectric_constant is None
                    else f"{layer.dielectric_constant:.3f}"
                ),
            )
            self._table.setItem(
                row, 5,
                QTableWidgetItem(
                    "" if layer.loss_tangent is None else f"{layer.loss_tangent:.4f}"
                ),
            )
            self._table.setItem(
                row, 6,
                QTableWidgetItem(
                    "" if layer.copper_oz is None else f"{layer.copper_oz:.2f}"
                ),
            )
        self._table.blockSignals(False)
        self._update_summary()

    def _update_summary(self) -> None:
        if not _HAS_IMPEDANCE:
            self._summary_label.setText("impedance module unavailable")
            return
        v = StackupValidator(self._layers)
        rep = v.report()
        self._summary_label.setText(
            f"Total: {rep['total_thickness_mm']:.3f} mm  |  "
            f"Signals: {rep['signal_layers']}  Planes: {rep['plane_layers']}  |  "
            f"Balanced: {'Yes' if rep['balanced'] else 'No'}"
        )

    # ------------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if not _HAS_IMPEDANCE:
            return
        row = item.row()
        col = item.column()
        if row >= len(self._layers):
            return
        layer = self._layers[row]
        text = item.text().strip()
        try:
            if col == 0:
                layer.name = text
            elif col == 1 and text in LAYER_KINDS:
                layer.kind = text
            elif col == 2:
                layer.thickness_mm = float(text)
            elif col == 3:
                layer.material = text
            elif col == 4:
                layer.dielectric_constant = float(text) if text else None
            elif col == 5:
                layer.loss_tangent = float(text) if text else None
            elif col == 6:
                layer.copper_oz = float(text) if text else None
        except ValueError:
            pass
        self._layers[row] = layer
        self._update_summary()

    def _on_add(self) -> None:
        if not _HAS_IMPEDANCE:
            return
        self._layers.append(
            StackupLayer(
                name=f"Layer{len(self._layers)+1}",
                kind="signal",
                thickness_mm=0.035,
                material="copper",
            )
        )
        self._refresh_table()

    def _on_remove(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._layers):
            self._layers.pop(row)
            self._refresh_table()

    def _move(self, delta: int) -> None:
        row = self._table.currentRow()
        new = row + delta
        if 0 <= row < len(self._layers) and 0 <= new < len(self._layers):
            self._layers[row], self._layers[new] = self._layers[new], self._layers[row]
            self._refresh_table()
            self._table.setCurrentCell(new, 0)

    def _on_preset(self, name: str) -> None:
        if not _HAS_IMPEDANCE or name not in MATERIAL_PRESETS:
            return
        preset = MATERIAL_PRESETS[name]
        self._er_spin.setValue(float(preset.get("er", 4.4)))

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Stackup", "stackup.json", "JSON (*.json)"
        )
        if not path:
            return
        data = [l.model_dump() for l in self._layers]
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _on_load(self) -> None:
        if not _HAS_IMPEDANCE:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Stackup", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self._layers = [StackupLayer(**entry) for entry in data]
            self._refresh_table()
            self._recompute_impedance()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def _recompute_impedance(self) -> None:
        if not _HAS_IMPEDANCE:
            self._impedance_label.setText("N/A")
            return
        kind = self._imp_kind.currentText()
        w = self._trace_width.value()
        g = self._trace_gap.value()
        h = self._dielectric_h.value()
        t = self._copper_t.value()
        er = self._er_spin.value()
        try:
            if kind.startswith("microstrip (SE)"):
                res = ImpedanceCalculator.microstrip_se(w, h, t, er)
            elif kind.startswith("microstrip (diff)"):
                res = ImpedanceCalculator.microstrip_diff(w, g, h, t, er)
            elif kind.startswith("stripline (SE)"):
                res = ImpedanceCalculator.stripline_se(w, h, h, t, er)
            elif kind.startswith("stripline (diff)"):
                res = ImpedanceCalculator.stripline_diff(w, g, h, h, t, er)
            else:
                res = ImpedanceCalculator.coplanar_se(w, g, h, t, er)
        except Exception as e:  # noqa: BLE001
            self._impedance_label.setText(f"error: {e}")
            return
        self._impedance_label.setText(f"{res.impedance_ohm:.2f} \u03a9")
        self._extra_label.setText(
            f"L = {res.inductance_nh_per_mm:.3f} nH/mm  |  "
            f"C = {res.capacitance_pf_per_mm:.3f} pF/mm  |  "
            f"delay = {res.delay_ns_per_mm*1000:.2f} ps/mm  |  "
            f"er_eff = {res.er_effective:.3f}"
        )

    def _on_find_width(self) -> None:
        if not _HAS_IMPEDANCE:
            return
        kind_text = self._imp_kind.currentText()
        kind = "stripline" if "stripline" in kind_text else "microstrip"
        w = ImpedanceCalculator.find_width_for_impedance(
            target_ohm=self._target_z.value(),
            height_mm=self._dielectric_h.value(),
            er=self._er_spin.value(),
            kind=kind,
            t_mm=self._copper_t.value(),
        )
        self._trace_width.setValue(round(w, 4))


__all__ = ["PcbStackupPanel"]
