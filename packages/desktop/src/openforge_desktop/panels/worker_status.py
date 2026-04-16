"""Worker Status panel.

Displays the distributed worker pool managed by
:class:`openforge.runner.dispatch.WorkerPool`, with add/remove/health
and per-worker run history.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.runner.dispatch import WorkerNode, WorkerPool
except Exception:  # pragma: no cover
    WorkerNode = None  # type: ignore[assignment]
    WorkerPool = None  # type: ignore[assignment]


_BG = "#11131a"
_SURFACE = "#1b1e27"
_TEXT = "#e5e9f0"
_BORDER = "#2b3040"
_ACCENT = "#4c8dff"


_HEADERS = ["URL", "Name", "Capabilities", "Load", "Status", "Last Seen"]


class WorkerStatusPanel(QWidget):
    """Table of registered remote workers."""

    def __init__(self, pool: WorkerPool | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkerStatusPanel")
        self.setStyleSheet(
            f"QWidget#WorkerStatusPanel {{ background: {_BG}; color: {_TEXT}; }}"
            f"QLabel {{ color: {_TEXT}; }}"
            f"QPushButton {{ background: {_SURFACE}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border: 1px solid {_ACCENT}; }}"
            f"QTableWidget {{ background: {_SURFACE}; color: {_TEXT};"
            f" gridline-color: {_BORDER}; border: 1px solid {_BORDER}; }}"
            f"QHeaderView::section {{ background: {_SURFACE}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; padding: 4px; }}"
        )

        if pool is None and WorkerPool is not None:
            pool = WorkerPool(workers=[])
        self.pool = pool
        self._history: dict[str, list[str]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Distributed workers:"))
        bar.addStretch(1)
        self.add_btn = QPushButton("Add Worker...")
        self.add_btn.clicked.connect(self._on_add)
        bar.addWidget(self.add_btn)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._on_remove)
        bar.addWidget(self.remove_btn)
        self.health_btn = QPushButton("Health Check")
        self.health_btn.clicked.connect(self._on_health)
        bar.addWidget(self.health_btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.itemSelectionChanged.connect(self._refresh_history)
        root.addWidget(self.table, 1)

        self.history_label = QLabel("Run history (selected worker):")
        root.addWidget(self.history_label)
        self.history = QTableWidget(0, 2)
        self.history.setHorizontalHeaderLabels(["Run ID", "Status"])
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.history)

        self._refresh_table()

    # ----- helpers ---------------------------------------------------------

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        if self.pool is None:
            return
        for w in self.pool.workers:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(w.url))
            self.table.setItem(row, 1, QTableWidgetItem(w.name))
            self.table.setItem(row, 2, QTableWidgetItem(", ".join(w.capabilities)))
            self.table.setItem(row, 3, QTableWidgetItem(str(w.current_load)))
            self.table.setItem(row, 4, QTableWidgetItem(w.status))
            self.table.setItem(row, 5, QTableWidgetItem(f"{w.last_seen:.0f}" if w.last_seen else ""))

    def _selected_worker(self):  # type: ignore[no-untyped-def]
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or self.pool is None:
            return None
        idx = rows[0].row()
        if idx < 0 or idx >= len(self.pool.workers):
            return None
        return self.pool.workers[idx]

    def _refresh_history(self) -> None:
        self.history.setRowCount(0)
        w = self._selected_worker()
        if w is None:
            return
        for entry in self._history.get(w.url, []):
            row = self.history.rowCount()
            self.history.insertRow(row)
            parts = entry.split("|", 1)
            run_id = parts[0]
            status = parts[1] if len(parts) > 1 else ""
            self.history.setItem(row, 0, QTableWidgetItem(run_id))
            self.history.setItem(row, 1, QTableWidgetItem(status))

    # ----- slots -----------------------------------------------------------

    def _on_add(self) -> None:
        if self.pool is None or WorkerNode is None:
            QMessageBox.warning(self, "Add Worker", "Dispatch module not available.")
            return
        url, ok = QInputDialog.getText(self, "Add Worker", "Worker URL (e.g. http://host:8765):")
        if not ok or not url.strip():
            return
        url = url.strip().rstrip("/")
        if any(w.url == url for w in self.pool.workers):
            QMessageBox.information(self, "Add Worker", "Worker already registered.")
            return
        name, _ok = QInputDialog.getText(self, "Add Worker", "Name:", text=url)
        self.pool.workers.append(
            WorkerNode(url=url, name=(name or url), capabilities=[], status="unknown", current_load=0)
        )
        self._refresh_table()

    def _on_remove(self) -> None:
        w = self._selected_worker()
        if w is None or self.pool is None:
            return
        self.pool.workers = [x for x in self.pool.workers if x.url != w.url]
        self._refresh_table()

    def _on_health(self) -> None:
        if self.pool is None:
            return
        try:
            result = self.pool.health_check()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Health Check", f"Failed: {e}")
            return
        self._refresh_table()
        QMessageBox.information(
            self,
            "Health Check",
            "\n".join(f"{k}: {v}" for k, v in result.items()) or "No workers registered.",
        )

    def record_run(self, worker_url: str, run_id: str, status: str) -> None:
        self._history.setdefault(worker_url, []).append(f"{run_id}|{status}")
        self._refresh_history()


__all__ = ["WorkerStatusPanel"]
