"""AXI protocol checker panel.

Lists AXI interfaces detected in the active block design and lets the
user wrap them with assertion monitors, view per-interface status, and
read live assertion firings from a running simulation.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge_desktop.panels._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:
        return extra

try:
    from openforge.block_design.auto_connect import AutoConnector
    from openforge.verification.axi_monitors import (
        generate_axi4_full_monitor,
        generate_axi4_lite_monitor,
        generate_axis_monitor,
    )
    _CORE_OK = True
except Exception:  # pragma: no cover
    _CORE_OK = False


_BG = "#1e1e2e"
_MANTLE = "#181825"
_SURFACE0 = "#313244"
_SURFACE1 = "#45475a"
_TEXT = "#cdd6f4"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"
_BLUE = "#89b4fa"


class AxiCheckerPanel(QDockWidget):
    """Dock showing per-interface protocol checker state."""

    monitors_generated = Signal(dict)  # {interface_name: verilog_source}

    def __init__(self, title: str = "AXI Checker", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._design: Any = None
        self._monitors: dict[str, str] = {}
        self._status: dict[str, dict] = {}

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Toolbar row
        row = QHBoxLayout()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_wrap = QPushButton("Wrap with Monitor")
        self._btn_remove = QPushButton("Remove Monitor")
        self._btn_run = QPushButton("Run Sim with Assertions")
        self._btn_refresh.clicked.connect(self.refresh)
        self._btn_wrap.clicked.connect(self._wrap_selected)
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_run.clicked.connect(self._run_sim)
        for b in (self._btn_refresh, self._btn_wrap, self._btn_remove, self._btn_run):
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)

        split = QSplitter(Qt.Orientation.Vertical)

        # Tree of interfaces
        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(
            ["Interface", "Kind", "Direction", "Monitored", "Status"]
        )
        self._tree.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self._tree)

        # Lower: log + coverage
        lower = QWidget()
        llay = QVBoxLayout(lower)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.addWidget(QLabel("Assertion log:"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        llay.addWidget(self._log, stretch=1)
        self._cov_label = QLabel("Coverage: (no data)")
        self._cov_label.setWordWrap(True)
        llay.addWidget(self._cov_label)
        split.addWidget(lower)

        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        self.setWidget(central)
        self._apply_theme()

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        self.setStyleSheet(
            panel_tab_qss(True)
            + f"""
            QDockWidget, QWidget {{ background: {_BG}; color: {_TEXT}; }}
            QTreeWidget, QPlainTextEdit {{
                background: {_MANTLE}; color: {_TEXT};
                border: 1px solid {_SURFACE0};
                font-size: 11px;
            }}
            QPushButton {{
                background: {_SURFACE0}; color: {_TEXT};
                border: 1px solid {_SURFACE1};
                border-radius: 3px;
                padding: 3px 10px;
                font-size: 11px;
            }}
            QPushButton:hover {{ border-color: {_BLUE}; }}
            QLabel {{ color: {_TEXT}; font-size: 11px; }}
        """
        )

    # ------------------------------------------------------------------
    def set_block_design(self, design: Any) -> None:
        self._design = design
        self.refresh()

    def refresh(self) -> None:
        self._tree.clear()
        if not _CORE_OK or self._design is None:
            root = QTreeWidgetItem(["(no block design loaded)", "", "", "", ""])
            self._tree.addTopLevelItem(root)
            return
        try:
            ac = AutoConnector(self._design)
            ifaces = ac.detect_axi_interfaces()
        except Exception as exc:
            self._tree.addTopLevelItem(
                QTreeWidgetItem([f"(error: {exc})", "", "", "", ""])
            )
            return
        for inst, group in ifaces.items():
            parent = QTreeWidgetItem([inst, "", "", "", ""])
            self._tree.addTopLevelItem(parent)
            for ifc in group:
                key = f"{inst}.{ifc['prefix']}"
                monitored = "yes" if key in self._monitors else "no"
                status = self._status.get(key, {}).get("state", "idle")
                item = QTreeWidgetItem([
                    ifc["prefix"], ifc["kind"], ifc["direction"],
                    monitored, status,
                ])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setData(1, Qt.ItemDataRole.UserRole, ifc)
                parent.addChild(item)
            parent.setExpanded(True)

    # ------------------------------------------------------------------
    def _selected_items(self) -> list[QTreeWidgetItem]:
        out: list[QTreeWidgetItem] = []
        for it in self._tree.selectedItems():
            if it.data(0, Qt.ItemDataRole.UserRole) is not None:
                out.append(it)
        return out

    def _on_select(self) -> None:
        items = self._selected_items()
        if not items:
            self._cov_label.setText("Coverage: (no data)")
            return
        it = items[0]
        key = it.data(0, Qt.ItemDataRole.UserRole)
        st = self._status.get(key, {})
        cov = st.get("coverage", {})
        if cov:
            self._cov_label.setText(
                "Coverage: "
                + ", ".join(f"{k}={v}" for k, v in cov.items())
            )
        else:
            self._cov_label.setText("Coverage: (no data)")

    def _wrap_selected(self) -> None:
        if not _CORE_OK:
            self._log.appendPlainText("core module unavailable; cannot generate monitor")
            return
        items = self._selected_items()
        if not items:
            self._log.appendPlainText("no interface selected")
            return
        generated: dict[str, str] = {}
        for it in items:
            key = it.data(0, Qt.ItemDataRole.UserRole)
            ifc = it.data(1, Qt.ItemDataRole.UserRole)
            if not ifc:
                continue
            prefix = ifc["prefix"].upper()
            kind = ifc["kind"]
            if kind == "lite":
                src = generate_axi4_lite_monitor(prefix)
            elif kind == "full":
                src = generate_axi4_full_monitor(prefix)
            elif kind == "stream":
                src = generate_axis_monitor(prefix)
            else:
                continue
            self._monitors[key] = src
            generated[key] = src
            self._log.appendPlainText(f"[wrap] generated monitor for {key}")
        if generated:
            self.monitors_generated.emit(generated)
        self.refresh()

    def _remove_selected(self) -> None:
        for it in self._selected_items():
            key = it.data(0, Qt.ItemDataRole.UserRole)
            if key in self._monitors:
                del self._monitors[key]
                self._log.appendPlainText(f"[remove] dropped monitor {key}")
        self.refresh()

    def _run_sim(self) -> None:
        self._log.appendPlainText(
            "[sim] request emitted (wire this to the simulation runner)"
        )
        # Marker for parent to hook: write a flag on the widget
        self.setProperty("sim_requested", True)

    def ingest_assertion_line(self, line: str) -> None:
        """Hook for the simulation runner to feed live assertion output."""
        self._log.appendPlainText(line)

    def update_status(self, key: str, state: str, coverage: dict[str, int] | None = None) -> None:
        self._status[key] = {"state": state, "coverage": coverage or {}}
        self.refresh()


__all__ = ["AxiCheckerPanel"]
