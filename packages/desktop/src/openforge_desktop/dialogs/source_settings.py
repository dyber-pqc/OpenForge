"""Source settings dialog -- per-file language/library/testbench metadata
plus project-wide include dirs, defines, and language version."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_LANGUAGES = ["auto", "verilog", "systemverilog", "vhdl"]
_LANG_VERSIONS = ["v2005", "sv2012", "sv2017", "vhdl93", "vhdl2008"]


class SourceSettingsDialog(QDialog):
    """Dialog for editing per-source-file and project-wide HDL settings."""

    settings_changed = Signal(dict)

    def __init__(self, project_config: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Source Settings")
        self.resize(780, 620)
        self._project_config = project_config

        layout = QVBoxLayout(self)

        # ---- Source files table ----------------------------------------
        files_box = QGroupBox("Source Files")
        files_layout = QVBoxLayout(files_box)

        self.files_table = QTableWidget(0, 4, self)
        self.files_table.setHorizontalHeaderLabels(
            ["File", "Language", "Library", "Testbench"]
        )
        header = self.files_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        files_layout.addWidget(self.files_table)

        files_buttons = QHBoxLayout()
        self.add_file_btn = QPushButton("Add File...")
        self.remove_file_btn = QPushButton("Remove")
        self.add_file_btn.clicked.connect(self._on_add_file)
        self.remove_file_btn.clicked.connect(self._on_remove_file)
        files_buttons.addWidget(self.add_file_btn)
        files_buttons.addWidget(self.remove_file_btn)
        files_buttons.addStretch(1)
        files_layout.addLayout(files_buttons)
        layout.addWidget(files_box)

        # ---- Include directories ---------------------------------------
        inc_box = QGroupBox("Include Directories")
        inc_layout = QVBoxLayout(inc_box)
        self.includes_list = QListWidget(self)
        inc_layout.addWidget(self.includes_list)
        inc_buttons = QHBoxLayout()
        self.add_inc_btn = QPushButton("Add...")
        self.remove_inc_btn = QPushButton("Remove")
        self.add_inc_btn.clicked.connect(self._on_add_include)
        self.remove_inc_btn.clicked.connect(self._on_remove_include)
        inc_buttons.addWidget(self.add_inc_btn)
        inc_buttons.addWidget(self.remove_inc_btn)
        inc_buttons.addStretch(1)
        inc_layout.addLayout(inc_buttons)
        layout.addWidget(inc_box)

        # ---- Defines ----------------------------------------------------
        def_box = QGroupBox("Preprocessor Defines")
        def_layout = QVBoxLayout(def_box)
        self.defines_table = QTableWidget(0, 2, self)
        self.defines_table.setHorizontalHeaderLabels(["Name", "Value"])
        self.defines_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        def_layout.addWidget(self.defines_table)
        def_buttons = QHBoxLayout()
        self.add_def_btn = QPushButton("Add")
        self.remove_def_btn = QPushButton("Remove")
        self.add_def_btn.clicked.connect(self._on_add_define)
        self.remove_def_btn.clicked.connect(self._on_remove_define)
        def_buttons.addWidget(self.add_def_btn)
        def_buttons.addWidget(self.remove_def_btn)
        def_buttons.addStretch(1)
        def_layout.addLayout(def_buttons)
        layout.addWidget(def_box)

        # ---- Language version ------------------------------------------
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language Version:"))
        self.lang_combo = QComboBox(self)
        self.lang_combo.addItems(_LANG_VERSIONS)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch(1)
        layout.addLayout(lang_row)

        # ---- OK / Cancel -----------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_from_config(project_config)

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load_from_config(self, cfg: Any) -> None:
        proj = getattr(cfg, "project", None)
        if proj is None:
            return

        # Sources come from DesignConfig (list of strings) or a dedicated
        # source_files field if present.
        sources = getattr(cfg, "source_files", None)
        if sources is None:
            design = getattr(cfg, "design", None)
            raw = list(getattr(design, "sources", []) or []) if design else []
            sources = [{"path": s, "library": "work", "language": "auto",
                        "is_testbench": False} for s in raw]

        for src in sources:
            if hasattr(src, "path"):
                path = str(src.path)
                lang = getattr(src, "language", "auto")
                lib = getattr(src, "library", "work")
                tb = bool(getattr(src, "is_testbench", False))
            else:
                path = str(src.get("path", ""))
                lang = src.get("language", "auto")
                lib = src.get("library", "work")
                tb = bool(src.get("is_testbench", False))
            self._append_file_row(path, lang, lib, tb)

        for d in getattr(proj, "include_dirs", []) or []:
            self.includes_list.addItem(str(d))

        for name, value in (getattr(proj, "defines", {}) or {}).items():
            self._append_define_row(name, value)

        lang_ver = getattr(proj, "language_version", "sv2017")
        idx = self.lang_combo.findText(lang_ver)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

    def _append_file_row(self, path: str, language: str, library: str, tb: bool) -> None:
        row = self.files_table.rowCount()
        self.files_table.insertRow(row)
        self.files_table.setItem(row, 0, QTableWidgetItem(path))

        lang_cb = QComboBox()
        lang_cb.addItems(_LANGUAGES)
        lang_cb.setCurrentText(language if language in _LANGUAGES else "auto")
        self.files_table.setCellWidget(row, 1, lang_cb)

        self.files_table.setItem(row, 2, QTableWidgetItem(library or "work"))

        tb_item = QTableWidgetItem()
        tb_item.setFlags(tb_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        tb_item.setCheckState(Qt.CheckState.Checked if tb else Qt.CheckState.Unchecked)
        self.files_table.setItem(row, 3, tb_item)

    def _append_define_row(self, name: str, value: str) -> None:
        row = self.defines_table.rowCount()
        self.defines_table.insertRow(row)
        self.defines_table.setItem(row, 0, QTableWidgetItem(str(name)))
        self.defines_table.setItem(row, 1, QTableWidgetItem(str(value)))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select HDL Sources",
            "",
            "HDL Files (*.v *.sv *.svh *.vhd *.vhdl);;All Files (*.*)",
        )
        for p in paths:
            self._append_file_row(p, "auto", "work", False)

    def _on_remove_file(self) -> None:
        rows = sorted({i.row() for i in self.files_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.files_table.removeRow(r)

    def _on_add_include(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Include Directory")
        if d:
            self.includes_list.addItem(d)

    def _on_remove_include(self) -> None:
        for item in self.includes_list.selectedItems():
            self.includes_list.takeItem(self.includes_list.row(item))

    def _on_add_define(self) -> None:
        self._append_define_row("NAME", "1")

    def _on_remove_define(self) -> None:
        rows = sorted({i.row() for i in self.defines_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.defines_table.removeRow(r)

    def _on_accept(self) -> None:
        data = self.collect_settings()
        self.settings_changed.emit(data)
        self.accept()

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    def collect_settings(self) -> dict:
        sources: list[dict] = []
        for row in range(self.files_table.rowCount()):
            path_item = self.files_table.item(row, 0)
            if path_item is None:
                continue
            lang_cb = self.files_table.cellWidget(row, 1)
            lib_item = self.files_table.item(row, 2)
            tb_item = self.files_table.item(row, 3)
            sources.append(
                {
                    "path": path_item.text(),
                    "language": lang_cb.currentText() if lang_cb else "auto",
                    "library": lib_item.text() if lib_item else "work",
                    "is_testbench": (
                        tb_item is not None
                        and tb_item.checkState() == Qt.CheckState.Checked
                    ),
                }
            )

        includes: list[str] = []
        for i in range(self.includes_list.count()):
            includes.append(self.includes_list.item(i).text())

        defines: dict[str, str] = {}
        for row in range(self.defines_table.rowCount()):
            name_item = self.defines_table.item(row, 0)
            val_item = self.defines_table.item(row, 1)
            if name_item and name_item.text().strip():
                defines[name_item.text().strip()] = val_item.text() if val_item else ""

        return {
            "source_files": sources,
            "project": {
                "include_dirs": includes,
                "defines": defines,
                "language_version": self.lang_combo.currentText(),
            },
        }
