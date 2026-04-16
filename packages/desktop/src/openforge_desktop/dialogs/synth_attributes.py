"""Dialog for inserting Verilog synthesis attributes into source code."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:  # pragma: no cover
    from openforge.synthesis.attributes import (
        ATTRIBUTE_DESCRIPTIONS,
        ATTRIBUTE_VALUES,
        AttributeType,
        SynthesisAttribute,
        find_attributes_in_source,
    )
except Exception:  # pragma: no cover
    ATTRIBUTE_DESCRIPTIONS = {}  # type: ignore
    ATTRIBUTE_VALUES = {}  # type: ignore

    class AttributeType:  # type: ignore
        pass

    class SynthesisAttribute:  # type: ignore
        def __init__(self, type, value="true", target=""):
            self.type = type
            self.value = value
            self.target = target

        def to_verilog(self):
            return f"(* {self.type} = \"{self.value}\" *)"

    def find_attributes_in_source(text):  # type: ignore
        return []


# Catppuccin Mocha palette
_BASE = "#1e1e2e"
_MANTLE = "#181825"
_SURFACE0 = "#313244"
_SURFACE1 = "#45475a"
_TEXT = "#cdd6f4"
_SUBTEXT = "#a6adc8"
_BLUE = "#89b4fa"
_MAUVE = "#cba6f7"
_GREEN = "#a6e3a1"
_PEACH = "#fab387"
_RED = "#f38ba8"


_STYLESHEET = f"""
QDialog {{
    background-color: {_BASE};
    color: {_TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}
QLabel {{
    color: {_TEXT};
}}
QLabel#TitleLabel {{
    color: {_MAUVE};
    font-size: 14pt;
    font-weight: bold;
}}
QLabel#PreviewHeader {{
    color: {_BLUE};
    font-weight: bold;
}}
QComboBox, QSpinBox, QLineEdit {{
    background-color: {_MANTLE};
    color: {_TEXT};
    border: 1px solid {_SURFACE0};
    border-radius: 4px;
    padding: 4px 6px;
    min-height: 22px;
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {_BLUE};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {_MANTLE};
    color: {_TEXT};
    selection-background-color: {_SURFACE1};
    selection-color: {_MAUVE};
    border: 1px solid {_SURFACE0};
}}
QTextBrowser, QTextEdit {{
    background-color: {_MANTLE};
    color: {_TEXT};
    border: 1px solid {_SURFACE0};
    border-radius: 6px;
    padding: 6px;
}}
QListWidget {{
    background-color: {_MANTLE};
    color: {_TEXT};
    border: 1px solid {_SURFACE0};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    padding: 4px 8px;
    border-radius: 3px;
}}
QListWidget::item:selected {{
    background-color: {_SURFACE1};
    color: {_MAUVE};
}}
QListWidget::item:hover {{
    background-color: {_SURFACE0};
}}
QGroupBox {{
    background-color: {_MANTLE};
    border: 1px solid {_SURFACE0};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: {_BLUE};
    font-weight: bold;
}}
QPushButton {{
    background-color: {_SURFACE0};
    color: {_TEXT};
    border: 1px solid {_SURFACE1};
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 80px;
}}
QPushButton:hover {{
    background-color: {_SURFACE1};
}}
QPushButton:default {{
    background-color: {_BLUE};
    color: {_BASE};
    border-color: {_BLUE};
    font-weight: bold;
}}
QPushButton:default:hover {{
    background-color: {_MAUVE};
    border-color: {_MAUVE};
}}
QFrame#Separator {{
    background-color: {_SURFACE0};
    max-height: 1px;
    min-height: 1px;
}}
"""


class SynthAttributesDialog(QDialog):
    """Pick a synthesis attribute and insert it into Verilog source."""

    attribute_inserted = Signal(int, str)  # line, attribute_text

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Synthesis Attribute")
        self.resize(640, 560)
        self.setStyleSheet(_STYLESHEET)

        self._source_text: str = ""
        self._current_line: int = 1

        self._build_ui()
        self._populate_types()
        self._refresh_existing_attributes()
        self._update_preview()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_source(self, source_text: str, current_line: int = 1) -> None:
        """Provide the Verilog source text and the user's cursor line."""
        self._source_text = source_text or ""
        self._current_line = max(1, int(current_line))
        max_line = max(1, len(self._source_text.splitlines()))
        self.sb_line.setRange(1, max_line)
        self.sb_line.setValue(min(self._current_line, max_line))
        self._refresh_existing_attributes()
        self._update_preview()

    def get_attribute(self) -> "SynthesisAttribute | None":
        """Return the configured ``SynthesisAttribute`` (or ``None``)."""
        try:
            type_value = self.cb_type.currentData()
            if type_value is None:
                return None
            attr_type = AttributeType(type_value)
        except Exception:
            return None
        return SynthesisAttribute(
            type=attr_type,
            value=self.cb_value.currentText() or "true",
            target=self.le_target.text(),
        )

    def get_target_line(self) -> int:
        return self.sb_line.value()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        title = QLabel("Add Synthesis Attribute")
        title.setObjectName("TitleLabel")
        outer.addWidget(title)

        subtitle = QLabel(
            "Insert a Verilog synthesis attribute (e.g. (* keep = \"true\" *))."
        )
        subtitle.setStyleSheet(f"color: {_SUBTEXT};")
        outer.addWidget(subtitle)

        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFrameShape(QFrame.HLine)
        outer.addWidget(sep)

        # Attribute selection group
        type_group = QGroupBox("Attribute")
        form = QFormLayout(type_group)
        form.setSpacing(6)

        self.cb_type = QComboBox()
        self.cb_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Type:", self.cb_type)

        self.cb_value = QComboBox()
        self.cb_value.setEditable(True)
        self.cb_value.editTextChanged.connect(self._update_preview)
        self.cb_value.currentIndexChanged.connect(self._update_preview)
        form.addRow("Value:", self.cb_value)

        self.le_target = QLineEdit()
        self.le_target.setPlaceholderText("optional - signal/module name")
        self.le_target.textChanged.connect(self._update_preview)
        form.addRow("Target:", self.le_target)

        self.sb_line = QSpinBox()
        self.sb_line.setRange(1, 1)
        self.sb_line.setValue(1)
        self.sb_line.valueChanged.connect(self._update_preview)
        form.addRow("Insert before line:", self.sb_line)

        outer.addWidget(type_group)

        # Description box
        desc_group = QGroupBox("Description")
        desc_lay = QVBoxLayout(desc_group)
        self.description_browser = QTextBrowser()
        self.description_browser.setMaximumHeight(80)
        desc_lay.addWidget(self.description_browser)
        outer.addWidget(desc_group)

        # Preview box
        preview_group = QGroupBox("Preview")
        preview_lay = QVBoxLayout(preview_group)
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("PreviewHeader")
        preview_lay.addWidget(self.preview_label)
        self.preview_browser = QTextEdit()
        self.preview_browser.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)
        self.preview_browser.setFont(mono)
        self.preview_browser.setMaximumHeight(120)
        preview_lay.addWidget(self.preview_browser)
        outer.addWidget(preview_group)

        # Existing attributes
        existing_group = QGroupBox("Existing Attributes")
        existing_lay = QVBoxLayout(existing_group)
        self.existing_list = QListWidget()
        self.existing_list.setMaximumHeight(120)
        existing_lay.addWidget(self.existing_list)
        outer.addWidget(existing_group)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = button_box.button(QDialogButtonBox.Ok)
        if ok_btn is not None:
            ok_btn.setText("Insert")
        button_box.accepted.connect(self._on_insert)
        button_box.rejected.connect(self.reject)
        outer.addWidget(button_box)

    # ------------------------------------------------------------------ #
    # Population
    # ------------------------------------------------------------------ #
    def _populate_types(self) -> None:
        try:
            types = list(AttributeType)
        except TypeError:
            types = []
        for at in types:
            label = at.value
            self.cb_type.addItem(label, at.value)
        if self.cb_type.count() > 0:
            self.cb_type.setCurrentIndex(0)
            self._on_type_changed(0)

    def _refresh_existing_attributes(self) -> None:
        self.existing_list.clear()
        if not self._source_text:
            return
        try:
            found = find_attributes_in_source(self._source_text)
        except Exception:
            found = []
        if not found:
            placeholder = QListWidgetItem("(none)")
            placeholder.setFlags(Qt.NoItemFlags)
            self.existing_list.addItem(placeholder)
            return
        for line_num, text in found:
            item = QListWidgetItem(f"line {line_num}:  (* {text} *)")
            item.setData(Qt.UserRole, line_num)
            self.existing_list.addItem(item)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #
    def _on_type_changed(self, _index: int) -> None:
        type_value = self.cb_type.currentData()
        try:
            attr_type = AttributeType(type_value)
        except Exception:
            attr_type = None

        # Update description
        if attr_type is not None and attr_type in ATTRIBUTE_DESCRIPTIONS:
            self.description_browser.setPlainText(
                ATTRIBUTE_DESCRIPTIONS[attr_type]
            )
        else:
            self.description_browser.setPlainText("")

        # Update value choices
        self.cb_value.blockSignals(True)
        self.cb_value.clear()
        choices = ATTRIBUTE_VALUES.get(attr_type, ["true", "false"]) if attr_type else ["true", "false"]
        for choice in choices:
            self.cb_value.addItem(choice)
        self.cb_value.setCurrentIndex(0)
        self.cb_value.blockSignals(False)

        self._update_preview()

    def _update_preview(self) -> None:
        attr = self.get_attribute()
        if attr is None:
            self.preview_label.setText("(invalid)")
            self.preview_browser.setPlainText("")
            return
        verilog = attr.to_verilog()
        line_num = self.sb_line.value()
        self.preview_label.setText(f"Will insert before line {line_num}:")

        # Show a small context window
        lines = self._source_text.splitlines()
        snippet_lines: list[str] = []
        start = max(1, line_num - 1)
        end = min(len(lines), line_num + 1)
        for i in range(start, end + 1):
            marker = " >> " if i == line_num else "    "
            snippet_lines.append(f"{marker}{i:4d}: {lines[i - 1]}")

        # Insert preview line
        indent = ""
        if 0 < line_num <= len(lines):
            for c in lines[line_num - 1]:
                if c in (" ", "\t"):
                    indent += c
                else:
                    break

        preview = []
        preview.append(f"  + {line_num:4d}: {indent}{verilog}")
        if snippet_lines:
            preview.extend(snippet_lines)
        else:
            preview.append(f"  + {verilog}")
        self.preview_browser.setPlainText("\n".join(preview))

    def _on_insert(self) -> None:
        attr = self.get_attribute()
        if attr is None:
            self.reject()
            return
        line_num = self.sb_line.value()
        self.attribute_inserted.emit(line_num, attr.to_verilog())
        self.accept()
