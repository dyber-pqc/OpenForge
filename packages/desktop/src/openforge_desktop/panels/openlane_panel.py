"""OpenLane2 dock panel.

Provides detection, configuration, step running, log tail, metrics
dashboard and Caravel project bootstrap from the OpenForge desktop app.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.openlane.openlane2 import (
        OpenLane2Config,
        OpenLane2Runner,
        OpenLane2Stage,
    )
except Exception:  # pragma: no cover
    OpenLane2Config = None  # type: ignore[assignment]
    OpenLane2Runner = None  # type: ignore[assignment]
    OpenLane2Stage = None  # type: ignore[assignment]

try:
    from openforge.templates.caravel import CaravelConfig, create_caravel_project
except Exception:  # pragma: no cover
    CaravelConfig = None  # type: ignore[assignment]
    create_caravel_project = None  # type: ignore[assignment]


# design_system dark palette
_BG = "#11131a"
_SURFACE = "#1b1e27"
_PANEL = "#232734"
_TEXT = "#e5e9f0"
_MUTED = "#8a93a6"
_ACCENT = "#7aa2f7"
_GREEN = "#9ece6a"
_RED = "#f7768e"
_YELLOW = "#e0af68"


_STATUS_COLORS = {
    "pending": _MUTED,
    "running": _YELLOW,
    "success": _GREEN,
    "fail": _RED,
    "skipped": _MUTED,
}


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class _RunWorker(QObject):
    line = Signal(str)
    finished = Signal(dict)

    def __init__(
        self,
        runner: OpenLane2Runner,
        steps: list | None = None,
        single_step: object | None = None,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._runner = runner
        self._steps = steps
        self._single = single_step
        self._run_dir = run_dir

    def run(self) -> None:
        try:
            if self._single is not None and self._run_dir is not None:
                result = self._runner.run_step(
                    self._single, self._run_dir, log_callback=self.line.emit
                )
            else:
                result = self._runner.run_flow(steps=self._steps, log_callback=self.line.emit)
        except Exception as exc:  # pragma: no cover
            result = {"ok": False, "error": str(exc)}
        self.finished.emit(result)


class OpenLanePanel(QWidget):
    """Dockable OpenLane2 orchestration panel."""

    run_finished = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._runner: OpenLane2Runner | None = None
        self._design_dir: Path | None = None
        self._worker_thread: QThread | None = None
        self._worker: _RunWorker | None = None
        self._step_rows: dict[str, int] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # -- Detection group ----------------------------------------
        det_group = QGroupBox("OpenLane2 Installation")
        det_layout = QFormLayout(det_group)
        self._lbl_path = QLabel("(not detected)")
        self._lbl_version = QLabel("-")
        self._lbl_pdk = QLabel("-")
        det_btn = QPushButton("Detect")
        det_btn.clicked.connect(self._detect)
        det_layout.addRow("Path:", self._lbl_path)
        det_layout.addRow("Version:", self._lbl_version)
        det_layout.addRow("PDK:", self._lbl_pdk)
        det_layout.addRow("", det_btn)
        root.addWidget(det_group)

        # -- Config form --------------------------------------------
        cfg_group = QGroupBox("Design Configuration")
        cfg_form = QFormLayout(cfg_group)
        self._ed_design_name = QLineEdit("user_proj_example")
        self._ed_verilog = QLineEdit("")
        self._ed_clock_port = QLineEdit("wb_clk_i")
        self._ed_period = QDoubleSpinBox()
        self._ed_period.setRange(0.1, 10000.0)
        self._ed_period.setValue(40.0)
        self._ed_period.setSuffix(" ns")
        self._ed_util = QDoubleSpinBox()
        self._ed_util.setRange(1.0, 99.0)
        self._ed_util.setValue(50.0)
        self._ed_util.setSuffix(" %")
        self._ed_density = QDoubleSpinBox()
        self._ed_density.setRange(0.05, 0.99)
        self._ed_density.setSingleStep(0.05)
        self._ed_density.setValue(0.55)
        self._ed_strategy = QComboBox()
        self._ed_strategy.addItems(["AREA 0", "AREA 1", "AREA 2", "DELAY 0", "DELAY 1", "DELAY 2"])
        self._ed_pdk = QComboBox()
        self._ed_pdk.addItems(["sky130A", "sky130B", "gf180mcuC"])
        self._ed_stdcell = QLineEdit("sky130_fd_sc_hd")

        cfg_form.addRow("DESIGN_NAME:", self._ed_design_name)
        cfg_form.addRow("VERILOG_FILES (csv):", self._ed_verilog)
        cfg_form.addRow("CLOCK_PORT:", self._ed_clock_port)
        cfg_form.addRow("CLOCK_PERIOD:", self._ed_period)
        cfg_form.addRow("FP_CORE_UTIL:", self._ed_util)
        cfg_form.addRow("PL_TARGET_DENSITY:", self._ed_density)
        cfg_form.addRow("SYNTH_STRATEGY:", self._ed_strategy)
        cfg_form.addRow("PDK:", self._ed_pdk)
        cfg_form.addRow("STD_CELL_LIBRARY:", self._ed_stdcell)

        design_row = QHBoxLayout()
        self._ed_design_dir = QLineEdit("")
        self._ed_design_dir.setPlaceholderText("Design directory...")
        pick_btn = QPushButton("Browse...")
        pick_btn.clicked.connect(self._pick_design_dir)
        design_row.addWidget(self._ed_design_dir, 1)
        design_row.addWidget(pick_btn)
        cfg_form.addRow("Design dir:", design_row)
        root.addWidget(cfg_group)

        # -- Split: steps + log -------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Steps table
        steps_wrap = QWidget()
        steps_layout = QVBoxLayout(steps_wrap)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        self._tbl_steps = QTableWidget(0, 3)
        self._tbl_steps.setHorizontalHeaderLabels(["#", "Step", "Status"])
        self._tbl_steps.verticalHeader().setVisible(False)
        self._tbl_steps.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tbl_steps.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tbl_steps.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        steps_layout.addWidget(self._tbl_steps)

        run_row = QHBoxLayout()
        self._btn_run_all = QPushButton("Run All")
        self._btn_run_from = QPushButton("Run From")
        self._btn_run_one = QPushButton("Run Single")
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setEnabled(False)
        self._btn_run_all.clicked.connect(self._on_run_all)
        self._btn_run_from.clicked.connect(self._on_run_from)
        self._btn_run_one.clicked.connect(self._on_run_single)
        self._btn_stop.clicked.connect(self._on_stop)
        for b in (
            self._btn_run_all,
            self._btn_run_from,
            self._btn_run_one,
            self._btn_stop,
        ):
            run_row.addWidget(b)
        steps_layout.addLayout(run_row)

        cara_row = QHBoxLayout()
        self._btn_new_caravel = QPushButton("New Caravel Project")
        self._btn_new_caravel.clicked.connect(self._on_new_caravel)
        cara_row.addWidget(self._btn_new_caravel)
        cara_row.addStretch(1)
        steps_layout.addLayout(cara_row)

        splitter.addWidget(steps_wrap)

        # Log + metrics tab-ish region
        right = QSplitter(Qt.Orientation.Vertical)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(10_000)
        self._log.setStyleSheet(
            f"QPlainTextEdit {{ background: {_BG}; color: {_TEXT}; "
            f"font-family: Consolas, Menlo, monospace; }}"
        )
        log_layout.addWidget(self._log)
        right.addWidget(log_group)

        metrics_group = QGroupBox("Metrics / Artifacts")
        metrics_layout = QVBoxLayout(metrics_group)
        self._tree_metrics = QTreeWidget()
        self._tree_metrics.setHeaderLabels(["Metric / Artifact", "Value"])
        self._tree_metrics.setAlternatingRowColors(True)
        metrics_layout.addWidget(self._tree_metrics)
        refresh_metrics = QPushButton("Refresh Metrics")
        refresh_metrics.clicked.connect(self._refresh_metrics)
        metrics_layout.addWidget(refresh_metrics)
        right.addWidget(metrics_group)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self._populate_steps()
        self._apply_theme()
        self._detect()

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{ background: {_BG}; color: {_TEXT}; }}
            QGroupBox {{
                border: 1px solid {_PANEL};
                border-radius: 6px;
                margin-top: 10px;
                padding: 6px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: {_ACCENT};
                font-weight: 600;
            }}
            QLineEdit, QComboBox, QDoubleSpinBox {{
                background: {_SURFACE};
                color: {_TEXT};
                border: 1px solid {_PANEL};
                border-radius: 3px;
                padding: 3px 6px;
            }}
            QPushButton {{
                background: {_PANEL};
                color: {_TEXT};
                border: 1px solid {_PANEL};
                border-radius: 4px;
                padding: 5px 12px;
            }}
            QPushButton:hover {{ background: {_ACCENT}; color: {_BG}; }}
            QPushButton:disabled {{ color: {_MUTED}; }}
            QTableWidget, QTreeWidget, QPlainTextEdit {{
                background: {_SURFACE};
                color: {_TEXT};
                border: 1px solid {_PANEL};
                gridline-color: {_PANEL};
            }}
            QHeaderView::section {{
                background: {_PANEL};
                color: {_TEXT};
                border: none;
                padding: 4px;
            }}
            """
        )

    # ------------------------------------------------------------------
    def _populate_steps(self) -> None:
        if OpenLane2Stage is None:
            return
        stages = list(OpenLane2Stage)
        # De-dupe step ids (MAGIC_DRC == DRC)
        seen: set[str] = set()
        self._tbl_steps.setRowCount(0)
        self._step_rows.clear()
        for idx, stage in enumerate(stages):
            key = stage.value
            if key in seen:
                continue
            seen.add(key)
            row = self._tbl_steps.rowCount()
            self._tbl_steps.insertRow(row)
            self._tbl_steps.setItem(row, 0, QTableWidgetItem(str(idx + 1)))
            self._tbl_steps.setItem(row, 1, QTableWidgetItem(stage.name))
            badge = QTableWidgetItem("pending")
            badge.setForeground(QColor(_STATUS_COLORS["pending"]))
            self._tbl_steps.setItem(row, 2, badge)
            self._step_rows[stage.name] = row

    def _set_step_status(self, step_name: str, status: str) -> None:
        row = self._step_rows.get(step_name)
        if row is None:
            return
        item = self._tbl_steps.item(row, 2)
        if item is None:
            return
        item.setText(status)
        item.setForeground(QColor(_STATUS_COLORS.get(status, _TEXT)))

    # ------------------------------------------------------------------
    def _detect(self) -> None:
        if OpenLane2Runner is None:
            self._lbl_path.setText("core library unavailable")
            return
        runner = self._make_runner(ensure=False)
        if runner is None:
            self._lbl_path.setText("(set design dir first)")
            return
        cli = runner.detect_openlane()
        if cli is None:
            self._lbl_path.setText("(not found)")
            self._lbl_version.setText("-")
        else:
            self._lbl_path.setText(str(cli))
            self._lbl_version.setText(runner.version() or "unknown")
        self._lbl_pdk.setText(self._ed_pdk.currentText())

    def _pick_design_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select design directory")
        if path:
            self._ed_design_dir.setText(path)
            self._design_dir = Path(path)

    # ------------------------------------------------------------------
    def _build_config(self) -> OpenLane2Config | None:
        if OpenLane2Config is None:
            QMessageBox.warning(self, "OpenLane", "OpenLane2 core module not available")
            return None
        files = [f.strip() for f in self._ed_verilog.text().split(",") if f.strip()]
        if not files:
            QMessageBox.warning(self, "OpenLane", "At least one Verilog file is required")
            return None
        try:
            return OpenLane2Config(
                DESIGN_NAME=self._ed_design_name.text().strip() or "top",
                VERILOG_FILES=files,
                CLOCK_PORT=self._ed_clock_port.text().strip() or "clk",
                CLOCK_PERIOD=float(self._ed_period.value()),
                FP_CORE_UTIL=float(self._ed_util.value()),
                PL_TARGET_DENSITY=float(self._ed_density.value()),
                SYNTH_STRATEGY=self._ed_strategy.currentText(),
                PDK=self._ed_pdk.currentText(),
                STD_CELL_LIBRARY=self._ed_stdcell.text().strip() or "sky130_fd_sc_hd",
            )
        except Exception as exc:
            QMessageBox.warning(self, "OpenLane", f"Invalid config: {exc}")
            return None

    def _make_runner(self, ensure: bool = True) -> OpenLane2Runner | None:
        if OpenLane2Runner is None:
            return None
        design_dir_text = self._ed_design_dir.text().strip()
        if not design_dir_text:
            if ensure:
                QMessageBox.warning(self, "OpenLane", "Pick a design directory first")
            return None
        design_dir = Path(design_dir_text)
        cfg = self._build_config()
        if cfg is None:
            return None
        return OpenLane2Runner(cfg, design_dir)

    # ------------------------------------------------------------------
    def _on_run_all(self) -> None:
        runner = self._make_runner()
        if runner is None:
            return
        self._start_worker(runner, steps=None)

    def _on_run_from(self) -> None:
        if OpenLane2Stage is None:
            return
        items = [s.name for s in OpenLane2Stage]
        name, ok = QInputDialog.getItem(self, "Run From", "Start at step:", items, 0, False)
        if not ok:
            return
        runner = self._make_runner()
        if runner is None:
            return
        stages = list(OpenLane2Stage)
        idx = next((i for i, s in enumerate(stages) if s.name == name), 0)
        self._start_worker(runner, steps=stages[idx:])

    def _on_run_single(self) -> None:
        if OpenLane2Stage is None:
            return
        items = [s.name for s in OpenLane2Stage]
        name, ok = QInputDialog.getItem(self, "Run Single", "Step:", items, 0, False)
        if not ok:
            return
        runner = self._make_runner()
        if runner is None:
            return
        stage = next((s for s in OpenLane2Stage if s.name == name), None)
        if stage is None:
            return
        run_dir = runner.design_dir / "runs" / f"single_{stage.name.lower()}"
        self._start_worker(runner, steps=None, single_step=stage, run_dir=run_dir)

    def _on_stop(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.requestInterruption()
            self._append_log("[stop requested]")

    # ------------------------------------------------------------------
    def _start_worker(
        self,
        runner: OpenLane2Runner,
        steps: list | None,
        single_step: object | None = None,
        run_dir: Path | None = None,
    ) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            QMessageBox.information(self, "OpenLane", "A run is already in progress")
            return

        # Reset statuses
        if steps is None and single_step is None:
            target_names = list(self._step_rows.keys())
        elif single_step is not None:
            target_names = [single_step.name]  # type: ignore[attr-defined]
        else:
            target_names = [s.name for s in steps]  # type: ignore[union-attr]
        for name in target_names:
            self._set_step_status(name, "pending")

        thread = QThread(self)
        worker = _RunWorker(runner, steps=steps, single_step=single_step, run_dir=run_dir)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.line.connect(self._append_log)
        worker.finished.connect(self._on_run_finished)
        worker.finished.connect(thread.quit)
        self._worker_thread = thread
        self._worker = worker
        self._btn_stop.setEnabled(True)
        for b in (self._btn_run_all, self._btn_run_from, self._btn_run_one):
            b.setEnabled(False)
        self._append_log(f"[start] {runner.config.DESIGN_NAME}")
        thread.start()

    def _on_run_finished(self, result: dict) -> None:
        ok = bool(result.get("ok"))
        if ok:
            self._append_log("[run complete - success]")
        else:
            err = result.get("error") or f"rc={result.get('returncode')}"
            self._append_log(f"[run failed] {err}")
        for b in (self._btn_run_all, self._btn_run_from, self._btn_run_one):
            b.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self.run_finished.emit(ok)
        self._refresh_metrics()

    # ------------------------------------------------------------------
    def _append_log(self, line: str) -> None:
        clean = _ANSI_RE.sub("", line)
        color = _TEXT
        lower = clean.lower()
        if "error" in lower or "fatal" in lower:
            color = _RED
        elif "warning" in lower:
            color = _YELLOW
        elif "success" in lower or "done" in lower:
            color = _GREEN

        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(clean + "\n", fmt)
        self._log.setTextCursor(cursor)

        # Try to map log lines to step status
        for name in self._step_rows:
            if name.lower() in lower:
                if "start" in lower:
                    self._set_step_status(name, "running")
                elif "fail" in lower or "error" in lower:
                    self._set_step_status(name, "fail")
                elif "done" in lower or "success" in lower:
                    self._set_step_status(name, "success")

    # ------------------------------------------------------------------
    def _refresh_metrics(self) -> None:
        self._tree_metrics.clear()
        runner = self._make_runner(ensure=False)
        if runner is None:
            return
        latest = runner.latest_run_dir()
        if latest is None:
            root = QTreeWidgetItem(["(no runs)", ""])
            self._tree_metrics.addTopLevelItem(root)
            return

        metrics = runner.parse_metrics(latest)
        metrics_root = QTreeWidgetItem([f"metrics ({latest.name})", ""])
        self._tree_metrics.addTopLevelItem(metrics_root)
        for step_name, data in metrics.items():
            step_item = QTreeWidgetItem([step_name, ""])
            metrics_root.addChild(step_item)
            if isinstance(data, dict):
                for k, v in sorted(data.items()):
                    step_item.addChild(QTreeWidgetItem([str(k), str(v)]))

        artifacts = runner.collect_artifacts(latest)
        art_root = QTreeWidgetItem(["artifacts", ""])
        self._tree_metrics.addTopLevelItem(art_root)
        for kind, path in artifacts.items():
            art_root.addChild(QTreeWidgetItem([kind.value, str(path)]))
        self._tree_metrics.expandAll()

    # ------------------------------------------------------------------
    def _on_new_caravel(self) -> None:
        if create_caravel_project is None or CaravelConfig is None:
            QMessageBox.warning(self, "Caravel", "Caravel template module not available")
            return
        name, ok = QInputDialog.getText(self, "New Caravel Project", "Project name:")
        if not ok or not name.strip():
            return
        parent = QFileDialog.getExistingDirectory(self, "Parent directory")
        if not parent:
            return
        try:
            cfg = CaravelConfig(project_name=name.strip())
            root = create_caravel_project(name.strip(), Path(parent), cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Caravel", f"Failed to create project: {exc}")
            return
        self._ed_design_dir.setText(str(root))
        self._ed_design_name.setText(cfg.user_module_name)
        self._ed_verilog.setText(
            str((root / "verilog" / "rtl" / f"{cfg.user_module_name}.v").as_posix())
        )
        QMessageBox.information(self, "Caravel", f"Created Caravel project at:\n{root}")
