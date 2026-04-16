"""Accessibility support for the OpenForge desktop.

Exposes:

* :class:`A11ySettings` - a Pydantic model of the user's a11y preferences
  (persisted in ``QSettings`` by the preferences dialog).
* :data:`HIGH_CONTRAST_PALETTE` - a WCAG AAA-flavoured variant of the
  Catppuccin-inspired dark palette, with solid black background, pure
  white foreground and saturated accents so contrast ratios exceed 7:1.
* :func:`apply_a11y_settings` - mutates a running :class:`QMainWindow` in
  place: swaps the palette, scales fonts, sets ``accessibleName`` on
  dock widgets so screen readers announce them, and disables Qt
  animations when ``motion_reduced`` is set.

All operations are guarded so the function is safe to call even when
Qt is unavailable (tests, headless CI).
"""

from __future__ import annotations

from pydantic import BaseModel

from openforge_desktop.theme.design_system import ColorPalette, DARK_PALETTE


class A11ySettings(BaseModel):
    high_contrast: bool = False
    font_scale: float = 1.0  # 1.0 == default
    screen_reader_labels: bool = True
    motion_reduced: bool = False


HIGH_CONTRAST_PALETTE = ColorPalette(
    bg_canvas="#000000",
    bg_base="#000000",
    bg_subtle="#0a0a0a",
    bg_surface="#111111",
    bg_elevated="#1a1a1a",
    bg_overlay="rgba(0,0,0,0.9)",
    border_default="#ffffff",
    border_subtle="#cccccc",
    border_strong="#ffffff",
    border_focus="#ffff00",
    text_primary="#ffffff",
    text_secondary="#eeeeee",
    text_tertiary="#cccccc",
    text_disabled="#888888",
    text_inverse="#000000",
    text_link="#00ffff",
    brand_primary="#ffff00",
    brand_primary_hover="#ffff66",
    brand_secondary="#ff00ff",
    accent_blue="#00bfff",
    accent_purple="#ff66ff",
    accent_green="#00ff66",
    accent_yellow="#ffff00",
    accent_orange="#ffaa00",
    accent_red="#ff3030",
    accent_pink="#ff66cc",
    accent_teal="#00ffcc",
    accent_cyan="#00ffff",
    success="#00ff66",
    warning="#ffff00",
    error="#ff3030",
    info="#00ffff",
    selection_bg="#ffff00",
    selection_text="#000000",
    layer_met1="#00bfff",
    layer_met2="#00ff66",
    layer_met3="#ffff00",
    layer_met4="#ffaa00",
    layer_met5="#ff3030",
    layer_via="#ff00ff",
    layer_poly="#ff3030",
    layer_diff="#00ffcc",
    layer_nwell="#00bfff",
    layer_pwell="#eeeeee",
    status_pass="#00ff66",
    status_fail="#ff3030",
    status_warn="#ffff00",
    status_info="#00ffff",
    status_running="#ff00ff",
)


def get_font_scale_factor(settings: A11ySettings) -> float:
    """Clamp the configured font scale into a sane range."""
    return max(0.75, min(2.0, float(settings.font_scale or 1.0)))


def apply_a11y_settings(main_window, settings: A11ySettings) -> None:
    """Apply accessibility settings to a running QMainWindow."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QDockWidget
    except Exception:
        return

    # Font scale
    try:
        app = main_window.window()
        base_font: QFont = app.font()
        scaled = QFont(base_font)
        pt = base_font.pointSizeF() if base_font.pointSizeF() > 0 else 10.0
        scaled.setPointSizeF(pt * get_font_scale_factor(settings))
        main_window.setFont(scaled)
    except Exception:
        pass

    # High contrast palette via design_system stylesheet
    try:
        from openforge_desktop.theme.design_system import build_stylesheet  # type: ignore

        palette = HIGH_CONTRAST_PALETTE if settings.high_contrast else DARK_PALETTE
        qss = build_stylesheet(palette=palette)
        main_window.setStyleSheet(qss)
    except Exception:
        pass

    # Screen reader labels on dock widgets
    if settings.screen_reader_labels:
        try:
            for dock in main_window.findChildren(QDockWidget):
                title = dock.windowTitle() or dock.objectName() or "Dock Panel"
                dock.setAccessibleName(title)
                dock.setAccessibleDescription(f"OpenForge panel: {title}")
        except Exception:
            pass

    # Motion-reduced: disable animated dock/splitter transitions
    try:
        if settings.motion_reduced:
            main_window.setAnimated(False)
            main_window.setDockOptions(
                main_window.dockOptions() & ~Qt.AnimatedDocks  # type: ignore[arg-type]
            )
        else:
            main_window.setAnimated(True)
    except Exception:
        pass


__all__ = [
    "A11ySettings",
    "HIGH_CONTRAST_PALETTE",
    "apply_a11y_settings",
    "get_font_scale_factor",
]
