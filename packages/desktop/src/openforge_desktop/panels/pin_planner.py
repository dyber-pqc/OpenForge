"""Interactive FPGA pin planner with package view and constraint I/O.

``PinPlannerPanel`` provides a three-pane interface:

1. **Net list** (left) -- top-level ports discovered in the current RTL,
   drag-droppable onto package pins.
2. **Package view** (center) -- a ``QGraphicsView`` rendering the physical
   package (BGA grid, QFP four-side rows, QFN / LGA). Pins are clickable
   with hover tooltips and voltage-bank color coding.
3. **Pin table** (right/bottom) -- editable table with columns
   Pin, Bank, Net, Direction, IO Standard, Drive, Slew, Pull.

The panel reads / writes :class:`ConstraintSet` models via the format
writers in :mod:`openforge.constraints.model` and supports importing
XDC / LPF / PCF / CST files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.constraints.model import (
        Constraint,
        ConstraintKind,
        ConstraintSet,
    )
    from openforge.fpga.boards import (
        Board,
        BoardFormat,
        get_board,
        list_boards,
    )

    _HAS_CORE = True
except Exception:  # pragma: no cover - core may not be installed
    Constraint = ConstraintKind = ConstraintSet = None  # type: ignore[assignment,misc]
    Board = BoardFormat = None  # type: ignore[assignment,misc]

    def get_board(name: str):  # type: ignore[misc]
        return None

    def list_boards():  # type: ignore[misc]
        return []

    _HAS_CORE = False

try:
    from openforge_desktop.theme.design_system import (
        DARK_PALETTE,
        get_layer_color,
        get_palette,
        status_color,
    )

    _PAL = get_palette(dark=True)
except Exception:  # pragma: no cover
    DARK_PALETTE = None  # type: ignore[assignment]
    _PAL = None

    def get_layer_color(name: str, palette: Any = None) -> str:  # type: ignore[misc]
        return "#89b4fa"

    def status_color(name: str, palette: Any = None) -> str:  # type: ignore[misc]
        return "#a6e3a1"


# ─────────────────────────────────────────────────────────────────────────────
# IO standards / drive / slew catalogs
# ─────────────────────────────────────────────────────────────────────────────


IO_STANDARDS: list[str] = [
    "LVCMOS12",
    "LVCMOS15",
    "LVCMOS18",
    "LVCMOS25",
    "LVCMOS33",
    "LVTTL",
    "LVDS",
    "LVDS_25",
    "SSTL12",
    "SSTL15",
    "SSTL18_I",
    "SSTL18_II",
    "HSTL_I",
    "HSTL_II",
    "POD12",
    "DIFF_SSTL15",
    "DIFF_HSTL_I",
]

DRIVE_STRENGTHS: list[str] = ["2", "4", "6", "8", "12", "16", "24"]
SLEW_RATES: list[str] = ["SLOW", "FAST"]
PULL_TYPES: list[str] = ["NONE", "UP", "DOWN", "KEEPER"]
DIRECTIONS: list[str] = ["input", "output", "inout"]

# Voltage bank colors (Catppuccin Mocha accent colors)
_BANK_COLORS: dict[str, str] = {
    "3.3V": "#89b4fa",  # blue
    "2.5V": "#a6e3a1",  # green
    "1.8V": "#f9e2af",  # yellow
    "1.5V": "#fab387",  # peach
    "1.2V": "#f38ba8",  # red
    "VCCIO": "#cba6f7",  # mauve
    "VCCAUX": "#94e2d5",  # teal
    "GND": "#6c7086",
    "NC": "#45475a",
}

_BG = "#1e1e2e"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_ACCENT = "#00d4ff"  # Dyber Blue


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PinInfo:
    """Information about a single physical package pin."""

    name: str
    row: int = 0
    col: int = 0
    bank: str = ""
    voltage: str = "3.3V"
    function: str = ""  # VCCIO / GND / NC / IO / CLK / ...
    assigned_net: str = ""
    io_standard: str = "LVCMOS33"
    direction: str = "input"
    drive: str = "8"
    slew: str = "SLOW"
    pull: str = "NONE"


@dataclass
class PackageGeometry:
    """Layout description for a package type."""

    kind: str  # "BGA", "QFP", "QFN", "LGA"
    rows: int = 0
    cols: int = 0
    pins: list[PinInfo] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Package geometry builders
# ─────────────────────────────────────────────────────────────────────────────


def _bga_label(row: int, col: int) -> str:
    # BGA labels: A-Z, skipping I, O, Q, S, X, Z (JEDEC)
    letters = "ABCDEFGHJKLMNPRTUVWY"
    if row < len(letters):
        prefix = letters[row]
    else:
        prefix = letters[row // len(letters) - 1] + letters[row % len(letters)]
    return f"{prefix}{col + 1}"


def build_bga(rows: int, cols: int) -> PackageGeometry:
    g = PackageGeometry(kind="BGA", rows=rows, cols=cols)
    for r in range(rows):
        for c in range(cols):
            name = _bga_label(r, c)
            # simple voltage banding: outer ring 3.3V, inner 1.8V
            if r == 0 or c == 0 or r == rows - 1 or c == cols - 1:
                v = "3.3V"
                bank = "0"
            else:
                v = "1.8V"
                bank = "1"
            g.pins.append(PinInfo(name=name, row=r, col=c, bank=bank, voltage=v))
    return g


def build_qfp(pins_per_side: int) -> PackageGeometry:
    g = PackageGeometry(kind="QFP", rows=pins_per_side, cols=pins_per_side)
    idx = 1
    # Bottom side (left-to-right)
    for i in range(pins_per_side):
        g.pins.append(PinInfo(name=str(idx), row=pins_per_side, col=i, bank="S", voltage="3.3V"))
        idx += 1
    # Right side (bottom-to-top)
    for i in range(pins_per_side):
        g.pins.append(
            PinInfo(
                name=str(idx), row=pins_per_side - i, col=pins_per_side, bank="E", voltage="3.3V"
            )
        )
        idx += 1
    # Top side (right-to-left)
    for i in range(pins_per_side):
        g.pins.append(
            PinInfo(name=str(idx), row=0, col=pins_per_side - i, bank="N", voltage="3.3V")
        )
        idx += 1
    # Left side (top-to-bottom)
    for i in range(pins_per_side):
        g.pins.append(PinInfo(name=str(idx), row=i, col=0, bank="W", voltage="3.3V"))
        idx += 1
    return g


def build_qfn(pins_per_side: int) -> PackageGeometry:
    g = build_qfp(pins_per_side)
    g.kind = "QFN"
    return g


def build_lga(rows: int, cols: int) -> PackageGeometry:
    g = build_bga(rows, cols)
    g.kind = "LGA"
    return g


def _geometry_for_board(board: Any) -> PackageGeometry:
    """Best-effort geometry builder for a Board's package string."""
    if board is None:
        return build_bga(10, 10)
    pkg = str(getattr(board, "package", "")).upper()
    if "BGA" in pkg or "CABGA" in pkg or "PBGA" in pkg or pkg.startswith("CM"):
        # Extract pin count if possible
        digits = "".join(ch for ch in pkg if ch.isdigit())
        n = int(digits) if digits else 256
        # Round up to next square
        side = max(4, int(n**0.5 + 0.999))
        return build_bga(side, side)
    if "QFP" in pkg:
        digits = "".join(ch for ch in pkg if ch.isdigit())
        n = int(digits) if digits else 100
        return build_qfp(max(4, n // 4))
    if "QFN" in pkg or pkg.startswith("SG"):
        digits = "".join(ch for ch in pkg if ch.isdigit())
        n = int(digits) if digits else 48
        return build_qfn(max(4, n // 4))
    if "UWG" in pkg or "LGA" in pkg:
        digits = "".join(ch for ch in pkg if ch.isdigit())
        n = int(digits) if digits else 30
        side = max(4, int(n**0.5 + 0.999))
        return build_lga(side, side)
    return build_bga(10, 10)


# ─────────────────────────────────────────────────────────────────────────────
# Graphics item
# ─────────────────────────────────────────────────────────────────────────────


class PinItem(QGraphicsEllipseItem):
    """Clickable / hover-aware ellipse representing one pin."""

    SIZE = 22.0

    def __init__(self, pin: PinInfo, x: float, y: float, panel: PinPlannerPanel):
        super().__init__(QRectF(x, y, self.SIZE, self.SIZE))
        self.pin = pin
        self.panel = panel
        self.setAcceptHoverEvents(True)
        self.setAcceptDrops(True)
        self.setToolTip(self._tooltip())
        self._apply_color()

    def _tooltip(self) -> str:
        return (
            f"Pin: {self.pin.name}\n"
            f"Bank: {self.pin.bank}\n"
            f"Voltage: {self.pin.voltage}\n"
            f"Net: {self.pin.assigned_net or '(unassigned)'}\n"
            f"IO: {self.pin.io_standard}"
        )

    def _apply_color(self) -> None:
        base = _BANK_COLORS.get(self.pin.voltage, "#89b4fa")
        col = QColor(base)
        if self.pin.assigned_net:
            col = QColor(_ACCENT)
        self.setBrush(QBrush(col))
        self.setPen(QPen(QColor("#181825"), 1.5))

    def hoverEnterEvent(self, event):  # noqa: N802 (Qt override)
        self.setPen(QPen(QColor(_ACCENT), 2.5))
        self.setToolTip(self._tooltip())
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):  # noqa: N802
        self.setPen(QPen(QColor("#181825"), 1.5))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        self.panel._on_pin_clicked(self.pin)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        if event.mimeData().hasText():
            net = event.mimeData().text()
            self.panel.assign_net_to_pin(net, self.pin.name)
            event.acceptProposedAction()

    def refresh(self) -> None:
        self._apply_color()
        self.setToolTip(self._tooltip())


class PackageView(QGraphicsView):
    """Graphics view rendering the package and its pins."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setBackgroundBrush(QBrush(QColor(_BG)))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._pin_items: dict[str, PinItem] = {}

    def load(self, geom: PackageGeometry, panel: PinPlannerPanel) -> None:
        self._scene.clear()
        self._pin_items.clear()
        spacing = PinItem.SIZE + 10.0
        margin = 40.0

        # Body rectangle
        if geom.kind in ("BGA", "LGA"):
            w = geom.cols * spacing + 2 * margin
            h = geom.rows * spacing + 2 * margin
        else:  # QFP / QFN
            w = (geom.cols + 1) * spacing + 2 * margin
            h = (geom.rows + 1) * spacing + 2 * margin

        body = QGraphicsRectItem(0, 0, w, h)
        body.setBrush(QBrush(QColor(_SURFACE)))
        body.setPen(QPen(QColor("#45475a"), 2))
        self._scene.addItem(body)

        # Pin 1 marker (dot in top-left)
        marker = QGraphicsEllipseItem(margin / 2, margin / 2, 8, 8)
        marker.setBrush(QBrush(QColor(_ACCENT)))
        marker.setPen(QPen(Qt.PenStyle.NoPen))
        self._scene.addItem(marker)

        for p in geom.pins:
            x = margin + p.col * spacing
            y = margin + p.row * spacing
            item = PinItem(p, x, y, panel)
            self._scene.addItem(item)
            self._pin_items[p.name] = item

            # Label
            label = QGraphicsSimpleTextItem(p.name)
            label.setBrush(QBrush(QColor(_TEXT)))
            f = QFont()
            f.setPointSize(6)
            label.setFont(f)
            lr = label.boundingRect()
            label.setPos(
                x + PinItem.SIZE / 2 - lr.width() / 2,
                y + PinItem.SIZE + 1,
            )
            self._scene.addItem(label)

        self._scene.setSceneRect(-margin, -margin, w + 2 * margin, h + 2 * margin)

    def refresh_pin(self, pin_name: str) -> None:
        item = self._pin_items.get(pin_name)
        if item is not None:
            item.refresh()

    def refresh_all(self) -> None:
        for item in self._pin_items.values():
            item.refresh()

    def wheelEvent(self, event):  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


# ─────────────────────────────────────────────────────────────────────────────
# Table delegates
# ─────────────────────────────────────────────────────────────────────────────


class _ComboDelegate(QStyledItemDelegate):
    def __init__(self, items: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._items = items

    def createEditor(self, parent, option, index):  # noqa: N802
        cb = QComboBox(parent)
        cb.addItems(self._items)
        cb.setEditable(True)
        return cb

    def setEditorData(self, editor, index):  # noqa: N802
        val = index.data(Qt.ItemDataRole.EditRole) or ""
        i = editor.findText(str(val))
        if i >= 0:
            editor.setCurrentIndex(i)
        else:
            editor.setEditText(str(val))

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


# ─────────────────────────────────────────────────────────────────────────────
# Main panel
# ─────────────────────────────────────────────────────────────────────────────


class PinPlannerPanel(QDockWidget):
    """Dock-widget wrapper so the pin planner behaves like other OpenForge panels."""

    netsAssigned = Signal(str, str)  # net, pin
    constraintsChanged = Signal()

    COL_PIN = 0
    COL_BANK = 1
    COL_NET = 2
    COL_DIR = 3
    COL_STD = 4
    COL_DRIVE = 5
    COL_SLEW = 6
    COL_PULL = 7

    _HEADERS = [
        "Pin",
        "Bank",
        "Net",
        "Direction",
        "IO Standard",
        "Drive",
        "Slew",
        "Pull",
    ]

    def __init__(self, title: str = "Pin Planner", parent: QWidget | None = None):
        super().__init__(title, parent)
        self.setObjectName("pin_planner_dock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._geom: PackageGeometry = build_bga(10, 10)
        self._pins_by_name: dict[str, PinInfo] = {}
        self._board: Any = None

        self._build_ui()
        self._populate_pins_from_geom()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setStyleSheet(f"QWidget {{ background-color: {_BG}; color: {_TEXT}; }}")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Toolbar
        tb = QToolBar(root)
        tb.setStyleSheet(
            f"QToolBar {{ background: {_SURFACE}; border: none; }}"
            f"QToolButton {{ color: {_TEXT}; padding: 4px 8px; }}"
            f"QToolButton:hover {{ background: {_ACCENT}; color: #000; }}"
        )
        self._board_combo = QComboBox(tb)
        self._board_combo.addItem("(custom)")
        for b in list_boards():
            self._board_combo.addItem(b.name)
        self._board_combo.currentTextChanged.connect(self._on_board_changed)
        tb.addWidget(QLabel("Board: "))
        tb.addWidget(self._board_combo)
        tb.addSeparator()
        tb.addAction("Import", self._on_import)
        tb.addAction("Export XDC", lambda: self._on_export("xdc"))
        tb.addAction("Export LPF", lambda: self._on_export("lpf"))
        tb.addAction("Export PCF", lambda: self._on_export("pcf"))
        tb.addAction("Export CST", lambda: self._on_export("cst"))
        tb.addSeparator()
        self._filter_edit = QLineEdit(tb)
        self._filter_edit.setPlaceholderText("Filter by bank / voltage / net…")
        self._filter_edit.setMaximumWidth(260)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        tb.addWidget(self._filter_edit)
        outer.addWidget(tb)

        # Horizontal splitter: [nets] [package view] [table]
        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.setChildrenCollapsible(False)

        # Net list
        self._net_tree = QTreeWidget(splitter)
        self._net_tree.setHeaderLabel("Top-level Ports")
        self._net_tree.setDragEnabled(True)
        self._net_tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._net_tree.setStyleSheet(
            f"QTreeWidget {{ background:{_SURFACE}; color:{_TEXT}; border:1px solid #45475a; }}"
            f"QTreeWidget::item:selected {{ background:{_ACCENT}; color:#000; }}"
        )
        self._net_tree.itemDoubleClicked.connect(self._on_net_double_clicked)
        splitter.addWidget(self._net_tree)

        # Package view
        self._pkg_view = PackageView(splitter)
        splitter.addWidget(self._pkg_view)

        # Pin table
        self._table = QTableWidget(0, len(self._HEADERS), splitter)
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setStyleSheet(
            f"QTableWidget {{ background:{_SURFACE}; color:{_TEXT};"
            f" gridline-color:#45475a; alternate-background-color:#1a1a2e; }}"
            f"QHeaderView::section {{ background:#181825; color:{_TEXT};"
            f" padding:4px; border:1px solid #45475a; }}"
        )
        self._table.setItemDelegateForColumn(
            self.COL_STD, _ComboDelegate(IO_STANDARDS, self._table)
        )
        self._table.setItemDelegateForColumn(
            self.COL_DRIVE, _ComboDelegate(DRIVE_STRENGTHS, self._table)
        )
        self._table.setItemDelegateForColumn(self.COL_SLEW, _ComboDelegate(SLEW_RATES, self._table))
        self._table.setItemDelegateForColumn(self.COL_PULL, _ComboDelegate(PULL_TYPES, self._table))
        self._table.setItemDelegateForColumn(self.COL_DIR, _ComboDelegate(DIRECTIONS, self._table))
        self._table.itemChanged.connect(self._on_table_changed)
        splitter.addWidget(self._table)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        outer.addWidget(splitter, 1)

        # Status bar
        self._status = QLabel("Ready", root)
        self._status.setStyleSheet(f"color:{_TEXT}; padding:2px 6px;")
        outer.addWidget(self._status)

        self.setWidget(root)

    # ── Board / package management ─────────────────────────────────────────

    def set_board(self, board_name: str) -> None:
        board = get_board(board_name) if _HAS_CORE else None
        if board is None:
            self._board = None
            return
        self._board = board
        self._geom = _geometry_for_board(board)
        self._populate_pins_from_geom()
        # Load default constraint set
        cs = board.default_constraint_set()
        self.load_constraint_set(cs)
        self._status.setText(f"Loaded {board.name} ({board.device}, {board.package})")

    def _on_board_changed(self, name: str) -> None:
        if name and name != "(custom)":
            self.set_board(name)

    def _populate_pins_from_geom(self) -> None:
        self._pins_by_name = {p.name: p for p in self._geom.pins}
        self._pkg_view.load(self._geom, self)
        self._refresh_table()

    # ── Net list ───────────────────────────────────────────────────────────

    def set_nets(self, nets: list[str]) -> None:
        """Populate the left-hand port list from RTL top-level."""
        self._net_tree.clear()
        for n in nets:
            QTreeWidgetItem(self._net_tree, [n])

    def _on_net_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        # Assign to currently selected row in table
        row = self._table.currentRow()
        if row < 0:
            return
        pin_item = self._table.item(row, self.COL_PIN)
        if pin_item is None:
            return
        self.assign_net_to_pin(item.text(0), pin_item.text())

    # ── Pin operations ─────────────────────────────────────────────────────

    def _on_pin_clicked(self, pin: PinInfo) -> None:
        # Select the row in the table
        for r in range(self._table.rowCount()):
            it = self._table.item(r, self.COL_PIN)
            if it is not None and it.text() == pin.name:
                self._table.selectRow(r)
                self._table.scrollToItem(it)
                break
        self._status.setText(
            f"Pin {pin.name} -- bank {pin.bank} ({pin.voltage}) -- "
            f"net={pin.assigned_net or '(none)'}"
        )

    def assign_net_to_pin(self, net: str, pin_name: str) -> None:
        pin = self._pins_by_name.get(pin_name)
        if pin is None:
            return
        pin.assigned_net = net
        self._pkg_view.refresh_pin(pin_name)
        self._refresh_table()
        self._check_conflicts()
        self.netsAssigned.emit(net, pin_name)
        self.constraintsChanged.emit()

    # ── Table management ───────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        filt = (
            (self._filter_edit.text() or "").strip().lower()
            if hasattr(self, "_filter_edit")
            else ""
        )
        for p in self._geom.pins:
            if filt:
                hay = f"{p.name} {p.bank} {p.voltage} {p.assigned_net}".lower()
                if filt not in hay:
                    continue
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, self.COL_PIN, QTableWidgetItem(p.name))
            self._table.item(r, self.COL_PIN).setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            )
            self._table.setItem(r, self.COL_BANK, QTableWidgetItem(p.bank))
            self._table.item(r, self.COL_BANK).setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            )
            self._table.setItem(r, self.COL_NET, QTableWidgetItem(p.assigned_net))
            self._table.setItem(r, self.COL_DIR, QTableWidgetItem(p.direction))
            self._table.setItem(r, self.COL_STD, QTableWidgetItem(p.io_standard))
            self._table.setItem(r, self.COL_DRIVE, QTableWidgetItem(p.drive))
            self._table.setItem(r, self.COL_SLEW, QTableWidgetItem(p.slew))
            self._table.setItem(r, self.COL_PULL, QTableWidgetItem(p.pull))
        self._table.blockSignals(False)
        self._check_conflicts()

    def _on_table_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        pin_name_item = self._table.item(row, self.COL_PIN)
        if pin_name_item is None:
            return
        pin = self._pins_by_name.get(pin_name_item.text())
        if pin is None:
            return
        col = item.column()
        text = item.text()
        if col == self.COL_NET:
            pin.assigned_net = text
        elif col == self.COL_DIR:
            pin.direction = text
        elif col == self.COL_STD:
            pin.io_standard = text
        elif col == self.COL_DRIVE:
            pin.drive = text
        elif col == self.COL_SLEW:
            pin.slew = text
        elif col == self.COL_PULL:
            pin.pull = text
        self._pkg_view.refresh_pin(pin.name)
        self._check_conflicts()
        self.constraintsChanged.emit()

    def _on_filter_changed(self, _text: str) -> None:
        self._refresh_table()

    # ── Conflict highlighter ───────────────────────────────────────────────

    def _check_conflicts(self) -> None:
        """Highlight bank rows whose IO standards are incompatible."""
        bank_stds: dict[str, set[str]] = {}
        for p in self._geom.pins:
            if p.assigned_net:
                bank_stds.setdefault(p.bank, set()).add(p.io_standard)
        bad_banks: set[str] = set()
        for bank, stds in bank_stds.items():
            voltages: set[str] = set()
            for s in stds:
                voltages.add(_io_voltage(s))
            if len(voltages - {""}) > 1:
                bad_banks.add(bank)

        red = QBrush(QColor("#f38ba8"))
        clear = QBrush(QColor("#00000000"))
        for r in range(self._table.rowCount()):
            bank_item = self._table.item(r, self.COL_BANK)
            if bank_item is None:
                continue
            if bank_item.text() in bad_banks:
                bank_item.setBackground(red)
                bank_item.setToolTip(f"Bank {bank_item.text()}: mixed IO voltage standards")
            else:
                bank_item.setBackground(clear)
                bank_item.setToolTip("")

    # ── Import / export ────────────────────────────────────────────────────

    def _on_import(self) -> None:
        if not _HAS_CORE:
            QMessageBox.warning(self, "Pin Planner", "openforge.constraints not available")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import constraint file",
            "",
            "Constraints (*.xdc *.lpf *.pcf *.cst *.sdc);;All files (*)",
        )
        if not path:
            return
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        ext = p.suffix.lower()
        try:
            if ext == ".xdc":
                cs = ConstraintSet.from_xdc(text, name=p.stem)
            elif ext == ".lpf":
                cs = ConstraintSet.from_lpf(text, name=p.stem)
            elif ext == ".pcf":
                cs = ConstraintSet.from_pcf(text, name=p.stem)
            elif ext == ".cst":
                cs = ConstraintSet.from_cst(text, name=p.stem)
            else:
                cs = ConstraintSet.from_sdc(text, name=p.stem)
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.load_constraint_set(cs)
        self._status.setText(f"Imported {len(cs.constraints)} constraints from {p.name}")

    def _on_export(self, fmt: str) -> None:
        if not _HAS_CORE:
            return
        cs = self.build_constraint_set()
        suffix = {"xdc": ".xdc", "lpf": ".lpf", "pcf": ".pcf", "cst": ".cst"}.get(fmt, ".sdc")
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", f"constraints{suffix}", f"*{suffix}"
        )
        if not path:
            return
        try:
            if fmt == "xdc":
                text = cs.to_xdc()
            elif fmt == "lpf":
                text = cs.to_lpf()
            elif fmt == "pcf":
                text = cs.to_pcf()
            elif fmt == "cst":
                text = cs.to_cst()
            else:
                text = cs.to_sdc()
            Path(path).write_text(text, encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._status.setText(f"Exported {fmt.upper()}: {path}")

    # ── ConstraintSet bridge ───────────────────────────────────────────────

    def build_constraint_set(self, name: str = "pin_planner") -> Any:
        if not _HAS_CORE:
            return None
        cs = ConstraintSet(name=name)
        for p in self._geom.pins:
            if not p.assigned_net:
                continue
            cs.add(
                Constraint(
                    kind=ConstraintKind.PIN_LOCATION,
                    target=p.assigned_net,
                    value=p.name,
                )
            )
            cs.add(
                Constraint(
                    kind=ConstraintKind.IO_STANDARD,
                    target=p.assigned_net,
                    value=p.io_standard,
                )
            )
            if p.drive:
                cs.add(
                    Constraint(
                        kind=ConstraintKind.DRIVE_STRENGTH,
                        target=p.assigned_net,
                        value=p.drive,
                    )
                )
            if p.slew:
                cs.add(
                    Constraint(
                        kind=ConstraintKind.SLEW_RATE,
                        target=p.assigned_net,
                        value=p.slew,
                    )
                )
            if p.pull and p.pull.upper() != "NONE":
                cs.add(
                    Constraint(
                        kind=ConstraintKind.PULL,
                        target=p.assigned_net,
                        value=p.pull,
                    )
                )
        return cs

    def load_constraint_set(self, cs: Any) -> None:
        if not _HAS_CORE or cs is None:
            return
        # Build map from constraints: net -> pin info
        for c in cs.constraints:
            if c.kind == ConstraintKind.PIN_LOCATION:
                net = c.target
                pin_name = str(c.value)
                pin = self._pins_by_name.get(pin_name)
                if pin is None:
                    # Create a synthetic pin so it's visible
                    pin = PinInfo(name=pin_name)
                    self._pins_by_name[pin_name] = pin
                    self._geom.pins.append(pin)
                pin.assigned_net = net
            elif c.kind == ConstraintKind.IO_STANDARD:
                for p in self._find_pins_for_net(c.target):
                    p.io_standard = str(c.value)
            elif c.kind == ConstraintKind.DRIVE_STRENGTH:
                for p in self._find_pins_for_net(c.target):
                    p.drive = str(c.value)
            elif c.kind == ConstraintKind.SLEW_RATE:
                for p in self._find_pins_for_net(c.target):
                    p.slew = str(c.value)
            elif c.kind == ConstraintKind.PULL:
                for p in self._find_pins_for_net(c.target):
                    p.pull = str(c.value)
        self._pkg_view.refresh_all()
        self._refresh_table()

    def _find_pins_for_net(self, net: str) -> list[PinInfo]:
        return [p for p in self._geom.pins if p.assigned_net == net]


# ─────────────────────────────────────────────────────────────────────────────
# IO-standard voltage decoder (for conflict detection)
# ─────────────────────────────────────────────────────────────────────────────


def _io_voltage(std: str) -> str:
    """Return the rail voltage implied by an IO standard name."""
    s = std.upper()
    if "33" in s:
        return "3.3"
    if "25" in s:
        return "2.5"
    if "18" in s:
        return "1.8"
    if "15" in s:
        return "1.5"
    if "12" in s:
        return "1.2"
    if "LVDS" in s:
        return "2.5"
    return ""


__all__ = ["PinPlannerPanel", "PackageView", "PinItem", "PinInfo", "PackageGeometry"]
