"""LVS Debugger dock panel for OpenForge desktop."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Catppuccin Mocha palette
_DARK = {
    "base": "#1e1e2e",
    "mantle": "#181825",
    "surface": "#313244",
    "overlay": "#45475a",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "blue": "#89b4fa",
    "green": "#a6e3a1",
    "red": "#f38ba8",
    "yellow": "#f9e2af",
}

_LIGHT = {
    "base": "#eff1f5",
    "mantle": "#e6e9ef",
    "surface": "#dce0e8",
    "overlay": "#bcc0cc",
    "text": "#4c4f69",
    "subtext": "#6c6f85",
    "blue": "#1e66f5",
    "green": "#40a02b",
    "red": "#d20f39",
    "yellow": "#df8e1d",
}


class LvsDebuggerPanel(QDockWidget):
    """Production-grade LVS debugger dock panel."""

    runRequested = Signal(str, str, str)  # layout, schematic, top

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LVS Debugger")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setObjectName("LvsDebuggerPanel")

        self._dark = True
        self._result = None

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ----- File pickers + run button -----
        pickers = QGridLayout()
        pickers.setHorizontalSpacing(6)
        pickers.setVerticalSpacing(4)

        self.layoutEdit = QLineEdit()
        self.layoutEdit.setPlaceholderText("Layout netlist (.spice / .cdl)")
        self.layoutBtn = QPushButton("Browse...")
        self.layoutBtn.clicked.connect(self._pick_layout)

        self.schemEdit = QLineEdit()
        self.schemEdit.setPlaceholderText("Schematic netlist (.v / .spice)")
        self.schemBtn = QPushButton("Browse...")
        self.schemBtn.clicked.connect(self._pick_schem)

        self.topEdit = QLineEdit()
        self.topEdit.setPlaceholderText("Top module name")

        self.runBtn = QPushButton("Run LVS")
        self.runBtn.setObjectName("LvsRunBtn")
        self.runBtn.clicked.connect(self._on_run)

        self.runNativeBtn = QPushButton("Run Native LVS (Rust)")
        self.runNativeBtn.setToolTip(
            "Run OpenForge's native Rust LVS engine (openforge-lvs).\n"
            "Faster than Netgen, with VF2 graph isomorphism."
        )
        self.runNativeBtn.clicked.connect(self._on_run_native)

        pickers.addWidget(QLabel("Layout:"), 0, 0)
        pickers.addWidget(self.layoutEdit, 0, 1)
        pickers.addWidget(self.layoutBtn, 0, 2)
        pickers.addWidget(QLabel("Schematic:"), 1, 0)
        pickers.addWidget(self.schemEdit, 1, 1)
        pickers.addWidget(self.schemBtn, 1, 2)
        pickers.addWidget(QLabel("Top:"), 2, 0)
        pickers.addWidget(self.topEdit, 2, 1)
        pickers.addWidget(self.runBtn, 2, 2)
        pickers.addWidget(self.runNativeBtn, 3, 1, 1, 2)
        layout.addLayout(pickers)

        # ----- Big status banner -----
        self.statusLabel = QLabel("READY")
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self.statusLabel.setFont(f)
        self.statusLabel.setObjectName("LvsStatus")
        self.statusLabel.setMinimumHeight(56)
        layout.addWidget(self.statusLabel)

        # ----- Stats grid -----
        stats = QGridLayout()
        stats.setHorizontalSpacing(20)
        stats.addWidget(QLabel("<b>Layout</b>"), 0, 1)
        stats.addWidget(QLabel("<b>Schematic</b>"), 0, 2)
        stats.addWidget(QLabel("Devices:"), 1, 0)
        stats.addWidget(QLabel("Nets:"), 2, 0)
        self.layDev = QLabel("-")
        self.layNet = QLabel("-")
        self.scDev = QLabel("-")
        self.scNet = QLabel("-")
        stats.addWidget(self.layDev, 1, 1)
        stats.addWidget(self.layNet, 2, 1)
        stats.addWidget(self.scDev, 1, 2)
        stats.addWidget(self.scNet, 2, 2)
        layout.addLayout(stats)

        # ----- Tabs -----
        self.tabs = QTabWidget()
        self.mismatchTbl = self._make_table(["Type", "Layout", "Schematic", "Description"])
        self.netDiffTbl = self._make_table(["Layout net", "Schematic net", "Matched"])
        self.devDiffTbl = self._make_table(["Instance", "Type", "Parameters", "Matched"])
        self.suggestList = QPlainTextEdit()
        self.suggestList.setReadOnly(True)
        self.logView = QPlainTextEdit()
        self.logView.setReadOnly(True)
        f2 = QFont("Consolas", 9)
        self.logView.setFont(f2)

        self.tabs.addTab(self.mismatchTbl, "Mismatches")
        self.tabs.addTab(self.netDiffTbl, "Net Diff")
        self.tabs.addTab(self.devDiffTbl, "Device Diff")
        self.tabs.addTab(self.suggestList, "Suggestions")
        self.tabs.addTab(self.logView, "Log")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        layout.addWidget(splitter, 1)

        self.setWidget(root)
        self.set_theme(True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        return t

    def _pick_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select layout netlist",
            "",
            "Netlists (*.spice *.cdl *.sp *.v);;All files (*)",
        )
        if path:
            self.layoutEdit.setText(path)

    def _pick_schem(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select schematic netlist",
            "",
            "Netlists (*.v *.spice *.sp *.cdl);;All files (*)",
        )
        if path:
            self.schemEdit.setText(path)

    def _on_run(self) -> None:
        self.runRequested.emit(
            self.layoutEdit.text(),
            self.schemEdit.text(),
            self.topEdit.text(),
        )

    def _on_run_native(self) -> None:
        """Run the native Rust LVS engine (openforge-lvs) and show results."""
        import json
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path as _Path

        from PySide6.QtWidgets import QMessageBox

        layout = self.layoutEdit.text().strip()
        schem = self.schemEdit.text().strip()
        top = self.topEdit.text().strip() or "top"
        if not layout or not schem:
            QMessageBox.warning(
                self,
                "Run Native LVS",
                "Please pick both a layout netlist and a schematic netlist first.",
            )
            return

        # Locate the openforge-lvs binary
        bin_path = shutil.which("openforge-lvs")
        if bin_path is None:
            here = _Path(__file__).resolve()
            for parent in here.parents:
                for sub in ("target/release", "target/debug"):
                    for ext in ("", ".exe"):
                        cand = parent / sub / f"openforge-lvs{ext}"
                        if cand.exists():
                            bin_path = str(cand)
                            break
                    if bin_path:
                        break
                if bin_path:
                    break
        if bin_path is None:
            QMessageBox.warning(
                self,
                "Native LVS not found",
                "openforge-lvs binary not found. Build it with:\n\n"
                "  cargo build --release -p openforge-lvs",
            )
            return

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            out_path = tf.name

        try:
            proc = subprocess.run(
                [
                    str(bin_path),
                    "check",
                    "--layout",
                    layout,
                    "--schematic",
                    schem,
                    "--top",
                    top,
                    "--output",
                    out_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "LVS", "LVS run timed out (120s).")
            return
        except Exception as exc:
            QMessageBox.critical(self, "LVS error", str(exc))
            return

        # Exit codes: 0 = MATCH, 1 = MISMATCH, 2 = error
        if proc.returncode == 2:
            QMessageBox.critical(
                self,
                "LVS error",
                f"openforge-lvs error:\n\n{proc.stderr[:500] or proc.stdout[:500]}",
            )
            return

        # Render results from the JSON report
        try:
            with open(out_path, encoding="utf-8") as f:
                report = json.load(f)
        except Exception as exc:
            QMessageBox.warning(self, "LVS", f"Could not read report: {exc}")
            return

        # Map the openforge-lvs JSON schema onto LvsDebugResult-shaped fields
        class _Wrap:
            pass

        r = _Wrap()
        r.matched = bool(report.get("matched", False))
        r.layout_devices = int(report.get("device_count_layout", 0))
        r.layout_nets = int(report.get("net_count_layout", 0))
        r.schematic_devices = int(report.get("device_count_schem", 0))
        r.schematic_nets = int(report.get("net_count_schem", 0))
        r.mismatches = []
        r.matched_nets = []
        r.unmatched_nets = []
        r.matched_devices = []
        r.unmatched_devices = []
        r.log = proc.stdout

        self.show_result(r)
        QMessageBox.information(
            self,
            "Native LVS complete",
            f"openforge-lvs exit code: {proc.returncode} "
            f"({'MATCH' if r.matched else 'MISMATCH'})\n\n{proc.stdout[-400:]}",
        )

    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------

    def show_result(self, result) -> None:
        """Populate the panel from an LvsDebugResult."""
        self._result = result
        if result is None:
            self.statusLabel.setText("READY")
            return

        if getattr(result, "matched", False):
            self.statusLabel.setText("MATCH")
            color = _DARK["green"] if self._dark else _LIGHT["green"]
        else:
            self.statusLabel.setText("MISMATCH")
            color = _DARK["red"] if self._dark else _LIGHT["red"]
        self.statusLabel.setStyleSheet(
            f"color: {color}; padding: 6px; border: 2px solid {color}; border-radius: 6px;"
        )

        self.layDev.setText(str(getattr(result, "layout_devices", 0)))
        self.layNet.setText(str(getattr(result, "layout_nets", 0)))
        self.scDev.setText(str(getattr(result, "schematic_devices", 0)))
        self.scNet.setText(str(getattr(result, "schematic_nets", 0)))

        # Mismatches
        mm = getattr(result, "mismatches", []) or []
        self.mismatchTbl.setRowCount(len(mm))
        for i, m in enumerate(mm):
            self.mismatchTbl.setItem(i, 0, QTableWidgetItem(str(m.type)))
            self.mismatchTbl.setItem(i, 1, QTableWidgetItem(str(m.layout_value)))
            self.mismatchTbl.setItem(i, 2, QTableWidgetItem(str(m.schematic_value)))
            self.mismatchTbl.setItem(i, 3, QTableWidgetItem(str(m.description)))

        # Net diff
        nets = list(getattr(result, "matched_nets", []) or [])
        nets += list(getattr(result, "unmatched_nets", []) or [])
        self.netDiffTbl.setRowCount(len(nets))
        for i, n in enumerate(nets):
            self.netDiffTbl.setItem(i, 0, QTableWidgetItem(n.name_layout))
            self.netDiffTbl.setItem(i, 1, QTableWidgetItem(n.name_schematic))
            it = QTableWidgetItem("YES" if n.matched else "NO")
            self.netDiffTbl.setItem(i, 2, it)

        # Device diff
        devs = list(getattr(result, "matched_devices", []) or [])
        devs += list(getattr(result, "unmatched_devices", []) or [])
        self.devDiffTbl.setRowCount(len(devs))
        for i, d in enumerate(devs):
            self.devDiffTbl.setItem(i, 0, QTableWidgetItem(d.instance))
            self.devDiffTbl.setItem(i, 1, QTableWidgetItem(d.type))
            params = ", ".join(f"{k}={v}" for k, v in d.parameters.items())
            self.devDiffTbl.setItem(i, 2, QTableWidgetItem(params))
            self.devDiffTbl.setItem(i, 3, QTableWidgetItem("YES" if d.matched else "NO"))

        # Suggestions
        try:
            from openforge.physical.lvs_debugger import LvsDebugger

            dbg = LvsDebugger()
            text = "ROOT CAUSE\n  " + dbg.find_root_cause(result) + "\n\n"
            text += "SUGGESTED FIXES\n"
            for s in dbg.suggest_fixes(result):
                text += f"  - {s}\n"
            self.suggestList.setPlainText(text)
        except Exception as e:
            self.suggestList.setPlainText(f"(suggestion engine unavailable: {e})")

        # Log
        self.logView.setPlainText(getattr(result, "log", "") or "")

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = bool(dark)
        p = _DARK if self._dark else _LIGHT
        qss = f"""
        QDockWidget {{
            color: {p["text"]};
        }}
        QWidget {{
            background-color: {p["base"]};
            color: {p["text"]};
            font-size: 10pt;
        }}
        QLineEdit, QPlainTextEdit, QTableWidget {{
            background-color: {p["mantle"]};
            color: {p["text"]};
            border: 1px solid {p["overlay"]};
            border-radius: 4px;
            padding: 4px;
        }}
        QPushButton {{
            background-color: {p["surface"]};
            color: {p["text"]};
            border: 1px solid {p["overlay"]};
            padding: 5px 12px;
            border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {p["overlay"]}; }}
        QPushButton#LvsRunBtn {{
            background-color: {p["blue"]};
            color: {p["base"]};
            font-weight: bold;
        }}
        QTabWidget::pane {{ border: 1px solid {p["overlay"]}; }}
        QTabBar::tab {{
            background: {p["surface"]};
            color: {p["subtext"]};
            padding: 6px 12px;
        }}
        QTabBar::tab:selected {{
            background: {p["mantle"]};
            color: {p["text"]};
        }}
        QHeaderView::section {{
            background-color: {p["surface"]};
            color: {p["text"]};
            border: 1px solid {p["overlay"]};
            padding: 4px;
        }}
        """
        self.setStyleSheet(qss)


__all__ = ["LvsDebuggerPanel"]
