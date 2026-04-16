"""Constrained Random Verification builder panel.

Lets the user define a randomised SV class (fields + constraints), pick a
protocol sequence template, preview the generated SystemVerilog, write it
to the project verification directory and optionally test-compile it with
Verilator.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
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


try:
    from openforge.verification.uvm_lite.crv import (
        ConstraintExpression,
        emit_random_class_sv,
        generate_apb_random_sequence,
        generate_axi_random_sequence,
        generate_i2c_random_sequence,
        generate_uart_random_sequence,
    )
except Exception:  # pragma: no cover
    ConstraintExpression = None  # type: ignore
    emit_random_class_sv = None  # type: ignore
    generate_apb_random_sequence = None  # type: ignore
    generate_axi_random_sequence = None  # type: ignore
    generate_i2c_random_sequence = None  # type: ignore
    generate_uart_random_sequence = None  # type: ignore


class CrvBuilderPanel(QWidget):
    """Interactive builder for constrained-random SV classes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CrvBuilderPanel")
        self._project_dir: Path | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title = QLabel("CRV / Sequence builder")
        title.setStyleSheet("font-size:14px; font-weight:600;")
        root.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        # ---- Left: sequence templates sidebar ------------------------
        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(4, 4, 4, 4)
        side_lay.addWidget(QLabel("Sequence templates"))
        self._template_list = QListWidget()
        for name in (
            "AXI random bursts",
            "APB random transfers",
            "UART random chars",
            "I2C random transactions",
        ):
            QListWidgetItem(name, self._template_list)
        self._template_list.itemDoubleClicked.connect(self._on_template_used)
        side_lay.addWidget(self._template_list, 1)
        side_form = QFormLayout()
        self._template_count = QSpinBox()
        self._template_count.setRange(1, 10_000)
        self._template_count.setValue(16)
        side_form.addRow("Count:", self._template_count)
        self._template_seed = QSpinBox()
        self._template_seed.setRange(0, 2_000_000_000)
        self._template_seed.setValue(42)
        side_form.addRow("Seed:", self._template_seed)
        side_lay.addLayout(side_form)
        self._template_btn = QPushButton("Insert template into preview")
        self._template_btn.clicked.connect(self._on_template_used)
        side_lay.addWidget(self._template_btn)
        splitter.addWidget(side)

        # ---- Middle: class editor ------------------------------------
        middle = QWidget()
        mid_lay = QVBoxLayout(middle)
        mid_lay.setContentsMargins(4, 4, 4, 4)

        cls_box = QGroupBox("Class")
        cls_form = QFormLayout(cls_box)
        self._class_name = QLineEdit("my_item")
        cls_form.addRow("Class name:", self._class_name)
        mid_lay.addWidget(cls_box)

        fields_box = QGroupBox("Fields")
        fields_lay = QVBoxLayout(fields_box)
        self._fields_table = QTableWidget(0, 2)
        self._fields_table.setHorizontalHeaderLabels(["Field", "Width"])
        self._fields_table.horizontalHeader().setStretchLastSection(True)
        fields_lay.addWidget(self._fields_table, 1)
        fbar = QHBoxLayout()
        add_f = QPushButton("Add")
        add_f.clicked.connect(self._on_add_field)
        rem_f = QPushButton("Remove")
        rem_f.clicked.connect(self._on_remove_field)
        fbar.addWidget(add_f)
        fbar.addWidget(rem_f)
        fbar.addStretch(1)
        fields_lay.addLayout(fbar)
        mid_lay.addWidget(fields_box, 1)

        cons_box = QGroupBox("Constraints")
        cons_lay = QVBoxLayout(cons_box)
        self._cons_table = QTableWidget(0, 3)
        self._cons_table.setHorizontalHeaderLabels(["Field", "Expression", "Weight"])
        self._cons_table.horizontalHeader().setStretchLastSection(True)
        cons_lay.addWidget(self._cons_table, 1)
        cbar = QHBoxLayout()
        add_c = QPushButton("Add")
        add_c.clicked.connect(self._on_add_constraint)
        rem_c = QPushButton("Remove")
        rem_c.clicked.connect(self._on_remove_constraint)
        cbar.addWidget(add_c)
        cbar.addWidget(rem_c)
        cbar.addStretch(1)
        cons_lay.addLayout(cbar)
        mid_lay.addWidget(cons_box, 1)

        # Seed some defaults
        self._seed_defaults()
        splitter.addWidget(middle)

        # ---- Right: preview + actions --------------------------------
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 4, 4, 4)
        right_lay.addWidget(QLabel("Preview"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(False)
        mono = QFont("Consolas, 'Courier New', monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._preview.setFont(mono)
        right_lay.addWidget(self._preview, 1)

        actions = QHBoxLayout()
        self._regen_btn = QPushButton("Regenerate")
        self._regen_btn.clicked.connect(self._on_regenerate)
        self._save_btn = QPushButton("Generate")
        self._save_btn.clicked.connect(self._on_generate_to_file)
        self._test_btn = QPushButton("Test it")
        self._test_btn.clicked.connect(self._on_test_it)
        actions.addWidget(self._regen_btn)
        actions.addWidget(self._save_btn)
        actions.addWidget(self._test_btn)
        actions.addStretch(1)
        right_lay.addLayout(actions)
        self._status = QLabel("Ready.")
        self._status.setStyleSheet("color:#94a3b8;")
        right_lay.addWidget(self._status)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)

        with contextlib.suppress(Exception):
            self.setStyleSheet(panel_tab_qss(True))

        self._on_regenerate()

    # ------------------------------------------------------------------
    def set_project_dir(self, path: Path) -> None:
        self._project_dir = Path(path)

    # ------------------------------------------------------------------
    def _seed_defaults(self) -> None:
        self._add_field_row("addr", 32)
        self._add_field_row("data", 32)
        self._add_field_row("is_write", 1)
        self._add_constraint_row("addr", "addr[1:0] == 2'b00;", 1)
        self._add_constraint_row("data", "data inside {[0:32'hFFFF_FFFF]};", 1)

    def _add_field_row(self, name: str, width: int) -> None:
        row = self._fields_table.rowCount()
        self._fields_table.insertRow(row)
        self._fields_table.setItem(row, 0, QTableWidgetItem(name))
        self._fields_table.setItem(row, 1, QTableWidgetItem(str(width)))

    def _add_constraint_row(self, field: str, expr: str, weight: int) -> None:
        row = self._cons_table.rowCount()
        self._cons_table.insertRow(row)
        self._cons_table.setItem(row, 0, QTableWidgetItem(field))
        self._cons_table.setItem(row, 1, QTableWidgetItem(expr))
        self._cons_table.setItem(row, 2, QTableWidgetItem(str(weight)))

    def _on_add_field(self) -> None:
        self._add_field_row("new_field", 8)

    def _on_remove_field(self) -> None:
        row = self._fields_table.currentRow()
        if row >= 0:
            self._fields_table.removeRow(row)

    def _on_add_constraint(self) -> None:
        self._add_constraint_row("new_field", "new_field > 0;", 1)

    def _on_remove_constraint(self) -> None:
        row = self._cons_table.currentRow()
        if row >= 0:
            self._cons_table.removeRow(row)

    # ------------------------------------------------------------------
    def _collect_fields(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for r in range(self._fields_table.rowCount()):
            name_item = self._fields_table.item(r, 0)
            width_item = self._fields_table.item(r, 1)
            if not name_item or not width_item:
                continue
            try:
                w = int(width_item.text())
            except ValueError:
                w = 1
            out.append((name_item.text().strip() or f"f{r}", max(1, w)))
        return out

    def _collect_constraints(self) -> list:
        out = []
        if ConstraintExpression is None:
            return out
        for r in range(self._cons_table.rowCount()):
            fitem = self._cons_table.item(r, 0)
            eitem = self._cons_table.item(r, 1)
            witem = self._cons_table.item(r, 2)
            if not fitem or not eitem:
                continue
            try:
                weight = int(witem.text()) if witem else 1
            except ValueError:
                weight = 1
            out.append(
                ConstraintExpression(
                    field=fitem.text().strip(),
                    expression=eitem.text().strip(),
                    weight=weight,
                )
            )
        return out

    def _on_regenerate(self) -> None:
        if emit_random_class_sv is None:
            self._preview.setPlainText("// uvm_lite.crv not available")
            return
        name = self._class_name.text().strip() or "my_item"
        sv = emit_random_class_sv(
            name=name,
            fields=self._collect_fields(),
            constraints=self._collect_constraints(),
        )
        self._preview.setPlainText(sv)
        self._status.setText("Regenerated preview.")

    def _on_template_used(self) -> None:
        item = self._template_list.currentItem()
        if item is None:
            return
        n = int(self._template_count.value())
        seed = int(self._template_seed.value())
        text = ""
        label = item.text()
        if label.startswith("AXI") and generate_axi_random_sequence is not None:
            text = generate_axi_random_sequence(n, 0x0, 0x0000_FFFF, 32, seed)
        elif label.startswith("APB") and generate_apb_random_sequence is not None:
            text = generate_apb_random_sequence(n, seed=seed)
        elif label.startswith("UART") and generate_uart_random_sequence is not None:
            text = generate_uart_random_sequence(n, seed=seed)
        elif label.startswith("I2C") and generate_i2c_random_sequence is not None:
            text = generate_i2c_random_sequence(n, seed=seed)
        if text:
            existing = self._preview.toPlainText()
            self._preview.setPlainText(existing + "\n\n" + text)
            self._status.setText(f"Inserted template: {label}")

    def _on_generate_to_file(self) -> None:
        base = self._project_dir or Path.cwd()
        default_dir = base / "verification"
        default_dir.mkdir(parents=True, exist_ok=True)
        name = self._class_name.text().strip() or "my_item"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save generated SV",
            str(default_dir / f"{name}_crv.sv"),
            "SystemVerilog (*.sv)",
        )
        if not target:
            return
        try:
            Path(target).write_text(self._preview.toPlainText(), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Write failed", str(exc))
            return
        self._status.setText(f"Wrote {target}")

    def _on_test_it(self) -> None:
        verilator = shutil.which("verilator")
        if not verilator:
            self._status.setText("verilator not found on PATH")
            return
        base = self._project_dir or Path.cwd()
        tmp = base / "verification" / "_crv_test"
        tmp.mkdir(parents=True, exist_ok=True)
        name = self._class_name.text().strip() or "my_item"
        sv_path = tmp / f"{name}_crv.sv"
        try:
            sv_path.write_text(self._preview.toPlainText(), encoding="utf-8")
        except Exception as exc:
            self._status.setText(f"write failed: {exc}")
            return
        wrapper = tmp / "tb_wrapper.sv"
        wrapper.write_text(
            'module tb_wrapper; initial begin $display("crv ok"); $finish; end endmodule\n',
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [verilator, "--lint-only", "--sv", str(sv_path), str(wrapper)],
                cwd=str(tmp),
                capture_output=True,
                text=True,
                timeout=30,
            )
            ok = result.returncode == 0
            self._status.setText(
                "Verilator: OK" if ok else f"Verilator: FAIL rc={result.returncode}"
            )
        except Exception as exc:
            self._status.setText(f"verilator error: {exc}")
