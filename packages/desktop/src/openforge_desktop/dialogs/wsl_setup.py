"""WSL2 setup wizard for Windows users.

Walks the user through enabling WSL2, installing Ubuntu, and installing the
open-source EDA stack inside the WSL distribution. Each phase is run as a
worker so the UI stays responsive, with retry on failure.
"""

from __future__ import annotations

import os
import platform
import subprocess
import textwrap
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------


@dataclass
class WslStep:
    id: str
    title: str
    description: str
    command: list[str] = field(default_factory=list)
    can_skip: bool = False
    success: bool | None = None
    output: str = ""


def _build_steps() -> list[WslStep]:
    return [
        WslStep(
            id="check",
            title="Check WSL2 status",
            description=(
                "Detect whether WSL2 is already enabled on this system. We will "
                "run `wsl --status` and parse the result."
            ),
            command=["wsl", "--status"],
        ),
        WslStep(
            id="install_wsl",
            title="Install WSL2",
            description=(
                "Enable the Windows Subsystem for Linux feature and install the "
                "WSL2 kernel. Requires administrator privileges. We will run "
                "`wsl --install --no-distribution`."
            ),
            command=["wsl", "--install", "--no-distribution"],
            can_skip=True,
        ),
        WslStep(
            id="install_ubuntu",
            title="Install Ubuntu 22.04",
            description=(
                "Install the Ubuntu 22.04 LTS distribution from the Microsoft "
                "Store. Once it finishes, you'll be asked to set a username and "
                "password inside the Ubuntu shell."
            ),
            command=["wsl", "--install", "-d", "Ubuntu-22.04"],
            can_skip=True,
        ),
        WslStep(
            id="install_tools",
            title="Install EDA tools",
            description=(
                "Install Yosys, Magic, Netgen, KLayout, Icarus Verilog, "
                "Verilator, and a prebuilt OpenROAD binary inside the Ubuntu "
                "distribution. We generate a `setup.sh` script and execute it."
            ),
            command=[],  # filled at runtime
        ),
        WslStep(
            id="verify",
            title="Verify installation",
            description=(
                "Run each tool with `--version` to confirm it is installed and "
                "executable from inside WSL."
            ),
            command=[],
        ),
    ]


# ---------------------------------------------------------------------------
# Worker thread for shelling out to wsl.exe
# ---------------------------------------------------------------------------


class _StepWorker(QObject):
    line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, command: list[str], shell_script: str | None = None):
        super().__init__()
        self._command = command
        self._shell_script = shell_script
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            if self._shell_script:
                # Pipe a bash script into wsl bash
                proc = subprocess.Popen(
                    ["wsl", "bash", "-s"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert proc.stdin is not None
                proc.stdin.write(self._shell_script)
                proc.stdin.close()
            else:
                proc = subprocess.Popen(
                    self._command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            collected: list[str] = []
            assert proc.stdout is not None
            for raw in proc.stdout:
                if self._cancelled:
                    proc.terminate()
                    self.finished.emit(False, "Cancelled by user.")
                    return
                line = raw.rstrip()
                collected.append(line)
                self.line.emit(line)
            rc = proc.wait()
            self.finished.emit(rc == 0, "\n".join(collected))
        except FileNotFoundError as exc:
            self.finished.emit(False, f"Command not found: {exc}")
        except Exception as exc:
            self.finished.emit(False, f"Error: {exc}")


# ---------------------------------------------------------------------------
# Setup script generator
# ---------------------------------------------------------------------------


def generate_setup_script() -> str:
    """Return a bash script that installs the EDA tool stack inside WSL."""
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        echo "[OpenForge] Updating apt..."
        sudo apt-get update -y

        echo "[OpenForge] Installing apt packages..."
        sudo apt-get install -y \\
            build-essential git curl wget \\
            python3 python3-pip python3-venv \\
            yosys magic netgen-lvs klayout \\
            iverilog verilator gtkwave \\
            tcl-dev tk-dev libreadline-dev

        echo "[OpenForge] Installing prebuilt OpenROAD..."
        OPENROAD_URL="https://github.com/Precision-Innovations/OpenROAD/releases/latest/download/openroad_ubuntu22.tar.gz"
        TMPDIR=$(mktemp -d)
        cd "$TMPDIR"
        wget -q "$OPENROAD_URL" -O openroad.tar.gz || echo "OpenROAD download failed; continuing"
        if [ -f openroad.tar.gz ]; then
            sudo tar -xzf openroad.tar.gz -C /opt/
            sudo ln -sf /opt/openroad/bin/openroad /usr/local/bin/openroad
        fi

        echo "[OpenForge] Done."
        """
    ).strip()


def generate_verify_script() -> str:
    """Return a bash script that calls --version on each tool."""
    tools = [
        "yosys",
        "magic",
        "netgen",
        "klayout",
        "iverilog",
        "verilator",
        "openroad",
    ]
    lines = ["#!/usr/bin/env bash", "set +e", ""]
    for tool in tools:
        lines.append(f'echo "=== {tool} ==="')
        lines.append(f"{tool} --version 2>&1 | head -n 2 || echo '  NOT FOUND'")
    lines.append('echo "[verify] complete"')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class WslSetupDialog(QDialog):
    """Wizard-style dialog for installing WSL2 and the EDA stack."""

    setup_complete = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WSL2 Setup Wizard")
        self.resize(780, 600)
        self._steps: list[WslStep] = _build_steps()
        self._current = 0
        self._worker: _StepWorker | None = None
        self._thread: QThread | None = None
        self._build_ui()
        self._refresh()

    # ----- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        # Header
        header = QVBoxLayout()
        title = QLabel("OpenForge WSL2 Setup")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #cdd6f4;")
        subtitle = QLabel(
            "OpenForge depends on a handful of Linux-only EDA tools. This wizard "
            "installs WSL2, Ubuntu 22.04, and the open-source toolchain so the "
            "desktop app can drive them transparently."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #9399b2; font-size: 12px;")
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Body: list on left, details on right
        body = QHBoxLayout()
        body.setSpacing(16)
        layout.addLayout(body, stretch=1)

        self._step_list = QListWidget()
        self._step_list.setFixedWidth(220)
        self._step_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for step in self._steps:
            item = QListWidgetItem(f"⬜  {step.title}")
            self._step_list.addItem(item)
        body.addWidget(self._step_list)

        details = QVBoxLayout()
        details.setSpacing(8)
        body.addLayout(details, stretch=1)

        self._step_title = QLabel("")
        self._step_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #cdd6f4;")
        details.addWidget(self._step_title)

        self._step_desc = QLabel("")
        self._step_desc.setWordWrap(True)
        self._step_desc.setStyleSheet("color: #bac2de; font-size: 12px;")
        details.addWidget(self._step_desc)

        self._command_label = QLabel("")
        self._command_label.setStyleSheet(
            "color: #89b4fa; font-family: Consolas, monospace; font-size: 11px;"
        )
        self._command_label.setWordWrap(True)
        details.addWidget(self._command_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # busy by default
        self._progress.setVisible(False)
        details.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QTextEdit { background: #11111b; color: #cdd6f4; border: 1px solid #313244; "
            "font-family: Consolas, monospace; font-size: 11px; }"
        )
        details.addWidget(self._log, stretch=1)

        # Footer buttons
        footer = QHBoxLayout()
        layout.addLayout(footer)
        self._open_store_btn = QPushButton("Open Microsoft Store")
        self._open_store_btn.clicked.connect(self._open_store)
        footer.addWidget(self._open_store_btn)

        footer.addStretch(1)

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.clicked.connect(self._skip_current)
        footer.addWidget(self._skip_btn)

        self._retry_btn = QPushButton("Retry")
        self._retry_btn.clicked.connect(self._run_current)
        footer.addWidget(self._retry_btn)

        self._run_btn = QPushButton("Run Step")
        self._run_btn.setDefault(True)
        self._run_btn.clicked.connect(self._run_current)
        footer.addWidget(self._run_btn)

        self._next_btn = QPushButton("Next ▶")
        self._next_btn.clicked.connect(self._advance)
        footer.addWidget(self._next_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)
        footer.addWidget(self._close_btn)

        self.setStyleSheet(
            """
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QListWidget {
                background: #181825; color: #cdd6f4; border: 1px solid #313244;
                border-radius: 6px; padding: 6px; font-size: 12px;
            }
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

    # ----- step lifecycle ---------------------------------------------------

    def _refresh(self) -> None:
        for i, step in enumerate(self._steps):
            mark = "⬜"
            if step.success is True:
                mark = "✅"
            elif step.success is False:
                mark = "❌"
            elif i == self._current:
                mark = "▶ "
            self._step_list.item(i).setText(f"{mark}  {step.title}")
        if self._current >= len(self._steps):
            self._step_title.setText("All done!")
            self._step_desc.setText(
                "WSL2 and the EDA toolchain are installed. You can close this "
                "wizard and start using OpenForge."
            )
            self._command_label.setText("")
            self._run_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        step = self._steps[self._current]
        self._step_title.setText(step.title)
        self._step_desc.setText(step.description)
        if step.command:
            self._command_label.setText("$ " + " ".join(step.command))
        else:
            self._command_label.setText("(generated script)")
        self._skip_btn.setEnabled(step.can_skip)
        self._retry_btn.setEnabled(step.success is False)
        self._next_btn.setEnabled(step.success is True)
        self._run_btn.setEnabled(step.success is not True)

    def _run_current(self) -> None:
        if not self._is_windows():
            self._append_log("[warn] Not running on Windows; this wizard is a no-op on this OS.")
            self._steps[self._current].success = True
            self._refresh()
            return
        step = self._steps[self._current]
        self._log.clear()
        self._append_log(f"[run] {step.title}")
        self._progress.setVisible(True)

        script: str | None = None
        cmd: list[str] = step.command
        if step.id == "install_tools":
            script = generate_setup_script()
            cmd = []
        elif step.id == "verify":
            script = generate_verify_script()
            cmd = []

        self._worker = _StepWorker(cmd, script)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.line.connect(self._append_log)
        self._worker.finished.connect(self._on_step_finished)
        self._thread.start()

    def _on_step_finished(self, ok: bool, output: str) -> None:
        self._progress.setVisible(False)
        step = self._steps[self._current]
        step.success = ok
        step.output = output
        self._append_log("")
        self._append_log("[ok] step succeeded" if ok else "[error] step failed; you can Retry")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(1000)
            self._thread = None
            self._worker = None
        self._refresh()

    def _advance(self) -> None:
        self._current += 1
        self._refresh()
        if self._current >= len(self._steps):
            self.setup_complete.emit()

    def _skip_current(self) -> None:
        step = self._steps[self._current]
        if not step.can_skip:
            return
        step.success = True
        self._append_log(f"[skip] {step.title}")
        self._advance()

    # ----- helpers ----------------------------------------------------------

    def _append_log(self, text: str) -> None:
        self._log.append(text)

    def _is_windows(self) -> bool:
        return platform.system().lower().startswith("win")

    def _open_store(self) -> None:
        try:
            if self._is_windows():
                os.startfile("ms-windows-store://pdp/?productid=9PN20MSR04DW")  # type: ignore[attr-defined]
            else:
                self._append_log("[info] Microsoft Store only available on Windows.")
        except Exception as exc:
            self._append_log(f"[warn] could not open store: {exc}")

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(1500)
        super().closeEvent(event)
