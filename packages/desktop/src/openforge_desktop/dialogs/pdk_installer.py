"""PDK download and install wizard.

Lists the open-source PDKs OpenForge supports, lets the user pick one, and
clones it via git in a worker thread. PDKs install to ~/.openforge/pdks/<name>.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QThread, QSize
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QFrame,
    QTextEdit,
    QMessageBox,
    QSizePolicy,
    QWidget,
)


# ---------------------------------------------------------------------------
# PDK catalogue
# ---------------------------------------------------------------------------


@dataclass
class PdkSource:
    name: str
    display_name: str
    foundry: str
    size_gb: float
    git_url: str
    target_dir: Path
    description: str = ""
    process: str = ""


def _pdk_root() -> Path:
    return Path.home() / ".openforge" / "pdks"


def builtin_pdks() -> list[PdkSource]:
    root = _pdk_root()
    return [
        PdkSource(
            name="sky130",
            display_name="SkyWater SKY130",
            foundry="SkyWater",
            size_gb=0.5,
            git_url="https://github.com/google/skywater-pdk.git",
            target_dir=root / "sky130",
            process="130nm CMOS",
            description=(
                "Open-source 130nm CMOS process from SkyWater Technology, "
                "released in collaboration with Google. The flagship PDK for "
                "open silicon."
            ),
        ),
        PdkSource(
            name="gf180mcu",
            display_name="GlobalFoundries 180MCU",
            foundry="GlobalFoundries",
            size_gb=0.8,
            git_url="https://github.com/google/gf180mcu-pdk.git",
            target_dir=root / "gf180mcu",
            process="180nm BCD",
            description=(
                "Open 180nm process suitable for analog/mixed-signal and high-"
                "voltage designs. Released by GlobalFoundries with Google."
            ),
        ),
        PdkSource(
            name="asap7",
            display_name="ASAP7",
            foundry="ASU / ARM",
            size_gb=1.0,
            git_url="https://github.com/The-OpenROAD-Project/asap7.git",
            target_dir=root / "asap7",
            process="7nm predictive",
            description=(
                "Predictive 7nm FinFET PDK developed by ASU and ARM. Used "
                "extensively for academic research."
            ),
        ),
        PdkSource(
            name="ihp-sg13g2",
            display_name="IHP SG13G2",
            foundry="IHP Microelectronics",
            size_gb=0.6,
            git_url="https://github.com/IHP-GmbH/IHP-Open-PDK.git",
            target_dir=root / "ihp-sg13g2",
            process="130nm SiGe BiCMOS",
            description=(
                "First fully open-source SiGe BiCMOS process. Includes "
                "high-frequency HBTs suitable for RF and millimetre-wave."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Worker that clones a PDK with git
# ---------------------------------------------------------------------------


class _CloneWorker(QObject):
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, pdk: PdkSource):
        super().__init__()
        self._pdk = pdk
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        target = self._pdk.target_dir
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                self.progress.emit(f"[skip] {target} already exists; pulling instead")
                cmd = ["git", "-C", str(target), "pull", "--ff-only"]
            else:
                cmd = [
                    "git", "clone", "--depth", "1", "--progress",
                    self._pdk.git_url, str(target),
                ]
            self.progress.emit("$ " + " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                if self._cancelled:
                    proc.terminate()
                    self.finished.emit(False, "Cancelled by user")
                    return
                self.progress.emit(line.rstrip())
            rc = proc.wait()
            if rc == 0:
                self.finished.emit(True, f"Installed to {target}")
            else:
                self.finished.emit(False, f"git exited with code {rc}")
        except FileNotFoundError:
            self.finished.emit(False, "git not found on PATH")
        except Exception as exc:
            self.finished.emit(False, f"Error: {exc}")


# ---------------------------------------------------------------------------
# PDK row item widget
# ---------------------------------------------------------------------------


class _PdkRow(QFrame):
    install_clicked = Signal(str)  # pdk name

    def __init__(self, pdk: PdkSource, installed: bool, parent=None):
        super().__init__(parent)
        self._pdk = pdk
        self.setObjectName("PdkRow")
        self.setMinimumHeight(110)
        self._installed = installed
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(self._pdk.display_name)
        title.setStyleSheet("color: #cdd6f4; font-size: 14px; font-weight: 700;")
        meta = QLabel(
            f"{self._pdk.foundry}  •  {self._pdk.process}  •  ~{self._pdk.size_gb:.1f} GB"
        )
        meta.setStyleSheet("color: #9399b2; font-size: 11px;")
        desc = QLabel(self._pdk.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #bac2de; font-size: 12px;")
        text_col.addWidget(title)
        text_col.addWidget(meta)
        text_col.addWidget(desc)
        layout.addLayout(text_col, stretch=1)

        self._install_btn = QPushButton(
            "Reinstall" if self._installed else "Install"
        )
        self._install_btn.setFixedWidth(110)
        self._install_btn.clicked.connect(
            lambda: self.install_clicked.emit(self._pdk.name)
        )
        layout.addWidget(self._install_btn)

        self.setStyleSheet(
            """
            QFrame#PdkRow {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QFrame#PdkRow:hover { border: 1px solid #585b70; }
            QPushButton {
                background: #89b4fa; color: #1e1e2e; border: none;
                border-radius: 6px; padding: 6px 14px; font-weight: 600;
            }
            QPushButton:hover { background: #b4befe; }
            QPushButton:disabled { background: #45475a; color: #9399b2; }
            """
        )

    def set_busy(self, busy: bool) -> None:
        self._install_btn.setEnabled(not busy)
        if busy:
            self._install_btn.setText("Installing...")
        else:
            self._install_btn.setText("Reinstall" if self._installed else "Install")


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class PdkInstallerDialog(QDialog):
    """Wizard for installing PDKs into ~/.openforge/pdks."""

    pdk_installed = Signal(str)  # pdk name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDK Installer")
        self.resize(720, 580)
        self._pdks = builtin_pdks()
        self._rows: dict[str, _PdkRow] = {}
        self._worker: Optional[_CloneWorker] = None
        self._thread: Optional[QThread] = None
        self._active: Optional[str] = None
        self._build_ui()

    # ----- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        title = QLabel("Install Process Design Kits")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #cdd6f4;")
        layout.addWidget(title)

        sub = QLabel(
            "PDKs are downloaded with git and installed under "
            "<code>~/.openforge/pdks/</code>. Make sure git is on your PATH."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #9399b2; font-size: 12px;")
        sub.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(sub)

        rows_container = QWidget()
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(10)
        for pdk in self._pdks:
            installed = pdk.target_dir.exists()
            row = _PdkRow(pdk, installed)
            row.install_clicked.connect(self._start_install)
            rows_layout.addWidget(row)
            self._rows[pdk.name] = row
        layout.addWidget(rows_container)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(140)
        self._log.setStyleSheet(
            "QTextEdit { background: #11111b; color: #cdd6f4; "
            "border: 1px solid #313244; font-family: Consolas, monospace; font-size: 11px; }"
        )
        layout.addWidget(self._log, stretch=1)

        footer = QHBoxLayout()
        layout.addLayout(footer)
        footer.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel)
        footer.addWidget(self._cancel_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)

        self.setStyleSheet(
            """
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QPushButton {
                background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                border-radius: 6px; padding: 6px 14px;
            }
            QPushButton:hover { background: #45475a; }
            QProgressBar {
                background: #313244; border: none; border-radius: 4px; height: 8px;
            }
            QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
            """
        )

    # ----- install lifecycle ------------------------------------------------

    def _start_install(self, name: str) -> None:
        if self._worker is not None:
            QMessageBox.warning(
                self, "Busy", "Another install is already running. Wait or cancel it first."
            )
            return
        pdk = next((p for p in self._pdks if p.name == name), None)
        if pdk is None:
            return
        self._active = name
        self._rows[name].set_busy(True)
        self._cancel_btn.setEnabled(True)
        self._progress.setVisible(True)
        self._log.clear()
        self._log.append(f"[install] {pdk.display_name} → {pdk.target_dir}")

        self._worker = _CloneWorker(pdk)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._log.append)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, ok: bool, message: str) -> None:
        self._log.append("")
        self._log.append(f"[done] {message}")
        if self._active is not None:
            self._rows[self._active].set_busy(False)
            if ok:
                self.pdk_installed.emit(self._active)
        self._active = None
        self._cancel_btn.setEnabled(False)
        self._progress.setVisible(False)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
            self._worker = None

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._log.append("[cancel] requested")

    def closeEvent(self, event):
        self._cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
