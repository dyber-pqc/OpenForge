"""Dialog for selecting and customizing a synthesis strategy.

Catppuccin Mocha-themed QDialog mirroring the layout of Vivado's
synthesis strategy picker.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
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
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

try:  # pragma: no cover - import-time fallback for tests
    from openforge.synthesis.strategies import (
        BUILTIN_STRATEGIES,
        OptimizationGoal,
        SynthesisStrategy,
        get_strategy,
        list_strategies,
    )
except Exception:  # pragma: no cover
    BUILTIN_STRATEGIES = {}  # type: ignore
    SynthesisStrategy = object  # type: ignore

    class OptimizationGoal:  # type: ignore
        DEFAULT = "default"
        AREA = "area"
        SPEED = "speed"
        POWER = "power"
        BALANCED = "balanced"

    def list_strategies():  # type: ignore
        return []

    def get_strategy(name):  # type: ignore
        return None


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
_YELLOW = "#f9e2af"


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
QLabel#GoalLabel {{
    color: {_BLUE};
    font-weight: bold;
}}
QLabel#TradeoffLabel {{
    color: {_PEACH};
}}
QLabel#NotesLabel {{
    color: {_SUBTEXT};
    font-style: italic;
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
    padding: 8px 10px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {_SURFACE1};
    color: {_MAUVE};
}}
QListWidget::item:hover {{
    background-color: {_SURFACE0};
}}
QTextBrowser {{
    background-color: {_MANTLE};
    color: {_TEXT};
    border: 1px solid {_SURFACE0};
    border-radius: 6px;
    padding: 8px;
}}
QGroupBox {{
    background-color: {_MANTLE};
    border: 1px solid {_SURFACE0};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    color: {_TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: {_BLUE};
    font-weight: bold;
}}
QCheckBox {{
    color: {_TEXT};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {_SURFACE1};
    border-radius: 3px;
    background-color: {_BASE};
}}
QCheckBox::indicator:checked {{
    background-color: {_GREEN};
    border-color: {_GREEN};
}}
QSpinBox, QLineEdit, QComboBox {{
    background-color: {_BASE};
    color: {_TEXT};
    border: 1px solid {_SURFACE0};
    border-radius: 4px;
    padding: 4px 6px;
    min-height: 22px;
}}
QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{
    border-color: {_BLUE};
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


_GOAL_ICON = {
    "area": "[A]",
    "speed": "[S]",
    "power": "[P]",
    "balanced": "[B]",
    "default": "[D]",
}


class SynthStrategyDialog(QDialog):
    """Pick or customize a synthesis strategy."""

    strategy_selected = Signal(str)  # strategy name

    CUSTOM_KEY = "__custom__"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Synthesis Strategy")
        self.resize(860, 580)
        self.setStyleSheet(_STYLESHEET)

        self._current_strategy: str = "default"
        self._strategies: dict[str, SynthesisStrategy] = dict(BUILTIN_STRATEGIES)

        self._build_ui()
        self._populate_strategies()
        self._select_strategy_by_name(self._current_strategy)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_current_strategy(self, name: str) -> None:
        self._current_strategy = name
        self._select_strategy_by_name(name)

    def get_selected_strategy(self) -> str:
        item = self.list_widget.currentItem()
        if item is None:
            return self._current_strategy
        return item.data(Qt.UserRole) or self._current_strategy

    def get_custom_settings(self) -> dict:
        """Return the current custom-editor settings as a plain dict."""
        return {
            "yosys_flatten": self.cb_flatten.isChecked(),
            "yosys_keep_hierarchy": self.cb_keep_hier.isChecked(),
            "yosys_retime": self.cb_retime.isChecked(),
            "use_dsp": self.cb_use_dsp.isChecked(),
            "use_bram": self.cb_use_bram.isChecked(),
            "max_fanout": self.sb_max_fanout.value(),
            "yosys_abc_script": self.le_abc_script.text(),
            "opt_full": self.cb_opt_full.isChecked(),
            "opt_share": self.cb_opt_share.isChecked(),
        }

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        header = QLabel("Synthesis Strategy")
        header.setObjectName("TitleLabel")
        outer.addWidget(header)

        subtitle = QLabel(
            "Choose a preset that matches your design goals, or create a custom strategy."
        )
        subtitle.setStyleSheet(f"color: {_SUBTEXT};")
        outer.addWidget(subtitle)

        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFrameShape(QFrame.HLine)
        outer.addWidget(sep)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, stretch=1)

        # ------- Left: list -------
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)
        left_lay.addWidget(QLabel("Available Strategies"))
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        left_lay.addWidget(self.list_widget, stretch=1)
        splitter.addWidget(left)

        # ------- Right: detail pane -------
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        self.title_label = QLabel("")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {_MAUVE};")
        right_lay.addWidget(self.title_label)

        self.goal_label = QLabel("")
        self.goal_label.setObjectName("GoalLabel")
        right_lay.addWidget(self.goal_label)

        self.tradeoff_label = QLabel("")
        self.tradeoff_label.setObjectName("TradeoffLabel")
        right_lay.addWidget(self.tradeoff_label)

        self.description_browser = QTextBrowser()
        self.description_browser.setMaximumHeight(110)
        right_lay.addWidget(self.description_browser)

        # Yosys flag list
        flags_group = QGroupBox("Yosys Flags")
        flags_lay = QVBoxLayout(flags_group)
        self.flags_label = QLabel("")
        self.flags_label.setWordWrap(True)
        self.flags_label.setStyleSheet(f"color: {_GREEN};")
        flags_lay.addWidget(self.flags_label)
        right_lay.addWidget(flags_group)

        # Custom editor (only enabled for Custom)
        self.custom_group = QGroupBox("Custom Settings")
        form = QFormLayout(self.custom_group)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setSpacing(6)

        self.cb_flatten = QCheckBox("Flatten hierarchy")
        self.cb_keep_hier = QCheckBox("Keep hierarchy")
        self.cb_retime = QCheckBox("Retiming")
        self.cb_use_dsp = QCheckBox("Use DSP blocks")
        self.cb_use_bram = QCheckBox("Use BRAM")
        self.cb_opt_full = QCheckBox("opt -full")
        self.cb_opt_share = QCheckBox("opt share")
        self.cb_use_dsp.setChecked(True)
        self.cb_use_bram.setChecked(True)
        self.cb_opt_full.setChecked(True)
        self.cb_opt_share.setChecked(True)

        form.addRow(self.cb_flatten)
        form.addRow(self.cb_keep_hier)
        form.addRow(self.cb_retime)
        form.addRow(self.cb_use_dsp)
        form.addRow(self.cb_use_bram)
        form.addRow(self.cb_opt_full)
        form.addRow(self.cb_opt_share)

        self.sb_max_fanout = QSpinBox()
        self.sb_max_fanout.setRange(0, 10000)
        self.sb_max_fanout.setSpecialValueText("unlimited")
        form.addRow("Max fanout:", self.sb_max_fanout)

        self.le_abc_script = QLineEdit()
        self.le_abc_script.setPlaceholderText("strash; dch; map -B 0.9; ...")
        form.addRow("Custom ABC script:", self.le_abc_script)

        right_lay.addWidget(self.custom_group)

        self.notes_label = QLabel("")
        self.notes_label.setObjectName("NotesLabel")
        self.notes_label.setWordWrap(True)
        right_lay.addWidget(self.notes_label)

        right_lay.addStretch(1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([260, 580])

        # ------- Bottom: buttons -------
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        outer.addWidget(button_box)

    # ------------------------------------------------------------------ #
    # Population & selection
    # ------------------------------------------------------------------ #
    def _populate_strategies(self) -> None:
        for strat in list_strategies():
            item = QListWidgetItem(strat.display_name)
            item.setData(Qt.UserRole, strat.name)
            tip = getattr(strat, "description", "")
            item.setToolTip(tip)
            self.list_widget.addItem(item)

        # Custom entry
        custom_item = QListWidgetItem("Custom...")
        custom_item.setData(Qt.UserRole, self.CUSTOM_KEY)
        custom_item.setToolTip("Build your own synthesis strategy")
        self.list_widget.addItem(custom_item)

    def _select_strategy_by_name(self, name: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == name:
                self.list_widget.setCurrentItem(item)
                return
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #
    def _on_selection_changed(
        self, current: QListWidgetItem, previous: QListWidgetItem
    ) -> None:
        if current is None:
            return
        key = current.data(Qt.UserRole)
        if key == self.CUSTOM_KEY:
            self._show_custom()
        else:
            strat = self._strategies.get(key)
            if strat is not None:
                self._show_strategy(strat)

    def _show_strategy(self, strat: SynthesisStrategy) -> None:
        self.title_label.setText(strat.display_name)
        goal_val = getattr(strat.goal, "value", str(strat.goal))
        icon = _GOAL_ICON.get(goal_val, "[*]")
        self.goal_label.setText(f"{icon} Goal: {goal_val}")
        if hasattr(strat, "tradeoff_summary"):
            self.tradeoff_label.setText(strat.tradeoff_summary())
        else:
            self.tradeoff_label.setText("")
        self.description_browser.setPlainText(strat.description)

        flags = (
            strat.yosys_flag_summary()
            if hasattr(strat, "yosys_flag_summary")
            else []
        )
        if flags:
            self.flags_label.setText(" - " + "\n - ".join(flags))
        else:
            self.flags_label.setText("(default Yosys flow)")

        self.notes_label.setText(getattr(strat, "notes", "") or "")

        # Mirror values into the custom editor (read-only).
        self.cb_flatten.setChecked(strat.yosys_flatten)
        self.cb_keep_hier.setChecked(strat.yosys_keep_hierarchy)
        self.cb_retime.setChecked(strat.yosys_retime)
        self.cb_use_dsp.setChecked(strat.use_dsp)
        self.cb_use_bram.setChecked(strat.use_bram)
        self.cb_opt_full.setChecked(strat.opt_full)
        self.cb_opt_share.setChecked(strat.opt_share)
        self.sb_max_fanout.setValue(strat.max_fanout)
        self.le_abc_script.setText(strat.yosys_abc_script)
        self._set_custom_enabled(False)

    def _show_custom(self) -> None:
        self.title_label.setText("Custom Strategy")
        self.goal_label.setText("[*] Goal: user-defined")
        self.tradeoff_label.setText("Tradeoffs depend on chosen flags")
        self.description_browser.setPlainText(
            "Build your own synthesis strategy by combining the options below. "
            "Mix and match Yosys flags to target your design's specific goals."
        )
        self.flags_label.setText("(see custom settings below)")
        self.notes_label.setText("Custom strategies are not persisted between sessions.")
        self._set_custom_enabled(True)

    def _set_custom_enabled(self, enabled: bool) -> None:
        for widget in (
            self.cb_flatten,
            self.cb_keep_hier,
            self.cb_retime,
            self.cb_use_dsp,
            self.cb_use_bram,
            self.cb_opt_full,
            self.cb_opt_share,
            self.sb_max_fanout,
            self.le_abc_script,
        ):
            widget.setEnabled(enabled)

    def _on_accept(self) -> None:
        name = self.get_selected_strategy()
        self.strategy_selected.emit(name)
        self.accept()
