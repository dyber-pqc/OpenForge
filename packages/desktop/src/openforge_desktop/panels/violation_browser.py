"""Unified multi-physics violation browser panel.

Shows every violation from every sign-off engine in a single table backed
by :class:`openforge.physical.violation_db.ViolationDb`. Supports
filter-by-kind/severity/instance, a heatmap thumbnail of filtered
violations, cross-probing to layout viewer, waiver creation, and
import from other panels.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    import numpy as np
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    _HAVE_MPL = True
except Exception:  # pragma: no cover
    _HAVE_MPL = False
    FigureCanvas = object  # type: ignore[assignment,misc]
    Figure = object  # type: ignore[assignment,misc]

try:
    from openforge.physical.violation_db import (
        VALID_KINDS,
        VALID_SEVERITIES,
        Violation,
        ViolationDb,
        ViolationImporter,
    )
    _HAVE_DB = True
except Exception:  # pragma: no cover
    VALID_KINDS = set()  # type: ignore[assignment]
    VALID_SEVERITIES = ()  # type: ignore[assignment]
    Violation = None  # type: ignore[assignment,misc]
    ViolationDb = None  # type: ignore[assignment,misc]
    ViolationImporter = None  # type: ignore[assignment,misc]
    _HAVE_DB = False


class _ScoreTile(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #1a1a1a; border: 1px solid #333; border-radius: 6px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self._score = QLabel("--")
        self._score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._score.setStyleSheet("font-size: 48px; font-weight: bold; color: #7abaff;")
        self._sub = QLabel("Sign-off score")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setStyleSheet("color:#aaa;")
        lay.addWidget(self._score)
        lay.addWidget(self._sub)

    def set_score(self, score: float, total: int) -> None:
        color = "#2e8b57" if score > 90 else ("#d48806" if score > 70 else "#cf1322")
        self._score.setText(f"{score:.1f}")
        self._score.setStyleSheet(
            f"font-size: 48px; font-weight: bold; color: {color};"
        )
        self._sub.setText(f"Sign-off score  |  {total} violations")


class ViolationBrowserPanel(QWidget):
    """Unified multi-physics violation browser."""

    # Emitted when user clicks a violation with a known location, so the
    # layout viewer can pan/highlight.
    cross_probe = Signal(float, float, str)  # x_um, y_um, label

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = ViolationDb() if _HAVE_DB else None
        self._filtered: list["Violation"] = []
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------
    def db(self) -> Optional["ViolationDb"]:
        return self._db

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Filter bar
        filter_row = QHBoxLayout()
        self._kind_combo = QComboBox()
        self._kind_combo.addItem("All kinds", None)
        for k in sorted(VALID_KINDS):
            self._kind_combo.addItem(k, k)
        self._kind_combo.currentIndexChanged.connect(self._refresh)
        self._sev_combo = QComboBox()
        self._sev_combo.addItem("All severities", None)
        for s in VALID_SEVERITIES:
            self._sev_combo.addItem(s, s)
        self._sev_combo.currentIndexChanged.connect(self._refresh)
        self._search = QLineEdit()
        self._search.setPlaceholderText("search instance / net / layer")
        self._search.textChanged.connect(self._refresh)
        self._group_combo = QComboBox()
        self._group_combo.addItems(["Flat", "Group by kind", "Group by severity"])
        self._group_combo.currentIndexChanged.connect(self._refresh)

        filter_row.addWidget(QLabel("Kind:"))
        filter_row.addWidget(self._kind_combo)
        filter_row.addWidget(QLabel("Severity:"))
        filter_row.addWidget(self._sev_combo)
        filter_row.addWidget(self._search, 1)
        filter_row.addWidget(self._group_combo)
        root.addLayout(filter_row)

        # Action bar
        action_row = QHBoxLayout()
        self._import_btn = QPushButton("Import all")
        self._import_btn.clicked.connect(self._import_all)
        self._waive_btn = QPushButton("Create Waiver")
        self._waive_btn.clicked.connect(self._waive_selected)
        self._export_json_btn = QPushButton("Export JSON")
        self._export_json_btn.clicked.connect(lambda: self._export("json"))
        self._export_csv_btn = QPushButton("Export CSV")
        self._export_csv_btn.clicked.connect(lambda: self._export("csv"))
        self._export_html_btn = QPushButton("Export HTML")
        self._export_html_btn.clicked.connect(lambda: self._export("html"))
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_db)
        for b in (
            self._import_btn, self._waive_btn, self._export_json_btn,
            self._export_csv_btn, self._export_html_btn, self._clear_btn,
        ):
            action_row.addWidget(b)
        action_row.addStretch(1)
        root.addLayout(action_row)

        # Body: table + right panel
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["Kind", "Sev", "Location", "Instance", "Net/Layer",
             "Value", "Unit", "Delta", "Suggestion"]
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._selection_changed)
        self._table.cellDoubleClicked.connect(self._double_clicked)
        splitter.addWidget(self._table)

        # Right pane
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        self._tile = _ScoreTile()
        rl.addWidget(self._tile)

        grp_det = QGroupBox("Details")
        det_lay = QVBoxLayout(grp_det)
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        det_lay.addWidget(self._details)
        rl.addWidget(grp_det, 1)

        grp_heat = QGroupBox("Location heatmap")
        heat_lay = QVBoxLayout(grp_heat)
        if _HAVE_MPL:
            self._heat_fig = Figure(figsize=(3.5, 3), facecolor="#111")
            self._heat_canvas = FigureCanvas(self._heat_fig)
            self._heat_ax = self._heat_fig.add_subplot(111)
            self._heat_ax.set_facecolor("#111")
            heat_lay.addWidget(self._heat_canvas)
        else:
            heat_lay.addWidget(QLabel("matplotlib unavailable"))
            self._heat_fig = None
            self._heat_canvas = None
            self._heat_ax = None
        rl.addWidget(grp_heat, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        if not _HAVE_DB:
            warn = QLabel("Violation DB unavailable")
            warn.setStyleSheet("color:#cf1322;")
            root.addWidget(warn)
            for b in (
                self._import_btn, self._waive_btn, self._export_json_btn,
                self._export_csv_btn, self._export_html_btn, self._clear_btn,
            ):
                b.setEnabled(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_violations(self, violations: list["Violation"]) -> None:
        if self._db is None:
            return
        self._db.add_bulk(violations)
        self._refresh()

    def import_from(
        self,
        sta: object = None,
        drc: object = None,
        ir: object = None,
        em: object = None,
        thermal: object = None,
        antenna: object = None,
        glitch: object = None,
        crosstalk: object = None,
        lvs: object = None,
    ) -> int:
        if self._db is None or ViolationImporter is None:
            return 0
        count = ViolationImporter.import_all(
            self._db,
            sta=sta, drc=drc, ir=ir, em=em, thermal=thermal,
            antenna=antenna, glitch=glitch, crosstalk=crosstalk, lvs=lvs,
        )
        self._refresh()
        return count

    # ------------------------------------------------------------------
    def _import_all(self) -> None:
        """Collect result objects from sibling panels in the main window."""
        if self._db is None:
            return
        mw = self.window()
        kwargs: dict[str, object] = {}
        # Look for commonly-named results on other panels
        for attr, key in (
            ("_signoff_dashboard", "sta"),
            ("_drc_browser", "drc"),
            ("_ir_drop_overlay", "ir"),
            ("_thermal_panel", "thermal"),
            ("_em_panel", "em"),
            ("_pba_xtalk", "crosstalk"),
        ):
            w = getattr(mw, attr, None)
            if w is None:
                continue
            inner = getattr(w, "widget", None)
            target = inner() if callable(inner) else w
            for probe in ("last_result", "result", "_result", "_last_result"):
                val = getattr(target, probe, None)
                if val is not None:
                    kwargs[key] = val
                    break
        count = ViolationImporter.import_all(self._db, **kwargs)  # type: ignore[arg-type]
        self._refresh()
        QMessageBox.information(
            self, "Import complete", f"Imported {count} violations from sibling panels."
        )

    def _clear_db(self) -> None:
        if self._db is None:
            return
        self._db.clear()
        self._refresh()

    # ------------------------------------------------------------------
    def _current_filter(self) -> list["Violation"]:
        if self._db is None:
            return []
        kind = self._kind_combo.currentData()
        sev = self._sev_combo.currentData()
        query = self._search.text().strip().lower()
        out = self._db.query(kind=kind, severity=sev)
        if query:
            def _match(v: "Violation") -> bool:
                hay = " ".join([
                    (v.instance or ""), (v.net or ""), (v.layer or ""),
                    v.suggestion or "",
                ]).lower()
                return query in hay
            out = [v for v in out if _match(v)]
        return out

    def _refresh(self) -> None:
        vs = self._current_filter()
        mode = self._group_combo.currentText() if hasattr(self, "_group_combo") else "Flat"
        if mode == "Group by kind":
            vs.sort(key=lambda v: (v.kind, -abs(v.delta)))
        elif mode == "Group by severity":
            order = {s: i for i, s in enumerate(["critical", "major", "minor", "info"])}
            vs.sort(key=lambda v: (order.get(v.severity, 99), -abs(v.delta)))
        else:
            vs.sort(key=lambda v: -abs(v.delta))

        self._filtered = vs

        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        sev_color = {
            "critical": QColor("#cf1322"),
            "major": QColor("#d48806"),
            "minor": QColor("#7abaff"),
            "info": QColor("#888"),
        }
        for v in vs:
            r = self._table.rowCount()
            self._table.insertRow(r)
            loc = f"{v.location[0]:.1f},{v.location[1]:.1f}" if v.location else ""
            net_layer = v.net or v.layer or ""
            cells = [
                v.kind,
                v.severity,
                loc,
                v.instance or "",
                net_layer,
                f"{v.metric_value:.3f}",
                v.metric_unit,
                f"{v.delta:.3f}",
                (v.suggestion or "")[:80],
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.ItemDataRole.UserRole, v.id)
                if col == 1:
                    item.setForeground(sev_color.get(v.severity, QColor("#ccc")))
                if v.waiver_id:
                    item.setForeground(QColor("#555"))
                self._table.setItem(r, col, item)
        self._table.setSortingEnabled(True)

        # Score tile
        if self._db is not None:
            self._tile.set_score(self._db.signoff_score(), self._db.total_count())

        # Heatmap
        self._render_heatmap(vs)

    def _render_heatmap(self, vs: list["Violation"]) -> None:
        if not _HAVE_MPL or self._heat_ax is None:
            return
        self._heat_ax.clear()
        pts_x: list[float] = []
        pts_y: list[float] = []
        weights: list[float] = []
        w_map = {"critical": 4.0, "major": 2.0, "minor": 1.0, "info": 0.5}
        for v in vs:
            if v.location is None:
                continue
            pts_x.append(v.location[0])
            pts_y.append(v.location[1])
            weights.append(w_map.get(v.severity, 1.0))
        if pts_x:
            self._heat_ax.hexbin(
                pts_x, pts_y, C=weights, reduce_C_function=np.sum,
                gridsize=30, cmap="inferno",
            )
            self._heat_ax.set_xlabel("x (um)", color="#ccc")
            self._heat_ax.set_ylabel("y (um)", color="#ccc")
        else:
            self._heat_ax.text(
                0.5, 0.5, "no located violations",
                ha="center", va="center", color="#888",
                transform=self._heat_ax.transAxes,
            )
        self._heat_ax.tick_params(colors="#ccc")
        for sp in self._heat_ax.spines.values():
            sp.set_color("#444")
        if self._heat_canvas is not None:
            self._heat_canvas.draw_idle()

    # ------------------------------------------------------------------
    def _selected_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in self._table.selectedItems():
            vid = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(vid, str) and vid not in seen:
                seen.add(vid)
                ids.append(vid)
        return ids

    def _selection_changed(self) -> None:
        ids = set(self._selected_ids())
        if not ids or self._db is None:
            self._details.clear()
            return
        lines: list[str] = []
        for v in self._db.all():
            if v.id not in ids:
                continue
            lines.append(f"[{v.kind.upper()}  {v.severity}]")
            if v.instance:
                lines.append(f"  instance : {v.instance}")
            if v.net:
                lines.append(f"  net      : {v.net}")
            if v.layer:
                lines.append(f"  layer    : {v.layer}")
            if v.location:
                lines.append(
                    f"  location : ({v.location[0]:.2f}, {v.location[1]:.2f}) um"
                )
            lines.append(
                f"  value    : {v.metric_value:.3f} {v.metric_unit}"
                f"  (threshold {v.threshold:.3f}, delta {v.delta:+.3f})"
            )
            lines.append(f"  source   : {v.source}")
            if v.waiver_id:
                lines.append(f"  WAIVED   : {v.waiver_id}")
            if v.suggestion:
                lines.append(f"  fix      : {v.suggestion}")
            lines.append("")
        self._details.setPlainText("\n".join(lines))

    def _double_clicked(self, row: int, col: int) -> None:
        item = self._table.item(row, 0)
        if item is None or self._db is None:
            return
        vid = item.data(Qt.ItemDataRole.UserRole)
        for v in self._db.all():
            if v.id != vid:
                continue
            if v.location is not None:
                label = f"{v.kind}: {v.instance or v.net or ''}"
                self.cross_probe.emit(
                    float(v.location[0]), float(v.location[1]), label
                )
            break

    # ------------------------------------------------------------------
    def _waive_selected(self) -> None:
        if self._db is None:
            return
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "Waiver", "Select violations first.")
            return
        waiver_id, ok = QInputDialog.getText(
            self, "Waiver ID", "Waiver identifier:", text="WVR-001"
        )
        if not ok or not waiver_id.strip():
            return
        justification, ok = QInputDialog.getMultiLineText(
            self, "Waiver justification", "Justification:"
        )
        if not ok:
            return
        n = self._db.waive_bulk(ids, waiver_id.strip(), justification.strip())
        self._refresh()
        QMessageBox.information(self, "Waiver", f"Waived {n} violations as {waiver_id}.")

    # ------------------------------------------------------------------
    def _export(self, fmt: str) -> None:
        if self._db is None:
            return
        default = f"violations.{fmt}"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", default,
            f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        try:
            if fmt == "json":
                self._db.export_json(Path(path))
            elif fmt == "csv":
                self._db.export_csv(Path(path))
            else:
                self._db.export_html(Path(path))
            QMessageBox.information(self, "Exported", f"Wrote {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))


__all__ = ["ViolationBrowserPanel"]
