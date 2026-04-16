"""Real-time collaboration panel.

Provides the UI shell for multi-user collaboration: user presence,
activity feed, threaded comments anchored to files/lines, team chat,
and file lock indicators. The backend is a WebSocket endpoint at
/ws/collab; actual CRDT document merging is a future project, so
this panel focuses on presence, comments and chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import (
    QObject,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Catppuccin palette
CAT_BASE = "#1e1e2e"
CAT_MANTLE = "#181825"
CAT_CRUST = "#11111b"
CAT_SURFACE0 = "#313244"
CAT_SURFACE1 = "#45475a"
CAT_TEXT = "#cdd6f4"
CAT_SUBTEXT = "#a6adc8"
CAT_BLUE = "#89b4fa"
CAT_LAVENDER = "#b4befe"
CAT_MAUVE = "#cba6f7"
CAT_PINK = "#f5c2e7"
CAT_RED = "#f38ba8"
CAT_PEACH = "#fab387"
CAT_YELLOW = "#f9e2af"
CAT_GREEN = "#a6e3a1"
CAT_TEAL = "#94e2d5"
CAT_SKY = "#89dceb"

AVATAR_COLORS = [
    CAT_BLUE,
    CAT_MAUVE,
    CAT_PEACH,
    CAT_GREEN,
    CAT_RED,
    CAT_YELLOW,
    CAT_TEAL,
    CAT_PINK,
    CAT_SKY,
    CAT_LAVENDER,
]


COLLAB_QSS = f"""
QDockWidget {{
    background: {CAT_BASE};
    color: {CAT_TEXT};
}}
QDockWidget::title {{
    background: {CAT_MANTLE};
    color: {CAT_LAVENDER};
    padding: 6px;
    font-weight: bold;
}}
QWidget {{
    background: {CAT_BASE};
    color: {CAT_TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}}
QTabWidget::pane {{
    border: 1px solid {CAT_SURFACE0};
}}
QTabBar::tab {{
    background: {CAT_MANTLE};
    color: {CAT_SUBTEXT};
    padding: 6px 14px;
    border: 1px solid {CAT_SURFACE0};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background: {CAT_BASE};
    color: {CAT_BLUE};
    border-bottom: 2px solid {CAT_BLUE};
}}
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {CAT_MANTLE};
    border: 1px solid {CAT_SURFACE0};
    border-radius: 4px;
    padding: 6px;
    selection-background-color: {CAT_BLUE};
}}
QPushButton {{
    background: {CAT_SURFACE0};
    border: 1px solid {CAT_SURFACE1};
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background: {CAT_SURFACE1};
    border-color: {CAT_MAUVE};
}}
QListWidget, QTreeWidget, QTableWidget {{
    background: {CAT_MANTLE};
    border: 1px solid {CAT_SURFACE0};
    alternate-background-color: {CAT_BASE};
}}
QGroupBox {{
    border: 1px solid {CAT_SURFACE0};
    border-radius: 4px;
    margin-top: 14px;
    padding-top: 14px;
    color: {CAT_PINK};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QLabel#status_connected {{
    color: {CAT_GREEN};
    font-weight: bold;
}}
QLabel#status_disconnected {{
    color: {CAT_RED};
    font-weight: bold;
}}
QLabel#heading {{
    color: {CAT_LAVENDER};
    font-size: 12pt;
    font-weight: bold;
}}
"""


# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------
@dataclass
class CollabUser:
    username: str
    display_name: str
    online: bool = False
    color: str = CAT_BLUE
    current_file: str = ""
    idle: bool = False


@dataclass
class Activity:
    timestamp: datetime
    user: str
    action: str  # "edited", "committed", "started build", etc.
    target: str  # file or object


@dataclass
class Comment:
    author: str
    text: str
    file: str = ""
    line: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    replies: list[Comment] = field(default_factory=list)


@dataclass
class FileLock:
    file: str
    locked_by: str
    acquired: datetime


@dataclass
class ChatMessage:
    author: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)


# ----------------------------------------------------------------------
# Mock websocket client (stub to be replaced with QWebSocket)
# ----------------------------------------------------------------------
class CollabClient(QObject):
    """WebSocket-like client stub. Emits events that the UI consumes."""

    connection_changed = Signal(bool)  # connected?
    user_joined = Signal(object)
    user_left = Signal(str)
    activity = Signal(object)
    chat = Signal(object)
    comment = Signal(object)
    lock_changed = Signal(object, bool)

    def __init__(self, url: str = "ws://localhost:8000/ws/collab", parent=None):
        super().__init__(parent)
        self.url = url
        self._connected = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_tick)
        self._tick = 0

    def connect(self) -> None:
        self._connected = True
        self.connection_changed.emit(True)
        self._timer.start(5000)

    def disconnect(self) -> None:
        self._connected = False
        self._timer.stop()
        self.connection_changed.emit(False)

    def is_connected(self) -> bool:
        return self._connected

    def send_chat(self, author: str, text: str) -> None:
        if self._connected:
            self.chat.emit(ChatMessage(author=author, text=text))

    def send_comment(self, comment: Comment) -> None:
        if self._connected:
            self.comment.emit(comment)

    def _simulate_tick(self) -> None:
        # No-op simulation placeholder.
        self._tick += 1


# ----------------------------------------------------------------------
# Avatar utility
# ----------------------------------------------------------------------
def make_avatar(name: str, color_hex: str, size: int = 32) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color_hex)))
    p.setPen(QPen(QColor(CAT_CRUST), 1))
    p.drawEllipse(1, 1, size - 2, size - 2)
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    p.setPen(QColor(CAT_CRUST))
    f = QFont()
    f.setBold(True)
    f.setPointSize(int(size * 0.35))
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, initials)
    p.end()
    return QIcon(pix)


# ----------------------------------------------------------------------
# Main panel
# ----------------------------------------------------------------------
class CollaborationPanel(QDockWidget):
    """Real-time multi-user collaboration UI."""

    chat_sent = Signal(str)
    comment_added = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Collaboration", parent)
        self.setObjectName("CollaborationPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setStyleSheet(COLLAB_QSS)

        self._client = CollabClient(parent=self)
        self._users: dict[str, CollabUser] = {}
        self._activities: list[Activity] = []
        self._comments: list[Comment] = []
        self._locks: dict[str, FileLock] = {}
        self._messages: list[ChatMessage] = []
        self._current_user = "zachary"

        root = QWidget()
        self.setWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(6, 6, 6, 6)
        main.setSpacing(6)

        main.addLayout(self._build_status_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self._build_users_panel())
        top.addWidget(self._build_activity_panel())
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 2)
        splitter.addWidget(top)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_comments_tab(), "Comments")
        self._tabs.addTab(self._build_chat_tab(), "Team Chat")
        self._tabs.addTab(self._build_locks_tab(), "File Locks")
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main.addWidget(splitter, 1)

        self._client.connection_changed.connect(self._on_connection_changed)
        self._client.chat.connect(self._on_chat_received)
        self._client.activity.connect(self._on_activity_received)
        self._client.comment.connect(self._on_comment_received)

        self._seed_demo_data()
        self._connect_btn.click()  # auto-connect

    # ------------------------------------------------------------------
    def _build_status_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {CAT_RED}; font-size: 16pt;")
        row.addWidget(self._status_dot)

        self._status_label = QLabel("Disconnected")
        self._status_label.setObjectName("status_disconnected")
        row.addWidget(self._status_label)

        row.addSpacing(20)
        row.addWidget(QLabel("Endpoint:"))
        self._url_edit = QLineEdit("ws://localhost:8000/ws/collab")
        row.addWidget(self._url_edit, 1)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._toggle_connect)
        row.addWidget(self._connect_btn)
        return row

    def _toggle_connect(self) -> None:
        if self._client.is_connected():
            self._client.disconnect()
        else:
            self._client.url = self._url_edit.text()
            self._client.connect()

    def _on_connection_changed(self, connected: bool) -> None:
        if connected:
            self._status_dot.setStyleSheet(f"color: {CAT_GREEN}; font-size: 16pt;")
            self._status_label.setText("Connected")
            self._status_label.setObjectName("status_connected")
            self._connect_btn.setText("Disconnect")
        else:
            self._status_dot.setStyleSheet(f"color: {CAT_RED}; font-size: 16pt;")
            self._status_label.setText("Disconnected")
            self._status_label.setObjectName("status_disconnected")
            self._connect_btn.setText("Connect")
        self._status_label.setStyleSheet(self._status_label.styleSheet())

    # ------------------------------------------------------------------
    def _build_users_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)

        h = QLabel("Active Users")
        h.setObjectName("heading")
        lay.addWidget(h)

        self._users_list = QListWidget()
        self._users_list.setIconSize(QSize(28, 28))
        lay.addWidget(self._users_list, 1)

        self._user_count_lbl = QLabel("0 online")
        self._user_count_lbl.setStyleSheet(f"color: {CAT_SUBTEXT};")
        lay.addWidget(self._user_count_lbl)
        return w

    def add_user(self, user: CollabUser) -> None:
        self._users[user.username] = user
        self._refresh_users()

    def _refresh_users(self) -> None:
        self._users_list.clear()
        online = 0
        for user in sorted(self._users.values(), key=lambda u: (not u.online, u.username)):
            status = "🟢" if user.online else "⚫"
            suffix = ""
            if user.online and user.current_file:
                suffix = f"  ({user.current_file})"
            if user.idle:
                suffix += "  [idle]"
            item = QListWidgetItem(f"{status} {user.display_name}{suffix}")
            item.setIcon(make_avatar(user.display_name, user.color))
            item.setData(Qt.ItemDataRole.UserRole, user.username)
            if not user.online:
                item.setForeground(QBrush(QColor(CAT_SUBTEXT)))
            self._users_list.addItem(item)
            if user.online:
                online += 1
        self._user_count_lbl.setText(f"{online} online / {len(self._users)} total")

    # ------------------------------------------------------------------
    def _build_activity_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)

        h = QLabel("Activity Feed")
        h.setObjectName("heading")
        lay.addWidget(h)

        self._activity_browser = QTextBrowser()
        self._activity_browser.setOpenExternalLinks(False)
        lay.addWidget(self._activity_browser, 1)

        bar = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_activity)
        bar.addStretch(1)
        bar.addWidget(clear)
        lay.addLayout(bar)
        return w

    def add_activity(self, activity: Activity) -> None:
        self._activities.append(activity)
        ts = activity.timestamp.strftime("%H:%M:%S")
        user = self._users.get(activity.user)
        color = user.color if user else CAT_SUBTEXT
        line = (
            f'<span style="color:{CAT_SUBTEXT}">[{ts}]</span> '
            f'<span style="color:{color}; font-weight:bold">{activity.user}</span> '
            f'<span style="color:{CAT_TEXT}">{activity.action}</span> '
            f'<span style="color:{CAT_YELLOW}">{activity.target}</span>'
        )
        self._activity_browser.append(line)

    def _clear_activity(self) -> None:
        self._activities.clear()
        self._activity_browser.clear()

    def _on_activity_received(self, activity: Activity) -> None:
        self.add_activity(activity)

    # ------------------------------------------------------------------
    def _build_comments_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._comments_tree = QTreeWidget()
        self._comments_tree.setHeaderLabels(["Author", "File:Line", "Comment", "Time"])
        self._comments_tree.header().setStretchLastSection(False)
        self._comments_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._comments_tree, 1)

        form = QGroupBox("Add comment")
        fl = QFormLayout(form)
        self._cmt_file = QLineEdit()
        self._cmt_file.setPlaceholderText("src/main.v")
        self._cmt_line = QLineEdit()
        self._cmt_line.setPlaceholderText("42")
        self._cmt_text = QPlainTextEdit()
        self._cmt_text.setMaximumHeight(80)
        fl.addRow("File:", self._cmt_file)
        fl.addRow("Line:", self._cmt_line)
        fl.addRow("Text:", self._cmt_text)
        submit = QPushButton("Post comment")
        submit.clicked.connect(self._post_comment)
        fl.addRow("", submit)
        lay.addWidget(form)
        return w

    def add_comment(self, comment: Comment) -> None:
        self._comments.append(comment)
        loc = f"{comment.file}:{comment.line}" if comment.file else ""
        ts = comment.timestamp.strftime("%Y-%m-%d %H:%M")
        item = QTreeWidgetItem([comment.author, loc, comment.text, ts])
        if comment.resolved:
            item.setForeground(0, QBrush(QColor(CAT_SUBTEXT)))
            item.setForeground(2, QBrush(QColor(CAT_SUBTEXT)))
        else:
            user = self._users.get(comment.author)
            if user:
                item.setForeground(0, QBrush(QColor(user.color)))
        for reply in comment.replies:
            rts = reply.timestamp.strftime("%H:%M")
            child = QTreeWidgetItem(["↳ " + reply.author, "", reply.text, rts])
            item.addChild(child)
        self._comments_tree.addTopLevelItem(item)
        item.setExpanded(True)

    def _post_comment(self) -> None:
        text = self._cmt_text.toPlainText().strip()
        if not text:
            return
        try:
            line = int(self._cmt_line.text() or 0)
        except ValueError:
            line = 0
        cmt = Comment(
            author=self._current_user,
            text=text,
            file=self._cmt_file.text(),
            line=line,
        )
        self.add_comment(cmt)
        self._client.send_comment(cmt)
        self.comment_added.emit(cmt)
        self._cmt_text.clear()

    def _on_comment_received(self, comment: Comment) -> None:
        self.add_comment(comment)

    # ------------------------------------------------------------------
    def _build_chat_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._chat_view = QTextBrowser()
        lay.addWidget(self._chat_view, 1)

        row = QHBoxLayout()
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Type a message... (Enter to send)")
        self._chat_input.returnPressed.connect(self._send_chat)
        row.addWidget(self._chat_input, 1)
        send = QPushButton("Send")
        send.clicked.connect(self._send_chat)
        row.addWidget(send)
        lay.addLayout(row)
        return w

    def _send_chat(self) -> None:
        text = self._chat_input.text().strip()
        if not text:
            return
        msg = ChatMessage(author=self._current_user, text=text)
        self._append_chat(msg)
        self._client.send_chat(msg.author, msg.text)
        self.chat_sent.emit(text)
        self._chat_input.clear()

    def _append_chat(self, msg: ChatMessage) -> None:
        self._messages.append(msg)
        user = self._users.get(msg.author)
        color = user.color if user else CAT_BLUE
        ts = msg.timestamp.strftime("%H:%M")
        html = (
            f'<div style="margin: 4px 0;">'
            f'<span style="color:{CAT_SUBTEXT}">[{ts}]</span> '
            f'<span style="color:{color}; font-weight:bold">{msg.author}:</span> '
            f'<span style="color:{CAT_TEXT}">{msg.text}</span>'
            f"</div>"
        )
        self._chat_view.append(html)

    def _on_chat_received(self, msg: ChatMessage) -> None:
        self._append_chat(msg)

    # ------------------------------------------------------------------
    def _build_locks_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._locks_table = QTableWidget(0, 3)
        self._locks_table.setHorizontalHeaderLabels(["File", "Locked By", "Since"])
        self._locks_table.horizontalHeader().setStretchLastSection(False)
        self._locks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._locks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self._locks_table, 1)

        bar = QHBoxLayout()
        release = QPushButton("Release selected lock")
        release.clicked.connect(self._release_selected_lock)
        bar.addStretch(1)
        bar.addWidget(release)
        lay.addLayout(bar)
        return w

    def set_lock(self, file: str, user: str) -> None:
        self._locks[file] = FileLock(file=file, locked_by=user, acquired=datetime.now())
        self._refresh_locks()

    def release_lock(self, file: str) -> None:
        self._locks.pop(file, None)
        self._refresh_locks()

    def _refresh_locks(self) -> None:
        self._locks_table.setRowCount(len(self._locks))
        for i, lock in enumerate(self._locks.values()):
            self._locks_table.setItem(i, 0, QTableWidgetItem(lock.file))
            self._locks_table.setItem(i, 1, QTableWidgetItem(lock.locked_by))
            self._locks_table.setItem(i, 2, QTableWidgetItem(lock.acquired.strftime("%H:%M:%S")))

    def _release_selected_lock(self) -> None:
        row = self._locks_table.currentRow()
        if row < 0:
            return
        file_item = self._locks_table.item(row, 0)
        if file_item:
            self.release_lock(file_item.text())

    # ------------------------------------------------------------------
    def _seed_demo_data(self) -> None:
        demo_users = [
            ("zachary", "Zachary K."),
            ("alice", "Alice Chen"),
            ("bob", "Bob Martinez"),
            ("carol", "Carol Singh"),
            ("dave", "Dave Johnson"),
        ]
        for i, (uname, display) in enumerate(demo_users):
            self.add_user(
                CollabUser(
                    username=uname,
                    display_name=display,
                    online=(i < 3),
                    color=AVATAR_COLORS[i % len(AVATAR_COLORS)],
                    current_file=("src/top.v" if i == 1 else "tb/top_tb.sv" if i == 2 else ""),
                )
            )
        now = datetime.now()
        for act in [
            Activity(now, "alice", "edited", "src/top.v"),
            Activity(now, "bob", "ran simulation on", "tb/top_tb.sv"),
            Activity(now, "alice", "committed", "a4f5e21: Fix counter overflow"),
            Activity(now, "zachary", "started synthesis of", "src/top.v"),
        ]:
            self.add_activity(act)
        self.add_comment(
            Comment(
                author="bob",
                text="Should this use a synchronous reset instead?",
                file="src/top.v",
                line=42,
            )
        )
        self.add_comment(
            Comment(
                author="alice",
                text="LGTM once CI passes.",
                file="src/counter.v",
                line=15,
                resolved=True,
            )
        )
        self._append_chat(ChatMessage(author="alice", text="pushed a fix for the overflow bug"))
        self._append_chat(ChatMessage(author="bob", text="nice, running sim now"))
        self.set_lock("src/top.v", "alice")
