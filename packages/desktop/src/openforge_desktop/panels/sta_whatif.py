"""STA what-if analysis panel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.sta_parser import StaReport, parse_sta_report_file
    from openforge.physical.sta_whatif import StaWhatIf, WhatIfChange
except Exception:  # pragma: no cover
    StaReport = None  # type: ignore[assignment]
    StaWhatIf = None  # type: ignore[assignment]
    WhatIfChange = None  # type: ignore[assignment]
    parse_sta_report_file = None  # type: ignore[assignment]


_BG = QColor("#1e1e2e")
_PANEL = QColor("#181825")
_SURFACE = QColor("#313244")
_TEXT = QColor("#cdd6f4")
_SUBTLE = QColor("#a6adc8")
_BLUE = QColor("#89b4fa")
_GREEN = QColor("#a6e3a1")
_RED = QColor("#f38ba8")
_YELLOW = QColor("#f9e2af")


class StaWhatIfPanel(QDockWidget):
    """Dock with knobs for live STA what-if preview."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("STA What-if", parent)
        self.setObjectName("sta_whatif_dock")
        self._whatif: Optional["StaWhatIf"] = None
        self._baseline_wns: float = 0.0
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setStyleSheet(
            f"background:{_BG.name()}; color:{_TEXT.name()};"
            "QLabel { color:#cdd6f4; }"
            "QLineEdit, QDoubleSpinBox, QComboBox {"
            f"  background:{_PANEL.name()}; color:{_TEXT.name()}; "
            "  border:1px solid #313244; padding:2px 4px; }"
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Toolbar ----------------------------------------------------
        tb = QToolBar()
        tb.setStyleSheet(
            f"QToolBar {{ background:{_PANEL.name()}; border:1px solid #313244; }}"
        )
        load_btn = QPushButton("Load STA Report")
        load_btn.clicked.connect(self._on_load)
        tb.addWidget(load_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset)
        tb.addWidget(reset_btn)
        apply_btn = QPushButton("Apply to Constraints")
        apply_btn.setStyleSheet(
            "QPushButton { background:#89b4fa; color:#1e1e2e; padding:4px 10px; "
            "border-radius:4px; font-weight:600; }"
        )
        apply_btn.clicked.connect(self._on_apply)
        tb.addWidget(apply_btn)
        layout.addWidget(tb)

        # --- Splitter: knobs | results ---------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        knobs = QFrame()
        knobs.setStyleSheet(
            f"background:{_PANEL.name()}; border:1px solid #313244; border-radius:4px;"
        )
        form = QFormLayout(knobs)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        # Clock period
        self._clock_name = QLineEdit("clk")
        form.addRow("Clock name", self._clock_name)
        self._period_spin = QDoubleSpinBox()
        self._period_spin.setRange(0.1, 1000.0)
        self._period_spin.setDecimals(3)
        self._period_spin.setSingleStep(0.1)
        self._period_spin.setValue(10.0)
        self._period_spin.valueChanged.connect(self._recompute)
        self._period_slider = QSlider(Qt.Orientation.Horizontal)
        self._period_slider.setRange(1, 10000)
        self._period_slider.setValue(100)
        self._period_slider.valueChanged.connect(
            lambda v: self._period_spin.setValue(v / 10.0)
        )
        form.addRow("Clock period (ns)", self._period_spin)
        form.addRow("", self._period_slider)

        # Driver strength
        self._driver_pattern = QLineEdit("*buf*")
        form.addRow("Driver cell pattern", self._driver_pattern)
        self._driver_scale = QDoubleSpinBox()
        self._driver_scale.setRange(0.1, 10.0)
        self._driver_scale.setSingleStep(0.1)
        self._driver_scale.setValue(1.0)
        self._driver_scale.valueChanged.connect(self._recompute)
        form.addRow("Driver strength scale", self._driver_scale)

        # Wire load
        self._wire_pattern = QLineEdit("*")
        form.addRow("Wire net pattern", self._wire_pattern)
        self._wire_scale = QDoubleSpinBox()
        self._wire_scale.setRange(0.1, 10.0)
        self._wire_scale.setSingleStep(0.1)
        self._wire_scale.setValue(1.0)
        self._wire_scale.valueChanged.connect(self._recompute)
        form.addRow("Wire load scale", self._wire_scale)

        # Derate
        self._derate_corner = QLineEdit("")
        form.addRow("Corner name (blank=any)", self._derate_corner)
        self._derate_val = QDoubleSpinBox()
        self._derate_val.setRange(0.5, 2.0)
        self._derate_val.setSingleStep(0.01)
        self._derate_val.setValue(1.0)
        self._derate_val.valueChanged.connect(self._recompute)
        form.addRow("OCV derate", self._derate_val)

        # Fanout
        self._fanout_pattern = QLineEdit("*")
        form.addRow("Fanout cell pattern", self._fanout_pattern)
        self._fanout_scale = QDoubleSpinBox()
        self._fanout_scale.setRange(0.1, 10.0)
        self._fanout_scale.setSingleStep(0.1)
        self._fanout_scale.setValue(1.0)
        self._fanout_scale.valueChanged.connect(self._recompute)
        form.addRow("Fanout scale", self._fanout_scale)

        splitter.addWidget(knobs)

        # Right: live readout + top-10 table
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        header_row = QHBoxLayout()
        self._wns_label = QLabel("WNS: -")
        self._wns_label.setStyleSheet(
            f"color:{_TEXT.name()}; font-size:22px; font-weight:700;"
        )
        header_row.addWidget(self._wns_label)
        self._delta_label = QLabel("")
        self._delta_label.setStyleSheet("font-size:14px; font-weight:600;")
        header_row.addWidget(self._delta_label)
        header_row.addStretch()
        rl.addLayout(header_row)

        self._paths_table = QTableWidget(0, 4)
        self._paths_table.setHorizontalHeaderLabels(
            ["Path", "Original slack", "New slack", "Delta"]
        )
        self._paths_table.setStyleSheet(
            f"QTableWidget {{ background:{_PANEL.name()}; color:{_TEXT.name()}; "
            f"gridline-color:#313244; }}"
            f"QHeaderView::section {{ background:{_SURFACE.name()}; color:{_TEXT.name()}; "
            f"padding:4px; border:0; }}"
        )
        self._paths_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._paths_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        rl.addWidget(self._paths_table, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.setWidget(root)

    # ------------------------------------------------------------------

    def set_report(self, report: "StaReport") -> None:
        if StaWhatIf is None:
            return
        self._whatif = StaWhatIf(report)
        self._baseline_wns = report.wns
        if report.clocks:
            self._clock_name.setText(report.clocks[0].name)
            self._period_spin.setValue(report.clocks[0].period_ns)
            self._period_slider.setValue(int(report.clocks[0].period_ns * 10))
        self._recompute()

    def _on_load(self) -> None:
        if parse_sta_report_file is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open STA report", "", "Reports (*.rpt *.log *.txt);;All (*)"
        )
        if not path:
            return
        report = parse_sta_report_file(path)
        self.set_report(report)

    def _on_reset(self) -> None:
        if self._whatif is None:
            return
        self._whatif.reset()
        self._driver_scale.setValue(1.0)
        self._wire_scale.setValue(1.0)
        self._derate_val.setValue(1.0)
        self._fanout_scale.setValue(1.0)
        self._recompute()

    def _gather_changes(self) -> list["WhatIfChange"]:
        if WhatIfChange is None or self._whatif is None:
            return []
        changes: list[WhatIfChange] = []
        orig_period = self._whatif._period_of(self._clock_name.text())
        if orig_period and abs(self._period_spin.value() - orig_period) > 1e-6:
            changes.append(
                WhatIfChange(
                    kind="clock_period",
                    target=self._clock_name.text(),
                    old_value=orig_period,
                    new_value=self._period_spin.value(),
                )
            )
        if abs(self._driver_scale.value() - 1.0) > 1e-6:
            changes.append(
                WhatIfChange(
                    kind="driver_strength",
                    target=self._driver_pattern.text(),
                    old_value=1.0,
                    new_value=self._driver_scale.value(),
                )
            )
        if abs(self._wire_scale.value() - 1.0) > 1e-6:
            changes.append(
                WhatIfChange(
                    kind="wire_load",
                    target=self._wire_pattern.text(),
                    old_value=1.0,
                    new_value=self._wire_scale.value(),
                )
            )
        if abs(self._derate_val.value() - 1.0) > 1e-6:
            changes.append(
                WhatIfChange(
                    kind="derate",
                    target=self._derate_corner.text(),
                    old_value=1.0,
                    new_value=self._derate_val.value(),
                )
            )
        if abs(self._fanout_scale.value() - 1.0) > 1e-6:
            changes.append(
                WhatIfChange(
                    kind="fanout",
                    target=self._fanout_pattern.text(),
                    old_value=1.0,
                    new_value=self._fanout_scale.value(),
                )
            )
        return changes

    def _recompute(self) -> None:
        if self._whatif is None:
            return
        changes = self._gather_changes()
        new_report = self._whatif.apply(changes)
        wns = new_report.wns
        delta = wns - self._baseline_wns
        self._wns_label.setText(f"WNS: {wns:+.3f} ns")
        if delta > 1e-4:
            self._delta_label.setText(f"▲ +{delta:.3f}")
            self._delta_label.setStyleSheet(
                f"color:{_GREEN.name()}; font-size:14px; font-weight:600;"
            )
        elif delta < -1e-4:
            self._delta_label.setText(f"▼ {delta:.3f}")
            self._delta_label.setStyleSheet(
                f"color:{_RED.name()}; font-size:14px; font-weight:600;"
            )
        else:
            self._delta_label.setText("no change")
            self._delta_label.setStyleSheet(
                f"color:{_SUBTLE.name()}; font-size:14px; font-weight:600;"
            )

        # Top 10 by new slack
        paths = sorted(new_report.paths, key=lambda p: p.slack_ns)[:10]
        orig_map = {
            (p.startpoint, p.endpoint): p.slack_ns
            for p in self._whatif.original.paths
        }
        self._paths_table.setRowCount(len(paths))
        for r, p in enumerate(paths):
            original = orig_map.get((p.startpoint, p.endpoint), p.slack_ns)
            pdelta = p.slack_ns - original
            self._paths_table.setItem(
                r, 0, QTableWidgetItem(f"{p.startpoint} -> {p.endpoint}")
            )
            self._paths_table.setItem(r, 1, QTableWidgetItem(f"{original:+.3f}"))
            self._paths_table.setItem(r, 2, QTableWidgetItem(f"{p.slack_ns:+.3f}"))
            delta_item = QTableWidgetItem(f"{pdelta:+.3f}")
            if pdelta > 1e-4:
                delta_item.setForeground(QBrush(_GREEN))
            elif pdelta < -1e-4:
                delta_item.setForeground(QBrush(_RED))
            self._paths_table.setItem(r, 3, delta_item)

    def _on_apply(self) -> None:
        """Emit an SDC patch containing the applied changes."""
        changes = self._gather_changes()
        if not changes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save SDC patch", "whatif.sdc", "SDC (*.sdc);;Tcl (*.tcl)"
        )
        if not path:
            return
        lines = ["# SDC patch generated by OpenForge STA What-if"]
        for ch in changes:
            if ch.kind == "clock_period":
                lines.append(
                    f"create_clock -period {ch.new_value:.3f} "
                    f"[get_ports {ch.target}]  ;# was {ch.old_value:.3f}"
                )
            elif ch.kind == "driver_strength":
                lines.append(
                    f"# set_driving_cell -lib_cell <{ch.target}>  scale={ch.new_value:.2f}"
                )
            elif ch.kind == "wire_load":
                lines.append(
                    f"set_wire_load_model -name wlm_x{ch.new_value:.2f} "
                    f"[current_design]"
                )
            elif ch.kind == "derate":
                lines.append(
                    f"set_timing_derate -late {ch.new_value:.3f} "
                    f"{'[get_clocks ' + ch.target + ']' if ch.target else ''}"
                )
            elif ch.kind == "fanout":
                lines.append(
                    f"set_max_fanout {ch.new_value:.1f} [current_design] "
                    f"# pattern={ch.target}"
                )
        Path(path).write_text("\n".join(lines) + "\n")
