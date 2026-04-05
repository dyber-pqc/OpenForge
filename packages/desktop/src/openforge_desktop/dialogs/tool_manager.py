"""Tool Manager dialog -- shows installed EDA tools and their status."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSettings,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openforge_desktop.workers import ToolCheckWorker

# ── Catppuccin Mocha palette ───────────────────────────────────────────────

_BG: Final[str] = "#1e1e2e"
_MANTLE: Final[str] = "#181825"
_SURFACE0: Final[str] = "#313244"
_SURFACE1: Final[str] = "#45475a"
_TEXT: Final[str] = "#cdd6f4"
_SUBTEXT: Final[str] = "#a6adc8"
_GREEN: Final[str] = "#a6e3a1"
_RED: Final[str] = "#f38ba8"
_YELLOW: Final[str] = "#f9e2af"
_BLUE: Final[str] = "#89b4fa"
_PEACH: Final[str] = "#fab387"
_MAUVE: Final[str] = "#cba6f7"

# ── Tool definitions ──────────────────────────────────────────────────────

_TOOL_CATEGORIES: Final[dict[str, list[dict[str, str]]]] = {
    "Simulation": [
        {"name": "Verilator", "binary": "verilator", "docker": "verilator/verilator"},
        {"name": "Icarus Verilog", "binary": "iverilog", "docker": "hdlc/iverilog"},
        {"name": "GHDL", "binary": "ghdl", "docker": "hdlc/ghdl"},
        {"name": "cocotb", "binary": "cocotb-config", "docker": ""},
    ],
    "Synthesis": [
        {"name": "Yosys", "binary": "yosys", "docker": "hdlc/yosys"},
    ],
    "Physical Design": [
        {"name": "OpenSTA", "binary": "sta", "docker": "openroad/opensta"},
        {"name": "OpenROAD", "binary": "openroad", "docker": "openroad/flow"},
        {"name": "Magic", "binary": "magic", "docker": "efabless/magic"},
        {"name": "KLayout", "binary": "klayout", "docker": ""},
    ],
    "Verification": [
        {"name": "SymbiYosys", "binary": "sby", "docker": "hdlc/symbiyosys"},
        {"name": "Netgen", "binary": "netgen", "docker": "efabless/netgen"},
    ],
    "Analysis": [
        {"name": "Verible", "binary": "verible-verilog-lint", "docker": "chipsalliance/verible"},
    ],
}


class ToolManagerDialog(QDialog):
    """Dialog showing all EDA tool engines with install/version status."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tool Manager")
        self.setMinimumSize(750, 550)
        self.resize(800, 600)

        self._settings = QSettings("Dyber", "OpenForge EDA")
        self._worker: ToolCheckWorker | None = None
        self._tool_rows: dict[str, int] = {}

        self._build_ui()
        self._load_custom_paths()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header = QLabel("OpenForge EDA Tool Manager")
        header.setStyleSheet(
            f"color: {_BLUE}; font-size: 16px; font-weight: bold; padding: 4px;"
        )
        layout.addWidget(header)

        desc = QLabel(
            "Check the installation status of all EDA tools. "
            "Missing tools can be run via Docker containers."
        )
        desc.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px; padding: 0 4px 4px 4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tool table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Category", "Tool", "Binary", "Installed", "Version", "Docker Image",
        ])
        header_view = self._table.horizontalHeader()
        if header_view is not None:
            header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        self._populate_table()
        layout.addWidget(self._table, stretch=1)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        self._progress.setFormat("Checking tools... %v / %m")
        layout.addWidget(self._progress)

        # Summary
        self._summary = QLabel("Click 'Check All' to scan installed tools")
        self._summary.setStyleSheet(
            f"color: {_SUBTEXT}; font-size: 12px; padding: 4px;"
        )
        layout.addWidget(self._summary)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_check = QPushButton("Check All")
        self._btn_check.setStyleSheet(
            f"background: {_SURFACE0}; color: {_GREEN}; font-weight: bold;"
        )
        self._btn_check.clicked.connect(self._on_check_all)
        btn_row.addWidget(self._btn_check)

        btn_row.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    def _populate_table(self) -> None:
        """Fill the table with all known tools grouped by category."""
        total = sum(len(tools) for tools in _TOOL_CATEGORIES.values())
        self._table.setRowCount(total)

        row = 0
        for category, tools in _TOOL_CATEGORIES.items():
            for tool in tools:
                name = tool["name"]
                self._tool_rows[name] = row

                cat_item = QTableWidgetItem(category)
                cat_item.setForeground(QColor(_MAUVE))
                self._table.setItem(row, 0, cat_item)

                name_item = QTableWidgetItem(name)
                name_item.setForeground(QColor(_TEXT))
                font = QFont()
                font.setBold(True)
                name_item.setFont(font)
                self._table.setItem(row, 1, name_item)

                bin_item = QTableWidgetItem(tool["binary"])
                bin_item.setForeground(QColor(_SUBTEXT))
                self._table.setItem(row, 2, bin_item)

                status_item = QTableWidgetItem("--")
                status_item.setForeground(QColor(_SUBTEXT))
                status_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                self._table.setItem(row, 3, status_item)

                ver_item = QTableWidgetItem("--")
                ver_item.setForeground(QColor(_SUBTEXT))
                self._table.setItem(row, 4, ver_item)

                docker_item = QTableWidgetItem(tool["docker"] or "N/A")
                docker_item.setForeground(QColor(_SUBTEXT))
                self._table.setItem(row, 5, docker_item)

                row += 1

    # ------------------------------------------------------------------
    # Check all tools
    # ------------------------------------------------------------------

    def _on_check_all(self) -> None:
        if self._worker is not None:
            return

        total = sum(len(tools) for tools in _TOOL_CATEGORIES.values())
        self._progress.setMaximum(total)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._btn_check.setEnabled(False)
        self._checked = 0
        self._installed_count = 0

        self._worker = ToolCheckWorker(parent=self)
        self._worker.tool_checked.connect(self._on_tool_checked)
        self._worker.all_finished.connect(self._on_all_checked)
        self._worker.start()

    @Slot(str, bool, str)
    def _on_tool_checked(self, name: str, installed: bool, version: str) -> None:
        self._checked += 1
        self._progress.setValue(self._checked)

        row = self._tool_rows.get(name)
        if row is None:
            return

        if installed:
            self._installed_count += 1

        # Status column
        status_item = QTableWidgetItem("Yes" if installed else "No")
        status_item.setForeground(QColor(_GREEN if installed else _RED))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setBold(True)
        status_item.setFont(font)
        self._table.setItem(row, 3, status_item)

        # Version column
        ver_item = QTableWidgetItem(version if version else "--")
        ver_item.setForeground(QColor(_TEXT if version else _SUBTEXT))
        self._table.setItem(row, 4, ver_item)

    @Slot()
    def _on_all_checked(self) -> None:
        self._progress.setVisible(False)
        self._btn_check.setEnabled(True)
        self._worker = None

        total = sum(len(tools) for tools in _TOOL_CATEGORIES.values())
        pct = 100.0 * self._installed_count / total if total else 0
        color = _GREEN if pct > 80 else (_YELLOW if pct > 50 else _RED)
        self._summary.setText(
            f"{self._installed_count}/{total} tools installed ({pct:.0f}% ready)"
        )
        self._summary.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: bold; padding: 4px;"
        )

    # ------------------------------------------------------------------
    # Custom paths persistence
    # ------------------------------------------------------------------

    def _load_custom_paths(self) -> None:
        """Load user-configured custom binary paths from QSettings."""
        # Reserved for future "Configure" button per tool
        pass

    def _save_custom_path(self, tool_name: str, path: str) -> None:
        self._settings.setValue(f"tool_paths/{tool_name}", path)
