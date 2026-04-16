"""Shared theme utilities for panels with Catppuccin-style QSS.

Provides ``panel_tab_qss(dark)`` which generates the standard QTabWidget /
QGroupBox / QPushButton / QLineEdit / etc. stylesheet used by the Synthesis,
Physical Design, Timing, and Security panels.
"""

from __future__ import annotations

# ── Dark palette (Catppuccin Mocha) ──────────────────────────────────────────

_DARK: dict[str, str] = {
    "bg": "#1e1e2e",
    "mantle": "#181825",
    "crust": "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "overlay0": "#6c7086",
    "blue": "#89b4fa",
    "alt_row": "#1a1a2e",
}

# ── Light palette ────────────────────────────────────────────────────────────

_LIGHT: dict[str, str] = {
    "bg": "#f8f9fa",
    "mantle": "#e9ecef",
    "crust": "#ffffff",
    "surface0": "#dee2e6",
    "surface1": "#ced4da",
    "surface2": "#adb5bd",
    "text": "#212529",
    "subtext": "#495057",
    "overlay0": "#6c757d",
    "blue": "#0d6efd",
    "alt_row": "#f1f3f5",
}


def _p(dark: bool) -> dict[str, str]:
    return _DARK if dark else _LIGHT


def panel_tab_qss(dark: bool, *, extra: str = "") -> str:
    """Return the standard panel QSS for the given theme.

    The optional *extra* string is appended verbatim (useful for panel-specific
    rules like QCheckBox in the security panel).
    """
    p = _p(dark)
    return f"""
        QTabWidget::pane {{
            border: none;
            background-color: {p["bg"]};
        }}
        QTabBar::tab {{
            background-color: {p["surface0"]};
            color: {p["subtext"]};
            border: none;
            padding: 6px 16px;
            font-size: 11px;
            margin-right: 1px;
            min-width: 60px;
        }}
        QTabBar::tab:selected {{
            background-color: {p["bg"]};
            color: {p["text"]};
            border-bottom: 2px solid {p["blue"]};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {p["surface1"]};
            color: {p["text"]};
        }}
        QGroupBox {{
            background-color: {p["mantle"]};
            border: 1px solid {p["surface0"]};
            border-radius: 4px;
            margin-top: 14px;
            padding: 10px 8px 8px 8px;
            font-size: 11px;
            font-weight: bold;
            color: {p["blue"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 2px 8px;
        }}
        QPushButton {{
            background-color: {p["surface0"]};
            color: {p["text"]};
            border: 1px solid {p["surface1"]};
            border-radius: 4px;
            padding: 4px 12px;
            font-size: 11px;
        }}
        QPushButton:hover {{
            background-color: {p["surface1"]};
            border-color: {p["blue"]};
        }}
        QPushButton:pressed {{
            background-color: {p["surface2"]};
        }}
        QPushButton:checked {{
            background-color: {p["blue"]};
            color: {p["crust"]};
            border-color: {p["blue"]};
        }}
        QPushButton:disabled {{
            background-color: {p["crust"]};
            color: {p["surface1"]};
            border-color: {p["surface0"]};
        }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {p["surface0"]};
            color: {p["text"]};
            border: 1px solid {p["surface1"]};
            border-radius: 3px;
            padding: 3px 6px;
            font-size: 11px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {p["blue"]};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {p["surface0"]};
            color: {p["text"]};
            selection-background-color: {p["surface1"]};
            border: 1px solid {p["surface1"]};
        }}
        QLabel {{
            color: {p["text"]};
            font-size: 11px;
        }}
        QProgressBar {{
            background-color: {p["surface0"]};
            border: none;
            border-radius: 3px;
            text-align: center;
            color: {p["text"]};
            font-size: 10px;
            max-height: 18px;
        }}
        QProgressBar::chunk {{
            background-color: {p["blue"]};
            border-radius: 3px;
        }}
        QSlider::groove:horizontal {{
            background: {p["surface0"]};
            height: 6px;
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background: {p["blue"]};
            width: 14px;
            margin: -4px 0;
            border-radius: 7px;
        }}
        QSlider::sub-page:horizontal {{
            background: {p["blue"]};
            border-radius: 3px;
        }}
        QSplitter::handle {{
            background-color: {p["surface0"]};
            height: 2px;
            width: 2px;
        }}
        QHeaderView::section {{
            background-color: {p["mantle"]};
            color: {p["subtext"]};
            border: none;
            border-right: 1px solid {p["surface0"]};
            border-bottom: 1px solid {p["surface0"]};
            padding: 4px 6px;
            font-size: 11px;
            font-weight: bold;
        }}
        QTableWidget {{
            alternate-background-color: {p["alt_row"]};
        }}
        QTreeWidget {{
            alternate-background-color: {p["alt_row"]};
        }}
        {extra}
    """
