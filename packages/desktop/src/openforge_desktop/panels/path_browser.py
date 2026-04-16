"""Timing path browser dock widget.

A full-featured browser for STA timing paths with cell-by-cell navigation,
slack coloring, and cross-probing into the layout viewer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen

if TYPE_CHECKING:
    from openforge.physical.sta_parser import StaReport, TimingPath, TimingStage
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

_CLEAN = "\u2713"  # checkmark
_VIOL = "\u2717"  # cross


def _slack_color(slack: float, dark: bool) -> QColor:
    """Pick a color for a slack value: red for violated, yellow for marginal, green for met."""
    if slack < 0:
        return QColor("#e74c3c")
    if slack < 0.5:
        return QColor("#f39c12")
    return QColor("#2ecc71") if dark else QColor("#27ae60")


def _format_ns(v: float) -> str:
    return f"{v:+.3f} ns"


# ---------------------------------------------------------------------------
# Path bar visualization widget
# ---------------------------------------------------------------------------


class PathBarWidget(QFrame):
    """Horizontal bar showing each cell as a colored block scaled by delay."""

    cell_clicked = Signal(int)  # stage index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stages: list[dict] = []
        self._dark = True
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMouseTracking(True)
        self._hover_index = -1

    def set_stages(self, stages: list[dict]) -> None:
        self._stages = list(stages)
        self.update()

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#1e1e1e") if self._dark else QColor("#f5f5f5")
        painter.fillRect(self.rect(), bg)

        if not self._stages:
            painter.setPen(QPen(QColor("#888888")))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No path selected")
            return

        margin = 8
        usable_w = self.width() - 2 * margin
        h = self.height() - 2 * margin
        total_delay = sum(max(0.001, s.get("delay", 0.0)) for s in self._stages)
        if total_delay <= 0:
            return

        x = margin
        for i, stage in enumerate(self._stages):
            delay = max(0.001, stage.get("delay", 0.0))
            w = max(8.0, (delay / total_delay) * usable_w)
            color = self._stage_color(stage, i)
            if i == self._hover_index:
                color = color.lighter(130)
            painter.fillRect(int(x), margin, int(w), h, color)
            painter.setPen(QPen(QColor("#000000") if not self._dark else QColor("#ffffff")))
            painter.drawRect(int(x), margin, int(w), h)
            # Label
            cell_type = stage.get("type", "?")
            if w > 36:
                f = QFont()
                f.setPointSize(8)
                painter.setFont(f)
                painter.drawText(
                    int(x) + 2,
                    margin,
                    int(w) - 4,
                    h,
                    Qt.AlignmentFlag.AlignCenter,
                    cell_type,
                )
            x += w

    def _stage_color(self, stage: dict, idx: int) -> QColor:
        ctype = stage.get("type", "").upper()
        if "FF" in ctype or "LATCH" in ctype:
            return QColor("#3498db")
        if "BUF" in ctype or "INV" in ctype:
            return QColor("#9b59b6")
        if "AND" in ctype or "OR" in ctype or "XOR" in ctype:
            return QColor("#1abc9c")
        if "MUX" in ctype:
            return QColor("#e67e22")
        palette = ["#34495e", "#16a085", "#2980b9", "#8e44ad", "#27ae60"]
        return QColor(palette[idx % len(palette)])

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = self._hit_test(event.position().x())
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()
            if idx >= 0 and idx < len(self._stages):
                stage = self._stages[idx]
                self.setToolTip(
                    f"{stage.get('cell', '')}\n"
                    f"Type: {stage.get('type', '')}\n"
                    f"Pin: {stage.get('pin', '')}\n"
                    f"Delay: {stage.get('delay', 0):.3f} ns\n"
                    f"Cumulative: {stage.get('cumulative', 0):.3f} ns"
                )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        idx = self._hit_test(event.position().x())
        if idx >= 0:
            self.cell_clicked.emit(idx)

    def _hit_test(self, x: float) -> int:
        if not self._stages:
            return -1
        margin = 8
        usable_w = self.width() - 2 * margin
        total_delay = sum(max(0.001, s.get("delay", 0.0)) for s in self._stages)
        if total_delay <= 0:
            return -1
        cur = margin
        for i, stage in enumerate(self._stages):
            delay = max(0.001, stage.get("delay", 0.0))
            w = max(8.0, (delay / total_delay) * usable_w)
            if cur <= x <= cur + w:
                return i
            cur += w
        return -1


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class PathBrowserPanel(QDockWidget):
    """QDockWidget for browsing timing paths with cell-level navigation."""

    cell_selected = Signal(str)  # cell instance name
    layout_navigate_requested = Signal(float, float)  # (x, y) in um
    path_selected = Signal(dict)
    source_navigate = Signal(str)  # startpoint identifier for RTL editor jump

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Timing Paths")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._paths: list[dict] = []
        self._current_path: dict | None = None
        self._report: StaReport | None = None
        self._dark = True

        self._build_ui()
        self._wire()
        self.set_theme(True)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # Top toolbar
        self._toolbar = QToolBar("Path Filters")
        self._toolbar.setIconSize(self._toolbar.iconSize())

        self._toolbar.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Setup", "Hold", "Both"])
        self._toolbar.addWidget(self.type_combo)

        self._toolbar.addSeparator()
        self._toolbar.addWidget(QLabel("Slack <"))
        self.slack_filter = QDoubleSpinBox()
        self.slack_filter.setRange(-1000.0, 1000.0)
        self.slack_filter.setValue(1000.0)
        self.slack_filter.setSuffix(" ns")
        self.slack_filter.setSingleStep(0.1)
        self._toolbar.addWidget(self.slack_filter)

        self._toolbar.addSeparator()
        self._toolbar.addWidget(QLabel("Group by:"))
        self.group_combo = QComboBox()
        self.group_combo.addItems(["Clock", "Endpoint", "None"])
        self._toolbar.addWidget(self.group_combo)

        self._toolbar.addSeparator()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search endpoints...")
        self.search.setMaximumWidth(220)
        self._toolbar.addWidget(self.search)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setText("Refresh")
        self._toolbar.addWidget(self.refresh_btn)

        self.critical_btn = QToolButton()
        self.critical_btn.setText("Critical Path")
        self.critical_btn.setToolTip("Jump to the worst-slack path")
        self._toolbar.addWidget(self.critical_btn)

        root_layout.addWidget(self._toolbar)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: tree of paths
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Endpoint", "Slack", "Delay", "Stages"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setMinimumWidth(360)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.tree)

        # Right: detail
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)

        # Header info
        header_box = QFrame()
        header_box.setFrameShape(QFrame.Shape.StyledPanel)
        hb = QHBoxLayout(header_box)
        hb.setContentsMargins(8, 8, 8, 8)
        self.lbl_endpoint = QLabel("No path selected")
        f = QFont()
        f.setBold(True)
        self.lbl_endpoint.setFont(f)
        hb.addWidget(self.lbl_endpoint, 1)
        self.lbl_slack = QLabel("Slack: -")
        self.lbl_required = QLabel("Required: -")
        self.lbl_arrival = QLabel("Arrival: -")
        for w in (self.lbl_slack, self.lbl_required, self.lbl_arrival):
            hb.addWidget(w)
        right_layout.addWidget(header_box)

        # Bar
        self.bar = PathBarWidget()
        right_layout.addWidget(self.bar)

        # Stage table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Cell", "Type", "Pin", "Dir", "Delay (ns)", "Cumulative"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        thdr = self.table.horizontalHeader()
        thdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        thdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.table, 1)

        # Bottom buttons
        btns = QHBoxLayout()
        self.btn_show_layout = QPushButton("Show in Layout")
        self.btn_export = QPushButton("Export Report...")
        btns.addWidget(self.btn_show_layout)
        btns.addWidget(self.btn_export)
        btns.addStretch(1)
        right_layout.addLayout(btns)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 700])

        root_layout.addWidget(splitter, 1)
        self.setWidget(root)

    def _wire(self) -> None:
        self.tree.itemSelectionChanged.connect(self._on_tree_select)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.cellDoubleClicked.connect(self._on_table_double_click)
        self.bar.cell_clicked.connect(self._on_bar_click)
        self.search.textChanged.connect(self.filter_paths)
        self.type_combo.currentIndexChanged.connect(self._refresh_tree)
        self.slack_filter.valueChanged.connect(self._refresh_tree)
        self.group_combo.currentIndexChanged.connect(self._refresh_tree)
        self.refresh_btn.clicked.connect(self._refresh_tree)
        self.critical_btn.clicked.connect(self._select_critical_path)
        self.btn_show_layout.clicked.connect(self._on_show_layout)

    # -- Public API -------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self.bar.set_theme(dark)
        if dark:
            style = """
                QDockWidget { color: #ddd; }
                QTreeWidget { background: #1e1e1e; color: #ddd; alternate-background-color: #252525;
                              gridline-color: #333; border: 1px solid #333; }
                QTreeWidget::item:selected { background: #094771; }
                QTableWidget { background: #1e1e1e; color: #ddd; alternate-background-color: #252525;
                               gridline-color: #333; border: 1px solid #333; }
                QHeaderView::section { background: #2a2a2a; color: #ddd; padding: 4px;
                                       border: 1px solid #333; }
                QFrame { background: #232323; color: #ddd; }
                QLabel { color: #ddd; }
                QToolBar { background: #2a2a2a; border: none; spacing: 4px; }
                QPushButton, QToolButton { background: #333; color: #ddd; border: 1px solid #555;
                                            padding: 4px 10px; border-radius: 3px; }
                QPushButton:hover, QToolButton:hover { background: #3d3d3d; }
                QLineEdit, QComboBox, QDoubleSpinBox { background: #2a2a2a; color: #ddd;
                                                       border: 1px solid #444; padding: 2px 4px; }
            """
        else:
            style = """
                QTreeWidget, QTableWidget { background: #ffffff; alternate-background-color: #f5f5f5; }
            """
        self.setStyleSheet(style)

    def load_paths(self, paths: list[dict]) -> None:
        """Load timing paths into the browser."""
        self._paths = list(paths)
        self._current_path = None
        self._refresh_tree()

    def filter_paths(self, query: str) -> None:
        """Filter the displayed tree by endpoint substring."""
        q = (query or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            grp = self.tree.topLevelItem(i)
            visible_children = 0
            for j in range(grp.childCount()):
                child = grp.child(j)
                ep = child.text(1).lower()
                match = (not q) or (q in ep)
                child.setHidden(not match)
                if match:
                    visible_children += 1
            grp.setHidden(visible_children == 0 and bool(q))

    # -- Tree population --------------------------------------------------

    def _refresh_tree(self) -> None:
        self.tree.clear()
        if not self._paths:
            return

        slack_max = self.slack_filter.value()
        group_by = self.group_combo.currentText()

        # Apply filters
        filtered = [p for p in self._paths if p.get("slack", 0.0) < slack_max]

        if group_by == "None":
            groups = {"All Paths": filtered}
        elif group_by == "Endpoint":
            groups = {}
            for p in filtered:
                ep_root = p.get("endpoint", "?").rsplit("/", 1)[0]
                groups.setdefault(ep_root, []).append(p)
        else:  # Clock
            groups = {}
            for p in filtered:
                clk = p.get("clock", "default")
                groups.setdefault(clk, []).append(p)

        for grp_name, paths in sorted(groups.items()):
            paths.sort(key=lambda x: x.get("slack", 0.0))
            grp_item = QTreeWidgetItem(
                [
                    "",
                    f"{grp_name}  ({len(paths)})",
                    "",
                    "",
                    "",
                ]
            )
            f = QFont()
            f.setBold(True)
            grp_item.setFont(1, f)
            self.tree.addTopLevelItem(grp_item)
            for p in paths:
                slack = p.get("slack", 0.0)
                status = _CLEAN if slack >= 0 else _VIOL
                delay = p.get("arrival", 0.0)
                item = QTreeWidgetItem(
                    [
                        status,
                        p.get("endpoint", "?"),
                        _format_ns(slack),
                        f"{delay:.3f} ns",
                        str(len(p.get("stages", []))),
                    ]
                )
                color = _slack_color(slack, self._dark)
                item.setForeground(2, QBrush(color))
                item.setForeground(0, QBrush(color))
                item.setData(0, Qt.ItemDataRole.UserRole, p)
                grp_item.addChild(item)
            grp_item.setExpanded(True)

    # -- Selection handlers -----------------------------------------------

    def _on_tree_select(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, dict):
            return
        self._current_path = path
        self._populate_detail(path)
        self.path_selected.emit(path)
        sp = path.get("startpoint") or path.get("start")
        if sp:
            self.source_navigate.emit(str(sp))

    def _populate_detail(self, path: dict) -> None:
        self.lbl_endpoint.setText(path.get("endpoint", "?"))
        slack = path.get("slack", 0.0)
        self.lbl_slack.setText(f"Slack: {_format_ns(slack)}")
        self.lbl_required.setText(f"Required: {path.get('required', 0.0):.3f}")
        self.lbl_arrival.setText(f"Arrival: {path.get('arrival', 0.0):.3f}")
        color = _slack_color(slack, self._dark)
        self.lbl_slack.setStyleSheet(f"color: {color.name()}; font-weight: bold;")

        stages = path.get("stages", [])
        self.bar.set_stages(stages)

        self.table.setRowCount(len(stages))
        for i, stage in enumerate(stages):
            cells = [
                stage.get("cell", ""),
                stage.get("type", ""),
                stage.get("pin", ""),
                stage.get("direction", ""),
                f"{stage.get('delay', 0.0):.3f}",
                f"{stage.get('cumulative', 0.0):.3f}",
            ]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c >= 4:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(i, c, item)

    def _on_table_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or not self._current_path:
            return
        row = rows[0].row()
        stages = self._current_path.get("stages", [])
        if 0 <= row < len(stages):
            self._emit_stage(stages[row])

    def _on_table_double_click(self, row: int, col: int) -> None:  # noqa: ARG002
        if not self._current_path:
            return
        stages = self._current_path.get("stages", [])
        if 0 <= row < len(stages):
            self._emit_stage(stages[row])

    def _on_bar_click(self, idx: int) -> None:
        if not self._current_path:
            return
        stages = self._current_path.get("stages", [])
        if 0 <= idx < len(stages):
            self.table.selectRow(idx)
            self._emit_stage(stages[idx])

    def _emit_stage(self, stage: dict) -> None:
        cell = stage.get("cell", "")
        if cell:
            self.cell_selected.emit(cell)
        x = stage.get("x")
        y = stage.get("y")
        if x is not None and y is not None:
            self.layout_navigate_requested.emit(float(x), float(y))

    def _on_show_layout(self) -> None:
        if not self._current_path:
            return
        stages = self._current_path.get("stages", [])
        if stages:
            first = stages[0]
            x, y = first.get("x"), first.get("y")
            if x is not None and y is not None:
                self.layout_navigate_requested.emit(float(x), float(y))

    # ------------------------------------------------------------------
    # Real STA report integration
    # ------------------------------------------------------------------

    def load_sta_report(self, report: StaReport) -> None:
        """Populate the browser with paths from a real :class:`StaReport`."""
        self._report = report
        self._paths = [self._path_to_dict(p) for p in report.paths]
        self._current_path = None
        self._refresh_tree()

    def _path_to_dict(self, path: TimingPath) -> dict[str, Any]:
        """Convert a :class:`TimingPath` into the dict format the tree uses."""
        stages: list[dict[str, Any]] = []

        def _push(stage: TimingStage, section: str) -> None:
            stages.append(
                {
                    "section": section,
                    "cell": stage.cell_instance or stage.pin_name,
                    "type": stage.cell_type,
                    "pin": stage.pin_name,
                    "short_pin": stage.short_pin,
                    "direction": "rise" if stage.edge == "rise" else "fall",
                    "delay": stage.delay_ns,
                    "cumulative": stage.cumulative_ns,
                    "is_clock_edge": stage.is_clock_edge,
                    "is_clock_network": stage.is_clock_network,
                    "is_setup_hold": stage.is_setup_hold,
                    "description": stage.description,
                }
            )

        for s in path.launch_clock_path:
            _push(s, "launch")
        for s in path.data_path:
            _push(s, "data")
        for s in path.capture_clock_path:
            _push(s, "capture")

        return {
            "startpoint": path.startpoint,
            "endpoint": path.endpoint,
            "start": path.startpoint,
            "end": path.endpoint,
            "clock": path.endpoint_clock or path.startpoint_clock or "default",
            "slack": path.slack_ns,
            "arrival": path.data_arrival_ns,
            "required": path.data_required_ns,
            "delay": path.data_arrival_ns,
            "levels": path.num_levels,
            "stages": stages,
            "path_type": path.path_type,
            "check_type": path.check_type,
            "status": path.status,
            "_path_obj": path,
        }

    def _select_critical_path(self) -> None:
        """Select the worst-slack path in the tree."""
        if not self._paths:
            return
        worst = min(self._paths, key=lambda p: p.get("slack", 0.0))
        target_ep = worst.get("endpoint")
        for i in range(self.tree.topLevelItemCount()):
            grp = self.tree.topLevelItem(i)
            for j in range(grp.childCount()):
                child = grp.child(j)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and data.get("endpoint") == target_ep:
                    self.tree.setCurrentItem(child)
                    grp.setExpanded(True)
                    self.tree.scrollToItem(child)
                    return

    def _emit_stage(self, stage: dict) -> None:  # type: ignore[override]
        cell = stage.get("cell", "")
        if cell:
            self.cell_selected.emit(cell)
        x = stage.get("x")
        y = stage.get("y")
        if x is not None and y is not None:
            self.layout_navigate_requested.emit(float(x), float(y))


__all__ = ["PathBrowserPanel", "PathBarWidget"]
