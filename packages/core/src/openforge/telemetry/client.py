"""Opt-in, anonymous telemetry client.

Disabled by default. When enabled, batches events to an HTTP endpoint
every 60 seconds using a background thread. No PII is ever captured -
only: which panels were used, which flows ran, error categories, and
coarse performance metrics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import threading
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_VERSION = "0.1.0"


class TelemetryEvent(BaseModel):
    event_type: str
    timestamp: str
    session_id: str
    install_id: str
    platform: str
    version: str
    properties: dict = Field(default_factory=dict)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _install_id() -> str:
    """Stable, anonymous install id derived from hostname + user."""
    try:
        raw = f"{platform.node()}|{platform.system()}|{Path.home().name}"
    except Exception:  # noqa: BLE001
        raw = "unknown"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class TelemetryClient:
    """Batching telemetry client. Thread-safe. No-op when disabled."""

    def __init__(
        self,
        endpoint: str | None = None,
        enabled: bool = False,
        version: str = _VERSION,
        flush_interval_s: float = 60.0,
    ) -> None:
        self.endpoint = endpoint or "https://telemetry.openforge.dev/v1/events"
        self.enabled = enabled
        self.version = version
        self.flush_interval_s = flush_interval_s
        self.session_id = str(uuid.uuid4())
        self._install_id = _install_id()
        self._platform = f"{platform.system()}-{platform.machine()}"
        self._buffer: list[TelemetryEvent] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        if self.enabled:
            self._start_worker()

    # ------------------------------------------------------------------
    def install_id(self) -> str:
        return self._install_id

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if on and self._thread is None:
            self._start_worker()
        elif not on:
            self._stop.set()

    # ------------------------------------------------------------------
    def event(self, name: str, **properties) -> None:
        if not self.enabled:
            return
        ev = TelemetryEvent(
            event_type=name,
            timestamp=_iso_now(),
            session_id=self.session_id,
            install_id=self._install_id,
            platform=self._platform,
            version=self.version,
            properties=self._scrub(properties),
        )
        with self._lock:
            self._buffer.append(ev)

    def time(self, stage: str, duration_s: float, success: bool) -> None:
        self.event("timing", stage=stage, duration_s=round(duration_s, 3), success=bool(success))

    def error(self, error_type: str, message: str) -> None:
        # Only coarse error category, never full messages (might contain paths).
        self.event("error", error_type=error_type, message_len=len(message or ""))

    def flush(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            batch = list(self._buffer)
            self._buffer.clear()
        if not batch:
            return
        try:
            payload = json.dumps(
                {"events": [e.model_dump() for e in batch]},
                separators=(",", ":"),
            ).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": f"openforge/{self.version}"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)  # noqa: S310
            logger.debug("telemetry: flushed %d events", len(batch))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            logger.debug("telemetry flush failed: %s", exc)
            # drop the batch - don't let telemetry buffering grow unbounded

    # ------------------------------------------------------------------
    @staticmethod
    def _scrub(props: dict) -> dict:
        """Remove obvious PII. Drops any value that looks like a path."""
        clean: dict = {}
        for k, v in (props or {}).items():
            if k.lower() in {"path", "file", "filename", "project", "project_name", "user", "email"}:
                continue
            if isinstance(v, str) and (("/" in v) or ("\\" in v)):
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                clean[k] = v
            else:
                clean[k] = str(type(v).__name__)
        return clean

    # ------------------------------------------------------------------
    def _start_worker(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="openforge-telemetry", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.flush_interval_s)
            if self._stop.is_set():
                break
            try:
                self.flush()
            except Exception as exc:  # noqa: BLE001
                logger.debug("telemetry worker error: %s", exc)
        # Final flush on shutdown
        try:
            self.flush()
        except Exception:  # noqa: BLE001
            pass


_client_singleton: TelemetryClient | None = None


def get_client() -> TelemetryClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = TelemetryClient(enabled=False)
    return _client_singleton


def configure(enabled: bool, endpoint: str | None = None, version: str = _VERSION) -> TelemetryClient:
    global _client_singleton
    _client_singleton = TelemetryClient(endpoint=endpoint, enabled=enabled, version=version)
    return _client_singleton
