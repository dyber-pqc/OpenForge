"""Signal browser dialog -- Vivado-style signal search and add to waveform viewer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SignalBrowserDialog(QDialog):
    """Browse and select signals to add to the waveform viewer.

    Mimics Vivado's "Add Signals" dialog with:
    - Hierarchical scope tree on the left
    - Signal list with search on the right
    - Multi-select with Add/Add All buttons
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Signals to Waveform")
        self.setMinimumSize(800, 500)

        self._selected_signals: list[str] = []
        self._all_signals: dict[str, list[dict[str, str]]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Filter:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search signals by name...")
        self._search_input.textChanged.connect(self._filter_signals)
        search_layout.addWidget(self._search_input)
        layout.addLayout(search_layout)

        # Main content: scope tree | signal list
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Scope tree (left)
        self._scope_tree = QTreeWidget()
        self._scope_tree.setHeaderLabel("Design Hierarchy")
        self._scope_tree.setMinimumWidth(250)
        self._scope_tree.currentItemChanged.connect(self._on_scope_selected)
        splitter.addWidget(self._scope_tree)

        # Signal list (right)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._signal_list = QTreeWidget()
        self._signal_list.setHeaderLabels(["Signal", "Width", "Type", "Direction"])
        self._signal_list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._signal_list.setRootIsDecorated(False)
        self._signal_list.setAlternatingRowColors(True)
        self._signal_list.setStyleSheet("alternate-background-color: #1a1a2e;")
        header = self._signal_list.header()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(1, 60)
            header.resizeSection(2, 80)
            header.resizeSection(3, 80)
        right_layout.addWidget(self._signal_list)

        # Signal count
        self._count_label = QLabel("0 signals")
        self._count_label.setStyleSheet("color: #585b70; font-size: 11px;")
        right_layout.addWidget(self._count_label)

        splitter.addWidget(right_widget)
        splitter.setSizes([250, 550])
        layout.addWidget(splitter)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_add = QPushButton("Add Selected")
        self._btn_add.setFixedWidth(120)
        self._btn_add.clicked.connect(self._add_selected)
        btn_layout.addWidget(self._btn_add)

        self._btn_add_all = QPushButton("Add All Visible")
        self._btn_add_all.setFixedWidth(120)
        self._btn_add_all.clicked.connect(self._add_all)
        btn_layout.addWidget(self._btn_add_all)

        btn_cancel = QPushButton("Close")
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

        # Populate with placeholder data
        self._load_placeholder_hierarchy()

    def selected_signals(self) -> list[str]:
        """Return fully-qualified names of selected signals."""
        return list(self._selected_signals)

    def set_design_hierarchy(self, hierarchy: dict[str, list[dict[str, str]]]) -> None:
        """Set the design hierarchy for browsing.

        Args:
            hierarchy: dict mapping scope path to list of signal dicts
                       (each with keys: name, width, type, direction)
        """
        self._all_signals = hierarchy
        self._scope_tree.clear()
        self._build_scope_tree(hierarchy)

    # -- Internal --

    def _load_placeholder_hierarchy(self) -> None:
        hierarchy: dict[str, list[dict[str, str]]] = {
            "top": [
                {"name": "clk", "width": "1", "type": "wire", "direction": "input"},
                {"name": "rst_n", "width": "1", "type": "wire", "direction": "input"},
                {"name": "enable", "width": "1", "type": "wire", "direction": "input"},
            ],
            "top.ntt_butterfly": [
                {"name": "valid_in", "width": "1", "type": "wire", "direction": "input"},
                {"name": "a_in", "width": "12", "type": "reg", "direction": "input"},
                {"name": "b_in", "width": "12", "type": "reg", "direction": "input"},
                {"name": "twiddle", "width": "12", "type": "wire", "direction": "input"},
                {"name": "valid_out", "width": "1", "type": "reg", "direction": "output"},
                {"name": "a_out", "width": "12", "type": "reg", "direction": "output"},
                {"name": "b_out", "width": "12", "type": "reg", "direction": "output"},
                {"name": "wb_product", "width": "24", "type": "reg", "direction": "internal"},
            ],
            "top.keccak_core": [
                {"name": "state", "width": "1600", "type": "reg", "direction": "internal"},
                {"name": "round_cnt", "width": "5", "type": "reg", "direction": "internal"},
                {"name": "absorb_en", "width": "1", "type": "wire", "direction": "input"},
                {"name": "squeeze_en", "width": "1", "type": "wire", "direction": "input"},
                {"name": "done", "width": "1", "type": "wire", "direction": "output"},
            ],
            "top.key_manager": [
                {"name": "key_reg", "width": "256", "type": "reg", "direction": "internal"},
                {"name": "zeroize", "width": "1", "type": "wire", "direction": "input"},
                {"name": "key_valid", "width": "1", "type": "wire", "direction": "output"},
                {"name": "key_ready", "width": "1", "type": "wire", "direction": "input"},
            ],
        }
        self.set_design_hierarchy(hierarchy)

    def _build_scope_tree(self, hierarchy: dict[str, list[dict[str, str]]]) -> None:
        nodes: dict[str, QTreeWidgetItem] = {}

        for scope_path in sorted(hierarchy.keys()):
            parts = scope_path.split(".")
            current_path = ""

            for i, part in enumerate(parts):
                current_path = f"{current_path}.{part}" if current_path else part
                if current_path not in nodes:
                    item = QTreeWidgetItem([part])
                    item.setData(0, Qt.ItemDataRole.UserRole, current_path)
                    item.setForeground(0, QColor("#89b4fa"))

                    parent_path = ".".join(parts[:i]) if i > 0 else ""
                    if parent_path and parent_path in nodes:
                        nodes[parent_path].addChild(item)
                    else:
                        self._scope_tree.addTopLevelItem(item)

                    nodes[current_path] = item

        self._scope_tree.expandAll()

        # Select first scope
        if self._scope_tree.topLevelItemCount() > 0:
            self._scope_tree.setCurrentItem(self._scope_tree.topLevelItem(0))

    def _on_scope_selected(
        self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None
    ) -> None:
        if not current:
            return
        scope = current.data(0, Qt.ItemDataRole.UserRole)
        signals = self._all_signals.get(scope, [])
        self._populate_signal_list(signals, scope)

    def _populate_signal_list(self, signals: list[dict[str, str]], scope: str) -> None:
        self._signal_list.clear()
        filter_text = self._search_input.text().lower()

        for sig in signals:
            name = sig["name"]
            if filter_text and filter_text not in name.lower():
                continue

            item = QTreeWidgetItem(
                [name, sig.get("width", "1"), sig.get("type", "wire"), sig.get("direction", "")]
            )

            # Color by type
            type_colors = {
                "input": "#a6e3a1",
                "output": "#f9e2af",
                "internal": "#89b4fa",
                "inout": "#f5c2e7",
            }
            color = type_colors.get(sig.get("direction", ""), "#cdd6f4")
            for col in range(4):
                item.setForeground(col, QColor(color))

            item.setData(0, Qt.ItemDataRole.UserRole, f"{scope}.{name}")
            self._signal_list.addTopLevelItem(item)

        self._count_label.setText(f"{self._signal_list.topLevelItemCount()} signals")

    def _filter_signals(self, _text: str) -> None:
        current = self._scope_tree.currentItem()
        if current:
            self._on_scope_selected(current, None)

    def _add_selected(self) -> None:
        for item in self._signal_list.selectedItems():
            full_name = item.data(0, Qt.ItemDataRole.UserRole)
            if full_name and full_name not in self._selected_signals:
                self._selected_signals.append(full_name)
        self.accept()

    def _add_all(self) -> None:
        for i in range(self._signal_list.topLevelItemCount()):
            item = self._signal_list.topLevelItem(i)
            if item:
                full_name = item.data(0, Qt.ItemDataRole.UserRole)
                if full_name and full_name not in self._selected_signals:
                    self._selected_signals.append(full_name)
        self.accept()
