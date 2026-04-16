"""Regression triage panel.

Clusters regression failures by fuzzy-hashing their error messages, shows a
per-cluster table with counts and sample tests, lets the user drill into
individual logs, rerun a cluster with different seeds for flake detection,
attach per-cluster triage notes, and export an HTML report.
"""

from __future__ import annotations

import contextlib
import hashlib
import html as _html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ._theme import panel_tab_qss
except Exception:  # pragma: no cover

    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TriageFailure:
    test_name: str
    log_path: Path
    message: str
    seed: int = 0


@dataclass
class TriageCluster:
    key: str
    count: int = 0
    first_line: str = ""
    sample_tests: list[str] = field(default_factory=list)
    failures: list[TriageFailure] = field(default_factory=list)
    note: str = ""


_NUM_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b\d+\b")
_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^ \t\"'\n]+|/[^ \t\"'\n]+")
_TIME_RE = re.compile(r"\[\d+\]|@\d+ns")


def fuzzy_hash(message: str) -> str:
    """Normalise numbers/paths/timestamps then hash for clustering."""
    norm = message.strip()
    norm = _TIME_RE.sub("<t>", norm)
    norm = _PATH_RE.sub("<path>", norm)
    norm = _NUM_RE.sub("<n>", norm)
    norm = re.sub(r"\s+", " ", norm)
    return hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()[:10]


def cluster_failures(failures: list[TriageFailure]) -> list[TriageCluster]:
    """Group failures by fuzzy hash of their first error line."""
    clusters: dict[str, TriageCluster] = {}
    for f in failures:
        first_line = next((ln for ln in f.message.splitlines() if ln.strip()), f.message)[:400]
        key = fuzzy_hash(first_line)
        cl = clusters.get(key)
        if cl is None:
            cl = TriageCluster(key=key, first_line=first_line)
            clusters[key] = cl
        cl.count += 1
        if f.test_name not in cl.sample_tests and len(cl.sample_tests) < 8:
            cl.sample_tests.append(f.test_name)
        cl.failures.append(f)
    return sorted(clusters.values(), key=lambda c: -c.count)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class RegressionTriagePanel(QWidget):
    """Panel that clusters regression failures for triage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RegressionTriagePanel")
        self._clusters: list[TriageCluster] = []
        self._current: TriageCluster | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title = QLabel("Regression triage")
        title.setStyleSheet("font-size:14px; font-weight:600;")
        root.addWidget(title)

        bar = QHBoxLayout()
        self._load_btn = QPushButton("Load results JSON...")
        self._load_btn.clicked.connect(self._on_load_results)
        bar.addWidget(self._load_btn)
        self._rerun_btn = QPushButton("Rerun cluster with new seeds")
        self._rerun_btn.clicked.connect(self._on_rerun_cluster)
        bar.addWidget(self._rerun_btn)
        self._export_btn = QPushButton("Export HTML report")
        self._export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._export_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        # Left: cluster table
        self._cluster_table = QTableWidget(0, 4)
        self._cluster_table.setHorizontalHeaderLabels(
            ["Key", "Count", "Sample test", "First error"]
        )
        self._cluster_table.horizontalHeader().setStretchLastSection(True)
        self._cluster_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._cluster_table.itemSelectionChanged.connect(self._on_cluster_selected)
        splitter.addWidget(self._cluster_table)

        # Right: drill-in
        right = QWidget()
        r_lay = QVBoxLayout(right)
        r_lay.setContentsMargins(4, 4, 4, 4)
        r_lay.addWidget(QLabel("Tests in cluster"))
        self._tests_table = QTableWidget(0, 3)
        self._tests_table.setHorizontalHeaderLabels(["Test", "Seed", "Log"])
        self._tests_table.horizontalHeader().setStretchLastSection(True)
        self._tests_table.itemSelectionChanged.connect(self._on_test_selected)
        r_lay.addWidget(self._tests_table, 1)

        r_lay.addWidget(QLabel("Log preview"))
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        mono = QFont("Consolas, 'Courier New', monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._log_view.setFont(mono)
        r_lay.addWidget(self._log_view, 1)

        r_lay.addWidget(QLabel("Triage notes"))
        self._notes = QPlainTextEdit()
        self._notes.textChanged.connect(self._on_notes_changed)
        self._notes.setMaximumHeight(100)
        r_lay.addWidget(self._notes)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self._status = QLabel("No results loaded.")
        self._status.setStyleSheet("color:#94a3b8;")
        root.addWidget(self._status)

        with contextlib.suppress(Exception):
            self.setStyleSheet(panel_tab_qss(True))

    # ------------------------------------------------------------------
    def set_results(self, failures: list[TriageFailure]) -> None:
        """Programmatic entrypoint: set failures directly."""
        self._clusters = cluster_failures(failures)
        self._refresh_cluster_table()
        self._status.setText(
            f"Clustered {sum(c.count for c in self._clusters)} failures "
            f"into {len(self._clusters)} clusters."
        )

    def _on_load_results(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load regression results", "", "JSON (*.json)")
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        failures: list[TriageFailure] = []
        entries = raw.get("failures", raw if isinstance(raw, list) else [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            failures.append(
                TriageFailure(
                    test_name=str(entry.get("test", entry.get("name", "?"))),
                    log_path=Path(entry.get("log", "")),
                    message=str(entry.get("message", entry.get("error", ""))),
                    seed=int(entry.get("seed", 0) or 0),
                )
            )
        self.set_results(failures)

    def _refresh_cluster_table(self) -> None:
        self._cluster_table.setRowCount(0)
        for cl in self._clusters:
            row = self._cluster_table.rowCount()
            self._cluster_table.insertRow(row)
            self._cluster_table.setItem(row, 0, QTableWidgetItem(cl.key))
            self._cluster_table.setItem(row, 1, QTableWidgetItem(str(cl.count)))
            self._cluster_table.setItem(
                row, 2, QTableWidgetItem(cl.sample_tests[0] if cl.sample_tests else "")
            )
            self._cluster_table.setItem(row, 3, QTableWidgetItem(cl.first_line))

    def _on_cluster_selected(self) -> None:
        row = self._cluster_table.currentRow()
        if row < 0 or row >= len(self._clusters):
            self._current = None
            self._tests_table.setRowCount(0)
            return
        cl = self._clusters[row]
        self._current = cl
        self._tests_table.setRowCount(0)
        for f in cl.failures:
            r = self._tests_table.rowCount()
            self._tests_table.insertRow(r)
            self._tests_table.setItem(r, 0, QTableWidgetItem(f.test_name))
            self._tests_table.setItem(r, 1, QTableWidgetItem(str(f.seed)))
            self._tests_table.setItem(r, 2, QTableWidgetItem(str(f.log_path)))
        self._notes.blockSignals(True)
        self._notes.setPlainText(cl.note)
        self._notes.blockSignals(False)
        self._log_view.setPlainText("")

    def _on_test_selected(self) -> None:
        if self._current is None:
            return
        row = self._tests_table.currentRow()
        if row < 0 or row >= len(self._current.failures):
            return
        f = self._current.failures[row]
        try:
            if f.log_path and f.log_path.exists():
                text = f.log_path.read_text(encoding="utf-8", errors="ignore")
            else:
                text = f.message
        except Exception as exc:
            text = f"<error reading log: {exc}>"
        self._log_view.setPlainText(text)

    def _on_notes_changed(self) -> None:
        if self._current is None:
            return
        self._current.note = self._notes.toPlainText()

    def _on_rerun_cluster(self) -> None:
        if self._current is None:
            self._status.setText("Select a cluster first.")
            return
        # Produce a rerun spec file that an external runner can consume.
        base = Path.cwd() / "triage_rerun"
        base.mkdir(parents=True, exist_ok=True)
        spec = {
            "cluster": self._current.key,
            "tests": [
                {"name": f.test_name, "seeds": [f.seed + i for i in range(1, 4)]}
                for f in self._current.failures
            ],
        }
        out = base / f"{self._current.key}.json"
        out.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        self._status.setText(f"Wrote rerun spec: {out}")

    def _on_export(self) -> None:
        if not self._clusters:
            self._status.setText("Nothing to export.")
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Export triage report", "triage_report.html", "HTML (*.html)"
        )
        if not target:
            return
        rows: list[str] = []
        for cl in self._clusters:
            rows.append(
                "<tr>"
                f"<td>{_html.escape(cl.key)}</td>"
                f"<td>{cl.count}</td>"
                f"<td>{_html.escape(cl.first_line)}</td>"
                f"<td>{_html.escape(', '.join(cl.sample_tests))}</td>"
                f"<td>{_html.escape(cl.note)}</td>"
                "</tr>"
            )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>OpenForge triage</title>"
            "<style>body{background:#11111b;color:#cdd6f4;font-family:sans-serif}"
            "table{border-collapse:collapse}td,th{border:1px solid #45475a;padding:4px}"
            "</style></head><body><h1>Regression triage report</h1>"
            "<table><tr><th>Key</th><th>Count</th><th>First error</th>"
            "<th>Sample tests</th><th>Notes</th></tr>" + "".join(rows) + "</table></body></html>"
        )
        try:
            Path(target).write_text(html, encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._status.setText(f"Exported: {target}")
