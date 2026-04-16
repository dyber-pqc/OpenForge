"""Reusable UI components for OpenForge EDA panels.

These are pre-styled, drop-in widgets that all panels can use to ensure
consistent appearance. Inspired by Linear, Vercel, and Altium Designer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openforge_desktop.theme.design_system import (
    DARK_PALETTE,
    TYPOGRAPHY,
    ColorPalette,
    Radius,
    badge_qss,
    card_qss,
    metric_card_qss,
    section_header_qss,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ==============================================================================
# METRIC CARD
# ==============================================================================


class MetricCard(QFrame):
    """A KPI/metric card with label, value, and optional trend indicator.

    Used on dashboards to show synthesis stats, timing summaries, etc.
    """

    clicked = Signal()

    def __init__(
        self,
        label: str,
        value: str = "-",
        unit: str = "",
        trend: str = "",
        trend_good: bool = True,
        icon: str = "",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._icon = icon
        self._build()
        self.set_label(label)
        self.set_value(value, unit)
        if trend:
            self.set_trend(trend, trend_good)
        if icon:
            self.set_icon(icon)

    def _build(self) -> None:
        self.setObjectName("metric-card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(metric_card_qss(self._palette))
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self._label = QLabel()
        self._label.setObjectName("metric-label")

        self._icon_label = QLabel()
        self._icon_label.setObjectName("metric-icon")
        self._icon_label.hide()

        header_row.addWidget(self._label, 1)
        header_row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header_row)

        self._value = QLabel()
        self._value.setObjectName("metric-value")
        layout.addWidget(self._value)

        self._trend = QLabel()
        self._trend.setObjectName("metric-trend")
        self._trend.hide()
        layout.addWidget(self._trend)

        layout.addStretch()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_label(self, text: str) -> None:
        self._label.setText(text.upper())

    def set_value(self, value: str, unit: str = "") -> None:
        if unit:
            self._value.setText(f"{value} <span style='font-size:13px;color:#9aa5b1'>{unit}</span>")
            self._value.setTextFormat(Qt.TextFormat.RichText)
        else:
            self._value.setText(str(value))

    def set_trend(self, trend: str, good: bool = True) -> None:
        self._trend.setText(trend)
        self._trend.setObjectName("metric-trend" if good else "metric-trend-bad")
        self._trend.setStyleSheet(metric_card_qss(self._palette))
        self._trend.show()

    def set_icon(self, icon: str) -> None:
        self._icon_label.setText(icon)
        self._icon_label.show()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ==============================================================================
# STATUS BADGE
# ==============================================================================


class StatusBadge(QLabel):
    """A small colored pill showing status (PASS/FAIL/WARN/RUNNING/INFO)."""

    SEVERITIES = {
        "success": "badge-success",
        "error": "badge-error",
        "warning": "badge-warning",
        "info": "badge-info",
        "muted": "badge-info",
    }

    def __init__(
        self,
        text: str,
        severity: str = "info",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text.upper(), parent)
        self._palette = palette
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(badge_qss(palette))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.set_severity(severity)

    def set_severity(self, severity: str) -> None:
        cls = self.SEVERITIES.get(severity, "badge-info")
        self.setProperty("class", cls)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_text(self, text: str) -> None:
        self.setText(text.upper())


# ==============================================================================
# SECTION HEADER
# ==============================================================================


class SectionHeader(QLabel):
    """A small uppercase section header for grouping content within a panel."""

    def __init__(
        self,
        text: str,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text.upper(), parent)
        self._palette = palette
        self._setup()

    def _setup(self) -> None:
        self.setStyleSheet(section_header_qss(self._palette))
        f = self.font()
        f.setBold(True)
        f.setPixelSize(TYPOGRAPHY.size_xs)
        self.setFont(f)


# ==============================================================================
# ICON BUTTON
# ==============================================================================


class IconButton(QToolButton):
    """A flat icon-only button with hover state."""

    def __init__(
        self,
        icon_text: str = "",
        tooltip: str = "",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        if icon_text:
            self.setText(icon_text)
        if tooltip:
            self.setToolTip(tooltip)
        self._style()

    def _style(self) -> None:
        p = self._palette
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(28, 28))
        self.setStyleSheet(
            f"""
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {Radius.SM}px;
                color: {p.text_secondary};
                font-size: 14px;
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
            """
        )


# ==============================================================================
# TOOLBAR SEPARATOR
# ==============================================================================


class ToolbarSeparator(QFrame):
    """Vertical separator for toolbars."""

    def __init__(
        self,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedWidth(1)
        self.setStyleSheet(
            f"color: {palette.border_default}; background: {palette.border_default};"
        )


# ==============================================================================
# COLLAPSIBLE SECTION
# ==============================================================================


class CollapsibleSection(QWidget):
    """A collapsible section with header + content.

    Used in property inspectors, navigators, etc. (like Vivado's Flow Navigator).
    """

    expanded = Signal(bool)

    def __init__(
        self,
        title: str,
        expanded: bool = True,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._expanded = expanded
        self._build(title)

    def _build(self, title: str) -> None:
        p = self._palette
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QPushButton()
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setCheckable(True)
        self._header.setChecked(self._expanded)
        self._set_header_text(title)
        self._header.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {p.bg_subtle};
                color: {p.text_primary};
                border: none;
                border-bottom: 1px solid {p.border_default};
                text-align: left;
                padding: 8px 12px;
                font-weight: {TYPOGRAPHY.weight_semibold};
                text-transform: uppercase;
                font-size: 10px;
                letter-spacing: 0.8px;
            }}
            QPushButton:hover {{
                background-color: {p.bg_surface};
                color: {p.brand_primary};
            }}
            """
        )
        self._header.clicked.connect(self.toggle)

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 10, 10, 10)
        self._content_layout.setSpacing(6)
        self._content.setVisible(self._expanded)

        root.addWidget(self._header)
        root.addWidget(self._content)

        self._title_text = title

    def _set_header_text(self, title: str) -> None:
        arrow = "\u25BE" if self._expanded else "\u25B8"
        self._header.setText(f"  {arrow}   {title.upper()}")

    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._set_header_text(self._title_text)
        self._header.setChecked(expanded)
        self.expanded.emit(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)


# ==============================================================================
# CARD
# ==============================================================================


class Card(QFrame):
    """A bordered card container with optional title."""

    def __init__(
        self,
        title: str = "",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._build(title)

    def _build(self, title: str) -> None:
        self.setObjectName("card")
        self.setStyleSheet(card_qss(self._palette))

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        if title:
            self._title_label = QLabel(title)
            self._title_label.setObjectName("card-title")
            self._layout.addWidget(self._title_label)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(8)
        self._layout.addWidget(self._body)

    def add(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)


# ==============================================================================
# SEGMENTED CONTROL
# ==============================================================================


class SegmentedControl(QWidget):
    """iOS-style segmented control for toggling between options."""

    value_changed = Signal(int)

    def __init__(
        self,
        options: list[str],
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._options = options
        self._current = 0
        self._buttons: list[QPushButton] = []
        self._build()

    def _build(self) -> None:
        p = self._palette
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self.setStyleSheet(
            f"""
            SegmentedControl {{
                background-color: {p.bg_subtle};
                border: 1px solid {p.border_default};
                border-radius: {Radius.MD}px;
            }}
            QPushButton {{
                background-color: transparent;
                color: {p.text_secondary};
                border: none;
                border-radius: {Radius.SM}px;
                padding: 5px 14px;
                font-weight: {TYPOGRAPHY.weight_medium};
                font-size: 11px;
            }}
            QPushButton:hover {{
                color: {p.text_primary};
            }}
            QPushButton:checked {{
                background-color: {p.brand_primary};
                color: {p.text_inverse};
                font-weight: {TYPOGRAPHY.weight_semibold};
            }}
            """
        )

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for i, label in enumerate(self._options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self.set_current(idx))
            self._buttons.append(btn)
            self._group.addButton(btn, i)
            layout.addWidget(btn)

        if self._buttons:
            self._buttons[0].setChecked(True)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._current = index
            self._buttons[index].setChecked(True)
            self.value_changed.emit(index)

    def current(self) -> int:
        return self._current


# ==============================================================================
# SEARCH INPUT
# ==============================================================================


class SearchInput(QFrame):
    """A search input with icon and clear button."""

    text_changed = Signal(str)

    def __init__(
        self,
        placeholder: str = "Search...",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._build(placeholder)

    def _build(self, placeholder: str) -> None:
        p = self._palette
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"""
            SearchInput {{
                background-color: {p.bg_canvas};
                border: 1px solid {p.border_default};
                border-radius: {Radius.SM}px;
            }}
            SearchInput:hover {{
                border-color: {p.border_strong};
            }}
            SearchInput:focus-within {{
                border-color: {p.border_focus};
            }}
            QLineEdit {{
                background: transparent;
                border: none;
                color: {p.text_primary};
                padding: 4px 4px;
            }}
            QLabel {{
                color: {p.text_tertiary};
                background: transparent;
                padding: 0 4px;
            }}
            QToolButton {{
                background: transparent;
                border: none;
                color: {p.text_tertiary};
                padding: 2px 6px;
            }}
            QToolButton:hover {{
                color: {p.text_primary};
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 4, 3)
        layout.setSpacing(4)

        self._icon = QLabel("\u2315")
        self._icon.setFixedWidth(16)
        layout.addWidget(self._icon)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._edit, 1)

        self._clear_btn = QToolButton()
        self._clear_btn.setText("\u2715")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self.clear)
        self._clear_btn.hide()
        layout.addWidget(self._clear_btn)

        self.setFixedHeight(28)

    def _on_text_changed(self, txt: str) -> None:
        self._clear_btn.setVisible(bool(txt))
        self.text_changed.emit(txt)

    def text(self) -> str:
        return self._edit.text()

    def clear(self) -> None:
        self._edit.clear()

    def set_placeholder(self, text: str) -> None:
        self._edit.setPlaceholderText(text)


# ==============================================================================
# PROGRESS INDICATOR
# ==============================================================================


class ProgressIndicator(QWidget):
    """A modern progress indicator with optional label and percentage."""

    def __init__(
        self,
        label: str = "",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._build(label)

    def _build(self, label: str) -> None:
        p = self._palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {p.text_secondary}; font-size: 11px; background: transparent;"
        )
        row.addWidget(self._label, 1)

        self._percent = QLabel("0%")
        self._percent.setStyleSheet(
            f"color: {p.text_primary}; font-size: 11px; "
            f"font-family: {TYPOGRAPHY.family_mono}; background: transparent;"
        )
        row.addWidget(self._percent, 0, Qt.AlignmentFlag.AlignRight)

        layout.addLayout(row)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: {p.bg_subtle};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {p.brand_primary};
                border-radius: 3px;
            }}
            """
        )
        layout.addWidget(self._bar)

    def set_value(self, percent: float) -> None:
        pct = max(0, min(100, int(percent)))
        self._bar.setValue(pct)
        self._percent.setText(f"{pct}%")

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_indeterminate(self, on: bool) -> None:
        if on:
            self._bar.setRange(0, 0)
            self._percent.setText("...")
        else:
            self._bar.setRange(0, 100)


# ==============================================================================
# EMPTY STATE
# ==============================================================================


class EmptyState(QWidget):
    """Shown when a panel has no data yet."""

    def __init__(
        self,
        icon: str = "",
        title: str = "",
        description: str = "",
        action_text: str = "",
        action_handler: Callable[[], None] | None = None,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._build(icon, title, description, action_text, action_handler)

    def _build(
        self,
        icon: str,
        title: str,
        description: str,
        action_text: str,
        action_handler: Callable[[], None] | None,
    ) -> None:
        p = self._palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet(
                f"color: {p.text_tertiary}; font-size: 48px; background: transparent;"
            )
            layout.addWidget(icon_lbl)

        if title:
            title_lbl = QLabel(title)
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_lbl.setStyleSheet(
                f"color: {p.text_primary}; font-size: 16px; "
                f"font-weight: {TYPOGRAPHY.weight_semibold}; background: transparent;"
            )
            layout.addWidget(title_lbl)

        if description:
            desc_lbl = QLabel(description)
            desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(
                f"color: {p.text_secondary}; font-size: 12px; "
                f"background: transparent;"
            )
            layout.addWidget(desc_lbl)

        if action_text and action_handler:
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn = QPushButton(action_text)
            btn.setProperty("class", "primary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(action_handler)
            btn.setMinimumWidth(140)
            btn_row.addWidget(btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)


# ==============================================================================
# TOAST NOTIFICATION
# ==============================================================================


class Toast(QFrame):
    """Toast notification (slides in and auto-dismisses)."""

    SEVERITY_COLORS = {
        "info": "#58a6ff",
        "success": "#3fb950",
        "warning": "#d29922",
        "error": "#f85149",
    }

    def __init__(
        self,
        message: str,
        severity: str = "info",
        duration_ms: int = 3500,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._duration = duration_ms
        self._build(message, severity)
        self._show_animation()

    def _build(self, message: str, severity: str) -> None:
        p = self._palette
        accent = self.SEVERITY_COLORS.get(severity, p.info)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {p.bg_elevated};
                border: 1px solid {p.border_strong};
                border-left: 3px solid {accent};
                border-radius: {Radius.MD}px;
            }}
            QLabel {{
                color: {p.text_primary};
                background: transparent;
                font-size: 12px;
            }}
            """
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        self._msg = QLabel(message)
        layout.addWidget(self._msg, 1)

    def _show_animation(self) -> None:
        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.start()

        QTimer.singleShot(self._duration, self._dismiss)

    def _dismiss(self) -> None:
        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self.deleteLater)
        self._fade_out.start()


# ==============================================================================
# KEY VALUE ROW
# ==============================================================================


class KeyValueRow(QWidget):
    """A two-column row showing label : value, used in property inspectors."""

    def __init__(
        self,
        label: str,
        value: str,
        value_color: str = "",
        mono: bool = False,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._mono = mono
        self._build(label, value, value_color)

    def _build(self, label: str, value: str, value_color: str) -> None:
        p = self._palette
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(12)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {p.text_secondary}; font-size: 11px; background: transparent;"
        )
        self._label.setMinimumWidth(110)
        layout.addWidget(self._label, 0)

        color = value_color if value_color else p.text_primary
        family = TYPOGRAPHY.family_mono if self._mono else TYPOGRAPHY.family_sans
        self._value = QLabel(value)
        self._value.setStyleSheet(
            f"color: {color}; font-size: 12px; background: transparent; "
            f"font-family: {family};"
        )
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._value, 1)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_label(self, label: str) -> None:
        self._label.setText(label)


# ==============================================================================
# TAB BAR (custom)
# ==============================================================================


class TabBar(QWidget):
    """A modern tab bar (alternative to QTabBar with custom styling)."""

    current_changed = Signal(int)

    def __init__(
        self,
        tabs: list[str],
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._tabs = tabs
        self._current = 0
        self._buttons: list[QPushButton] = []
        self._build()

    def _build(self) -> None:
        p = self._palette
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setStyleSheet(
            f"""
            TabBar {{
                background-color: {p.bg_subtle};
                border-bottom: 1px solid {p.border_default};
            }}
            QPushButton {{
                background-color: transparent;
                color: {p.text_secondary};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 8px 16px;
                font-weight: {TYPOGRAPHY.weight_medium};
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {p.text_primary};
                background-color: {p.bg_elevated};
            }}
            QPushButton:checked {{
                color: {p.brand_primary};
                border-bottom: 2px solid {p.brand_primary};
                font-weight: {TYPOGRAPHY.weight_semibold};
            }}
            """
        )

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for i, name in enumerate(self._tabs):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self.set_current(idx))
            self._buttons.append(btn)
            self._group.addButton(btn, i)
            layout.addWidget(btn)

        layout.addStretch()

        if self._buttons:
            self._buttons[0].setChecked(True)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._current = index
            self._buttons[index].setChecked(True)
            self.current_changed.emit(index)

    def current(self) -> int:
        return self._current


# ==============================================================================
# DIVIDER
# ==============================================================================


class Divider(QFrame):
    """A horizontal or vertical divider line."""

    def __init__(
        self,
        horizontal: bool = True,
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if horizontal:
            self.setFrameShape(QFrame.Shape.HLine)
            self.setFixedHeight(1)
        else:
            self.setFrameShape(QFrame.Shape.VLine)
            self.setFixedWidth(1)
        self.setStyleSheet(
            f"background-color: {palette.border_default}; "
            f"color: {palette.border_default}; border: none;"
        )


# ==============================================================================
# PILL
# ==============================================================================


class Pill(QLabel):
    """A small rounded pill showing a count or tag."""

    def __init__(
        self,
        text: str,
        color: str = "",
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._palette = palette
        bg = color if color else palette.brand_primary
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {bg};
                color: {palette.text_inverse};
                border-radius: {Radius.PILL}px;
                padding: 1px 8px;
                font-size: 10px;
                font-weight: {TYPOGRAPHY.weight_bold};
            }}
            """
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)


# ==============================================================================
# STAT ROW
# ==============================================================================


class StatRow(QWidget):
    """A horizontal row of mini stats (icon + label + value)."""

    def __init__(
        self,
        stats: list[tuple[str, str, str]],
        palette: ColorPalette = DARK_PALETTE,
        parent: QWidget | None = None,
    ) -> None:
        """stats: list of (icon, label, value) tuples."""
        super().__init__(parent)
        self._palette = palette
        self._build(stats)

    def _build(self, stats: list[tuple[str, str, str]]) -> None:
        p = self._palette
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        for icon, label, value in stats:
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(6)

            if icon:
                icon_lbl = QLabel(icon)
                icon_lbl.setStyleSheet(
                    f"color: {p.brand_primary}; font-size: 14px; background: transparent;"
                )
                cell_layout.addWidget(icon_lbl)

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(0)

            lbl = QLabel(label.upper())
            lbl.setStyleSheet(
                f"color: {p.text_tertiary}; font-size: 9px; background: transparent; "
                f"letter-spacing: 0.5px;"
            )
            val = QLabel(value)
            val.setStyleSheet(
                f"color: {p.text_primary}; font-size: 13px; background: transparent; "
                f"font-weight: {TYPOGRAPHY.weight_semibold}; "
                f"font-family: {TYPOGRAPHY.family_mono};"
            )

            text_col.addWidget(lbl)
            text_col.addWidget(val)
            cell_layout.addLayout(text_col)

            layout.addWidget(cell)

        layout.addStretch()
