"""First-run setup wizard for OpenForge.

Shown once on first launch to detect tools, install PDKs, pick a default
workspace, and explain opt-in telemetry. Writes ``~/.openforge/settings.json``
and a ``~/.openforge/setup_complete`` marker file.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

logger = logging.getLogger(__name__)

try:
    from openforge.setup.tool_installer import KNOWN_TOOLS, ToolInstaller
except Exception:  # noqa: BLE001
    KNOWN_TOOLS = {}  # type: ignore[assignment]
    ToolInstaller = None  # type: ignore[assignment,misc]


# ------------------------------------------------------------------
# Settings path
# ------------------------------------------------------------------
def _settings_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "OpenForge"
    return Path.home() / ".openforge"


def _settings_file() -> Path:
    return _settings_dir() / "settings.json"


def _marker_file() -> Path:
    return _settings_dir() / "setup_complete"


def setup_complete() -> bool:
    return _marker_file().exists()


def mark_setup_complete() -> None:
    d = _settings_dir()
    d.mkdir(parents=True, exist_ok=True)
    _marker_file().write_text("1\n", encoding="utf-8")


def save_settings(data: dict) -> None:
    d = _settings_dir()
    d.mkdir(parents=True, exist_ok=True)
    _settings_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_settings() -> dict:
    f = _settings_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------
class _WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Welcome to OpenForge EDA")
        self.setSubTitle("Open-source silicon design, from RTL to GDSII")
        lay = QVBoxLayout(self)
        logo = QLabel("OPENFORGE")
        f = QFont()
        f.setBold(True)
        f.setPointSize(28)
        logo.setFont(f)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        msg = QLabel(
            "Thanks for installing OpenForge. This short setup will:\n\n"
            "  - Scan your system for EDA tools\n"
            "  - Download the PDKs you need\n"
            "  - Let you pick a default workspace layout\n\n"
            "You can always re-run this wizard from Help > Welcome."
        )
        msg.setWordWrap(True)
        lay.addWidget(msg)
        lay.addStretch()


class _ToolDetectPage(QWizardPage):
    TOOLS = [
        "yosys", "nextpnr-ice40", "nextpnr-ecp5", "openroad",
        "magic", "netgen", "ngspice", "verilator", "iverilog",
        "klayout", "openfpgaloader", "icestorm", "prjtrellis",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Detect EDA Tools")
        self.setSubTitle("We'll scan PATH for each tool. Missing tools can be installed later.")
        lay = QVBoxLayout(self)

        self.table = QTableWidget(len(self.TOOLS), 4)
        self.table.setHorizontalHeaderLabels(["Tool", "Status", "Version", "Path"])
        hh = self.table.horizontalHeader()
        if hh:
            hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)

        for i, name in enumerate(self.TOOLS):
            self.table.setItem(i, 0, QTableWidgetItem(name))
            self.table.setItem(i, 1, QTableWidgetItem("-"))
            self.table.setItem(i, 2, QTableWidgetItem("-"))
            self.table.setItem(i, 3, QTableWidgetItem("-"))

        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.clicked.connect(self._rescan)
        btn_row.addWidget(self.btn_rescan)
        self.btn_browse = QPushButton("Set Path for Selected...")
        self.btn_browse.clicked.connect(self._browse_selected)
        btn_row.addWidget(self.btn_browse)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self.wsl_label = QLabel()
        lay.addWidget(self.wsl_label)

    def initializePage(self) -> None:
        self._rescan()
        if sys.platform.startswith("win"):
            import shutil
            if shutil.which("wsl.exe"):
                self.wsl_label.setText("WSL2 detected - Linux EDA tools can run through it.")
            else:
                self.wsl_label.setText("WSL2 not found. Run: wsl --install -d Ubuntu-24.04")

    def _rescan(self) -> None:
        if ToolInstaller is None:
            return
        installer = ToolInstaller()
        for i, name in enumerate(self.TOOLS):
            path = installer.detect(name)
            version = installer.get_version(name) or "-"
            self.table.item(i, 1).setText("found" if path else "missing")
            self.table.item(i, 2).setText(version)
            self.table.item(i, 3).setText(path or "-")

    def _browse_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.TOOLS[row]
        path, _ = QFileDialog.getOpenFileName(self, f"Binary for {name}")
        if path and ToolInstaller is not None:
            ToolInstaller().set_user_path(name, path)
            self._rescan()


class _PDKPage(QWizardPage):
    PDKS = [
        ("sky130A", "SkyWater 130nm (high density)", 900, True),
        ("sky130B", "SkyWater 130nm (with MIM cap)", 900, False),
        ("gf180mcuC", "GlobalFoundries 180nm MCU", 1400, False),
        ("asap7", "ASAP7 7nm predictive", 300, False),
        ("ihp_sg13g2", "IHP SG13G2 130nm BiCMOS", 600, False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Select PDKs")
        self.setSubTitle("Pick which process design kits to download. sky130A is recommended.")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        for pdk, desc, size, default in self.PDKS:
            item = QListWidgetItem(f"{pdk}  -  {desc}  (~{size} MB)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if default else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, pdk)
            self.list.addItem(item)
        lay.addWidget(self.list)

    def selected_pdks(self) -> list[str]:
        out: list[str] = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out


class _InstallPage(QWizardPage):
    def __init__(self, pdk_page: _PDKPage) -> None:
        super().__init__()
        self._pdk_page = pdk_page
        self.setTitle("Install PDKs")
        self.setSubTitle("Downloading selected PDKs. You can skip and install later.")
        lay = QVBoxLayout(self)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        lay.addWidget(self.progress)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)
        self._worker: _PdkInstallWorker | None = None
        self._done = False

    def isComplete(self) -> bool:  # noqa: N802
        return self._done

    def initializePage(self) -> None:
        pdks = self._pdk_page.selected_pdks()
        if not pdks:
            self.log.append("No PDKs selected - skipping.")
            self._done = True
            self.completeChanged.emit()
            return
        self.log.append(f"Installing: {', '.join(pdks)}")
        self._worker = _PdkInstallWorker(pdks)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self.log.append)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, frac: float) -> None:
        self.progress.setValue(int(frac * 100))

    def _on_done(self) -> None:
        self._done = True
        self.progress.setValue(100)
        self.log.append("PDK installation finished.")
        self.completeChanged.emit()


class _PdkInstallWorker(QThread):
    progress = Signal(float)
    log = Signal(str)
    done = Signal()

    def __init__(self, pdks: list[str]) -> None:
        super().__init__()
        self._pdks = pdks

    def run(self) -> None:  # noqa: D401
        try:
            from openforge.pdk.manager import PdkManager  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"pdk.manager unavailable: {exc}")
            self.done.emit()
            return
        try:
            mgr = PdkManager()
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"PdkManager init failed: {exc}")
            self.done.emit()
            return
        total = len(self._pdks) or 1
        for i, pdk in enumerate(self._pdks):
            self.log.emit(f"-> {pdk}")
            try:
                if hasattr(mgr, "install"):
                    mgr.install(pdk)
                elif hasattr(mgr, "download"):
                    mgr.download(pdk)
            except Exception as exc:  # noqa: BLE001
                self.log.emit(f"   failed: {exc}")
            self.progress.emit((i + 1) / total)
        self.done.emit()


class _ToolBundlerPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Install Missing Tools (optional)")
        self.setSubTitle("Offer to install any EDA tools that weren't found on PATH.")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        lay.addWidget(self.list)

        if sys.platform.startswith("win"):
            self.wsl_box = QCheckBox("Also set up WSL2 Ubuntu + install Linux tools there")
            lay.addWidget(self.wsl_box)
        else:
            self.wsl_box = None

        note = QLabel(
            "Tools are installed via your native package manager (apt / winget / brew / scoop) "
            "when available, else downloaded from GitHub releases."
        )
        note.setWordWrap(True)
        lay.addWidget(note)

    def initializePage(self) -> None:
        self.list.clear()
        if ToolInstaller is None:
            return
        installer = ToolInstaller()
        for name in _ToolDetectPage.TOOLS:
            path = installer.detect(name)
            if path is None:
                item = QListWidgetItem(f"{name}")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.list.addItem(item)

    def selected(self) -> list[str]:
        out: list[str] = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out


class _WorkspacePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Workspace Defaults")
        self.setSubTitle("Pick your preferred project location, PDK, theme, and layout.")
        form = QFormLayout(self)

        self.project_dir = QLineEdit(str(Path.home() / "OpenForgeProjects"))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.project_dir)
        row.addWidget(browse)
        form.addRow("Project folder:", row)

        self.default_pdk = QComboBox()
        self.default_pdk.addItems(["sky130A", "sky130B", "gf180mcuC", "asap7", "ihp_sg13g2"])
        form.addRow("Default PDK:", self.default_pdk)

        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        form.addRow("Theme:", self.theme)

        self.layout_cb = QComboBox()
        self.layout_cb.addItems(["Default", "FPGA", "ASIC", "PCB", "Verification"])
        form.addRow("Default layout:", self.layout_cb)

        self.telemetry = QCheckBox("Share anonymous usage data to help improve OpenForge")
        self.telemetry.setChecked(False)
        form.addRow("", self.telemetry)

        priv = QLabel(
            "Telemetry (opt-in): we only collect which panels were used, which flows were run, "
            "error categories, and performance timings. Never paths, file contents, or project names."
        )
        priv.setWordWrap(True)
        priv.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", priv)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Project folder", self.project_dir.text())
        if d:
            self.project_dir.setText(d)


class _DonePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("You're All Set")
        self.setSubTitle("OpenForge is ready. Click Finish to open the main window.")
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        lay = QVBoxLayout(self)
        lay.addWidget(self.summary)

    def set_summary(self, text: str) -> None:
        self.summary.setPlainText(text)


# ------------------------------------------------------------------
# Wizard
# ------------------------------------------------------------------
class FirstRunWizard(QWizard):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenForge Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(780, 560)

        self._welcome = _WelcomePage()
        self._detect = _ToolDetectPage()
        self._pdks = _PDKPage()
        self._install = _InstallPage(self._pdks)
        self._bundler = _ToolBundlerPage()
        self._workspace = _WorkspacePage()
        self._done = _DonePage()

        for p in (
            self._welcome, self._detect, self._pdks, self._install,
            self._bundler, self._workspace, self._done,
        ):
            self.addPage(p)

        self.currentIdChanged.connect(self._on_page_change)

    def _on_page_change(self, page_id: int) -> None:
        if self.page(page_id) is self._done:
            pdks = self._pdks.selected_pdks()
            self._done.set_summary(
                "Summary:\n"
                f"  Project folder : {self._workspace.project_dir.text()}\n"
                f"  Default PDK    : {self._workspace.default_pdk.currentText()}\n"
                f"  PDKs installed : {', '.join(pdks) or '(none)'}\n"
                f"  Theme          : {self._workspace.theme.currentText()}\n"
                f"  Layout         : {self._workspace.layout_cb.currentText()}\n"
                f"  Telemetry      : {'on' if self._workspace.telemetry.isChecked() else 'off'}\n"
            )

    # ------------------------------------------------------------------
    def accept(self) -> None:  # noqa: D401
        settings = {
            "project_dir": self._workspace.project_dir.text(),
            "default_pdk": self._workspace.default_pdk.currentText(),
            "installed_pdks": self._pdks.selected_pdks(),
            "theme": self._workspace.theme.currentText(),
            "layout": self._workspace.layout_cb.currentText(),
            "telemetry_enabled": self._workspace.telemetry.isChecked(),
        }
        save_settings(settings)
        mark_setup_complete()

        # Kick off post-wizard tool installs (fire-and-forget).
        to_install = self._bundler.selected()
        if to_install and ToolInstaller is not None:
            try:
                installer = ToolInstaller()
                for name in to_install:
                    try:
                        installer.install(name)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("tool install failed for %s: %s", name, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tool installer unavailable: %s", exc)

        # Configure telemetry now that user has chosen.
        try:
            from openforge.telemetry import get_client
            get_client().set_enabled(settings["telemetry_enabled"])
        except Exception:  # noqa: BLE001
            pass

        super().accept()
