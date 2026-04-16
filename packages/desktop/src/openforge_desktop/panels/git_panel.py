"""Git integration dock panel for OpenForge.

A VS Code-style Git panel implemented with plain ``subprocess`` calls so it
does not depend on PyGit2 or GitPython. Long-running commands run on a
``QThread`` worker so the UI never blocks.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QObject,
    QSize,
    Qt,
    QThread,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


MOCHA = {
    "base": "#1e1e2e",
    "mantle": "#181825",
    "surface0": "#313244",
    "surface1": "#45475a",
    "text": "#cdd6f4",
    "subtext0": "#a6adc8",
    "blue": "#89b4fa",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "red": "#f38ba8",
    "mauve": "#cba6f7",
    "peach": "#fab387",
}

LATTE = {
    "base": "#eff1f5",
    "mantle": "#e6e9ef",
    "surface0": "#ccd0da",
    "surface1": "#bcc0cc",
    "text": "#4c4f69",
    "subtext0": "#6c6f85",
    "blue": "#1e66f5",
    "green": "#40a02b",
    "yellow": "#df8e1d",
    "red": "#d20f39",
    "mauve": "#8839ef",
    "peach": "#fe640b",
}


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------


@dataclass
class GitFileStatus:
    path: str
    status: str  # "M", "A", "D", "??", "R", "U"
    staged: bool


@dataclass
class GitCommit:
    hash: str
    short: str
    author: str
    when: str
    subject: str


class GitRunner:
    """Synchronous git wrapper. Used by both the UI and the worker thread."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None

    def set_root(self, root: Path | None) -> None:
        self.root = Path(root) if root else None

    def is_repo(self) -> bool:
        if not self.root:
            return False
        try:
            res = self._run(["rev-parse", "--is-inside-work-tree"], check=False)
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=str(self.root) if self.root else None,
            capture_output=True,
            text=True,
            check=check,
            encoding="utf-8",
            errors="replace",
        )

    # -- queries --------------------------------------------------------
    def current_branch(self) -> str:
        try:
            res = self._run(["branch", "--show-current"], check=False)
            return res.stdout.strip() or "(detached)"
        except Exception:
            return "(error)"

    def status(self) -> list[GitFileStatus]:
        out: list[GitFileStatus] = []
        try:
            res = self._run(["status", "--porcelain=v1", "-z"], check=False)
        except Exception:
            return out
        if res.returncode != 0:
            return out
        # -z separates entries with NUL.
        entries = res.stdout.split("\0")
        for entry in entries:
            if len(entry) < 3:
                continue
            x, y, _, path = entry[0], entry[1], entry[2], entry[3:]
            if x != " " and x != "?":
                out.append(GitFileStatus(path=path, status=x, staged=True))
            if y != " ":
                if y == "?":
                    out.append(GitFileStatus(path=path, status="??", staged=False))
                else:
                    out.append(GitFileStatus(path=path, status=y, staged=False))
        return out

    def diff(self, path: str, staged: bool = False) -> str:
        try:
            args = ["diff"]
            if staged:
                args.append("--cached")
            args += ["--", path]
            res = self._run(args, check=False)
            return res.stdout
        except Exception as exc:
            return f"diff failed: {exc}"

    def stage(self, path: str) -> None:
        self._run(["add", "--", path], check=False)

    def unstage(self, path: str) -> None:
        self._run(["reset", "HEAD", "--", path], check=False)

    def commit(self, message: str) -> tuple[bool, str]:
        if not message.strip():
            return False, "Commit message is empty."
        try:
            res = self._run(["commit", "-m", message], check=False)
            return res.returncode == 0, (res.stdout + res.stderr).strip()
        except Exception as exc:
            return False, str(exc)

    def push(self) -> tuple[bool, str]:
        res = self._run(["push"], check=False)
        return res.returncode == 0, (res.stdout + res.stderr).strip()

    def pull(self) -> tuple[bool, str]:
        res = self._run(["pull", "--ff-only"], check=False)
        return res.returncode == 0, (res.stdout + res.stderr).strip()

    def fetch(self) -> tuple[bool, str]:
        res = self._run(["fetch", "--all"], check=False)
        return res.returncode == 0, (res.stdout + res.stderr).strip()

    def branches(self) -> list[str]:
        res = self._run(["branch", "--list"], check=False)
        out: list[str] = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("*"):
                line = line[1:].strip()
            if line:
                out.append(line)
        return out

    def switch(self, branch: str) -> tuple[bool, str]:
        res = self._run(["checkout", branch], check=False)
        return res.returncode == 0, (res.stdout + res.stderr).strip()

    def log(self, limit: int = 50) -> list[GitCommit]:
        sep = "\x1f"
        fmt = sep.join(["%H", "%h", "%an", "%ad", "%s"])
        res = self._run(["log", f"-n{limit}", f"--pretty=format:{fmt}", "--date=iso"], check=False)
        commits: list[GitCommit] = []
        for line in res.stdout.splitlines():
            parts = line.split(sep)
            if len(parts) == 5:
                commits.append(GitCommit(*parts))
        return commits

    def stash(self) -> tuple[bool, str]:
        res = self._run(["stash", "push"], check=False)
        return res.returncode == 0, (res.stdout + res.stderr).strip()

    def stash_pop(self) -> tuple[bool, str]:
        res = self._run(["stash", "pop"], check=False)
        return res.returncode == 0, (res.stdout + res.stderr).strip()


# ---------------------------------------------------------------------------
# Worker thread for long-running ops
# ---------------------------------------------------------------------------


class _GitWorker(QObject):
    finished = Signal(str, bool, str)  # (op, ok, output)

    def __init__(self, runner: GitRunner) -> None:
        super().__init__()
        self.runner = runner

    @Slot(str)
    def run_op(self, op: str) -> None:
        try:
            if op == "push":
                ok, out = self.runner.push()
            elif op == "pull":
                ok, out = self.runner.pull()
            elif op == "fetch":
                ok, out = self.runner.fetch()
            elif op == "stash":
                ok, out = self.runner.stash()
            elif op == "stash_pop":
                ok, out = self.runner.stash_pop()
            else:
                ok, out = False, f"Unknown op: {op}"
        except Exception as exc:
            ok, out = False, str(exc)
        self.finished.emit(op, ok, out)


# ---------------------------------------------------------------------------
# Dock panel
# ---------------------------------------------------------------------------


class GitPanel(QDockWidget):
    """VS Code-style Git panel."""

    file_diff_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Source Control", parent)
        self.setObjectName("GitPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self._dark = True
        self._palette = MOCHA
        self.runner = GitRunner()
        self._project_root: Path | None = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_fs_changed)
        self._watcher.directoryChanged.connect(self._on_fs_changed)

        self._thread = QThread(self)
        self._worker = _GitWorker(self.runner)
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self._on_worker_finished)
        self._thread.start()

        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget(self)
        self.setWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        self.toolbar = QToolBar(container)
        self.toolbar.setIconSize(QSize(16, 16))
        self.act_refresh = QAction("Refresh", self)
        self.act_pull = QAction("Pull", self)
        self.act_push = QAction("Push", self)
        self.act_fetch = QAction("Fetch", self)
        self.act_stash = QAction("Stash", self)
        self.act_pop = QAction("Pop", self)
        for a in (
            self.act_refresh,
            self.act_pull,
            self.act_push,
            self.act_fetch,
            self.act_stash,
            self.act_pop,
        ):
            self.toolbar.addAction(a)
        outer.addWidget(self.toolbar)

        # Branch row
        branch_row = QHBoxLayout()
        branch_row.setContentsMargins(8, 4, 8, 4)
        self.branch_label = QLabel("Branch:")
        branch_row.addWidget(self.branch_label)
        self.branch_combo = QComboBox()
        self.branch_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        branch_row.addWidget(self.branch_combo, 1)
        outer.addLayout(branch_row)

        # Tabs: Changes / History
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_changes_tab(), "Changes")
        self.tabs.addTab(self._build_history_tab(), "History")

        # Wiring
        self.act_refresh.triggered.connect(self.refresh)
        self.act_pull.triggered.connect(lambda: self._dispatch("pull"))
        self.act_push.triggered.connect(lambda: self._dispatch("push"))
        self.act_fetch.triggered.connect(lambda: self._dispatch("fetch"))
        self.act_stash.triggered.connect(lambda: self._dispatch("stash"))
        self.act_pop.triggered.connect(lambda: self._dispatch("stash_pop"))
        self.branch_combo.activated.connect(self._on_branch_activated)

    def _build_changes_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Status", "File"])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemClicked.connect(self._on_file_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        splitter.addWidget(self.tree)

        self.diff_view = QTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("Consolas", 9))
        splitter.addWidget(self.diff_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Commit area
        self.commit_msg = QTextEdit()
        self.commit_msg.setPlaceholderText("Commit message... (Ctrl+Enter to commit)")
        self.commit_msg.setMaximumHeight(80)
        layout.addWidget(self.commit_msg)
        commit_row = QHBoxLayout()
        self.commit_btn = QPushButton("Commit")
        self.commit_btn.clicked.connect(self._on_commit_clicked)
        commit_row.addWidget(self.commit_btn)
        commit_row.addStretch(1)
        layout.addLayout(commit_row)

        return w

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.history = QTreeWidget()
        self.history.setHeaderLabels(["Hash", "Author", "Date", "Subject"])
        self.history.setRootIsDecorated(False)
        layout.addWidget(self.history, 1)
        return w

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_project_root(self, path: Path) -> None:
        self._project_root = Path(path)
        self.runner.set_root(self._project_root)
        # Watch the .git/HEAD and the project dir
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        head = self._project_root / ".git" / "HEAD"
        if head.exists():
            self._watcher.addPath(str(head))
        if self._project_root.exists():
            self._watcher.addPath(str(self._project_root))
        self.refresh()

    def refresh(self) -> None:
        if not self.runner.is_repo():
            self.tree.clear()
            self.diff_view.clear()
            self.branch_combo.clear()
            self.branch_combo.addItem("(not a git repository)")
            return
        # Branches
        branches = self.runner.branches()
        current = self.runner.current_branch()
        self.branch_combo.blockSignals(True)
        self.branch_combo.clear()
        self.branch_combo.addItems(branches)
        if current in branches:
            self.branch_combo.setCurrentText(current)
        self.branch_combo.blockSignals(False)

        # Files
        self.tree.clear()
        groups = {
            "Staged": QTreeWidgetItem(self.tree, ["Staged"]),
            "Modified": QTreeWidgetItem(self.tree, ["Modified"]),
            "Untracked": QTreeWidgetItem(self.tree, ["Untracked"]),
        }
        for g in groups.values():
            g.setExpanded(True)
            f = QFont()
            f.setBold(True)
            g.setFont(0, f)

        for fs in self.runner.status():
            label = self._status_label(fs.status)
            item = QTreeWidgetItem([label, fs.path])
            item.setData(0, Qt.UserRole, fs)
            if fs.staged:
                groups["Staged"].addChild(item)
            elif fs.status == "??":
                groups["Untracked"].addChild(item)
            else:
                groups["Modified"].addChild(item)

        for _name, group in list(groups.items()):
            if group.childCount() == 0:
                idx = self.tree.indexOfTopLevelItem(group)
                self.tree.takeTopLevelItem(idx)

        self._refresh_history()

    def _refresh_history(self) -> None:
        self.history.clear()
        for c in self.runner.log(100):
            QTreeWidgetItem(self.history, [c.short, c.author, c.when, c.subject])
        for i in range(4):
            self.history.resizeColumnToContents(i)

    def stage_file(self, path: str) -> None:
        self.runner.stage(path)
        self.refresh()

    def unstage_file(self, path: str) -> None:
        self.runner.unstage(path)
        self.refresh()

    def commit(self, message: str) -> bool:
        ok, out = self.runner.commit(message)
        if not ok:
            QMessageBox.warning(self, "Commit failed", out)
        self.refresh()
        return ok

    def push(self) -> None:
        self._dispatch("push")

    def pull(self) -> None:
        self._dispatch("pull")

    def get_branches(self) -> list[str]:
        return self.runner.branches()

    def switch_branch(self, branch: str) -> None:
        ok, out = self.runner.switch(branch)
        if not ok:
            QMessageBox.warning(self, "Switch failed", out)
        self.refresh()

    def get_log(self, limit: int = 50) -> list[dict]:
        return [c.__dict__ for c in self.runner.log(limit)]

    def set_theme(self, dark: bool = True) -> None:
        self._dark = dark
        self._palette = MOCHA if dark else LATTE
        self._apply_theme()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        p = self._palette
        self.setStyleSheet(
            f"""
            QDockWidget#GitPanel {{ color: {p["text"]}; }}
            QWidget {{ background: {p["base"]}; color: {p["text"]}; }}
            QToolBar {{ background: {p["mantle"]}; border: none; padding: 4px; }}
            QToolBar QToolButton {{
                background: {p["surface0"]}; color: {p["text"]};
                border: 1px solid {p["surface1"]}; border-radius: 4px;
                padding: 3px 8px; margin: 2px;
            }}
            QToolBar QToolButton:hover {{ background: {p["surface1"]}; }}
            QTreeWidget, QTextEdit, QComboBox {{
                background: {p["mantle"]}; color: {p["text"]};
                border: 1px solid {p["surface0"]};
                selection-background-color: {p["blue"]};
                selection-color: {p["base"]};
            }}
            QHeaderView::section {{
                background: {p["surface0"]}; color: {p["text"]};
                border: none; padding: 4px;
            }}
            QPushButton {{
                background: {p["green"]}; color: {p["base"]};
                border: none; border-radius: 4px; padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {p["blue"]}; }}
            QTabBar::tab {{
                background: {p["surface0"]}; color: {p["text"]};
                padding: 6px 12px;
            }}
            QTabBar::tab:selected {{ background: {p["blue"]}; color: {p["base"]}; }}
            QLabel {{ color: {p["subtext0"]}; }}
            """
        )

    @staticmethod
    def _status_label(s: str) -> str:
        return {
            "M": "M",
            "A": "A",
            "D": "D",
            "R": "R",
            "C": "C",
            "U": "U",
            "??": "U?",
        }.get(s, s)

    def _on_file_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        fs = item.data(0, Qt.UserRole)
        if not isinstance(fs, GitFileStatus):
            return
        text = self.runner.diff(fs.path, staged=fs.staged)
        if not text and fs.status == "??":
            try:
                full = (self._project_root or Path()) / fs.path
                text = (
                    "+++ Untracked file: "
                    + fs.path
                    + "\n"
                    + full.read_text(encoding="utf-8", errors="replace")
                )
            except OSError as exc:
                text = f"(could not read file: {exc})"
        self._render_diff(text)
        self.file_diff_requested.emit(fs.path, text)

    def _render_diff(self, text: str) -> None:
        self.diff_view.clear()
        p = self._palette
        cursor = self.diff_view.textCursor()
        for line in text.splitlines():
            fmt = QTextCharFormat()
            if line.startswith("+++") or line.startswith("---"):
                fmt.setForeground(QColor(p["mauve"]))
            elif line.startswith("@@"):
                fmt.setBackground(QColor(p["surface0"]))
                fmt.setForeground(QColor(p["blue"]))
            elif line.startswith("+"):
                fmt.setBackground(QColor(p["green"]).darker(150))
                fmt.setForeground(QColor(p["green"]))
            elif line.startswith("-"):
                fmt.setBackground(QColor(p["red"]).darker(180))
                fmt.setForeground(QColor(p["red"]))
            else:
                fmt.setForeground(QColor(p["text"]))
            cursor.insertText(line + "\n", fmt)

    def _on_tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        fs = item.data(0, Qt.UserRole)
        if not isinstance(fs, GitFileStatus):
            return
        menu = QMenu(self)
        if fs.staged:
            menu.addAction("Unstage", lambda: self.unstage_file(fs.path))
        else:
            menu.addAction("Stage", lambda: self.stage_file(fs.path))
        menu.addSeparator()
        menu.addAction("Discard changes", lambda: self._discard(fs.path))
        menu.addAction("Open file", lambda: self._open_file(fs.path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _discard(self, path: str) -> None:
        ok = QMessageBox.question(
            self,
            "Discard changes",
            f"Discard all uncommitted changes in {path}?",
        )
        if ok == QMessageBox.Yes:
            self.runner._run(["checkout", "--", path], check=False)
            self.refresh()

    def _open_file(self, path: str) -> None:
        if self._project_root:
            self.file_diff_requested.emit(str(self._project_root / path), "")

    def _on_commit_clicked(self) -> None:
        msg = self.commit_msg.toPlainText().strip()
        if not msg:
            QMessageBox.warning(self, "Commit", "Enter a commit message first.")
            return
        if self.commit(msg):
            self.commit_msg.clear()

    def _on_branch_activated(self, _idx: int) -> None:
        target = self.branch_combo.currentText()
        if target and target != self.runner.current_branch():
            self.switch_branch(target)

    def _dispatch(self, op: str) -> None:
        if not self.runner.is_repo():
            return
        # Run on worker thread via direct invocation - QThread + Slot.
        self._worker.run_op(op)

    @Slot(str, bool, str)
    def _on_worker_finished(self, op: str, ok: bool, output: str) -> None:
        if not ok:
            QMessageBox.warning(self, f"git {op} failed", output or "(no output)")
        else:
            QMessageBox.information(self, f"git {op}", output or "OK")
        self.refresh()

    def _on_fs_changed(self, _path: str) -> None:
        self.refresh()

    def closeEvent(self, event):
        self._thread.quit()
        self._thread.wait(1000)
        super().closeEvent(event)
