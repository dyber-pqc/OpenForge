"""OpenForge EDA Theme package.

Provides the single source of truth for UI styling: design tokens,
global QSS generation, and reusable pre-styled components.
"""

from openforge_desktop.theme.design_system import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    TYPOGRAPHY,
    ColorPalette,
    Density,
    Radius,
    Shadows,
    Spacing,
    Typography,
    apply_theme,
    get_global_qss,
    get_layer_color,
    get_palette,
    metric_card_qss,
    section_header_qss,
)

__all__ = [
    "DARK_PALETTE",
    "LIGHT_PALETTE",
    "TYPOGRAPHY",
    "ColorPalette",
    "Density",
    "Radius",
    "Shadows",
    "Spacing",
    "Typography",
    "apply_theme",
    "get_global_qss",
    "get_layer_color",
    "get_palette",
    "metric_card_qss",
    "section_header_qss",
]
