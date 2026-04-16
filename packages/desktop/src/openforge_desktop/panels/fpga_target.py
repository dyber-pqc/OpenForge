"""FPGA Target dock widget.

Rewritten for Phase 1 of the FPGA toolchain integration. Provides:

* Board selection (card grid of supported boards)
* Toolchain discovery (nextpnr / yosys / icepack / ecppack / gowin_pack /
  openFPGALoader)
* Build pipeline: Synthesize -> P&R -> Pack -> Program with per-step
  status, runtime and log preview
* Resource utilization gauges + Fmax indicator
* LiteX SoC configuration form

Styled with the OpenForge design system (Catppuccin Mocha, Dyber Blue
highlight) and compatible with the main window dock layout.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# --- Core imports (guarded) ------------------------------------------------

try:
    from openforge.fpga.boards import BOARDS, Board  # type: ignore
except Exception:  # pragma: no cover
    BOARDS = {}
    Board = object  # type: ignore

try:
    from openforge.litex.integration import (
        LiteXBuilder,
        LiteXSocConfig,
        SUPPORTED_BOARDS as LITEX_BOARDS,
    )
except Exception:  # pragma: no cover
    LiteXBuilder = None  # type: ignore
    LiteXSocConfig = None  # type: ignore
    LITEX_BOARDS = {}  # type: ignore

try:
    from openforge_desktop.theme.design_system import get_palette
    from openforge_desktop.theme.components import MetricCard
except Exception:  # pragma: no cover
    get_palette = None  # type: ignore
    MetricCard = None  # type: ignore


# ---------------------------------------------------------------------------
# Catppuccin Mocha palette (fallback if design_system is unavailable)
# ---------------------------------------------------------------------------

_BG = "#1e1e2e"
_MANTLE = "#181825"
_CRUST = "#11111b"
_SURFACE0 = "#313244"
_SURFACE1 = "#45475a"
_SURFACE2 = "#585b70"
_TEXT = "#cdd6f4"
_SUBTEXT = "#a6adc8"
_BLUE = "#89b4fa"
_DYBER_BLUE = "#00d4ff"
_GREEN = "#a6e3a1"
_YELLOW = "#f9e2af"
_PEACH = "#fab387"
_RED = "#f38ba8"
_MAUVE = "#cba6f7"


# ---------------------------------------------------------------------------
# Helpers: board metadata extraction
# ---------------------------------------------------------------------------


def _board_attr(board: Any, *names: str, default: Any = "") -> Any:
    for n in names:
        v = getattr(board, n, None)
        if v not in (None, ""):
            return v
    return default


@dataclass
class _BuildStep:
    name: str
    label: QLabel
    status: QLabel
    runtime: QLabel
    button: QPushButton
    log_preview: QPlainTextEdit
    runner: Optional[Callable[[], dict]] = None
    last_result: Optional[dict] = None


# ---------------------------------------------------------------------------
# Utilization bar widget
# ---------------------------------------------------------------------------


class UtilBar(QFrame):
    """Horizontal utilization bar with label and percentage."""

    def __init__(self, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("util-bar")
        self._name = name
        self._pct = 0.0
        self._used = 0
        self._total = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        self._label = QLabel(name)
        self._label.setStyleSheet(f"color:{_SUBTEXT}; font-size:10px; font-weight:600;")

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(10)
        self._bar.setStyleSheet(
            f"QProgressBar{{background-color:{_SURFACE0};border:1px solid {_SURFACE1};"
            f"border-radius:3px;}}"
            f"QProgressBar::chunk{{background-color:{_DYBER_BLUE};border-radius:3px;}}"
        )

        self._value = QLabel("0 / 0 (0%)")
        self._value.setStyleSheet(f"color:{_TEXT}; font-size:10px;")

        lay.addWidget(self._label)
        lay.addWidget(self._bar)
        lay.addWidget(self._value)

    def set_value(self, used: int, total: int, pct: float) -> None:
        self._used = used
        self._total = total
        self._pct = pct
        self._bar.setValue(int(max(0, min(100, pct))))
        self._value.setText(f"{used} / {total} ({pct:.1f}%)")
        color = _GREEN
        if pct >= 90:
            color = _RED
        elif pct >= 70:
            color = _YELLOW
        self._bar.setStyleSheet(
            f"QProgressBar{{background-color:{_SURFACE0};border:1px solid {_SURFACE1};"
            f"border-radius:3px;}}"
            f"QProgressBar::chunk{{background-color:{color};border-radius:3px;}}"
        )


# ---------------------------------------------------------------------------
# Fmax dial
# ---------------------------------------------------------------------------


class FmaxDial(QFrame):
    """Simple dial-style widget that displays an Fmax in MHz."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 120)
        self._fmax = 0.0
        self._target = 100.0
        self.setStyleSheet(
            f"background-color:{_MANTLE};border:1px solid {_SURFACE1};border-radius:6px;"
        )

    def set_fmax(self, fmax_mhz: float, target_mhz: float = 100.0) -> None:
        self._fmax = fmax_mhz
        self._target = max(target_mhz, 1.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D401, N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)
        # arc background
        pen = QPen(QColor(_SURFACE1))
        pen.setWidth(8)
        p.setPen(pen)
        start = 225 * 16
        span = -270 * 16
        p.drawArc(rect, start, span)
        # value arc
        ratio = max(0.0, min(1.0, self._fmax / self._target))
        color = _GREEN if self._fmax >= self._target else _PEACH if self._fmax >= self._target * 0.7 else _RED
        pen2 = QPen(QColor(color))
        pen2.setWidth(8)
        p.setPen(pen2)
        p.drawArc(rect, start, int(span * ratio))
        # text
        p.setPen(QColor(_TEXT))
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        p.setFont(f)
        p.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            f"{self._fmax:.1f}\nMHz",
        )


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class FpgaTargetPanel(QDockWidget):
    """FPGA target, toolchain, build and LiteX SoC configuration panel."""

    target_changed = Signal(dict)
    build_requested = Signal(str)  # step name
    program_requested = Signal(str)  # bitstream path
    litex_generate_requested = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("FPGA Target", parent)
        self.setObjectName("FpgaTargetPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self._current_board: Any = None
        self._current_bitstream: str = ""
        self._constraint_path: str = ""
        self._build_steps: dict[str, _BuildStep] = {}

        self._build_ui()
        self.set_theme(True)
        self._populate_board_grid()
        self._scan_toolchain()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        container = QWidget(self)
        container.setObjectName("FpgaTargetRoot")
        root = QVBoxLayout(container)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.tabs = QTabWidget(container)
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_board_tab(), "Board")
        self.tabs.addTab(self._build_toolchain_tab(), "Toolchain")
        self.tabs.addTab(self._build_build_tab(), "Build")
        self.tabs.addTab(self._build_resources_tab(), "Resources")
        self.tabs.addTab(self._build_litex_tab(), "LiteX SoC")

        self.setWidget(container)

    # -- Board tab --------------------------------------------------------

    def _build_board_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        # Left: scrollable card grid
        grid_scroll = QScrollArea()
        grid_scroll.setWidgetResizable(True)
        grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._grid_host = QWidget()
        self._grid_layout = QGridLayout(self._grid_host)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setSpacing(8)
        grid_scroll.setWidget(self._grid_host)
        lay.addWidget(grid_scroll, 2)

        # Right: spec table + photo placeholder
        right = QVBoxLayout()
        right.setSpacing(6)

        self._photo = QFrame()
        self._photo.setMinimumHeight(140)
        self._photo.setStyleSheet(
            f"background-color:{_MANTLE};border:1px dashed {_SURFACE2};"
            f"border-radius:6px;"
        )
        photo_lay = QVBoxLayout(self._photo)
        self._photo_label = QLabel("Select a board")
        self._photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo_label.setStyleSheet(f"color:{_SUBTEXT}; font-style:italic;")
        photo_lay.addWidget(self._photo_label)
        right.addWidget(self._photo)

        spec_box = QGroupBox("Specifications")
        spec_lay = QFormLayout(spec_box)
        self._spec_vendor = QLabel("-")
        self._spec_device = QLabel("-")
        self._spec_package = QLabel("-")
        self._spec_clk = QLabel("-")
        self._spec_io = QLabel("-")
        self._spec_bram = QLabel("-")
        self._spec_dsp = QLabel("-")
        self._spec_luts = QLabel("-")
        spec_lay.addRow("Vendor:", self._spec_vendor)
        spec_lay.addRow("Device:", self._spec_device)
        spec_lay.addRow("Package:", self._spec_package)
        spec_lay.addRow("OSC freq:", self._spec_clk)
        spec_lay.addRow("IO count:", self._spec_io)
        spec_lay.addRow("BRAM:", self._spec_bram)
        spec_lay.addRow("DSP:", self._spec_dsp)
        spec_lay.addRow("LUTs:", self._spec_luts)
        right.addWidget(spec_box)
        right.addStretch()

        right_host = QWidget()
        right_host.setLayout(right)
        right_host.setMinimumWidth(260)
        lay.addWidget(right_host, 1)

        return w

    def _populate_board_grid(self) -> None:
        # Clear existing
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        if not BOARDS:
            lbl = QLabel("No boards registered.")
            lbl.setStyleSheet(f"color:{_SUBTEXT};")
            self._grid_layout.addWidget(lbl, 0, 0)
            return

        row = col = 0
        cols = 2
        for name, board in sorted(BOARDS.items()):
            card = self._make_board_card(name, board)
            self._grid_layout.addWidget(card, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1

    def _make_board_card(self, name: str, board: Any) -> QPushButton:
        display = _board_attr(board, "display", "name", default=name)
        vendor = _board_attr(board, "vendor", default="")
        device = _board_attr(board, "device", "part", default="")
        btn = QPushButton()
        btn.setObjectName("board-card")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(72)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setText(f"{display}\n{vendor} -- {device}")
        btn.setStyleSheet(
            f"QPushButton#board-card{{background-color:{_SURFACE0};color:{_TEXT};"
            f"border:1px solid {_SURFACE1};border-radius:6px;padding:8px;"
            f"text-align:left;font-weight:600;}}"
            f"QPushButton#board-card:hover{{border-color:{_DYBER_BLUE};"
            f"background-color:{_SURFACE1};}}"
        )
        btn.clicked.connect(lambda _=False, b=board, n=name: self._on_board_selected(n, b))
        return btn

    def _on_board_selected(self, name: str, board: Any) -> None:
        self._current_board = board
        self._photo_label.setText(_board_attr(board, "display", "name", default=name))
        self._spec_vendor.setText(str(_board_attr(board, "vendor", default="-")))
        self._spec_device.setText(str(_board_attr(board, "device", "part", default="-")))
        self._spec_package.setText(str(_board_attr(board, "package", default="-")))
        freq = _board_attr(board, "default_clk_freq_mhz", "default_clock_freq_mhz", default=0.0)
        self._spec_clk.setText(f"{float(freq):.2f} MHz" if freq else "-")
        self._spec_io.setText(str(_board_attr(board, "io_count", default="-")))
        bram = _board_attr(board, "bram_kbits", default=0)
        self._spec_bram.setText(f"{bram} Kb" if bram else "-")
        self._spec_dsp.setText(str(_board_attr(board, "dsp_blocks", default="-")))
        self._spec_luts.setText(str(_board_attr(board, "lut_count", default="-")))

        self.target_changed.emit(
            {
                "name": name,
                "vendor": str(_board_attr(board, "vendor", default="")),
                "device": str(_board_attr(board, "device", "part", default="")),
            }
        )

    # -- Toolchain tab ----------------------------------------------------

    def _build_toolchain_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)

        hdr = QLabel("Detected FPGA toolchain binaries")
        hdr.setStyleSheet(f"color:{_DYBER_BLUE}; font-weight:700; padding:4px;")
        lay.addWidget(hdr)

        self._tool_table = QTableWidget(0, 3)
        self._tool_table.setHorizontalHeaderLabels(["Tool", "Status", "Path"])
        self._tool_table.horizontalHeader().setStretchLastSection(True)
        self._tool_table.verticalHeader().setVisible(False)
        self._tool_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self._tool_table)

        row = QHBoxLayout()
        rescan = QPushButton("Rescan")
        rescan.clicked.connect(self._scan_toolchain)
        row.addWidget(rescan)
        row.addStretch()
        lay.addLayout(row)

        return w

    def _scan_toolchain(self) -> None:
        tools = [
            ("yosys", "Yosys synthesis"),
            ("nextpnr-ice40", "nextpnr iCE40"),
            ("nextpnr-ecp5", "nextpnr ECP5"),
            ("nextpnr-nexus", "nextpnr Nexus"),
            ("nextpnr-machxo2", "nextpnr MachXO2"),
            ("nextpnr-generic", "nextpnr generic"),
            ("icepack", "IceStorm icepack"),
            ("icetime", "IceStorm icetime"),
            ("iceprog", "IceStorm iceprog"),
            ("ecppack", "Trellis ecppack"),
            ("gowin_pack", "Apicula gowin_pack"),
            ("openFPGALoader", "openFPGALoader"),
        ]
        self._tool_table.setRowCount(len(tools))
        for i, (bin_name, desc) in enumerate(tools):
            path = shutil.which(bin_name)
            name_item = QTableWidgetItem(f"{bin_name}  --  {desc}")
            status_text = "Found" if path else "Missing"
            status_item = QTableWidgetItem(status_text)
            color = QColor(_GREEN if path else _RED)
            status_item.setForeground(color)
            path_item = QTableWidgetItem(path or "")
            self._tool_table.setItem(i, 0, name_item)
            self._tool_table.setItem(i, 1, status_item)
            self._tool_table.setItem(i, 2, path_item)

    # -- Build tab --------------------------------------------------------

    def _build_build_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        intro = QLabel(
            "Run the FPGA build pipeline. Each step captures stdout/stderr and "
            "reports runtime and exit status."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{_SUBTEXT};")
        lay.addWidget(intro)

        for step in ("Synthesize", "Place & Route", "Pack", "Program"):
            lay.addWidget(self._make_step_widget(step))
        lay.addStretch()
        return w

    def _make_step_widget(self, name: str) -> QGroupBox:
        box = QGroupBox(name)
        glay = QVBoxLayout(box)
        row = QHBoxLayout()
        label = QLabel(name)
        label.setStyleSheet(f"color:{_TEXT}; font-weight:600;")
        status = QLabel("idle")
        status.setStyleSheet(f"color:{_SUBTEXT};")
        runtime = QLabel("-- s")
        runtime.setStyleSheet(f"color:{_SUBTEXT};")
        btn = QPushButton(f"Run {name}")
        btn.setStyleSheet(
            f"QPushButton{{background-color:{_SURFACE1};color:{_TEXT};"
            f"border:1px solid {_SURFACE2};border-radius:4px;padding:5px 10px;}}"
            f"QPushButton:hover{{border-color:{_DYBER_BLUE};}}"
        )
        btn.clicked.connect(lambda _=False, n=name: self._on_run_step(n))
        row.addWidget(label, 1)
        row.addWidget(status)
        row.addWidget(runtime)
        row.addWidget(btn)
        glay.addLayout(row)

        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setMaximumBlockCount(500)
        log.setMaximumHeight(100)
        log.setPlaceholderText(f"{name} log preview ...")
        glay.addWidget(log)

        self._build_steps[name] = _BuildStep(
            name=name,
            label=label,
            status=status,
            runtime=runtime,
            button=btn,
            log_preview=log,
        )
        return box

    def _on_run_step(self, name: str) -> None:
        step = self._build_steps.get(name)
        if step is None:
            return
        step.status.setText("running ...")
        step.status.setStyleSheet(f"color:{_DYBER_BLUE};")
        step.log_preview.setPlainText(f"[{name}] starting ...\n")
        self.build_requested.emit(name)

        start = time.monotonic()
        result: dict[str, Any]
        try:
            if step.runner is not None:
                result = step.runner() or {}
            else:
                result = self._default_step_runner(name)
        except Exception as exc:  # pragma: no cover
            result = {"ok": False, "log": f"exception: {exc}"}
        duration = time.monotonic() - start

        step.last_result = result
        step.runtime.setText(f"{duration:.2f} s")
        ok = bool(result.get("ok", False))
        step.status.setText("done" if ok else "failed")
        step.status.setStyleSheet(f"color:{_GREEN if ok else _RED};")
        log_text = str(result.get("log", result.get("stdout", "")))[:4000]
        if log_text:
            step.log_preview.setPlainText(log_text)

    def _default_step_runner(self, name: str) -> dict[str, Any]:
        # Without a RunEngine hooked up, we just probe that the tools
        # for this step exist and report their availability.
        probes = {
            "Synthesize": ["yosys"],
            "Place & Route": ["nextpnr-ice40", "nextpnr-ecp5"],
            "Pack": ["icepack", "ecppack", "gowin_pack"],
            "Program": ["openFPGALoader", "iceprog"],
        }.get(name, [])
        found = [b for b in probes if shutil.which(b)]
        log = "\n".join(
            f"{b}: {'found at ' + (shutil.which(b) or '') if shutil.which(b) else 'missing'}"
            for b in probes
        )
        return {"ok": bool(found), "log": log or f"no probes for {name}"}

    # -- Resources tab ----------------------------------------------------

    def _build_resources_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        util_box = QGroupBox("Utilization")
        util_lay = QGridLayout(util_box)
        self._util_bars: dict[str, UtilBar] = {}
        for i, key in enumerate(("LUTs", "FFs", "BRAMs", "DSPs")):
            bar = UtilBar(key)
            self._util_bars[key] = bar
            util_lay.addWidget(bar, i // 2, i % 2)
        lay.addWidget(util_box)

        bottom = QHBoxLayout()
        fmax_box = QGroupBox("Fmax")
        fmax_lay = QVBoxLayout(fmax_box)
        self._fmax_dial = FmaxDial()
        fmax_lay.addWidget(self._fmax_dial)
        bottom.addWidget(fmax_box, 1)

        counts_box = QGroupBox("Diagnostics")
        counts_lay = QFormLayout(counts_box)
        self._err_label = QLabel("0")
        self._warn_label = QLabel("0")
        self._tv_label = QLabel("0")
        counts_lay.addRow("Errors:", self._err_label)
        counts_lay.addRow("Warnings:", self._warn_label)
        counts_lay.addRow("Timing violations:", self._tv_label)
        bottom.addWidget(counts_box, 1)

        lay.addLayout(bottom)
        lay.addStretch()
        return w

    def update_resources(self, data: dict[str, Any]) -> None:
        """Feed a ``parse_nextpnr_log`` style dict into the gauges."""
        util = data.get("utilization") or {}
        for key, bar in self._util_bars.items():
            entry = util.get(key)
            if entry:
                used, total, pct = entry
                bar.set_value(int(used), int(total), float(pct))
        self._fmax_dial.set_fmax(float(data.get("fmax_mhz", 0.0)))
        self._tv_label.setText(str(int(data.get("timing_violations", 0))))
        self._err_label.setText(str(int(data.get("errors", 0))))
        self._warn_label.setText(str(int(data.get("warnings", 0))))

    # -- LiteX tab --------------------------------------------------------

    def _build_litex_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        form_box = QGroupBox("LiteX SoC configuration")
        form = QFormLayout(form_box)

        self._litex_board = QComboBox()
        if LITEX_BOARDS:
            for b in sorted(LITEX_BOARDS):
                self._litex_board.addItem(b)
        form.addRow("Board:", self._litex_board)

        self._litex_cpu = QComboBox()
        self._litex_cpu.addItems(
            ["vexriscv", "picorv32", "serv", "neorv32", "naxriscv", "none"]
        )
        form.addRow("CPU type:", self._litex_cpu)

        self._litex_variant = QLineEdit("standard")
        form.addRow("CPU variant:", self._litex_variant)

        self._litex_freq = QSpinBox()
        self._litex_freq.setRange(1, 1000)
        self._litex_freq.setSuffix(" MHz")
        self._litex_freq.setValue(50)
        form.addRow("sys_clk_freq:", self._litex_freq)

        self._litex_rom = QSpinBox()
        self._litex_rom.setRange(0, 1024 * 1024)
        self._litex_rom.setSingleStep(4096)
        self._litex_rom.setValue(0x8000)
        form.addRow("ROM bytes:", self._litex_rom)

        self._litex_sram = QSpinBox()
        self._litex_sram.setRange(0, 1024 * 1024)
        self._litex_sram.setSingleStep(4096)
        self._litex_sram.setValue(0x2000)
        form.addRow("SRAM bytes:", self._litex_sram)

        self._litex_mainram = QSpinBox()
        self._litex_mainram.setRange(0, 16 * 1024 * 1024)
        self._litex_mainram.setSingleStep(4096)
        self._litex_mainram.setValue(0x4000)
        form.addRow("Main RAM bytes:", self._litex_mainram)

        self._litex_uart = QComboBox()
        self._litex_uart.addItems(["serial", "jtag_uart", "crossover", "stub"])
        form.addRow("UART:", self._litex_uart)

        self._litex_eth = QCheckBox("Ethernet")
        self._litex_etherbone = QCheckBox("Etherbone")
        self._litex_sd = QCheckBox("SD card")
        self._litex_video = QCheckBox("Video terminal")
        peris = QHBoxLayout()
        peris.addWidget(self._litex_eth)
        peris.addWidget(self._litex_etherbone)
        peris.addWidget(self._litex_sd)
        peris.addWidget(self._litex_video)
        form.addRow("Peripherals:", self._peripheral_row(peris))

        lay.addWidget(form_box)

        gen_row = QHBoxLayout()
        self._litex_out = QLineEdit()
        self._litex_out.setPlaceholderText("Output directory ...")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_litex_out)
        gen_row.addWidget(self._litex_out, 1)
        gen_row.addWidget(browse)
        lay.addLayout(gen_row)

        self._litex_generate = QPushButton("Generate SoC")
        self._litex_generate.setStyleSheet(
            f"QPushButton{{background-color:{_DYBER_BLUE};color:{_CRUST};"
            f"border:none;border-radius:4px;padding:7px 14px;font-weight:700;}}"
            f"QPushButton:hover{{background-color:{_BLUE};}}"
        )
        self._litex_generate.clicked.connect(self._on_generate_litex)
        lay.addWidget(self._litex_generate)

        self._litex_log = QPlainTextEdit()
        self._litex_log.setReadOnly(True)
        self._litex_log.setMaximumBlockCount(1000)
        self._litex_log.setPlaceholderText("LiteX generation log ...")
        lay.addWidget(self._litex_log, 1)

        return w

    def _peripheral_row(self, hlay: QHBoxLayout) -> QWidget:
        host = QWidget()
        host.setLayout(hlay)
        return host

    def _browse_litex_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output directory")
        if path:
            self._litex_out.setText(path)

    def _on_generate_litex(self) -> None:
        if LiteXBuilder is None or LiteXSocConfig is None:
            self._litex_log.setPlainText(
                "openforge.litex.integration is not importable. "
                "Install dependencies and retry."
            )
            return
        board = self._litex_board.currentText().strip()
        out = self._litex_out.text().strip()
        if not board or not out:
            self._litex_log.setPlainText("Select a board and output directory.")
            return

        cfg = LiteXSocConfig(
            cpu_type=self._litex_cpu.currentText(),
            cpu_variant=self._litex_variant.text().strip() or "standard",
            sys_clk_freq=int(self._litex_freq.value()) * 1_000_000,
            integrated_rom_size=int(self._litex_rom.value()),
            integrated_sram_size=int(self._litex_sram.value()),
            integrated_main_ram_size=int(self._litex_mainram.value()),
            uart_name=self._litex_uart.currentText(),
            with_ethernet=self._litex_eth.isChecked(),
            with_etherbone=self._litex_etherbone.isChecked(),
            with_sdcard=self._litex_sd.isChecked(),
            with_video_terminal=self._litex_video.isChecked(),
        )
        try:
            builder = LiteXBuilder(board, cfg, Path(out))
            script_path = builder.generate()
        except Exception as exc:  # pragma: no cover
            self._litex_log.setPlainText(f"Failed: {exc}")
            return

        self._litex_log.setPlainText(
            f"Generated {script_path}\n\nRun it with:\n    python {script_path}\n"
        )
        self.litex_generate_requested.emit(
            {"board": board, "config": cfg.model_dump(), "script": str(script_path)}
        )

    # ------------------------------------------------------------------
    # Public API (compat with existing mainwindow)
    # ------------------------------------------------------------------

    def set_bitstream_path(self, path: str) -> None:
        self._current_bitstream = path

    def get_target(self) -> dict[str, Any]:
        board = self._current_board
        if board is None:
            return {}
        return {
            "name": _board_attr(board, "name", default=""),
            "vendor": str(_board_attr(board, "vendor", default="")),
            "device": str(_board_attr(board, "device", "part", default="")),
            "constraint_file": self._constraint_path or None,
        }

    def set_detected_devices(self, devices: list[dict]) -> None:
        # Kept for backward compat; toolchain tab doesn't show devices.
        return

    def register_step_runner(self, name: str, runner: Callable[[], dict]) -> None:
        """Allow the mainwindow to plug a real RunEngine into a build step."""
        step = self._build_steps.get(name)
        if step is not None:
            step.runner = runner

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        if not dark:
            self.setStyleSheet("")
            return
        qss = f"""
        QDockWidget#FpgaTargetPanel {{ color: {_TEXT}; }}
        QWidget#FpgaTargetRoot {{ background-color: {_BG}; color: {_TEXT}; }}
        QTabWidget::pane {{
            background: {_BG};
            border: 1px solid {_SURFACE1};
            border-radius: 4px;
        }}
        QTabBar::tab {{
            background: {_MANTLE};
            color: {_SUBTEXT};
            padding: 6px 14px;
            border: 1px solid {_SURFACE1};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }}
        QTabBar::tab:selected {{
            background: {_SURFACE0};
            color: {_DYBER_BLUE};
            font-weight: 700;
        }}
        QGroupBox {{
            background-color: {_MANTLE};
            color: {_TEXT};
            border: 1px solid {_SURFACE1};
            border-radius: 6px;
            margin-top: 10px;
            padding: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: {_DYBER_BLUE};
            font-weight: 700;
        }}
        QLabel {{ color: {_TEXT}; }}
        QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget {{
            background-color: {_SURFACE0};
            color: {_TEXT};
            border: 1px solid {_SURFACE1};
            border-radius: 4px;
            padding: 3px 6px;
            selection-background-color: {_DYBER_BLUE};
            selection-color: {_CRUST};
        }}
        QComboBox QAbstractItemView {{
            background-color: {_SURFACE0};
            color: {_TEXT};
            selection-background-color: {_DYBER_BLUE};
        }}
        QPushButton {{
            background-color: {_SURFACE1};
            color: {_TEXT};
            border: 1px solid {_SURFACE2};
            border-radius: 4px;
            padding: 5px 10px;
        }}
        QPushButton:hover {{
            background-color: {_SURFACE2};
            border-color: {_DYBER_BLUE};
        }}
        QHeaderView::section {{
            background-color: {_SURFACE1};
            color: {_TEXT};
            border: none;
            padding: 4px 6px;
        }}
        QCheckBox {{ color: {_TEXT}; }}
        QProgressBar {{
            background-color: {_SURFACE0};
            border: 1px solid {_SURFACE1};
            border-radius: 3px;
        }}
        """
        self.setStyleSheet(qss)
