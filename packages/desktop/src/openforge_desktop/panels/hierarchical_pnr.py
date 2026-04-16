"""Hierarchical place-and-route panel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.physical.hierarchical import (
        BlockBudget,
        HierarchicalFlow,
        HierBlock,
        HierDesign,
    )
except Exception:  # pragma: no cover
    BlockBudget = None  # type: ignore[assignment]
    HierarchicalFlow = None  # type: ignore[assignment]
    HierBlock = None  # type: ignore[assignment]
    HierDesign = None  # type: ignore[assignment]


_BG = "#1e1e2e"
_PANEL = "#181825"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_SUBTLE = "#a6adc8"
_BLUE = "#89b4fa"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"
_MAUVE = "#cba6f7"


_STATE_COLOR = {
    "not_started": _SUBTLE,
    "synth_done": _BLUE,
    "pnr_done": _MAUVE,
    "abstract_done": _GREEN,
    "frozen": _YELLOW,
}


class HierarchicalPnrPanel(QDockWidget):
    """Dock that drives a :class:`HierDesign` through the bottom-up flow."""

    block_run_requested = Signal(str, str)  # block_name, stage

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Hierarchical P&R", parent)
        self.setObjectName("hierarchical_pnr_dock")
        self._dark = True
        self._design: HierDesign | None = None  # type: ignore[valid-type]
        self._flow: HierarchicalFlow | None = None  # type: ignore[valid-type]
        self._work_dir = Path.cwd() / "hier_work"

        root = QWidget(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Toolbar
        self._toolbar = QToolBar("Hierarchical P&R", root)
        self._act_synth = self._toolbar.addAction("Synthesize")
        self._act_pnr = self._toolbar.addAction("Place & Route")
        self._act_abs = self._toolbar.addAction("Abstract")
        self._act_freeze = self._toolbar.addAction("Freeze")
        self._toolbar.addSeparator()
        self._act_all = self._toolbar.addAction("Run All Bottom-Up")
        self._act_budget = self._toolbar.addAction("Propagate Budgets")
        self._act_integrate = self._toolbar.addAction("Integrate Top")
        outer.addWidget(self._toolbar)

        self._act_synth.triggered.connect(lambda: self._run_stage("synth"))
        self._act_pnr.triggered.connect(lambda: self._run_stage("pnr"))
        self._act_abs.triggered.connect(lambda: self._run_stage("abstract"))
        self._act_freeze.triggered.connect(lambda: self._run_stage("freeze"))
        self._act_all.triggered.connect(self._run_all)
        self._act_budget.triggered.connect(self._propagate_budgets)
        self._act_integrate.triggered.connect(self._integrate_top)

        # Splitter: tree | detail / integration
        splitter = QSplitter(Qt.Orientation.Horizontal, root)

        # Left: block tree
        self._tree = QTreeWidget(splitter)
        self._tree.setHeaderLabels(["Block", "State", "Area (um^2)", "Freq (MHz)", "Util"])
        self._tree.setMinimumWidth(320)
        self._tree.itemSelectionChanged.connect(self._on_block_selected)
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self._tree)

        # Right: tab-ish area split vertically
        right = QWidget(splitter)
        rlayout = QVBoxLayout(right)
        rlayout.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QLabel("Select a block")
        self._detail_label.setStyleSheet(
            f"color: {_BLUE}; font-weight: bold; padding: 4px;"
        )
        rlayout.addWidget(self._detail_label)

        form_holder = QWidget(right)
        self._form = QFormLayout(form_holder)
        self._f_rtl = QLabel("-")
        self._f_rtl.setWordWrap(True)
        self._f_sdc = QLabel("-")
        self._f_sdc.setWordWrap(True)
        self._f_budget_area = QLabel("-")
        self._f_budget_freq = QLabel("-")
        self._f_budget_util = QLabel("-")
        self._f_budget_power = QLabel("-")
        self._f_achieved = QLabel("-")
        self._f_achieved_wns = QLabel("-")
        self._form.addRow("RTL files", self._f_rtl)
        self._form.addRow("Constraints", self._f_sdc)
        self._form.addRow("Max area um^2", self._f_budget_area)
        self._form.addRow("Target MHz", self._f_budget_freq)
        self._form.addRow("Util target", self._f_budget_util)
        self._form.addRow("Power budget mW", self._f_budget_power)
        self._form.addRow("Achieved MHz", self._f_achieved)
        self._form.addRow("WNS (ns)", self._f_achieved_wns)
        rlayout.addWidget(form_holder)

        # Floorplan strip
        strip_label = QLabel("Floorplan thumbnails")
        strip_label.setStyleSheet(f"color: {_SUBTLE}; padding-top: 4px;")
        rlayout.addWidget(strip_label)
        self._strip = QTableWidget(1, 0, right)
        self._strip.verticalHeader().setVisible(False)
        self._strip.horizontalHeader().setVisible(False)
        self._strip.setFixedHeight(70)
        rlayout.addWidget(self._strip)

        # Top integration / timing table
        self._integration_table = QTableWidget(0, 4, right)
        self._integration_table.setHorizontalHeaderLabels(
            ["Block", "X um", "Y um", "State"]
        )
        self._integration_table.horizontalHeader().setStretchLastSection(True)
        rlayout.addWidget(QLabel("Top integration view"))
        rlayout.addWidget(self._integration_table)

        # Timing log
        self._log = QTextEdit(right)
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Timing / cross-block path log")
        self._log.setMaximumHeight(120)
        rlayout.addWidget(self._log)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

        # Progress
        self._progress = QProgressBar(root)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        outer.addWidget(self._progress)

        self.setWidget(root)
        self._apply_style()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_design(self, design: "HierDesign", work_dir: Path | None = None) -> None:
        self._design = design
        if work_dir is not None:
            self._work_dir = Path(work_dir)
        if HierarchicalFlow is not None:
            self._flow = HierarchicalFlow(design, self._work_dir)
        self._rebuild_tree()
        self._rebuild_strip()

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_style()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_style(self) -> None:
        bg = _BG if self._dark else "#eff1f5"
        fg = _TEXT if self._dark else "#4c4f69"
        panel = _PANEL if self._dark else "#e6e9ef"
        surface = _SURFACE if self._dark else "#dce0e8"
        self.setStyleSheet(
            f"""
            QDockWidget {{ color: {fg}; }}
            QWidget {{ background-color: {bg}; color: {fg}; }}
            QTreeWidget, QTableWidget, QTextEdit {{
                background-color: {panel}; color: {fg};
                border: 1px solid {surface};
            }}
            QPushButton {{
                background-color: {surface}; color: {fg};
                border: 1px solid {surface}; padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {_BLUE}; color: black; }}
            QToolBar {{ background: {panel}; border: none; spacing: 2px; }}
            """
        )

    def _rebuild_tree(self) -> None:
        self._tree.clear()
        if self._design is None:
            return
        top = self._design.top
        nodes: dict[str, QTreeWidgetItem] = {}

        def add(name: str, parent_item: QTreeWidgetItem | None) -> None:
            block = self._design.blocks.get(name)
            if block is None:
                return
            item = QTreeWidgetItem(
                [
                    block.name,
                    block.state,
                    f"{block.area_um2:.1f}",
                    f"{block.achieved_freq_mhz:.1f}",
                    f"{block.utilization:.2f}",
                ]
            )
            color = _STATE_COLOR.get(block.state, _SUBTLE)
            item.setForeground(1, QBrush(QColor(color)))
            nodes[name] = item
            if parent_item is None:
                self._tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            for child in block.children:
                add(child, item)

        add(top, None)
        self._tree.expandAll()

    def _rebuild_strip(self) -> None:
        self._strip.clear()
        if self._design is None:
            return
        names = list(self._design.blocks.keys())
        self._strip.setColumnCount(len(names))
        for i, name in enumerate(names):
            block = self._design.blocks[name]
            item = QTableWidgetItem(f"{name}\n{block.state}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(
                QBrush(QColor(_STATE_COLOR.get(block.state, _SUBTLE)))
            )
            self._strip.setItem(0, i, item)
            self._strip.setColumnWidth(i, 110)

    def _rebuild_integration(self) -> None:
        self._integration_table.setRowCount(0)
        if self._design is None:
            return
        for row, (name, block) in enumerate(self._design.blocks.items()):
            if name == self._design.top:
                continue
            self._integration_table.insertRow(row)
            self._integration_table.setItem(
                row, 0, QTableWidgetItem(name)
            )
            self._integration_table.setItem(row, 1, QTableWidgetItem("-"))
            self._integration_table.setItem(row, 2, QTableWidgetItem("-"))
            self._integration_table.setItem(
                row, 3, QTableWidgetItem(block.state)
            )

    def _on_block_selected(self) -> None:
        items = self._tree.selectedItems()
        if not items or self._design is None:
            return
        name = items[0].text(0)
        block = self._design.blocks.get(name)
        if block is None:
            return
        self._detail_label.setText(f"Block: {block.name} [{block.state}]")
        self._f_rtl.setText(", ".join(block.rtl_files) or "-")
        self._f_sdc.setText(", ".join(block.constraints) or "-")
        b = block.budget
        self._f_budget_area.setText(f"{b.max_area_um2:.1f}")
        self._f_budget_freq.setText(f"{b.target_freq_mhz:.1f}")
        self._f_budget_util.setText(f"{b.utilization_target:.2f}")
        self._f_budget_power.setText(f"{b.power_budget_mw:.2f}")
        self._f_achieved.setText(f"{block.achieved_freq_mhz:.2f}")
        self._f_achieved_wns.setText(f"{block.wns_ns:.3f}")

    def _current_block(self) -> str | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        return items[0].text(0)

    def _run_stage(self, stage: str) -> None:
        name = self._current_block()
        if name is None:
            QMessageBox.information(self, "Hierarchical P&R", "Select a block first.")
            return
        if self._flow is None or self._design is None:
            self.block_run_requested.emit(name, stage)
            return
        try:
            if stage == "synth":
                self._flow.synthesize_block(name)
            elif stage == "pnr":
                self._flow.place_route_block(name)
            elif stage == "abstract":
                self._flow.generate_abstract(name)
            elif stage == "freeze":
                block = self._design.blocks[name]
                block.state = "frozen"
            self._log.append(f"[{stage}] {name}: OK")
        except Exception as exc:
            self._log.append(f"[{stage}] {name}: FAILED -- {exc}")
        self._rebuild_tree()
        self._rebuild_strip()

    def _run_all(self) -> None:
        if self._design is None or self._flow is None:
            return
        order = list(self._design.integration_order)
        if not order:
            self._design._recompute_integration_order()  # noqa: SLF001
            order = list(self._design.integration_order)
        total = max(1, len(order) * 3)
        done = 0
        for name in order:
            if name == self._design.top:
                continue
            for fn in (
                self._flow.synthesize_block,
                self._flow.place_route_block,
                self._flow.generate_abstract,
            ):
                try:
                    fn(name)
                    done += 1
                    self._progress.setValue(int(100 * done / total))
                    self._log.append(f"[{fn.__name__}] {name}: OK")
                except Exception as exc:
                    self._log.append(f"[{fn.__name__}] {name}: FAILED -- {exc}")
                    break
        self._rebuild_tree()
        self._rebuild_strip()
        self._rebuild_integration()

    def _propagate_budgets(self) -> None:
        if self._flow is None:
            return
        self._flow.propagate_budgets()
        self._rebuild_tree()
        self._log.append("Propagated budgets top-down")

    def _integrate_top(self) -> None:
        if self._flow is None:
            return
        try:
            result = self._flow.integrate_top()
            self._log.append(
                f"Integrated top {result['top']} with {result['block_count']} blocks"
            )
        except Exception as exc:
            self._log.append(f"Integration failed: {exc}")
        self._rebuild_integration()


__all__ = ["HierarchicalPnrPanel"]
