"""Pure-stdlib Ollama HTTP client.

Talks to a local Ollama daemon (default ``http://localhost:11434``)
using only :mod:`urllib`. Supports listing models, pulling models with
progress callbacks, streaming chat/generate responses, and embeddings.

The client never raises on connection errors from :meth:`is_running` or
:meth:`list_models` — those return falsy values so callers can decide
how to surface "Ollama not installed" in the UI.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Iterator


class OllamaClient:
    """Minimal HTTP client for the local Ollama REST API."""

    def __init__(self, host: str = "http://localhost:11434", timeout: float = 30.0) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=2.0) as r:
                return r.status == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def pull(self, model: str, callback: Callable[[dict], None] | None = None) -> bool:
        body = json.dumps({"name": model, "stream": True}).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/api/pull",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout * 30) as r:
                for raw in r:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if callback is not None:
                        try:
                            callback(msg)
                        except Exception:
                            pass
                    if msg.get("status") in ("success",) or msg.get("error"):
                        return msg.get("status") == "success"
            return True
        except urllib.error.URLError:
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict],
        stream: bool = True,
        options: dict | None = None,
    ) -> Iterator[str]:
        body = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if options:
            body["options"] = options
        yield from self._post_stream("/api/chat", body, stream, key="message")

    def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        stream: bool = True,
        options: dict | None = None,
    ) -> Iterator[str]:
        body: dict = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if options:
            body["options"] = options
        yield from self._post_stream("/api/generate", body, stream, key="response")

    def embed(self, model: str, text: str) -> list[float]:
        body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return list(data.get("embedding", []))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post_stream(
        self, path: str, body: dict, stream: bool, key: str
    ) -> Iterator[str]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.host + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout * 10) as r:
                if not stream:
                    payload = json.loads(r.read().decode("utf-8"))
                    chunk = payload.get(key)
                    if isinstance(chunk, dict):
                        yield chunk.get("content", "")
                    elif isinstance(chunk, str):
                        yield chunk
                    return
                for raw in r:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = msg.get(key)
                    if isinstance(chunk, dict):
                        text = chunk.get("content", "")
                    else:
                        text = chunk or ""
                    if text:
                        yield text
                    if msg.get("done"):
                        break
        except urllib.error.URLError as e:
            yield f"[ollama error: {e}]"
        except Exception as e:  # pragma: no cover - defensive
            yield f"[ollama error: {e}]"


__all__ = ["OllamaClient"]
