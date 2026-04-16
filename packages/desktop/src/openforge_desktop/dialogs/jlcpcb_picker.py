"""JLCPCB part picker dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

try:
    from openforge.pcb.jlcpcb import JlcPartPicker, LcscPart

    _HAS_JLC = True
except Exception:  # noqa: BLE001
    _HAS_JLC = False


class JlcpcbPickerDialog(QDialog):
    """Search JLCPCB Basic parts, link to board components, export BOM/CPL."""

    def __init__(
        self,
        board: Any = None,
        parent=None,
        picker: JlcPartPicker | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("JLCPCB Part Picker")
        self.resize(900, 600)
        self._board = board
        self._picker = picker
        if self._picker is None and _HAS_JLC:
            self._picker = JlcPartPicker()

        self._build_ui()
        self._refresh_results("")
        self._refresh_refs()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)

        # Search row
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("10k, 100nF, AMS1117, 0603 ...")
        search_row.addWidget(self._search_edit, 1)
        lay.addLayout(search_row)

        # Results table
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["LCSC #", "Name", "Package", "Mfr", "Basic", "Price", "Stock"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self._table, 1)

        # Link row
        link_row = QHBoxLayout()
        link_row.addWidget(QLabel("Link to ref:"))
        self._ref_combo = QComboBox()
        self._ref_combo.setMinimumWidth(120)
        link_row.addWidget(self._ref_combo)
        self._link_btn = QPushButton("Link")
        link_row.addWidget(self._link_btn)
        link_row.addStretch(1)
        self._bom_btn = QPushButton("Export JLC BOM")
        self._cpl_btn = QPushButton("Export JLC CPL")
        self._close_btn = QPushButton("Close")
        link_row.addWidget(self._bom_btn)
        link_row.addWidget(self._cpl_btn)
        link_row.addWidget(self._close_btn)
        lay.addLayout(link_row)

        self._status = QLabel()
        self._status.setStyleSheet("color: #888;")
        lay.addWidget(self._status)

        # Signals
        self._search_edit.textChanged.connect(self._refresh_results)
        self._link_btn.clicked.connect(self._on_link)
        self._bom_btn.clicked.connect(self._on_export_bom)
        self._cpl_btn.clicked.connect(self._on_export_cpl)
        self._close_btn.clicked.connect(self.accept)

    # ------------------------------------------------------------------
    def _refresh_results(self, query: str) -> None:
        self._table.setRowCount(0)
        if not _HAS_JLC or self._picker is None:
            return
        parts = self._picker.search(query, limit=200) if query else self._picker.all_parts()
        self._table.setRowCount(len(parts))
        for row, p in enumerate(parts):
            self._table.setItem(row, 0, QTableWidgetItem(p.lcsc_part_number))
            self._table.setItem(row, 1, QTableWidgetItem(p.name))
            self._table.setItem(row, 2, QTableWidgetItem(p.package))
            self._table.setItem(row, 3, QTableWidgetItem(p.manufacturer))
            self._table.setItem(row, 4, QTableWidgetItem("Basic" if p.is_basic else "Extended"))
            self._table.setItem(row, 5, QTableWidgetItem(f"${p.price_per_unit:.4f}"))
            self._table.setItem(row, 6, QTableWidgetItem(str(p.stock)))
        self._status.setText(f"{len(parts)} parts")

    def _refresh_refs(self) -> None:
        self._ref_combo.clear()
        if self._board is None:
            return
        for fp in getattr(self._board, "footprints", []):
            self._ref_combo.addItem(f"{fp.ref} ({fp.value})")

    def _selected_part(self) -> LcscPart | None:
        if not _HAS_JLC or self._picker is None:
            return None
        row = self._table.currentRow()
        if row < 0:
            return None
        lcsc = self._table.item(row, 0).text()
        for p in self._picker.all_parts():
            if p.lcsc_part_number == lcsc:
                return p
        return None

    # ------------------------------------------------------------------
    def _on_link(self) -> None:
        part = self._selected_part()
        if part is None or self._picker is None:
            QMessageBox.warning(self, "JLC Picker", "Select a part first.")
            return
        ref_text = self._ref_combo.currentText()
        if not ref_text:
            QMessageBox.warning(self, "JLC Picker", "No board ref selected.")
            return
        ref = ref_text.split(" ")[0]
        self._picker.link_part(ref, part.lcsc_part_number)
        self._status.setText(f"Linked {ref} -> {part.lcsc_part_number}")

    def _on_export_bom(self) -> None:
        if self._board is None or self._picker is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JLCPCB BOM", "bom_jlc.csv", "CSV (*.csv)"
        )
        if not path:
            return
        out = self._picker.export_jlc_bom(self._board, Path(path))
        self._status.setText(f"BOM written: {out}")

    def _on_export_cpl(self) -> None:
        if self._board is None or self._picker is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JLCPCB CPL", "cpl_jlc.csv", "CSV (*.csv)"
        )
        if not path:
            return
        out = self._picker.export_jlc_cpl(self._board, Path(path))
        self._status.setText(f"CPL written: {out}")


__all__ = ["JlcpcbPickerDialog"]
