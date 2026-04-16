"""Auto-update system for OpenForge desktop.

Polls the GitHub releases API for the latest version, compares to the
current build, downloads the installer, and prompts the user to apply it.
Network calls run on a worker thread; the dialog is purely UI.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt,
    QObject,
    QThread,
    Signal,
    QTimer,
    QUrl,
    QSize,
)
from PySide6.QtGui import QDesktopServices, QFont, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QFrame,
    QProgressBar,
    QMessageBox,
    QSizePolicy,
    QWidget,
)


GITHUB_RELEASES_URL = "https://api.github.com/repos/dyber/openforge/releases/latest"


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def _parse_version(v: str) -> tuple[int, ...]:
    v = v.lstrip("v").strip()
    parts: list[int] = []
    for chunk in v.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, current: str) -> bool:
    return _parse_version(remote) > _parse_version(current)


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


@dataclass
class ReleaseInfo:
    version: str
    changelog: str
    asset_url: Optional[str]
    asset_name: Optional[str]


class _CheckWorker(QObject):
    finished = Signal(object)  # ReleaseInfo or None
    error = Signal(str)

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "OpenForge"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            version = str(data.get("tag_name") or data.get("name") or "0.0.0")
            changelog = str(data.get("body") or "")
            asset_url = None
            asset_name = None
            for asset in data.get("assets", []) or []:
                name = asset.get("name", "").lower()
                if _matches_platform(name):
                    asset_url = asset.get("browser_download_url")
                    asset_name = asset.get("name")
                    break
            self.finished.emit(ReleaseInfo(version, changelog, asset_url, asset_name))
        except urllib.error.URLError as exc:
            self.error.emit(f"Network error: {exc}")
        except Exception as exc:
            self.error.emit(f"Error: {exc}")


def _matches_platform(name: str) -> bool:
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        return name.endswith(".exe") or name.endswith(".msi") or name.endswith(".msix")
    if sysname == "darwin":
        return name.endswith(".dmg") or name.endswith(".pkg")
    return name.endswith(".appimage") or name.endswith(".deb") or name.endswith(".rpm")


class _DownloadWorker(QObject):
    progress = Signal(int, int)  # downloaded, total
    finished = Signal(str)  # local path
    error = Signal(str)

    def __init__(self, url: str, dest: Path):
        super().__init__()
        self._url = url
        self._dest = dest
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                self._url, headers={"User-Agent": "OpenForge"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", "0") or 0)
                downloaded = 0
                self._dest.parent.mkdir(parents=True, exist_ok=True)
                with open(self._dest, "wb") as fh:
                    while True:
                        if self._cancelled:
                            self.error.emit("Cancelled")
                            return
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)
            self.finished.emit(str(self._dest))
        except Exception as exc:
            self.error.emit(f"Download failed: {exc}")


# ---------------------------------------------------------------------------
# AutoUpdater orchestrator
# ---------------------------------------------------------------------------


class AutoUpdater(QObject):
    update_available = Signal(str, str)  # version, changelog
    no_update = Signal()
    update_downloaded = Signal(str)  # local path
    update_error = Signal(str)
    download_progress = Signal(int, int)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current = current_version
        self._release: Optional[ReleaseInfo] = None
        self._download_path: Optional[Path] = None
        self._check_thread: Optional[QThread] = None
        self._check_worker: Optional[_CheckWorker] = None
        self._dl_thread: Optional[QThread] = None
        self._dl_worker: Optional[_DownloadWorker] = None

    # ----- check ------------------------------------------------------------

    def check_for_updates(self) -> None:
        self._check_worker = _CheckWorker()
        self._check_thread = QThread(self)
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_check_done)
        self._check_worker.error.connect(self._on_check_error)
        self._check_thread.start()

    def _on_check_done(self, info: ReleaseInfo) -> None:
        self._release = info
        if self._check_thread is not None:
            self._check_thread.quit()
            self._check_thread.wait(1500)
            self._check_thread = None
            self._check_worker = None
        if is_newer(info.version, self._current):
            self.update_available.emit(info.version, info.changelog)
        else:
            self.no_update.emit()

    def _on_check_error(self, message: str) -> None:
        self.update_error.emit(message)
        if self._check_thread is not None:
            self._check_thread.quit()
            self._check_thread.wait(1500)
            self._check_thread = None
            self._check_worker = None

    # ----- download ---------------------------------------------------------

    def download_update(self) -> None:
        if self._release is None or not self._release.asset_url:
            self.update_error.emit("No downloadable asset for this platform.")
            return
        dest = Path(tempfile.gettempdir()) / "openforge-updates" / (
            self._release.asset_name or "openforge-update.bin"
        )
        self._dl_worker = _DownloadWorker(self._release.asset_url, dest)
        self._dl_thread = QThread(self)
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.progress.connect(self.download_progress.emit)
        self._dl_worker.finished.connect(self._on_download_done)
        self._dl_worker.error.connect(self._on_download_error)
        self._dl_thread.start()

    def _on_download_done(self, path: str) -> None:
        self._download_path = Path(path)
        if self._dl_thread is not None:
            self._dl_thread.quit()
            self._dl_thread.wait(1500)
            self._dl_thread = None
            self._dl_worker = None
        self.update_downloaded.emit(path)

    def _on_download_error(self, message: str) -> None:
        if self._dl_thread is not None:
            self._dl_thread.quit()
            self._dl_thread.wait(1500)
            self._dl_thread = None
            self._dl_worker = None
        self.update_error.emit(message)

    def cancel_download(self) -> None:
        if self._dl_worker is not None:
            self._dl_worker.cancel()

    # ----- install ----------------------------------------------------------

    def install_update(self) -> None:
        if self._download_path is None or not self._download_path.exists():
            self.update_error.emit("No downloaded update to install.")
            return
        path = str(self._download_path)
        try:
            sysname = platform.system().lower()
            if sysname.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sysname == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self.update_error.emit(f"Failed to launch installer: {exc}")


# ---------------------------------------------------------------------------
# Update dialog
# ---------------------------------------------------------------------------


class UpdateDialog(QDialog):
    """Shown when an update is available."""

    def __init__(self, version: str, changelog: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"OpenForge Update — v{version}")
        self.resize(560, 480)
        self._version = version
        self._changelog = changelog
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        icon_row = QHBoxLayout()
        icon = QLabel("⬆️")
        icon.setStyleSheet("font-size: 36px;")
        icon_row.addWidget(icon)
        title_block = QVBoxLayout()
        title = QLabel(f"OpenForge {self._version} is available")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #cdd6f4;")
        sub = QLabel("A newer version has been released. Review the changes below.")
        sub.setStyleSheet("color: #9399b2; font-size: 12px;")
        title_block.addWidget(title)
        title_block.addWidget(sub)
        icon_row.addLayout(title_block)
        icon_row.addStretch(1)
        layout.addLayout(icon_row)

        self._changelog_view = QTextBrowser()
        self._changelog_view.setOpenExternalLinks(True)
        self._changelog_view.setMarkdown(self._changelog or "_(no changelog provided)_")
        self._changelog_view.setStyleSheet(
            "QTextBrowser { background: #181825; color: #cdd6f4; "
            "border: 1px solid #313244; border-radius: 8px; padding: 10px; }"
        )
        layout.addWidget(self._changelog_view, stretch=1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        footer = QHBoxLayout()
        layout.addLayout(footer)
        skip = QPushButton("Skip This Version")
        skip.clicked.connect(self.reject)
        footer.addWidget(skip)
        footer.addStretch(1)
        self._later_btn = QPushButton("Remind Me Later")
        self._later_btn.clicked.connect(self.reject)
        footer.addWidget(self._later_btn)
        self._install_btn = QPushButton("Download && Install")
        self._install_btn.setDefault(True)
        self._install_btn.clicked.connect(self.accept)
        footer.addWidget(self._install_btn)

        self.setStyleSheet(
            """
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QPushButton {
                background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                border-radius: 6px; padding: 6px 14px;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton:default { background: #89b4fa; color: #1e1e2e; border: none; }
            QProgressBar {
                background: #313244; border: none; border-radius: 4px; height: 8px;
            }
            QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
            """
        )

    def set_progress(self, downloaded: int, total: int) -> None:
        self._progress.setVisible(True)
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(downloaded)
        else:
            self._progress.setRange(0, 0)

    def set_installing(self) -> None:
        self._install_btn.setText("Installing...")
        self._install_btn.setEnabled(False)
        self._later_btn.setEnabled(False)


# ---------------------------------------------------------------------------
# Core-backed helper (Phase 7)
# ---------------------------------------------------------------------------
def check_via_core(current_version: str = "0.0.0", repo: str = "openforge/openforge"):
    """Convenience wrapper around openforge.setup.Updater.

    Returns an UpdateInfo or None on failure. Used by menu items that want
    a quick, synchronous check without spinning up the full dialog.
    """
    try:
        from openforge.setup.updater import Updater
        return Updater(repo=repo, current_version=current_version).check_for_updates()
    except Exception:  # noqa: BLE001
        return None
