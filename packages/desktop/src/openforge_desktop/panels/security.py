"""Crown-jewel crypto security dashboard -- the Dyber differentiator.

Provides six analysis tabs: Overview, Constant-Time, Side-Channel, FIPS
Compliance, Entropy, and Fault Injection.  Nothing like this exists in Vivado.

All widgets use the Catppuccin Mocha dark theme for a premium security aesthetic.
"""

from __future__ import annotations

import math
import random
from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ── Catppuccin Mocha palette ────────────────────────────────────────────────

_BG: Final[str] = "#1e1e2e"
_MANTLE: Final[str] = "#181825"
_CRUST: Final[str] = "#11111b"
_SURFACE0: Final[str] = "#313244"
_SURFACE1: Final[str] = "#45475a"
_SURFACE2: Final[str] = "#585b70"


def _scrollable(widget: QWidget) -> QScrollArea:
    """Wrap a widget in a scroll area so tab content never clips."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    return scroll
_TEXT: Final[str] = "#cdd6f4"
_SUBTEXT: Final[str] = "#a6adc8"
_OVERLAY0: Final[str] = "#6c7086"

_CLR_BLUE: Final[str] = "#89b4fa"
_CLR_GREEN: Final[str] = "#a6e3a1"
_CLR_RED: Final[str] = "#f38ba8"
_CLR_YELLOW: Final[str] = "#f9e2af"
_CLR_MAUVE: Final[str] = "#cba6f7"
_CLR_PEACH: Final[str] = "#fab387"
_CLR_TEAL: Final[str] = "#94e2d5"
_CLR_PINK: Final[str] = "#f5c2e7"
_CLR_SAPPHIRE: Final[str] = "#74c7ec"
_CLR_SKY: Final[str] = "#89dceb"
_CLR_FLAMINGO: Final[str] = "#f2cdcd"
_CLR_ROSEWATER: Final[str] = "#f5e0dc"
_CLR_LAVENDER: Final[str] = "#b4befe"

_ALT_ROW: Final[str] = "#1a1a2e"

# ── Category definitions ───────────────────────────────────────────────────

_CATEGORIES: Final[list[tuple[str, str]]] = [
    ("Constant-Time", _CLR_BLUE),
    ("Power SCA", _CLR_MAUVE),
    ("Fault Injection", _CLR_RED),
    ("Entropy", _CLR_GREEN),
    ("FIPS 140-3", _CLR_PEACH),
    ("Key Handling", _CLR_TEAL),
]

# ── FIPS 140-3 requirement groups ──────────────────────────────────────────

_FIPS_GROUPS: Final[list[tuple[str, list[tuple[str, str]]]]] = [
    ("Cryptographic Module Specification", [
        ("CMS-01", "Module boundary clearly defined"),
        ("CMS-02", "Hardware/software/firmware components identified"),
        ("CMS-03", "Security level documented for each interface"),
    ]),
    ("Module Interfaces", [
        ("MI-01", "Data input interface isolated"),
        ("MI-02", "Data output interface isolated"),
        ("MI-03", "Control input interface defined"),
        ("MI-04", "Status output interface defined"),
    ]),
    ("Roles, Services, and Authentication", [
        ("RSA-01", "Crypto Officer role implemented"),
        ("RSA-02", "User role implemented"),
        ("RSA-03", "Role-based authentication enforced"),
    ]),
    ("Finite State Model", [
        ("FSM-01", "State diagram documented"),
        ("FSM-02", "All transitions validated"),
        ("FSM-03", "Error states handled correctly"),
    ]),
    ("Physical Security", [
        ("PS-01", "Tamper evidence mechanisms"),
        ("PS-02", "Tamper response (zeroization) implemented"),
        ("PS-03", "EFP/EFT protection"),
    ]),
    ("Non-Invasive Security", [
        ("NIS-01", "SPA countermeasures implemented"),
        ("NIS-02", "DPA countermeasures implemented"),
        ("NIS-03", "Timing attack countermeasures implemented"),
        ("NIS-04", "Fault injection countermeasures implemented"),
    ]),
    ("Key Management", [
        ("KM-01", "Key generation uses approved RNG"),
        ("KM-02", "Key storage uses approved method"),
        ("KM-03", "Key transport uses approved method"),
        ("KM-04", "Key zeroization implemented"),
        ("KM-05", "Key separation enforced"),
    ]),
    ("Self-Tests", [
        ("ST-01", "Power-on self-tests implemented"),
        ("ST-02", "Conditional self-tests implemented"),
        ("ST-03", "Known-answer tests for algorithms"),
        ("ST-04", "Integrity test of module firmware"),
    ]),
    ("Design Assurance", [
        ("DA-01", "Configuration management documented"),
        ("DA-02", "Delivery and operation guidance"),
        ("DA-03", "Development documentation complete"),
    ]),
    ("Mitigation of Other Attacks", [
        ("MOA-01", "Side-channel mitigations documented"),
        ("MOA-02", "Fault attack mitigations documented"),
    ]),
]

# ── Shared helpers ─────────────────────────────────────────────────────────


def _text_item(text: str, color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    return item


def _numeric_item(value: float | int, fmt: str = "{:.1f}", color: str = _TEXT) -> QTableWidgetItem:
    item = QTableWidgetItem(fmt.format(value))
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item.setData(Qt.ItemDataRole.UserRole, value)
    return item


def _header_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_CLR_BLUE}; font-weight: bold; font-size: 13px; padding: 4px 0px;")
    return lbl


def _dim_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
    return lbl


def _configure_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(f"QTableWidget {{ alternate-background-color: {_ALT_ROW}; }}")
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)


def _score_color(score: float) -> str:
    """Return colour based on 0-100 score."""
    if score >= 80:
        return _CLR_GREEN
    if score >= 50:
        return _CLR_YELLOW
    return _CLR_RED


def _status_color(status: str) -> str:
    """Return colour for PASS/FAIL/WARNING/N/A status."""
    status_map = {"PASS": _CLR_GREEN, "FAIL": _CLR_RED, "WARNING": _CLR_YELLOW, "N/A": _OVERLAY0}
    return status_map.get(status, _TEXT)


def _accent_button(text: str, color: str = _CLR_BLUE) -> QPushButton:
    """Create a coloured accent button."""
    btn = QPushButton(text)
    btn.setStyleSheet(
        f"QPushButton {{ background-color: {color}; color: {_CRUST}; border: none; "
        f"border-radius: 4px; padding: 8px 20px; font-weight: bold; font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {_CLR_LAVENDER}; }}"
        f"QPushButton:pressed {{ background-color: {_SURFACE2}; color: {_TEXT}; }}"
    )
    return btn


# ── Circular Score Gauge ───────────────────────────────────────────────────


class _ScoreGaugeWidget(QWidget):
    """Large circular gauge for overall security score (0-100).

    Uses QPainter with a conical gradient arc from red through yellow to green.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setMaximumSize(260, 260)
        self._score: float = 0.0
        self._label: str = "Security Score"

    def set_score(self, score: float, label: str = "Security Score") -> None:
        self._score = max(0.0, min(100.0, score))
        self._label = label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        size = min(w, h) - 20
        cx, cy = w / 2, h / 2
        rect = QRectF(cx - size / 2, cy - size / 2, size, size)

        pen_width = 14
        arc_rect = rect.adjusted(pen_width / 2, pen_width / 2, -pen_width / 2, -pen_width / 2)

        # Background track
        track_pen = QPen(QColor(_SURFACE0), pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc_rect, 225 * 16, -270 * 16)

        # Score arc with gradient
        sweep_angle = int(self._score / 100.0 * 270)
        if sweep_angle > 0:
            # Determine colour from score
            if self._score >= 80:
                arc_color = QColor(_CLR_GREEN)
            elif self._score >= 50:
                arc_color = QColor(_CLR_YELLOW)
            else:
                arc_color = QColor(_CLR_RED)

            score_pen = QPen(arc_color, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(score_pen)
            painter.drawArc(arc_rect, 225 * 16, -sweep_angle * 16)

        # Score text in center
        painter.setPen(QColor(_TEXT))
        font = QFont()
        font.setPixelSize(int(size * 0.28))
        font.setBold(True)
        painter.setFont(font)
        score_text = f"{self._score:.0f}"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, score_text)

        # Label below score
        painter.setPen(QColor(_SUBTEXT))
        font.setPixelSize(int(size * 0.08))
        font.setBold(False)
        painter.setFont(font)
        label_rect = QRectF(rect.left(), rect.center().y() + size * 0.15, rect.width(), size * 0.15)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._label)


# ── Radar / Spider Chart ──────────────────────────────────────────────────


class _RadarChartWidget(QWidget):
    """Radar/spider chart for category security scores."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._categories: list[tuple[str, float, str]] = []  # (name, score, color)

    def set_data(self, categories: list[tuple[str, float, str]]) -> None:
        self._categories = categories
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._categories:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 50
        n = len(self._categories)
        if n < 3:
            return

        angle_step = 2 * math.pi / n

        # Grid rings at 25%, 50%, 75%, 100%
        for frac in (0.25, 0.5, 0.75, 1.0):
            painter.setPen(QPen(QColor(_SURFACE0), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = radius * frac
            pts = QPolygonF()
            for i in range(n):
                angle = -math.pi / 2 + i * angle_step
                pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
            pts.append(pts[0])
            painter.drawPolygon(pts)

        # Axes
        painter.setPen(QPen(QColor(_SURFACE1), 1))
        for i in range(n):
            angle = -math.pi / 2 + i * angle_step
            painter.drawLine(QPointF(cx, cy),
                             QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

        # Data polygon fill
        data_pts = QPolygonF()
        for i, (_, score, _) in enumerate(self._categories):
            angle = -math.pi / 2 + i * angle_step
            r = radius * (score / 100.0)
            data_pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
        data_pts.append(data_pts[0])

        fill_color = QColor(_CLR_BLUE)
        fill_color.setAlpha(40)
        painter.setPen(QPen(QColor(_CLR_BLUE), 2))
        painter.setBrush(fill_color)
        painter.drawPolygon(data_pts)

        # Data points and labels
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)

        for i, (name, score, color) in enumerate(self._categories):
            angle = -math.pi / 2 + i * angle_step
            r = radius * (score / 100.0)
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)

            # Dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(px, py), 4, 4)

            # Label at outer edge
            lx = cx + (radius + 18) * math.cos(angle)
            ly = cy + (radius + 18) * math.sin(angle)
            text = f"{name}\n{score:.0f}"
            tw = fm.horizontalAdvance(name)
            painter.setPen(QColor(color))
            align = Qt.AlignmentFlag.AlignCenter
            painter.drawText(QRectF(lx - tw / 2 - 8, ly - 14, tw + 16, 30), align, text)


# ── Power Trace Widget ────────────────────────────────────────────────────


class _PowerTraceWidget(QWidget):
    """Overlaid power trace visualization with leakage point highlighting."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._traces: list[list[float]] = []
        self._leakage_points: list[int] = []

    def set_data(self, traces: list[list[float]], leakage_points: list[int] | None = None) -> None:
        self._traces = traces
        self._leakage_points = leakage_points or []
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._traces:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        ml, mr, mt, mb = 50, 10, 10, 30
        pw = w - ml - mr
        ph = h - mt - mb

        all_vals = [v for t in self._traces for v in t]
        if not all_vals:
            return
        y_min, y_max = min(all_vals), max(all_vals)
        y_range = y_max - y_min if y_max != y_min else 1.0
        trace_len = max(len(t) for t in self._traces)

        # Axes
        painter.setPen(QPen(QColor(_SURFACE1), 1))
        painter.drawLine(ml, mt, ml, h - mb)
        painter.drawLine(ml, h - mb, w - mr, h - mb)

        # Leakage point highlights
        for lp in self._leakage_points:
            if 0 <= lp < trace_len:
                x = ml + lp / max(trace_len - 1, 1) * pw
                painter.setPen(Qt.PenStyle.NoPen)
                highlight = QColor(_CLR_RED)
                highlight.setAlpha(30)
                painter.setBrush(highlight)
                painter.drawRect(QRectF(x - 3, mt, 6, ph))

        # Traces
        colors = [_CLR_BLUE, _CLR_MAUVE, _CLR_TEAL, _CLR_PEACH, _CLR_GREEN]
        for ti, trace in enumerate(self._traces):
            tc = QColor(colors[ti % len(colors)])
            tc.setAlpha(80)
            pen = QPen(tc, 1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            for j, val in enumerate(trace):
                x = ml + j / max(len(trace) - 1, 1) * pw
                y = h - mb - (val - y_min) / y_range * ph
                if j == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.drawPath(path)

        # Leakage point markers on top
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_CLR_RED))
        for lp in self._leakage_points:
            if 0 <= lp < trace_len:
                x = ml + lp / max(trace_len - 1, 1) * pw
                painter.drawEllipse(QPointF(x, mt + 8), 4, 4)

        # Axis labels
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor(_SUBTEXT))
        painter.drawText(QRectF(0, mt, ml - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{y_max:.2f}")
        painter.drawText(QRectF(0, h - mb - 8, ml - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{y_min:.2f}")
        painter.drawText(QRectF(ml, h - mb + 2, pw, 16), Qt.AlignmentFlag.AlignLeft, "0")
        painter.drawText(QRectF(ml, h - mb + 2, pw, 16), Qt.AlignmentFlag.AlignRight, f"{trace_len}")

        # Title
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(ml, mt - 2, pw, 14), Qt.AlignmentFlag.AlignCenter, "Power Traces (Hamming Weight Model)")


# ── T-Statistic Plot ──────────────────────────────────────────────────────


class _TStatPlotWidget(QWidget):
    """TVLA t-statistic plot with threshold lines at +/-4.5."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._values: list[float] = []
        self._threshold: float = 4.5

    def set_data(self, values: list[float], threshold: float = 4.5) -> None:
        self._values = values
        self._threshold = threshold
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        ml, mr, mt, mb = 50, 10, 10, 30
        pw = w - ml - mr
        ph = h - mt - mb

        y_max = max(abs(v) for v in self._values)
        y_max = max(y_max, self._threshold + 1)
        n = len(self._values)

        # Axes
        painter.setPen(QPen(QColor(_SURFACE1), 1))
        painter.drawLine(ml, mt, ml, h - mb)
        painter.drawLine(ml, h - mb, w - mr, h - mb)

        # Zero line
        zero_y = mt + ph / 2
        painter.setPen(QPen(QColor(_OVERLAY0), 1, Qt.PenStyle.DashLine))
        painter.drawLine(ml, int(zero_y), w - mr, int(zero_y))

        # Threshold lines
        for sign in (1, -1):
            ty = zero_y - sign * (self._threshold / y_max) * (ph / 2)
            painter.setPen(QPen(QColor(_CLR_RED), 1, Qt.PenStyle.DashDotLine))
            painter.drawLine(ml, int(ty), w - mr, int(ty))

        # T-statistic curve
        path = QPainterPath()
        for i, val in enumerate(self._values):
            x = ml + i / max(n - 1, 1) * pw
            y = zero_y - (val / y_max) * (ph / 2)
            if abs(val) > self._threshold:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(_CLR_RED))
                painter.drawEllipse(QPointF(x, y), 3, 3)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QPen(QColor(_CLR_SAPPHIRE), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Labels
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor(_SUBTEXT))
        painter.drawText(QRectF(0, mt, ml - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"+{y_max:.1f}")
        painter.drawText(QRectF(0, h - mb - 8, ml - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"-{y_max:.1f}")

        # Title
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(ml, mt - 2, pw, 14), Qt.AlignmentFlag.AlignCenter, "TVLA T-Statistic (threshold = +/-4.5)")


# ── Donut Pie Chart ───────────────────────────────────────────────────────


class _PieChartWidget(QWidget):
    """Donut pie chart for fault injection results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(180, 200)
        self.setMaximumSize(220, 240)
        self._slices: list[tuple[str, float, str]] = []

    def set_data(self, slices: list[tuple[str, float, str]]) -> None:
        self._slices = slices
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._slices:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total = sum(v for _, v, _ in self._slices)
        if total <= 0:
            return

        w, h = self.width(), self.height()
        size = min(w, h - 40) - 20
        outer = QRectF((w - size) / 2, 10, size, size)
        inner_size = size * 0.55
        inner = QRectF((w - inner_size) / 2, 10 + (size - inner_size) / 2, inner_size, inner_size)

        start = 90 * 16
        for _label, value, color in self._slices:
            span = int(value / total * 360 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPie(outer, start, span)
            start += span

        # Donut hole
        painter.setBrush(QColor(_BG))
        painter.drawEllipse(inner)

        # Center text
        painter.setPen(QColor(_TEXT))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, f"{total:.0f}\nfaults")

        # Legend below
        legend_y = 10 + size + 8
        font.setPointSize(7)
        font.setBold(False)
        painter.setFont(font)
        x = 6
        for label, value, color in self._slices:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(x, legend_y, 8, 8))
            painter.setPen(QColor(_SUBTEXT))
            pct = value / total * 100 if total else 0
            text = f"{label} ({pct:.0f}%)"
            painter.drawText(QPointF(x + 12, legend_y + 8), text)
            x += QFontMetrics(font).horizontalAdvance(text) + 18


# ── Entropy Flow Diagram ─────────────────────────────────────────────────


class _EntropyFlowScene(QGraphicsScene):
    """QGraphicsScene for entropy source -> conditioner -> sink flow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QColor(_BG))

    def build_demo(self) -> None:
        self.clear()
        sources = ["TRNG Ring Osc.", "PLL Jitter", "ADC Noise"]
        conditioners = ["Von Neumann", "SHA-256 Cond."]
        sinks = ["DRBG Seed", "Nonce Gen", "Key Gen"]

        col_x = [40, 260, 480]
        y_step = 70
        node_w, node_h = 140, 40

        font = QFont()
        font.setPointSize(9)

        # Draw nodes
        source_nodes = []
        for i, name in enumerate(sources):
            y = 30 + i * y_step
            self.addRect(QRectF(col_x[0], y, node_w, node_h),
                             QPen(QColor(_CLR_GREEN), 2), QBrush(QColor(_SURFACE0)))
            t = self.addSimpleText(name, font)
            t.setBrush(QColor(_CLR_GREEN))
            t.setPos(col_x[0] + 8, y + 10)
            source_nodes.append((col_x[0] + node_w, y + node_h / 2))

        cond_nodes = []
        for i, name in enumerate(conditioners):
            y = 50 + i * y_step
            self.addRect(QRectF(col_x[1], y, node_w, node_h),
                             QPen(QColor(_CLR_YELLOW), 2), QBrush(QColor(_SURFACE0)))
            t = self.addSimpleText(name, font)
            t.setBrush(QColor(_CLR_YELLOW))
            t.setPos(col_x[1] + 8, y + 10)
            cond_nodes.append((col_x[1], y + node_h / 2, col_x[1] + node_w, y + node_h / 2))

        sink_nodes = []
        for i, name in enumerate(sinks):
            y = 30 + i * y_step
            color = _CLR_GREEN if i < 2 else _CLR_RED
            self.addRect(QRectF(col_x[2], y, node_w, node_h),
                             QPen(QColor(color), 2), QBrush(QColor(_SURFACE0)))
            t = self.addSimpleText(name, font)
            t.setBrush(QColor(color))
            t.setPos(col_x[2] + 8, y + 10)
            sink_nodes.append((col_x[2], y + node_h / 2))

        # Edges: sources -> conditioners
        edge_pen = QPen(QColor(_CLR_BLUE), 1.5)
        edge_pen.setStyle(Qt.PenStyle.SolidLine)
        bits_font = QFont()
        bits_font.setPointSize(7)

        for sx, sy in source_nodes:
            for clx, cy, _crx, _cry in cond_nodes:
                self.addLine(sx, sy, clx, cy, edge_pen)

        # Edges: conditioners -> sinks
        for _clx, _cy, crx, cry in cond_nodes:
            for skx, sky in sink_nodes:
                self.addLine(crx, cry, skx, sky, edge_pen)

        # Bit annotations
        for _clx, _cy, crx, cry in cond_nodes:
            for skx, sky in sink_nodes:
                mid_x = (crx + skx) / 2
                mid_y = (cry + sky) / 2
                bits_val = random.choice([128, 256, 64])
                bt = self.addSimpleText(f"{bits_val}b", bits_font)
                bt.setBrush(QColor(_SUBTEXT))
                bt.setPos(mid_x - 8, mid_y - 12)


# ══════════════════════════════════════════════════════════════════════════
# Tab: Overview
# ══════════════════════════════════════════════════════════════════════════


class _OverviewTab(QWidget):
    """Security overview: gauge, radar chart, findings summary."""

    run_analysis_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Top row: gauge + radar
        top_row = QHBoxLayout()

        # Left: Score gauge
        gauge_box = QVBoxLayout()
        self._gauge = _ScoreGaugeWidget()
        gauge_box.addWidget(self._gauge, alignment=Qt.AlignmentFlag.AlignCenter)
        top_row.addLayout(gauge_box)

        # Right: Radar chart
        self._radar = _RadarChartWidget()
        top_row.addWidget(self._radar, stretch=1)
        root.addLayout(top_row, stretch=1)

        # Category scores table
        root.addWidget(_header_label("Category Scores"))
        self._cat_table = QTableWidget(6, 4)
        self._cat_table.setHorizontalHeaderLabels(["Category", "Score", "Issues", "Status"])
        _configure_table(self._cat_table)
        self._cat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._cat_table.setMaximumHeight(220)
        root.addWidget(self._cat_table)

        # Findings summary
        findings_row = QHBoxLayout()
        self._lbl_critical = QLabel("0 Critical")
        self._lbl_critical.setStyleSheet(f"color: {_CLR_RED}; font-weight: bold; font-size: 14px; padding: 4px 12px;")
        self._lbl_warnings = QLabel("0 Warnings")
        self._lbl_warnings.setStyleSheet(f"color: {_CLR_YELLOW}; font-weight: bold; font-size: 14px; padding: 4px 12px;")
        self._lbl_info = QLabel("0 Info")
        self._lbl_info.setStyleSheet(f"color: {_CLR_BLUE}; font-weight: bold; font-size: 14px; padding: 4px 12px;")
        findings_row.addWidget(self._lbl_critical)
        findings_row.addWidget(self._lbl_warnings)
        findings_row.addWidget(self._lbl_info)
        findings_row.addStretch()
        root.addLayout(findings_row)

        # Timestamp and button row
        btn_row = QHBoxLayout()
        self._lbl_timestamp = _dim_label("Last analysis: Never")
        btn_row.addWidget(self._lbl_timestamp)
        btn_row.addStretch()
        self._btn_run = _accent_button("Run Full Security Analysis")
        self._btn_run.clicked.connect(self.run_analysis_requested.emit)
        btn_row.addWidget(self._btn_run)
        root.addLayout(btn_row)

    def populate(
        self,
        overall_score: float,
        categories: list[tuple[str, float, int, str, str]],  # name, score, issues, status, color
        critical: int,
        warnings: int,
        info: int,
        timestamp: str,
        duration: str,
    ) -> None:
        self._gauge.set_score(overall_score)
        self._radar.set_data([(n, s, c) for n, s, _i, _st, c in categories])

        self._cat_table.setRowCount(len(categories))
        for row, (name, score, issues, status, color) in enumerate(categories):
            self._cat_table.setItem(row, 0, _text_item(name, color))
            self._cat_table.setItem(row, 1, _numeric_item(score, "{:.0f}", _score_color(score)))
            self._cat_table.setItem(row, 2, _numeric_item(issues, "{:.0f}", _CLR_YELLOW if issues > 0 else _CLR_GREEN))
            self._cat_table.setItem(row, 3, _text_item(status, _status_color(status)))

        self._lbl_critical.setText(f"{critical} Critical")
        self._lbl_warnings.setText(f"{warnings} Warnings")
        self._lbl_info.setText(f"{info} Info")
        self._lbl_timestamp.setText(f"Last analysis: {timestamp} ({duration})")


# ══════════════════════════════════════════════════════════════════════════
# Tab: Constant-Time
# ══════════════════════════════════════════════════════════════════════════


class _ConstantTimeTab(QWidget):
    """Taint propagation tree, violations table, SVA generation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: Taint propagation tree
        top_w = QWidget()
        top_layout = QVBoxLayout(top_w)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(_header_label("Taint Propagation"))

        self._taint_tree = QTreeWidget()
        self._taint_tree.setHeaderLabels(["Signal", "Taint Status", "Module", "Taint Path"])
        self._taint_tree.setAlternatingRowColors(True)
        self._taint_tree.setStyleSheet(f"QTreeWidget {{ alternate-background-color: {_ALT_ROW}; }}")
        self._taint_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._taint_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        top_layout.addWidget(self._taint_tree)
        splitter.addWidget(top_w)

        # Bottom: Violations table
        bot_w = QWidget()
        bot_layout = QVBoxLayout(bot_w)
        bot_layout.setContentsMargins(0, 0, 0, 0)
        bot_layout.addWidget(_header_label("Violations"))

        self._violations_table = QTableWidget(0, 5)
        self._violations_table.setHorizontalHeaderLabels(["Signal", "Location", "Type", "Severity", "Description"])
        _configure_table(self._violations_table)
        self._violations_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._violations_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        bot_layout.addWidget(self._violations_table)

        # SVA output area
        self._sva_output = QTextEdit()
        self._sva_output.setReadOnly(True)
        self._sva_output.setMaximumHeight(120)
        self._sva_output.setPlaceholderText("Generated SVA properties will appear here...")
        self._sva_output.setStyleSheet(
            f"QTextEdit {{ background-color: {_MANTLE}; color: {_CLR_GREEN}; "
            f"font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px; "
            f"border: 1px solid {_SURFACE0}; }}"
        )
        bot_layout.addWidget(self._sva_output)
        self._sva_output.setVisible(False)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_run_ct = _accent_button("Run CT Analysis", _CLR_BLUE)
        btn_row.addWidget(self._btn_run_ct)
        self._btn_gen_sva = _accent_button("Generate SVA Properties", _CLR_MAUVE)
        self._btn_gen_sva.clicked.connect(self._toggle_sva)
        btn_row.addWidget(self._btn_gen_sva)
        btn_row.addStretch()
        bot_layout.addLayout(btn_row)

        splitter.addWidget(bot_w)
        splitter.setSizes([300, 300])
        root.addWidget(splitter)

    def _toggle_sva(self) -> None:
        self._sva_output.setVisible(not self._sva_output.isVisible())

    def populate(
        self,
        signals: list[dict],
        violations: list[dict],
        sva_text: str,
    ) -> None:
        """Populate the constant-time tab.

        signals: list of {name, status, module, path}
        violations: list of {signal, location, type, severity, description}
        """
        self._taint_tree.clear()
        status_colors = {"SECRET": _CLR_RED, "PUBLIC": _CLR_GREEN, "MIXED": _CLR_YELLOW}
        for sig in signals:
            item = QTreeWidgetItem([sig["name"], sig["status"], sig["module"], sig.get("path", "")])
            item.setForeground(1, QColor(status_colors.get(sig["status"], _TEXT)))
            self._taint_tree.addTopLevelItem(item)

            # Add taint path as children if present
            for step in sig.get("path_steps", []):
                child = QTreeWidgetItem(["", step, "", ""])
                child.setForeground(1, QColor(_SUBTEXT))
                item.addChild(child)

        self._violations_table.setRowCount(len(violations))
        severity_colors = {"CRITICAL": _CLR_RED, "HIGH": _CLR_PEACH, "MEDIUM": _CLR_YELLOW, "LOW": _CLR_BLUE}
        for row, v in enumerate(violations):
            self._violations_table.setItem(row, 0, _text_item(v["signal"], _CLR_RED))
            self._violations_table.setItem(row, 1, _text_item(v["location"]))
            self._violations_table.setItem(row, 2, _text_item(v["type"], _CLR_MAUVE))
            self._violations_table.setItem(row, 3, _text_item(v["severity"], severity_colors.get(v["severity"], _TEXT)))
            self._violations_table.setItem(row, 4, _text_item(v["description"]))

        self._sva_output.setPlainText(sva_text)


# ══════════════════════════════════════════════════════════════════════════
# Tab: Side-Channel
# ══════════════════════════════════════════════════════════════════════════


class _SideChannelTab(QWidget):
    """Power traces, TVLA, CPA results, and controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: Power traces and TVLA
        top_w = QWidget()
        top_layout = QVBoxLayout(top_w)
        top_layout.setContentsMargins(0, 0, 0, 0)

        top_layout.addWidget(_header_label("Power Trace Analysis"))
        self._power_trace = _PowerTraceWidget()
        top_layout.addWidget(self._power_trace)

        top_layout.addWidget(_header_label("TVLA Results"))
        self._tstat_plot = _TStatPlotWidget()
        top_layout.addWidget(self._tstat_plot)

        splitter.addWidget(top_w)

        # Bottom: CPA + controls
        bot_w = QWidget()
        bot_layout = QVBoxLayout(bot_w)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        # Leakage points table
        bot_layout.addWidget(_header_label("Leakage Points"))
        self._leakage_table = QTableWidget(0, 3)
        self._leakage_table.setHorizontalHeaderLabels(["Time Index", "T-Value", "Significance"])
        _configure_table(self._leakage_table)
        self._leakage_table.setMaximumHeight(120)
        bot_layout.addWidget(self._leakage_table)

        # CPA key rank table
        bot_layout.addWidget(_header_label("CPA Key Rank"))
        self._key_rank_table = QTableWidget(0, 3)
        self._key_rank_table.setHorizontalHeaderLabels(["Key Guess (hex)", "Correlation", "Rank"])
        _configure_table(self._key_rank_table)
        self._key_rank_table.setMaximumHeight(120)
        bot_layout.addWidget(self._key_rank_table)

        # Verdict
        self._verdict_label = QLabel("Verdict: --")
        self._verdict_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 14px; font-weight: bold; padding: 4px;")
        bot_layout.addWidget(self._verdict_label)

        # Controls row
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(_dim_label("Traces:"))
        self._trace_slider = QSlider(Qt.Orientation.Horizontal)
        self._trace_slider.setRange(100, 100000)
        self._trace_slider.setValue(10000)
        self._trace_slider.setFixedWidth(160)
        ctrl_row.addWidget(self._trace_slider)
        self._trace_count_lbl = _dim_label("10000")
        self._trace_slider.valueChanged.connect(lambda v: self._trace_count_lbl.setText(str(v)))
        ctrl_row.addWidget(self._trace_count_lbl)

        ctrl_row.addWidget(_dim_label("Power Model:"))
        self._model_combo = QComboBox()
        self._model_combo.addItems(["Hamming Weight", "Hamming Distance", "Identity", "Bit Model"])
        ctrl_row.addWidget(self._model_combo)

        ctrl_row.addWidget(_dim_label("Threshold:"))
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(1, 20)
        self._threshold_spin.setValue(5)
        ctrl_row.addWidget(self._threshold_spin)

        ctrl_row.addStretch()
        bot_layout.addLayout(ctrl_row)

        splitter.addWidget(bot_w)
        splitter.setSizes([350, 350])
        root.addWidget(splitter)

    def populate(
        self,
        traces: list[list[float]],
        leakage_points: list[int],
        t_values: list[float],
        leakage_entries: list[dict],
        key_ranks: list[dict],
        verdict: str,
    ) -> None:
        self._power_trace.set_data(traces, leakage_points)
        self._tstat_plot.set_data(t_values)

        self._leakage_table.setRowCount(len(leakage_entries))
        for row, entry in enumerate(leakage_entries):
            self._leakage_table.setItem(row, 0, _numeric_item(entry["time_idx"], "{:.0f}"))
            self._leakage_table.setItem(row, 1, _numeric_item(entry["t_value"], "{:.2f}", _CLR_RED))
            self._leakage_table.setItem(row, 2, _text_item(entry["significance"], _CLR_RED))

        self._key_rank_table.setRowCount(len(key_ranks))
        for row, kr in enumerate(key_ranks):
            self._key_rank_table.setItem(row, 0, _text_item(kr["key_hex"], _CLR_MAUVE))
            self._key_rank_table.setItem(row, 1, _numeric_item(kr["correlation"], "{:.4f}"))
            self._key_rank_table.setItem(row, 2, _numeric_item(kr["rank"], "{:.0f}"))

        v_color = _CLR_RED if "Vulnerable" in verdict else _CLR_GREEN
        self._verdict_label.setText(f"Verdict: {verdict}")
        self._verdict_label.setStyleSheet(f"color: {v_color}; font-size: 14px; font-weight: bold; padding: 4px;")


# ══════════════════════════════════════════════════════════════════════════
# Tab: FIPS Compliance
# ══════════════════════════════════════════════════════════════════════════


class _FIPSComplianceTab(QWidget):
    """FIPS 140-3 checklist with grouped requirements, progress, export."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Progress bar
        prog_row = QHBoxLayout()
        prog_row.addWidget(_header_label("FIPS 140-3 Compliance"))
        prog_row.addStretch()
        self._progress_label = _dim_label("0 / 0 checks passed")
        prog_row.addWidget(self._progress_label)
        root.addLayout(prog_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

        # Requirements tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["ID", "Description", "Status", "Evidence"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"QTreeWidget {{ alternate-background-color: {_ALT_ROW}; }}")
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._tree.setColumnWidth(0, 80)
        self._tree.setColumnWidth(2, 100)
        root.addWidget(self._tree, stretch=1)

        # Button row
        btn_row = QHBoxLayout()
        self._btn_generate = _accent_button("Generate FIPS Report", _CLR_PEACH)
        btn_row.addWidget(self._btn_generate)

        self._btn_pdf = QPushButton("Export PDF")
        btn_row.addWidget(self._btn_pdf)
        self._btn_html = QPushButton("Export HTML")
        btn_row.addWidget(self._btn_html)
        self._btn_csv = QPushButton("Export CSV")
        btn_row.addWidget(self._btn_csv)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def populate(self, results: dict[str, str], evidence: dict[str, str] | None = None) -> None:
        """Populate with check results.

        results: {check_id: "PASS" | "FAIL" | "WARNING" | "N/A"}
        evidence: {check_id: evidence_text}
        """
        evidence = evidence or {}
        self._tree.clear()
        total, passed = 0, 0

        for group_name, checks in _FIPS_GROUPS:
            group_item = QTreeWidgetItem([group_name, "", "", ""])
            group_item.setForeground(0, QColor(_CLR_BLUE))
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            self._tree.addTopLevelItem(group_item)

            for check_id, desc in checks:
                status = results.get(check_id, "N/A")
                ev = evidence.get(check_id, "")
                child = QTreeWidgetItem([check_id, desc, status, ev])
                child.setForeground(2, QColor(_status_color(status)))
                group_item.addChild(child)
                total += 1
                if status == "PASS":
                    passed += 1

            group_item.setExpanded(True)

        pct = int(passed / total * 100) if total > 0 else 0
        self._progress.setValue(pct)
        self._progress_label.setText(f"{passed} / {total} checks passed ({pct}%)")

        # Colour the progress bar
        if pct >= 80:
            color = _CLR_GREEN
        elif pct >= 50:
            color = _CLR_YELLOW
        else:
            color = _CLR_RED
        self._progress.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Tab: Entropy
# ══════════════════════════════════════════════════════════════════════════


class _EntropyTab(QWidget):
    """Entropy flow diagram, issues, NIST SP 800-90B test results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: Flow diagram
        top_w = QWidget()
        top_layout = QVBoxLayout(top_w)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(_header_label("Entropy Flow Diagram"))

        self._scene = _EntropyFlowScene()
        self._view = QGraphicsView(self._scene)
        self._view.setMinimumHeight(200)
        self._view.setStyleSheet(f"border: 1px solid {_SURFACE0};")
        top_layout.addWidget(self._view)
        splitter.addWidget(top_w)

        # Bottom: Issues + NIST results
        bot_w = QWidget()
        bot_layout = QVBoxLayout(bot_w)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        bot_layout.addWidget(_header_label("Entropy Issues"))
        self._issues_table = QTableWidget(0, 4)
        self._issues_table.setHorizontalHeaderLabels(["Source", "Issue", "Severity", "Recommendation"])
        _configure_table(self._issues_table)
        self._issues_table.setMaximumHeight(120)
        bot_layout.addWidget(self._issues_table)

        bot_layout.addWidget(_header_label("NIST SP 800-90B Test Results"))
        self._nist_table = QTableWidget(0, 4)
        self._nist_table.setHorizontalHeaderLabels(["Test", "Statistic", "Threshold", "Result"])
        _configure_table(self._nist_table)
        bot_layout.addWidget(self._nist_table)

        splitter.addWidget(bot_w)
        splitter.setSizes([250, 300])
        root.addWidget(splitter)

    def populate(
        self,
        issues: list[dict],
        nist_results: list[dict],
    ) -> None:
        self._scene.build_demo()

        self._issues_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            sev_color = {"CRITICAL": _CLR_RED, "HIGH": _CLR_PEACH, "MEDIUM": _CLR_YELLOW, "LOW": _CLR_GREEN}
            self._issues_table.setItem(row, 0, _text_item(issue["source"]))
            self._issues_table.setItem(row, 1, _text_item(issue["issue"], _CLR_YELLOW))
            self._issues_table.setItem(row, 2, _text_item(issue["severity"], sev_color.get(issue["severity"], _TEXT)))
            self._issues_table.setItem(row, 3, _text_item(issue["recommendation"]))

        self._nist_table.setRowCount(len(nist_results))
        for row, nr in enumerate(nist_results):
            result_color = _CLR_GREEN if nr["result"] == "PASS" else _CLR_RED
            self._nist_table.setItem(row, 0, _text_item(nr["test"]))
            self._nist_table.setItem(row, 1, _numeric_item(nr["statistic"], "{:.4f}"))
            self._nist_table.setItem(row, 2, _numeric_item(nr["threshold"], "{:.4f}"))
            self._nist_table.setItem(row, 3, _text_item(nr["result"], result_color))


# ══════════════════════════════════════════════════════════════════════════
# Tab: Fault Injection
# ══════════════════════════════════════════════════════════════════════════


class _FaultInjectionTab(QWidget):
    """Fault campaign results, pie chart, resilience score, countermeasures."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: results table + pie chart side by side
        top_w = QWidget()
        top_layout = QHBoxLayout(top_w)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Left: fault campaign table
        table_box = QVBoxLayout()
        table_box.addWidget(_header_label("Fault Campaign Results"))
        self._fault_table = QTableWidget(0, 6)
        self._fault_table.setHorizontalHeaderLabels(
            ["Model", "Target", "Detected?", "Output Affected?", "Key Leaked?", "Classification"]
        )
        _configure_table(self._fault_table)
        table_box.addWidget(self._fault_table)
        top_layout.addLayout(table_box, stretch=2)

        # Right: pie chart + resilience score
        chart_box = QVBoxLayout()
        chart_box.addWidget(_header_label("Fault Classification"))
        self._pie = _PieChartWidget()
        chart_box.addWidget(self._pie, alignment=Qt.AlignmentFlag.AlignCenter)

        self._resilience_label = QLabel("Resilience Score: --")
        self._resilience_label.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-weight: bold; padding: 4px;")
        self._resilience_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_box.addWidget(self._resilience_label)

        self._recommendation = QLabel("")
        self._recommendation.setWordWrap(True)
        self._recommendation.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px; padding: 4px;")
        chart_box.addWidget(self._recommendation)
        chart_box.addStretch()
        top_layout.addLayout(chart_box, stretch=1)

        splitter.addWidget(top_w)

        # Bottom: countermeasure checklist + controls
        bot_w = QWidget()
        bot_layout = QVBoxLayout(bot_w)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        bot_layout.addWidget(_header_label("Countermeasure Checklist"))
        countermeasures = [
            ("Triple Modular Redundancy (TMR)", "Replicate critical logic 3x with majority voter"),
            ("Dual-Rail Logic", "Complementary signal pairs for glitch detection"),
            ("Error Detection Codes", "Parity / CRC on datapath and control signals"),
            ("Temporal Redundancy", "Execute operations twice and compare"),
            ("Instruction Flow Monitoring", "FSM watchdog for expected state transitions"),
            ("Voltage Glitch Detectors", "Analog sensors for supply voltage anomalies"),
            ("Clock Glitch Detectors", "PLL lock-loss and frequency-out-of-range detection"),
            ("Laser Fault Detectors", "Light-sensitive shields and sensors"),
        ]

        cm_grid = QVBoxLayout()
        self._cm_checks: list[QCheckBox] = []
        for name, desc in countermeasures:
            cb = QCheckBox(f"{name}  --  {desc}")
            cb.setStyleSheet(f"QCheckBox {{ color: {_TEXT}; font-size: 12px; padding: 2px; }}")
            cm_grid.addWidget(cb)
            self._cm_checks.append(cb)
        bot_layout.addLayout(cm_grid)

        # Controls
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(_dim_label("Fault Model:"))
        self._model_combo = QComboBox()
        self._model_combo.addItems(["Glitch (clock/voltage)", "Bit Flip (SEU)", "Laser (spatial)", "All Models"])
        ctrl_row.addWidget(self._model_combo)
        ctrl_row.addStretch()
        self._btn_run_fault = _accent_button("Run Fault Campaign", _CLR_RED)
        ctrl_row.addWidget(self._btn_run_fault)
        bot_layout.addLayout(ctrl_row)

        splitter.addWidget(bot_w)
        splitter.setSizes([350, 300])
        root.addWidget(splitter)

    def populate(
        self,
        faults: list[dict],
        classification: dict[str, float],
        resilience_score: float,
        recommendation: str,
        active_countermeasures: list[int] | None = None,
    ) -> None:
        self._fault_table.setRowCount(len(faults))
        for row, f in enumerate(faults):
            cls_colors = {"critical": _CLR_RED, "undetected": _CLR_PEACH, "detected": _CLR_YELLOW, "safe_error": _CLR_GREEN}
            self._fault_table.setItem(row, 0, _text_item(f["model"]))
            self._fault_table.setItem(row, 1, _text_item(f["target"]))
            self._fault_table.setItem(row, 2, _text_item(f["detected"], _CLR_GREEN if f["detected"] == "Yes" else _CLR_RED))
            self._fault_table.setItem(row, 3, _text_item(f["output_affected"], _CLR_RED if f["output_affected"] == "Yes" else _CLR_GREEN))
            self._fault_table.setItem(row, 4, _text_item(f["key_leaked"], _CLR_RED if f["key_leaked"] == "Yes" else _CLR_GREEN))
            self._fault_table.setItem(row, 5, _text_item(f["classification"], cls_colors.get(f["classification"], _TEXT)))

        slices = [
            ("Safe Error", classification.get("safe_error", 0), _CLR_GREEN),
            ("Detected", classification.get("detected", 0), _CLR_YELLOW),
            ("Undetected", classification.get("undetected", 0), _CLR_PEACH),
            ("Critical", classification.get("critical", 0), _CLR_RED),
        ]
        self._pie.set_data(slices)

        r_color = _score_color(resilience_score)
        self._resilience_label.setText(f"Resilience Score: {resilience_score:.0f}/100")
        self._resilience_label.setStyleSheet(f"color: {r_color}; font-size: 16px; font-weight: bold; padding: 4px;")
        self._recommendation.setText(recommendation)

        if active_countermeasures:
            for idx in active_countermeasures:
                if 0 <= idx < len(self._cm_checks):
                    self._cm_checks[idx].setChecked(True)


# ══════════════════════════════════════════════════════════════════════════
# SecurityPanel -- the main dock widget
# ══════════════════════════════════════════════════════════════════════════


class SecurityPanel(QDockWidget):
    """Crypto security analysis dock widget with six specialized tabs."""

    def __init__(self, title: str = "Security", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setMinimumWidth(420)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {_BG};
            }}
            QTabBar::tab {{
                background-color: {_SURFACE0};
                color: {_SUBTEXT};
                border: none;
                padding: 6px 14px;
                font-size: 11px;
                margin-right: 1px;
                min-width: 50px;
            }}
            QTabBar::tab:selected {{
                background-color: {_BG};
                color: {_TEXT};
                border-bottom: 2px solid {_CLR_BLUE};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {_SURFACE1};
                color: {_TEXT};
            }}
            QGroupBox {{
                background-color: {_MANTLE};
                border: 1px solid {_SURFACE0};
                border-radius: 4px;
                margin-top: 14px;
                padding: 10px 8px 8px 8px;
                font-size: 11px;
                font-weight: bold;
                color: {_CLR_BLUE};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
            }}
            QPushButton {{
                background-color: {_SURFACE0};
                color: {_TEXT};
                border: 1px solid {_SURFACE1};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {_SURFACE1};
                border-color: {_CLR_BLUE};
            }}
            QPushButton:pressed {{
                background-color: {_SURFACE2};
            }}
            QPushButton:checked {{
                background-color: {_CLR_BLUE};
                color: {_CRUST};
                border-color: {_CLR_BLUE};
            }}
            QLineEdit, QComboBox, QSpinBox {{
                background-color: {_SURFACE0};
                color: {_TEXT};
                border: 1px solid {_SURFACE1};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 11px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border-color: {_CLR_BLUE};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {_SURFACE0};
                color: {_TEXT};
                selection-background-color: {_SURFACE1};
                border: 1px solid {_SURFACE1};
            }}
            QLabel {{
                color: {_TEXT};
                font-size: 11px;
            }}
            QProgressBar {{
                background-color: {_SURFACE0};
                border: none;
                border-radius: 3px;
                text-align: center;
                color: {_TEXT};
                font-size: 10px;
                max-height: 18px;
            }}
            QProgressBar::chunk {{
                background-color: {_CLR_BLUE};
                border-radius: 3px;
            }}
            QSlider::groove:horizontal {{
                background: {_SURFACE0};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {_CLR_BLUE};
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {_CLR_BLUE};
                border-radius: 3px;
            }}
            QCheckBox {{
                color: {_TEXT};
                font-size: 11px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid {_SURFACE1};
                background-color: {_SURFACE0};
            }}
            QCheckBox::indicator:checked {{
                background-color: {_CLR_BLUE};
                border-color: {_CLR_BLUE};
            }}
            QSplitter::handle {{
                background-color: {_SURFACE0};
                height: 2px;
                width: 2px;
            }}
            QHeaderView::section {{
                background-color: {_MANTLE};
                color: {_SUBTEXT};
                border: none;
                border-right: 1px solid {_SURFACE0};
                border-bottom: 1px solid {_SURFACE0};
                padding: 4px 6px;
                font-size: 11px;
                font-weight: bold;
            }}
        """)

        self._overview_tab = _OverviewTab()
        self._ct_tab = _ConstantTimeTab()
        self._sca_tab = _SideChannelTab()
        self._fips_tab = _FIPSComplianceTab()
        self._entropy_tab = _EntropyTab()
        self._fault_tab = _FaultInjectionTab()

        self._tabs.addTab(_scrollable(self._overview_tab), "Overview")
        self._tabs.addTab(_scrollable(self._ct_tab), "Constant-Time")
        self._tabs.addTab(_scrollable(self._sca_tab), "Side-Channel")
        self._tabs.addTab(_scrollable(self._fips_tab), "FIPS 140-3")
        self._tabs.addTab(_scrollable(self._entropy_tab), "Entropy")
        self._tabs.addTab(_scrollable(self._fault_tab), "Fault Injection")

        layout.addWidget(self._tabs)
        self.setWidget(container)

    def set_theme(self, dark: bool) -> None:
        """Switch panel QSS between dark and light themes."""
        from openforge_desktop.panels._theme import panel_tab_qss
        extra = f"""
            QCheckBox {{
                color: {'#cdd6f4' if dark else '#212529'};
                font-size: 11px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid {'#45475a' if dark else '#ced4da'};
                background-color: {'#313244' if dark else '#dee2e6'};
            }}
            QCheckBox::indicator:checked {{
                background-color: {'#89b4fa' if dark else '#0d6efd'};
                border-color: {'#89b4fa' if dark else '#0d6efd'};
            }}
        """
        self._tabs.setStyleSheet(panel_tab_qss(dark, extra=extra))

    def run_analysis(self, source_files: list[str], top_module: str) -> None:
        """Run real crypto security analysis using CryptoWorker backend.

        Creates a CryptoWorker, connects its signals, and updates all tabs
        with real results when the analysis completes.  Falls back to demo
        data if no CryptoWorker is available.
        """
        try:
            from openforge_desktop.workers import CryptoWorker
            self._crypto_worker = CryptoWorker(
                source_files=source_files,
                top_module=top_module,
                parent=self,
            )
            self._crypto_worker.finished.connect(self.update_from_crypto_result)
            self._crypto_worker.error.connect(self._on_crypto_error)
            self._crypto_worker.start()
        except (ImportError, AttributeError):
            # CryptoWorker not available yet, use demo data
            self.show_demo_data()

    def update_from_crypto_result(self, result: object) -> None:
        """Populate all 6 tabs from actual analysis data.

        Parameters
        ----------
        result:
            Object with attributes matching the crypto analysis output.
            Falls back to demo data for any missing attributes.
        """
        try:
            # Overview
            if hasattr(result, "overall_score"):
                categories = getattr(result, "categories", [])
                self._overview_tab.populate(
                    overall_score=result.overall_score,
                    categories=categories,
                    critical=getattr(result, "critical_count", 0),
                    warnings=getattr(result, "warning_count", 0),
                    info=getattr(result, "info_count", 0),
                    timestamp=getattr(result, "timestamp", "now"),
                    duration=getattr(result, "duration", "--"),
                )
            else:
                self._populate_overview_demo()

            # Constant-time
            if hasattr(result, "ct_signals"):
                self._ct_tab.populate(
                    result.ct_signals,
                    getattr(result, "ct_violations", []),
                    getattr(result, "sva_text", ""),
                )
            else:
                self._populate_ct_demo()

            # Side-channel
            if hasattr(result, "sca_traces"):
                self._sca_tab.populate(
                    traces=result.sca_traces,
                    leakage_points=getattr(result, "leakage_points", []),
                    t_values=getattr(result, "t_values", []),
                    leakage_entries=getattr(result, "leakage_entries", []),
                    key_ranks=getattr(result, "key_ranks", []),
                    verdict=getattr(result, "sca_verdict", "--"),
                )
            else:
                self._populate_sca_demo()

            # FIPS
            if hasattr(result, "fips_results"):
                self._fips_tab.populate(
                    result.fips_results,
                    getattr(result, "fips_evidence", None),
                )
            else:
                self._populate_fips_demo()

            # Entropy
            if hasattr(result, "entropy_issues"):
                self._entropy_tab.populate(
                    result.entropy_issues,
                    getattr(result, "nist_results", []),
                )
            else:
                self._populate_entropy_demo()

            # Fault injection
            if hasattr(result, "fault_results"):
                self._fault_tab.populate(
                    faults=result.fault_results,
                    classification=getattr(result, "fault_classification", {}),
                    resilience_score=getattr(result, "resilience_score", 0.0),
                    recommendation=getattr(result, "fault_recommendation", ""),
                    active_countermeasures=getattr(result, "active_countermeasures", None),
                )
            else:
                self._populate_fault_demo()
        except Exception:
            # If anything fails, fall back to demo data
            self.show_demo_data()

    def _on_crypto_error(self, msg: str) -> None:
        """Handle CryptoWorker error by falling back to demo data."""
        self.show_demo_data()

    def show_demo_data(self) -> None:
        """Populate all tabs with representative demo data."""
        self._populate_overview_demo()
        self._populate_ct_demo()
        self._populate_sca_demo()
        self._populate_fips_demo()
        self._populate_entropy_demo()
        self._populate_fault_demo()

    # ── Demo data generators ──────────────────────────────────────────

    def _populate_overview_demo(self) -> None:
        categories = [
            ("Constant-Time", 72.0, 3, "WARNING", _CLR_BLUE),
            ("Power SCA", 85.0, 1, "PASS", _CLR_MAUVE),
            ("Fault Injection", 58.0, 5, "WARNING", _CLR_RED),
            ("Entropy", 91.0, 0, "PASS", _CLR_GREEN),
            ("FIPS 140-3", 67.0, 8, "WARNING", _CLR_PEACH),
            ("Key Handling", 88.0, 1, "PASS", _CLR_TEAL),
        ]
        overall = sum(s for _, s, *_ in categories) / len(categories)
        self._overview_tab.populate(
            overall_score=overall,
            categories=categories,
            critical=2,
            warnings=7,
            info=12,
            timestamp="2026-04-05 14:32:18",
            duration="4.7s",
        )

    def _populate_ct_demo(self) -> None:
        signals = [
            {"name": "aes_core.key_reg", "status": "SECRET", "module": "aes_core",
             "path": "key_in -> key_reg", "path_steps": ["key_in", "key_expand.round_key", "key_reg"]},
            {"name": "aes_core.sbox_out", "status": "SECRET", "module": "aes_core",
             "path": "key_reg -> sbox_in -> sbox_out", "path_steps": ["key_reg", "sbox_in", "sbox_out"]},
            {"name": "aes_core.plaintext", "status": "PUBLIC", "module": "aes_core",
             "path": "", "path_steps": []},
            {"name": "aes_core.round_sel", "status": "MIXED", "module": "aes_core",
             "path": "state -> round_sel", "path_steps": ["state_reg", "round_logic", "round_sel"]},
            {"name": "aes_core.done", "status": "PUBLIC", "module": "aes_core",
             "path": "", "path_steps": []},
        ]
        violations = [
            {"signal": "aes_core.round_sel", "location": "aes_core.sv:142", "type": "branch",
             "severity": "CRITICAL", "description": "If condition depends on tainted signal 'round_sel'"},
            {"signal": "aes_core.sbox_addr", "location": "aes_sbox.sv:38", "type": "address",
             "severity": "HIGH", "description": "Memory index derived from secret key byte"},
            {"signal": "aes_core.mul_op", "location": "gf_mult.sv:12", "type": "variable-latency",
             "severity": "MEDIUM", "description": "GF multiply with data-dependent timing path"},
        ]
        sva = (
            "// Auto-generated CT non-interference properties\n"
            "// Design: aes_core\n\n"
            "property ct_no_branch_leak;\n"
            "  @(posedge clk) disable iff (rst)\n"
            "    (key_a != key_b) |-> (done_a == done_b);\n"
            "endproperty\n"
            "assert property (ct_no_branch_leak);\n\n"
            "property ct_fixed_latency;\n"
            "  @(posedge clk) disable iff (rst)\n"
            "    $rose(start) |-> ##[10:10] $rose(done);\n"
            "endproperty\n"
            "assert property (ct_fixed_latency);"
        )
        self._ct_tab.populate(signals, violations, sva)

    def _populate_sca_demo(self) -> None:
        random.seed(42)
        n_samples = 200
        traces = []
        for _ in range(8):
            trace = [3.0 + 0.5 * math.sin(i / 10.0) + random.gauss(0, 0.3) for i in range(n_samples)]
            # Add leakage bump
            for lp in [45, 120, 175]:
                if lp < n_samples:
                    trace[lp] += random.gauss(1.2, 0.2)
            traces.append(trace)

        leakage_points = [45, 120, 175]

        t_values = [random.gauss(0, 1.5) for _ in range(n_samples)]
        for lp in leakage_points:
            if lp < n_samples:
                t_values[lp] = random.choice([-1, 1]) * random.uniform(5.0, 8.0)

        leakage_entries = [
            {"time_idx": 45, "t_value": 6.82, "significance": "p < 0.001"},
            {"time_idx": 120, "t_value": -5.41, "significance": "p < 0.001"},
            {"time_idx": 175, "t_value": 7.15, "significance": "p < 0.001"},
        ]

        key_ranks = [
            {"key_hex": "0x2B", "correlation": 0.892, "rank": 1},
            {"key_hex": "0x7E", "correlation": 0.341, "rank": 2},
            {"key_hex": "0xA1", "correlation": 0.298, "rank": 3},
            {"key_hex": "0xF4", "correlation": 0.215, "rank": 4},
            {"key_hex": "0x09", "correlation": 0.187, "rank": 5},
        ]

        self._sca_tab.populate(
            traces=traces,
            leakage_points=leakage_points,
            t_values=t_values,
            leakage_entries=leakage_entries,
            key_ranks=key_ranks,
            verdict="Vulnerable -- 3 leakage points exceed threshold",
        )

    def _populate_fips_demo(self) -> None:
        results: dict[str, str] = {}
        evidence: dict[str, str] = {}
        demo_statuses = ["PASS", "PASS", "PASS", "FAIL", "WARNING", "N/A"]
        idx = 0
        for _group_name, checks in _FIPS_GROUPS:
            for check_id, _desc in checks:
                status = demo_statuses[idx % len(demo_statuses)]
                results[check_id] = status
                if status == "PASS":
                    evidence[check_id] = "Verified in RTL simulation"
                elif status == "FAIL":
                    evidence[check_id] = "Not implemented -- requires design change"
                elif status == "WARNING":
                    evidence[check_id] = "Partial implementation detected"
                idx += 1
        self._fips_tab.populate(results, evidence)

    def _populate_entropy_demo(self) -> None:
        issues = [
            {"source": "PLL Jitter", "issue": "Entropy rate below 0.5 bits/sample",
             "severity": "HIGH", "recommendation": "Increase PLL free-running frequency"},
            {"source": "Key Gen", "issue": "Insufficient conditioning before use",
             "severity": "MEDIUM", "recommendation": "Add SHA-256 conditioning stage"},
        ]
        nist_results = [
            {"test": "Excursion", "statistic": 0.0312, "threshold": 0.0500, "result": "PASS"},
            {"test": "numDirectionalRuns", "statistic": 0.0289, "threshold": 0.0500, "result": "PASS"},
            {"test": "lenDirectionalRuns", "statistic": 0.0478, "threshold": 0.0500, "result": "PASS"},
            {"test": "numIncreasesDecreases", "statistic": 0.0612, "threshold": 0.0500, "result": "FAIL"},
            {"test": "numRunsMedian", "statistic": 0.0198, "threshold": 0.0500, "result": "PASS"},
            {"test": "lenRunsMedian", "statistic": 0.0345, "threshold": 0.0500, "result": "PASS"},
            {"test": "avgCollision", "statistic": 0.0267, "threshold": 0.0500, "result": "PASS"},
            {"test": "maxCollision", "statistic": 0.0401, "threshold": 0.0500, "result": "PASS"},
            {"test": "periodicity(1)", "statistic": 0.0156, "threshold": 0.0500, "result": "PASS"},
            {"test": "periodicity(2)", "statistic": 0.0223, "threshold": 0.0500, "result": "PASS"},
            {"test": "covariance(1)", "statistic": 0.0189, "threshold": 0.0500, "result": "PASS"},
            {"test": "compression", "statistic": 0.0534, "threshold": 0.0500, "result": "FAIL"},
        ]
        self._entropy_tab.populate(issues, nist_results)

    def _populate_fault_demo(self) -> None:
        faults = [
            {"model": "Glitch", "target": "aes_core.round_ctr", "detected": "Yes", "output_affected": "No", "key_leaked": "No", "classification": "detected"},
            {"model": "Glitch", "target": "aes_core.key_reg[7]", "detected": "No", "output_affected": "Yes", "key_leaked": "Yes", "classification": "critical"},
            {"model": "Bit Flip", "target": "aes_core.sbox_out[3]", "detected": "Yes", "output_affected": "Yes", "key_leaked": "No", "classification": "detected"},
            {"model": "Bit Flip", "target": "aes_core.state[127]", "detected": "No", "output_affected": "No", "key_leaked": "No", "classification": "safe_error"},
            {"model": "Laser", "target": "aes_core.mix_col", "detected": "No", "output_affected": "Yes", "key_leaked": "No", "classification": "undetected"},
            {"model": "Laser", "target": "aes_core.key_sched", "detected": "No", "output_affected": "Yes", "key_leaked": "Yes", "classification": "critical"},
            {"model": "Glitch", "target": "aes_core.done_flag", "detected": "No", "output_affected": "No", "key_leaked": "No", "classification": "safe_error"},
            {"model": "Bit Flip", "target": "aes_core.round_key[0]", "detected": "Yes", "output_affected": "No", "key_leaked": "No", "classification": "detected"},
        ]
        classification = {"safe_error": 25, "detected": 38, "undetected": 12, "critical": 25}
        self._fault_tab.populate(
            faults=faults,
            classification=classification,
            resilience_score=58.0,
            recommendation=(
                "Critical: 2 fault paths leak key material. Recommended actions:\n"
                "1. Add TMR on key_reg and key_sched modules\n"
                "2. Implement error detection codes on round counter\n"
                "3. Add clock/voltage glitch detectors"
            ),
            active_countermeasures=[0, 2],
        )
