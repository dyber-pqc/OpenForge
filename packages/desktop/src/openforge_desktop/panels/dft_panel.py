"""DFT (Scan + ATPG + BIST) dock panel for OpenForge desktop."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


_DARK = {
    "base":    "#1e1e2e",
    "mantle":  "#181825",
    "surface": "#313244",
    "overlay": "#45475a",
    "text":    "#cdd6f4",
    "subtext": "#a6adc8",
    "blue":    "#89b4fa",
    "mauve":   "#cba6f7",
    "green":   "#a6e3a1",
    "red":     "#f38ba8",
    "yellow":  "#f9e2af",
    "peach":   "#fab387",
}

_LIGHT = {
    "base":    "#eff1f5",
    "mantle":  "#e6e9ef",
    "surface": "#dce0e8",
    "overlay": "#bcc0cc",
    "text":    "#4c4f69",
    "subtext": "#6c6f85",
    "blue":    "#1e66f5",
    "mauve":   "#8839ef",
    "green":   "#40a02b",
    "red":     "#d20f39",
    "yellow":  "#df8e1d",
    "peach":   "#fe640b",
}


class _ScanChainWidget(QWidget):
    """Lightweight visualizer drawing flops as boxes connected by lines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self._chains: list = []
        self._dark = True

    def set_chains(self, chains: list) -> None:
        self._chains = chains
        self.update()

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def paintEvent(self, _event) -> None:
        p = _DARK if self._dark else _LIGHT
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(p["mantle"]))

        if not self._chains:
            painter.setPen(QPen(QColor(p["subtext"])))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "(no scan chains - run insertion)",
            )
            return

        box_w = 28
        box_h = 18
        gap = 6
        y0 = 10
        for ci, chain in enumerate(self._chains):
            y = y0 + ci * (box_h + 18)
            x = 10
            painter.setPen(QPen(QColor(p["text"])))
            painter.drawText(x, y - 2, f"{chain.name} (len={chain.length})")
            for fi, _flop in enumerate(chain.flops[:60]):
                rx = x + fi * (box_w + gap)
                ry = y + 4
                painter.setBrush(QBrush(QColor(p["blue"])))
                painter.setPen(QPen(QColor(p["overlay"])))
                painter.drawRoundedRect(rx, ry, box_w, box_h, 3, 3)
                if fi > 0:
                    pen = QPen(QColor(p["mauve"]), 1.5)
                    painter.setPen(pen)
                    painter.drawLine(
                        rx, ry + box_h // 2,
                        rx - gap, ry + box_h // 2,
                    )
            if len(chain.flops) > 60:
                painter.setPen(QPen(QColor(p["subtext"])))
                painter.drawText(
                    x + 60 * (box_w + gap), y + box_h,
                    f"... +{len(chain.flops) - 60} more",
                )
        painter.end()


class DftPanel(QDockWidget):
    """DFT panel: scan insertion, ATPG, and memory BIST."""

    insertScanRequested = Signal(str, str, int, int)
    runAtpgRequested = Signal(str, str, str)
    insertBistRequested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DFT")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setObjectName("DftPanel")
        self._dark = True

        root = QWidget(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Common netlist + top inputs
        head = QGridLayout()
        self.netlistEdit = QLineEdit()
        self.netlistEdit.setPlaceholderText("Netlist (.v)")
        self.netlistBtn = QPushButton("Browse...")
        self.netlistBtn.clicked.connect(self._pick_netlist)
        self.topEdit = QLineEdit()
        self.topEdit.setPlaceholderText("Top module")
        head.addWidget(QLabel("Netlist:"), 0, 0)
        head.addWidget(self.netlistEdit, 0, 1)
        head.addWidget(self.netlistBtn, 0, 2)
        head.addWidget(QLabel("Top:"), 1, 0)
        head.addWidget(self.topEdit, 1, 1, 1, 2)
        outer.addLayout(head)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self._build_scan_tab()
        self._build_atpg_tab()
        self._build_bist_tab()

        self.setWidget(root)
        self.set_theme(True)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_scan_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)

        settings = QGridLayout()
        self.maxChainLen = QSpinBox()
        self.maxChainLen.setRange(8, 8192)
        self.maxChainLen.setValue(256)
        self.numChains = QSpinBox()
        self.numChains.setRange(1, 64)
        self.numChains.setValue(1)
        self.scanCellEdit = QLineEdit("sky130_fd_sc_hd__sdfrtp_1")
        settings.addWidget(QLabel("Max chain length:"), 0, 0)
        settings.addWidget(self.maxChainLen, 0, 1)
        settings.addWidget(QLabel("Num chains:"), 0, 2)
        settings.addWidget(self.numChains, 0, 3)
        settings.addWidget(QLabel("Scan cell:"), 1, 0)
        settings.addWidget(self.scanCellEdit, 1, 1, 1, 3)
        lay.addLayout(settings)

        self.insertScanBtn = QPushButton("Insert Scan Chains")
        self.insertScanBtn.setObjectName("DftPrimaryBtn")
        self.insertScanBtn.clicked.connect(self._on_insert_scan)
        lay.addWidget(self.insertScanBtn)

        results = QGridLayout()
        self.totalFlopsLbl   = QLabel("-")
        self.scannedFlopsLbl = QLabel("-")
        self.coverageLbl     = QLabel("-")
        self.coverageBar     = QProgressBar()
        self.coverageBar.setRange(0, 100)
        results.addWidget(QLabel("Total flops:"),   0, 0)
        results.addWidget(self.totalFlopsLbl,       0, 1)
        results.addWidget(QLabel("Scanned flops:"), 0, 2)
        results.addWidget(self.scannedFlopsLbl,     0, 3)
        results.addWidget(QLabel("Coverage:"),      1, 0)
        results.addWidget(self.coverageLbl,         1, 1)
        results.addWidget(self.coverageBar,         1, 2, 1, 2)
        lay.addLayout(results)

        self.chainViz = _ScanChainWidget()
        lay.addWidget(self.chainViz, 1)

        self.tabs.addTab(w, "Scan Insertion")

    def _build_atpg_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)

        settings = QGridLayout()
        self.faultModelCombo = QComboBox()
        self.faultModelCombo.addItems([
            "stuck_at", "transition", "path_delay", "iddq", "bridging",
        ])
        settings.addWidget(QLabel("Fault model:"), 0, 0)
        settings.addWidget(self.faultModelCombo, 0, 1)
        lay.addLayout(settings)

        self.atpgBtn = QPushButton("Generate Patterns")
        self.atpgBtn.setObjectName("DftPrimaryBtn")
        self.atpgBtn.clicked.connect(self._on_run_atpg)
        lay.addWidget(self.atpgBtn)

        results = QGridLayout()
        self.patternCountLbl = QLabel("-")
        self.faultCovLbl     = QLabel("-")
        self.faultCovBar     = QProgressBar()
        self.faultCovBar.setRange(0, 100)
        results.addWidget(QLabel("Pattern count:"), 0, 0)
        results.addWidget(self.patternCountLbl,    0, 1)
        results.addWidget(QLabel("Fault coverage:"), 0, 2)
        results.addWidget(self.faultCovLbl,        0, 3)
        results.addWidget(self.faultCovBar,        1, 0, 1, 4)
        lay.addLayout(results)

        self.uncoveredTbl = QTableWidget(0, 3)
        self.uncoveredTbl.setHorizontalHeaderLabels(
            ["Fault site", "Type", "Severity"]
        )
        self.uncoveredTbl.horizontalHeader().setStretchLastSection(True)
        self.uncoveredTbl.verticalHeader().setVisible(False)
        lay.addWidget(QLabel("Top uncovered faults:"))
        lay.addWidget(self.uncoveredTbl, 1)

        self.tabs.addTab(w, "ATPG")

    def _build_bist_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)

        head = QHBoxLayout()
        self.detectMemBtn = QPushButton("Detect Memories")
        self.detectMemBtn.clicked.connect(self._on_detect_memories)
        self.algoCombo = QComboBox()
        self.algoCombo.addItems([
            "MARCH-C-", "MATS+", "Checkerboard", "Walking-1",
        ])
        self.insertBistBtn = QPushButton("Insert BIST")
        self.insertBistBtn.setObjectName("DftPrimaryBtn")
        self.insertBistBtn.clicked.connect(self._on_insert_bist)
        head.addWidget(self.detectMemBtn)
        head.addWidget(QLabel("Algorithm:"))
        head.addWidget(self.algoCombo, 1)
        head.addWidget(self.insertBistBtn)
        lay.addLayout(head)

        self.memTbl = QTableWidget(0, 5)
        self.memTbl.setHorizontalHeaderLabels(
            ["Instance", "Type", "Width", "Depth", "Ports"]
        )
        self.memTbl.horizontalHeader().setStretchLastSection(True)
        self.memTbl.verticalHeader().setVisible(False)
        lay.addWidget(self.memTbl, 1)

        lay.addWidget(QLabel("BIST controller preview:"))
        self.bistPreview = QPlainTextEdit()
        self.bistPreview.setReadOnly(True)
        f = QFont("Consolas", 9)
        self.bistPreview.setFont(f)
        lay.addWidget(self.bistPreview, 2)

        self.tabs.addTab(w, "BIST")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _pick_netlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select netlist", "",
            "Verilog (*.v *.sv);;All files (*)",
        )
        if path:
            self.netlistEdit.setText(path)

    def _on_insert_scan(self) -> None:
        self.insertScanRequested.emit(
            self.netlistEdit.text(),
            self.topEdit.text(),
            self.maxChainLen.value(),
            self.numChains.value(),
        )

    def _on_run_atpg(self) -> None:
        self.runAtpgRequested.emit(
            self.netlistEdit.text(),
            self.topEdit.text(),
            self.faultModelCombo.currentText(),
        )

    def _on_detect_memories(self) -> None:
        try:
            from openforge.verification.bist import BistInserter
            mems = BistInserter().detect_memories(Path(self.netlistEdit.text()))
            self.show_memories(mems)
        except Exception as e:
            self.bistPreview.setPlainText(f"(detection failed: {e})")

    def _on_insert_bist(self) -> None:
        self.insertBistRequested.emit(
            self.netlistEdit.text(),
            self.topEdit.text(),
            self.algoCombo.currentText(),
        )
        try:
            from openforge.verification.bist import BistInserter, MemoryInfo
            ins = BistInserter()
            mem = MemoryInfo(name="preview", instance="u_mem",
                             width=32, depth=256)
            self.bistPreview.setPlainText(
                ins.generate_bist_controller(mem, self.algoCombo.currentText())
            )
        except Exception as e:
            self.bistPreview.setPlainText(f"(preview failed: {e})")

    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------

    def show_scan_result(self, result) -> None:
        if result is None:
            return
        self.totalFlopsLbl.setText(str(result.total_flops))
        self.scannedFlopsLbl.setText(str(result.scanned_flops))
        cov = float(getattr(result, "scan_coverage", 0.0))
        self.coverageLbl.setText(f"{cov:.1f}%")
        self.coverageBar.setValue(int(cov))
        self.chainViz.set_chains(getattr(result, "scan_chains", []) or [])

    def show_atpg_result(self, result) -> None:
        if result is None:
            return
        self.patternCountLbl.setText(str(getattr(result, "test_patterns", 0)))
        cov = float(getattr(result, "fault_coverage", 0.0))
        self.faultCovLbl.setText(f"{cov:.2f}%")
        self.faultCovBar.setValue(int(cov))

    def show_memories(self, memories) -> None:
        memories = memories or []
        self.memTbl.setRowCount(len(memories))
        for i, m in enumerate(memories):
            self.memTbl.setItem(i, 0, QTableWidgetItem(m.instance))
            self.memTbl.setItem(i, 1, QTableWidgetItem(m.name))
            self.memTbl.setItem(i, 2, QTableWidgetItem(str(m.width)))
            self.memTbl.setItem(i, 3, QTableWidgetItem(str(m.depth)))
            ports = "DP" if m.is_dual_port else "SP"
            self.memTbl.setItem(i, 4, QTableWidgetItem(ports))

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = bool(dark)
        p = _DARK if self._dark else _LIGHT
        self.chainViz.set_theme(self._dark)
        qss = f"""
        QWidget {{
            background-color: {p['base']};
            color: {p['text']};
            font-size: 10pt;
        }}
        QLineEdit, QPlainTextEdit, QTableWidget, QSpinBox, QComboBox {{
            background-color: {p['mantle']};
            color: {p['text']};
            border: 1px solid {p['overlay']};
            border-radius: 4px;
            padding: 4px;
        }}
        QPushButton {{
            background-color: {p['surface']};
            color: {p['text']};
            border: 1px solid {p['overlay']};
            padding: 5px 12px;
            border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {p['overlay']}; }}
        QPushButton#DftPrimaryBtn {{
            background-color: {p['mauve']};
            color: {p['base']};
            font-weight: bold;
        }}
        QTabWidget::pane {{ border: 1px solid {p['overlay']}; }}
        QTabBar::tab {{
            background: {p['surface']};
            color: {p['subtext']};
            padding: 6px 12px;
        }}
        QTabBar::tab:selected {{
            background: {p['mantle']};
            color: {p['text']};
        }}
        QHeaderView::section {{
            background-color: {p['surface']};
            color: {p['text']};
            border: 1px solid {p['overlay']};
            padding: 4px;
        }}
        QProgressBar {{
            background-color: {p['mantle']};
            border: 1px solid {p['overlay']};
            border-radius: 4px;
            text-align: center;
            color: {p['text']};
        }}
        QProgressBar::chunk {{
            background-color: {p['green']};
            border-radius: 3px;
        }}
        """
        self.setStyleSheet(qss)


__all__ = ["DftPanel"]
