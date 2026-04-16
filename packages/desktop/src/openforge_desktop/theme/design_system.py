"""OpenForge EDA Design System.

Professional EDA-grade design tokens, components, and styles inspired by:
- Altium Designer (information density, panel-heavy)
- Xilinx Vivado (dark theme, dense data)
- VS Code (clean typography, hover states)
- Cadence Innovus (technical density)
- Linear (modern minimalism)

This is the SINGLE SOURCE OF TRUTH for UI styling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

# ==============================================================================
# DESIGN TOKENS
# ==============================================================================


class Density(Enum):
    """UI density presets."""

    COMPACT = "compact"  # Vivado-style dense (11px font, 3px padding)
    NORMAL = "normal"  # Default (12px font, 5px padding)
    COMFORTABLE = "comfortable"  # Spacious (13px font, 7px padding)


@dataclass(frozen=True)
class ColorPalette:
    """Color tokens. All panels read from this - no hardcoded hex."""

    # Surfaces (5 levels of elevation)
    bg_canvas: str
    bg_base: str
    bg_subtle: str
    bg_surface: str
    bg_elevated: str
    bg_overlay: str

    # Borders
    border_default: str
    border_subtle: str
    border_strong: str
    border_focus: str

    # Text
    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_disabled: str
    text_inverse: str
    text_link: str

    # Brand & accents
    brand_primary: str
    brand_primary_hover: str
    brand_secondary: str
    accent_blue: str
    accent_purple: str
    accent_green: str
    accent_yellow: str
    accent_orange: str
    accent_red: str
    accent_pink: str
    accent_teal: str
    accent_cyan: str

    # Semantic
    success: str
    warning: str
    error: str
    info: str

    # Selection
    selection_bg: str
    selection_text: str

    # EDA layers
    layer_met1: str
    layer_met2: str
    layer_met3: str
    layer_met4: str
    layer_met5: str
    layer_via: str
    layer_poly: str
    layer_diff: str
    layer_nwell: str
    layer_pwell: str

    # Status
    status_pass: str
    status_fail: str
    status_warn: str
    status_info: str
    status_running: str


DARK_PALETTE = ColorPalette(
    bg_canvas="#0a0e14",
    bg_base="#0d1117",
    bg_subtle="#161b22",
    bg_surface="#1c2128",
    bg_elevated="#22272e",
    bg_overlay="rgba(0,0,0,0.7)",
    border_default="#30363d",
    border_subtle="#21262d",
    border_strong="#444c56",
    border_focus="#00d4ff",
    text_primary="#e6edf3",
    text_secondary="#9aa5b1",
    text_tertiary="#6c757d",
    text_disabled="#484f58",
    text_inverse="#0d1117",
    text_link="#58a6ff",
    brand_primary="#00d4ff",
    brand_primary_hover="#00bfe6",
    brand_secondary="#7c3aed",
    accent_blue="#58a6ff",
    accent_purple="#bc8cff",
    accent_green="#56d364",
    accent_yellow="#e3b341",
    accent_orange="#f0883e",
    accent_red="#f85149",
    accent_pink="#ff7eb6",
    accent_teal="#39c5cf",
    accent_cyan="#76e3ea",
    success="#3fb950",
    warning="#d29922",
    error="#f85149",
    info="#58a6ff",
    selection_bg="#1f6feb",
    selection_text="#ffffff",
    layer_met1="#3993dd",
    layer_met2="#a1c659",
    layer_met3="#e1b73a",
    layer_met4="#e07b3a",
    layer_met5="#c93c5b",
    layer_via="#9b59b6",
    layer_poly="#e74c3c",
    layer_diff="#16a085",
    layer_nwell="#34495e",
    layer_pwell="#7f8c8d",
    status_pass="#3fb950",
    status_fail="#f85149",
    status_warn="#d29922",
    status_info="#58a6ff",
    status_running="#bc8cff",
)


LIGHT_PALETTE = ColorPalette(
    bg_canvas="#ffffff",
    bg_base="#f6f8fa",
    bg_subtle="#eaeef2",
    bg_surface="#d0d7de",
    bg_elevated="#ffffff",
    bg_overlay="rgba(0,0,0,0.4)",
    border_default="#d0d7de",
    border_subtle="#eaeef2",
    border_strong="#8c959f",
    border_focus="#0969da",
    text_primary="#1f2328",
    text_secondary="#656d76",
    text_tertiary="#848d97",
    text_disabled="#afb8c1",
    text_inverse="#ffffff",
    text_link="#0969da",
    brand_primary="#0969da",
    brand_primary_hover="#0860c7",
    brand_secondary="#8250df",
    accent_blue="#0969da",
    accent_purple="#8250df",
    accent_green="#1a7f37",
    accent_yellow="#9a6700",
    accent_orange="#bc4c00",
    accent_red="#cf222e",
    accent_pink="#bf3989",
    accent_teal="#1b7c83",
    accent_cyan="#0891b2",
    success="#1a7f37",
    warning="#9a6700",
    error="#cf222e",
    info="#0969da",
    selection_bg="#0969da",
    selection_text="#ffffff",
    layer_met1="#3993dd",
    layer_met2="#a1c659",
    layer_met3="#e1b73a",
    layer_met4="#e07b3a",
    layer_met5="#c93c5b",
    layer_via="#9b59b6",
    layer_poly="#e74c3c",
    layer_diff="#16a085",
    layer_nwell="#34495e",
    layer_pwell="#7f8c8d",
    status_pass="#1a7f37",
    status_fail="#cf222e",
    status_warn="#9a6700",
    status_info="#0969da",
    status_running="#8250df",
)


# ==============================================================================
# TYPOGRAPHY
# ==============================================================================


@dataclass(frozen=True)
class Typography:
    """Typography tokens."""

    family_sans: str = '"Inter", "Segoe UI", "Helvetica Neue", system-ui, sans-serif'
    family_mono: str = '"JetBrains Mono", "Cascadia Code", "SF Mono", Consolas, monospace'
    family_display: str = '"Inter Display", "Inter", system-ui, sans-serif'

    # Sizes (in px)
    size_xs: int = 10
    size_sm: int = 11
    size_base: int = 12
    size_md: int = 13
    size_lg: int = 15
    size_xl: int = 18
    size_2xl: int = 22
    size_3xl: int = 28

    # Weights
    weight_regular: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 700

    # Line heights
    leading_tight: float = 1.2
    leading_normal: float = 1.4
    leading_relaxed: float = 1.6


TYPOGRAPHY = Typography()


# ==============================================================================
# SPACING (8pt grid)
# ==============================================================================


class Spacing:
    """8pt-grid spacing scale."""

    XXS: Final[int] = 2
    XS: Final[int] = 4
    SM: Final[int] = 6
    MD: Final[int] = 8
    LG: Final[int] = 12
    XL: Final[int] = 16
    XXL: Final[int] = 24
    XXXL: Final[int] = 32
    XXXXL: Final[int] = 48


# ==============================================================================
# RADIUS
# ==============================================================================


class Radius:
    """Border radius tokens."""

    NONE: Final[int] = 0
    XS: Final[int] = 2
    SM: Final[int] = 3
    MD: Final[int] = 4
    LG: Final[int] = 6
    XL: Final[int] = 8
    XXL: Final[int] = 12
    PILL: Final[int] = 999


# ==============================================================================
# SHADOWS
# ==============================================================================


class Shadows:
    """Drop shadow tokens (as CSS box-shadow strings)."""

    NONE: Final[str] = "none"
    XS: Final[str] = "0 1px 2px rgba(0,0,0,0.3)"
    SM: Final[str] = "0 2px 4px rgba(0,0,0,0.4)"
    MD: Final[str] = "0 4px 8px rgba(0,0,0,0.5)"
    LG: Final[str] = "0 8px 16px rgba(0,0,0,0.6)"
    XL: Final[str] = "0 16px 32px rgba(0,0,0,0.7)"


# ==============================================================================
# GLOBAL QSS GENERATION
# ==============================================================================


def get_global_qss(
    palette: ColorPalette = DARK_PALETTE,
    density: Density = Density.NORMAL,
) -> str:
    """Generate the global QSS for the entire application.

    This replaces ad-hoc DARK_THEME_QSS / LIGHT_THEME_QSS strings
    with a properly structured, dense, professional EDA theme.
    """

    if density == Density.COMPACT:
        font_size = 11
        padding_y = 3
        padding_x = 8
        row_height = 22
    elif density == Density.NORMAL:
        font_size = 12
        padding_y = 5
        padding_x = 10
        row_height = 26
    else:  # COMFORTABLE
        font_size = 13
        padding_y = 7
        padding_x = 12
        row_height = 30

    p = palette

    return f"""
/* ============================================================================
   OpenForge EDA - Global Theme
   Density: {density.value} | Generated by design_system.py
   ============================================================================ */

/* Base */
* {{
    font-family: {TYPOGRAPHY.family_sans};
    font-size: {font_size}px;
    color: {p.text_primary};
}}

QWidget {{
    background-color: {p.bg_base};
    color: {p.text_primary};
    selection-background-color: {p.selection_bg};
    selection-color: {p.selection_text};
}}

QMainWindow, QDialog {{
    background-color: {p.bg_canvas};
}}

QMainWindow::separator {{
    background-color: {p.border_default};
    width: 1px;
    height: 1px;
}}

QMainWindow::separator:hover {{
    background-color: {p.border_focus};
}}

QDialog {{
    background-color: {p.bg_base};
    border: 1px solid {p.border_default};
}}

/* ============================================================================
   MENU BAR
   ============================================================================ */

QMenuBar {{
    background-color: {p.bg_subtle};
    border-bottom: 1px solid {p.border_default};
    padding: 2px 4px;
    spacing: 2px;
    color: {p.text_primary};
}}

QMenuBar::item {{
    padding: 4px 10px;
    border-radius: {Radius.SM}px;
    background-color: transparent;
    color: {p.text_primary};
}}

QMenuBar::item:selected {{
    background-color: {p.bg_elevated};
}}

QMenuBar::item:pressed {{
    background-color: {p.brand_primary};
    color: {p.text_inverse};
}}

QMenuBar::item:disabled {{
    color: {p.text_disabled};
}}

/* ============================================================================
   MENUS
   ============================================================================ */

QMenu {{
    background-color: {p.bg_elevated};
    border: 1px solid {p.border_strong};
    border-radius: {Radius.MD}px;
    padding: 4px 0;
    color: {p.text_primary};
}}

QMenu::item {{
    padding: 6px 20px 6px 28px;
    margin: 1px 4px;
    border-radius: {Radius.SM}px;
    color: {p.text_primary};
}}

QMenu::item:selected {{
    background-color: {p.brand_primary};
    color: {p.text_inverse};
}}

QMenu::item:disabled {{
    color: {p.text_disabled};
}}

QMenu::separator {{
    height: 1px;
    background-color: {p.border_default};
    margin: 4px 12px;
}}

QMenu::indicator {{
    width: 14px;
    height: 14px;
    margin-left: 6px;
}}

QMenu::icon {{
    padding-left: 6px;
}}

/* ============================================================================
   TOOLBARS
   ============================================================================ */

QToolBar {{
    background-color: {p.bg_subtle};
    border: none;
    border-bottom: 1px solid {p.border_default};
    padding: 4px;
    spacing: 2px;
}}

QToolBar::separator {{
    background-color: {p.border_default};
    width: 1px;
    margin: 4px 6px;
}}

QToolBar::handle {{
    background-color: {p.border_default};
    width: 4px;
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {Radius.SM}px;
    padding: 4px 8px;
    color: {p.text_secondary};
    min-height: 22px;
}}

QToolButton:hover {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
    border-color: {p.border_default};
}}

QToolButton:pressed {{
    background-color: {p.bg_surface};
}}

QToolButton:checked {{
    background-color: {p.brand_primary};
    color: {p.text_inverse};
    border-color: {p.brand_primary};
}}

QToolButton:disabled {{
    color: {p.text_disabled};
    background-color: transparent;
}}

QToolButton::menu-indicator {{
    image: none;
    width: 0;
}}

/* ============================================================================
   DOCK WIDGETS
   ============================================================================ */

QDockWidget {{
    color: {p.text_secondary};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    font-size: {font_size - 1}px;
    font-weight: {TYPOGRAPHY.weight_semibold};
    background-color: {p.bg_base};
}}

QDockWidget::title {{
    background-color: {p.bg_surface};
    border-bottom: 2px solid {p.brand_primary};
    padding: 6px 10px;
    text-align: left;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: {p.text_primary};
}}

QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
    icon-size: 12px;
    border-radius: {Radius.XS}px;
}}

QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {p.bg_elevated};
}}

/* ============================================================================
   TABS
   ============================================================================ */

QTabWidget::pane {{
    border: 1px solid {p.border_default};
    background-color: {p.bg_base};
    border-radius: {Radius.SM}px;
    top: -1px;
}}

QTabWidget::tab-bar {{
    alignment: left;
}}

QTabBar {{
    background-color: transparent;
    border: none;
}}

QTabBar::tab {{
    background-color: {p.bg_subtle};
    color: {p.text_secondary};
    padding: 6px 14px;
    border: 1px solid {p.border_subtle};
    border-bottom: none;
    border-top-left-radius: {Radius.SM}px;
    border-top-right-radius: {Radius.SM}px;
    margin-right: 1px;
    min-width: 60px;
}}

QTabBar::tab:selected {{
    background-color: {p.bg_base};
    color: {p.text_primary};
    border-color: {p.border_default};
    border-bottom: 2px solid {p.brand_primary};
    padding-bottom: 4px;
}}

QTabBar::tab:hover:!selected {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
}}

QTabBar::tab:disabled {{
    color: {p.text_disabled};
}}

QTabBar::close-button {{
    subcontrol-position: right;
    border-radius: {Radius.SM}px;
    padding: 2px;
}}

QTabBar::close-button:hover {{
    background-color: {p.error};
}}

QTabBar::scroller {{
    width: 20px;
}}

/* ============================================================================
   PUSH BUTTONS
   ============================================================================ */

QPushButton {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
    border: 1px solid {p.border_default};
    border-radius: {Radius.MD}px;
    padding: {padding_y}px {padding_x}px;
    min-height: 22px;
    font-weight: {TYPOGRAPHY.weight_medium};
}}

QPushButton:hover {{
    background-color: {p.bg_surface};
    border-color: {p.border_strong};
}}

QPushButton:pressed {{
    background-color: {p.bg_subtle};
}}

QPushButton:focus {{
    border-color: {p.border_focus};
    outline: none;
}}

QPushButton:default {{
    background-color: {p.brand_primary};
    color: {p.text_inverse};
    border-color: {p.brand_primary};
    font-weight: {TYPOGRAPHY.weight_semibold};
}}

QPushButton:default:hover {{
    background-color: {p.brand_primary_hover};
}}

QPushButton:disabled {{
    background-color: {p.bg_subtle};
    color: {p.text_disabled};
    border-color: {p.border_subtle};
}}

QPushButton[class="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
}}

QPushButton[class="ghost"]:hover {{
    background-color: {p.bg_elevated};
    border-color: {p.border_default};
}}

QPushButton[class="danger"] {{
    background-color: {p.error};
    color: #ffffff;
    border-color: {p.error};
}}

QPushButton[class="danger"]:hover {{
    background-color: {p.error};
    border-color: {p.error};
}}

QPushButton[class="success"] {{
    background-color: {p.success};
    color: #ffffff;
    border-color: {p.success};
}}

QPushButton[class="primary"] {{
    background-color: {p.brand_primary};
    color: {p.text_inverse};
    border-color: {p.brand_primary};
    font-weight: {TYPOGRAPHY.weight_semibold};
}}

QPushButton[class="primary"]:hover {{
    background-color: {p.brand_primary_hover};
}}

/* ============================================================================
   INPUT FIELDS
   ============================================================================ */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit, QTimeEdit, QDateTimeEdit {{
    background-color: {p.bg_canvas};
    color: {p.text_primary};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
    padding: {padding_y}px {padding_x}px;
    selection-background-color: {p.selection_bg};
    selection-color: {p.selection_text};
    min-height: 20px;
}}

QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover,
QDateEdit:hover, QTimeEdit:hover, QDateTimeEdit:hover {{
    border-color: {p.border_strong};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {{
    border-color: {p.border_focus};
    outline: none;
}}

QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    background-color: {p.bg_subtle};
    color: {p.text_disabled};
    border-color: {p.border_subtle};
}}

QLineEdit[readOnly="true"] {{
    background-color: {p.bg_subtle};
    color: {p.text_secondary};
}}

QPlainTextEdit, QTextEdit {{
    font-family: {TYPOGRAPHY.family_mono};
    font-size: {font_size - 1}px;
    padding: 6px;
}}

QComboBox {{
    padding-right: 24px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: right;
    width: 20px;
    border-left: 1px solid {p.border_default};
    background-color: transparent;
}}

QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
}}

QComboBox::down-arrow:on {{
    top: 1px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
    border: 1px solid {p.border_strong};
    border-radius: {Radius.SM}px;
    selection-background-color: {p.brand_primary};
    selection-color: {p.text_inverse};
    padding: 4px;
    outline: none;
}}

QComboBox QAbstractItemView::item {{
    padding: 5px 8px;
    border-radius: {Radius.XS}px;
    min-height: 22px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {p.bg_surface};
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {p.bg_elevated};
    border: none;
    border-left: 1px solid {p.border_default};
    width: 16px;
}}

QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: {Radius.SM}px;
}}

QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: {Radius.SM}px;
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {p.brand_primary};
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 8px;
    height: 8px;
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 8px;
    height: 8px;
}}

/* ============================================================================
   CHECKBOXES & RADIOS
   ============================================================================ */

QCheckBox, QRadioButton {{
    color: {p.text_primary};
    spacing: 6px;
    background-color: transparent;
    padding: 2px;
}}

QCheckBox:disabled, QRadioButton:disabled {{
    color: {p.text_disabled};
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {p.border_strong};
    background-color: {p.bg_canvas};
}}

QCheckBox::indicator {{
    border-radius: {Radius.XS}px;
}}

QRadioButton::indicator {{
    border-radius: 7px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p.brand_primary};
}}

QCheckBox::indicator:checked {{
    background-color: {p.brand_primary};
    border-color: {p.brand_primary};
}}

QCheckBox::indicator:checked:hover {{
    background-color: {p.brand_primary_hover};
}}

QCheckBox::indicator:indeterminate {{
    background-color: {p.brand_primary};
    border-color: {p.brand_primary};
}}

QRadioButton::indicator:checked {{
    background-color: {p.bg_canvas};
    border: 4px solid {p.brand_primary};
}}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background-color: {p.bg_subtle};
    border-color: {p.border_subtle};
}}

/* ============================================================================
   GROUPBOX
   ============================================================================ */

QGroupBox {{
    background-color: transparent;
    border: 1px solid {p.border_default};
    border-radius: {Radius.MD}px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: {TYPOGRAPHY.weight_semibold};
    color: {p.text_primary};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {p.text_secondary};
    background-color: {p.bg_base};
    text-transform: uppercase;
    font-size: {font_size - 2}px;
    letter-spacing: 0.5px;
    left: 10px;
}}

QGroupBox:disabled {{
    color: {p.text_disabled};
    border-color: {p.border_subtle};
}}

/* ============================================================================
   TABLES / TREES / LISTS
   ============================================================================ */

QTableView, QTableWidget, QTreeView, QTreeWidget, QListView, QListWidget {{
    background-color: {p.bg_canvas};
    alternate-background-color: {p.bg_subtle};
    color: {p.text_primary};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
    gridline-color: {p.border_subtle};
    selection-background-color: {p.selection_bg};
    selection-color: {p.selection_text};
    outline: none;
    show-decoration-selected: 1;
}}

QTableView::item, QTableWidget::item, QTreeView::item, QTreeWidget::item,
QListView::item, QListWidget::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {p.border_subtle};
    min-height: {row_height}px;
    color: {p.text_primary};
}}

QTableView::item:hover, QTableWidget::item:hover,
QTreeView::item:hover, QTreeWidget::item:hover,
QListView::item:hover, QListWidget::item:hover {{
    background-color: {p.bg_subtle};
}}

QTableView::item:selected, QTableWidget::item:selected,
QTreeView::item:selected, QTreeWidget::item:selected,
QListView::item:selected, QListWidget::item:selected {{
    background-color: {p.selection_bg};
    color: {p.selection_text};
}}

QTableView::item:selected:!active, QTreeView::item:selected:!active,
QListView::item:selected:!active {{
    background-color: {p.bg_surface};
    color: {p.text_primary};
}}

QHeaderView {{
    background-color: {p.bg_subtle};
    border: none;
}}

QHeaderView::section {{
    background-color: {p.bg_subtle};
    color: {p.text_secondary};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {p.border_subtle};
    border-bottom: 1px solid {p.border_default};
    font-weight: {TYPOGRAPHY.weight_semibold};
    font-size: {font_size - 1}px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QHeaderView::section:hover {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
}}

QHeaderView::section:pressed {{
    background-color: {p.brand_primary};
    color: {p.text_inverse};
}}

QHeaderView::section:checked {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
}}

QHeaderView::up-arrow, QHeaderView::down-arrow {{
    width: 10px;
    height: 10px;
    subcontrol-position: center right;
}}

QTreeView::branch {{
    background-color: {p.bg_canvas};
}}

QTreeView::branch:has-siblings:!adjoins-item {{
    border-image: none;
}}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    border-image: none;
}}

QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{
    border-image: none;
}}

QTableCornerButton::section {{
    background-color: {p.bg_subtle};
    border: none;
    border-right: 1px solid {p.border_default};
    border-bottom: 1px solid {p.border_default};
}}

/* ============================================================================
   SCROLL BARS
   ============================================================================ */

QScrollBar:vertical {{
    background-color: {p.bg_canvas};
    width: 10px;
    border: none;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {p.border_strong};
    min-height: 30px;
    border-radius: 5px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {p.brand_primary};
}}

QScrollBar::handle:vertical:pressed {{
    background-color: {p.brand_primary_hover};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background-color: {p.bg_canvas};
    height: 10px;
    border: none;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {p.border_strong};
    min-width: 30px;
    border-radius: 5px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {p.brand_primary};
}}

QScrollBar::handle:horizontal:pressed {{
    background-color: {p.brand_primary_hover};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: transparent;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ============================================================================
   PROGRESS BAR
   ============================================================================ */

QProgressBar {{
    background-color: {p.bg_subtle};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
    text-align: center;
    color: {p.text_primary};
    font-size: {font_size - 1}px;
    height: 18px;
}}

QProgressBar::chunk {{
    background-color: {p.brand_primary};
    border-radius: {Radius.XS}px;
}}

QProgressBar[class="success"]::chunk {{
    background-color: {p.success};
}}

QProgressBar[class="error"]::chunk {{
    background-color: {p.error};
}}

QProgressBar[class="warning"]::chunk {{
    background-color: {p.warning};
}}

/* ============================================================================
   SLIDERS
   ============================================================================ */

QSlider::groove:horizontal {{
    background-color: {p.bg_subtle};
    height: 4px;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background-color: {p.brand_primary};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid {p.bg_canvas};
}}

QSlider::handle:horizontal:hover {{
    background-color: {p.brand_primary_hover};
}}

QSlider::sub-page:horizontal {{
    background-color: {p.brand_primary};
    border-radius: 2px;
}}

QSlider::groove:vertical {{
    background-color: {p.bg_subtle};
    width: 4px;
    border-radius: 2px;
}}

QSlider::handle:vertical {{
    background-color: {p.brand_primary};
    width: 14px;
    height: 14px;
    margin: 0 -5px;
    border-radius: 7px;
    border: 2px solid {p.bg_canvas};
}}

QSlider::handle:vertical:hover {{
    background-color: {p.brand_primary_hover};
}}

QSlider::sub-page:vertical {{
    background-color: {p.bg_subtle};
}}

QSlider::add-page:vertical {{
    background-color: {p.brand_primary};
    border-radius: 2px;
}}

/* ============================================================================
   STATUS BAR
   ============================================================================ */

QStatusBar {{
    background-color: {p.bg_subtle};
    color: {p.text_secondary};
    border-top: 1px solid {p.border_default};
    font-size: {font_size - 1}px;
    padding: 2px 8px;
}}

QStatusBar::item {{
    border: none;
    padding: 0 8px;
}}

QStatusBar QLabel {{
    color: {p.text_secondary};
    background: transparent;
}}

QSizeGrip {{
    background-color: transparent;
    width: 14px;
    height: 14px;
}}

/* ============================================================================
   TOOLTIPS
   ============================================================================ */

QToolTip {{
    background-color: {p.bg_elevated};
    color: {p.text_primary};
    border: 1px solid {p.border_strong};
    border-radius: {Radius.SM}px;
    padding: 6px 10px;
    font-size: {font_size - 1}px;
    opacity: 240;
}}

/* ============================================================================
   SPLITTER
   ============================================================================ */

QSplitter {{
    background-color: {p.bg_base};
}}

QSplitter::handle {{
    background-color: {p.bg_subtle};
}}

QSplitter::handle:hover {{
    background-color: {p.brand_primary};
}}

QSplitter::handle:pressed {{
    background-color: {p.brand_primary_hover};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* ============================================================================
   FRAMES
   ============================================================================ */

QFrame[frameShape="4"] /* HLine */,
QFrame[frameShape="5"] /* VLine */ {{
    color: {p.border_default};
    background-color: {p.border_default};
}}

/* ============================================================================
   LABELS
   ============================================================================ */

QLabel {{
    background-color: transparent;
    color: {p.text_primary};
}}

QLabel:disabled {{
    color: {p.text_disabled};
}}

QLabel[class="secondary"] {{
    color: {p.text_secondary};
}}

QLabel[class="tertiary"] {{
    color: {p.text_tertiary};
}}

QLabel[class="heading"] {{
    font-size: {TYPOGRAPHY.size_lg}px;
    font-weight: {TYPOGRAPHY.weight_bold};
    color: {p.text_primary};
}}

QLabel[class="title"] {{
    font-size: {TYPOGRAPHY.size_xl}px;
    font-weight: {TYPOGRAPHY.weight_bold};
    color: {p.text_primary};
}}

QLabel[class="display"] {{
    font-size: {TYPOGRAPHY.size_3xl}px;
    font-weight: {TYPOGRAPHY.weight_bold};
    color: {p.text_primary};
}}

QLabel[class="mono"] {{
    font-family: {TYPOGRAPHY.family_mono};
}}

QLabel[class="error"] {{
    color: {p.error};
}}

QLabel[class="success"] {{
    color: {p.success};
}}

QLabel[class="warning"] {{
    color: {p.warning};
}}

/* ============================================================================
   CALENDAR
   ============================================================================ */

QCalendarWidget QToolButton {{
    background-color: {p.bg_subtle};
    color: {p.text_primary};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
    padding: 4px 8px;
}}

QCalendarWidget QMenu {{
    background-color: {p.bg_elevated};
}}

QCalendarWidget QSpinBox {{
    background-color: {p.bg_canvas};
}}

QCalendarWidget QAbstractItemView:enabled {{
    background-color: {p.bg_canvas};
    color: {p.text_primary};
    selection-background-color: {p.brand_primary};
    selection-color: {p.text_inverse};
}}

QCalendarWidget QAbstractItemView:disabled {{
    color: {p.text_disabled};
}}

/* ============================================================================
   MESSAGE BOX
   ============================================================================ */

QMessageBox {{
    background-color: {p.bg_base};
    color: {p.text_primary};
}}

QMessageBox QLabel {{
    color: {p.text_primary};
    background-color: transparent;
}}

QMessageBox QPushButton {{
    min-width: 80px;
    min-height: 26px;
}}

/* ============================================================================
   DIAL
   ============================================================================ */

QDial {{
    background-color: {p.bg_subtle};
}}

/* ============================================================================
   LCD NUMBER
   ============================================================================ */

QLCDNumber {{
    background-color: {p.bg_canvas};
    color: {p.brand_primary};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
}}

/* ============================================================================
   SCROLL AREA
   ============================================================================ */

QScrollArea {{
    background-color: {p.bg_base};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
}}

QScrollArea > QWidget > QWidget {{
    background-color: {p.bg_base};
}}

QAbstractScrollArea::corner {{
    background-color: {p.bg_canvas};
    border: none;
}}

/* ============================================================================
   GRAPHICS VIEW
   ============================================================================ */

QGraphicsView {{
    background-color: {p.bg_canvas};
    border: 1px solid {p.border_default};
    border-radius: {Radius.SM}px;
}}

/* ============================================================================
   MDI
   ============================================================================ */

QMdiArea {{
    background-color: {p.bg_canvas};
}}

QMdiSubWindow {{
    background-color: {p.bg_base};
    border: 1px solid {p.border_default};
}}

QMdiSubWindow::title {{
    background-color: {p.bg_surface};
    color: {p.text_primary};
}}
"""


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================


def get_palette(dark: bool = True) -> ColorPalette:
    """Return the dark or light palette."""
    return DARK_PALETTE if dark else LIGHT_PALETTE


def apply_theme(app, dark: bool = True, density: Density = Density.NORMAL) -> None:
    """Apply the global theme to a QApplication."""
    palette = get_palette(dark)
    app.setStyleSheet(get_global_qss(palette, density))


def section_header_qss(palette: ColorPalette = DARK_PALETTE) -> str:
    """QSS for section header labels (used inside panels)."""
    return f"""
        QLabel {{
            color: {palette.brand_primary};
            font-size: {TYPOGRAPHY.size_xs}px;
            font-weight: {TYPOGRAPHY.weight_bold};
            text-transform: uppercase;
            letter-spacing: 1.2px;
            padding: 8px 4px 4px 4px;
            background: transparent;
        }}
    """


def metric_card_qss(palette: ColorPalette = DARK_PALETTE) -> str:
    """QSS for metric/KPI cards."""
    return f"""
        QFrame#metric-card {{
            background-color: {palette.bg_subtle};
            border: 1px solid {palette.border_default};
            border-radius: {Radius.MD}px;
            padding: 12px 16px;
        }}
        QFrame#metric-card:hover {{
            border-color: {palette.brand_primary};
        }}
        QLabel#metric-label {{
            color: {palette.text_tertiary};
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            font-weight: {TYPOGRAPHY.weight_semibold};
            background: transparent;
        }}
        QLabel#metric-value {{
            color: {palette.text_primary};
            font-size: 22px;
            font-weight: {TYPOGRAPHY.weight_bold};
            font-family: {TYPOGRAPHY.family_mono};
            background: transparent;
        }}
        QLabel#metric-trend {{
            color: {palette.success};
            font-size: 11px;
            background: transparent;
        }}
        QLabel#metric-trend-bad {{
            color: {palette.error};
            font-size: 11px;
            background: transparent;
        }}
        QLabel#metric-icon {{
            color: {palette.brand_primary};
            font-size: 20px;
            background: transparent;
        }}
    """


def badge_qss(palette: ColorPalette = DARK_PALETTE) -> str:
    """QSS for status badge pills."""
    return f"""
        QLabel[class="badge-success"] {{
            background-color: rgba(63,185,80,0.15);
            color: {palette.success};
            border: 1px solid {palette.success};
            border-radius: {Radius.PILL}px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: {TYPOGRAPHY.weight_bold};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        QLabel[class="badge-error"] {{
            background-color: rgba(248,81,73,0.15);
            color: {palette.error};
            border: 1px solid {palette.error};
            border-radius: {Radius.PILL}px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: {TYPOGRAPHY.weight_bold};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        QLabel[class="badge-warning"] {{
            background-color: rgba(210,153,34,0.15);
            color: {palette.warning};
            border: 1px solid {palette.warning};
            border-radius: {Radius.PILL}px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: {TYPOGRAPHY.weight_bold};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        QLabel[class="badge-info"] {{
            background-color: rgba(88,166,255,0.15);
            color: {palette.info};
            border: 1px solid {palette.info};
            border-radius: {Radius.PILL}px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: {TYPOGRAPHY.weight_bold};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
    """


def card_qss(palette: ColorPalette = DARK_PALETTE) -> str:
    """QSS for generic card containers."""
    return f"""
        QFrame#card {{
            background-color: {palette.bg_subtle};
            border: 1px solid {palette.border_default};
            border-radius: {Radius.LG}px;
        }}
        QFrame#card:hover {{
            border-color: {palette.border_strong};
        }}
        QLabel#card-title {{
            color: {palette.text_primary};
            font-size: {TYPOGRAPHY.size_md}px;
            font-weight: {TYPOGRAPHY.weight_semibold};
            padding: 10px 14px;
            border-bottom: 1px solid {palette.border_default};
            background: transparent;
        }}
    """


def get_layer_color(layer_name: str, palette: ColorPalette = DARK_PALETTE) -> str:
    """Get the standard color for a metal/poly/diff layer."""
    layer_map = {
        "met1": palette.layer_met1,
        "metal1": palette.layer_met1,
        "met2": palette.layer_met2,
        "metal2": palette.layer_met2,
        "met3": palette.layer_met3,
        "metal3": palette.layer_met3,
        "met4": palette.layer_met4,
        "metal4": palette.layer_met4,
        "met5": palette.layer_met5,
        "metal5": palette.layer_met5,
        "via": palette.layer_via,
        "via1": palette.layer_via,
        "via2": palette.layer_via,
        "via3": palette.layer_via,
        "via4": palette.layer_via,
        "li1": palette.layer_via,
        "poly": palette.layer_poly,
        "polysilicon": palette.layer_poly,
        "diff": palette.layer_diff,
        "ndiff": palette.layer_diff,
        "pdiff": palette.layer_diff,
        "diffusion": palette.layer_diff,
        "nwell": palette.layer_nwell,
        "pwell": palette.layer_pwell,
    }
    return layer_map.get(layer_name.lower(), palette.text_secondary)


def status_color(status: str, palette: ColorPalette = DARK_PALETTE) -> str:
    """Get color for a status name."""
    status_map = {
        "pass": palette.status_pass,
        "passed": palette.status_pass,
        "success": palette.status_pass,
        "ok": palette.status_pass,
        "fail": palette.status_fail,
        "failed": palette.status_fail,
        "error": palette.status_fail,
        "warn": palette.status_warn,
        "warning": palette.status_warn,
        "info": palette.status_info,
        "running": palette.status_running,
        "busy": palette.status_running,
        "pending": palette.text_tertiary,
        "idle": palette.text_tertiary,
    }
    return status_map.get(status.lower(), palette.text_secondary)
