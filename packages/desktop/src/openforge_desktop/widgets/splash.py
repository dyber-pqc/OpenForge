"""Vivado-style splash screen for OpenForge EDA."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSplashScreen


class OpenForgeSplash(QSplashScreen):
    """Professional splash screen shown during application startup."""

    WIDTH = 680
    HEIGHT = 420

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self._status_text = "Initializing..."
        self._progress = 0.0

    def set_status(self, text: str, progress: float = -1.0) -> None:
        """Update status text and optional progress (0.0 - 1.0)."""
        self._status_text = text
        if progress >= 0:
            self._progress = min(1.0, max(0.0, progress))
        self.repaint()

    def drawContents(self, painter: QPainter) -> None:
        w, h = self.WIDTH, self.HEIGHT

        # Background gradient
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor("#0f0f1a"))
        grad.setColorAt(0.5, QColor("#1a1a2e"))
        grad.setColorAt(1.0, QColor("#0d0d1a"))
        painter.fillRect(0, 0, w, h, grad)

        # Accent line at top
        accent_grad = QLinearGradient(0, 0, w, 0)
        accent_grad.setColorAt(0.0, QColor("#89b4fa"))
        accent_grad.setColorAt(0.5, QColor("#cba6f7"))
        accent_grad.setColorAt(1.0, QColor("#89b4fa"))
        painter.fillRect(0, 0, w, 3, accent_grad)

        # Logo area
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Subtle glow behind "OpenForge"
        glow_color = QColor("#89b4fa")
        glow_color.setAlpha(25)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow_color)
        painter.drawRoundedRect(30, 78, 400, 60, 12, 12)

        # "Open" text -- measured with the LIGHT font
        logo_font = QFont("Segoe UI", 36, QFont.Weight.Light)
        painter.setFont(logo_font)
        painter.setPen(QPen(QColor("#cdd6f4")))
        painter.drawText(48, 126, "Open")
        open_w = painter.fontMetrics().horizontalAdvance("Open")

        # "Forge" text -- drawn right after "Open"
        bold_font = QFont("Segoe UI", 36, QFont.Weight.Bold)
        painter.setFont(bold_font)
        painter.setPen(QPen(QColor("#89b4fa")))
        painter.drawText(48 + open_w, 126, "Forge")
        forge_w = painter.fontMetrics().horizontalAdvance("Forge")

        # "EDA" badge positioned after "Forge"
        badge_font = QFont("Segoe UI", 14, QFont.Weight.Bold)
        painter.setFont(badge_font)
        badge_x = 48 + open_w + forge_w + 8
        badge_y = 106

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#89b4fa"))
        painter.drawRoundedRect(badge_x, badge_y, 46, 22, 4, 4)
        painter.setPen(QPen(QColor("#0f0f1a")))
        painter.drawText(badge_x + 8, badge_y + 16, "EDA")

        # Tagline
        tag_font = QFont("Segoe UI", 11)
        painter.setFont(tag_font)
        painter.setPen(QPen(QColor("#a6adc8")))
        painter.drawText(50, 158, "Cloud-Native Cryptographic Hardware Verification")

        # Version
        ver_font = QFont("JetBrains Mono", 9)
        painter.setFont(ver_font)
        painter.setPen(QPen(QColor("#585b70")))
        painter.drawText(50, 184, "Version 0.1.0  |  Dyber Inc.")

        # Decorative circuit lines
        line_y = 206
        painter.setPen(QPen(QColor("#313244"), 1))
        painter.drawLine(48, line_y, w - 48, line_y)

        # Circuit nodes -- varying sizes and some filled with accent color
        node_positions = list(range(72, w - 48, 80))
        for i, x_pos in enumerate(node_positions):
            painter.setPen(Qt.PenStyle.NoPen)
            if i % 3 == 0:
                # Accent-colored node, slightly larger
                painter.setBrush(QColor("#89b4fa"))
                painter.drawEllipse(x_pos - 4, line_y - 4, 8, 8)
            elif i % 3 == 1:
                # Medium node
                painter.setBrush(QColor("#585b70"))
                painter.drawEllipse(x_pos - 3, line_y - 3, 6, 6)
            else:
                # Small node
                painter.setBrush(QColor("#45475a"))
                painter.drawEllipse(x_pos - 2, line_y - 2, 4, 4)

        # Feature highlights
        feat_font = QFont("Segoe UI", 9)
        painter.setFont(feat_font)
        painter.setPen(QPen(QColor("#6c7086")))
        features = [
            "RTL Simulation  \u2022  Formal Verification  \u2022  Synthesis",
            "Side-Channel Analysis  \u2022  FIPS Compliance  \u2022  NTT Validation",
        ]
        for i, feat in enumerate(features):
            painter.drawText(50, 238 + i * 20, feat)

        # Progress bar
        bar_y = h - 70
        bar_h = 4
        bar_margin = 48

        # Background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#313244"))
        painter.drawRoundedRect(bar_margin, bar_y, w - bar_margin * 2, bar_h, 2, 2)

        # Fill
        if self._progress > 0:
            fill_w = int((w - bar_margin * 2) * self._progress)
            fill_grad = QLinearGradient(bar_margin, 0, bar_margin + fill_w, 0)
            fill_grad.setColorAt(0.0, QColor("#89b4fa"))
            fill_grad.setColorAt(1.0, QColor("#cba6f7"))
            painter.setBrush(fill_grad)
            painter.drawRoundedRect(bar_margin, bar_y, fill_w, bar_h, 2, 2)

        # Status text
        status_font = QFont("Segoe UI", 9)
        painter.setFont(status_font)
        painter.setPen(QPen(QColor("#a6adc8")))
        painter.drawText(bar_margin, bar_y + 22, self._status_text)

        # Copyright
        painter.setPen(QPen(QColor("#45475a")))
        cr_font = QFont("Segoe UI", 8)
        painter.setFont(cr_font)
        painter.drawText(bar_margin, h - 14, "\u00A9 2026 Dyber Inc. All rights reserved.")

        # Rounded inner border
        painter.setPen(QPen(QColor("#313244"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 8, 8)
