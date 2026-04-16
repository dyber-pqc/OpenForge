"""Import Project dialog.

Lets the user pick a Vivado / OpenLane2 / KiCad / Quartus project and
preview what will be imported before creating a new OpenForge project.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:  # pragma: no cover - optional import at runtime
    from openforge.project.importers import (
        import_kicad_project,
        import_openlane_dir,
        import_quartus_qpf,
        import_xpr,
    )
    from openforge.project.model import Project
except Exception:  # pragma: no cover
    import_xpr = None  # type: ignore[assignment]
    import_openlane_dir = None  # type: ignore[assignment]
    import_kicad_project = None  # type: ignore[assignment]
    import_quartus_qpf = None  # type: ignore[assignment]
    Project = None  # type: ignore[assignment]


_BG = "#11131a"
_SURFACE = "#1b1e27"
_TEXT = "#e5e9f0"
_BORDER = "#2b3040"
_ACCENT = "#4c8dff"


_KINDS = [
    ("Vivado (.xpr)", "vivado", "Vivado Project (*.xpr)"),
    ("OpenLane2 (directory)", "openlane2", ""),
    ("KiCad (.kicad_pro)", "kicad", "KiCad Project (*.kicad_pro)"),
    ("Quartus (.qpf)", "quartus", "Quartus Project (*.qpf)"),
]


class ImportProjectDialog(QDialog):
    """Dialog to import a third-party project into OpenForge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Project")
        self.resize(720, 560)
        self.setStyleSheet(
            f"QDialog {{ background: {_BG}; color: {_TEXT}; }}"
            f"QLabel {{ color: {_TEXT}; }}"
            f"QLineEdit, QComboBox, QPlainTextEdit {{ background: {_SURFACE};"
            f" color: {_TEXT}; border: 1px solid {_BORDER}; padding: 4px; }}"
            f"QPushButton {{ background: {_SURFACE}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; padding: 6px 12px; }}"
            f"QPushButton:hover {{ border: 1px solid {_ACCENT}; }}"
        )

        self._project: Project | None = None
        self._source_path: Path | None = None

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.kind_combo = QComboBox()
        for label, _k, _f in _KINDS:
            self.kind_combo.addItem(label)
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._on_kind_changed())
        form.addRow("Project type:", self.kind_combo)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select a project file or directory...")
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_btn)
        form.addRow("Source:", path_row)

        root.addLayout(form)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview:"))
        self.refresh_btn = QPushButton("Refresh Preview")
        self.refresh_btn.clicked.connect(self._refresh_preview)
        preview_row.addStretch(1)
        preview_row.addWidget(self.refresh_btn)
        root.addLayout(preview_row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        root.addWidget(self.preview, 1)

        self.warn_label = QLabel("")
        self.warn_label.setStyleSheet("color: #f0a868;")
        self.warn_label.setWordWrap(True)
        root.addWidget(self.warn_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_btn is not None:
            self._ok_btn.setText("Import")
            self._ok_btn.setEnabled(False)
        buttons.accepted.connect(self._on_import)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ----- slots -----------------------------------------------------------

    def _on_kind_changed(self) -> None:
        self.path_edit.clear()
        self.preview.clear()
        self.warn_label.clear()
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(False)

    def _on_browse(self) -> None:
        idx = self.kind_combo.currentIndex()
        _label, kind, flt = _KINDS[idx]
        if kind == "openlane2":
            d = QFileDialog.getExistingDirectory(self, "Select OpenLane2 design directory")
            if d:
                self.path_edit.setText(d)
                self._refresh_preview()
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select project file", "", flt or "All Files (*)"
        )
        if path:
            self.path_edit.setText(path)
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        idx = self.kind_combo.currentIndex()
        _label, kind, _flt = _KINDS[idx]
        src = self.path_edit.text().strip()
        self.preview.clear()
        self.warn_label.clear()
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(False)
        if not src:
            return
        p = Path(src)
        if not p.exists():
            self.preview.setPlainText(f"Path does not exist: {src}")
            return
        try:
            proj = self._do_import(kind, p)
        except Exception as e:  # noqa: BLE001
            self.preview.setPlainText(f"Import failed: {e}")
            return
        if proj is None:
            self.preview.setPlainText("Importer unavailable in this build.")
            return
        self._project = proj
        self._source_path = p

        lines: list[str] = []
        lines.append(f"Name:       {proj.name}")
        lines.append(f"Kind:       {proj.kind.value}")
        lines.append(f"Top module: {proj.top_module or '(none)'}")
        if proj.target is not None:
            t = proj.target
            lines.append(f"Target:     {t.vendor or '?'} / {t.family or '?'} / {t.device or '?'}")
        if proj.pdk is not None:
            lines.append(f"PDK:        {proj.pdk.name} ({proj.pdk.std_cell_lib or '-'})")
        lines.append(f"RTL sources:     {len(proj.rtl_sources)}")
        for s in proj.rtl_sources[:20]:
            lines.append(f"  - {s}")
        if len(proj.rtl_sources) > 20:
            lines.append(f"  ... and {len(proj.rtl_sources) - 20} more")
        lines.append(f"Constraint files: {len(proj.constraint_files)}")
        for s in proj.constraint_files[:10]:
            lines.append(f"  - {s}")
        lines.append(f"Testbench files: {len(proj.tb_sources)}")
        lines.append(f"IP instances:    {len(proj.ips)}")
        if proj.schematic_file:
            lines.append(f"Schematic: {proj.schematic_file}")
        if proj.pcb_file:
            lines.append(f"PCB:       {proj.pcb_file}")

        self.preview.setPlainText("\n".join(lines))

        warnings = proj.validate_consistency()
        if kind == "vivado":
            warnings.append("Vivado IP .xci files are recorded but not re-synthesized.")
        if kind == "kicad":
            warnings.append("KiCad stackup/components are recorded as metadata only.")
        if kind == "quartus":
            warnings.append("Quartus Qsys/IP subsystems are not expanded.")
        if warnings:
            self.warn_label.setText("Warnings: " + " ; ".join(warnings))
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(True)

    def _do_import(self, kind: str, path: Path):  # type: ignore[no-untyped-def]
        if kind == "vivado" and import_xpr is not None:
            return import_xpr(path)
        if kind == "openlane2" and import_openlane_dir is not None:
            return import_openlane_dir(path)
        if kind == "kicad" and import_kicad_project is not None:
            return import_kicad_project(path)
        if kind == "quartus" and import_quartus_qpf is not None:
            return import_quartus_qpf(path)
        return None

    def _on_import(self) -> None:
        if self._project is None:
            QMessageBox.warning(
                self, "Import Project", "Nothing to import - refresh preview first."
            )
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save OpenForge project as...",
            f"{self._project.name}.yaml",
            "OpenForge Project (*.yaml)",
        )
        if not out_path:
            return
        try:
            self._project.save(out_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Import Project", f"Failed to save: {e}")
            return
        self._saved_path = Path(out_path)
        self.accept()

    # ----- public accessors -----------------------------------------------

    def imported_project(self):  # type: ignore[no-untyped-def]
        return self._project

    def saved_path(self) -> Path | None:
        return getattr(self, "_saved_path", None)


__all__ = ["ImportProjectDialog"]
