"""Toast notification system for OpenForge desktop.

A NotificationManager attaches to the main window and stacks small toast
widgets in the bottom-right corner. Each toast slides in via a property
animation, auto-fades after a configurable duration, and can carry an
optional action button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Severity styling
# ---------------------------------------------------------------------------

SEVERITY_STYLES = {
    "info": {
        "bg": "#313244",
        "border": "#89b4fa",
        "icon": "ℹ",
        "icon_color": "#89b4fa",
    },
    "success": {
        "bg": "#313244",
        "border": "#a6e3a1",
        "icon": "✓",
        "icon_color": "#a6e3a1",
    },
    "warning": {
        "bg": "#313244",
        "border": "#f9e2af",
        "icon": "⚠",
        "icon_color": "#f9e2af",
    },
    "error": {
        "bg": "#313244",
        "border": "#f38ba8",
        "icon": "✕",
        "icon_color": "#f38ba8",
    },
}


# ---------------------------------------------------------------------------
# Toast widget
# ---------------------------------------------------------------------------


class _Toast(QFrame):
    """Single toast widget that slides in from the bottom-right."""

    dismissed = Signal(object)  # self

    TOAST_WIDTH = 340

    def __init__(
        self,
        message: str,
        severity: str = "info",
        duration_ms: int = 3000,
        action_text: str | None = None,
        on_action: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._message = message
        self._severity = severity if severity in SEVERITY_STYLES else "info"
        self._duration_ms = duration_ms
        self._action_text = action_text
        self._on_action = on_action
        self._anim_in: QPropertyAnimation | None = None
        self._anim_out: QPropertyAnimation | None = None
        self._timer: QTimer | None = None

        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedWidth(self.TOAST_WIDTH)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        self._build_ui()
        self._apply_style()
        self._install_shadow()

    # ----- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 10, 12)
        outer.setSpacing(12)

        style = SEVERITY_STYLES[self._severity]

        self._icon_label = QLabel(style["icon"])
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        self._icon_label.setFont(f)
        self._icon_label.setStyleSheet(
            f"color: {style['icon_color']}; background: transparent;"
        )
        self._icon_label.setFixedWidth(24)
        self._icon_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        outer.addWidget(self._icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._text_label = QLabel(self._message)
        self._text_label.setWordWrap(True)
        self._text_label.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; background: transparent;"
        )
        text_col.addWidget(self._text_label)

        if self._action_text and self._on_action is not None:
            action_btn = QPushButton(self._action_text)
            action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            action_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {style['icon_color']}; "
                "border: none; padding: 2px 0; font-weight: 600; font-size: 12px; "
                "text-align: left; }} "
                f"QPushButton:hover {{ color: #cdd6f4; }}"
            )
            action_btn.clicked.connect(self._handle_action)
            text_col.addWidget(action_btn)
        outer.addLayout(text_col, stretch=1)

        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            "QToolButton { color: #9399b2; background: transparent; border: none; "
            "font-size: 12px; padding: 2px 6px; } "
            "QToolButton:hover { color: #f38ba8; }"
        )
        close_btn.clicked.connect(self.dismiss)
        outer.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

    def _apply_style(self) -> None:
        style = SEVERITY_STYLES[self._severity]
        self.setStyleSheet(
            f"""
            QFrame#Toast {{
                background: {style['bg']};
                border: 1px solid {style['border']};
                border-radius: 10px;
            }}
            """
        )

    def _install_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

    # ----- animation --------------------------------------------------------

    def slide_in(self, target_pos: QPoint) -> None:
        start = QPoint(target_pos.x() + self.TOAST_WIDTH + 40, target_pos.y())
        self.move(start)
        self.show()
        self._anim_in = QPropertyAnimation(self, b"pos", self)
        self._anim_in.setDuration(260)
        self._anim_in.setStartValue(start)
        self._anim_in.setEndValue(target_pos)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_in.start()

        if self._duration_ms > 0:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.dismiss)
            self._timer.start(self._duration_ms)

    def slide_to(self, target_pos: QPoint) -> None:
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(180)
        anim.setStartValue(self.pos())
        anim.setEndValue(target_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def dismiss(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        end = QPoint(self.x() + self.TOAST_WIDTH + 60, self.y())
        self._anim_out = QPropertyAnimation(self, b"pos", self)
        self._anim_out.setDuration(220)
        self._anim_out.setStartValue(self.pos())
        self._anim_out.setEndValue(end)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(self._finalize)
        self._anim_out.start()

    def _finalize(self) -> None:
        self.dismissed.emit(self)
        self.close()

    def _handle_action(self) -> None:
        try:
            if self._on_action is not None:
                self._on_action()
        finally:
            self.dismiss()


# ---------------------------------------------------------------------------
# Notification manager
# ---------------------------------------------------------------------------


class NotificationManager(QObject):
    """Stack toast notifications in the bottom-right of a parent window."""

    MARGIN = 18
    SPACING = 8

    def __init__(self, parent_window: QWidget):
        super().__init__(parent_window)
        self._parent = parent_window
        self._toasts: list[_Toast] = []
        if parent_window is not None:
            parent_window.installEventFilter(self)

    # ----- public api -------------------------------------------------------

    def show(
        self,
        message: str,
        severity: str = "info",
        duration_ms: int = 3000,
    ) -> _Toast:
        """Show a toast notification in the bottom-right of the parent window."""
        toast = _Toast(message, severity, duration_ms, parent=self._parent)
        self._mount(toast)
        return toast

    def show_action(
        self,
        message: str,
        action_text: str,
        on_action: Callable[[], None],
        severity: str = "info",
        duration_ms: int = 6000,
    ) -> _Toast:
        """Toast with an action button."""
        toast = _Toast(
            message,
            severity,
            duration_ms,
            action_text=action_text,
            on_action=on_action,
            parent=self._parent,
        )
        self._mount(toast)
        return toast

    def info(self, message: str, duration_ms: int = 3000) -> _Toast:
        return self.show(message, "info", duration_ms)

    def success(self, message: str, duration_ms: int = 3000) -> _Toast:
        return self.show(message, "success", duration_ms)

    def warning(self, message: str, duration_ms: int = 4000) -> _Toast:
        return self.show(message, "warning", duration_ms)

    def error(self, message: str, duration_ms: int = 5000) -> _Toast:
        return self.show(message, "error", duration_ms)

    def clear(self) -> None:
        for toast in list(self._toasts):
            toast.dismiss()

    # ----- internal ---------------------------------------------------------

    def _mount(self, toast: _Toast) -> None:
        toast.adjustSize()
        toast.dismissed.connect(self._on_dismissed)
        self._toasts.append(toast)
        target = self._target_position_for_index(len(self._toasts) - 1, toast)
        toast.slide_in(target)
        self._reflow(animate=True)

    def _on_dismissed(self, toast: _Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reflow(animate=True)

    def _reflow(self, animate: bool = False) -> None:
        if self._parent is None:
            return
        # Place toasts from bottom upward
        y_cursor = self._parent.height() - self.MARGIN
        for toast in reversed(self._toasts):
            toast.adjustSize()
            x = self._parent.width() - toast.width() - self.MARGIN
            y = y_cursor - toast.height()
            target = QPoint(x, y)
            if animate:
                toast.slide_to(target)
            else:
                toast.move(target)
            y_cursor = y - self.SPACING

    def _target_position_for_index(self, index: int, toast: _Toast) -> QPoint:
        if self._parent is None:
            return QPoint(0, 0)
        x = self._parent.width() - toast.width() - self.MARGIN
        y = self._parent.height() - self.MARGIN - toast.height()
        return QPoint(x, y)

    # ----- event filter -----------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._parent and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
        ):
            self._reflow(animate=False)
        return super().eventFilter(obj, event)
