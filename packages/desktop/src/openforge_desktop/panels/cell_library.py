"""Cell Library Browser dock widget."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QTreeWidget,
    QTreeWidgetItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QTextEdit,
    QPushButton,
    QAbstractItemView,
)

from openforge.pdk.manager import PdkManager
from openforge.pdk.liberty_parser import (
    parse_liberty,
    LibertyLibrary,
    LibertyCell,
)


# Catppuccin Mocha
_BG = "#1e1e2e"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_BLUE = "#89b4fa"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"


# ---------------------------------------------------------------------------
def _categorize(cell_name: str) -> str:
    name = cell_name.lower()
    # Strip library prefix like sky130_fd_sc_hd__
    if "__" in name:
        name = name.split("__", 1)[1]
    if name.startswith(("inv", "clkinv")):
        return "Inverters"
    if name.startswith(("buf", "clkbuf")):
        return "Buffers"
    if name.startswith(("dff", "sdff", "edff")) or "flop" in name:
        return "Sequential"
    if name.startswith(("dl", "latch")):
        return "Sequential"
    if name.startswith(("mux",)):
        return "Multiplexers"
    if name.startswith(("aoi", "oai")):
        return "Compound Gates"
    if name.startswith(("nand", "nor", "and", "or", "xor", "xnor")):
        return "Logic Gates"
    if any(name.startswith(p) for p in ("diode", "fill", "decap", "tap", "conb", "antenna")):
        return "Special"
    return "Other"


# ---------------------------------------------------------------------------
class _SchematicView(QWidget):
    """Draws a basic schematic of a cell from its function string."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cell: Optional[LibertyCell] = None
        self.setMinimumSize(280, 220)

    def set_cell(self, cell: Optional[LibertyCell]) -> None:
        self._cell = cell
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(_BG))
        if not self._cell:
            p.setPen(QColor(_TEXT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "(no cell selected)")
            return

        cell = self._cell
        # Pick output pin function
        out_pin = next(
            (pp for pp in cell.pins.values() if pp.direction == "output" and pp.function),
            None,
        )
        func = out_pin.function if out_pin else None

        pen = QPen(QColor(_BLUE), 2)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(_SURFACE)))

        cx = self.width() / 2
        cy = self.height() / 2

        if cell.is_sequential:
            self._draw_dff(p, cx, cy)
        elif func is None:
            self._draw_box(p, cx, cy, cell.name.split("__")[-1][:10])
        else:
            shape = self._classify_function(func)
            if shape == "inv":
                self._draw_inverter(p, cx, cy)
            elif shape == "and":
                self._draw_and(p, cx, cy, bubble=False)
            elif shape == "nand":
                self._draw_and(p, cx, cy, bubble=True)
            elif shape == "or":
                self._draw_or(p, cx, cy, bubble=False)
            elif shape == "nor":
                self._draw_or(p, cx, cy, bubble=True)
            elif shape == "xor":
                self._draw_xor(p, cx, cy, bubble=False)
            elif shape == "xnor":
                self._draw_xor(p, cx, cy, bubble=True)
            elif shape == "aoi":
                self._draw_aoi(p, cx, cy)
            else:
                self._draw_box(p, cx, cy, "FUNC")

        # Label
        p.setPen(QColor(_TEXT))
        p.setFont(QFont("Sans", 8))
        p.drawText(8, self.height() - 8, cell.name)
        if func:
            p.drawText(8, 16, f"Y = {func}")

    @staticmethod
    def _classify_function(func: str) -> str:
        f = func.replace(" ", "")
        # Determine pattern
        if re.fullmatch(r"\(?!\(?[A-Za-z0-9_]+\)?\)?", f) or re.fullmatch(r"!\w+", f):
            return "inv"
        has_and = "&" in f or "*" in f
        has_or = "|" in f or "+" in f
        has_xor = "^" in f
        leading_not = f.startswith("!") or f.startswith("(!")
        if has_and and has_or:
            return "aoi"
        if has_xor:
            return "xnor" if leading_not else "xor"
        if has_and:
            return "nand" if leading_not else "and"
        if has_or:
            return "nor" if leading_not else "or"
        return "box"

    # --- gate primitives ----------------------------------------------------
    def _draw_inverter(self, p: QPainter, cx: float, cy: float) -> None:
        path = QPainterPath()
        path.moveTo(cx - 40, cy - 30)
        path.lineTo(cx - 40, cy + 30)
        path.lineTo(cx + 25, cy)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QPointF(cx + 30, cy), 5, 5)
        p.drawLine(int(cx - 70), int(cy), int(cx - 40), int(cy))
        p.drawLine(int(cx + 35), int(cy), int(cx + 70), int(cy))

    def _draw_and(self, p: QPainter, cx: float, cy: float, bubble: bool) -> None:
        path = QPainterPath()
        path.moveTo(cx - 40, cy - 30)
        path.lineTo(cx, cy - 30)
        path.arcTo(QRectF(cx - 30, cy - 30, 60, 60), 90, -180)
        path.lineTo(cx - 40, cy + 30)
        path.closeSubpath()
        p.drawPath(path)
        if bubble:
            p.drawEllipse(QPointF(cx + 35, cy), 5, 5)
            p.drawLine(int(cx + 40), int(cy), int(cx + 70), int(cy))
        else:
            p.drawLine(int(cx + 30), int(cy), int(cx + 70), int(cy))
        p.drawLine(int(cx - 70), int(cy - 15), int(cx - 40), int(cy - 15))
        p.drawLine(int(cx - 70), int(cy + 15), int(cx - 40), int(cy + 15))

    def _draw_or(self, p: QPainter, cx: float, cy: float, bubble: bool) -> None:
        path = QPainterPath()
        path.moveTo(cx - 40, cy - 30)
        path.quadTo(cx - 20, cy, cx - 40, cy + 30)
        path.quadTo(cx, cy + 30, cx + 30, cy)
        path.quadTo(cx, cy - 30, cx - 40, cy - 30)
        p.drawPath(path)
        if bubble:
            p.drawEllipse(QPointF(cx + 35, cy), 5, 5)
            p.drawLine(int(cx + 40), int(cy), int(cx + 70), int(cy))
        else:
            p.drawLine(int(cx + 30), int(cy), int(cx + 70), int(cy))
        p.drawLine(int(cx - 70), int(cy - 15), int(cx - 30), int(cy - 15))
        p.drawLine(int(cx - 70), int(cy + 15), int(cx - 30), int(cy + 15))

    def _draw_xor(self, p: QPainter, cx: float, cy: float, bubble: bool) -> None:
        self._draw_or(p, cx + 5, cy, bubble)
        path = QPainterPath()
        path.moveTo(cx - 48, cy - 30)
        path.quadTo(cx - 28, cy, cx - 48, cy + 30)
        p.drawPath(path)

    def _draw_aoi(self, p: QPainter, cx: float, cy: float) -> None:
        # Two AND gates feeding into a NOR
        self._draw_and(p, cx - 50, cy - 30, bubble=False)
        self._draw_and(p, cx - 50, cy + 30, bubble=False)
        self._draw_or(p, cx + 40, cy, bubble=True)

    def _draw_dff(self, p: QPainter, cx: float, cy: float) -> None:
        rect = QRectF(cx - 50, cy - 45, 100, 90)
        p.drawRect(rect)
        p.setPen(QColor(_TEXT))
        p.drawText(QRectF(cx - 50, cy - 45, 100, 20), Qt.AlignmentFlag.AlignCenter, "DFF")
        p.drawText(QRectF(cx - 48, cy - 25, 30, 16), Qt.AlignmentFlag.AlignLeft, "D")
        p.drawText(QRectF(cx + 18, cy - 25, 30, 16), Qt.AlignmentFlag.AlignRight, "Q")
        p.drawText(QRectF(cx - 48, cy + 10, 30, 16), Qt.AlignmentFlag.AlignLeft, ">CLK")

    def _draw_box(self, p: QPainter, cx: float, cy: float, label: str) -> None:
        rect = QRectF(cx - 45, cy - 25, 90, 50)
        p.drawRect(rect)
        p.setPen(QColor(_TEXT))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


# ---------------------------------------------------------------------------
class CellLibraryPanel(QDockWidget):
    """Visual browser for standard cells from the active PDK."""

    cell_selected = Signal(str)
    insert_cell_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Cell Library")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._manager = PdkManager()
        self._library: Optional[LibertyLibrary] = None
        self._dark = True

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Top: pdk selector + library + search
        top = QHBoxLayout()
        top.addWidget(QLabel("PDK:"))
        self._pdk_combo = QComboBox()
        self._pdk_combo.currentIndexChanged.connect(self._on_pdk_changed)
        top.addWidget(self._pdk_combo)
        top.addWidget(QLabel("Lib:"))
        self._lib_combo = QComboBox()
        self._lib_combo.currentIndexChanged.connect(self._on_lib_changed)
        top.addWidget(self._lib_combo, 1)
        top.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter cells...")
        self._search.textChanged.connect(self._apply_search)
        top.addWidget(self._search, 1)
        layout.addLayout(top)

        # Splitter: tree | details
        splitter = QSplitter(Qt.Orientation.Horizontal, container)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Cell"])
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.itemSelectionChanged.connect(self._on_cell_selected)
        splitter.addWidget(self._tree)

        # Right details
        self._tabs = QTabWidget()

        # Properties tab
        self._props = QTextEdit()
        self._props.setReadOnly(True)
        self._tabs.addTab(self._props, "Properties")

        # Schematic tab
        self._schematic = _SchematicView()
        self._tabs.addTab(self._schematic, "Schematic")

        # Layout (placeholder)
        self._layout_label = QLabel("Layout view: load LEF for cell geometry.")
        self._layout_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabs.addTab(self._layout_label, "Layout")

        # Timing tab
        self._timing_table = QTableWidget(0, 4)
        self._timing_table.setHorizontalHeaderLabels(
            ["Related Pin", "Sense", "Rise (ps)", "Fall (ps)"]
        )
        self._timing_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._timing_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabs.addTab(self._timing_table, "Timing")

        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # Action row
        actions = QHBoxLayout()
        self._insert_btn = QPushButton("Insert into Editor")
        self._insert_btn.clicked.connect(self._on_insert)
        actions.addStretch(1)
        actions.addWidget(self._insert_btn)
        layout.addLayout(actions)

        self.setWidget(container)
        self.set_theme(True)
        self._populate_pdks()

    # ------------------------------------------------------------------
    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        bg = _BG if dark else "#eff1f5"
        surface = _SURFACE if dark else "#ccd0da"
        text = _TEXT if dark else "#4c4f69"
        self.setStyleSheet(
            f"""
            QDockWidget {{ color: {text}; }}
            QWidget {{ background-color: {bg}; color: {text}; }}
            QTreeWidget, QTableWidget, QTextEdit, QComboBox, QLineEdit {{
                background-color: {surface};
                color: {text};
                border: 1px solid {surface};
            }}
            QTabWidget::pane {{ border: 1px solid {surface}; background: {bg}; }}
            QTabBar::tab {{
                background: {surface}; color: {text};
                padding: 6px 12px; border: none;
            }}
            QTabBar::tab:selected {{ background: {_BLUE}; color: {_BG}; }}
            QHeaderView::section {{
                background-color: {surface}; color: {text};
                padding: 4px; border: none;
            }}
            QPushButton {{
                background-color: {surface}; color: {text};
                border: 1px solid {surface}; border-radius: 3px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{ background-color: {_BLUE}; color: {_BG}; }}
            """
        )

    # ------------------------------------------------------------------
    def _populate_pdks(self) -> None:
        self._pdk_combo.blockSignals(True)
        self._pdk_combo.clear()
        for info in self._manager.list_pdks():
            if info.installed:
                self._pdk_combo.addItem(info.display_name, info.name)
        self._pdk_combo.blockSignals(False)
        if self._pdk_combo.count() > 0:
            self._on_pdk_changed(0)

    def load_pdk(self, pdk_name: str) -> None:
        for i in range(self._pdk_combo.count()):
            if self._pdk_combo.itemData(i) == pdk_name:
                self._pdk_combo.setCurrentIndex(i)
                return
        # Not in combo: refresh
        self._manager.discover_local()
        self._populate_pdks()
        for i in range(self._pdk_combo.count()):
            if self._pdk_combo.itemData(i) == pdk_name:
                self._pdk_combo.setCurrentIndex(i)
                return

    def _on_pdk_changed(self, _idx: int) -> None:
        pdk_name = self._pdk_combo.currentData()
        if not pdk_name:
            return
        info = self._manager.get_pdk(pdk_name)
        if not info:
            return
        self._lib_combo.blockSignals(True)
        self._lib_combo.clear()
        for lib_name in info.cell_libraries:
            corners = info.corners.get(lib_name, [])
            if corners:
                self._lib_combo.addItem(lib_name, corners[0].liberty_file)
        self._lib_combo.blockSignals(False)
        if self._lib_combo.count() > 0:
            self._on_lib_changed(0)

    def _on_lib_changed(self, _idx: int) -> None:
        path = self._lib_combo.currentData()
        if isinstance(path, Path):
            self.load_library(path)

    def load_library(self, liberty_path: Path) -> None:
        try:
            self._library = parse_liberty(liberty_path)
        except Exception as exc:  # noqa: BLE001
            self._library = None
            self._props.setPlainText(f"Failed to parse {liberty_path}: {exc}")
            self._tree.clear()
            return
        self._populate_tree()

    # ------------------------------------------------------------------
    def _populate_tree(self) -> None:
        self._tree.clear()
        if not self._library:
            return
        groups: dict[str, QTreeWidgetItem] = {}
        for cell_name, _cell in sorted(self._library.cells.items()):
            cat = _categorize(cell_name)
            if cat not in groups:
                groups[cat] = QTreeWidgetItem(self._tree, [cat])
                groups[cat].setForeground(0, QColor(_BLUE))
            QTreeWidgetItem(groups[cat], [cell_name])
        self._tree.expandAll()
        self._apply_search(self._search.text())

    def _apply_search(self, text: str) -> None:
        text = text.lower().strip()
        for i in range(self._tree.topLevelItemCount()):
            grp = self._tree.topLevelItem(i)
            visible_children = 0
            for j in range(grp.childCount()):
                ch = grp.child(j)
                vis = (not text) or text in ch.text(0).lower()
                ch.setHidden(not vis)
                if vis:
                    visible_children += 1
            grp.setHidden(visible_children == 0)

    # ------------------------------------------------------------------
    def _on_cell_selected(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        item = items[0]
        if item.parent() is None:
            return  # group
        cell_name = item.text(0)
        if not self._library:
            return
        cell = self._library.cells.get(cell_name)
        if not cell:
            return
        self._show_cell(cell)
        self.cell_selected.emit(cell_name)

    def _show_cell(self, cell: LibertyCell) -> None:
        # Properties text
        lines = [
            f"Name:    {cell.name}",
            f"Area:    {cell.area:.4f}",
            f"Leakage: {cell.leakage_power:.4g}",
            f"Type:    {'Sequential' if cell.is_sequential else 'Combinational'}",
            "",
            "Pins:",
        ]
        for pin in cell.pins.values():
            extra = []
            if pin.function:
                extra.append(f"function={pin.function}")
            if pin.capacitance:
                extra.append(f"cap={pin.capacitance:.4g}")
            extra_s = "  " + ", ".join(extra) if extra else ""
            lines.append(f"  {pin.direction:6s} {pin.name}{extra_s}")
        self._props.setPlainText("\n".join(lines))

        self._schematic.set_cell(cell)

        # Timing
        self._timing_table.setRowCount(0)
        for arc in cell.timing_arcs:
            row = self._timing_table.rowCount()
            self._timing_table.insertRow(row)
            self._timing_table.setItem(row, 0, QTableWidgetItem(arc.related_pin))
            self._timing_table.setItem(row, 1, QTableWidgetItem(arc.sense))
            self._timing_table.setItem(
                row, 2, QTableWidgetItem(f"{arc.delay_rise_typ * 1000:.2f}")
            )
            self._timing_table.setItem(
                row, 3, QTableWidgetItem(f"{arc.delay_fall_typ * 1000:.2f}")
            )

    def _on_insert(self) -> None:
        items = self._tree.selectedItems()
        if not items or items[0].parent() is None:
            return
        self.insert_cell_requested.emit(items[0].text(0))
