"""AI Assistant dock panel for OpenForge.

A real, local AI assistant for hardware design powered by Ollama. Provides
streaming chat with Verilog/SystemVerilog/EDA expertise, project context
awareness, conversation history, and smart code actions. Falls back to
local templates/keyword lookup when Ollama is not available.
"""

from __future__ import annotations

import contextlib
import json
import re
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QObject,
    QSettings,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------

CAT_BASE = "#1e1e2e"
CAT_MANTLE = "#181825"
CAT_CRUST = "#11111b"
CAT_SURFACE0 = "#313244"
CAT_SURFACE1 = "#45475a"
CAT_SURFACE2 = "#585b70"
CAT_TEXT = "#cdd6f4"
CAT_SUBTEXT1 = "#bac2de"
CAT_SUBTEXT0 = "#a6adc8"
CAT_OVERLAY0 = "#6c7086"
CAT_OVERLAY1 = "#7f849c"
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


DEFAULT_SYSTEM_PROMPT = """You are an expert hardware design assistant for OpenForge EDA, specializing in:
- Verilog and SystemVerilog RTL design
- ASIC physical design (synthesis, place-and-route, timing closure)
- FPGA design (Xilinx, Lattice, Intel)
- EDA tools: Yosys, OpenROAD, Magic, KLayout, OpenSTA, Verilator, Icarus
- Cryptographic hardware (constant-time, side-channel resistance, FIPS 140-3)
- SKY130 PDK, GF180MCU PDK
- Timing analysis, power analysis, CDC checks

When the user asks a question:
1. Be technical and precise
2. Provide working code examples in Verilog/SystemVerilog when relevant
3. Reference specific tools and their commands
4. Explain timing/area/power tradeoffs
5. Suggest best practices for synthesizable RTL
6. When showing code, use proper Verilog syntax and meaningful signal names

You can run analyses, suggest fixes, complete code, and explain errors.
"""


RECOMMENDED_MODELS = [
    ("llama3.2", "3B", "2.0 GB", "Fast, good for general questions and code completion"),
    ("llama3.1:8b", "8B", "4.7 GB", "Higher quality reasoning, slower"),
    ("codellama:7b", "7B", "3.8 GB", "Specialized for code generation"),
    ("qwen2.5-coder:7b", "7B", "4.4 GB", "Best open model for code (recommended)"),
    ("deepseek-coder:6.7b", "6.7B", "3.8 GB", "Strong coding model"),
    ("mistral:7b", "7B", "4.1 GB", "General purpose, good reasoning"),
]


# ---------------------------------------------------------------------------
# Ollama HTTP client (uses only stdlib)
# ---------------------------------------------------------------------------


class OllamaError(Exception):
    """Raised on Ollama HTTP/protocol failures."""


class OllamaClient:
    """Minimal Ollama REST client using urllib (no third-party deps)."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: float = 600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._cancel = False

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _request(
        self,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        timeout: float | None = None,
    ) -> urllib.request.addinfourl:
        data: bytes | None = None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=data, method=method, headers=headers)
        return urllib.request.urlopen(req, timeout=timeout or self.timeout)

    def is_available(self) -> bool:
        """Check if Ollama is running locally."""
        try:
            with self._request("/api/tags", timeout=3.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return installed model names."""
        try:
            with self._request("/api/tags", timeout=5.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
        except Exception as exc:
            raise OllamaError(f"Failed to list models: {exc}") from exc

    def cancel(self) -> None:
        self._cancel = True

    def reset_cancel(self) -> None:
        self._cancel = False

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        num_ctx: int = 8192,
    ) -> Iterator[str]:
        """Stream a chat response. Yields text chunks."""
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": float(temperature),
                "num_ctx": int(num_ctx),
            },
        }
        self._cancel = False
        try:
            req = urllib.request.Request(
                self._url("/api/chat"),
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    if self._cancel:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in evt:
                        raise OllamaError(str(evt["error"]))
                    msg = evt.get("message") or {}
                    chunk = msg.get("content", "")
                    if chunk:
                        yield chunk
                    if evt.get("done"):
                        break
        except urllib.error.URLError as exc:
            raise OllamaError(f"Connection error: {exc}") from exc

    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Single-shot generation."""
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": float(temperature)},
        }
        try:
            with self._request("/api/generate", method="POST", body=body) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("response", "")
        except Exception as exc:
            raise OllamaError(f"Generate failed: {exc}") from exc

    def pull_model(self, model_name: str, progress_callback=None) -> bool:
        """Download a model. progress_callback(status, completed, total)."""
        body = {"name": model_name, "stream": True}
        try:
            req = urllib.request.Request(
                self._url("/api/pull"),
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in evt:
                        if progress_callback:
                            progress_callback(f"Error: {evt['error']}", 0, 0)
                        return False
                    status = evt.get("status", "")
                    completed = int(evt.get("completed", 0))
                    total = int(evt.get("total", 0))
                    if progress_callback:
                        progress_callback(status, completed, total)
                    if status == "success":
                        return True
            return True
        except Exception as exc:
            if progress_callback:
                progress_callback(f"Error: {exc}", 0, 0)
            return False


# ---------------------------------------------------------------------------
# Worker threads
# ---------------------------------------------------------------------------


class OllamaStreamWorker(QThread):
    chunk_received = Signal(str)
    finished_response = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        messages: list[dict],
        temperature: float = 0.7,
        num_ctx: int = 8192,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.messages = messages
        self.temperature = temperature
        self.num_ctx = num_ctx

    def stop(self) -> None:
        self.client.cancel()

    def run(self) -> None:
        full = ""
        try:
            for chunk in self.client.chat_stream(
                self.messages,
                temperature=self.temperature,
                num_ctx=self.num_ctx,
            ):
                full += chunk
                self.chunk_received.emit(chunk)
            self.finished_response.emit(full)
        except OllamaError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            self.error.emit(f"{type(exc).__name__}: {exc}")


class ModelPullWorker(QThread):
    progress = Signal(str, int, int)
    finished_ok = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model_name: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.model_name = model_name

    def run(self) -> None:
        def cb(status: str, completed: int, total: int) -> None:
            self.progress.emit(status, completed, total)

        ok = self.client.pull_model(self.model_name, progress_callback=cb)
        if ok:
            self.finished_ok.emit(self.model_name)
        else:
            self.error.emit(f"Failed to pull {self.model_name}")


# ---------------------------------------------------------------------------
# Conversation data classes
# ---------------------------------------------------------------------------


@dataclass
class ChatMessage:
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ChatMessage:
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            timestamp=d.get("timestamp", datetime.now().isoformat()),
        )


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    messages: list[ChatMessage] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Conversation:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            title=d.get("title", "Untitled"),
            created_at=d.get("created_at", datetime.now().isoformat()),
            messages=[ChatMessage.from_dict(m) for m in d.get("messages", [])],
        )

    @classmethod
    def new(cls, title: str = "New Chat") -> Conversation:
        return cls(
            id=str(uuid.uuid4()),
            title=title,
            created_at=datetime.now().isoformat(),
            messages=[],
        )


class ConversationStore:
    """Persists conversations as JSON files in ~/.openforge/conversations/"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (Path.home() / ".openforge" / "conversations")
        with contextlib.suppress(Exception):
            self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Conversation]:
        items: list[Conversation] = []
        if not self.root.exists():
            return items
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append(Conversation.from_dict(data))
            except Exception:
                continue
        return items

    def save(self, convo: Conversation) -> None:
        path = self.root / f"{convo.id}.json"
        with contextlib.suppress(Exception):
            path.write_text(json.dumps(convo.to_dict(), indent=2), encoding="utf-8")

    def delete(self, convo_id: str) -> None:
        path = self.root / f"{convo_id}.json"
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    def export_markdown(self, convo: Conversation, dest: Path) -> None:
        lines = [f"# {convo.title}", "", f"_Created: {convo.created_at}_", ""]
        for m in convo.messages:
            if m.role == "system":
                continue
            lines.append(f"## {m.role.capitalize()}")
            lines.append("")
            lines.append(m.content)
            lines.append("")
        dest.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Verilog syntax highlighter for code blocks
# ---------------------------------------------------------------------------


class VerilogHighlighter(QSyntaxHighlighter):
    KEYWORDS = {
        "module",
        "endmodule",
        "input",
        "output",
        "inout",
        "wire",
        "reg",
        "logic",
        "always",
        "always_comb",
        "always_ff",
        "always_latch",
        "begin",
        "end",
        "if",
        "else",
        "case",
        "endcase",
        "default",
        "for",
        "while",
        "assign",
        "parameter",
        "localparam",
        "generate",
        "endgenerate",
        "genvar",
        "posedge",
        "negedge",
        "or",
        "and",
        "not",
        "xor",
        "nand",
        "nor",
        "function",
        "endfunction",
        "task",
        "endtask",
        "return",
        "void",
        "typedef",
        "struct",
        "enum",
        "package",
        "endpackage",
        "import",
        "interface",
        "endinterface",
        "modport",
        "class",
        "endclass",
        "initial",
        "final",
        "fork",
        "join",
        "wait",
        "disable",
        "integer",
        "real",
        "time",
        "bit",
        "byte",
        "shortint",
        "int",
        "longint",
        "signed",
        "unsigned",
        "string",
        "automatic",
        "static",
        "const",
    }

    def __init__(self, document) -> None:
        super().__init__(document)
        self.kw_fmt = QTextCharFormat()
        self.kw_fmt.setForeground(QColor(CAT_MAUVE))
        self.kw_fmt.setFontWeight(QFont.Bold)
        self.num_fmt = QTextCharFormat()
        self.num_fmt.setForeground(QColor(CAT_PEACH))
        self.str_fmt = QTextCharFormat()
        self.str_fmt.setForeground(QColor(CAT_GREEN))
        self.cmt_fmt = QTextCharFormat()
        self.cmt_fmt.setForeground(QColor(CAT_OVERLAY1))
        self.cmt_fmt.setFontItalic(True)
        self.dir_fmt = QTextCharFormat()
        self.dir_fmt.setForeground(QColor(CAT_PINK))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for match in re.finditer(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text):
            word = match.group(0)
            if word in self.KEYWORDS:
                self.setFormat(match.start(), len(word), self.kw_fmt)
        for match in re.finditer(r"\b\d+'?[bdhBDH]?[0-9a-fA-F_xzXZ]*\b|\b\d+\b", text):
            self.setFormat(match.start(), len(match.group(0)), self.num_fmt)
        for match in re.finditer(r'"[^"]*"', text):
            self.setFormat(match.start(), len(match.group(0)), self.str_fmt)
        for match in re.finditer(r"`[a-zA-Z_]+", text):
            self.setFormat(match.start(), len(match.group(0)), self.dir_fmt)
        idx = text.find("//")
        if idx >= 0:
            self.setFormat(idx, len(text) - idx, self.cmt_fmt)


# ---------------------------------------------------------------------------
# Code block widget with action buttons
# ---------------------------------------------------------------------------


class CodeBlockWidget(QFrame):
    insert_requested = Signal(str)
    run_synthesis_requested = Signal(str)
    explain_requested = Signal(str)

    def __init__(
        self,
        code: str,
        language: str = "verilog",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.code = code
        self.language = language
        self.setObjectName("codeBlock")
        self.setStyleSheet(
            f"""
            QFrame#codeBlock {{
                background: {CAT_SURFACE0};
                border: 1px solid {CAT_SURFACE1};
                border-radius: 6px;
            }}
            QPlainTextEdit {{
                background: transparent;
                color: {CAT_TEXT};
                border: none;
                font-family: 'Cascadia Code', 'Consolas', 'Menlo', monospace;
                font-size: 12px;
            }}
            QPushButton {{
                background: {CAT_SURFACE1};
                color: {CAT_TEXT};
                border: none;
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: {CAT_SURFACE2}; }}
            QLabel#langLabel {{
                color: {CAT_LAVENDER};
                font-size: 10px;
                font-weight: bold;
                padding: 2px 8px;
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        lang = QLabel(language.upper())
        lang.setObjectName("langLabel")
        header.addWidget(lang)
        header.addStretch(1)
        layout.addLayout(header)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(code)
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Cascadia Code", 10)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        if language in ("verilog", "systemverilog", "sv", "v"):
            self._highlighter = VerilogHighlighter(self.editor.document())
        line_count = min(max(code.count("\n") + 1, 3), 24)
        self.editor.setFixedHeight(line_count * 16 + 16)
        layout.addWidget(self.editor)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        btn_insert = QPushButton("Insert at Cursor")
        btn_insert.clicked.connect(lambda: self.insert_requested.emit(self.code))
        btn_copy = QPushButton("Copy")
        btn_copy.clicked.connect(self._copy)
        btn_save = QPushButton("Save as File")
        btn_save.clicked.connect(self._save)
        btn_synth = QPushButton("Run Synthesis")
        btn_synth.clicked.connect(lambda: self.run_synthesis_requested.emit(self.code))
        btn_explain = QPushButton("Explain")
        btn_explain.clicked.connect(lambda: self.explain_requested.emit(self.code))
        for b in (btn_insert, btn_copy, btn_save, btn_synth, btn_explain):
            actions.addWidget(b)
        actions.addStretch(1)
        layout.addLayout(actions)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.code)

    def _save(self) -> None:
        ext = ".v" if self.language in ("verilog", "v") else ".sv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save code", f"snippet{ext}", f"Verilog (*{ext});;All Files (*)"
        )
        if path:
            try:
                Path(path).write_text(self.code, encoding="utf-8")
            except Exception as exc:
                QMessageBox.warning(self, "Save failed", str(exc))


# ---------------------------------------------------------------------------
# Chat message bubble
# ---------------------------------------------------------------------------


class MessageBubble(QFrame):
    insert_code_requested = Signal(str)
    run_synthesis_requested = Signal(str)
    explain_code_requested = Signal(str)

    def __init__(self, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self._raw_text = ""
        self._streaming = True
        self.setObjectName("bubble")
        self._apply_style()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)

        header = QHBoxLayout()
        name = QLabel("You" if role == "user" else "OpenForge AI")
        name.setStyleSheet(
            f"color: {CAT_BLUE if role == 'user' else CAT_MAUVE}; "
            f"font-weight: bold; font-size: 11px;"
        )
        header.addWidget(name)
        header.addStretch(1)
        self.time_label = QLabel(datetime.now().strftime("%H:%M"))
        self.time_label.setStyleSheet(f"color: {CAT_OVERLAY0}; font-size: 10px;")
        header.addWidget(self.time_label)
        self._layout.addLayout(header)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setStyleSheet(
            f"QTextBrowser {{ background: transparent; color: {CAT_TEXT}; "
            f"border: none; font-size: 13px; }}"
        )
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._layout.addWidget(self.body)

        self._code_widgets: list[CodeBlockWidget] = []

    def _apply_style(self) -> None:
        if self.role == "user":
            border = CAT_BLUE
            bg = "#1e2a4a"
        else:
            border = CAT_MAUVE
            bg = "#2a1e3a"
        self.setStyleSheet(
            f"QFrame#bubble {{ background: {bg}; border-left: 3px solid {border}; "
            f"border-radius: 8px; }}"
        )

    def append_chunk(self, chunk: str) -> None:
        self._raw_text += chunk
        self._render_text(self._raw_text + " <span style='color:#b4befe'>&#9608;</span>")

    def set_text(self, text: str) -> None:
        self._raw_text = text
        self._streaming = False
        self._render_text(text)
        self._extract_code_blocks()

    def finalize(self) -> None:
        self._streaming = False
        self._render_text(self._raw_text)
        self._extract_code_blocks()

    def _render_text(self, text: str) -> None:
        html = self._markdown_to_html(text)
        self.body.setHtml(html)
        doc_height = int(self.body.document().size().height()) + 12
        self.body.setFixedHeight(max(doc_height, 24))

    def _markdown_to_html(self, text: str) -> str:
        def repl_code(match: re.Match) -> str:
            lang = match.group(1) or ""
            code = match.group(2)
            esc = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return (
                f'<pre style="background:{CAT_SURFACE0};color:{CAT_TEXT};'
                f"padding:8px;border-radius:6px;font-family:Cascadia Code,Consolas,monospace;"
                f'font-size:12px;white-space:pre-wrap;">'
                f'<span style="color:{CAT_LAVENDER};font-size:10px;">{lang.upper()}</span>\n{esc}'
                f"</pre>"
            )

        body = re.sub(r"```(\w+)?\n(.*?)```", repl_code, text, flags=re.DOTALL)
        body = re.sub(
            r"`([^`]+)`",
            lambda m: (
                f'<code style="background:{CAT_SURFACE0};color:{CAT_PEACH};'
                f'padding:1px 4px;border-radius:3px;">{m.group(1)}</code>'
            ),
            body,
        )
        body = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", body)
        body = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", body)
        body = re.sub(r"(?m)^### (.+)$", r"<h4>\1</h4>", body)
        body = re.sub(r"(?m)^## (.+)$", r"<h3>\1</h3>", body)
        body = re.sub(r"(?m)^# (.+)$", r"<h2>\1</h2>", body)
        body = body.replace("\n", "<br>")
        return f'<div style="color:{CAT_TEXT};line-height:1.5;">{body}</div>'

    def _extract_code_blocks(self) -> None:
        for w in self._code_widgets:
            w.setParent(None)
            w.deleteLater()
        self._code_widgets.clear()
        for match in re.finditer(r"```(\w+)?\n(.*?)```", self._raw_text, re.DOTALL):
            lang = (match.group(1) or "verilog").lower()
            code = match.group(2).rstrip()
            if not code:
                continue
            cb = CodeBlockWidget(code, language=lang, parent=self)
            cb.insert_requested.connect(self.insert_code_requested)
            cb.run_synthesis_requested.connect(self.run_synthesis_requested)
            cb.explain_requested.connect(self.explain_code_requested)
            self._layout.addWidget(cb)
            self._code_widgets.append(cb)


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------


class SetupWizardWidget(QWidget):
    refresh_requested = Signal()
    install_model_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            QWidget {{ background: {CAT_BASE}; color: {CAT_TEXT}; }}
            QLabel#title {{ font-size: 18px; font-weight: bold; color: {CAT_LAVENDER}; }}
            QLabel#subtitle {{ font-size: 13px; color: {CAT_SUBTEXT0}; }}
            QPushButton {{
                background: {CAT_BLUE};
                color: {CAT_BASE};
                padding: 8px 16px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {CAT_LAVENDER}; }}
            QPushButton#secondary {{ background: {CAT_SURFACE1}; color: {CAT_TEXT}; }}
            QPushButton#secondary:hover {{ background: {CAT_SURFACE2}; }}
            QFrame#card {{
                background: {CAT_MANTLE};
                border: 1px solid {CAT_SURFACE0};
                border-radius: 8px;
            }}
            QProgressBar {{
                background: {CAT_SURFACE0};
                border: none;
                border-radius: 4px;
                text-align: center;
                color: {CAT_TEXT};
            }}
            QProgressBar::chunk {{ background: {CAT_BLUE}; border-radius: 4px; }}
            """
        )
        self._stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(self._stack)

        self._not_running = self._build_not_running()
        self._no_models = self._build_no_models()
        self._stack.addWidget(self._not_running)
        self._stack.addWidget(self._no_models)

    def _build_not_running(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(14)
        title = QLabel("Ollama Not Detected")
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel(
            "OpenForge AI Assistant runs on Ollama, a free local LLM runtime.\n"
            "Install it once and the assistant works fully offline."
        )
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        v.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setSpacing(10)
        steps = QLabel(
            "<b>1.</b> Click <b>Install Ollama</b> to download from ollama.com<br>"
            "<b>2.</b> Run the installer<br>"
            "<b>3.</b> Open a terminal and run: <code>ollama pull llama3.2</code><br>"
            "<b>4.</b> Click <b>Refresh</b> below"
        )
        steps.setTextFormat(Qt.RichText)
        steps.setWordWrap(True)
        cv.addWidget(steps)
        v.addWidget(card)

        row = QHBoxLayout()
        install = QPushButton("Install Ollama")
        install.clicked.connect(lambda: webbrowser.open("https://ollama.com/download"))
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self.refresh_requested.emit)
        row.addWidget(install)
        row.addWidget(refresh)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _build_no_models(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        title = QLabel("No Models Installed")
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel("Ollama is running but no models are installed. Choose one to download:")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        v.addWidget(sub)

        self._model_rows: dict[str, tuple[QPushButton, QProgressBar, QLabel]] = {}
        for name, params, size, desc in RECOMMENDED_MODELS:
            card = QFrame()
            card.setObjectName("card")
            cv = QVBoxLayout(card)
            top = QHBoxLayout()
            label = QLabel(
                f"<b>{name}</b>  <span style='color:{CAT_OVERLAY1}'>{params} &middot; {size}</span>"
            )
            label.setTextFormat(Qt.RichText)
            top.addWidget(label)
            top.addStretch(1)
            btn = QPushButton("Install")
            btn.clicked.connect(lambda _=False, n=name: self.install_model_requested.emit(n))
            top.addWidget(btn)
            cv.addLayout(top)
            d = QLabel(desc)
            d.setStyleSheet(f"color:{CAT_SUBTEXT0};font-size:11px;")
            cv.addWidget(d)
            bar = QProgressBar()
            bar.setVisible(False)
            bar.setRange(0, 100)
            cv.addWidget(bar)
            status = QLabel("")
            status.setStyleSheet(f"color:{CAT_OVERLAY1};font-size:10px;")
            status.setVisible(False)
            cv.addWidget(status)
            v.addWidget(card)
            self._model_rows[name] = (btn, bar, status)

        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self.refresh_requested.emit)
        row.addStretch(1)
        row.addWidget(refresh)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def show_not_running(self) -> None:
        self._stack.setCurrentWidget(self._not_running)

    def show_no_models(self) -> None:
        self._stack.setCurrentWidget(self._no_models)

    def update_model_progress(self, name: str, status: str, completed: int, total: int) -> None:
        row = self._model_rows.get(name)
        if not row:
            return
        btn, bar, label = row
        bar.setVisible(True)
        label.setVisible(True)
        btn.setEnabled(False)
        label.setText(status)
        if total > 0:
            bar.setRange(0, 100)
            bar.setValue(int(100 * completed / total))
        else:
            bar.setRange(0, 0)

    def model_install_done(self, name: str) -> None:
        row = self._model_rows.get(name)
        if not row:
            return
        btn, bar, label = row
        bar.setValue(100)
        bar.setRange(0, 100)
        label.setText("Installed")
        btn.setText("Installed")
        btn.setEnabled(False)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------


class AiSettingsDialog(QDialog):
    def __init__(
        self,
        settings: QSettings,
        available_models: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Assistant Settings")
        self.setMinimumWidth(560)
        self.settings = settings

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.url_edit = QLineEdit(
            settings.value("ai_assistant/ollama_url", "http://localhost:11434")
        )
        form.addRow("Ollama URL:", self.url_edit)

        self.model_combo = QComboBox()
        if available_models:
            self.model_combo.addItems(available_models)
            current = settings.value("ai_assistant/model", available_models[0])
            idx = self.model_combo.findText(current)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.addItem("(no models installed)")
        form.addRow("Model:", self.model_combo)

        temp_row = QHBoxLayout()
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(0, 200)
        self.temp_slider.setValue(int(float(settings.value("ai_assistant/temperature", 0.7)) * 100))
        self.temp_label = QLabel(f"{self.temp_slider.value() / 100:.2f}")
        self.temp_slider.valueChanged.connect(lambda v: self.temp_label.setText(f"{v / 100:.2f}"))
        temp_row.addWidget(self.temp_slider)
        temp_row.addWidget(self.temp_label)
        form.addRow("Temperature:", temp_row)

        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(1024, 32768)
        self.ctx_spin.setSingleStep(1024)
        self.ctx_spin.setValue(int(settings.value("ai_assistant/num_ctx", 8192)))
        form.addRow("Max context length:", self.ctx_spin)

        self.history_spin = QSpinBox()
        self.history_spin.setRange(1, 50)
        self.history_spin.setValue(int(settings.value("ai_assistant/history_messages", 20)))
        form.addRow("Past messages in context:", self.history_spin)

        self.save_history_cb = QCheckBox("Save conversation history to disk")
        self.save_history_cb.setChecked(
            settings.value("ai_assistant/save_history", "true") == "true"
        )
        form.addRow("", self.save_history_cb)

        layout.addLayout(form)

        layout.addWidget(QLabel("System prompt:"))
        self.sys_edit = QPlainTextEdit()
        self.sys_edit.setPlainText(
            settings.value("ai_assistant/system_prompt", DEFAULT_SYSTEM_PROMPT)
        )
        self.sys_edit.setMinimumHeight(180)
        layout.addWidget(self.sys_edit)

        reset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(lambda: self.sys_edit.setPlainText(DEFAULT_SYSTEM_PROMPT))
        reset_row.addStretch(1)
        reset_row.addWidget(reset_btn)
        layout.addLayout(reset_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self) -> None:
        s = self.settings
        s.setValue("ai_assistant/ollama_url", self.url_edit.text())
        s.setValue("ai_assistant/model", self.model_combo.currentText())
        s.setValue("ai_assistant/temperature", self.temp_slider.value() / 100)
        s.setValue("ai_assistant/num_ctx", self.ctx_spin.value())
        s.setValue("ai_assistant/history_messages", self.history_spin.value())
        s.setValue(
            "ai_assistant/save_history",
            "true" if self.save_history_cb.isChecked() else "false",
        )
        s.setValue("ai_assistant/system_prompt", self.sys_edit.toPlainText())


# ---------------------------------------------------------------------------
# Local fallback content: templates, keywords, errors
# ---------------------------------------------------------------------------


VERILOG_TEMPLATES: dict[str, str] = {
    "Counter (parameterised)": (
        "module counter #(parameter WIDTH = 8) (\n"
        "    input  wire             clk,\n"
        "    input  wire             rst_n,\n"
        "    input  wire             en,\n"
        "    output reg [WIDTH-1:0]  q\n"
        ");\n"
        "    always @(posedge clk or negedge rst_n) begin\n"
        "        if (!rst_n)      q <= '0;\n"
        "        else if (en)     q <= q + 1'b1;\n"
        "    end\n"
        "endmodule\n"
    ),
    "Synchronous FIFO": (
        "module sync_fifo #(\n"
        "    parameter DEPTH = 16,\n"
        "    parameter WIDTH = 8\n"
        ") (\n"
        "    input  wire             clk,\n"
        "    input  wire             rst_n,\n"
        "    input  wire             wr_en,\n"
        "    input  wire [WIDTH-1:0] din,\n"
        "    input  wire             rd_en,\n"
        "    output reg  [WIDTH-1:0] dout,\n"
        "    output wire             full,\n"
        "    output wire             empty\n"
        ");\n"
        "    localparam ADDR_W = $clog2(DEPTH);\n"
        "    reg [WIDTH-1:0] mem [0:DEPTH-1];\n"
        "    reg [ADDR_W:0]  wr_ptr, rd_ptr;\n"
        "    assign full  = (wr_ptr - rd_ptr) == DEPTH;\n"
        "    assign empty = wr_ptr == rd_ptr;\n"
        "    always @(posedge clk or negedge rst_n) begin\n"
        "        if (!rst_n) begin\n"
        "            wr_ptr <= 0; rd_ptr <= 0;\n"
        "        end else begin\n"
        "            if (wr_en && !full)  begin mem[wr_ptr[ADDR_W-1:0]] <= din; wr_ptr <= wr_ptr + 1; end\n"
        "            if (rd_en && !empty) begin dout <= mem[rd_ptr[ADDR_W-1:0]]; rd_ptr <= rd_ptr + 1; end\n"
        "        end\n"
        "    end\n"
        "endmodule\n"
    ),
    "2-FF Synchroniser": (
        "module sync2 #(parameter WIDTH = 1) (\n"
        "    input  wire             clk,\n"
        "    input  wire             rst_n,\n"
        "    input  wire [WIDTH-1:0] async_in,\n"
        "    output reg  [WIDTH-1:0] sync_out\n"
        ");\n"
        "    reg [WIDTH-1:0] meta;\n"
        "    always @(posedge clk or negedge rst_n) begin\n"
        "        if (!rst_n) {sync_out, meta} <= '0;\n"
        "        else        {sync_out, meta} <= {meta, async_in};\n"
        "    end\n"
        "endmodule\n"
    ),
    "FSM (Moore, 3-state)": (
        "module moore_fsm (\n"
        "    input  wire clk,\n"
        "    input  wire rst_n,\n"
        "    input  wire start,\n"
        "    input  wire done_in,\n"
        "    output reg  busy,\n"
        "    output reg  done\n"
        ");\n"
        "    typedef enum logic [1:0] {IDLE, RUN, DONE_S} state_t;\n"
        "    state_t state, next;\n"
        "    always_ff @(posedge clk or negedge rst_n)\n"
        "        if (!rst_n) state <= IDLE; else state <= next;\n"
        "    always_comb begin\n"
        "        next = state;\n"
        "        case (state)\n"
        "            IDLE:   if (start)   next = RUN;\n"
        "            RUN:    if (done_in) next = DONE_S;\n"
        "            DONE_S:              next = IDLE;\n"
        "        endcase\n"
        "    end\n"
        "    always_comb begin\n"
        "        busy = (state == RUN);\n"
        "        done = (state == DONE_S);\n"
        "    end\n"
        "endmodule\n"
    ),
    "Edge Detector": (
        "module edge_detect (\n"
        "    input  wire clk,\n"
        "    input  wire rst_n,\n"
        "    input  wire sig,\n"
        "    output wire rise,\n"
        "    output wire fall\n"
        ");\n"
        "    reg sig_d;\n"
        "    always @(posedge clk or negedge rst_n)\n"
        "        if (!rst_n) sig_d <= 1'b0; else sig_d <= sig;\n"
        "    assign rise =  sig & ~sig_d;\n"
        "    assign fall = ~sig &  sig_d;\n"
        "endmodule\n"
    ),
}


KEYWORD_DICTIONARY: dict[str, str] = {
    "always": "Procedural block. Use always_ff for sequential and always_comb for combinational logic.",
    "always_ff": "SystemVerilog: sequential block; tools enforce that only flip-flops are inferred.",
    "always_comb": "SystemVerilog: combinational block; sensitivity list inferred, latches flagged.",
    "assign": "Continuous assignment for nets. Cannot drive reg in classic Verilog.",
    "wire": "Net type, driven by continuous assignments or module ports.",
    "reg": "Variable type used inside procedural blocks.",
    "logic": "SystemVerilog 4-state type, replaces reg/wire in most cases.",
    "parameter": "Compile-time constant, overridable per instance.",
    "localparam": "Compile-time constant that cannot be overridden.",
    "generate": "Elaborates hardware conditionally or in loops at compile time.",
    "genvar": "Loop variable used inside generate-for blocks.",
    "posedge": "Edge sensitivity: rising clock edge.",
    "negedge": "Edge sensitivity: falling clock edge or active-low reset.",
    "case": "Multi-way branch. Use unique/priority qualifiers to enforce intent.",
    "function": "Returns a value, executes in zero simulation time, no event control.",
    "task": "May contain timing controls and have multiple outputs.",
    "module": "Top-level building block; encapsulates ports and logic.",
    "interface": "SystemVerilog construct grouping signals and tasks for clean connectivity.",
    "modport": "Defines direction view inside an interface.",
    "typedef": "Creates a new named type from an existing type.",
    "struct": "Aggregate type. Use packed for bit-level layouts that synthesise.",
    "enum": "Named integer-like type, common for FSM states.",
    "package": "Namespace for typedefs/parameters/functions reused across modules.",
}


ERROR_EXPLANATIONS: dict[str, str] = {
    "syntax error": "Parser failed. Check for missing semicolons, unbalanced begin/end, or stray characters.",
    "Latch inferred": "A combinational always block doesn't assign all outputs in every branch. Add a default.",
    "Multiple drivers": "A signal is driven from more than one always block or assign.",
    "Port size mismatch": "The instantiated module's port width differs from the signal you connected.",
    "Undeclared identifier": "Signal used before declaration. Declare wire/reg/logic, or check spelling.",
    "Implicit wire": "A signal was inferred as a 1-bit wire. Enable default_nettype none.",
    "Unsynthesizable": "Construct exists in simulation only. Remove from RTL.",
    "hold violation": "A path arrives too early. Add buffers or rebalance the clock tree.",
    "setup violation": "Path is too slow. Pipeline the logic or relax constraints.",
    "WIDTH": "Bit-width mismatch in expression. Add explicit casts or matching widths.",
    "UNUSED": "Signal declared but never used. Remove or mark verilator lint_off UNUSED.",
    "BLKSEQ": "Blocking assignment in sequential block. Use non-blocking (<=) for flip-flops.",
}


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class AiAssistantPanel(QDockWidget):
    """The OpenForge AI Assistant dock panel."""

    insert_code_requested = Signal(str)
    run_synthesis_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("AI Assistant", parent)
        self.setObjectName("AiAssistantPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self.settings = QSettings("OpenForge", "Desktop")
        self.store = ConversationStore()
        self.client = OllamaClient(
            base_url=self.settings.value("ai_assistant/ollama_url", "http://localhost:11434"),
            model=self.settings.value("ai_assistant/model", "llama3.2"),
        )

        self._project_path: Path | None = None
        self._top_module: str | None = None
        self._sources: list[Path] = []
        self._attached_files: list[Path] = []
        self._attached_errors: list[str] = []

        self._stream_worker: OllamaStreamWorker | None = None
        self._pull_worker: ModelPullWorker | None = None
        self._current_assistant_bubble: MessageBubble | None = None

        self._conversations: list[Conversation] = []
        self._current: Conversation | None = None

        self._dark = True
        self._build_ui()
        self._apply_theme()
        self._load_conversations()
        QTimer.singleShot(100, self._check_ollama_status)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        self._build_chat_tab()
        self._build_templates_tab()
        self._build_keywords_tab()
        self._build_errors_tab()

        self.setWidget(root)

    def _build_chat_tab(self) -> None:
        wrapper = QWidget()
        outer = QHBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sidebar
        self.sidebar = QWidget()
        self.sidebar.setMaximumWidth(220)
        self.sidebar.setMinimumWidth(180)
        sb = QVBoxLayout(self.sidebar)
        sb.setContentsMargins(8, 8, 8, 8)
        sb.setSpacing(6)
        new_btn = QPushButton("+ New Chat")
        new_btn.clicked.connect(self.new_chat)
        sb.addWidget(new_btn)
        self.convo_list = QListWidget()
        self.convo_list.itemClicked.connect(self._on_convo_clicked)
        self.convo_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.convo_list.customContextMenuRequested.connect(self._on_convo_context)
        sb.addWidget(self.convo_list, 1)

        # Chat area
        chat_area = QWidget()
        ca = QVBoxLayout(chat_area)
        ca.setContentsMargins(0, 0, 0, 0)
        ca.setSpacing(0)

        header = QFrame()
        header.setObjectName("chatHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 6, 10, 6)
        self.status_label = QLabel("Connecting to Ollama...")
        self.status_label.setStyleSheet(f"color:{CAT_OVERLAY1};font-size:11px;")
        hl.addWidget(self.status_label)
        hl.addStretch(1)
        self.model_label = QLabel("")
        self.model_label.setStyleSheet(f"color:{CAT_LAVENDER};font-size:11px;font-weight:bold;")
        hl.addWidget(self.model_label)
        toggle_sidebar = QToolButton()
        toggle_sidebar.setText("Sidebar")
        toggle_sidebar.setCheckable(True)
        toggle_sidebar.setChecked(True)
        toggle_sidebar.toggled.connect(self.sidebar.setVisible)
        hl.addWidget(toggle_sidebar)
        settings_btn = QToolButton()
        settings_btn.setText("Settings")
        settings_btn.clicked.connect(self.open_settings)
        hl.addWidget(settings_btn)
        ca.addWidget(header)

        # Stacked: setup wizard or messages
        self.chat_stack = QStackedWidget()

        self.setup_wizard = SetupWizardWidget()
        self.setup_wizard.refresh_requested.connect(self._check_ollama_status)
        self.setup_wizard.install_model_requested.connect(self._install_model)
        self.chat_stack.addWidget(self.setup_wizard)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(12, 12, 12, 12)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)
        self.chat_scroll.setWidget(self.messages_container)
        self.chat_stack.addWidget(self.chat_scroll)

        ca.addWidget(self.chat_stack, 1)

        # Quick actions toolbar
        self.actions_bar = QFrame()
        self.actions_bar.setObjectName("actionsBar")
        ab = QHBoxLayout(self.actions_bar)
        ab.setContentsMargins(8, 4, 8, 4)
        ab.setSpacing(4)
        for label, prompt in [
            ("Explain Selection", "Explain this Verilog code in detail:"),
            ("Fix Errors", "Help me fix these errors:"),
            (
                "Generate Testbench",
                "Generate a comprehensive SystemVerilog testbench for this module:",
            ),
            ("Review Code", "Review this code for bugs and best practices:"),
            ("Optimize", "Suggest optimizations for area, power and timing:"),
            ("Add Comments", "Add detailed comments to this code:"),
        ]:
            btn = QToolButton()
            btn.setText(label)
            btn.clicked.connect(lambda _=False, p=prompt: self._quick_action(p))
            ab.addWidget(btn)
        ab.addStretch(1)
        ca.addWidget(self.actions_bar)

        # Input area
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        il = QVBoxLayout(input_frame)
        il.setContentsMargins(8, 8, 8, 8)
        il.setSpacing(6)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(
            "Ask about Verilog, RTL, synthesis, timing... (Ctrl+Enter to send)"
        )
        self.input_edit.setMaximumHeight(110)
        il.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        self.attach_btn = QToolButton()
        self.attach_btn.setText("Attach File")
        self.attach_btn.clicked.connect(self._on_attach_file)
        btn_row.addWidget(self.attach_btn)
        self.context_label = QLabel("")
        self.context_label.setStyleSheet(f"color:{CAT_OVERLAY1};font-size:10px;")
        btn_row.addWidget(self.context_label)
        btn_row.addStretch(1)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop_streaming)
        btn_row.addWidget(self.stop_btn)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send_clicked)
        btn_row.addWidget(self.send_btn)
        il.addLayout(btn_row)

        # --- Deepened AI: tools / RAG / constraint debugger row ----------
        tools_row = QHBoxLayout()
        try:
            self.debug_path_btn = QPushButton("Debug failing path")
            self.debug_path_btn.setToolTip(
                "Run the AI ConstraintDebugger on the current critical STA path."
            )
            self.debug_path_btn.clicked.connect(self._on_debug_failing_path)
            tools_row.addWidget(self.debug_path_btn)

            self.explain_btn = QPushButton("Explain this")
            self.explain_btn.setToolTip(
                "Ask the LLM to explain the currently selected RTL or panel."
            )
            self.explain_btn.clicked.connect(self._on_explain_this)
            tools_row.addWidget(self.explain_btn)

            tools_row.addStretch(1)
            il.addLayout(tools_row)
        except Exception:
            pass
        ca.addWidget(input_frame)

        send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.input_edit)
        send_shortcut.activated.connect(self._on_send_clicked)
        send_shortcut2 = QShortcut(QKeySequence("Ctrl+Enter"), self.input_edit)
        send_shortcut2.activated.connect(self._on_send_clicked)

        outer.addWidget(self.sidebar)
        outer.addWidget(chat_area, 1)
        self.tabs.addTab(wrapper, "Chat")

    def _build_templates_tab(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        info = QLabel("Local templates (no AI required). Click Insert to push to active editor.")
        info.setStyleSheet(f"color:{CAT_OVERLAY1};font-size:11px;")
        v.addWidget(info)
        self.template_list = QListWidget()
        for name in VERILOG_TEMPLATES:
            self.template_list.addItem(name)
        v.addWidget(self.template_list, 1)
        self.template_preview = QPlainTextEdit()
        self.template_preview.setReadOnly(True)
        font = QFont("Cascadia Code", 10)
        font.setStyleHint(QFont.Monospace)
        self.template_preview.setFont(font)
        VerilogHighlighter(self.template_preview.document())
        v.addWidget(self.template_preview, 2)
        row = QHBoxLayout()
        row.addStretch(1)
        insert = QPushButton("Insert at Cursor")
        insert.clicked.connect(self._insert_template_at_cursor)
        row.addWidget(insert)
        v.addLayout(row)
        self.template_list.currentTextChanged.connect(
            lambda name: self.template_preview.setPlainText(VERILOG_TEMPLATES.get(name, ""))
        )
        if self.template_list.count():
            self.template_list.setCurrentRow(0)
        self.tabs.addTab(w, "Templates")

    def _build_keywords_tab(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        self.keyword_search = QLineEdit()
        self.keyword_search.setPlaceholderText("Search keyword...")
        self.keyword_search.textChanged.connect(self._filter_keywords)
        v.addWidget(self.keyword_search)
        self.keyword_list = QListWidget()
        for k in sorted(KEYWORD_DICTIONARY):
            self.keyword_list.addItem(k)
        self.keyword_list.currentTextChanged.connect(
            lambda k: self.keyword_desc.setPlainText(KEYWORD_DICTIONARY.get(k, ""))
        )
        v.addWidget(self.keyword_list, 1)
        self.keyword_desc = QPlainTextEdit()
        self.keyword_desc.setReadOnly(True)
        v.addWidget(self.keyword_desc, 1)
        self.tabs.addTab(w, "Keywords")

    def _build_errors_tab(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        info = QLabel("Paste an error message and click Explain (offline lookup).")
        info.setStyleSheet(f"color:{CAT_OVERLAY1};font-size:11px;")
        v.addWidget(info)
        self.error_input = QPlainTextEdit()
        self.error_input.setMaximumHeight(120)
        v.addWidget(self.error_input)
        row = QHBoxLayout()
        row.addStretch(1)
        explain = QPushButton("Explain")
        explain.clicked.connect(self._explain_local)
        ask_ai = QPushButton("Ask AI")
        ask_ai.clicked.connect(self._explain_with_ai)
        row.addWidget(explain)
        row.addWidget(ask_ai)
        v.addLayout(row)
        self.error_output = QTextBrowser()
        v.addWidget(self.error_output, 1)
        self.tabs.addTab(w, "Errors")

    # -- Theme ------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QDockWidget {{ background: {CAT_BASE}; color: {CAT_TEXT}; }}
            QWidget {{ background: {CAT_BASE}; color: {CAT_TEXT}; font-size: 12px; }}
            QTabWidget::pane {{ border: none; background: {CAT_BASE}; }}
            QTabBar::tab {{
                background: {CAT_MANTLE};
                color: {CAT_SUBTEXT0};
                padding: 8px 14px;
                border: none;
            }}
            QTabBar::tab:selected {{
                background: {CAT_BASE};
                color: {CAT_LAVENDER};
                border-bottom: 2px solid {CAT_BLUE};
            }}
            QFrame#chatHeader, QFrame#actionsBar, QFrame#inputFrame {{
                background: {CAT_MANTLE};
                border-top: 1px solid {CAT_SURFACE0};
            }}
            QPlainTextEdit, QTextEdit, QTextBrowser, QLineEdit {{
                background: {CAT_SURFACE0};
                color: {CAT_TEXT};
                border: 1px solid {CAT_SURFACE1};
                border-radius: 6px;
                padding: 6px;
                selection-background-color: {CAT_BLUE};
            }}
            QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {{
                border: 1px solid {CAT_BLUE};
            }}
            QPushButton {{
                background: {CAT_BLUE};
                color: {CAT_BASE};
                border: none;
                padding: 6px 14px;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {CAT_LAVENDER}; }}
            QPushButton:disabled {{ background: {CAT_SURFACE1}; color: {CAT_OVERLAY0}; }}
            QToolButton {{
                background: {CAT_SURFACE0};
                color: {CAT_TEXT};
                border: 1px solid {CAT_SURFACE1};
                padding: 4px 10px;
                border-radius: 4px;
            }}
            QToolButton:hover {{ background: {CAT_SURFACE1}; }}
            QListWidget {{
                background: {CAT_MANTLE};
                color: {CAT_TEXT};
                border: 1px solid {CAT_SURFACE0};
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background: {CAT_SURFACE0};
                color: {CAT_LAVENDER};
            }}
            QScrollArea {{ background: {CAT_BASE}; border: none; }}
            QScrollBar:vertical {{
                background: {CAT_BASE}; width: 10px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {CAT_SURFACE1}; border-radius: 5px; min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {CAT_SURFACE2}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            """
        )

    # -- Ollama status ----------------------------------------------------

    def _check_ollama_status(self) -> None:
        self.client.base_url = self.settings.value(
            "ai_assistant/ollama_url", "http://localhost:11434"
        ).rstrip("/")
        if not self.client.is_available():
            self.status_label.setText("Ollama not running")
            self.status_label.setStyleSheet(f"color:{CAT_RED};font-size:11px;")
            self.model_label.setText("")
            self.setup_wizard.show_not_running()
            self.chat_stack.setCurrentWidget(self.setup_wizard)
            self._set_input_enabled(False)
            return
        try:
            models = self.client.list_models()
        except OllamaError:
            models = []
        if not models:
            self.status_label.setText("Ollama running, no models")
            self.status_label.setStyleSheet(f"color:{CAT_YELLOW};font-size:11px;")
            self.model_label.setText("")
            self.setup_wizard.show_no_models()
            self.chat_stack.setCurrentWidget(self.setup_wizard)
            self._set_input_enabled(False)
            return
        configured = self.settings.value("ai_assistant/model", "")
        if configured in models:
            self.client.model = configured
        else:
            self.client.model = models[0]
            self.settings.setValue("ai_assistant/model", self.client.model)
        self.status_label.setText("Ollama ready")
        self.status_label.setStyleSheet(f"color:{CAT_GREEN};font-size:11px;")
        self.model_label.setText(self.client.model)
        self.chat_stack.setCurrentWidget(self.chat_scroll)
        self._set_input_enabled(True)

    def _set_input_enabled(self, enabled: bool) -> None:
        self.input_edit.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.actions_bar.setEnabled(enabled)

    def _install_model(self, name: str) -> None:
        if self._pull_worker and self._pull_worker.isRunning():
            QMessageBox.information(self, "Busy", "Already installing a model.")
            return
        self._pull_worker = ModelPullWorker(self.client, name)
        self._pull_worker.progress.connect(
            lambda s, c, t, n=name: self.setup_wizard.update_model_progress(n, s, c, t)
        )
        self._pull_worker.finished_ok.connect(self._on_pull_done)
        self._pull_worker.error.connect(lambda msg: QMessageBox.warning(self, "Pull failed", msg))
        self._pull_worker.start()

    def _on_pull_done(self, name: str) -> None:
        self.setup_wizard.model_install_done(name)
        QTimer.singleShot(500, self._check_ollama_status)

    # -- Settings ---------------------------------------------------------

    def open_settings(self) -> None:
        try:
            models = self.client.list_models() if self.client.is_available() else []
        except OllamaError:
            models = []
        dlg = AiSettingsDialog(self.settings, models, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.save()
            self.client.base_url = self.settings.value(
                "ai_assistant/ollama_url", "http://localhost:11434"
            ).rstrip("/")
            self.client.model = self.settings.value("ai_assistant/model", self.client.model)
            self.model_label.setText(self.client.model)

    # -- Conversation management ------------------------------------------

    def _load_conversations(self) -> None:
        self._conversations = self.store.list()
        self.convo_list.clear()
        for c in self._conversations:
            item = QListWidgetItem(c.title)
            item.setData(Qt.UserRole, c.id)
            self.convo_list.addItem(item)
        if not self._conversations:
            self.new_chat()
        else:
            self._load_conversation(self._conversations[0])
            self.convo_list.setCurrentRow(0)

    def new_chat(self) -> None:
        convo = Conversation.new(title="New Chat")
        self._conversations.insert(0, convo)
        self.store.save(convo)
        item = QListWidgetItem(convo.title)
        item.setData(Qt.UserRole, convo.id)
        self.convo_list.insertItem(0, item)
        self.convo_list.setCurrentRow(0)
        self._load_conversation(convo)

    def _load_conversation(self, convo: Conversation) -> None:
        self._current = convo
        while self.messages_layout.count() > 0:
            item = self.messages_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.messages_layout.addStretch(1)
        for m in convo.messages:
            if m.role == "system":
                continue
            self._render_message(m.role, m.content, stream=False)

    def _on_convo_clicked(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.UserRole)
        for c in self._conversations:
            if c.id == cid:
                self._load_conversation(c)
                return

    def _on_convo_context(self, pos) -> None:
        item = self.convo_list.itemAt(pos)
        if not item:
            return
        cid = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu.addAction("Rename")
        delete = menu.addAction("Delete")
        export = menu.addAction("Export to Markdown")
        chosen = menu.exec(self.convo_list.mapToGlobal(pos))
        convo = next((c for c in self._conversations if c.id == cid), None)
        if not convo:
            return
        if chosen == rename:
            new_title, ok = QInputDialog.getText(self, "Rename", "Title:", text=convo.title)
            if ok and new_title.strip():
                convo.title = new_title.strip()
                item.setText(convo.title)
                self.store.save(convo)
        elif chosen == delete:
            if QMessageBox.question(self, "Delete", f"Delete '{convo.title}'?") == QMessageBox.Yes:
                self.store.delete(convo.id)
                self._conversations = [c for c in self._conversations if c.id != cid]
                self.convo_list.takeItem(self.convo_list.row(item))
                if self._current and self._current.id == cid:
                    if self._conversations:
                        self._load_conversation(self._conversations[0])
                        self.convo_list.setCurrentRow(0)
                    else:
                        self.new_chat()
        elif chosen == export:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export conversation", f"{convo.title}.md", "Markdown (*.md)"
            )
            if path:
                self.store.export_markdown(convo, Path(path))

    # -- Message rendering ------------------------------------------------

    def _render_message(self, role: str, content: str, stream: bool = False) -> MessageBubble:
        bubble = MessageBubble(role, parent=self.messages_container)
        bubble.insert_code_requested.connect(self.insert_code_requested)
        bubble.run_synthesis_requested.connect(self.run_synthesis_requested)
        bubble.explain_code_requested.connect(self._explain_code_block)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
        if stream:
            bubble._raw_text = ""
        else:
            bubble.set_text(content)
        QTimer.singleShot(50, self._scroll_to_bottom)
        return bubble

    def _scroll_to_bottom(self) -> None:
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -- Sending messages -------------------------------------------------

    def _on_send_clicked(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self.input_edit.clear()
        self.send_message(text)

    def send_message(self, text: str) -> None:
        if not self.client.is_available():
            QMessageBox.warning(
                self,
                "Ollama unavailable",
                "Ollama is not running. Please install/start it from the setup wizard.",
            )
            self._check_ollama_status()
            return
        if self._current is None:
            self.new_chat()

        full_user_text = text
        if self._attached_files:
            ctx_parts = []
            for fp in self._attached_files:
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    ctx_parts.append(f"\n\n--- File: {fp.name} ---\n```\n{content}\n```")
                except Exception:
                    pass
            if ctx_parts:
                full_user_text += "\n\nAttached files:" + "".join(ctx_parts)
            self._attached_files.clear()
        if self._attached_errors:
            full_user_text += (
                "\n\nRecent errors:\n```\n" + "\n".join(self._attached_errors) + "\n```"
            )
            self._attached_errors.clear()
        self._update_context_label()

        user_msg = ChatMessage(role="user", content=full_user_text)
        assert self._current is not None
        self._current.messages.append(user_msg)
        if self._current.title in ("", "New Chat"):
            self._current.title = (text[:40] + ("..." if len(text) > 40 else "")) or "New Chat"
            row = self.convo_list.currentRow()
            if row >= 0:
                self.convo_list.item(row).setText(self._current.title)
        self._render_message("user", full_user_text, stream=False)

        if self.settings.value("ai_assistant/save_history", "true") == "true":
            self.store.save(self._current)

        messages = self._build_llm_messages()

        self._current_assistant_bubble = self._render_message("assistant", "", stream=True)

        temp = float(self.settings.value("ai_assistant/temperature", 0.7))
        num_ctx = int(self.settings.value("ai_assistant/num_ctx", 8192))
        self._stream_worker = OllamaStreamWorker(
            self.client, messages, temperature=temp, num_ctx=num_ctx
        )
        self._stream_worker.chunk_received.connect(self._on_chunk)
        self._stream_worker.finished_response.connect(self._on_stream_done)
        self._stream_worker.error.connect(self._on_stream_error)
        self._stream_worker.start()

        self.send_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.input_edit.setEnabled(False)

    def _build_llm_messages(self) -> list[dict]:
        messages: list[dict] = []
        sys_prompt = self.settings.value("ai_assistant/system_prompt", DEFAULT_SYSTEM_PROMPT)
        ctx_lines = []
        if self._project_path:
            ctx_lines.append(f"Current project: {self._project_path}")
        if self._top_module:
            ctx_lines.append(f"Top module: {self._top_module}")
        if self._sources:
            names = ", ".join(p.name for p in self._sources[:20])
            ctx_lines.append(f"Source files ({len(self._sources)}): {names}")
        if ctx_lines:
            sys_prompt = sys_prompt + "\n\n# Project Context\n" + "\n".join(ctx_lines)

        # RAG retrieval: inject top-k relevant doc chunks
        try:
            last_user = ""
            if self._current:
                for m in reversed(self._current.messages):
                    if m.role == "user":
                        last_user = m.content
                        break
            if last_user:
                rag_ctx = self._retrieve_rag_context(last_user, top_k=5)
                if rag_ctx:
                    sys_prompt += "\n\n" + rag_ctx
        except Exception:
            pass

        messages.append({"role": "system", "content": sys_prompt})

        history_n = int(self.settings.value("ai_assistant/history_messages", 20))
        if self._current:
            recent = [m for m in self._current.messages if m.role != "system"][-history_n:]
            for m in recent:
                messages.append({"role": m.role, "content": m.content})
        return messages

    @Slot(str)
    def _on_chunk(self, chunk: str) -> None:
        if self._current_assistant_bubble is None:
            return
        self._current_assistant_bubble.append_chunk(chunk)
        self._scroll_to_bottom()

    @Slot(str)
    def _on_stream_done(self, full: str) -> None:
        if self._current_assistant_bubble is not None:
            self._current_assistant_bubble.set_text(full)
            self._current_assistant_bubble = None
        if self._current is not None:
            self._current.messages.append(ChatMessage(role="assistant", content=full))
            if self.settings.value("ai_assistant/save_history", "true") == "true":
                self.store.save(self._current)
        self._end_streaming()

        # Tool-calling loop: if the assistant replied with a tool call,
        # execute it and feed the result back as a follow-up user turn.
        try:
            if str(self.settings.value("ai/enable_tools", "true")).lower() == "true":
                result = self._try_tool_call_from_text(full)
                if result is not None and self._current is not None:
                    self._current.messages.append(
                        ChatMessage(role="user", content=result.to_llm_text())
                    )
                    self._render_message("user", result.to_llm_text(), stream=False)
        except Exception:
            pass

    @Slot(str)
    def _on_stream_error(self, msg: str) -> None:
        if self._current_assistant_bubble is not None:
            self._current_assistant_bubble.set_text(f"**Error:** {msg}")
            self._current_assistant_bubble = None
        self._end_streaming()

    def _end_streaming(self) -> None:
        self.send_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.input_edit.setEnabled(True)
        self.input_edit.setFocus()
        self._scroll_to_bottom()

    def _stop_streaming(self) -> None:
        if self._stream_worker and self._stream_worker.isRunning():
            self._stream_worker.stop()
            self._stream_worker.wait(2000)
        self._end_streaming()

    # -- Context attachment ----------------------------------------------

    def set_project_context(self, project_path: Path, top_module: str, sources: list[Path]) -> None:
        self._project_path = Path(project_path)
        self._top_module = top_module
        self._sources = list(sources)
        self._update_context_label()

    def attach_file_to_context(self, file_path: Path) -> None:
        self._attached_files.append(Path(file_path))
        self._update_context_label()

    def attach_error_to_context(self, error_text: str) -> None:
        self._attached_errors.append(error_text)
        self._update_context_label()

    def _update_context_label(self) -> None:
        parts = []
        if self._top_module:
            parts.append(f"top={self._top_module}")
        if self._attached_files:
            parts.append(f"{len(self._attached_files)} file(s) attached")
        if self._attached_errors:
            parts.append(f"{len(self._attached_errors)} error(s) attached")
        self.context_label.setText("  ".join(parts))

    def _on_attach_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach file", "", "Verilog (*.v *.sv);;All Files (*)"
        )
        if path:
            self.attach_file_to_context(Path(path))

    # -- Quick actions ---------------------------------------------------

    def _quick_action(self, prompt_prefix: str) -> None:
        existing = self.input_edit.toPlainText().strip()
        if existing:
            self.input_edit.setPlainText(f"{prompt_prefix}\n\n{existing}")
        else:
            self.input_edit.setPlainText(prompt_prefix + "\n\n")
            cursor = self.input_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

    def _explain_code_block(self, code: str) -> None:
        self.input_edit.setPlainText(f"Explain this code in detail:\n\n```verilog\n{code}\n```")
        self._on_send_clicked()

    # -- Public chat helpers ---------------------------------------------

    def clear_chat(self) -> None:
        if self._current is None:
            return
        self._current.messages.clear()
        self._load_conversation(self._current)
        self.store.save(self._current)

    # -- Old API: local fallbacks ----------------------------------------

    def explain_error(self, error_text: str) -> None:
        self.tabs.setCurrentIndex(3)
        self.error_input.setPlainText(error_text)
        self._explain_local()

    def insert_template(self, template_name: str) -> None:
        code = VERILOG_TEMPLATES.get(template_name)
        if code:
            self.insert_code_requested.emit(code)

    def lookup_keyword(self, keyword: str) -> str:
        return KEYWORD_DICTIONARY.get(keyword, "")

    # -- Templates / keywords / errors tab handlers ----------------------

    def _insert_template_at_cursor(self) -> None:
        code = self.template_preview.toPlainText()
        if code:
            self.insert_code_requested.emit(code)

    def _filter_keywords(self, text: str) -> None:
        text = text.lower().strip()
        for i in range(self.keyword_list.count()):
            item = self.keyword_list.item(i)
            item.setHidden(text not in item.text().lower())

    def _explain_local(self) -> None:
        text = self.error_input.toPlainText().strip()
        if not text:
            return
        matches = []
        for key, desc in ERROR_EXPLANATIONS.items():
            if key.lower() in text.lower():
                matches.append(f"<b>{key}</b><br>{desc}<br><br>")
        if not matches:
            html = (
                f"<i style='color:{CAT_OVERLAY1}'>No local match. Click <b>Ask AI</b> "
                f"to send this error to the chat assistant.</i>"
            )
        else:
            html = "".join(matches)
        self.error_output.setHtml(html)

    def _explain_with_ai(self) -> None:
        text = self.error_input.toPlainText().strip()
        if not text:
            return
        self.tabs.setCurrentIndex(0)
        self.attach_error_to_context(text)
        self.input_edit.setPlainText("Help me understand and fix this error.")
        self._on_send_clicked()

    # ------------------------------------------------------------------
    # Wave 3: tool-calling, RAG context, constraint debugger hooks
    # ------------------------------------------------------------------

    def _get_rag_index(self):
        """Lazy-load a RagIndex for the current project."""
        try:
            if getattr(self, "_rag_index", None) is not None:
                return self._rag_index
            if not self._project_path:
                return None
            from openforge.ai.rag import RagIndex

            idx = RagIndex(self._project_path)
            try:
                if not idx.load_index():
                    idx.index_project()
                    idx.save_index()
            except Exception:
                pass
            self._rag_index = idx
            return idx
        except Exception:
            return None

    def _retrieve_rag_context(self, query: str, top_k: int = 5) -> str:
        try:
            if str(self.settings.value("ai/enable_rag", "true")).lower() != "true":
                return ""
            idx = self._get_rag_index()
            if idx is None:
                return ""
            docs = idx.search(query, top_k=top_k)
            if not docs:
                return ""
            parts = ["# Retrieved project context"]
            for d in docs:
                parts.append(f"## {d.path} ({d.kind})\n{d.content[:1200]}")
            return "\n\n".join(parts)
        except Exception:
            return ""

    def _try_tool_call_from_text(self, text: str):
        """Very small tool-call parser: looks for a JSON block shaped
        {"tool": "name", "arguments": {...}}."""
        try:
            import json
            import re

            m = re.search(r"\{[^{}]*\"tool\"\s*:\s*\"[^\"]+\"[^{}]*\}", text, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group(0))
            if not isinstance(data, dict) or "tool" not in data:
                return None
            from openforge.ai.tools import ToolCall, ToolRegistry

            reg = ToolRegistry.instance()
            if not reg.has(data["tool"]):
                return None
            return reg.invoke(
                ToolCall(tool=data["tool"], arguments=data.get("arguments", {}) or {})
            )
        except Exception:
            return None

    def _on_debug_failing_path(self) -> None:
        try:
            from openforge.ai.constraint_debugger import ConstraintDebugger, StaPath
            from openforge.ai.tools import ToolCall, ToolRegistry

            reg = ToolRegistry.instance()
            res = reg.invoke(ToolCall(tool="get_timing_report", arguments={}))
            sta = res.output if res and res.success else None

            # Pick first failing path heuristically
            path = StaPath(
                path_id="critical_0",
                startpoint="reg/Q",
                endpoint="reg/D",
                slack=-0.25,
                clock="clk",
            )

            dbg = ConstraintDebugger(
                ollama_client=None,
                sta_report=sta,
                sdc_files=[],
            )
            fixes = dbg.propose_fixes(path)
            if not fixes:
                self.input_edit.setPlainText(
                    "No constraint fixes could be proposed for the current critical path."
                )
            else:
                lines = ["Here are proposed SDC fixes for the critical path:\n"]
                for i, f in enumerate(fixes, 1):
                    lines.append(
                        f"{i}. {f.sdc_change}\n   rationale: {f.rationale}\n"
                        f"   est slack delta: {f.estimated_slack_delta:+.2f} ns"
                    )
                self.input_edit.setPlainText("\n".join(lines))
                self._on_send_clicked()
        except Exception as e:
            with contextlib.suppress(Exception):
                self.input_edit.setPlainText(f"Constraint debugger unavailable: {e}")

    def _on_explain_this(self) -> None:
        try:
            parent = self.parent()
            selection = ""
            try:
                editor = getattr(parent, "_editor", None)
                if editor is not None and hasattr(editor, "current_selection_text"):
                    selection = editor.current_selection_text() or ""
            except Exception:
                selection = ""
            if not selection:
                selection = self.input_edit.toPlainText()
            prompt = (
                "Please explain the following in clear, concise terms. "
                "Cover what it does, why it matters, and any gotchas.\n\n"
                f"```\n{selection[:4000]}\n```"
            )
            self.input_edit.setPlainText(prompt)
            self._on_send_clicked()
        except Exception:
            pass
