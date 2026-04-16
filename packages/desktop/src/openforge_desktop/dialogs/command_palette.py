"""VS Code-style command palette for OpenForge.

Press Ctrl+Shift+P (or Ctrl+P) to open. Fuzzy-matches across registered
commands by title, category, and keywords. Recent commands surface to the
top when no query is entered.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRect,
    QSettings,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Command dataclass + registration
# ---------------------------------------------------------------------------


@dataclass
class Command:
    id: str
    title: str
    category: str
    shortcut: str = ""
    icon: str = ""
    handler: Callable[[], None] | None = None
    keywords: list[str] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        return f"{self.category}: {self.title}" if self.category else self.title


# ---------------------------------------------------------------------------
# Built-in command catalogue (~100 entries)
# ---------------------------------------------------------------------------


def _build_builtin_commands() -> list[Command]:
    cmds: list[Command] = []

    def add(id_, title, category, shortcut="", icon="", keywords=None):
        cmds.append(
            Command(
                id=id_,
                title=title,
                category=category,
                shortcut=shortcut,
                icon=icon,
                keywords=keywords or [],
            )
        )

    # File ------------------------------------------------------------------
    add("file.newProject", "New Project...", "File", "Ctrl+Shift+N", "✨", ["create"])
    add("file.openProject", "Open Project...", "File", "Ctrl+O", "📂", ["load"])
    add("file.openFolder", "Open Folder...", "File", "", "📁")
    add("file.openRecent", "Open Recent", "File", "", "🕘")
    add("file.closeProject", "Close Project", "File", "Ctrl+W", "❎")
    add("file.save", "Save", "File", "Ctrl+S", "💾", ["write"])
    add("file.saveAs", "Save As...", "File", "Ctrl+Shift+S", "💾")
    add("file.saveAll", "Save All", "File", "Ctrl+K S", "💾")
    add("file.revert", "Revert File", "File", "", "↩️")
    add("file.import", "Import RTL...", "File", "", "⬇️", ["verilog", "vhdl"])
    add("file.export", "Export...", "File", "", "⬆️")
    add("file.exit", "Exit", "File", "Ctrl+Q", "🚪", ["quit"])

    # Edit ------------------------------------------------------------------
    add("edit.undo", "Undo", "Edit", "Ctrl+Z", "↶")
    add("edit.redo", "Redo", "Edit", "Ctrl+Y", "↷")
    add("edit.cut", "Cut", "Edit", "Ctrl+X", "✂️")
    add("edit.copy", "Copy", "Edit", "Ctrl+C", "📋")
    add("edit.paste", "Paste", "Edit", "Ctrl+V", "📌")
    add("edit.find", "Find", "Edit", "Ctrl+F", "🔎")
    add("edit.replace", "Replace", "Edit", "Ctrl+H", "🔁")
    add("edit.findInFiles", "Find in Files", "Edit", "Ctrl+Shift+F", "🔍")
    add("edit.gotoLine", "Go to Line...", "Edit", "Ctrl+G", "↪️")
    add("edit.gotoSymbol", "Go to Symbol...", "Edit", "Ctrl+Shift+O", "🔣")
    add("edit.gotoDefinition", "Go to Definition", "Edit", "F12", "📍")
    add("edit.format", "Format Document", "Edit", "Shift+Alt+F", "🪄")
    add("edit.commentLine", "Toggle Line Comment", "Edit", "Ctrl+/", "💬")
    add("edit.duplicateLine", "Duplicate Line", "Edit", "Ctrl+D", "⎘")

    # View ------------------------------------------------------------------
    add("view.toggleSidebar", "Toggle Sidebar", "View", "Ctrl+B", "📑")
    add("view.toggleConsole", "Toggle Console", "View", "Ctrl+`", "💻")
    add("view.zoomIn", "Zoom In", "View", "Ctrl+=", "🔎")
    add("view.zoomOut", "Zoom Out", "View", "Ctrl+-", "🔎")
    add("view.resetZoom", "Reset Zoom", "View", "Ctrl+0", "🔎")
    add("view.fullscreen", "Toggle Full Screen", "View", "F11", "🖥️")
    add("view.toggleDarkMode", "Toggle Dark Mode", "View", "", "🌓")
    add("view.layoutReset", "Reset Window Layout", "View", "", "🧱")

    # Synthesis -------------------------------------------------------------
    add("synth.run", "Run Synthesis", "Synthesis", "F7", "⚙️", ["yosys"])
    add("synth.stop", "Stop Synthesis", "Synthesis", "", "⏹️")
    add("synth.viewNetlist", "View Synthesized Netlist", "Synthesis", "", "🕸️")
    add("synth.report", "Open Synthesis Report", "Synthesis", "", "📄")
    add("synth.cleanCache", "Clean Synthesis Cache", "Synthesis", "", "🧹")
    add("synth.openOptions", "Synthesis Options...", "Synthesis", "", "⚙️")

    # Simulation ------------------------------------------------------------
    add("sim.run", "Run Simulation", "Simulation", "F5", "▶️", ["icarus", "verilator"])
    add("sim.stop", "Stop Simulation", "Simulation", "Shift+F5", "⏹️")
    add("sim.openWaveform", "Open Waveform Viewer", "Simulation", "", "📈")
    add("sim.openCoverage", "Open Coverage Report", "Simulation", "", "📊")
    add("sim.runRegression", "Run Regression Suite", "Simulation", "", "🧪")
    add("sim.openTestbench", "Open Active Testbench", "Simulation", "", "🧫")

    # Place & Route ---------------------------------------------------------
    add("pnr.run", "Run Place & Route", "Place & Route", "F8", "🧩", ["openroad"])
    add("pnr.openFloorplan", "Open Floorplan", "Place & Route", "", "🏗️")
    add("pnr.openCongestion", "Show Congestion Map", "Place & Route", "", "🚦")
    add("pnr.openPower", "Show Power Map", "Place & Route", "", "🔋")
    add("pnr.openDensity", "Show Density Map", "Place & Route", "", "📐")

    # DRC / LVS / GDS -------------------------------------------------------
    add("drc.run", "Run DRC", "Verification", "F9", "✅", ["magic", "klayout"])
    add("drc.openViewer", "Open DRC Viewer", "Verification", "", "🔍")
    add("lvs.run", "Run LVS", "Verification", "Shift+F9", "🧷", ["netgen"])
    add("lvs.openReport", "Open LVS Report", "Verification", "", "📄")
    add("gds.export", "Export GDSII", "Verification", "", "📦")
    add("gds.openViewer", "Open GDS Viewer", "Verification", "", "🗺️")

    # STA / Power -----------------------------------------------------------
    add("sta.run", "Run Static Timing Analysis", "Timing", "", "⏱️", ["opensta"])
    add("sta.openReport", "Open Timing Report", "Timing", "", "📄")
    add("sta.openSlackHistogram", "Open Slack Histogram", "Timing", "", "📊")
    add("power.run", "Run Power Analysis", "Power", "", "🔋")
    add("power.openReport", "Open Power Report", "Power", "", "📄")

    # FPGA ------------------------------------------------------------------
    add("fpga.synth", "FPGA Synthesis", "FPGA", "", "🟩")
    add("fpga.pnr", "FPGA Place & Route", "FPGA", "", "🟦", ["nextpnr"])
    add("fpga.bitstream", "Generate Bitstream", "FPGA", "", "🟪")
    add("fpga.program", "Program Board", "FPGA", "", "📡", ["openocd"])
    add("fpga.selectBoard", "Select Board...", "FPGA", "", "🧰")

    # Crypto ----------------------------------------------------------------
    add("crypto.tvla", "Run TVLA Leakage Test", "Crypto", "", "🔐")
    add("crypto.constantTime", "Verify Constant-Time Operation", "Crypto", "", "⏱️")
    add("crypto.fips", "Run FIPS 140-3 Checks", "Crypto", "", "🛡️")
    add("crypto.openSuite", "Open Crypto Verification Suite", "Crypto", "", "🧪")

    # Block design / IP -----------------------------------------------------
    add("block.openDesigner", "Open Block Designer", "Design", "", "🧱")
    add("block.addIp", "Add IP Block...", "Design", "", "➕")
    add("block.autoConnect", "Auto-Connect Buses", "Design", "", "🔗")
    add("block.generateWrapper", "Generate Wrapper", "Design", "", "🧰")

    # Git -------------------------------------------------------------------
    add("git.commit", "Git: Commit", "Git", "Ctrl+K Ctrl+C", "📝")
    add("git.push", "Git: Push", "Git", "", "⬆️")
    add("git.pull", "Git: Pull", "Git", "", "⬇️")
    add("git.openPanel", "Open Source Control Panel", "Git", "Ctrl+Shift+G", "🌿")
    add("git.diff", "Show Diff", "Git", "", "🆚")
    add("git.history", "Show File History", "Git", "", "🕘")

    # Tools / settings ------------------------------------------------------
    add("tools.openTcl", "Open Tcl Console", "Tools", "", "🐚")
    add("tools.openTerminal", "Open Terminal", "Tools", "Ctrl+Shift+`", "💻")
    add("tools.openExtensions", "Manage Extensions", "Tools", "Ctrl+Shift+X", "🧩")
    add("tools.openPdkInstaller", "Install PDK...", "Tools", "", "📥")
    add("tools.openWslSetup", "WSL Setup Wizard", "Tools", "", "🐧")
    add("tools.checkUpdates", "Check for Updates", "Tools", "", "🔄")
    add("tools.openSettings", "Settings", "Tools", "Ctrl+,", "⚙️")
    add("tools.openKeybindings", "Keyboard Shortcuts", "Tools", "Ctrl+K Ctrl+S", "⌨️")

    # Help ------------------------------------------------------------------
    add("help.docs", "Open Documentation", "Help", "F1", "📖")
    add("help.tutorials", "Browse Tutorials", "Help", "", "🎓")
    add("help.shortcuts", "Show Keyboard Shortcuts Reference", "Help", "", "📋")
    add("help.about", "About OpenForge EDA", "Help", "", "ℹ️")
    add("help.reportBug", "Report a Bug", "Help", "", "🐞")
    add("help.discord", "Join Discord Community", "Help", "", "💬")

    # Window ----------------------------------------------------------------
    add("window.newWindow", "New Window", "Window", "Ctrl+Shift+N", "🪟")
    add("window.closeWindow", "Close Window", "Window", "Ctrl+Shift+W", "❎")
    add("window.minimize", "Minimize", "Window", "", "➖")
    add("window.maximize", "Maximize", "Window", "", "🟦")

    return cmds


BUILTIN_COMMANDS: list[Command] = _build_builtin_commands()


# ---------------------------------------------------------------------------
# Fuzzy matcher
# ---------------------------------------------------------------------------


def _fuzzy_score(query: str, target: str) -> int:
    """Return a score >= 0 if all query chars appear in target in order.

    Higher is better. Returns -1 on no match.
    """
    if not query:
        return 0
    q = query.lower()
    t = target.lower()
    if q in t:
        # exact substring is best
        return 1000 - t.index(q) - (len(t) - len(q))
    score = 0
    qi = 0
    streak = 0
    last_match = -1
    for i, ch in enumerate(t):
        if qi < len(q) and ch == q[qi]:
            qi += 1
            if last_match == i - 1:
                streak += 1
                score += 5 + streak
            else:
                streak = 0
                score += 1
            last_match = i
    if qi != len(q):
        return -1
    # Bonus for shorter targets
    score += max(0, 30 - len(t))
    return score


def _command_score(query: str, cmd: Command) -> int:
    """Best score across title, category, id, and keywords."""
    if not query:
        return 0
    candidates = [cmd.title, cmd.category, cmd.display_title, cmd.id]
    candidates.extend(cmd.keywords)
    best = -1
    for c in candidates:
        s = _fuzzy_score(query, c)
        if s > best:
            best = s
    return best


# ---------------------------------------------------------------------------
# Custom item delegate for nicer rows
# ---------------------------------------------------------------------------


class _CommandDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fg = QColor("#cdd6f4")
        self._dim = QColor("#9399b2")
        self._accent = QColor("#89b4fa")
        self._sel_bg = QColor("#45475a")
        self._hover_bg = QColor("#313244")

    def set_palette(self, fg, dim, accent, sel_bg, hover_bg) -> None:
        self._fg = QColor(fg)
        self._dim = QColor(dim)
        self._accent = QColor(accent)
        self._sel_bg = QColor(sel_bg)
        self._hover_bg = QColor(hover_bg)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 38)

    def paint(self, painter: QPainter, option, index) -> None:
        cmd: Command = index.data(Qt.ItemDataRole.UserRole)
        if cmd is None:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(6, 2, -6, -2)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(self._sel_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(self._hover_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 6, 6)

        # Icon
        painter.setPen(self._fg)
        font = painter.font()
        font.setPointSize(13)
        painter.setFont(font)
        icon_rect = QRect(rect.left() + 10, rect.top(), 24, rect.height())
        painter.drawText(
            icon_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cmd.icon or "•"
        )

        # Title
        font.setBold(True)
        painter.setFont(font)
        title_rect = QRect(rect.left() + 40, rect.top(), rect.width() - 200, rect.height())
        painter.drawText(
            title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cmd.title
        )

        # Category
        font.setBold(False)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(self._dim)
        fm = QFontMetrics(font)
        title_w = fm.horizontalAdvance(cmd.title) + 50
        cat_rect = QRect(
            rect.left() + 40 + title_w,
            rect.top(),
            rect.width() - 200 - title_w,
            rect.height(),
        )
        painter.drawText(
            cat_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            cmd.category,
        )

        # Shortcut
        if cmd.shortcut:
            painter.setPen(self._accent)
            sc_rect = QRect(rect.right() - 150, rect.top(), 140, rect.height())
            painter.drawText(
                sc_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                cmd.shortcut,
            )

        painter.restore()


# ---------------------------------------------------------------------------
# Command palette dialog
# ---------------------------------------------------------------------------


class CommandPalette(QDialog):
    """Floating, frameless command palette."""

    command_executed = Signal(str)  # command id

    MAX_RECENTS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Command Palette")
        self.resize(700, 460)

        self._commands: dict[str, Command] = {}
        self._filtered: list[tuple[Command, int]] = []
        self._recents: list[str] = self._load_recents()
        self._build_ui()
        self.register_commands(BUILTIN_COMMANDS)
        self._refresh_list("")

    # ----- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._frame = QFrame(self)
        self._frame.setObjectName("CommandPaletteFrame")
        outer.addWidget(self._frame)

        shadow = QGraphicsDropShadowEffect(self._frame)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._frame.setGraphicsEffect(shadow)

        body = QVBoxLayout(self._frame)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(8)

        # Search input
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or search...")
        self._input.setClearButtonEnabled(True)
        f = self._input.font()
        f.setPointSize(13)
        self._input.setFont(f)
        self._input.textChanged.connect(self._on_query_changed)
        self._input.returnPressed.connect(self._execute_current)
        self._input.installEventFilter(self)
        body.addWidget(self._input)

        # Result list
        self._list = QListWidget()
        self._list.setMouseTracking(True)
        self._list.setUniformItemSizes(True)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.itemActivated.connect(self._on_item_activated)
        self._list.itemClicked.connect(self._on_item_activated)
        self._delegate = _CommandDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        body.addWidget(self._list, stretch=1)

        # Footer hints
        self._footer = QLabel("↑↓ navigate    ↵ run    Esc close    type to search")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self._footer)

        self._apply_dark_theme()

    # ----- registration -----------------------------------------------------

    def register_command(self, command: Command) -> None:
        self._commands[command.id] = command

    def register_commands(self, commands: list[Command]) -> None:
        for c in commands:
            self.register_command(c)

    def set_handler(self, command_id: str, handler: Callable[[], None]) -> None:
        cmd = self._commands.get(command_id)
        if cmd is not None:
            cmd.handler = handler

    # ----- search / filter --------------------------------------------------

    def filter_commands(self, query: str) -> list[Command]:
        if not query:
            # Recents first, then everything alphabetised
            recents = [self._commands[r] for r in self._recents if r in self._commands]
            recent_ids = {r.id for r in recents}
            others = sorted(
                (c for c in self._commands.values() if c.id not in recent_ids),
                key=lambda c: (c.category, c.title),
            )
            return recents + others
        scored: list[tuple[Command, int]] = []
        for cmd in self._commands.values():
            s = _command_score(query, cmd)
            if s >= 0:
                scored.append((cmd, s))
        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:200]]

    def _refresh_list(self, query: str) -> None:
        self._list.clear()
        results = self.filter_commands(query)
        if not query and self._recents:
            header = QListWidgetItem("RECENTLY USED")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setSizeHint(QSize(0, 22))
            self._list.addItem(header)
        for cmd in results:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cmd)
            item.setSizeHint(QSize(0, 38))
            self._list.addItem(item)
        if self._list.count() > 0:
            for i in range(self._list.count()):
                it = self._list.item(i)
                if it.flags() & Qt.ItemFlag.ItemIsSelectable:
                    self._list.setCurrentRow(i)
                    break

    def _on_query_changed(self, text: str) -> None:
        self._refresh_list(text)

    # ----- show / animate ---------------------------------------------------

    def show_palette(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            geo = parent.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + max(80, geo.height() // 6)
            self.move(x, y)
        self._input.clear()
        self._input.setFocus()
        self._refresh_list("")
        self.setWindowOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ----- execute ----------------------------------------------------------

    def _execute_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._on_item_activated(item)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        cmd: Command | None = item.data(Qt.ItemDataRole.UserRole)
        if cmd is None:
            return
        self._push_recent(cmd.id)
        self.command_executed.emit(cmd.id)
        if cmd.handler is not None:
            with contextlib.suppress(Exception):
                cmd.handler()
        self.close()

    # ----- recents ----------------------------------------------------------

    def _load_recents(self) -> list[str]:
        settings = QSettings("OpenForge", "Desktop")
        raw = settings.value("command_palette/recents", "[]")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception:
            pass
        return []

    def _save_recents(self) -> None:
        settings = QSettings("OpenForge", "Desktop")
        settings.setValue("command_palette/recents", json.dumps(self._recents))

    def _push_recent(self, command_id: str) -> None:
        self._recents = [r for r in self._recents if r != command_id]
        self._recents.insert(0, command_id)
        self._recents = self._recents[: self.MAX_RECENTS]
        self._save_recents()

    # ----- key handling -----------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if key == Qt.Key.Key_PageDown:
                self._move_selection(8)
                return True
            if key == Qt.Key.Key_PageUp:
                self._move_selection(-8)
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, delta: int) -> None:
        count = self._list.count()
        if count == 0:
            return
        cur = self._list.currentRow()
        new = max(0, min(count - 1, cur + delta))
        # Skip non-selectable headers
        while 0 <= new < count and not (
            self._list.item(new).flags() & Qt.ItemFlag.ItemIsSelectable
        ):
            new += 1 if delta > 0 else -1
        if 0 <= new < count:
            self._list.setCurrentRow(new)

    # ----- theming ----------------------------------------------------------

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet(
            """
            QFrame#CommandPaletteFrame {
                background: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 12px;
            }
            QLineEdit {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 10px 12px;
                selection-background-color: #585b70;
            }
            QLineEdit:focus { border: 1px solid #89b4fa; }
            QListWidget {
                background: transparent;
                border: none;
                color: #cdd6f4;
                outline: 0;
            }
            QListWidget::item { border: none; }
            QLabel { color: #9399b2; font-size: 11px; }
            QScrollBar:vertical { background: transparent; width: 10px; }
            QScrollBar::handle:vertical {
                background: #45475a; border-radius: 5px; min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )
        self._delegate.set_palette("#cdd6f4", "#9399b2", "#89b4fa", "#45475a", "#313244")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
