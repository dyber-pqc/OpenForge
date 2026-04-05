"""Hierarchy browser panel showing module structure as a tree."""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtWidgets import QDockWidget, QTreeView, QVBoxLayout, QWidget


class _HierarchyNode:
    """Internal tree node for the hierarchy model."""

    __slots__ = ("name", "kind", "parent", "children")

    def __init__(
        self,
        name: str,
        kind: str = "module",
        parent: _HierarchyNode | None = None,
    ) -> None:
        self.name: str = name
        self.kind: str = kind
        self.parent: _HierarchyNode | None = parent
        self.children: list[_HierarchyNode] = []

    def append_child(self, child: _HierarchyNode) -> None:
        child.parent = self
        self.children.append(child)

    def row(self) -> int:
        if self.parent is not None:
            return self.parent.children.index(self)
        return 0


class HierarchyModel(QAbstractItemModel):
    """Tree model representing an RTL module hierarchy.

    This ships with a built-in placeholder hierarchy so the panel is
    never empty when the application starts.
    """

    _COLUMNS: tuple[str, ...] = ("Name", "Type")

    def __init__(self, parent: QWidget | None = None, *, placeholder: bool = True) -> None:
        super().__init__(parent)
        self._root = _HierarchyNode("<root>", "root")
        if placeholder:
            self._build_placeholder()

    # ── Placeholder data ───────────────────────────────────────────

    def _build_placeholder(self) -> None:
        top = _HierarchyNode("top_crypto_soc", "module")
        self._root.append_child(top)

        aes = _HierarchyNode("aes_core", "module")
        top.append_child(aes)
        aes.append_child(_HierarchyNode("aes_key_expand", "module"))
        aes.append_child(_HierarchyNode("aes_sbox", "module"))
        aes.append_child(_HierarchyNode("aes_round", "module"))

        sha3 = _HierarchyNode("sha3_keccak", "module")
        top.append_child(sha3)
        sha3.append_child(_HierarchyNode("keccak_round", "module"))
        sha3.append_child(_HierarchyNode("keccak_chi", "module"))
        sha3.append_child(_HierarchyNode("keccak_theta", "module"))

        mlkem = _HierarchyNode("ml_kem_top", "module")
        top.append_child(mlkem)
        mlkem.append_child(_HierarchyNode("ntt_butterfly", "module"))
        mlkem.append_child(_HierarchyNode("poly_arith", "module"))
        mlkem.append_child(_HierarchyNode("sampler", "module"))
        mlkem.append_child(_HierarchyNode("compress", "module"))

        bus = _HierarchyNode("axi_interconnect", "module")
        top.append_child(bus)
        bus.append_child(_HierarchyNode("axi_arbiter", "module"))
        bus.append_child(_HierarchyNode("axi_decoder", "module"))

    # ── QAbstractItemModel interface ───────────────────────────────

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self._root
        child = parent_node.children[row]
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node: _HierarchyNode = index.internalPointer()
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        node = parent.internalPointer() if parent.isValid() else self._root
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[return]
        if not index.isValid():
            return None
        node: _HierarchyNode = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return node.name
            if index.column() == 1:
                return node.kind
        return None

    def headerData(  # type: ignore[return]
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._COLUMNS[section]
        return None

    # ── Public helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        self.beginResetModel()
        self._root.children.clear()
        self.endResetModel()

    def set_root(self, root_node: _HierarchyNode) -> None:
        self.beginResetModel()
        self._root = root_node
        self.endResetModel()


class HierarchyPanel(QDockWidget):
    """Dock widget that hosts the hierarchy tree view."""

    def __init__(self, title: str = "Hierarchy Browser", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._model = HierarchyModel(self)
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(False)
        self._tree.setAnimated(True)
        self._tree.setIndentation(18)
        self._tree.expandAll()
        self._tree.setColumnWidth(0, 220)
        layout.addWidget(self._tree)

        self.setWidget(container)

    @property
    def model(self) -> HierarchyModel:
        return self._model

    @property
    def tree(self) -> QTreeView:
        return self._tree

    # ── Real data loading ─────────────────────────────────────────

    _VERILOG_KEYWORDS: frozenset[str] = frozenset({
        "module", "endmodule", "input", "output", "inout", "wire",
        "reg", "assign", "always", "initial", "parameter",
        "localparam", "generate", "genvar", "begin", "end", "if",
        "else", "case", "for", "while", "function", "task",
    })

    def load_from_sources(self, source_files: list[Path]) -> None:
        """Build the hierarchy tree from Verilog/SystemVerilog source files.

        Scans each file for ``module`` declarations and cell
        instantiations, then assembles a tree with top-level modules
        at the root and instantiated sub-modules as children.
        """
        # module_name -> list of (instance_type, instance_name)
        module_instances: dict[str, list[tuple[str, str]]] = {}
        all_modules: set[str] = set()
        instantiated_modules: set[str] = set()

        for src in source_files:
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8", errors="replace")
            # Find module declarations
            mod_names = re.findall(r"\bmodule\s+(\w+)", text)
            all_modules.update(mod_names)

            # Split text into per-module blocks for instance detection
            blocks = re.split(r"\bmodule\b", text)
            for i, block in enumerate(blocks[1:], 1):
                name_match = re.match(r"\s*(\w+)", block)
                if not name_match:
                    continue
                mod_name = name_match.group(1)
                # Find instantiations: <type> <name> (
                insts = re.findall(r"(\w+)\s+(\w+)\s*\(", block)
                filtered = [
                    (itype, iname)
                    for itype, iname in insts
                    if itype not in self._VERILOG_KEYWORDS
                ]
                module_instances.setdefault(mod_name, []).extend(filtered)
                for itype, _ in filtered:
                    instantiated_modules.add(itype)

        # Top modules are declared but never instantiated
        top_modules = all_modules - instantiated_modules
        if not top_modules:
            top_modules = all_modules  # fallback -- show everything

        root = _HierarchyNode("<root>", "root")

        def _build_subtree(mod_name: str, visited: set[str]) -> _HierarchyNode:
            node = _HierarchyNode(mod_name, "module")
            if mod_name in visited:
                return node  # prevent cycles
            visited.add(mod_name)
            for itype, iname in module_instances.get(mod_name, []):
                child = _build_subtree(itype, visited)
                child.name = f"{iname} ({itype})" if itype != iname else iname
                child.kind = "instance"
                node.append_child(child)
            visited.discard(mod_name)
            return node

        for top in sorted(top_modules):
            root.append_child(_build_subtree(top, set()))

        self._model.set_root(root)
        self._tree.expandAll()

    def load_from_json_netlist(self, json_path: Path) -> None:
        """Build the hierarchy tree from a Yosys JSON netlist.

        Walks ``data["modules"]`` and each module's ``cells`` dict to
        construct the tree.
        """
        if not json_path.exists():
            return

        data = json.loads(json_path.read_text(encoding="utf-8"))
        modules = data.get("modules", {})

        root = _HierarchyNode("<root>", "root")

        for mod_name, mod_data in modules.items():
            mod_node = _HierarchyNode(mod_name, "module")
            cells = mod_data.get("cells", {})
            # Count instances per cell type
            type_counts: dict[str, int] = {}
            for cell_data in cells.values():
                ctype = cell_data.get("type", "unknown")
                type_counts[ctype] = type_counts.get(ctype, 0) + 1

            for cell_name, cell_data in cells.items():
                ctype = cell_data.get("type", "unknown")
                count = type_counts.get(ctype, 1)
                label = f"{cell_name} [{ctype}]"
                child = _HierarchyNode(label, f"cell ({count}x {ctype})")
                mod_node.append_child(child)

            root.append_child(mod_node)

        self._model.set_root(root)
        self._tree.expandAll()

    def clear(self) -> None:
        """Reset to an empty tree with no placeholder data."""
        self._model.clear()
