"""Unified Preferences dialog.

Tabs:

* Appearance - theme mode, density, font scale.
* Keybindings - scheme picker, per-action table, import/export.
* Accessibility - high contrast, screen-reader labels, motion-reduced.
* AI - Ollama host/model, enable RAG, enable tool calls.
* Telemetry - opt-in toggle.

Settings are persisted through :class:`QSettings` under the
``openforge`` organisation. Changes are applied on ``Apply``/``OK`` and
dispatched to the main window via targeted methods where available.
"""

from __future__ import annotations

from pathlib import Path

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


if _QT_OK:

    class PreferencesDialog(QDialog):
        """Unified settings dialog."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Preferences")
            self.setMinimumSize(720, 560)
            self._main_window = parent
            self.settings = QSettings("openforge", "desktop")

            root = QVBoxLayout(self)
            self.tabs = QTabWidget(self)
            root.addWidget(self.tabs)

            self.tabs.addTab(self._build_appearance_tab(), "Appearance")
            self.tabs.addTab(self._build_keybindings_tab(), "Keybindings")
            self.tabs.addTab(self._build_a11y_tab(), "Accessibility")
            self.tabs.addTab(self._build_ai_tab(), "AI")
            self.tabs.addTab(self._build_telemetry_tab(), "Telemetry")

            buttons = QDialogButtonBox(
                QDialogButtonBox.Ok
                | QDialogButtonBox.Cancel
                | QDialogButtonBox.Apply,
                self,
            )
            buttons.accepted.connect(self._on_accept)
            buttons.rejected.connect(self.reject)
            buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
            root.addWidget(buttons)

            self._load_values()

        # -- Appearance --------------------------------------------------

        def _build_appearance_tab(self) -> QWidget:
            w = QWidget()
            form = QFormLayout(w)
            self.theme_combo = QComboBox()
            self.theme_combo.addItems(["Dark", "Light"])
            form.addRow("Theme:", self.theme_combo)

            self.density_combo = QComboBox()
            self.density_combo.addItems(["Compact", "Comfortable", "Spacious"])
            form.addRow("Density:", self.density_combo)

            self.font_scale_spin = QDoubleSpinBox()
            self.font_scale_spin.setRange(0.75, 2.0)
            self.font_scale_spin.setSingleStep(0.05)
            self.font_scale_spin.setValue(1.0)
            form.addRow("Font scale:", self.font_scale_spin)
            return w

        # -- Keybindings -------------------------------------------------

        def _build_keybindings_tab(self) -> QWidget:
            w = QWidget()
            layout = QVBoxLayout(w)

            top = QHBoxLayout()
            top.addWidget(QLabel("Scheme:"))
            self.scheme_combo = QComboBox()
            try:
                from openforge_desktop.keybindings import ALL_SCHEMES

                for name in ALL_SCHEMES.keys():
                    self.scheme_combo.addItem(name)
            except Exception:
                self.scheme_combo.addItems(
                    ["OpenForge Default", "Vivado", "Innovus", "KiCad"]
                )
            self.scheme_combo.addItem("Custom")
            top.addWidget(self.scheme_combo, 1)
            self.scheme_combo.currentTextChanged.connect(self._refresh_binding_table)

            import_btn = QPushButton("Import...")
            export_btn = QPushButton("Export...")
            import_btn.clicked.connect(self._import_scheme)
            export_btn.clicked.connect(self._export_scheme)
            top.addWidget(import_btn)
            top.addWidget(export_btn)
            layout.addLayout(top)

            self.binding_table = QTableWidget(0, 3)
            self.binding_table.setHorizontalHeaderLabels(["Action", "Keys", "Description"])
            self.binding_table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.binding_table, 1)
            return w

        def _refresh_binding_table(self, scheme_name: str) -> None:
            try:
                from openforge_desktop.keybindings import ALL_SCHEMES
            except Exception:
                return
            scheme = ALL_SCHEMES.get(scheme_name)
            if scheme is None:
                self.binding_table.setRowCount(0)
                return
            self.binding_table.setRowCount(len(scheme.bindings))
            for row, b in enumerate(scheme.bindings):
                self.binding_table.setItem(row, 0, QTableWidgetItem(b.action))
                self.binding_table.setItem(row, 1, QTableWidgetItem(", ".join(b.keys)))
                self.binding_table.setItem(row, 2, QTableWidgetItem(b.description))

        def _import_scheme(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Keybinding Scheme", "", "JSON (*.json)"
            )
            if not path:
                return
            try:
                from openforge_desktop.keybindings import load_user_scheme

                scheme = load_user_scheme(path)
                self.settings.setValue("keybindings/user_scheme_path", path)
                self.scheme_combo.setCurrentText("Custom")
                self.binding_table.setRowCount(len(scheme.bindings))
                for row, b in enumerate(scheme.bindings):
                    self.binding_table.setItem(row, 0, QTableWidgetItem(b.action))
                    self.binding_table.setItem(row, 1, QTableWidgetItem(", ".join(b.keys)))
                    self.binding_table.setItem(row, 2, QTableWidgetItem(b.description))
            except Exception:
                pass

        def _export_scheme(self) -> None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Keybinding Scheme", "openforge-keys.json", "JSON (*.json)"
            )
            if not path:
                return
            try:
                from openforge_desktop.keybindings import ALL_SCHEMES, save_user_scheme

                scheme = ALL_SCHEMES.get(self.scheme_combo.currentText())
                if scheme is not None:
                    save_user_scheme(scheme, Path(path))
            except Exception:
                pass

        # -- Accessibility ----------------------------------------------

        def _build_a11y_tab(self) -> QWidget:
            w = QWidget()
            form = QFormLayout(w)
            self.high_contrast_cb = QCheckBox("High-contrast palette")
            self.screen_reader_cb = QCheckBox("Screen-reader labels on panels")
            self.motion_reduced_cb = QCheckBox("Reduce motion (disable animations)")
            form.addRow(self.high_contrast_cb)
            form.addRow(self.screen_reader_cb)
            form.addRow(self.motion_reduced_cb)
            return w

        # -- AI ----------------------------------------------------------

        def _build_ai_tab(self) -> QWidget:
            w = QWidget()
            form = QFormLayout(w)
            self.ollama_host_edit = QLineEdit("http://localhost:11434")
            form.addRow("Ollama host:", self.ollama_host_edit)
            self.ollama_model_edit = QLineEdit("llama3.1")
            form.addRow("Chat model:", self.ollama_model_edit)
            self.embed_model_edit = QLineEdit("nomic-embed-text")
            form.addRow("Embedding model:", self.embed_model_edit)
            self.enable_rag_cb = QCheckBox("Enable RAG context retrieval")
            form.addRow(self.enable_rag_cb)
            self.enable_tools_cb = QCheckBox("Enable AI tool calling")
            form.addRow(self.enable_tools_cb)
            return w

        # -- Telemetry ---------------------------------------------------

        def _build_telemetry_tab(self) -> QWidget:
            w = QWidget()
            layout = QVBoxLayout(w)
            self.telemetry_cb = QCheckBox(
                "Share anonymous usage telemetry (opt-in)"
            )
            layout.addWidget(self.telemetry_cb)
            layout.addWidget(
                QLabel(
                    "OpenForge never transmits source code, project names, or "
                    "identifying information."
                )
            )
            layout.addStretch(1)
            return w

        # -- load/save ---------------------------------------------------

        def _load_values(self) -> None:
            s = self.settings
            self.theme_combo.setCurrentText(str(s.value("appearance/theme", "Dark")))
            self.density_combo.setCurrentText(
                str(s.value("appearance/density", "Comfortable"))
            )
            try:
                self.font_scale_spin.setValue(float(s.value("a11y/font_scale", 1.0)))
            except Exception:
                self.font_scale_spin.setValue(1.0)
            self.scheme_combo.setCurrentText(
                str(s.value("keybindings/scheme", "OpenForge Default"))
            )
            self._refresh_binding_table(self.scheme_combo.currentText())
            self.high_contrast_cb.setChecked(
                str(s.value("a11y/high_contrast", "false")).lower() == "true"
            )
            self.screen_reader_cb.setChecked(
                str(s.value("a11y/screen_reader_labels", "true")).lower() == "true"
            )
            self.motion_reduced_cb.setChecked(
                str(s.value("a11y/motion_reduced", "false")).lower() == "true"
            )
            self.ollama_host_edit.setText(
                str(s.value("ai/ollama_host", "http://localhost:11434"))
            )
            self.ollama_model_edit.setText(str(s.value("ai/model", "llama3.1")))
            self.embed_model_edit.setText(
                str(s.value("ai/embed_model", "nomic-embed-text"))
            )
            self.enable_rag_cb.setChecked(
                str(s.value("ai/enable_rag", "true")).lower() == "true"
            )
            self.enable_tools_cb.setChecked(
                str(s.value("ai/enable_tools", "true")).lower() == "true"
            )
            self.telemetry_cb.setChecked(
                str(s.value("telemetry/opt_in", "false")).lower() == "true"
            )

        def _apply(self) -> None:
            s = self.settings
            s.setValue("appearance/theme", self.theme_combo.currentText())
            s.setValue("appearance/density", self.density_combo.currentText())
            s.setValue("a11y/font_scale", self.font_scale_spin.value())
            s.setValue("keybindings/scheme", self.scheme_combo.currentText())
            s.setValue("a11y/high_contrast", self.high_contrast_cb.isChecked())
            s.setValue("a11y/screen_reader_labels", self.screen_reader_cb.isChecked())
            s.setValue("a11y/motion_reduced", self.motion_reduced_cb.isChecked())
            s.setValue("ai/ollama_host", self.ollama_host_edit.text())
            s.setValue("ai/model", self.ollama_model_edit.text())
            s.setValue("ai/embed_model", self.embed_model_edit.text())
            s.setValue("ai/enable_rag", self.enable_rag_cb.isChecked())
            s.setValue("ai/enable_tools", self.enable_tools_cb.isChecked())
            s.setValue("telemetry/opt_in", self.telemetry_cb.isChecked())

            # Push to main window
            mw = self._main_window
            if mw is None:
                return
            try:
                from openforge_desktop.theme.accessibility import (
                    A11ySettings,
                    apply_a11y_settings,
                )

                apply_a11y_settings(
                    mw,
                    A11ySettings(
                        high_contrast=self.high_contrast_cb.isChecked(),
                        font_scale=self.font_scale_spin.value(),
                        screen_reader_labels=self.screen_reader_cb.isChecked(),
                        motion_reduced=self.motion_reduced_cb.isChecked(),
                    ),
                )
            except Exception:
                pass
            try:
                from openforge_desktop.keybindings import ALL_SCHEMES, apply_scheme

                scheme = ALL_SCHEMES.get(self.scheme_combo.currentText())
                if scheme is not None:
                    apply_scheme(mw, scheme)
            except Exception:
                pass

        def _on_accept(self) -> None:
            self._apply()
            self.accept()

else:  # pragma: no cover - headless fallback

    class PreferencesDialog:  # type: ignore[no-redef]
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("PySide6 is not available")


__all__ = ["PreferencesDialog"]
