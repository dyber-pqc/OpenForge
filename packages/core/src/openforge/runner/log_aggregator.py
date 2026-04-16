"""Log aggregator for the OpenForge run engine v2.

Tails per-stage log files, strips ANSI colour codes, detects severity,
and fans events out to subscribers. Used by the desktop log panel and
the API websocket stream.
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


_SEV_PATTERNS: list[tuple[re.Pattern[str], LogLevel]] = [
    (re.compile(r"\b(fatal|panic)\b", re.I), LogLevel.FATAL),
    (re.compile(r"\b(error|err|failed|failure|traceback)\b", re.I), LogLevel.ERROR),
    (re.compile(r"\b(warn|warning)\b", re.I), LogLevel.WARN),
    (re.compile(r"\b(debug|trace)\b", re.I), LogLevel.DEBUG),
]


def _detect_level(message: str) -> LogLevel:
    for pat, level in _SEV_PATTERNS:
        if pat.search(message):
            return level
    return LogLevel.INFO


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class LogEntry(BaseModel):
    """A single aggregated log line."""

    model_config = ConfigDict(extra="allow")

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: str
    level: LogLevel = LogLevel.INFO
    message: str
    run_id: str | None = None
    stage_id: str | None = None


class LogFilter(BaseModel):
    """Filter used by LogAggregator consumers."""

    model_config = ConfigDict(extra="allow")

    levels: list[LogLevel] | None = None
    source: str | None = None
    stage: str | None = None
    pattern: str | None = None  # regex

    def matches(self, entry: LogEntry) -> bool:
        if self.levels and entry.level not in self.levels:
            return False
        if self.source and self.source not in entry.source:
            return False
        if self.stage and entry.stage_id != self.stage:
            return False
        if self.pattern:
            try:
                if not re.search(self.pattern, entry.message):
                    return False
            except re.error:
                return False
        return True


Subscriber = Callable[[LogEntry], None]


class LogAggregator:
    """Tail per-stage log files and stream :class:`LogEntry` events."""

    def __init__(self) -> None:
        self._subs: list[Subscriber] = []
        self._entries: list[LogEntry] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ----- subscribers ------------------------------------------------------

    def subscribe(self, cb: Subscriber) -> None:
        with self._lock:
            self._subs.append(cb)

    def unsubscribe(self, cb: Subscriber) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._subs.remove(cb)

    def entries(self, flt: LogFilter | None = None) -> list[LogEntry]:
        with self._lock:
            snap = list(self._entries)
        if flt is None:
            return snap
        return [e for e in snap if flt.matches(e)]

    # ----- ingest -----------------------------------------------------------

    def ingest_line(
        self,
        source: str,
        message: str,
        run_id: str | None = None,
        stage_id: str | None = None,
    ) -> LogEntry:
        msg = _strip_ansi(message.rstrip("\r\n"))
        entry = LogEntry(
            source=source,
            level=_detect_level(msg),
            message=msg,
            run_id=run_id,
            stage_id=stage_id,
        )
        with self._lock:
            self._entries.append(entry)
            subs = list(self._subs)
        for cb in subs:
            with contextlib.suppress(Exception):
                cb(entry)
        return entry

    def tail_file(
        self,
        path: str | Path,
        source: str,
        run_id: str | None = None,
        stage_id: str | None = None,
    ) -> None:
        """Start tailing ``path`` in a background thread."""
        p = Path(path)

        def _run() -> None:
            # wait for file to exist
            while not p.exists() and not self._stop.is_set():
                time.sleep(0.1)
            if self._stop.is_set():
                return
            with p.open("r", encoding="utf-8", errors="replace") as f:
                while not self._stop.is_set():
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    self.ingest_line(source, line, run_id=run_id, stage_id=stage_id)

        t = threading.Thread(target=_run, name=f"tail-{p.name}", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    # ----- export -----------------------------------------------------------

    def save_unified_log(self, output_path: str | Path) -> Path:
        """Write a single merged log (timestamp-ordered) to ``output_path``."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            snap = sorted(self._entries, key=lambda e: e.timestamp)
        lines = []
        for e in snap:
            src = e.source
            if e.stage_id:
                src = f"{src}:{e.stage_id}"
            lines.append(f"[{e.timestamp}] [{e.level.value:<5}] [{src}] {e.message}")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out


__all__ = [
    "LogAggregator",
    "LogEntry",
    "LogFilter",
    "LogLevel",
]
