"""KiCad Library Manager panel.

Lets the user:
    * see which KiCad install directories are active as sources,
    * import symbols + footprints from them into the OpenForge cache,
    * browse the imported libraries in a tree with a preview pane,
    * feed the parsed symbols back into the schematic editor.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.pcb.kicad_importer import (
        DEFAULT_ALLOW_FOOTPRINT_PRETTIES,
        DEFAULT_ALLOW_SYMBOL_LIBS,
        KicadLibraryImporter,
        default_cache_path,
    )

    _HAS_IMPORTER = True
except Exception:  # pragma: no cover - defensive
    _HAS_IMPORTER = False
    KicadLibraryImporter = None  # type: ignore
    DEFAULT_ALLOW_FOOTPRINT_PRETTIES = []  # type: ignore
    DEFAULT_ALLOW_SYMBOL_LIBS = []  # type: ignore

    def default_cache_path() -> Path:  # type: ignore
        return Path.home() / ".openforge" / "cache" / "kicad_libraries.json"


try:
    from openforge_desktop.theme.design_system import DARK_PALETTE
except Exception:  # pragma: no cover
    DARK_PALETTE = None  # type: ignore

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preview canvases
# ---------------------------------------------------------------------------


class _SymbolPreview(QGraphicsView):
    """Cream-colored KiCad-style symbol preview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#fff8dc")))
        self.setMinimumSize(260, 220)

    def show_symbol(self, sym: Any) -> None:
        self._scene.clear()
        if sym is None:
            return
        w = float(getattr(sym, "width", 200) or 200)
        h = float(getattr(sym, "height", 200) or 200)
        pen = QPen(QColor("#7a0000"), 2)
        self._scene.addRect(-w / 2, -h / 2, w, h, pen)

        pin_pen = QPen(QColor("#003366"), 2)
        label_color = QColor("#222")
        for p in getattr(sym, "pins", []) or []:
            x = float(getattr(p, "x", 0))
            y = float(getattr(p, "y", 0))
            length = float(getattr(p, "length", 100) or 100)
            orient = getattr(p, "orientation", "right")
            if orient == "right":
                x2, y2 = x + length, y
            elif orient == "left":
                x2, y2 = x - length, y
            elif orient == "up":
                x2, y2 = x, y - length
            else:
                x2, y2 = x, y + length
            self._scene.addLine(x, y, x2, y2, pin_pen)
            label = self._scene.addText(
                f"{getattr(p, 'number', '')} {getattr(p, 'name', '')}"
            )
            label.setDefaultTextColor(label_color)
            label.setPos(x2 + 2, y2 - 10)

        name = getattr(sym, "name", "")
        title = self._scene.addText(name)
        title.setDefaultTextColor(QColor("#7a0000"))
        title.setPos(-w / 2, -h / 2 - 24)

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class _FootprintPreview(QGraphicsView):
    """Dark-green PCB-style footprint preview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#0b3d0b")))
        self.setMinimumSize(260, 220)

    def _get(self, obj: Any, name: str, default: Any = 0) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def show_footprint(self, fp: Any) -> None:
        self._scene.clear()
        if fp is None:
            return

        scale = 10.0  # 1mm -> 10 scene units

        # Courtyard / silkscreen lines
        silk_pen = QPen(QColor("#f5f5dc"), 1.0)
        edge_pen = QPen(QColor("#ffe36a"), 1.2)
        fab_pen = QPen(QColor("#888"), 0.8)
        for ln in self._get(fp, "lines", []) or []:
            layer = self._get(ln, "layer", "F.SilkS")
            pen = silk_pen if "Silk" in layer else (edge_pen if "CrtYd" in layer else fab_pen)
            self._scene.addLine(
                float(self._get(ln, "x1")) * scale,
                float(self._get(ln, "y1")) * scale,
                float(self._get(ln, "x2")) * scale,
                float(self._get(ln, "y2")) * scale,
                pen,
            )
        for rc in self._get(fp, "rectangles", []) or []:
            x1 = float(self._get(rc, "x1")) * scale
            y1 = float(self._get(rc, "y1")) * scale
            x2 = float(self._get(rc, "x2")) * scale
            y2 = float(self._get(rc, "y2")) * scale
            self._scene.addRect(
                min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1), silk_pen
            )
        for ci in self._get(fp, "circles", []) or []:
            cx = float(self._get(ci, "center_x")) * scale
            cy = float(self._get(ci, "center_y")) * scale
            ex = float(self._get(ci, "end_x")) * scale
            ey = float(self._get(ci, "end_y")) * scale
            r = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
            self._scene.addEllipse(cx - r, cy - r, 2 * r, 2 * r, silk_pen)

        pad_top = QBrush(QColor("#d4a03a"))
        pad_top_pen = QPen(QColor("#ffdd77"), 0.8)
        pad_tht_pen = QPen(QColor("#bb8a24"), 0.8)
        for pad in self._get(fp, "pads", []) or []:
            x = float(self._get(pad, "x")) * scale
            y = float(self._get(pad, "y")) * scale
            w = float(self._get(pad, "width")) * scale
            h = float(self._get(pad, "height")) * scale
            if w <= 0 or h <= 0:
                continue
            shape = self._get(pad, "shape", "rect")
            pad_type = self._get(pad, "pad_type", "smd")
            pen = pad_tht_pen if "thru" in str(pad_type) else pad_top_pen
            if shape in ("circle", "oval") and abs(w - h) < 1e-6 or shape == "oval":
                item = self._scene.addEllipse(x - w / 2, y - h / 2, w, h, pen, pad_top)
            else:
                item = self._scene.addRect(x - w / 2, y - h / 2, w, h, pen, pad_top)
            item.setToolTip(f"Pad {self._get(pad, 'number', '?')}")
            drill = float(self._get(pad, "drill", 0) or 0) * scale
            if drill > 0:
                self._scene.addEllipse(
                    x - drill / 2,
                    y - drill / 2,
                    drill,
                    drill,
                    QPen(QColor("#0b3d0b"), 0.5),
                    QBrush(QColor("#0b3d0b")),
                )

        name = self._get(fp, "name", "")
        lbl = self._scene.addText(name)
        lbl.setDefaultTextColor(QColor("#f5f5dc"))
        br = self._scene.itemsBoundingRect()
        lbl.setPos(br.left(), br.top() - 20)

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-20, -30, 20, 20))
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class LibraryManagerPanel(QWidget):
    """KiCad Library Manager (symbols + footprints)."""

    libraries_imported = Signal(dict)  # emits {"symbols": {...}}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LibraryManagerPanel")
        self._importer: KicadLibraryImporter | None = (
            KicadLibraryImporter() if _HAS_IMPORTER else None
        )
        self._sources: list[Path] = []
        self._apply_theme()
        self._build_ui()
        self._auto_detect_sources()
        self._try_load_cache()

    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        bg = "#1e1e2e"
        subtle = "#181825"
        border = "#313244"
        text = "#cdd6f4"
        accent = "#00d4ff"
        if DARK_PALETTE is not None:
            bg = getattr(DARK_PALETTE, "bg_base", bg)
            subtle = getattr(DARK_PALETTE, "bg_subtle", subtle)
            border = getattr(DARK_PALETTE, "border_default", border)
            text = getattr(DARK_PALETTE, "text_primary", text)
            accent = getattr(DARK_PALETTE, "border_focus", accent)
        self.setStyleSheet(
            f"""
            QWidget#LibraryManagerPanel {{
                background: {bg};
                color: {text};
            }}
            QLabel {{ color: {text}; background: transparent; }}
            QLineEdit, QListWidget, QTreeWidget, QTabWidget::pane {{
                background: {subtle};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
            }}
            QTabBar::tab {{
                background: {subtle};
                color: {text};
                padding: 6px 14px;
                border: 1px solid {border};
                border-bottom: none;
            }}
            QTabBar::tab:selected {{ background: {bg}; color: {accent}; }}
            QPushButton {{
                background: {subtle};
                color: {text};
                border: 1px solid {border};
                padding: 5px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{ border-color: {accent}; color: {accent}; }}
            """
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("KiCad Library Manager")
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        self._import_btn = QPushButton("Import")
        self._import_btn.clicked.connect(self._on_import_clicked)
        header.addWidget(self._import_btn)
        root.addLayout(header)

        self._status = QLabel("Ready.")
        self._status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        root.addWidget(self._status)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_sources_tab(), "Sources")
        self._tabs.addTab(self._build_symbols_tab(), "Symbols")
        self._tabs.addTab(self._build_footprints_tab(), "Footprints")
        self._tabs.addTab(self._build_stats_tab(), "Statistics")
        root.addWidget(self._tabs, 1)

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------

    def _build_sources_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(6)
        lay.addWidget(QLabel("KiCad source directories:"))
        self._src_list = QListWidget()
        lay.addWidget(self._src_list, 1)
        btns = QHBoxLayout()
        add = QPushButton("Add…")
        rem = QPushButton("Remove")
        redetect = QPushButton("Auto-detect")
        add.clicked.connect(self._on_add_source)
        rem.clicked.connect(self._on_remove_source)
        redetect.clicked.connect(self._auto_detect_sources)
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addWidget(redetect)
        btns.addStretch(1)
        lay.addLayout(btns)
        return w

    def _build_symbols_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        self._sym_search = QLineEdit()
        self._sym_search.setPlaceholderText("Search symbols…")
        self._sym_search.textChanged.connect(self._filter_symbols)
        llay.addWidget(self._sym_search)
        self._sym_tree = QTreeWidget()
        self._sym_tree.setHeaderLabels(["Symbol / Library"])
        self._sym_tree.itemSelectionChanged.connect(self._on_sym_select)
        llay.addWidget(self._sym_tree, 1)
        splitter.addWidget(left)
        self._sym_preview = _SymbolPreview()
        splitter.addWidget(self._sym_preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        lay.addWidget(splitter)
        return w

    def _build_footprints_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        self._fp_search = QLineEdit()
        self._fp_search.setPlaceholderText("Search footprints…")
        self._fp_search.textChanged.connect(self._filter_footprints)
        llay.addWidget(self._fp_search)
        self._fp_tree = QTreeWidget()
        self._fp_tree.setHeaderLabels(["Footprint / Library"])
        self._fp_tree.itemSelectionChanged.connect(self._on_fp_select)
        llay.addWidget(self._fp_tree, 1)
        splitter.addWidget(left)
        self._fp_preview = _FootprintPreview()
        splitter.addWidget(self._fp_preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        lay.addWidget(splitter)
        return w

    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._stats_label = QLabel("No libraries imported.")
        self._stats_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._stats_label.setWordWrap(True)
        self._stats_label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self._stats_label, 1)
        return w

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def _auto_detect_sources(self) -> None:
        self._sources.clear()
        self._src_list.clear()
        if self._importer is None:
            self._src_list.addItem("(core importer unavailable)")
            return
        found = KicadLibraryImporter.detect_kicad_libs()
        for key in ("symbols", "footprints"):
            p = found.get(key)
            if p and p not in self._sources:
                self._sources.append(p)
                self._src_list.addItem(f"{key}: {p}")
        if not self._sources:
            self._src_list.addItem("(no KiCad install detected — add a path manually)")

    def _on_add_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select KiCad directory")
        if path:
            p = Path(path)
            self._sources.append(p)
            self._src_list.addItem(str(p))

    def _on_remove_source(self) -> None:
        row = self._src_list.currentRow()
        if row < 0 or row >= len(self._sources):
            return
        self._src_list.takeItem(row)
        with contextlib.suppress(IndexError):
            self._sources.pop(row)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _on_import_clicked(self) -> None:
        if self._importer is None:
            self._status.setText("Core importer not available.")
            return
        total_sym = 0
        total_fp = 0
        for src in self._sources:
            if not src.exists():
                continue
            if (src / "Device.kicad_sym").exists() or any(src.glob("*.kicad_sym")):
                total_sym += self._importer.import_symbols(
                    src, allow_libraries=DEFAULT_ALLOW_SYMBOL_LIBS
                )
            if any(src.glob("*.pretty")):
                total_fp += self._importer.import_footprints(
                    src, allow_pretty=DEFAULT_ALLOW_FOOTPRINT_PRETTIES
                )
        try:
            self._importer.cache_to_disk(default_cache_path())
        except Exception as exc:
            log.warning("failed to cache: %s", exc)
        self._refresh_trees()
        self._refresh_stats()
        self._status.setText(
            f"Imported {total_sym} symbols from {len(self._importer.symbol_lib_counts)} libraries"
            f" · {total_fp} footprints from {len(self._importer.footprint_lib_counts)} libraries"
        )
        self.libraries_imported.emit(
            {
                "symbols": dict(self._importer.symbols),
                "footprints": dict(self._importer.footprints),
            }
        )

    def _try_load_cache(self) -> None:
        if self._importer is None:
            return
        try:
            data = self._importer.load_from_cache(default_cache_path())
        except Exception as exc:
            log.debug("cache load failed: %s", exc)
            return
        if data and data.get("symbols"):
            self._refresh_trees()
            self._refresh_stats()
            n_sym = len(self._importer.symbols)
            n_fp = len(self._importer.footprints)
            self._status.setText(
                f"Loaded cache: {n_sym} symbols · {n_fp} footprints"
            )

    # ------------------------------------------------------------------
    # Trees
    # ------------------------------------------------------------------

    def _refresh_trees(self) -> None:
        self._sym_tree.clear()
        if self._importer is not None:
            by_lib: dict[str, list[tuple[str, Any]]] = {}
            for key, sym in self._importer.symbols.items():
                lib = getattr(sym, "library", "") or key.split(":", 1)[0]
                by_lib.setdefault(lib, []).append((getattr(sym, "name", key), sym))
            for lib in sorted(by_lib):
                items = sorted(by_lib[lib], key=lambda t: t[0].lower())
                top = QTreeWidgetItem([f"{lib}  ({len(items)})"])
                for name, sym in items:
                    child = QTreeWidgetItem([name])
                    child.setData(0, Qt.ItemDataRole.UserRole, sym)
                    top.addChild(child)
                self._sym_tree.addTopLevelItem(top)

        self._fp_tree.clear()
        if self._importer is not None:
            by_lib_fp: dict[str, list[tuple[str, Any]]] = {}
            for key, fp in self._importer.footprints.items():
                lib = (
                    fp.get("library") if isinstance(fp, dict) else getattr(fp, "library", "")
                ) or key.split(":", 1)[0]
                name = (
                    fp.get("name") if isinstance(fp, dict) else getattr(fp, "name", key)
                )
                by_lib_fp.setdefault(lib, []).append((name, fp))
            for lib in sorted(by_lib_fp):
                items = sorted(by_lib_fp[lib], key=lambda t: (t[0] or "").lower())
                top = QTreeWidgetItem([f"{lib}  ({len(items)})"])
                for name, fp in items:
                    child = QTreeWidgetItem([name or "?"])
                    child.setData(0, Qt.ItemDataRole.UserRole, fp)
                    top.addChild(child)
                self._fp_tree.addTopLevelItem(top)

    def _filter_symbols(self, text: str) -> None:
        self._filter_tree(self._sym_tree, text)

    def _filter_footprints(self, text: str) -> None:
        self._filter_tree(self._fp_tree, text)

    def _filter_tree(self, tree: QTreeWidget, text: str) -> None:
        needle = text.lower().strip()
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            any_visible = False
            for j in range(top.childCount()):
                child = top.child(j)
                show = needle in child.text(0).lower() if needle else True
                child.setHidden(not show)
                any_visible = any_visible or show
            top.setHidden(not any_visible)

    def _on_sym_select(self) -> None:
        items = self._sym_tree.selectedItems()
        if not items:
            return
        sym = items[0].data(0, Qt.ItemDataRole.UserRole)
        if sym is not None:
            self._sym_preview.show_symbol(sym)

    def _on_fp_select(self) -> None:
        items = self._fp_tree.selectedItems()
        if not items:
            return
        fp = items[0].data(0, Qt.ItemDataRole.UserRole)
        if fp is not None:
            self._fp_preview.show_footprint(fp)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _refresh_stats(self) -> None:
        if self._importer is None:
            self._stats_label.setText("Core importer not available.")
            return
        n_sym = len(self._importer.symbols)
        n_fp = len(self._importer.footprints)
        sym_bins: dict[str, int] = {}
        for sym in self._importer.symbols.values():
            pin_count = len(getattr(sym, "pins", []) or [])
            if pin_count <= 2:
                b = "1-2 pins"
            elif pin_count <= 8:
                b = "3-8 pins"
            elif pin_count <= 32:
                b = "9-32 pins"
            else:
                b = "33+ pins"
            sym_bins[b] = sym_bins.get(b, 0) + 1

        fp_bins: dict[str, int] = {}
        for fp in self._importer.footprints.values():
            pads = fp.get("pads") if isinstance(fp, dict) else getattr(fp, "pads", [])
            n = len(pads or [])
            if n <= 2:
                fp_bins["1-2 pads"] = fp_bins.get("1-2 pads", 0) + 1
            elif n <= 8:
                fp_bins["3-8 pads"] = fp_bins.get("3-8 pads", 0) + 1
            elif n <= 64:
                fp_bins["9-64 pads"] = fp_bins.get("9-64 pads", 0) + 1
            else:
                fp_bins["65+ pads"] = fp_bins.get("65+ pads", 0) + 1

        lines = [
            f"<b>Symbols:</b> {n_sym} across {len(self._importer.symbol_lib_counts)} libraries",
            "<br>".join(
                f"&nbsp;&nbsp;{k}: {v}"
                for k, v in sorted(self._importer.symbol_lib_counts.items())
            ),
            "",
            "<b>Symbol pin distribution:</b> "
            + ", ".join(f"{k}: {v}" for k, v in sorted(sym_bins.items())),
            "",
            f"<b>Footprints:</b> {n_fp} across {len(self._importer.footprint_lib_counts)} libraries",
            "<br>".join(
                f"&nbsp;&nbsp;{k}: {v}"
                for k, v in sorted(self._importer.footprint_lib_counts.items())
            ),
            "",
            "<b>Footprint pad distribution:</b> "
            + ", ".join(f"{k}: {v}" for k, v in sorted(fp_bins.items())),
        ]
        self._stats_label.setText("<br>".join(lines))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def imported_symbols(self) -> dict[str, Any]:
        return dict(self._importer.symbols) if self._importer else {}

    def imported_footprints(self) -> dict[str, Any]:
        return dict(self._importer.footprints) if self._importer else {}


__all__ = ["LibraryManagerPanel"]
