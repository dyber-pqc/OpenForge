"""Welcome panel shown when no project is open.

VS Code-style welcome page with quick actions, recent projects, learning
resources, and featured examples. Catppuccin Mocha (dark) / Latte (light).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt,
    Signal,
    QSize,
    QPoint,
    QSettings,
    QEvent,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import (
    QFont,
    QPixmap,
    QPainter,
    QColor,
    QPalette,
    QCursor,
    QLinearGradient,
    QBrush,
    QPen,
    QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QListWidget,
    QListWidgetItem,
    QGraphicsDropShadowEffect,
)


# ---------------------------------------------------------------------------
# Catppuccin palettes
# ---------------------------------------------------------------------------

CATPPUCCIN_MOCHA = {
    "base": "#1e1e2e",
    "mantle": "#181825",
    "crust": "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "text": "#cdd6f4",
    "subtext1": "#bac2de",
    "subtext0": "#a6adc8",
    "overlay2": "#9399b2",
    "overlay1": "#7f849c",
    "overlay0": "#6c7086",
    "blue": "#89b4fa",
    "lavender": "#b4befe",
    "sapphire": "#74c7ec",
    "sky": "#89dceb",
    "teal": "#94e2d5",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "peach": "#fab387",
    "maroon": "#eba0ac",
    "red": "#f38ba8",
    "mauve": "#cba6f7",
    "pink": "#f5c2e7",
    "flamingo": "#f2cdcd",
    "rosewater": "#f5e0dc",
}

CATPPUCCIN_LATTE = {
    "base": "#eff1f5",
    "mantle": "#e6e9ef",
    "crust": "#dce0e8",
    "surface0": "#ccd0da",
    "surface1": "#bcc0cc",
    "surface2": "#acb0be",
    "text": "#4c4f69",
    "subtext1": "#5c5f77",
    "subtext0": "#6c6f85",
    "overlay2": "#7c7f93",
    "overlay1": "#8c8fa1",
    "overlay0": "#9ca0b0",
    "blue": "#1e66f5",
    "lavender": "#7287fd",
    "sapphire": "#209fb5",
    "sky": "#04a5e5",
    "teal": "#179299",
    "green": "#40a02b",
    "yellow": "#df8e1d",
    "peach": "#fe640b",
    "maroon": "#e64553",
    "red": "#d20f39",
    "mauve": "#8839ef",
    "pink": "#ea76cb",
    "flamingo": "#dd7878",
    "rosewater": "#dc8a78",
}


# ---------------------------------------------------------------------------
# Featured example metadata
# ---------------------------------------------------------------------------


@dataclass
class FeaturedExample:
    name: str
    title: str
    description: str
    icon: str
    accent: str  # palette key
    category: str


FEATURED_EXAMPLES: list[FeaturedExample] = [
    FeaturedExample(
        name="simple-counter",
        title="Simple Counter",
        description="8-bit ASIC counter — full RTL-to-GDSII flow",
        icon="🔢",
        accent="blue",
        category="ASIC",
    ),
    FeaturedExample(
        name="aes-sbox",
        title="AES S-Box",
        description="Constant-time AES substitution box",
        icon="🔐",
        accent="mauve",
        category="Crypto",
    ),
    FeaturedExample(
        name="sha3-keccak",
        title="SHA-3 / Keccak",
        description="Single Keccak-f round permutation",
        icon="🧮",
        accent="teal",
        category="Crypto",
    ),
    FeaturedExample(
        name="uart-tx",
        title="UART Transmitter",
        description="Configurable baud-rate UART TX",
        icon="📡",
        accent="green",
        category="Peripherals",
    ),
    FeaturedExample(
        name="ml-kem-accelerator",
        title="ML-KEM Accelerator",
        description="Post-quantum NTT/INTT engine",
        icon="🛡️",
        accent="peach",
        category="PQC",
    ),
    FeaturedExample(
        name="spi-master",
        title="SPI Master",
        description="Mode 0/1/2/3 SPI controller",
        icon="🔗",
        accent="sapphire",
        category="Peripherals",
    ),
]


# ---------------------------------------------------------------------------
# Tip of the day
# ---------------------------------------------------------------------------

TIPS = [
    "Press Ctrl+Shift+P to open the command palette and run any action by name.",
    "Use the Block Designer to drag-drop IP blocks and auto-wire them together.",
    "TVLA leakage testing for your crypto IP runs from the Verification menu.",
    "The waveform viewer supports cursors — drag to measure delta time.",
    "You can drop a .v file directly onto the source explorer to add it.",
    "Hold Shift while resizing a dock to snap to the edge of another dock.",
    "Synthesis caches results — re-running on unchanged RTL is instant.",
    "The DRC viewer cross-probes back to GDS coordinates on click.",
    "Use the Tcl console to script any flow step interactively.",
    "Press F12 to jump to the definition of a signal or module.",
]


# ---------------------------------------------------------------------------
# Recent projects helpers
# ---------------------------------------------------------------------------


def _load_recent_projects() -> list[dict]:
    """Load recent projects from QSettings."""
    settings = QSettings("OpenForge", "Desktop")
    raw = settings.value("recent_projects", "[]")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception:
            return []
    return []


def _save_recent_projects(projects: list[dict]) -> None:
    """Save recent projects to QSettings as JSON."""
    settings = QSettings("OpenForge", "Desktop")
    settings.setValue("recent_projects", json.dumps(projects))


def _format_relative_date(iso: str) -> str:
    """Convert ISO date to a friendly relative string."""
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return iso
    now = datetime.now()
    delta = now - dt
    if delta.days == 0:
        if delta.seconds < 3600:
            mins = max(1, delta.seconds // 60)
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        hours = delta.seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if delta.days == 1:
        return "Yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    if delta.days < 30:
        weeks = delta.days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    if delta.days < 365:
        months = delta.days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = delta.days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


# ---------------------------------------------------------------------------
# Custom button-like widgets
# ---------------------------------------------------------------------------


class _ActionLink(QPushButton):
    """Quick-action link with icon and text, used in the Start column."""

    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._text = text
        self._accent = "#89b4fa"
        self._fg = "#cdd6f4"
        self._hover = "#313244"
        self.setText(f"  {icon}   {text}")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refresh_style()

    def set_palette(self, accent: str, fg: str, hover: str) -> None:
        self._accent = accent
        self._fg = fg
        self._hover = hover
        self._refresh_style()

    def _refresh_style(self) -> None:
        self.setStyleSheet(
            f"""
            QPushButton {{
                color: {self._accent};
                background: transparent;
                border: none;
                text-align: left;
                padding: 6px 10px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {self._hover};
                border-radius: 6px;
                color: {self._accent};
            }}
            QPushButton:pressed {{
                background: {self._hover};
            }}
            """
        )


class _LearnLink(QPushButton):
    """Learn-section link, slightly smaller than ActionLink."""

    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(parent)
        self.setText(f"  {icon}   {text}")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setMinimumHeight(30)
        self._fg = "#cdd6f4"
        self._hover = "#313244"
        self._refresh_style()

    def set_palette(self, fg: str, hover: str) -> None:
        self._fg = fg
        self._hover = hover
        self._refresh_style()

    def _refresh_style(self) -> None:
        self.setStyleSheet(
            f"""
            QPushButton {{
                color: {self._fg};
                background: transparent;
                border: none;
                text-align: left;
                padding: 5px 10px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {self._hover};
                border-radius: 6px;
            }}
            """
        )


class _RecentProjectItem(QFrame):
    """A row in the recent projects list."""

    clicked = Signal(str)  # path

    def __init__(self, path: str, name: str, last_opened: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._name = name
        self._last_opened = last_opened
        self._fg = "#cdd6f4"
        self._dim = "#9399b2"
        self._accent = "#89b4fa"
        self._hover = "#313244"
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(48)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        self._title = QLabel(self._name)
        self._title.setStyleSheet(
            f"color: {self._accent}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        self._sub = QLabel(f"{self._path}  •  {_format_relative_date(self._last_opened)}")
        self._sub.setStyleSheet(
            f"color: {self._dim}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._title)
        layout.addWidget(self._sub)
        self._refresh_style()

    def _refresh_style(self) -> None:
        self.setStyleSheet(
            f"""
            _RecentProjectItem {{ background: transparent; border-radius: 6px; }}
            _RecentProjectItem:hover {{ background: {self._hover}; }}
            """
        )

    def set_palette(self, accent: str, fg: str, dim: str, hover: str) -> None:
        self._accent = accent
        self._fg = fg
        self._dim = dim
        self._hover = hover
        self._title.setStyleSheet(
            f"color: {self._accent}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        self._sub.setStyleSheet(
            f"color: {self._dim}; font-size: 11px; background: transparent;"
        )
        self._refresh_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet(
            f"_RecentProjectItem {{ background: {self._hover}; border-radius: 6px; }}"
        )
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(
            f"_RecentProjectItem {{ background: transparent; border-radius: 6px; }}"
        )
        super().leaveEvent(event)


class _ExampleCard(QFrame):
    """Card for a featured example with icon, title, description."""

    clicked = Signal(str)  # example name

    def __init__(self, example: FeaturedExample, parent=None):
        super().__init__(parent)
        self._example = example
        self._bg = "#181825"
        self._fg = "#cdd6f4"
        self._dim = "#9399b2"
        self._accent = "#89b4fa"
        self._border = "#313244"
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumSize(180, 150)
        self.setMaximumHeight(180)
        self._build()
        # Drop shadow for depth
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        self._icon = QLabel(self._example.icon)
        self._icon.setStyleSheet("font-size: 32px; background: transparent;")
        self._title = QLabel(self._example.title)
        self._title.setStyleSheet(
            f"color: {self._fg}; font-size: 14px; font-weight: 700; background: transparent;"
        )
        self._desc = QLabel(self._example.description)
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet(
            f"color: {self._dim}; font-size: 11px; background: transparent;"
        )
        self._cat = QLabel(self._example.category)
        self._cat.setStyleSheet(
            f"color: {self._accent}; font-size: 10px; font-weight: 600; "
            f"background: transparent; text-transform: uppercase;"
        )
        layout.addWidget(self._icon)
        layout.addWidget(self._title)
        layout.addWidget(self._desc)
        layout.addStretch(1)
        layout.addWidget(self._cat)
        self._refresh_style()

    def _refresh_style(self) -> None:
        self.setStyleSheet(
            f"""
            _ExampleCard {{
                background: {self._bg};
                border: 1px solid {self._border};
                border-radius: 10px;
            }}
            _ExampleCard:hover {{
                border: 1px solid {self._accent};
            }}
            """
        )

    def set_palette(self, bg, fg, dim, accent, border) -> None:
        self._bg = bg
        self._fg = fg
        self._dim = dim
        self._accent = accent
        self._border = border
        self._title.setStyleSheet(
            f"color: {self._fg}; font-size: 14px; font-weight: 700; background: transparent;"
        )
        self._desc.setStyleSheet(
            f"color: {self._dim}; font-size: 11px; background: transparent;"
        )
        self._cat.setStyleSheet(
            f"color: {self._accent}; font-size: 10px; font-weight: 600; background: transparent;"
        )
        self._refresh_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._example.name)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Welcome panel
# ---------------------------------------------------------------------------


class WelcomePanel(QWidget):
    """Welcome page shown in the central area when no project is open."""

    project_open_requested = Signal(str)  # path
    new_project_requested = Signal()
    example_open_requested = Signal(str)  # example name
    tutorial_requested = Signal(str)  # tutorial id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomePanel")
        self._dark = True
        self._palette = CATPPUCCIN_MOCHA
        self._recent_items: list[_RecentProjectItem] = []
        self._action_links: list[_ActionLink] = []
        self._learn_links: list[_LearnLink] = []
        self._cards: list[_ExampleCard] = []
        self._tip_index = 0
        self._build_ui()
        self.refresh_recent()
        self._apply_theme()

    # ----- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area lets the content overflow gracefully on small screens
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll)

        container = QWidget()
        container.setObjectName("WelcomeContainer")
        scroll.setWidget(container)
        self._scroll = scroll
        self._container = container

        body = QVBoxLayout(container)
        body.setContentsMargins(60, 50, 60, 30)
        body.setSpacing(28)

        body.addLayout(self._build_header())
        body.addLayout(self._build_three_columns(), stretch=1)
        body.addWidget(self._build_examples_section())
        body.addWidget(self._build_bottom_strip())

    def _build_header(self) -> QVBoxLayout:
        header = QVBoxLayout()
        header.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(14)

        self._logo = QLabel("⚡")
        self._logo.setStyleSheet(
            "font-size: 56px; background: transparent;"
        )
        title_row.addWidget(self._logo)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        self._title_label = QLabel("OpenForge EDA")
        self._title_label.setStyleSheet(
            "font-size: 38px; font-weight: 800; background: transparent;"
        )
        self._tagline_label = QLabel(
            "Open-source silicon design, from RTL to GDSII"
        )
        self._tagline_label.setStyleSheet(
            "font-size: 15px; background: transparent;"
        )
        title_block.addWidget(self._title_label)
        title_block.addWidget(self._tagline_label)
        title_row.addLayout(title_block)

        title_row.addStretch(1)

        self._version_label = QLabel("v0.10.0  •  Phase 10")
        self._version_label.setStyleSheet(
            "font-size: 12px; background: transparent;"
        )
        self._version_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        title_row.addWidget(self._version_label)

        header.addLayout(title_row)

        # Subtle separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setObjectName("WelcomeSeparator")
        self._separator = sep
        header.addWidget(sep)
        return header

    def _build_three_columns(self) -> QHBoxLayout:
        columns = QHBoxLayout()
        columns.setSpacing(40)

        columns.addLayout(self._build_start_column(), stretch=1)
        columns.addLayout(self._build_recent_column(), stretch=2)
        columns.addLayout(self._build_learn_column(), stretch=1)

        return columns

    def _build_start_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)

        heading = self._make_heading("Start")
        col.addWidget(heading)

        actions = [
            ("📂", "Open Project...", lambda: self.project_open_requested.emit("")),
            ("✨", "New Project...", self.new_project_requested.emit),
            ("🎓", "Run a Tutorial", lambda: self.tutorial_requested.emit("first-project")),
            ("📚", "Browse Examples", lambda: self.example_open_requested.emit("")),
            ("🔗", "Clone from Git...", lambda: self.project_open_requested.emit("git")),
            ("⚙️", "Settings", lambda: self.tutorial_requested.emit("settings")),
        ]
        for icon, text, handler in actions:
            link = _ActionLink(icon, text)
            link.clicked.connect(handler)
            col.addWidget(link)
            self._action_links.append(link)

        col.addStretch(1)
        return col

    def _build_recent_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)

        heading = self._make_heading("Recent Projects")
        col.addWidget(heading)

        self._recent_container = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(2)
        col.addWidget(self._recent_container)

        self._no_recent_label = QLabel(
            "No recent projects yet — open one from the Start column to get going."
        )
        self._no_recent_label.setWordWrap(True)
        self._no_recent_label.setStyleSheet(
            "font-style: italic; padding: 10px; background: transparent;"
        )
        col.addWidget(self._no_recent_label)
        col.addStretch(1)
        return col

    def _build_learn_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)

        heading = self._make_heading("Learn")
        col.addWidget(heading)

        learn_items = [
            ("🚀", "Getting Started Guide", "getting-started"),
            ("📖", "RTL-to-GDSII Tutorial", "rtl-to-gds"),
            ("🧪", "Verification Workflow", "verification"),
            ("🔐", "Crypto Hardware Design", "crypto"),
            ("⚡", "FPGA Programming", "fpga"),
            ("📋", "Keyboard Shortcuts", "shortcuts"),
            ("🧠", "Block Designer", "block-designer"),
            ("🛠️", "Tcl Scripting", "tcl"),
        ]
        for icon, text, ident in learn_items:
            link = _LearnLink(icon, text)
            link.clicked.connect(lambda _=False, i=ident: self.tutorial_requested.emit(i))
            col.addWidget(link)
            self._learn_links.append(link)

        col.addStretch(1)
        return col

    def _build_examples_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        heading = self._make_heading("Featured Examples")
        layout.addWidget(heading)

        grid = QGridLayout()
        grid.setSpacing(14)
        for index, example in enumerate(FEATURED_EXAMPLES):
            card = _ExampleCard(example)
            card.clicked.connect(self.example_open_requested.emit)
            row = index // 3
            col = index % 3
            grid.addWidget(card, row, col)
            self._cards.append(card)
        layout.addLayout(grid)
        return wrapper

    def _build_bottom_strip(self) -> QWidget:
        strip = QFrame()
        strip.setObjectName("WelcomeBottomStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(20)

        self._tip_icon = QLabel("💡")
        self._tip_icon.setStyleSheet("font-size: 18px; background: transparent;")
        layout.addWidget(self._tip_icon)

        self._tip_label = QLabel(TIPS[0])
        self._tip_label.setWordWrap(True)
        self._tip_label.setStyleSheet("font-size: 12px; background: transparent;")
        layout.addWidget(self._tip_label, stretch=1)

        next_tip = QPushButton("Next Tip ▶")
        next_tip.setFlat(True)
        next_tip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        next_tip.clicked.connect(self._cycle_tip)
        next_tip.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 4px 10px; font-size: 12px; }"
        )
        self._next_tip_btn = next_tip
        layout.addWidget(next_tip)

        sep = QLabel("  •  ")
        sep.setStyleSheet("background: transparent;")
        layout.addWidget(sep)

        for label, _href in [
            ("📰 News", "https://openforge.dev/news"),
            ("💬 Discord", "https://discord.gg/openforge"),
            ("🐙 GitHub", "https://github.com/dyber/openforge"),
            ("🐦 Twitter", "https://twitter.com/openforge_eda"),
        ]:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 4px 6px; font-size: 12px; }"
            )
            layout.addWidget(btn)

        self._bottom_strip = strip
        return strip

    def _make_heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: 700; "
            "letter-spacing: 1.5px; padding: 4px 0 6px 0; background: transparent;"
        )
        lbl.setProperty("welcomeHeading", True)
        return lbl

    # ----- public API -------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        """Switch between dark (Mocha) and light (Latte) palettes."""
        self._dark = dark
        self._palette = CATPPUCCIN_MOCHA if dark else CATPPUCCIN_LATTE
        self._apply_theme()

    def add_recent_project(self, path: Path, name: str) -> None:
        """Push a project onto the recent list and persist it."""
        projects = _load_recent_projects()
        path_str = str(path)
        projects = [p for p in projects if p.get("path") != path_str]
        projects.insert(
            0,
            {
                "path": path_str,
                "name": name,
                "last_opened_iso": datetime.now().isoformat(timespec="seconds"),
            },
        )
        projects = projects[:12]
        _save_recent_projects(projects)
        self.refresh_recent()

    def refresh_recent(self) -> None:
        """Re-populate the recent projects list from QSettings."""
        # Clear existing rows
        for item in self._recent_items:
            item.setParent(None)
            item.deleteLater()
        self._recent_items.clear()

        projects = _load_recent_projects()
        if not projects:
            self._no_recent_label.setVisible(True)
            return
        self._no_recent_label.setVisible(False)
        for entry in projects[:8]:
            item = _RecentProjectItem(
                entry.get("path", ""),
                entry.get("name", entry.get("path", "Untitled")),
                entry.get("last_opened_iso", ""),
            )
            item.clicked.connect(self.project_open_requested.emit)
            self._recent_layout.addWidget(item)
            self._recent_items.append(item)
        self._apply_theme()  # repaint with current palette

    # ----- theming ----------------------------------------------------------

    def _apply_theme(self) -> None:
        p = self._palette
        self.setStyleSheet(
            f"""
            #WelcomePanel, #WelcomeContainer {{
                background: {p['base']};
                color: {p['text']};
            }}
            QScrollArea {{ background: {p['base']}; border: none; }}
            QLabel {{ color: {p['text']}; }}
            #WelcomeBottomStrip {{
                background: {p['mantle']};
                border: 1px solid {p['surface0']};
                border-radius: 8px;
            }}
            QFrame#WelcomeSeparator {{
                background: {p['surface0']};
                border: none;
            }}
            QLabel[welcomeHeading="true"] {{
                color: {p['overlay1']};
            }}
            """
        )
        self._title_label.setStyleSheet(
            f"font-size: 38px; font-weight: 800; color: {p['text']}; background: transparent;"
        )
        self._tagline_label.setStyleSheet(
            f"font-size: 15px; color: {p['subtext0']}; background: transparent;"
        )
        self._version_label.setStyleSheet(
            f"font-size: 12px; color: {p['overlay1']}; background: transparent;"
        )
        for link in self._action_links:
            link.set_palette(p["blue"], p["text"], p["surface0"])
        for link in self._learn_links:
            link.set_palette(p["text"], p["surface0"])
        for item in self._recent_items:
            item.set_palette(p["blue"], p["text"], p["overlay1"], p["surface0"])
        for card in self._cards:
            accent = p.get(card._example.accent, p["blue"])
            card.set_palette(p["mantle"], p["text"], p["subtext0"], accent, p["surface0"])
        self._tip_label.setStyleSheet(
            f"font-size: 12px; color: {p['subtext1']}; background: transparent;"
        )
        self._no_recent_label.setStyleSheet(
            f"font-style: italic; padding: 10px; color: {p['overlay1']}; background: transparent;"
        )
        self._next_tip_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; padding: 4px 10px; "
            f"font-size: 12px; color: {p['blue']}; }}"
            f"QPushButton:hover {{ color: {p['lavender']}; }}"
        )

    # ----- tip cycling ------------------------------------------------------

    def _cycle_tip(self) -> None:
        self._tip_index = (self._tip_index + 1) % len(TIPS)
        self._tip_label.setText(TIPS[self._tip_index])


# ---------------------------------------------------------------------------
# Phase 7 helpers - integration points for the core tutorials/templates
# ---------------------------------------------------------------------------
def featured_tutorials_for_welcome() -> list[dict]:
    """Return the three featured tutorials from the core library.

    Renders as simple dicts so the welcome panel can lay them out without
    needing to import Pydantic models in widget code.
    """
    try:
        from openforge.tutorials.library import featured
        return [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "persona": t.persona,
                "duration_minutes": t.duration_minutes,
                "difficulty": t.difficulty,
            }
            for t in featured()
        ]
    except Exception:  # noqa: BLE001
        return []


def load_recent_projects() -> list[dict]:
    """Read the recent projects list stored by the project service."""
    import os as _os
    import sys as _sys
    if _sys.platform.startswith("win") and _os.environ.get("APPDATA"):
        f = Path(_os.environ["APPDATA"]) / "OpenForge" / "recent.json"
    else:
        f = Path.home() / ".openforge" / "recent.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []
