"""PCB Router panel.

Net class manager + autoroute + length matching + diff pair routing,
all driven against an ``openforge.pcb.model.PcbBoard`` instance.
"""
from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.pcb.diff_pair import DiffPairRouter
    from openforge.pcb.length_match import LengthGroup, LengthMatcher
    from openforge.pcb.model import PcbBoard
    from openforge.pcb.net_classes import NetClass, NetClassRegistry
    from openforge.pcb.router import PcbRouter, RoutingMode

    _HAS_CORE = True
except Exception:  # noqa: BLE001
    _HAS_CORE = False
    PcbBoard = object  # type: ignore
    NetClass = object  # type: ignore
    NetClassRegistry = object  # type: ignore
    PcbRouter = object  # type: ignore


STYLE = """
QWidget { background: #1e1f2a; color: #e1e2e8; }
QGroupBox {
    background: #262834; border: 1px solid #3a3d4d;
    border-radius: 6px; margin-top: 10px; padding: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: #9bb0f7;
}
QPushButton {
    background: #3a3d4d; border: 1px solid #505569;
    border-radius: 4px; padding: 6px 12px; color: #e1e2e8;
}
QPushButton:hover { background: #4a4d5d; }
QPushButton:pressed { background: #2a2d3d; }
QTableWidget, QTreeWidget, QListWidget {
    background: #1a1b26; border: 1px solid #3a3d4d;
    alternate-background-color: #23242e;
}
QHeaderView::section {
    background: #2c2f3d; color: #9bb0f7; padding: 4px; border: none;
}
QComboBox, QDoubleSpinBox {
    background: #2c2f3d; border: 1px solid #505569; padding: 3px;
}
QProgressBar {
    background: #1a1b26; border: 1px solid #3a3d4d; border-radius: 3px;
    text-align: center;
}
QProgressBar::chunk { background: #7aa2f7; }
"""


class _RouteWorker(QThread):
    finished_with = Signal(object)  # RouteResult
    progress = Signal(int, str)

    def __init__(self, router, mode: str, targets: list[str] | None = None):
        super().__init__()
        self._router = router
        self._mode = mode
        self._targets = targets

    def run(self) -> None:  # noqa: D401
        try:
            self.progress.emit(10, f"Running {self._mode}...")
            if self._mode == "autoroute":
                result = self._router.autoroute(self._targets, RoutingMode.AUTOROUTE_ALL)
            elif self._mode == "walkaround":
                result = self._router.autoroute(self._targets, RoutingMode.WALKAROUND)
            elif self._mode == "freerouting":
                result = self._router.use_freerouting()
            else:
                result = self._router.autoroute(self._targets, RoutingMode.AUTOROUTE_ALL)
            self.progress.emit(100, "done")
            self.finished_with.emit(result)
        except Exception as exc:  # noqa: BLE001
            from openforge.pcb.router import RouteResult

            r = RouteResult(success=False, message=f"error: {exc}")
            self.finished_with.emit(r)


class PcbRouterPanel(QWidget):
    """Interactive PCB routing UI."""

    def __init__(self, board=None, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self._board = board if board is not None else self._demo_board()
        self._registry = NetClassRegistry.with_defaults() if _HAS_CORE else None
        self._worker: _RouteWorker | None = None
        self._build_ui()
        self._refresh_all()

    # ------------------------------------------------------------------
    def set_board(self, board) -> None:
        self._board = board
        self._refresh_all()

    def _demo_board(self):
        if not _HAS_CORE:
            return None
        from openforge.pcb.model import PcbBoard

        b = PcbBoard(name="demo")
        b.outline = [(0, 0), (50, 0), (50, 50), (0, 50)]
        b.add_net("VCC")
        b.add_net("GND")
        b.add_net("USB_DP")
        b.add_net("USB_DN")
        return b

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        title = QLabel("PCB Router")
        title.setStyleSheet("font-size: 14pt; color: #9bb0f7; font-weight: bold;")
        outer.addWidget(title)

        self._tabs = QTabWidget()
        outer.addWidget(self._tabs, 1)

        self._tabs.addTab(self._build_classes_tab(), "Net Classes")
        self._tabs.addTab(self._build_assign_tab(), "Assignment")
        self._tabs.addTab(self._build_auto_tab(), "Auto-route")
        self._tabs.addTab(self._build_length_tab(), "Length Match")
        self._tabs.addTab(self._build_diff_tab(), "Diff Pairs")

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        outer.addWidget(self._progress)

        self._status = QLabel("Ready")
        outer.addWidget(self._status)

    # ---- net classes tab --------------------------------------------
    def _build_classes_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_class)
        rm_btn = QPushButton("- Remove")
        rm_btn.clicked.connect(self._remove_class)
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.clicked.connect(self._reset_classes)
        bar.addWidget(add_btn)
        bar.addWidget(rm_btn)
        bar.addWidget(reset_btn)
        bar.addStretch(1)
        lay.addLayout(bar)

        self._class_table = QTableWidget(0, 8)
        self._class_table.setHorizontalHeaderLabels(
            ["Name", "Width mm", "Clearance", "Via drill", "Via dia", "Z0 (Ω)", "Len target", "Topology"]
        )
        self._class_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._class_table.itemChanged.connect(self._on_class_edited)
        lay.addWidget(self._class_table, 1)
        return w

    def _refresh_classes(self) -> None:
        if not _HAS_CORE or self._registry is None:
            return
        self._class_table.blockSignals(True)
        self._class_table.setRowCount(0)
        for name, klass in self._registry.classes.items():
            r = self._class_table.rowCount()
            self._class_table.insertRow(r)
            vals = [
                name,
                f"{klass.width_mm:.3f}",
                f"{klass.clearance_mm:.3f}",
                f"{klass.via_drill_mm:.3f}",
                f"{klass.via_diameter_mm:.3f}",
                f"{klass.impedance_target_ohm:.1f}" if klass.impedance_target_ohm else "",
                f"{klass.length_target_mm:.2f}" if klass.length_target_mm else "",
                klass.topology,
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._class_table.setItem(r, c, item)
        self._class_table.blockSignals(False)

    def _on_class_edited(self, item: QTableWidgetItem) -> None:
        if not _HAS_CORE or self._registry is None:
            return
        name_item = self._class_table.item(item.row(), 0)
        if not name_item:
            return
        klass = self._registry.classes.get(name_item.text())
        if klass is None:
            return
        col = item.column()
        text = item.text().strip()
        try:
            if col == 1:
                klass.width_mm = float(text)
            elif col == 2:
                klass.clearance_mm = float(text)
            elif col == 3:
                klass.via_drill_mm = float(text)
            elif col == 4:
                klass.via_diameter_mm = float(text)
            elif col == 5:
                klass.impedance_target_ohm = float(text) if text else None
            elif col == 6:
                klass.length_target_mm = float(text) if text else None
            elif col == 7:
                klass.topology = text or "free"
        except ValueError:
            self._refresh_classes()

    def _add_class(self) -> None:
        if not _HAS_CORE or self._registry is None:
            return
        base = "custom"
        name = base
        i = 1
        while name in self._registry.classes:
            name = f"{base}{i}"
            i += 1
        self._registry.add(NetClass(name=name))
        self._refresh_classes()

    def _remove_class(self) -> None:
        if not _HAS_CORE or self._registry is None:
            return
        r = self._class_table.currentRow()
        if r < 0:
            return
        name_item = self._class_table.item(r, 0)
        if not name_item:
            return
        try:
            self._registry.remove(name_item.text())
        except ValueError as e:
            QMessageBox.warning(self, "Cannot Remove", str(e))
            return
        self._refresh_classes()
        self._refresh_assign()

    def _reset_classes(self) -> None:
        if not _HAS_CORE:
            return
        self._registry = NetClassRegistry.with_defaults()
        self._refresh_classes()
        self._refresh_assign()

    # ---- assignment tab ---------------------------------------------
    def _build_assign_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Assign selected nets to:"))
        self._assign_combo = QComboBox()
        bar.addWidget(self._assign_combo, 1)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_assignment)
        bar.addWidget(apply_btn)
        lay.addLayout(bar)

        self._net_tree = QTreeWidget()
        self._net_tree.setHeaderLabels(["Net", "Class"])
        self._net_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        lay.addWidget(self._net_tree, 1)
        return w

    def _refresh_assign(self) -> None:
        if not _HAS_CORE or self._board is None or self._registry is None:
            return
        self._assign_combo.clear()
        for n in self._registry.classes:
            self._assign_combo.addItem(n)
        self._net_tree.clear()
        by_class: dict[str, list[str]] = {k: [] for k in self._registry.classes}
        for _nid, name in self._board.nets.items():
            if not name:
                continue
            klass = self._registry.get_for_net(name)
            by_class.setdefault(klass.name, []).append(name)
        for cname, nets in by_class.items():
            parent = QTreeWidgetItem([cname, f"{len(nets)} nets"])
            for n in sorted(nets):
                QTreeWidgetItem(parent, [n, cname])
            self._net_tree.addTopLevelItem(parent)
            parent.setExpanded(True)

    def _apply_assignment(self) -> None:
        if not _HAS_CORE or self._registry is None:
            return
        target = self._assign_combo.currentText()
        if not target:
            return
        for item in self._net_tree.selectedItems():
            if item.parent() is None:
                continue
            net = item.text(0)
            with contextlib.suppress(KeyError):
                self._registry.assign(net, target)
        self._refresh_assign()

    # ---- auto-route tab ---------------------------------------------
    def _build_auto_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        box = QGroupBox("Routing Engine")
        box_lay = QFormLayout(box)
        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["Built-in maze", "Freerouting (external)"])
        box_lay.addRow("Engine:", self._engine_combo)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Autoroute all", "Walkaround", "Diff pairs"])
        box_lay.addRow("Mode:", self._mode_combo)
        self._grid_spin = QDoubleSpinBox()
        self._grid_spin.setRange(0.05, 2.0)
        self._grid_spin.setSingleStep(0.05)
        self._grid_spin.setValue(0.25)
        self._grid_spin.setDecimals(2)
        box_lay.addRow("Grid mm:", self._grid_spin)
        lay.addWidget(box)

        bar = QHBoxLayout()
        run_btn = QPushButton("Route All")
        run_btn.clicked.connect(self._route_all)
        sel_btn = QPushButton("Route Selected")
        sel_btn.clicked.connect(self._route_selected)
        diff_btn = QPushButton("Route Diff Pairs")
        diff_btn.clicked.connect(self._route_diff_pairs)
        cancel_btn = QPushButton("Stop")
        cancel_btn.clicked.connect(self._cancel)
        bar.addWidget(run_btn)
        bar.addWidget(sel_btn)
        bar.addWidget(diff_btn)
        bar.addWidget(cancel_btn)
        bar.addStretch(1)
        lay.addLayout(bar)

        stats = QGroupBox("Statistics")
        sl = QFormLayout(stats)
        self._stat_routed = QLabel("-")
        self._stat_failed = QLabel("-")
        self._stat_len = QLabel("-")
        self._stat_vias = QLabel("-")
        self._stat_runtime = QLabel("-")
        sl.addRow("Routed:", self._stat_routed)
        sl.addRow("Failed:", self._stat_failed)
        sl.addRow("Total length:", self._stat_len)
        sl.addRow("Vias:", self._stat_vias)
        sl.addRow("Runtime:", self._stat_runtime)
        lay.addWidget(stats)

        lay.addWidget(QLabel("Failed nets:"))
        self._failed_list = QListWidget()
        lay.addWidget(self._failed_list, 1)
        return w

    def _current_router(self):
        if not _HAS_CORE:
            return None
        return PcbRouter(self._board, self._registry, grid_mm=float(self._grid_spin.value()))

    def _route_all(self) -> None:
        if not _HAS_CORE:
            return
        mode = "freerouting" if self._engine_combo.currentIndex() == 1 else "autoroute"
        self._start_worker(mode, None)

    def _route_selected(self) -> None:
        if not _HAS_CORE:
            return
        targets: list[str] = []
        for it in self._net_tree.selectedItems():
            if it.parent() is not None:
                targets.append(it.text(0))
        if not targets:
            self._status.setText("No nets selected")
            return
        self._start_worker("autoroute", targets)

    def _route_diff_pairs(self) -> None:
        if not _HAS_CORE:
            return
        router = self._current_router()
        if router is None:
            return
        dpr = DiffPairRouter(self._board, self._registry)
        pairs = dpr.detect_pairs()
        if not pairs:
            self._status.setText("No diff pairs detected")
            return
        names: list[str] = []
        for p in pairs:
            names.extend([p.pos_net, p.neg_net])
        self._start_worker("autoroute", names)

    def _start_worker(self, mode: str, targets: list[str] | None) -> None:
        router = self._current_router()
        if router is None:
            return
        if self._worker is not None and self._worker.isRunning():
            self._status.setText("Already running")
            return
        self._progress.setValue(0)
        self._worker = _RouteWorker(router, mode, targets)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_with.connect(self._on_route_finished)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._status.setText("Stop requested")

    def _on_progress(self, pct: int, msg: str) -> None:
        self._progress.setValue(pct)
        self._status.setText(msg)

    def _on_route_finished(self, result) -> None:
        self._progress.setValue(100)
        self._stat_routed.setText(str(result.routed_nets))
        self._stat_failed.setText(str(len(result.failed_nets)))
        self._stat_len.setText(f"{result.total_length_mm:.2f} mm")
        self._stat_vias.setText(str(result.via_count))
        self._stat_runtime.setText(f"{result.runtime_s:.3f} s")
        self._failed_list.clear()
        for n in result.failed_nets:
            item = QListWidgetItem(n)
            self._failed_list.addItem(item)
        self._status.setText(result.message or "Done")

    # ---- length match tab -------------------------------------------
    def _build_length_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Group (class):"))
        self._length_combo = QComboBox()
        bar.addWidget(self._length_combo, 1)
        match_btn = QPushButton("Match Group")
        match_btn.clicked.connect(self._match_group)
        bar.addWidget(match_btn)
        measure_btn = QPushButton("Measure")
        measure_btn.clicked.connect(self._measure_group)
        bar.addWidget(measure_btn)
        lay.addLayout(bar)

        self._length_table = QTableWidget(0, 3)
        self._length_table.setHorizontalHeaderLabels(["Net", "Length (mm)", "Δ to target"])
        self._length_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._length_table, 1)
        return w

    def _refresh_length(self) -> None:
        if not _HAS_CORE or self._registry is None:
            return
        self._length_combo.clear()
        for name in self._registry.classes:
            self._length_combo.addItem(name)

    def _measure_group(self) -> None:
        if not _HAS_CORE:
            return
        cname = self._length_combo.currentText()
        klass = self._registry.classes.get(cname)
        if klass is None:
            return
        group = LengthGroup(
            name=cname,
            nets=list(klass.nets),
            target_mm=klass.length_target_mm,
            tolerance_mm=klass.length_tolerance_mm or 0.5,
        )
        matcher = LengthMatcher(self._board)
        lengths = matcher.measure_group(group)
        target = group.target_mm if group.target_mm else (max(lengths.values()) if lengths else 0.0)
        self._length_table.setRowCount(0)
        for n, l in lengths.items():
            r = self._length_table.rowCount()
            self._length_table.insertRow(r)
            self._length_table.setItem(r, 0, QTableWidgetItem(n))
            self._length_table.setItem(r, 1, QTableWidgetItem(f"{l:.3f}"))
            self._length_table.setItem(r, 2, QTableWidgetItem(f"{target - l:+.3f}"))

    def _match_group(self) -> None:
        if not _HAS_CORE:
            return
        cname = self._length_combo.currentText()
        router = self._current_router()
        if router is None:
            return
        result = router.length_match(cname)
        self._status.setText(result.message)
        self._measure_group()

    # ---- diff pair tab ----------------------------------------------
    def _build_diff_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        detect_btn = QPushButton("Detect Pairs")
        detect_btn.clicked.connect(self._detect_pairs)
        calc_btn = QPushButton("Calc Geometry")
        calc_btn.clicked.connect(self._calc_geometry)
        bar.addWidget(detect_btn)
        bar.addWidget(calc_btn)
        bar.addStretch(1)
        lay.addLayout(bar)

        self._diff_table = QTableWidget(0, 6)
        self._diff_table.setHorizontalHeaderLabels(
            ["Pair", "P net", "N net", "Z target (Ω)", "Width mm", "Gap mm"]
        )
        self._diff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._diff_table, 1)
        return w

    def _detect_pairs(self) -> None:
        if not _HAS_CORE or self._board is None:
            return
        dpr = DiffPairRouter(self._board, self._registry)
        pairs = dpr.detect_pairs()
        self._diff_table.setRowCount(0)
        for p in pairs:
            r = self._diff_table.rowCount()
            self._diff_table.insertRow(r)
            self._diff_table.setItem(r, 0, QTableWidgetItem(p.name))
            self._diff_table.setItem(r, 1, QTableWidgetItem(p.pos_net))
            self._diff_table.setItem(r, 2, QTableWidgetItem(p.neg_net))
            self._diff_table.setItem(r, 3, QTableWidgetItem(f"{p.target_impedance_ohm:.1f}"))
            self._diff_table.setItem(r, 4, QTableWidgetItem(f"{p.width_mm:.3f}"))
            self._diff_table.setItem(r, 5, QTableWidgetItem(f"{p.gap_mm:.3f}"))
        self._status.setText(f"Detected {len(pairs)} diff pair(s)")

    def _calc_geometry(self) -> None:
        if not _HAS_CORE or self._board is None:
            return
        dpr = DiffPairRouter(self._board, self._registry)
        r = self._diff_table.currentRow()
        if r < 0:
            return
        try:
            z = float(self._diff_table.item(r, 3).text())
        except Exception:  # noqa: BLE001
            z = 100.0
        w, s = dpr.calc_geometry(z)
        self._diff_table.setItem(r, 4, QTableWidgetItem(f"{w:.3f}"))
        self._diff_table.setItem(r, 5, QTableWidgetItem(f"{s:.3f}"))
        self._status.setText(f"Z={z}Ω -> w={w:.3f} mm, gap={s:.3f} mm")

    # ------------------------------------------------------------------
    def _refresh_all(self) -> None:
        if not _HAS_CORE:
            self._status.setText("openforge.pcb unavailable")
            return
        self._refresh_classes()
        self._refresh_assign()
        self._refresh_length()


__all__ = ["PcbRouterPanel"]
