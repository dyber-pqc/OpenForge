"""Extension Marketplace dialog for OpenForge EDA.

Provides a two-tab interface for managing installed extensions and browsing
a marketplace of available extensions. Extension state persists to QSettings
so install/enable changes survive app restarts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final

from PySide6.QtCore import QSettings, Qt, Signal, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ── Theme constants (Catppuccin Mocha) ────────────────────────────────────

_BG: Final[str] = "#1e1e2e"
_SURFACE0: Final[str] = "#313244"
_SURFACE1: Final[str] = "#45475a"
_SURFACE2: Final[str] = "#585b70"
_TEXT: Final[str] = "#cdd6f4"
_SUBTEXT: Final[str] = "#a6adc8"
_BLUE: Final[str] = "#89b4fa"
_GREEN: Final[str] = "#a6e3a1"
_RED: Final[str] = "#f38ba8"
_YELLOW: Final[str] = "#f9e2af"
_MAUVE: Final[str] = "#cba6f7"
_PEACH: Final[str] = "#fab387"
_TEAL: Final[str] = "#94e2d5"
_CRUST: Final[str] = "#11111b"


@dataclass
class ExtensionInfo:
    """Metadata for an extension."""

    name: str
    version: str
    author: str
    description: str
    rating: float = 0.0
    downloads: str = "0"
    installed: bool = False
    enabled: bool = True
    category: str = "General"
    color: str = _BLUE


# Default catalog
_DEFAULT_EXTENSIONS: list[ExtensionInfo] = [
    ExtensionInfo(
        name="Verilog Formatter",
        version="1.2.0",
        author="OpenForge Team",
        description="Auto-format Verilog and SystemVerilog code with configurable style rules. "
                    "Supports IEEE-1364 and IEEE-1800 standards.",
        rating=4.7, downloads="12.4k",
        installed=True, enabled=True,
        category="Code Quality", color=_BLUE,
    ),
    ExtensionInfo(
        name="VHDL Support",
        version="2.0.1",
        author="HDL Community",
        description="Full VHDL syntax highlighting, code snippets, and entity/architecture "
                    "navigation for VHDL-93, VHDL-2008, and VHDL-2019.",
        rating=4.5, downloads="8.7k",
        installed=True, enabled=False,
        category="Language Support", color=_GREEN,
    ),
    ExtensionInfo(
        name="Chisel/SpinalHDL",
        version="0.9.3",
        author="Scala HDL Group",
        description="Scala-based HDL support with Chisel3 and SpinalHDL integration. "
                    "Includes FIRRTL viewer and elaboration preview.",
        rating=4.2, downloads="3.1k",
        category="Language Support", color=_MAUVE,
    ),
    ExtensionInfo(
        name="Git Integration",
        version="1.5.0",
        author="OpenForge Team",
        description="Version control sidebar with diff viewer, commit history, "
                    "branch management, and blame annotations for HDL files.",
        rating=4.8, downloads="15.2k",
        installed=True, enabled=True,
        category="Productivity", color=_PEACH,
    ),
    ExtensionInfo(
        name="Waveform Comparison",
        version="1.1.0",
        author="VerifTools",
        description="Compare two VCD/FST waveform files side-by-side with automatic "
                    "signal alignment and mismatch highlighting.",
        rating=4.3, downloads="5.6k",
        category="Verification", color=_TEAL,
    ),
    ExtensionInfo(
        name="Power Profiler",
        version="0.8.2",
        author="EDA Analytics",
        description="Interactive power analysis visualization with heatmaps, "
                    "per-module breakdown, and switching activity correlation.",
        rating=4.0, downloads="2.3k",
        category="Analysis", color=_YELLOW,
    ),
    ExtensionInfo(
        name="Security Scanner",
        version="1.3.1",
        author="CryptoForge Labs",
        description="Automated cryptographic security checks including constant-time "
                    "verification, fault injection resistance, and side-channel leakage detection.",
        rating=4.6, downloads="7.8k",
        category="Security", color=_RED,
    ),
    ExtensionInfo(
        name="PDK Browser",
        version="1.0.0",
        author="OpenPDK Collective",
        description="Browse standard cells visually with parametric views, "
                    "timing arcs, and layout cross-reference for SKY130 and GF180MCU.",
        rating=4.4, downloads="4.5k",
        category="Physical Design", color=_BLUE,
    ),
    ExtensionInfo(
        name="IP Catalog Pro",
        version="0.7.0",
        author="OpenForge Team",
        description="Enhanced IP integration with bus adapters, clock domain "
                    "crossing bridges, and parameterized FIFO/memory generators.",
        rating=3.9, downloads="1.8k",
        category="IP Integration", color=_MAUVE,
    ),
    ExtensionInfo(
        name="Cloud Synthesis",
        version="2.1.0",
        author="ForgeCloud Inc.",
        description="Remote synthesis on cloud servers with distributed compilation, "
                    "result caching, and multi-target parallel builds.",
        rating=4.1, downloads="6.2k",
        category="Cloud", color=_TEAL,
    ),
]


_CATEGORY_ICONS: dict[str, str] = {
    "Code Quality": "\u2714",
    "Language Support": "\u2630",
    "Productivity": "\u26a1",
    "Verification": "\u2611",
    "Analysis": "\u2623",
    "Security": "\u26e8",
    "Physical Design": "\u25a6",
    "IP Integration": "\u2699",
    "Cloud": "\u2601",
    "General": "\u25a0",
}


def _star_text(rating: float) -> str:
    full = int(rating)
    half = rating - full >= 0.5
    stars = "\u2605" * full + ("\u00bd" if half else "")
    return f"{stars} {rating:.1f}"


# ═══════════════════════════════════════════════════════════════════════════
# Extension Card
# ═══════════════════════════════════════════════════════════════════════════


class _ExtensionCard(QFrame):
    """Card widget for a single extension with real action buttons."""

    action_requested = Signal(str, str)  # (action, extension_name)

    def __init__(self, ext: ExtensionInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ext = ext
        self._busy = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            _ExtensionCard {{
                background-color: {_SURFACE0};
                border: 1px solid {_SURFACE1};
                border-radius: 8px;
            }}
            _ExtensionCard:hover {{
                border-color: {ext.color};
                background-color: #353548;
            }}
        """)
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Left: Category icon
        icon_label = QLabel(_CATEGORY_ICONS.get(ext.category, "\u25a0"))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(48, 48)
        icon_label.setStyleSheet(f"""
            background-color: {ext.color};
            color: {_CRUST};
            border-radius: 10px;
            font-size: 22px;
            font-weight: bold;
        """)
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # Center: info
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(3)

        # Name + version row
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_label = QLabel(ext.name)
        name_label.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: bold;")
        name_row.addWidget(name_label)

        version_label = QLabel(f"v{ext.version}")
        version_label.setStyleSheet(f"""
            color: {_SUBTEXT}; font-size: 9px;
            background-color: {_SURFACE1}; border-radius: 3px; padding: 1px 5px;
        """)
        name_row.addWidget(version_label)
        name_row.addStretch()

        rating_label = QLabel(_star_text(ext.rating))
        rating_label.setStyleSheet(f"color: {_YELLOW}; font-size: 11px;")
        name_row.addWidget(rating_label)

        dl_label = QLabel(f"\u2193 {ext.downloads}")
        dl_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 10px;")
        name_row.addWidget(dl_label)
        info_layout.addLayout(name_row)

        # Author
        author_label = QLabel(f"by {ext.author}")
        author_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 10px;")
        info_layout.addWidget(author_label)

        # Description
        desc_label = QLabel(ext.description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {_TEXT}; font-size: 11px; line-height: 1.3;")
        desc_label.setMaximumHeight(40)
        info_layout.addWidget(desc_label)

        # Action row
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        cat_label = QLabel(f"{_CATEGORY_ICONS.get(ext.category, '')} {ext.category}")
        cat_label.setStyleSheet(f"""
            background-color: {_SURFACE1}; color: {ext.color};
            border-radius: 4px; padding: 2px 8px; font-size: 10px;
        """)
        cat_label.setFixedHeight(20)
        bottom.addWidget(cat_label)
        bottom.addStretch()

        # Progress bar (hidden)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        self._progress.setFixedWidth(100)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar {{ background-color: {_SURFACE1}; border: none; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {ext.color}; border-radius: 3px; }}
        """)
        self._progress.setVisible(False)
        bottom.addWidget(self._progress)

        # Status label (for installed extensions)
        self._status_label = QLabel()
        bottom.addWidget(self._status_label)

        # Buttons container
        self._btn_container = QWidget()
        btn_layout = QHBoxLayout(self._btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)

        if ext.installed:
            self._update_installed_status()

            if ext.enabled:
                btn = self._make_button("Disable", _SURFACE1, _YELLOW, _SURFACE2)
                btn.clicked.connect(lambda: self._do_action("disable"))
                btn_layout.addWidget(btn)
            else:
                btn = self._make_button("Enable", _GREEN, _CRUST, "#b5eebd")
                btn.clicked.connect(lambda: self._do_action("enable"))
                btn_layout.addWidget(btn)

            btn = self._make_button("Uninstall", "transparent", _RED, _RED, hover_text=_CRUST)
            btn.clicked.connect(lambda: self._do_action("uninstall"))
            btn_layout.addWidget(btn)
        else:
            self._status_label.setVisible(False)
            btn = self._make_button("Install", _BLUE, _CRUST, "#a0c4fc", bold=True)
            btn.clicked.connect(lambda: self._do_action("install"))
            btn_layout.addWidget(btn)

        bottom.addWidget(self._btn_container)
        info_layout.addLayout(bottom)
        layout.addLayout(info_layout, 1)

    def _update_installed_status(self) -> None:
        ext = self._ext
        if ext.installed:
            status = "\u2713 Enabled" if ext.enabled else "\u25cb Disabled"
            color = _GREEN if ext.enabled else _SUBTEXT
            self._status_label.setText(status)
            self._status_label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)

    def _make_button(self, text: str, bg: str, fg: str, hover_bg: str,
                     hover_text: str = "", bold: bool = False) -> QPushButton:
        btn = QPushButton(text)
        weight = "bold" if bold else "normal"
        h_fg = hover_text if hover_text else fg
        border = f"1px solid {_SURFACE2}" if bg == "transparent" else "none"
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg}; color: {fg};
                border: {border}; border-radius: 4px;
                padding: 3px 12px; font-size: 10px; font-weight: {weight};
            }}
            QPushButton:hover {{ background-color: {hover_bg}; color: {h_fg}; }}
            QPushButton:disabled {{ background-color: {_SURFACE1}; color: {_SURFACE2}; }}
        """)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _do_action(self, action: str) -> None:
        """Start an action with visual progress feedback."""
        if self._busy:
            return
        self._busy = True

        # Disable buttons during action
        for btn in self._btn_container.findChildren(QPushButton):
            btn.setEnabled(False)

        self._progress.setVisible(True)

        # Simulate realistic install/uninstall time, then apply
        delay = 1200 if action in ("install", "uninstall") else 400
        QTimer.singleShot(delay, lambda: self._complete_action(action))

    def _complete_action(self, action: str) -> None:
        self._progress.setVisible(False)
        self._busy = False
        self.action_requested.emit(action, self._ext.name)


# ═══════════════════════════════════════════════════════════════════════════
# Main Dialog
# ═══════════════════════════════════════════════════════════════════════════


class ExtensionManagerDialog(QDialog):
    """Extension Marketplace with persistent state."""

    # Emitted when an extension's enabled state changes (for main app to react)
    extension_state_changed = Signal(str, bool)  # (name, enabled)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extension Manager")
        self.setMinimumSize(700, 550)
        self.resize(850, 650)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {_BG}; }}
            QScrollBar:vertical {{
                background: {_SURFACE0}; width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {_SURFACE1}; min-height: 30px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {_SURFACE2}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar:horizontal {{ height: 0px; }}
        """)

        self._settings = QSettings("Dyber", "OpenForge EDA")
        self._extensions = list(_DEFAULT_EXTENSIONS)
        self._load_state()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet(f"background-color: {_CRUST};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)

        title = QLabel("\u2699 Extension Manager")
        title.setStyleSheet(f"color: {_TEXT}; font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._count_label = QLabel()
        self._count_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        header_layout.addWidget(self._count_label)
        main_layout.addWidget(header)

        # Search bar
        search_row = QWidget()
        search_row.setStyleSheet(f"background-color: {_BG};")
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(16, 8, 16, 4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("\U0001f50d Search extensions...")
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_SURFACE0}; color: {_TEXT};
                border: 1px solid {_SURFACE1}; border-radius: 6px;
                padding: 6px 12px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {_BLUE}; }}
        """)
        self._search.textChanged.connect(self._on_search)
        search_layout.addWidget(self._search)
        main_layout.addWidget(search_row)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; background-color: {_BG}; }}
            QTabBar::tab {{
                background-color: {_SURFACE0}; color: {_SUBTEXT};
                border: none; padding: 8px 24px; font-size: 12px; margin-right: 1px;
            }}
            QTabBar::tab:selected {{
                background-color: {_BG}; color: {_TEXT};
                border-bottom: 2px solid {_BLUE};
            }}
            QTabBar::tab:hover:!selected {{ background-color: {_SURFACE1}; color: {_TEXT}; }}
        """)
        main_layout.addWidget(self._tabs)

        # Status bar
        self._status = QLabel()
        self._status.setStyleSheet(
            f"color: {_GREEN}; font-size: 11px; padding: 6px 16px; "
            f"background-color: {_CRUST};"
        )
        self._status.setVisible(False)
        main_layout.addWidget(self._status)

        self._rebuild_tabs()

    # ── State persistence ─────────────────────────────────────────

    def _load_state(self) -> None:
        """Load extension install/enable state from QSettings."""
        saved = self._settings.value("extensions/state")
        if saved and isinstance(saved, str):
            try:
                state_map: dict = json.loads(saved)
                for ext in self._extensions:
                    if ext.name in state_map:
                        s = state_map[ext.name]
                        ext.installed = s.get("installed", ext.installed)
                        ext.enabled = s.get("enabled", ext.enabled)
            except (json.JSONDecodeError, AttributeError):
                pass

    def _save_state(self) -> None:
        """Persist extension state to QSettings."""
        state_map = {}
        for ext in self._extensions:
            state_map[ext.name] = {
                "installed": ext.installed,
                "enabled": ext.enabled,
            }
        self._settings.setValue("extensions/state", json.dumps(state_map))

    # ── Tab building ──────────────────────────────────────────────

    def _rebuild_tabs(self, search_text: str = "") -> None:
        current = self._tabs.currentIndex()
        while self._tabs.count() > 0:
            self._tabs.removeTab(0)

        installed_count = sum(1 for e in self._extensions if e.installed)
        enabled_count = sum(1 for e in self._extensions if e.installed and e.enabled)
        self._count_label.setText(
            f"\u2713 {enabled_count} enabled  |  "
            f"{installed_count} installed  |  "
            f"{len(self._extensions)} total"
        )

        self._tabs.addTab(
            self._build_list(installed_only=True, search=search_text),
            f"Installed ({installed_count})",
        )
        self._tabs.addTab(
            self._build_list(installed_only=False, search=search_text),
            f"Marketplace ({len(self._extensions)})",
        )

        if 0 <= current < self._tabs.count():
            self._tabs.setCurrentIndex(current)

    def _build_list(self, *, installed_only: bool, search: str = "") -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"background-color: {_BG};")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {_BG}; border: none; }}")

        inner = QWidget()
        inner.setStyleSheet(f"background-color: {_BG};")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(16, 12, 16, 12)
        inner_layout.setSpacing(8)

        exts = self._extensions
        if installed_only:
            exts = [e for e in exts if e.installed]

        # Apply search filter
        if search:
            q = search.lower()
            exts = [
                e for e in exts
                if q in e.name.lower() or q in e.description.lower()
                or q in e.category.lower() or q in e.author.lower()
            ]

        if not exts:
            empty = QLabel(
                "No extensions found." if search
                else ("No extensions installed yet.\nBrowse the Marketplace tab to install."
                      if installed_only else "No extensions available.")
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {_SUBTEXT}; font-size: 13px; padding: 40px;")
            inner_layout.addWidget(empty)
        else:
            for ext in exts:
                card = _ExtensionCard(ext, inner)
                card.action_requested.connect(self._on_action)
                inner_layout.addWidget(card)

        inner_layout.addStretch()
        scroll.setWidget(inner)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return container

    # ── Action handling ───────────────────────────────────────────

    @Slot(str, str)
    def _on_action(self, action: str, name: str) -> None:
        """Handle extension actions with state persistence."""
        ext = next((e for e in self._extensions if e.name == name), None)
        if ext is None:
            return

        if action == "install":
            ext.installed = True
            ext.enabled = True
            self._show_status(f"\u2713 {name} installed and enabled", _GREEN)
        elif action == "uninstall":
            ext.installed = False
            ext.enabled = False
            self._show_status(f"\u2717 {name} uninstalled", _RED)
        elif action == "enable":
            ext.enabled = True
            self._show_status(f"\u2713 {name} enabled", _GREEN)
        elif action == "disable":
            ext.enabled = False
            self._show_status(f"\u25cb {name} disabled", _YELLOW)

        self._save_state()
        self.extension_state_changed.emit(name, ext.enabled and ext.installed)
        self._rebuild_tabs(self._search.text())

    def _show_status(self, msg: str, color: str) -> None:
        """Show a status message that auto-hides after 3 seconds."""
        self._status.setText(msg)
        self._status.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold; "
            f"padding: 6px 16px; background-color: {_CRUST};"
        )
        self._status.setVisible(True)
        QTimer.singleShot(3000, lambda: self._status.setVisible(False))

    @Slot(str)
    def _on_search(self, text: str) -> None:
        """Filter extensions by search text."""
        self._rebuild_tabs(text)
