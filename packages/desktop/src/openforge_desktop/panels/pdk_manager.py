"""PDK Manager panel.

Card-grid PDK browser with Install / Uninstall / Verify / Set Active
actions backed by :class:`openforge.pdk.installer.PdkInstaller`
(volare + git).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.pdk.installer import PdkInfo, PdkInstaller
except Exception:  # pragma: no cover
    PdkInfo = None  # type: ignore[assignment]
    PdkInstaller = None  # type: ignore[assignment]


# design_system dark palette
_BG = "#11131a"
_SURFACE = "#1b1e27"
_PANEL = "#232734"
_TEXT = "#e5e9f0"
_MUTED = "#8a93a6"
_ACCENT = "#7aa2f7"
_GREEN = "#9ece6a"
_RED = "#f7768e"
_YELLOW = "#e0af68"


class _InstallWorker(QObject):
    progress = Signal(str, float)
    finished = Signal(str, bool, str)

    def __init__(self, installer: "PdkInstaller", pdk_name: str) -> None:
        super().__init__()
        self._installer = installer
        self._pdk = pdk_name

    def run(self) -> None:
        try:
            path = self._installer.install(
                self._pdk,
                progress_callback=lambda m, f: self.progress.emit(m, f),
            )
            self.finished.emit(self._pdk, True, str(path))
        except Exception as exc:
            self.finished.emit(self._pdk, False, str(exc))


class _PdkCard(QFrame):
    """A single PDK card in the grid."""

    install_requested = Signal(str)
    uninstall_requested = Signal(str)
    verify_requested = Signal(str)
    set_active_requested = Signal(str)
    selected = Signal(str)

    def __init__(self, info: "PdkInfo", installed: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.info = info
        self._installed = installed
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(260)
        self.setMaximumWidth(340)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)

        # Header: logo placeholder + foundry
        hdr = QHBoxLayout()
        logo = QLabel("[FAB]")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"background: {_PANEL}; color: {_ACCENT}; border-radius: 4px; font-weight: bold;"
        )
        hdr.addWidget(logo)
        title_box = QVBoxLayout()
        title = QLabel(info.name)
        title.setStyleSheet(f"font-size: 14pt; font-weight: 600; color: {_TEXT};")
        sub = QLabel(f"{info.foundry} -- {info.node_nm} nm")
        sub.setStyleSheet(f"color: {_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        hdr.addLayout(title_box, 1)
        lay.addLayout(hdr)

        lay.addWidget(QLabel(f"Version: {info.version}"))
        lay.addWidget(QLabel(f"License: {info.license}"))

        self._badge = QLabel("Installed" if installed else "Not Installed")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(self._badge_style(installed))
        lay.addWidget(self._badge)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._btn_primary = QPushButton("Uninstall" if installed else "Install")
        self._btn_primary.clicked.connect(self._on_primary)
        btn_row.addWidget(self._btn_primary)
        self._btn_verify = QPushButton("Verify")
        self._btn_verify.clicked.connect(lambda: self.verify_requested.emit(info.name))
        btn_row.addWidget(self._btn_verify)
        lay.addLayout(btn_row)

        self._btn_active = QPushButton("Set Active")
        self._btn_active.setEnabled(installed)
        self._btn_active.clicked.connect(lambda: self.set_active_requested.emit(info.name))
        lay.addWidget(self._btn_active)

        self.setStyleSheet(
            f"""
            _PdkCard, QFrame {{
                background: {_SURFACE};
                border: 1px solid {_PANEL};
                border-radius: 6px;
            }}
            QLabel {{ background: transparent; color: {_TEXT}; }}
            QPushButton {{
                background: {_PANEL};
                color: {_TEXT};
                border: 1px solid {_PANEL};
                border-radius: 4px;
                padding: 5px 10px;
            }}
            QPushButton:hover {{ background: {_ACCENT}; color: {_BG}; }}
            QPushButton:disabled {{ color: {_MUTED}; }}
            QProgressBar {{
                background: {_PANEL};
                color: {_TEXT};
                border: 1px solid {_PANEL};
                border-radius: 3px;
                text-align: center;
            }}
            QProgressBar::chunk {{ background: {_GREEN}; }}
            """
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _badge_style(installed: bool) -> str:
        color = _GREEN if installed else _RED
        return (
            f"background: {_PANEL}; color: {color}; padding: 4px; "
            f"border-radius: 3px; font-weight: 600;"
        )

    def mousePressEvent(self, event) -> None:  # noqa: D401,N802
        self.selected.emit(self.info.name)
        super().mousePressEvent(event)

    def _on_primary(self) -> None:
        if self._installed:
            self.uninstall_requested.emit(self.info.name)
        else:
            self.install_requested.emit(self.info.name)

    def set_installed(self, installed: bool) -> None:
        self._installed = installed
        self._badge.setText("Installed" if installed else "Not Installed")
        self._badge.setStyleSheet(self._badge_style(installed))
        self._btn_primary.setText("Uninstall" if installed else "Install")
        self._btn_active.setEnabled(installed)
        self._progress.setVisible(False)

    def set_progress(self, frac: float, msg: str) -> None:
        self._progress.setVisible(True)
        self._progress.setValue(int(max(0.0, min(1.0, frac)) * 100))
        self._progress.setFormat(msg[:40])


class PdkManagerPanel(QWidget):
    """Card-grid PDK browser + detail pane."""

    pdk_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        if PdkInstaller is None:
            self._installer = None
        else:
            self._installer = PdkInstaller()

        self._cards: dict[str, _PdkCard] = {}
        self._workers: dict[str, tuple[QThread, _InstallWorker]] = {}
        self._active: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        self._lbl_active = QLabel("Active PDK: (none)")
        self._lbl_active.setStyleSheet(f"color: {_ACCENT}; font-weight: 600;")
        header.addWidget(self._lbl_active)
        header.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Card grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        grid_host = QWidget()
        self._grid = QGridLayout(grid_host)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(10)
        scroll.setWidget(grid_host)
        splitter.addWidget(scroll)

        # Detail pane
        detail_host = QWidget()
        dl = QVBoxLayout(detail_host)
        self._lbl_detail_title = QLabel("Select a PDK")
        self._lbl_detail_title.setStyleSheet(
            f"font-size: 14pt; font-weight: 600; color: {_ACCENT};"
        )
        dl.addWidget(self._lbl_detail_title)
        self._lbl_detail_meta = QLabel("")
        self._lbl_detail_meta.setWordWrap(True)
        self._lbl_detail_meta.setStyleSheet(f"color: {_TEXT};")
        dl.addWidget(self._lbl_detail_meta)

        dl.addWidget(QLabel("Cell libraries / tech files:"))
        self._list_libs = QListWidget()
        dl.addWidget(self._list_libs, 1)
        splitter.addWidget(detail_host)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {_MUTED};")
        root.addWidget(self._status)

        self._apply_theme()
        self.refresh()

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{ background: {_BG}; color: {_TEXT}; }}
            QScrollArea {{ background: {_BG}; border: none; }}
            QListWidget {{
                background: {_SURFACE};
                color: {_TEXT};
                border: 1px solid {_PANEL};
            }}
            QPushButton {{
                background: {_PANEL};
                color: {_TEXT};
                border: 1px solid {_PANEL};
                border-radius: 4px;
                padding: 5px 12px;
            }}
            QPushButton:hover {{ background: {_ACCENT}; color: {_BG}; }}
            """
        )

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        # Clear grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._cards.clear()

        if self._installer is None:
            self._status.setText("openforge.pdk.installer not available")
            return

        installed_names = {p.name for p in self._installer.list_installed()}
        known = self._installer.list_known()
        cols = 2
        for idx, info in enumerate(known):
            card = _PdkCard(info, installed=info.name in installed_names, parent=self)
            card.install_requested.connect(self._on_install)
            card.uninstall_requested.connect(self._on_uninstall)
            card.verify_requested.connect(self._on_verify)
            card.set_active_requested.connect(self._on_set_active)
            card.selected.connect(self._on_select)
            r, c = divmod(idx, cols)
            self._grid.addWidget(card, r, c)
            self._cards[info.name] = card
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    # ------------------------------------------------------------------
    def _on_select(self, name: str) -> None:
        if self._installer is None:
            return
        info = self._installer.KNOWN_PDKS.get(name)
        if info is None:
            return
        self._lbl_detail_title.setText(info.name)
        self._lbl_detail_meta.setText(
            f"Foundry: {info.foundry}\n"
            f"Vendor: {info.vendor}\n"
            f"Version: {info.version}\n"
            f"Node: {info.node_nm} nm\n"
            f"License: {info.license}\n"
            f"Source: {info.sources_url}\n"
            f"Installer: {info.installer}"
        )
        self._list_libs.clear()
        for lib in info.supported_libs:
            self._list_libs.addItem(lib)

    def _on_install(self, name: str) -> None:
        if self._installer is None or name in self._workers:
            return
        card = self._cards.get(name)
        if card is not None:
            card.set_progress(0.0, "starting...")
        thread = QThread(self)
        worker = _InstallWorker(self._installer, name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda m, f, n=name: self._on_progress(n, m, f))
        worker.finished.connect(self._on_install_finished)
        worker.finished.connect(thread.quit)
        self._workers[name] = (thread, worker)
        self._status.setText(f"Installing {name}...")
        thread.start()

    def _on_progress(self, name: str, msg: str, frac: float) -> None:
        card = self._cards.get(name)
        if card is not None:
            card.set_progress(frac, msg)
        self._status.setText(f"{name}: {msg}")

    def _on_install_finished(self, name: str, ok: bool, detail: str) -> None:
        entry = self._workers.pop(name, None)
        if entry is not None:
            thread, _ = entry
            thread.wait(1500)
        if ok:
            self._status.setText(f"Installed {name} -> {detail}")
        else:
            self._status.setText(f"Install failed: {name}: {detail}")
            QMessageBox.warning(self, "PDK Install Failed", f"{name}: {detail}")
        self.refresh()

    def _on_uninstall(self, name: str) -> None:
        if self._installer is None:
            return
        ok = self._installer.uninstall(name)
        self._status.setText(
            f"Uninstalled {name}" if ok else f"Could not uninstall {name}"
        )
        self.refresh()

    def _on_verify(self, name: str) -> None:
        if self._installer is None:
            return
        missing = self._installer.verify(name)
        if not missing:
            QMessageBox.information(self, "Verify", f"{name}: OK")
        else:
            QMessageBox.warning(self, "Verify", f"{name} issues:\n" + "\n".join(missing))

    def _on_set_active(self, name: str) -> None:
        self._active = name
        self._lbl_active.setText(f"Active PDK: {name}")
        self._status.setText(f"Active PDK set to {name}")
        self.pdk_changed.emit(name)
