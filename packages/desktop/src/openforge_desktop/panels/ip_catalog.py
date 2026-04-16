"""IP Catalog / Block Explorer panel with drag-and-drop support.

Scans ``share/ip/`` for available IP blocks and displays them in a
categorised tree.  Users can drag an IP onto the editor to insert
an instantiation template, double-click to open sources, or use
the right-click context menu.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDrag,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Try to import yaml; fall back to a simple parser if unavailable
try:
    import yaml as _yaml
except ImportError:
    _yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Verilog parser helpers
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(
    r"module\s+(\w+)\s*"
    r"(?:#\s*\((.*?)\))?\s*"
    r"\((.*?)\)\s*;",
    re.DOTALL,
)
_PARAM_RE = re.compile(
    r"parameter\s+(?:\[.*?\]\s*)?(\w+)\s*=\s*([^,\)]+)"
)
_PORT_RE = re.compile(
    r"(input|output|inout)\s+(?:wire|reg|logic)?\s*(\[.*?\])?\s*(\w+)"
)


def _parse_verilog_module(source: str) -> dict[str, Any] | None:
    """Extract module name, parameters, and ports from Verilog source."""
    m = _MODULE_RE.search(source)
    if not m:
        return None
    mod_name = m.group(1)

    params: list[dict[str, str]] = []
    if m.group(2):
        for pm in _PARAM_RE.finditer(m.group(2)):
            params.append({"name": pm.group(1), "default": pm.group(2).strip()})

    # Parse ports from the full source, not just header
    ports: list[dict[str, str]] = []
    for pm in _PORT_RE.finditer(source):
        width = pm.group(2) or ""
        ports.append({
            "direction": pm.group(1),
            "width": width.strip(),
            "name": pm.group(3),
        })

    return {"module": mod_name, "parameters": params, "ports": ports}


def _generate_instantiation(info: dict[str, Any]) -> str:
    """Generate a Verilog instantiation template from parsed module info."""
    mod = info["module"]
    lines: list[str] = []

    if info["parameters"]:
        lines.append(f"{mod} #(")
        param_lines = []
        for p in info["parameters"]:
            param_lines.append(f"    .{p['name']}({p['default']})")
        lines.append(",\n".join(param_lines))
        lines.append(f") u_{mod} (")
    else:
        lines.append(f"{mod} u_{mod} (")

    if info["ports"]:
        port_lines = []
        for p in info["ports"]:
            port_lines.append(f"    .{p['name']}()")
        lines.append(",\n".join(port_lines))

    lines.append(");")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Catalog data loader
# ---------------------------------------------------------------------------

def _load_catalog_yaml(path: Path) -> list[dict[str, Any]]:
    """Load the IP catalog from catalog.yaml."""
    catalog_file = path / "catalog.yaml"
    if not catalog_file.exists():
        return []
    try:
        text = catalog_file.read_text(encoding="utf-8")
        if _yaml is not None:
            data = _yaml.safe_load(text)
            return data.get("catalog", []) if isinstance(data, dict) else []
        # Minimal fallback: not full YAML but enough for our catalog
        return []
    except Exception:
        return []


def _scan_ip_directory(ip_root: Path) -> list[dict[str, Any]]:
    """Scan the IP directory and build entries from catalog + filesystem."""
    entries = _load_catalog_yaml(ip_root)

    # Also discover any IP subdirectories not in catalog
    catalog_names = {e.get("name", "") for e in entries}
    if ip_root.exists():
        for child in sorted(ip_root.iterdir()):
            if child.is_dir() and child.name not in catalog_names and not child.name.startswith("."):
                # Best-effort: find a top-level .v file
                v_files = list(child.rglob("*.v"))
                if v_files:
                    entries.append({
                        "name": child.name,
                        "description": f"IP block in {child.name}/",
                        "category": "Uncategorized",
                        "path": str(v_files[0].relative_to(ip_root)),
                        "top_module": child.name,
                        "parameters": [],
                    })
    return entries


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, str] = {
    "crypto": "Cryptographic",
    "communication": "Communication",
    "infrastructure": "Infrastructure",
    "uncategorized": "Other",
}


def _category_label(raw: str) -> str:
    return _CATEGORY_MAP.get(raw.lower(), raw)


# ---------------------------------------------------------------------------
# IP detail widget (shown when an IP is selected)
# ---------------------------------------------------------------------------

class _IpDetailWidget(QWidget):
    """Shows IP name, description, ports, and parameters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._title = QLabel("Select an IP block")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        self._title.setFont(title_font)
        self._title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(self._title)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setStyleSheet(
            "QTextEdit { background-color: #181825; color: #cdd6f4; border: 1px solid #313244; }"
        )
        layout.addWidget(self._detail)

    def show_ip(self, entry: dict[str, Any], parsed: dict[str, Any] | None) -> None:
        self._title.setText(entry.get("name", "Unknown"))
        lines: list[str] = []
        desc = entry.get("description", "")
        if desc:
            lines.append(f"<b>Description:</b> {desc}")
        iface = entry.get("interface", "")
        if iface:
            lines.append(f"<b>Interface:</b> {iface}")
        area = entry.get("area_estimate", "")
        if area:
            lines.append(f"<b>Area:</b> {area}")
        lic = entry.get("license", "")
        if lic:
            lines.append(f"<b>License:</b> {lic}")

        # Parameters
        params = entry.get("parameters", [])
        if parsed and parsed.get("parameters"):
            params = parsed["parameters"]
        if params:
            lines.append("")
            lines.append("<b>Parameters:</b>")
            for p in params:
                name = p.get("name", "?")
                default = p.get("default", "")
                pdesc = p.get("description", "")
                extra = f" -- {pdesc}" if pdesc else ""
                lines.append(f"  {name} = {default}{extra}")

        # Ports
        if parsed and parsed.get("ports"):
            lines.append("")
            lines.append("<b>Ports:</b>")
            for port in parsed["ports"]:
                d = port["direction"]
                w = port.get("width", "")
                n = port["name"]
                w_str = f" {w}" if w else ""
                lines.append(f"  {d}{w_str} {n}")

        # Features
        features = entry.get("features", [])
        if features:
            lines.append("")
            lines.append("<b>Features:</b>")
            for f in features:
                lines.append(f"  - {f}")

        self._detail.setHtml("<pre style='font-family: monospace;'>" + "\n".join(lines) + "</pre>")

    def clear(self) -> None:
        self._title.setText("Select an IP block")
        self._detail.clear()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class IpCatalogPanel(QDockWidget):
    """IP Catalog dock widget with tree browser and detail pane.

    Signals:
        open_file_requested(str): emitted when the user wants to open an IP source file.
        insert_text_requested(str): emitted to insert instantiation template into editor.
    """

    open_file_requested = Signal(str)
    insert_text_requested = Signal(str)

    def __init__(
        self,
        title: str = "IP Catalog",
        parent: QWidget | None = None,
        ip_root: Path | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName("ip_catalog_dock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setMinimumWidth(260)

        # Resolve IP root
        if ip_root is None:
            # Default: H:\openforge\share\ip
            ip_root = Path(__file__).resolve().parents[4] / "share" / "ip"
        self._ip_root = ip_root

        # Internal data
        self._entries: list[dict[str, Any]] = []
        self._parsed_cache: dict[str, dict[str, Any] | None] = {}

        # Build UI
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Tree widget
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Category"])
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setDragEnabled(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.setStyleSheet(
            "QTreeWidget { background-color: #1e1e2e; border: none; }"
            "QTreeWidget::item:hover { background-color: #313244; }"
            "QTreeWidget::item:selected { background-color: #45475a; }"
        )
        main_layout.addWidget(self._tree, stretch=2)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244;")
        main_layout.addWidget(sep)

        # Detail pane
        self._detail = _IpDetailWidget()
        main_layout.addWidget(self._detail, stretch=1)

        self.setWidget(container)

        # Load IP catalog
        self._load_catalog()

    # ------------------------------------------------------------------
    # Catalog loading
    # ------------------------------------------------------------------

    def _load_catalog(self) -> None:
        """Scan the IP directory and populate the tree."""
        self._entries = _scan_ip_directory(self._ip_root)

        # Group by category
        categories: dict[str, list[dict[str, Any]]] = {}
        for entry in self._entries:
            cat = _category_label(entry.get("category", "Other"))
            categories.setdefault(cat, []).append(entry)

        self._tree.clear()

        # Desired order
        cat_order = ["Cryptographic", "Communication", "Infrastructure"]
        ordered_cats = [c for c in cat_order if c in categories]
        for c in sorted(categories):
            if c not in ordered_cats:
                ordered_cats.append(c)

        for cat in ordered_cats:
            cat_item = QTreeWidgetItem([cat, ""])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            bold_font = QFont()
            bold_font.setBold(True)
            cat_item.setFont(0, bold_font)
            cat_item.setForeground(0, QColor("#89b4fa"))
            self._tree.addTopLevelItem(cat_item)

            for entry in sorted(categories[cat], key=lambda e: e.get("name", "")):
                name = entry.get("name", "unknown")
                child = QTreeWidgetItem([name, cat])
                child.setData(0, Qt.ItemDataRole.UserRole, entry)
                child.setForeground(0, QColor("#cdd6f4"))
                child.setToolTip(0, entry.get("description", ""))
                cat_item.addChild(child)

            cat_item.setExpanded(True)

    def refresh(self) -> None:
        """Re-scan the IP directory."""
        self._parsed_cache.clear()
        self._detail.clear()
        self._load_catalog()

    # ------------------------------------------------------------------
    # Verilog parsing
    # ------------------------------------------------------------------

    def _get_parsed(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        """Parse the Verilog source for a catalog entry, with caching."""
        name = entry.get("name", "")
        if name in self._parsed_cache:
            return self._parsed_cache[name]

        rel_path = entry.get("path", "")
        if not rel_path:
            self._parsed_cache[name] = None
            return None

        src_path = self._ip_root / rel_path
        if not src_path.exists():
            self._parsed_cache[name] = None
            return None

        try:
            source = src_path.read_text(encoding="utf-8", errors="replace")
            parsed = _parse_verilog_module(source)
            self._parsed_cache[name] = parsed
            return parsed
        except Exception:
            self._parsed_cache[name] = None
            return None

    def _get_instantiation(self, entry: dict[str, Any]) -> str:
        """Build an instantiation template for the given IP entry."""
        parsed = self._get_parsed(entry)
        if parsed:
            return _generate_instantiation(parsed)

        # Fallback: use catalog metadata
        mod = entry.get("top_module", entry.get("name", "module"))
        params = entry.get("parameters", [])
        lines: list[str] = []
        if params:
            lines.append(f"{mod} #(")
            plines = []
            for p in params:
                plines.append(f"    .{p.get('name', 'P')}({p.get('default', '')})")
            lines.append(",\n".join(plines))
            lines.append(f") u_{mod} (")
        else:
            lines.append(f"{mod} u_{mod} (")
        lines.append("    // connect ports here")
        lines.append(");")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _entry_from_item(self, item: QTreeWidgetItem | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None) -> None:
        entry = self._entry_from_item(current)
        if entry:
            parsed = self._get_parsed(entry)
            self._detail.show_ip(entry, parsed)
        else:
            self._detail.clear()

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        entry = self._entry_from_item(item)
        if entry:
            rel_path = entry.get("path", "")
            if rel_path:
                full_path = self._ip_root / rel_path
                if full_path.exists():
                    self.open_file_requested.emit(str(full_path))

    def _on_context_menu(self, pos: Any) -> None:
        item = self._tree.itemAt(pos)
        entry = self._entry_from_item(item)
        if not entry:
            return

        menu = QMenu(self)

        act_view = QAction("View Source", self)
        act_view.triggered.connect(lambda: self._view_source(entry))
        menu.addAction(act_view)

        act_copy = QAction("Copy Instantiation Template", self)
        act_copy.triggered.connect(lambda: self._copy_instantiation(entry))
        menu.addAction(act_copy)

        act_insert = QAction("Insert Instantiation", self)
        act_insert.triggered.connect(lambda: self._insert_instantiation(entry))
        menu.addAction(act_insert)

        act_doc = QAction("View Documentation", self)
        act_doc.triggered.connect(lambda: self._view_docs(entry))
        menu.addAction(act_doc)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _view_source(self, entry: dict[str, Any]) -> None:
        rel_path = entry.get("path", "")
        if rel_path:
            full_path = self._ip_root / rel_path
            if full_path.exists():
                self.open_file_requested.emit(str(full_path))

    def _copy_instantiation(self, entry: dict[str, Any]) -> None:
        from PySide6.QtWidgets import QApplication
        template = self._get_instantiation(entry)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(template)

    def _insert_instantiation(self, entry: dict[str, Any]) -> None:
        template = self._get_instantiation(entry)
        self.insert_text_requested.emit(template)

    def _view_docs(self, entry: dict[str, Any]) -> None:
        """Show documentation in the detail pane (same as selection)."""
        parsed = self._get_parsed(entry)
        self._detail.show_ip(entry, parsed)

    # ------------------------------------------------------------------
    # Theme support
    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        """Update panel colors for dark or light theme."""
        if dark:
            tree_bg = "#1e1e2e"
            hover_bg = "#313244"
            sel_bg = "#45475a"
            detail_bg = "#181825"
            detail_text = "#cdd6f4"
            detail_border = "#313244"
            title_color = "#89b4fa"
        else:
            tree_bg = "#ffffff"
            hover_bg = "#e9ecef"
            sel_bg = "#dee2e6"
            detail_bg = "#f8f9fa"
            detail_text = "#212529"
            detail_border = "#dee2e6"
            title_color = "#0d6efd"

        self._tree.setStyleSheet(
            f"QTreeWidget {{ background-color: {tree_bg}; border: none; }}"
            f"QTreeWidget::item:hover {{ background-color: {hover_bg}; }}"
            f"QTreeWidget::item:selected {{ background-color: {sel_bg}; }}"
        )
        self._detail._title.setStyleSheet(f"color: {title_color};")
        self._detail._detail.setStyleSheet(
            f"QTextEdit {{ background-color: {detail_bg}; color: {detail_text}; "
            f"border: 1px solid {detail_border}; }}"
        )

    # ------------------------------------------------------------------
    # Drag support
    # ------------------------------------------------------------------

    def startDrag(self, supportedActions: Any) -> None:
        """Override to provide instantiation template as drag data."""
        item = self._tree.currentItem()
        entry = self._entry_from_item(item)
        if not entry:
            return

        template = self._get_instantiation(entry)

        mime = QMimeData()
        mime.setText(template)

        drag = QDrag(self._tree)
        drag.setMimeData(mime)

        # Create a small label pixmap for the drag icon
        label = QLabel(entry.get("name", "IP"))
        label.setStyleSheet(
            "background-color: #313244; color: #cdd6f4; "
            "padding: 4px 8px; border-radius: 4px; font-size: 11px;"
        )
        label.adjustSize()
        pixmap = label.grab()
        drag.setPixmap(pixmap)

        drag.exec(Qt.DropAction.CopyAction)
