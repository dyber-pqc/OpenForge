"""Integrated Logic Analyzer (ILA) debug panel.

Provides a full-featured in-system debugger UI:

* Probe builder sourced from the project hierarchy
* Multi-stage trigger sequencer
* Circular / one-shot / multi-window capture
* Real-time JTAG status (adapter, scan chain)
* Arm / Force / Stop / Reset controls
* Multi-shot captures, each written to its own VCD
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.fpga.debug import (  # noqa: F401
        CaptureMode,
        DebugCore,
        DebugProbe,
        IlaReader,
        IlaVendor,
        TriggerCondition,
        TriggerKind,
        TriggerSequence,
        render_advanced_ila,
    )
except Exception:  # pragma: no cover
    CaptureMode = None  # type: ignore[assignment,misc]
    DebugCore = None  # type: ignore[assignment,misc]
    DebugProbe = None  # type: ignore[assignment,misc]
    IlaReader = None  # type: ignore[assignment,misc]
    IlaVendor = None  # type: ignore[assignment,misc]
    TriggerCondition = None  # type: ignore[assignment,misc]
    TriggerKind = None  # type: ignore[assignment,misc]
    TriggerSequence = None  # type: ignore[assignment,misc]
    render_advanced_ila = None  # type: ignore[assignment,misc]

try:
    from openforge.jtag.bridge import JtagBridge
except Exception:  # pragma: no cover
    JtagBridge = None  # type: ignore[assignment,misc]

try:
    from openforge_desktop.theme.design_system import DARK_PALETTE
except Exception:  # pragma: no cover
    DARK_PALETTE = None  # type: ignore[assignment,misc]


class IlaDebugPanel(QDockWidget):
    """Dockable ILA debug panel."""

    loadVcd = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ILA Debug", parent)
        self.setObjectName("ila_debug_dock")
        self._project_root: Path | None = None
        self._bridge: Any = None  # JtagBridge | None
        self._reader: Any = None  # IlaReader | None
        self._multi_shot_remaining = 0
        self._capture_counter = 0

        self._build_ui()
        self._apply_theme()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        body = QWidget(self)
        root = QVBoxLayout(body)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---- Probes ----
        probes_box = QGroupBox("Probes")
        probes_layout = QVBoxLayout(probes_box)

        self._hierarchy_hint = QLabel(
            "Load probes from a hierarchy JSON, or add them manually."
        )
        probes_layout.addWidget(self._hierarchy_hint)

        load_row = QHBoxLayout()
        self._load_hier_btn = QPushButton("Load Hierarchy JSON…")
        self._load_hier_btn.clicked.connect(self._on_load_hierarchy)
        self._add_probe_btn = QPushButton("Add Probe")
        self._add_probe_btn.clicked.connect(self._on_add_probe)
        self._remove_probe_btn = QPushButton("Remove")
        self._remove_probe_btn.clicked.connect(self._on_remove_probe)
        load_row.addWidget(self._load_hier_btn)
        load_row.addWidget(self._add_probe_btn)
        load_row.addWidget(self._remove_probe_btn)
        load_row.addStretch(1)
        probes_layout.addLayout(load_row)

        self._probe_table = QTableWidget(0, 3)
        self._probe_table.setHorizontalHeaderLabels(["Probe", "Signal", "Width"])
        self._probe_table.horizontalHeader().setStretchLastSection(True)
        self._probe_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        probes_layout.addWidget(self._probe_table)
        root.addWidget(probes_box)

        # ---- Trigger sequencer ----
        trig_box = QGroupBox("Trigger Sequencer (up to 8 stages)")
        trig_layout = QVBoxLayout(trig_box)
        self._trigger_table = QTableWidget(0, 4)
        self._trigger_table.setHorizontalHeaderLabels(
            ["Probe", "Kind", "Value", "Count"]
        )
        self._trigger_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        trig_layout.addWidget(self._trigger_table)
        trig_row = QHBoxLayout()
        self._add_stage_btn = QPushButton("Add Stage")
        self._add_stage_btn.clicked.connect(self._on_add_stage)
        self._del_stage_btn = QPushButton("Remove Stage")
        self._del_stage_btn.clicked.connect(self._on_remove_stage)
        trig_row.addWidget(self._add_stage_btn)
        trig_row.addWidget(self._del_stage_btn)
        trig_row.addStretch(1)
        trig_layout.addLayout(trig_row)
        root.addWidget(trig_box)

        # ---- Capture config ----
        cap_box = QGroupBox("Capture")
        cap_form = QFormLayout(cap_box)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["circular", "one_shot", "multi_window"])
        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(64, 65536)
        self._depth_spin.setSingleStep(64)
        self._depth_spin.setValue(1024)
        self._vendor_combo = QComboBox()
        self._vendor_combo.addItems(["xilinx", "ecp5", "ice40", "gowin"])
        self._shots_spin = QSpinBox()
        self._shots_spin.setRange(1, 1024)
        self._shots_spin.setValue(1)
        cap_form.addRow("Mode", self._mode_combo)
        cap_form.addRow("Depth (samples)", self._depth_spin)
        cap_form.addRow("Vendor primitive", self._vendor_combo)
        cap_form.addRow("Multi-shot captures", self._shots_spin)
        root.addWidget(cap_box)

        gen_row = QHBoxLayout()
        self._gen_btn = QPushButton("Generate ILA Verilog")
        self._gen_btn.clicked.connect(self._on_generate)
        gen_row.addWidget(self._gen_btn)
        gen_row.addStretch(1)
        root.addLayout(gen_row)

        # ---- JTAG ----
        jtag_box = QGroupBox("JTAG")
        jtag_layout = QVBoxLayout(jtag_box)
        self._adapter_label = QLabel("Adapter: (none)")
        self._scan_list = QListWidget()
        self._scan_list.setMaximumHeight(80)
        jtag_row = QHBoxLayout()
        self._detect_btn = QPushButton("Detect")
        self._detect_btn.clicked.connect(self._on_detect_jtag)
        self._scan_btn = QPushButton("Scan Chain")
        self._scan_btn.clicked.connect(self._on_scan_chain)
        jtag_row.addWidget(self._detect_btn)
        jtag_row.addWidget(self._scan_btn)
        jtag_row.addStretch(1)
        jtag_layout.addWidget(self._adapter_label)
        jtag_layout.addWidget(self._scan_list)
        jtag_layout.addLayout(jtag_row)
        root.addWidget(jtag_box)

        # ---- Run controls ----
        run_box = QGroupBox("Run")
        run_layout = QVBoxLayout(run_box)
        ctl_row = QHBoxLayout()
        self._arm_btn = QPushButton("Arm")
        self._arm_btn.clicked.connect(self._on_arm)
        self._force_btn = QPushButton("Force Trigger")
        self._force_btn.clicked.connect(self._on_force)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset)
        self._view_btn = QPushButton("View Waveform")
        self._view_btn.clicked.connect(self._on_view_waveform)
        for btn in (
            self._arm_btn,
            self._force_btn,
            self._stop_btn,
            self._reset_btn,
            self._view_btn,
        ):
            ctl_row.addWidget(btn)
        ctl_row.addStretch(1)
        run_layout.addLayout(ctl_row)

        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setRange(0, 100)
        run_layout.addWidget(self._progress)

        self._status_label = QLabel("Status: idle")
        self._status_label.setFont(QFont("monospace"))
        run_layout.addWidget(self._status_label)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        run_layout.addWidget(self._log)
        root.addWidget(run_box)

        root.addStretch(1)
        self.setWidget(body)

    def _apply_theme(self) -> None:
        if DARK_PALETTE is None:
            return
        p = DARK_PALETTE
        self.setStyleSheet(
            f"""
            QDockWidget {{ background: {getattr(p, 'surface0', '#1e1e2e')}; }}
            QGroupBox {{
                border: 1px solid {getattr(p, 'surface2', '#313244')};
                border-radius: 6px;
                margin-top: 10px;
                padding: 6px;
                color: {getattr(p, 'text', '#cdd6f4')};
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: {getattr(p, 'blue', '#89b4fa')};
            }}
            QPushButton {{
                background: {getattr(p, 'surface1', '#45475a')};
                color: {getattr(p, 'text', '#cdd6f4')};
                border: 1px solid {getattr(p, 'surface2', '#585b70')};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: {getattr(p, 'blue', '#89b4fa')};
                color: {getattr(p, 'base', '#1e1e2e')};
            }}
            """
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_project_root(self, path: Path | str) -> None:
        self._project_root = Path(path)

    def _log_msg(self, msg: str) -> None:
        self._log.append(msg)

    # ------------------------------------------------------------------
    # Probe actions
    # ------------------------------------------------------------------

    def _on_load_hierarchy(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load hierarchy JSON", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text())
        except Exception as exc:
            QMessageBox.warning(self, "ILA", f"Failed to parse JSON: {exc}")
            return
        signals = data.get("signals", [])
        self._probe_table.setRowCount(0)
        for s in signals:
            name = s.get("name") or s.get("signal", "sig")
            sig = s.get("signal", name)
            width = int(s.get("width", 1))
            self._append_probe_row(name, sig, width)
        self._log_msg(f"Loaded {len(signals)} probes from {path}")

    def _append_probe_row(self, name: str, signal: str, width: int) -> None:
        row = self._probe_table.rowCount()
        self._probe_table.insertRow(row)
        self._probe_table.setItem(row, 0, QTableWidgetItem(name))
        self._probe_table.setItem(row, 1, QTableWidgetItem(signal))
        self._probe_table.setItem(row, 2, QTableWidgetItem(str(width)))

    def _on_add_probe(self) -> None:
        self._append_probe_row(f"probe{self._probe_table.rowCount()}", "sig", 1)

    def _on_remove_probe(self) -> None:
        row = self._probe_table.currentRow()
        if row >= 0:
            self._probe_table.removeRow(row)

    # ------------------------------------------------------------------
    # Trigger actions
    # ------------------------------------------------------------------

    def _on_add_stage(self) -> None:
        if self._trigger_table.rowCount() >= 8:
            QMessageBox.information(self, "ILA", "Maximum of 8 stages.")
            return
        row = self._trigger_table.rowCount()
        self._trigger_table.insertRow(row)
        self._trigger_table.setItem(row, 0, QTableWidgetItem("probe0"))
        kind_combo = QComboBox()
        kind_combo.addItems([k.value for k in (TriggerKind or [])]) if TriggerKind else kind_combo.addItems(
            [
                "edge_rise",
                "edge_fall",
                "level_high",
                "level_low",
                "eq",
                "neq",
                "gt",
                "lt",
                "any",
            ]
        )
        self._trigger_table.setCellWidget(row, 1, kind_combo)
        self._trigger_table.setItem(row, 2, QTableWidgetItem("0"))
        self._trigger_table.setItem(row, 3, QTableWidgetItem("1"))

    def _on_remove_stage(self) -> None:
        row = self._trigger_table.currentRow()
        if row >= 0:
            self._trigger_table.removeRow(row)

    def _collect_probes(self) -> list:
        if DebugProbe is None:
            return []
        probes = []
        for row in range(self._probe_table.rowCount()):
            name_item = self._probe_table.item(row, 0)
            sig_item = self._probe_table.item(row, 1)
            w_item = self._probe_table.item(row, 2)
            if not (name_item and sig_item and w_item):
                continue
            try:
                probes.append(
                    DebugProbe(
                        name=name_item.text(),
                        signal=sig_item.text(),
                        width=int(w_item.text()),
                    )
                )
            except Exception as exc:
                self._log_msg(f"Probe row {row} invalid: {exc}")
        return probes

    def _collect_trigger_sequence(self):
        if TriggerSequence is None or TriggerCondition is None or TriggerKind is None:
            return None
        stages: list[tuple] = []
        for row in range(self._trigger_table.rowCount()):
            probe_item = self._trigger_table.item(row, 0)
            kind_w = self._trigger_table.cellWidget(row, 1)
            val_item = self._trigger_table.item(row, 2)
            count_item = self._trigger_table.item(row, 3)
            if not (probe_item and kind_w and val_item and count_item):
                continue
            try:
                kind = TriggerKind(kind_w.currentText())  # type: ignore[call-arg]
                val_txt = val_item.text().strip()
                val = int(val_txt, 0) if val_txt else 0
                count = max(1, int(count_item.text()))
                stages.append(
                    (
                        TriggerCondition(
                            probe=probe_item.text(), kind=kind, value=val
                        ),
                        count,
                    )
                )
            except Exception as exc:
                self._log_msg(f"Trigger row {row} invalid: {exc}")
        return TriggerSequence(stages=stages)

    # ------------------------------------------------------------------
    # Generate Verilog
    # ------------------------------------------------------------------

    def _on_generate(self) -> None:
        if DebugCore is None or render_advanced_ila is None or CaptureMode is None:
            QMessageBox.warning(self, "ILA", "openforge.fpga.debug not available.")
            return
        probes = self._collect_probes()
        if not probes:
            QMessageBox.information(self, "ILA", "Add at least one probe.")
            return
        trig = self._collect_trigger_sequence()
        try:
            mode = CaptureMode(self._mode_combo.currentText())  # type: ignore[call-arg]
            vendor = IlaVendor(self._vendor_combo.currentText()) if IlaVendor else None  # type: ignore[call-arg]
        except Exception:
            mode = None
            vendor = None
        core = DebugCore(probes=probes, capture_depth=self._depth_spin.value())
        try:
            verilog = render_advanced_ila(
                core, trig or TriggerSequence(stages=[]), mode, 4, vendor or IlaVendor.XILINX  # type: ignore[arg-type]
            )
        except Exception as exc:
            QMessageBox.warning(self, "ILA", f"Render failed: {exc}")
            return

        root = self._project_root or Path.cwd()
        out_dir = root / "rtl" / "ila"
        out_dir.mkdir(parents=True, exist_ok=True)
        top_name = f"top{self._capture_counter}"
        out = out_dir / f"ila_{top_name}.v"
        out.write_text(verilog, encoding="utf-8")
        self._log_msg(f"Wrote {out}")

    # ------------------------------------------------------------------
    # JTAG
    # ------------------------------------------------------------------

    def _on_detect_jtag(self) -> None:
        if JtagBridge is None:
            self._adapter_label.setText("Adapter: openforge.jtag not available")
            return
        adapter = JtagBridge.auto_detect()
        if adapter:
            self._adapter_label.setText(
                f"Adapter: {adapter.name} ({adapter.usb_id})"
            )
            self._bridge = JtagBridge(adapter=adapter)
        else:
            self._adapter_label.setText("Adapter: none detected")

    def _on_scan_chain(self) -> None:
        self._scan_list.clear()
        if self._bridge is None:
            if JtagBridge is None:
                return
            self._bridge = JtagBridge()
        if not self._bridge.open():
            self._scan_list.addItem("(failed to open openocd)")
            return
        try:
            devs = self._bridge.scan_chain()
        except Exception as exc:
            self._scan_list.addItem(f"(scan failed: {exc})")
            return
        for d in devs:
            self._scan_list.addItem(
                QListWidgetItem(f"{d.idcode_hex}  {d.name}  irlen={d.irlen}")
            )
        if not devs:
            self._scan_list.addItem("(no devices)")

    # ------------------------------------------------------------------
    # Run controls
    # ------------------------------------------------------------------

    def _ensure_reader(self) -> bool:
        if self._reader is not None:
            return True
        if IlaReader is None or DebugCore is None or self._bridge is None:
            self._log_msg("JTAG bridge not initialized; use Detect first.")
            return False
        probes = self._collect_probes()
        core = DebugCore(probes=probes, capture_depth=self._depth_spin.value())
        try:
            self._reader = IlaReader(self._bridge, core)
            return True
        except Exception as exc:
            self._log_msg(f"IlaReader init failed: {exc}")
            return False

    def _on_arm(self) -> None:
        if not self._ensure_reader():
            return
        try:
            self._reader.arm()
            self._multi_shot_remaining = max(1, self._shots_spin.value())
            self._log_msg(
                f"Armed ({self._multi_shot_remaining} capture(s) queued)"
            )
            self._status_timer.start()
        except Exception as exc:
            self._log_msg(f"Arm failed: {exc}")

    def _on_force(self) -> None:
        if not self._ensure_reader():
            return
        try:
            self._reader.force_trigger()
            self._log_msg("Force trigger")
        except Exception as exc:
            self._log_msg(f"Force failed: {exc}")

    def _on_stop(self) -> None:
        self._status_timer.stop()
        self._log_msg("Stopped")

    def _on_reset(self) -> None:
        self._reader = None
        self._multi_shot_remaining = 0
        self._progress.setValue(0)
        self._status_label.setText("Status: idle")
        self._log_msg("Reset")

    def _refresh_status(self) -> None:
        if self._reader is None:
            return
        try:
            s = self._reader.status()
        except Exception as exc:
            self._status_label.setText(f"Status: error ({exc})")
            return
        depth = self._depth_spin.value()
        self._status_label.setText(
            f"armed={s['armed']} trig={s['triggered']} full={s['full']} "
            f"samples={s['sample_count']}/{depth}"
        )
        self._progress.setValue(
            int(100 * min(1.0, s["sample_count"] / max(1, depth)))
        )
        if s["full"]:
            self._capture_to_vcd()

    def _capture_to_vcd(self) -> None:
        if self._reader is None:
            return
        try:
            samples = self._reader.read_samples()
        except Exception as exc:
            self._log_msg(f"Read failed: {exc}")
            return
        root = self._project_root or Path.cwd()
        out_dir = root / "ila_captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        self._capture_counter += 1
        out = out_dir / f"capture_{self._capture_counter:04d}.vcd"
        try:
            self._reader.to_vcd(samples, out)
            self._log_msg(f"Wrote {out}")
            self.loadVcd.emit(str(out))
        except Exception as exc:
            self._log_msg(f"VCD write failed: {exc}")

        self._multi_shot_remaining -= 1
        if self._multi_shot_remaining > 0:
            try:
                self._reader.arm()
            except Exception as exc:
                self._log_msg(f"Re-arm failed: {exc}")
                self._status_timer.stop()
        else:
            self._status_timer.stop()

    def _on_view_waveform(self) -> None:
        root = self._project_root or Path.cwd()
        candidates = sorted((root / "ila_captures").glob("capture_*.vcd"))
        if not candidates:
            QMessageBox.information(self, "ILA", "No captures yet.")
            return
        self.loadVcd.emit(str(candidates[-1]))


__all__ = ["IlaDebugPanel"]
