"""Qt dock panel for analog / mixed-signal SPICE simulation.

The :class:`SpicePanel` lets the user pick a SPICE netlist, configure a
simulation (DC / AC / TRAN / OP / NOISE), inspect the parsed components
and models, run ngspice, and plot the resulting waveforms with a custom
QPainter chart widget.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# We import lazily inside methods that touch them so the panel can be loaded
# even when the core package is not installed (e.g. unit tests of the UI).


# ---------------------------------------------------------------------------
# Theme palette
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Palette:
    bg: str
    panel: str
    text: str
    subtle: str
    accent: str
    accent2: str
    grid: str
    series: tuple[str, ...]


_DARK = _Palette(
    bg="#1e1e2e",
    panel="#181825",
    text="#cdd6f4",
    subtle="#9399b2",
    accent="#89b4fa",
    accent2="#f5c2e7",
    grid="#313244",
    series=("#89b4fa", "#f5c2e7", "#a6e3a1", "#fab387", "#f9e2af", "#94e2d5"),
)
_LIGHT = _Palette(
    bg="#eff1f5",
    panel="#e6e9ef",
    text="#4c4f69",
    subtle="#6c6f85",
    accent="#1e66f5",
    accent2="#ea76cb",
    grid="#bcc0cc",
    series=("#1e66f5", "#ea76cb", "#40a02b", "#fe640b", "#df8e1d", "#179299"),
)


# ---------------------------------------------------------------------------
# Custom plot widget
# ---------------------------------------------------------------------------


class _SpicePlot(QWidget):
    """Pure-QPainter line plot for SPICE waveforms."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._x_label = "time (s)"
        self._y_label = "V"
        self._series: list[tuple[str, list[float], list[float]]] = []
        self._palette: _Palette = _DARK

    def set_palette(self, palette: _Palette) -> None:
        self._palette = palette
        self.update()

    def clear(self) -> None:
        self._series.clear()
        self.update()

    def set_axes(self, x_label: str, y_label: str) -> None:
        self._x_label = x_label
        self._y_label = y_label
        self.update()

    def add_series(self, name: str, xs: list[float], ys: list[float]) -> None:
        if not xs or not ys:
            return
        self._series.append((name, list(xs), list(ys)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        p.fillRect(rect, QColor(self._palette.panel))

        margin_l = 60
        margin_b = 36
        margin_t = 20
        margin_r = 16
        plot_rect = QRectF(
            margin_l,
            margin_t,
            max(rect.width() - margin_l - margin_r, 10),
            max(rect.height() - margin_t - margin_b, 10),
        )

        if not self._series:
            p.setPen(QColor(self._palette.subtle))
            p.drawText(plot_rect, Qt.AlignmentFlag.AlignCenter, "No data - run a simulation")
            p.end()
            return

        # Compute bounds across all series.
        x_min = min(min(s[1]) for s in self._series)
        x_max = max(max(s[1]) for s in self._series)
        y_min = min(min(s[2]) for s in self._series)
        y_max = max(max(s[2]) for s in self._series)
        if x_max == x_min:
            x_max = x_min + 1.0
        if y_max == y_min:
            y_max = y_min + 1.0
        y_range = y_max - y_min
        y_min -= y_range * 0.05
        y_max += y_range * 0.05

        # Grid
        grid_pen = QPen(QColor(self._palette.grid))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        steps = 5
        for i in range(steps + 1):
            x = plot_rect.left() + plot_rect.width() * i / steps
            p.drawLine(QPointF(x, plot_rect.top()), QPointF(x, plot_rect.bottom()))
            y = plot_rect.top() + plot_rect.height() * i / steps
            p.drawLine(QPointF(plot_rect.left(), y), QPointF(plot_rect.right(), y))

        # Axes labels and tick values.
        p.setPen(QColor(self._palette.text))
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        for i in range(steps + 1):
            xv = x_min + (x_max - x_min) * i / steps
            xpx = plot_rect.left() + plot_rect.width() * i / steps
            p.drawText(
                QRectF(xpx - 30, plot_rect.bottom() + 2, 60, 14),
                Qt.AlignmentFlag.AlignCenter,
                _fmt_eng(xv),
            )
            yv = y_max - (y_max - y_min) * i / steps
            ypx = plot_rect.top() + plot_rect.height() * i / steps
            p.drawText(
                QRectF(2, ypx - 7, margin_l - 6, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _fmt_eng(yv),
            )
        p.drawText(
            QRectF(plot_rect.left(), plot_rect.bottom() + 18, plot_rect.width(), 14),
            Qt.AlignmentFlag.AlignCenter,
            self._x_label,
        )
        p.save()
        p.translate(12, plot_rect.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-60, -8, 120, 14), Qt.AlignmentFlag.AlignCenter, self._y_label)
        p.restore()

        # Series
        def to_px(x: float, y: float) -> QPointF:
            px = plot_rect.left() + (x - x_min) / (x_max - x_min) * plot_rect.width()
            py = plot_rect.bottom() - (y - y_min) / (y_max - y_min) * plot_rect.height()
            return QPointF(px, py)

        for idx, (name, xs, ys) in enumerate(self._series):
            color = QColor(self._palette.series[idx % len(self._palette.series)])
            pen = QPen(color)
            pen.setWidthF(1.6)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(to_px(xs[0], ys[0]))
            for j in range(1, len(xs)):
                path.lineTo(to_px(xs[j], ys[j]))
            p.drawPath(path)
            # Legend swatch
            ly = plot_rect.top() + 4 + idx * 14
            p.fillRect(QRectF(plot_rect.right() - 110, ly, 12, 10), color)
            p.setPen(QColor(self._palette.text))
            p.drawText(
                QRectF(plot_rect.right() - 92, ly - 2, 90, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

        p.end()


def _fmt_eng(v: float) -> str:
    if v == 0:
        return "0"
    av = abs(v)
    if av >= 1e9:
        return f"{v / 1e9:.2g}G"
    if av >= 1e6:
        return f"{v / 1e6:.2g}M"
    if av >= 1e3:
        return f"{v / 1e3:.2g}k"
    if av >= 1:
        return f"{v:.3g}"
    if av >= 1e-3:
        return f"{v * 1e3:.2g}m"
    if av >= 1e-6:
        return f"{v * 1e6:.2g}u"
    if av >= 1e-9:
        return f"{v * 1e9:.2g}n"
    return f"{v:.2e}"


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class SpicePanel(QDockWidget):
    """Dock widget for SPICE simulation."""

    simulation_complete = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SPICE Simulator")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._netlist_path: Path | None = None
        self._netlist_obj: Any = None
        self._palette: _Palette = _DARK

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ---- File picker row -----------------------------------------------
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Netlist:"))
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Pick a .cir / .sp netlist...")
        picker_row.addWidget(self._path_edit, 1)
        self._browse_btn = QPushButton("Browse")
        self._browse_btn.clicked.connect(self._on_browse)
        picker_row.addWidget(self._browse_btn)
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._reload_netlist)
        picker_row.addWidget(self._reload_btn)
        try:
            self._sch2net_btn = QPushButton("Schematic \u2192 Netlist")
            self._sch2net_btn.clicked.connect(self._on_schematic_to_netlist)
            picker_row.addWidget(self._sch2net_btn)
        except Exception:
            pass
        layout.addLayout(picker_row)

        # ---- Tabs -----------------------------------------------------------
        self._tabs = QTabWidget(root)
        layout.addWidget(self._tabs, 1)

        self._tabs.addTab(self._build_setup_tab(), "Setup")
        self._tabs.addTab(self._build_components_tab(), "Components")
        self._tabs.addTab(self._build_models_tab(), "Models")
        self._tabs.addTab(self._build_run_tab(), "Run")
        self._tabs.addTab(self._build_plot_tab(), "Plot")
        with contextlib.suppress(Exception):
            self._tabs.addTab(self._build_ip_library_tab(), "IP Library")
        with contextlib.suppress(Exception):
            self._tabs.addTab(self._build_monte_carlo_tab(), "Monte Carlo")

        # ---- Status bar -----------------------------------------------------
        self._status = QStatusBar(root)
        self._status.showMessage("Idle")
        layout.addWidget(self._status)

        self.setWidget(root)
        self.set_theme(True)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------
    def _build_setup_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._sim_type = QComboBox()
        self._sim_type.addItems(["DC", "AC", "TRAN", "OP", "NOISE"])
        self._sim_type.currentIndexChanged.connect(self._on_sim_type_changed)
        form.addRow("Analysis", self._sim_type)

        self._param_a = QDoubleSpinBox()
        self._param_a.setRange(-1e12, 1e12)
        self._param_a.setDecimals(6)
        self._param_a.setValue(0.0)
        self._param_a_label = QLabel("Start")
        form.addRow(self._param_a_label, self._param_a)

        self._param_b = QDoubleSpinBox()
        self._param_b.setRange(-1e12, 1e12)
        self._param_b.setDecimals(6)
        self._param_b.setValue(1e-6)
        self._param_b_label = QLabel("Stop")
        form.addRow(self._param_b_label, self._param_b)

        self._param_c = QDoubleSpinBox()
        self._param_c.setRange(0.0, 1e12)
        self._param_c.setDecimals(6)
        self._param_c.setValue(1e-9)
        self._param_c_label = QLabel("Step")
        form.addRow(self._param_c_label, self._param_c)

        self._sweep_source = QLineEdit()
        self._sweep_source.setPlaceholderText("e.g. Vin (DC) / vin (NOISE)")
        form.addRow("Source", self._sweep_source)

        self._noise_output = QLineEdit()
        self._noise_output.setPlaceholderText("output node (NOISE only)")
        form.addRow("Noise output", self._noise_output)

        form.addRow(QLabel("Output signals:"))
        self._signals_list = QListWidget()
        self._signals_list.setSelectionMode(self._signals_list.SelectionMode.MultiSelection)
        form.addRow(self._signals_list)

        return w

    def _build_components_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self._components_tree = QTreeWidget()
        self._components_tree.setHeaderLabels(["Name", "Type", "Nodes", "Value", "Params"])
        self._components_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._components_tree)
        return w

    def _build_models_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self._models_tree = QTreeWidget()
        self._models_tree.setHeaderLabels(["Name", "Type", "Parameters"])
        self._models_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._models_tree)
        return w

    def _build_run_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        row = QHBoxLayout()
        self._run_btn = QPushButton("Run Simulation")
        self._run_btn.clicked.connect(self._on_run)
        row.addWidget(self._run_btn)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        row.addWidget(self._stop_btn)
        self._docker_check = QCheckBox("Use Docker")
        row.addWidget(self._docker_check)
        row.addStretch(1)
        layout.addLayout(row)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Simulation output appears here")
        layout.addWidget(self._log, 1)
        return w

    def _build_plot_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._plot_signals = QListWidget()
        self._plot_signals.setSelectionMode(self._plot_signals.SelectionMode.MultiSelection)
        self._plot_signals.itemSelectionChanged.connect(self._refresh_plot)
        splitter.addWidget(self._plot_signals)
        self._plot = _SpicePlot()
        splitter.addWidget(self._plot)
        splitter.setStretchFactor(1, 4)
        layout.addWidget(splitter)
        return w

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_browse(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open SPICE netlist",
            "",
            "SPICE files (*.cir *.sp *.spice *.net);;All files (*)",
        )
        if path_str:
            self.load_netlist(Path(path_str))

    def _reload_netlist(self) -> None:
        if self._netlist_path is not None:
            self.load_netlist(self._netlist_path)

    def load_netlist(self, path: Path) -> None:
        self._netlist_path = Path(path)
        self._path_edit.setText(str(self._netlist_path))
        try:
            from openforge.spice.parser import parse_spice

            self._netlist_obj = parse_spice(self._netlist_path)
        except Exception as exc:  # pragma: no cover - defensive
            self._status.showMessage(f"Parse error: {exc}")
            self._netlist_obj = None
            return
        self._populate_components()
        self._populate_models()
        self._populate_signals()
        stats = self._netlist_obj.stats() if self._netlist_obj else {}
        self._status.showMessage(
            f"Loaded {self._netlist_path.name}: "
            f"{stats.get('components', 0)} components, "
            f"{stats.get('models', 0)} models, "
            f"{stats.get('subcircuits', 0)} subckts, "
            f"{stats.get('nets', 0)} nets"
        )

    def _populate_components(self) -> None:
        self._components_tree.clear()
        if not self._netlist_obj:
            return
        for comp in self._netlist_obj.components:
            item = QTreeWidgetItem(
                [
                    comp.name,
                    comp.type,
                    " ".join(comp.nodes),
                    comp.value,
                    " ".join(f"{k}={v}" for k, v in comp.parameters.items()),
                ]
            )
            self._components_tree.addTopLevelItem(item)
        for sub in self._netlist_obj.subckts.values():
            sub_item = QTreeWidgetItem([f".subckt {sub.name}", "X", " ".join(sub.ports), "", ""])
            for c in sub.components:
                sub_item.addChild(
                    QTreeWidgetItem(
                        [
                            c.name,
                            c.type,
                            " ".join(c.nodes),
                            c.value,
                            " ".join(f"{k}={v}" for k, v in c.parameters.items()),
                        ]
                    )
                )
            self._components_tree.addTopLevelItem(sub_item)

    def _populate_models(self) -> None:
        self._models_tree.clear()
        if not self._netlist_obj:
            return
        for m in self._netlist_obj.models.values():
            self._models_tree.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        m.name,
                        m.type,
                        " ".join(f"{k}={v}" for k, v in m.parameters.items()),
                    ]
                )
            )

    def _populate_signals(self) -> None:
        self._signals_list.clear()
        self._plot_signals.clear()
        if not self._netlist_obj:
            return
        for net in sorted(self._netlist_obj.nets):
            label = f"v({net})"
            self._signals_list.addItem(QListWidgetItem(label))
            self._plot_signals.addItem(QListWidgetItem(label))

    def _on_sim_type_changed(self, _idx: int) -> None:
        kind = self._sim_type.currentText()
        labels = {
            "DC": ("Start", "Stop", "Step"),
            "AC": ("Fstart", "Fstop", "Pts/dec"),
            "TRAN": ("Tstart", "Tstop", "Tstep"),
            "OP": ("(unused)", "(unused)", "(unused)"),
            "NOISE": ("Fstart", "Fstop", "Pts/dec"),
        }[kind]
        self._param_a_label.setText(labels[0])
        self._param_b_label.setText(labels[1])
        self._param_c_label.setText(labels[2])

    def _on_run(self) -> None:
        if self._netlist_path is None:
            self._status.showMessage("Pick a netlist first")
            return
        kind = self._sim_type.currentText()
        self._log.clear()
        self._log.appendPlainText(f"Running {kind} simulation on {self._netlist_path.name}")
        try:
            from openforge.engine.base import ExecutionBackend
            from openforge.engine.ngspice import NgspiceEngine

            backend = (
                ExecutionBackend.DOCKER
                if self._docker_check.isChecked()
                else ExecutionBackend.NATIVE
            )
            engine = NgspiceEngine(backend=backend)
        except Exception as exc:  # pragma: no cover - import-time guard
            self._log.appendPlainText(f"Failed to initialise ngspice engine: {exc}")
            return

        if not engine.check_installed():
            self._log.appendPlainText("ngspice is not installed on this system.")
            self._status.showMessage("ngspice not installed")
            return

        a = self._param_a.value()
        b = self._param_b.value()
        c = self._param_c.value()
        try:
            if kind == "DC":
                src = self._sweep_source.text() or "Vin"
                result = engine.run_dc(self._netlist_path, src, a, b, c)
            elif kind == "AC":
                result = engine.run_ac(self._netlist_path, a, b, int(c) or 10)
            elif kind == "TRAN":
                result = engine.run_tran(self._netlist_path, c, b, a)
            elif kind == "OP":
                result = engine.run_op(self._netlist_path)
            elif kind == "NOISE":
                src = self._sweep_source.text() or "Vin"
                out = self._noise_output.text() or "out"
                result = engine.run_noise(self._netlist_path, out, src, a, b)
            else:
                self._log.appendPlainText(f"Unknown analysis: {kind}")
                return
        except Exception as exc:  # pragma: no cover - defensive
            self._log.appendPlainText(f"Engine raised: {exc}")
            return

        self._log.appendPlainText(result.stdout or "")
        if result.stderr:
            self._log.appendPlainText(result.stderr)
        self._log.appendPlainText(f"Done (rc={result.returncode}, dur={result.duration:.2f}s)")
        raw_path: Path | None = None
        for tok in result.command:
            if tok.startswith("#raw="):
                raw_path = Path(tok.split("=", 1)[1])
                break
        if raw_path and raw_path.exists():
            self._load_raw(raw_path, kind)
        self._status.showMessage(
            "Simulation OK" if result.ok else f"Simulation failed (rc={result.returncode})"
        )
        self.simulation_complete.emit(
            {
                "kind": kind,
                "returncode": result.returncode,
                "duration": result.duration,
                "raw": str(raw_path) if raw_path else "",
            }
        )

    def _load_raw(self, raw_path: Path, kind: str) -> None:
        try:
            from openforge.engine.ngspice import NgspiceEngine

            data = NgspiceEngine.parse_raw_ascii(raw_path)
        except Exception as exc:  # pragma: no cover - defensive
            self._log.appendPlainText(f"Failed to parse raw: {exc}")
            return
        variables = data.get("variables", [])
        values = data.get("values", [])
        if not variables or not values:
            self._log.appendPlainText("(no data points in raw file)")
            return
        self._raw_variables = variables
        self._raw_values = values
        self._raw_kind = kind
        self._plot_signals.clear()
        for var in variables:
            self._plot_signals.addItem(QListWidgetItem(var["name"]))
        # Auto-select all V() signals.
        for i in range(self._plot_signals.count()):
            item = self._plot_signals.item(i)
            if item.text().lower().startswith("v("):
                item.setSelected(True)
        self._refresh_plot()

    def _refresh_plot(self) -> None:
        self._plot.clear()
        variables = getattr(self, "_raw_variables", None)
        values = getattr(self, "_raw_values", None)
        if not variables or not values:
            return
        kind = getattr(self, "_raw_kind", "TRAN")
        if kind == "AC":
            self._plot.set_axes("frequency (Hz)", "magnitude")
        elif kind == "DC":
            self._plot.set_axes("sweep (V)", "V")
        else:
            self._plot.set_axes("time (s)", "V")
        # First column is the X axis (time / freq / sweep).
        x_idx = 0
        for i, var in enumerate(variables):
            if var.get("type", "").lower() in ("time", "frequency", "voltage"):
                if var.get("type", "").lower() in ("time", "frequency"):
                    x_idx = i
                    break
        xs = [row[x_idx] for row in values if x_idx < len(row)]
        selected = {item.text() for item in self._plot_signals.selectedItems()}
        for i, var in enumerate(variables):
            if i == x_idx:
                continue
            if selected and var["name"] not in selected:
                continue
            ys = [row[i] for row in values if i < len(row)]
            if len(ys) == len(xs):
                self._plot.add_series(var["name"], xs, ys)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def set_theme(self, dark: bool) -> None:
        self._palette = _DARK if dark else _LIGHT
        self._plot.set_palette(self._palette)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(self._palette.bg))
        pal.setColor(QPalette.ColorRole.Base, QColor(self._palette.panel))
        pal.setColor(QPalette.ColorRole.Text, QColor(self._palette.text))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(self._palette.text))
        self.setPalette(pal)
        self.setStyleSheet(
            f"""
            QDockWidget {{ background: {self._palette.bg}; color: {self._palette.text}; }}
            QWidget {{ background: {self._palette.bg}; color: {self._palette.text}; }}
            QLineEdit, QPlainTextEdit, QTreeWidget, QListWidget, QComboBox, QDoubleSpinBox {{
                background: {self._palette.panel};
                color: {self._palette.text};
                border: 1px solid {self._palette.grid};
                selection-background-color: {self._palette.accent};
            }}
            QPushButton {{
                background: {self._palette.panel};
                color: {self._palette.text};
                border: 1px solid {self._palette.grid};
                padding: 4px 10px;
            }}
            QPushButton:hover {{ background: {self._palette.grid}; }}
            QTabWidget::pane {{ border: 1px solid {self._palette.grid}; }}
            QTabBar::tab {{
                background: {self._palette.panel};
                color: {self._palette.subtle};
                padding: 6px 12px;
            }}
            QTabBar::tab:selected {{
                color: {self._palette.text};
                border-bottom: 2px solid {self._palette.accent};
            }}
            QStatusBar {{ background: {self._palette.panel}; color: {self._palette.subtle}; }}
            """
        )

    # ------------------------------------------------------------------
    # IP Library tab
    # ------------------------------------------------------------------
    def _build_ip_library_tab(self) -> QWidget:
        from openforge.analog.ip_library import ANALOG_IP_LIBRARY

        w = QWidget()
        outer = QVBoxLayout(w)
        self._ip_list = QListWidget()
        for name, ip in ANALOG_IP_LIBRARY.items():
            item = QListWidgetItem(f"{name}  [{ip.category}]  -  {ip.description}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._ip_list.addItem(item)
        outer.addWidget(self._ip_list, 1)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load Testbench")
        load_btn.clicked.connect(self._on_load_ip_testbench)
        btn_row.addWidget(load_btn)
        view_btn = QPushButton("View Subckt")
        view_btn.clicked.connect(self._on_view_ip_subckt)
        btn_row.addWidget(view_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        self._ip_preview = QPlainTextEdit()
        self._ip_preview.setReadOnly(True)
        self._ip_preview.setMaximumHeight(180)
        outer.addWidget(self._ip_preview)
        return w

    def _selected_ip(self):
        from openforge.analog.ip_library import ANALOG_IP_LIBRARY

        item = self._ip_list.currentItem()
        if not item:
            return None
        return ANALOG_IP_LIBRARY.get(item.data(Qt.ItemDataRole.UserRole))

    def _on_view_ip_subckt(self) -> None:
        ip = self._selected_ip()
        if not ip:
            return
        self._ip_preview.setPlainText(ip.spice_subckt + "\n\n* Testbench:\n" + ip.test_bench)

    def _on_load_ip_testbench(self) -> None:
        import tempfile

        ip = self._selected_ip()
        if not ip:
            return
        tmpdir = Path(tempfile.gettempdir()) / "openforge_spice"
        tmpdir.mkdir(parents=True, exist_ok=True)
        sub_path = tmpdir / f"{ip.name}.cir"
        tb_path = tmpdir / f"{ip.name}_tb.cir"
        sub_path.write_text(ip.spice_subckt, encoding="utf-8")
        tb_path.write_text(ip.test_bench, encoding="utf-8")
        try:
            self.load_netlist(tb_path)
            self._status.showMessage(f"Loaded {ip.name} testbench")
        except Exception as e:  # pragma: no cover
            self._status.showMessage(f"Load failed: {e}")

    # ------------------------------------------------------------------
    # Monte Carlo tab
    # ------------------------------------------------------------------
    def _build_monte_carlo_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._mc_var = QLineEdit("R1")
        form.addRow("Variable", self._mc_var)
        self._mc_nominal = QDoubleSpinBox()
        self._mc_nominal.setRange(-1e12, 1e12)
        self._mc_nominal.setDecimals(6)
        self._mc_nominal.setValue(1000.0)
        form.addRow("Nominal", self._mc_nominal)
        self._mc_sigma = QDoubleSpinBox()
        self._mc_sigma.setRange(0.0, 1e12)
        self._mc_sigma.setDecimals(6)
        self._mc_sigma.setValue(50.0)
        form.addRow("Sigma", self._mc_sigma)
        self._mc_n = QDoubleSpinBox()
        self._mc_n.setRange(2, 10000)
        self._mc_n.setDecimals(0)
        self._mc_n.setValue(50)
        form.addRow("N samples", self._mc_n)
        self._mc_run = QPushButton("Run Monte Carlo")
        self._mc_run.clicked.connect(self._on_run_monte_carlo)
        form.addRow(self._mc_run)
        self._mc_results = QPlainTextEdit()
        self._mc_results.setReadOnly(True)
        form.addRow(self._mc_results)
        return w

    def _on_run_monte_carlo(self) -> None:
        import random
        import statistics

        var = self._mc_var.text().strip()
        nom = float(self._mc_nominal.value())
        sigma = float(self._mc_sigma.value())
        n = int(self._mc_n.value())
        samples: list[float] = []
        # Without ngspice we generate the random distribution and report
        # statistics. When a netlist is loaded, the values are substituted
        # in via .alter / .control loops by the runner integration; here
        # we just compute & display the distribution as a smoke test.
        rng = random.Random(0xC0FFEE)
        for _ in range(n):
            samples.append(rng.gauss(nom, sigma))
        mean = statistics.fmean(samples)
        std = statistics.pstdev(samples)
        lo = min(samples)
        hi = max(samples)
        self._mc_results.setPlainText(
            f"Variable: {var}\nN: {n}\nNominal: {nom}\nSigma: {sigma}\n"
            f"Sample mean: {mean:.6g}\nSample stdev: {std:.6g}\n"
            f"Min: {lo:.6g}  Max: {hi:.6g}\n\n"
            f"(Hook this into ngspice .control / alter loops to actually "
            f"sweep simulation results.)"
        )

    # ------------------------------------------------------------------
    # Schematic -> Netlist
    # ------------------------------------------------------------------
    def _on_schematic_to_netlist(self) -> None:
        import tempfile

        try:
            from openforge.spice.schematic_netlister import SpiceSchematic
        except Exception as e:
            self._status.showMessage(f"Netlister not available: {e}")
            return
        # Try to find an open SchematicEditor in the parent window
        sch = None
        try:
            from openforge_desktop.widgets.schematic_editor import (
                SchematicEditor,
            )

            mw = self.window()
            if mw is not None:
                editor = mw.findChild(SchematicEditor)
                if editor is not None and hasattr(editor, "schematic"):
                    sch = editor.schematic
        except Exception:
            sch = None
        if sch is None:
            self._status.showMessage("No schematic editor open.")
            return
        try:
            spice = SpiceSchematic.from_sch_editor(sch)
            spice.add_simulation("op")
            netlist = spice.to_netlist()
            tmp = Path(tempfile.gettempdir()) / "openforge_spice" / f"{spice.name}.cir"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(netlist, encoding="utf-8")
            self.load_netlist(tmp)
            self._status.showMessage(f"Generated netlist: {tmp}")
        except Exception as e:  # pragma: no cover
            self._status.showMessage(f"Netlist generation failed: {e}")


__all__ = ["SpicePanel"]
