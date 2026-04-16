"""Visual clock-tree viewer panel.

Uses :mod:`openforge.physical.clock_tree_parser` to load a :class:`CtsTree`
and renders it three ways in a single dock:

1. A dendrogram / radial canvas of the CTS itself (``QGraphicsView``).
2. A matplotlib histogram of insertion-delay distribution.
3. A per-sink table sortable by any column.

Plus summary :class:`MetricCard` tiles, a multi-clock selector, PNG/SVG
export, and a "useful-skew" optimizer button.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure

    _HAS_MPL = True
except Exception:  # pragma: no cover
    _HAS_MPL = False

try:
    from openforge.physical.clock_tree_parser import CtsParser, CtsSink, CtsTree
except Exception:  # pragma: no cover
    CtsParser = None  # type: ignore[assignment]
    CtsSink = None  # type: ignore[assignment]
    CtsTree = None  # type: ignore[assignment]

try:
    from openforge_desktop.theme import DARK_PALETTE
    from openforge_desktop.theme.components import MetricCard, SectionHeader
except Exception:  # pragma: no cover
    DARK_PALETTE = None  # type: ignore[assignment]
    MetricCard = None  # type: ignore[assignment]
    SectionHeader = None  # type: ignore[assignment]


# Catppuccin Mocha palette slice (used directly for canvas drawing)
_BG = QColor("#1e1e2e")
_PANEL = QColor("#181825")
_SURFACE = QColor("#313244")
_TEXT = QColor("#cdd6f4")
_SUBTLE = QColor("#a6adc8")
_BLUE = QColor("#89b4fa")  # Dyber Blue accent
_MAUVE = QColor("#cba6f7")
_GREEN = QColor("#a6e3a1")
_YELLOW = QColor("#f9e2af")
_RED = QColor("#f38ba8")
_TEAL = QColor("#94e2d5")


# ---------------------------------------------------------------------------
# Canvas scene
# ---------------------------------------------------------------------------


class _ClockTreeScene(QGraphicsScene):
    """Dendrogram layout of a :class:`CtsTree`.

    Nodes are placed column-by-column by ``level``, sinks trail after the
    deepest node level. Buffers are rendered as squares, inverters as
    diamonds, sinks as circles. Edges are colored by incremental delay.
    """

    sink_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(_BG))
        self._tree: CtsTree | None = None
        self._node_items: dict[str, QGraphicsRectItem | QGraphicsEllipseItem] = {}
        self._highlight_edges: list[QGraphicsLineItem] = []

    def set_tree(self, tree: CtsTree) -> None:
        self.clear()
        self._tree = tree
        self._node_items = {}
        self._highlight_edges = []
        if tree is None:
            return
        self._layout()

    # ------------------------------------------------------------------

    def _layout(self) -> None:
        assert self._tree is not None
        tree = self._tree

        max_level = max(1, tree.num_levels)
        col_width = 180.0
        row_height = 28.0

        # Group by level
        by_level: dict[int, list[str]] = {}
        for node in tree.nodes.values():
            by_level.setdefault(node.level, []).append(node.name)
        sinks_level = max_level + 1
        by_level[sinks_level] = [s.instance for s in tree.sinks]

        # Compute per-node y positions
        positions: dict[str, QPointF] = {}
        for level, names in sorted(by_level.items()):
            x = level * col_width + 20.0
            count = max(1, len(names))
            total_h = (count - 1) * row_height
            y0 = -total_h / 2.0
            for i, name in enumerate(names):
                positions[name] = QPointF(x, y0 + i * row_height)

        # Draw edges
        max_delay = max(
            (n.insertion_delay_ns for n in tree.nodes.values()),
            default=1e-3,
        )
        for node in tree.nodes.values():
            if not node.parent or node.parent not in positions:
                continue
            p0 = positions[node.parent]
            p1 = positions[node.name]
            frac = min(1.0, node.insertion_delay_ns / max(max_delay, 1e-9))
            edge_color = _lerp_color(_BLUE, _YELLOW, frac)
            pen = QPen(edge_color, 1.8)
            line = QGraphicsLineItem(p0.x() + 12, p0.y() + 8, p1.x(), p1.y() + 8)
            line.setPen(pen)
            line.setZValue(0)
            self.addItem(line)

        # Sink edges: connect sink to nearest level-max node by coordinate
        leaf_nodes = [n for n in tree.nodes.values() if n.level == max_level]
        for sink in tree.sinks:
            if not leaf_nodes:
                continue
            nearest = min(
                leaf_nodes,
                key=lambda n: (n.x_um - sink.x_um) ** 2 + (n.y_um - sink.y_um) ** 2,
            )
            if nearest.name not in positions or sink.instance not in positions:
                continue
            p0 = positions[nearest.name]
            p1 = positions[sink.instance]
            frac = min(1.0, sink.arrival_ns / max_delay) if max_delay > 0 else 0.0
            pen = QPen(_lerp_color(_BLUE, _RED, frac), 1.2)
            line = QGraphicsLineItem(p0.x() + 12, p0.y() + 8, p1.x(), p1.y() + 8)
            line.setPen(pen)
            self.addItem(line)

        # Draw nodes
        for name, node in tree.nodes.items():
            if name not in positions:
                continue
            pos = positions[name]
            item = QGraphicsRectItem(pos.x(), pos.y(), 24, 16)
            is_inv = "inv" in node.cell_type.lower()
            item.setBrush(QBrush(_MAUVE if is_inv else _TEAL))
            item.setPen(QPen(_TEXT, 1))
            item.setToolTip(
                f"{node.name}\ncell={node.cell_type}\n"
                f"level={node.level} ins={node.insertion_delay_ns:.3f}ns"
            )
            item.setZValue(2)
            self.addItem(item)
            self._node_items[name] = item

            label = QGraphicsSimpleTextItem(_truncate(name, 14))
            label.setBrush(QBrush(_SUBTLE))
            font = QFont()
            font.setPointSize(7)
            label.setFont(font)
            label.setPos(pos.x() + 26, pos.y())
            self.addItem(label)

        # Draw sinks
        for sink in tree.sinks:
            if sink.instance not in positions:
                continue
            pos = positions[sink.instance]
            circle = QGraphicsEllipseItem(pos.x(), pos.y(), 14, 14)
            circle.setBrush(QBrush(_GREEN))
            circle.setPen(QPen(_TEXT, 1))
            circle.setToolTip(
                f"{sink.instance}/{sink.pin}\n"
                f"arrival={sink.arrival_ns:.3f}ns trans={sink.transition_ns:.3f}ns"
            )
            circle.setData(0, sink.instance)
            circle.setZValue(2)
            self.addItem(circle)
            self._node_items[sink.instance] = circle

        # Root marker
        root_pos = positions.get(tree.root.name)
        if root_pos:
            marker = QGraphicsSimpleTextItem("CLK")
            marker.setBrush(QBrush(_BLUE))
            f = QFont()
            f.setBold(True)
            marker.setFont(f)
            marker.setPos(root_pos.x() - 40, root_pos.y())
            self.addItem(marker)

        # Fit scene rect
        self.setSceneRect(self.itemsBoundingRect().adjusted(-40, -40, 40, 40))

    # ------------------------------------------------------------------

    def highlight_path_to_root(self, sink_instance: str) -> None:
        """Clear previous highlight and redraw path from ``sink`` -> root."""
        for line in self._highlight_edges:
            self.removeItem(line)
        self._highlight_edges = []
        if self._tree is None:
            return

        chain = self._tree.path_to_root(sink_instance)
        pen = QPen(_YELLOW, 3)
        # iterate consecutive pairs
        for a, b in zip(chain[:-1], chain[1:], strict=False):
            ia = self._node_items.get(a)
            ib = self._node_items.get(b)
            if ia is None or ib is None:
                continue
            ra = ia.sceneBoundingRect()
            rb = ib.sceneBoundingRect()
            line = QGraphicsLineItem(
                ra.center().x(), ra.center().y(), rb.center().x(), rb.center().y()
            )
            line.setPen(pen)
            line.setZValue(3)
            self.addItem(line)
            self._highlight_edges.append(line)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        item = self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else None)
        if isinstance(item, QGraphicsEllipseItem):
            name = item.data(0)
            if name:
                self.sink_clicked.emit(name)
                self.highlight_path_to_root(name)
        super().mousePressEvent(event)


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "."


# ---------------------------------------------------------------------------
# Histogram widget
# ---------------------------------------------------------------------------


class _SkewHistogram(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if _HAS_MPL:
            self._fig = Figure(figsize=(4, 2.4), facecolor="#1e1e2e")
            self._canvas = FigureCanvas(self._fig)
            self._ax = self._fig.add_subplot(111)
            layout.addWidget(self._canvas)
        else:  # pragma: no cover
            layout.addWidget(QLabel("matplotlib not available"))
            self._fig = None
            self._canvas = None
            self._ax = None

    def plot(self, tree: CtsTree) -> None:
        if not _HAS_MPL or self._ax is None:
            return
        self._ax.clear()
        self._ax.set_facecolor("#181825")
        for spine in self._ax.spines.values():
            spine.set_color("#45475a")
        self._ax.tick_params(colors="#a6adc8", labelsize=8)
        self._ax.xaxis.label.set_color("#cdd6f4")
        self._ax.yaxis.label.set_color("#cdd6f4")

        edges, counts = tree.histogram(bins=20)
        if len(edges) >= 2 and counts:
            widths = [edges[i + 1] - edges[i] for i in range(len(counts))]
            self._ax.bar(
                edges[:-1],
                counts,
                width=widths,
                align="edge",
                color="#89b4fa",
                edgecolor="#1e1e2e",
                linewidth=0.4,
            )
        self._ax.set_xlabel("insertion delay (ns)", fontsize=9)
        self._ax.set_ylabel("# sinks", fontsize=9)
        self._ax.set_title(
            f"skew distribution ({tree.clock_name})",
            color="#cdd6f4",
            fontsize=10,
        )
        self._ax.axvline(tree.mean_insertion_ns, color="#f9e2af", linewidth=1.2, label="mean")
        self._ax.axvline(tree.max_insertion_ns, color="#f38ba8", linewidth=1.2, label="max")
        if tree.sinks:
            self._ax.axvline(
                min(s.arrival_ns for s in tree.sinks),
                color="#a6e3a1",
                linewidth=1.2,
                label="min",
            )
        self._ax.legend(
            facecolor="#181825",
            edgecolor="#45475a",
            labelcolor="#cdd6f4",
            fontsize=8,
        )
        self._fig.tight_layout()
        self._canvas.draw_idle()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class ClockTreeViewerPanel(QDockWidget):
    """Dock with dendrogram, histogram, sink table, and metric tiles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Clock Tree Viewer", parent)
        self.setObjectName("clock_tree_viewer_dock")
        self._trees: dict[str, CtsTree] = {}
        self._active: CtsTree | None = None
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setStyleSheet(f"background:{_BG.name()}; color:{_TEXT.name()};")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Toolbar ----------------------------------------------------
        toolbar = QToolBar()
        toolbar.setStyleSheet(
            f"QToolBar {{ background:{_PANEL.name()}; border:1px solid #313244; }}"
            f"QLabel {{ color:{_SUBTLE.name()}; }}"
        )
        toolbar.addWidget(QLabel("Clock: "))
        self._clock_combo = QComboBox()
        self._clock_combo.setMinimumWidth(140)
        self._clock_combo.currentTextChanged.connect(self._on_clock_changed)
        toolbar.addWidget(self._clock_combo)
        toolbar.addSeparator()

        self._load_btn = QPushButton("Load OpenROAD Report")
        self._load_btn.clicked.connect(self._on_load_openroad)
        toolbar.addWidget(self._load_btn)

        self._export_btn = QPushButton("Export PNG")
        self._export_btn.clicked.connect(self._on_export_png)
        toolbar.addWidget(self._export_btn)

        self._optimize_btn = QPushButton("Optimize (Useful Skew)")
        self._optimize_btn.clicked.connect(self._on_optimize)
        self._optimize_btn.setStyleSheet(
            "QPushButton { background:#89b4fa; color:#1e1e2e; padding:4px 10px; "
            "border-radius:4px; font-weight:600; }"
        )
        toolbar.addWidget(self._optimize_btn)

        layout.addWidget(toolbar)

        # --- Metric tiles ----------------------------------------------
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(8)
        self._tile_buffers = self._make_tile("BUFFERS", "-")
        self._tile_inverters = self._make_tile("INVERTERS", "-")
        self._tile_max_skew = self._make_tile("MAX SKEW", "-", "ns")
        self._tile_mean_ins = self._make_tile("MEAN INS", "-", "ns")
        self._tile_max_ins = self._make_tile("MAX INS", "-", "ns")
        for tile in (
            self._tile_buffers,
            self._tile_inverters,
            self._tile_max_skew,
            self._tile_mean_ins,
            self._tile_max_ins,
        ):
            tiles_row.addWidget(tile)
        layout.addLayout(tiles_row)

        # --- Splitter: canvas | (histogram + table) --------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Canvas
        self._scene = _ClockTreeScene(self)
        self._scene.sink_clicked.connect(self._on_sink_clicked)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self._view.setBackgroundBrush(QBrush(_BG))
        self._view.setFrameStyle(0)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        splitter.addWidget(self._view)

        # Right side (histogram + table)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self._hist = _SkewHistogram()
        right_layout.addWidget(self._hist, 2)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Sink", "Level", "Insertion (ns)", "Trans (ns)", "X,Y (um)"]
        )
        self._table.setStyleSheet(
            f"QTableWidget {{ background:{_PANEL.name()}; color:{_TEXT.name()}; "
            f"gridline-color:#313244; }}"
            f"QHeaderView::section {{ background:{_SURFACE.name()}; "
            f"color:{_TEXT.name()}; padding:4px; border:0; }}"
        )
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        right_layout.addWidget(self._table, 3)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.setWidget(root)

    def _make_tile(self, label: str, value: str, unit: str = "") -> QWidget:
        if MetricCard is not None and DARK_PALETTE is not None:
            try:
                return MetricCard(label=label, value=value, unit=unit, palette=DARK_PALETTE)
            except Exception:
                pass
        # Fallback
        frame = QWidget()
        frame.setStyleSheet(
            f"background:{_PANEL.name()}; border:1px solid #313244; border-radius:6px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{_SUBTLE.name()}; font-size:10px;")
        val = QLabel(f"{value} {unit}".strip())
        val.setStyleSheet(f"color:{_TEXT.name()}; font-size:16px; font-weight:600;")
        lay.addWidget(lab)
        lay.addWidget(val)
        frame._value_label = val  # type: ignore[attr-defined]
        frame._unit = unit  # type: ignore[attr-defined]
        return frame

    def _set_tile(self, tile: QWidget, value: str, unit: str = "") -> None:
        if hasattr(tile, "set_value"):
            try:
                tile.set_value(value, unit)
                return
            except Exception:
                pass
        lab = getattr(tile, "_value_label", None)
        if lab is not None:
            lab.setText(f"{value} {unit}".strip())

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def set_trees(self, trees: dict[str, CtsTree]) -> None:
        self._trees = dict(trees)
        self._clock_combo.blockSignals(True)
        self._clock_combo.clear()
        self._clock_combo.addItems(list(trees.keys()))
        self._clock_combo.blockSignals(False)
        if trees:
            first = next(iter(trees.values()))
            self._show_tree(first)

    def set_tree(self, tree: CtsTree) -> None:
        self.set_trees({tree.clock_name: tree})

    def _show_tree(self, tree: CtsTree) -> None:
        self._active = tree
        self._scene.set_tree(tree)
        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._hist.plot(tree)
        self._refresh_tiles(tree)
        self._refresh_table(tree)

    def _refresh_tiles(self, tree: CtsTree) -> None:
        self._set_tile(self._tile_buffers, str(tree.num_buffers))
        self._set_tile(self._tile_inverters, str(tree.num_inverters))
        self._set_tile(self._tile_max_skew, f"{tree.max_skew_ns:.3f}", "ns")
        self._set_tile(self._tile_mean_ins, f"{tree.mean_insertion_ns:.3f}", "ns")
        self._set_tile(self._tile_max_ins, f"{tree.max_insertion_ns:.3f}", "ns")

    def _refresh_table(self, tree: CtsTree) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(tree.sinks))
        for r, sink in enumerate(tree.sinks):
            self._table.setItem(r, 0, QTableWidgetItem(f"{sink.instance}/{sink.pin}"))
            self._table.setItem(r, 1, QTableWidgetItem(str(sink.level)))
            self._table.setItem(r, 2, QTableWidgetItem(f"{sink.arrival_ns:.4f}"))
            self._table.setItem(r, 3, QTableWidgetItem(f"{sink.transition_ns:.4f}"))
            self._table.setItem(r, 4, QTableWidgetItem(f"{sink.x_um:.1f}, {sink.y_um:.1f}"))
        self._table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_clock_changed(self, name: str) -> None:
        if name and name in self._trees:
            self._show_tree(self._trees[name])

    def _on_load_openroad(self) -> None:
        if CtsParser is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open OpenROAD clock-tree report",
            "",
            "Reports (*.rpt *.log *.txt);;All files (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(errors="ignore")
            tree = CtsParser.from_openroad_report(text)
            self.set_trees({tree.clock_name: tree, **self._trees})
        except Exception as exc:  # pragma: no cover - user feedback only
            QLabel(f"Failed to parse: {exc}", self).show()

    def _on_export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export clock tree", "clock_tree.png", "PNG (*.png);;SVG (*.svg)"
        )
        if not path:
            return
        rect = self._scene.sceneRect()
        if path.lower().endswith(".svg"):
            try:
                from PySide6.QtSvg import QSvgGenerator

                gen = QSvgGenerator()
                gen.setFileName(path)
                gen.setSize(rect.size().toSize())
                gen.setViewBox(rect)
                painter = QPainter(gen)
                self._scene.render(painter)
                painter.end()
            except Exception:
                pass
        else:
            from PySide6.QtGui import QImage

            img = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
            img.fill(_BG)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._scene.render(painter)
            painter.end()
            img.save(path, "PNG")

    def _on_sink_clicked(self, name: str) -> None:
        if self._active is None:
            return
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text().startswith(name):
                self._table.selectRow(row)
                break

    def _on_row_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        item = self._table.item(rows[0].row(), 0)
        if item:
            instance = item.text().split("/")[0]
            self._scene.highlight_path_to_root(instance)

    # ------------------------------------------------------------------
    # Useful-skew optimizer
    # ------------------------------------------------------------------

    def _on_optimize(self) -> None:
        """Simple useful-skew heuristic.

        Identify sinks in the top / bottom 10% of insertion delay and
        suggest shifting clock arrival on their branches to absorb setup
        slack from their fastest and hold slack from their slowest peers.

        We don't modify the tree -- we surface suggestions in the row
        tooltips and tile subtitles.
        """
        if self._active is None or not self._active.sinks:
            return
        sinks = sorted(self._active.sinks, key=lambda s: s.arrival_ns)
        n = len(sinks)
        fastest = sinks[: max(1, n // 10)]
        slowest = sinks[-max(1, n // 10) :]
        max_gain = (slowest[-1].arrival_ns - fastest[0].arrival_ns) * 0.4
        self._set_tile(
            self._tile_max_skew,
            f"{self._active.max_skew_ns:.3f}",
            f"ns / opt {max_gain:.3f}",
        )
        # Tooltip suggestions
        fastest_names = ", ".join(s.instance for s in fastest[:3])
        slowest_names = ", ".join(s.instance for s in slowest[-3:])
        self._optimize_btn.setToolTip(
            f"Push earlier: {fastest_names}\nPush later: {slowest_names}\n"
            f"Potential skew reduction: {max_gain:.3f} ns"
        )
