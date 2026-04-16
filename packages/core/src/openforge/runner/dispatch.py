"""Distributed dispatch for the OpenForge run engine v2.

Lightweight worker node model + HTTP dispatch using only the standard
library. Workers expose a small JSON HTTP API (``/health``, ``/run``,
``/status/{id}``, ``/logs/{id}``, ``/artifact/{id}/{name}``).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .engine import RunStage, RunStatus


class WorkerNode(BaseModel):
    """A remote worker that can execute run stages."""

    model_config = ConfigDict(extra="allow")

    url: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    status: str = "unknown"  # up | down | unknown
    current_load: int = 0
    last_seen: float = 0.0
    max_load: int = 4


class WorkerPool(BaseModel):
    """A pool of worker nodes with basic scheduling."""

    model_config = ConfigDict(extra="allow")

    workers: list[WorkerNode] = Field(default_factory=list)

    def best_for(self, stage: RunStage) -> WorkerNode | None:
        """Return the worker best suited for ``stage`` (lowest load, up)."""
        required = set(getattr(stage, "capabilities", []) or [])
        candidates = [
            w
            for w in self.workers
            if w.status in ("up", "unknown")
            and w.current_load < w.max_load
            and (not required or required.issubset(set(w.capabilities)))
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda w: (w.current_load, w.name))
        return candidates[0]

    def health_check(self, timeout: float = 2.0) -> dict[str, str]:
        """Ping /health on every worker. Returns {url: status}."""
        out: dict[str, str] = {}
        for w in self.workers:
            try:
                with urllib.request.urlopen(f"{w.url}/health", timeout=timeout) as r:
                    if r.status == 200:
                        w.status = "up"
                        w.last_seen = time.time()
                    else:
                        w.status = "down"
            except Exception:
                w.status = "down"
            out[w.url] = w.status
        return out

    def stage_to_worker_payload(self, stage: RunStage) -> dict[str, Any]:
        """Serialize a :class:`RunStage` to a JSON-safe payload for POST /run."""
        return {"stage": stage.model_dump(mode="json")}


def dispatch(stage: RunStage, worker: WorkerNode, poll_interval: float = 0.5,
             timeout: float = 3600.0) -> dict[str, Any]:
    """POST a stage to ``worker``, then poll /status/{id} until terminal.

    Returns the final status dict from the worker.
    """
    payload = json.dumps({"stage": stage.model_dump(mode="json")}).encode("utf-8")
    req = urllib.request.Request(
        f"{worker.url}/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    worker.current_load += 1
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            start = json.loads(r.read().decode("utf-8"))
        run_id = start.get("run_id") or start.get("id")
        if not run_id:
            return {"error": "worker did not return run_id", "raw": start}

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{worker.url}/status/{run_id}", timeout=10
                ) as r:
                    status = json.loads(r.read().decode("utf-8"))
            except Exception as e:
                status = {"error": str(e)}
                time.sleep(poll_interval)
                continue
            st = status.get("status")
            if st in (
                RunStatus.SUCCESS.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
                RunStatus.SKIPPED.value,
            ):
                return status
            time.sleep(poll_interval)
        return {"error": "dispatch timeout", "run_id": run_id}
    finally:
        worker.current_load = max(0, worker.current_load - 1)


# ----- minimal worker HTTP server ------------------------------------------


_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _run_stage_job(job_id: str, stage: RunStage, workdir: Path) -> None:
    import subprocess

    job = _JOBS[job_id]
    job["status"] = RunStatus.RUNNING.value
    job["started_at"] = time.time()
    log_path = workdir / f"{job_id}.log"
    job["log_path"] = str(log_path)
    try:
        if not stage.command:
            job["status"] = RunStatus.SUCCESS.value
            job["exit_code"] = 0
            log_path.write_text("[no-op stage]\n", encoding="utf-8")
            return
        with log_path.open("wb") as logf:
            proc = subprocess.Popen(
                stage.command,
                cwd=stage.cwd or str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            job["pid"] = proc.pid
            assert proc.stdout is not None
            for line in proc.stdout:
                logf.write(line)
                logf.flush()
            rc = proc.wait()
        job["exit_code"] = rc
        job["status"] = (
            RunStatus.SUCCESS.value if rc == 0 else RunStatus.FAILED.value
        )
    except Exception as e:  # noqa: BLE001
        job["status"] = RunStatus.FAILED.value
        job["error"] = str(e)
    finally:
        job["finished_at"] = time.time()


def serve_worker(port: int = 8765, workdir: str | Path | None = None) -> ThreadingHTTPServer:
    """Start a minimal worker HTTP server.

    Exposes:
      - GET  /health
      - POST /run          body: {"stage": {...}}
      - GET  /status/{id}
      - GET  /logs/{id}
      - GET  /artifact/{id}/{name}

    Returns the running :class:`ThreadingHTTPServer`. Call ``.shutdown()`` to stop.
    """
    work = Path(workdir) if workdir else Path.cwd() / ".openforge-worker"
    work.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _json(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path
            if path == "/health":
                self._json(200, {"status": "up", "jobs": len(_JOBS)})
                return
            if path.startswith("/status/"):
                jid = path[len("/status/"):]
                with _JOBS_LOCK:
                    job = _JOBS.get(jid)
                if not job:
                    self._json(404, {"error": "not found"})
                    return
                self._json(200, {"run_id": jid, **{k: v for k, v in job.items() if k != "stage"}})
                return
            if path.startswith("/logs/"):
                jid = path[len("/logs/"):]
                with _JOBS_LOCK:
                    job = _JOBS.get(jid)
                if not job or not job.get("log_path"):
                    self._json(404, {"error": "not found"})
                    return
                try:
                    data = Path(job["log_path"]).read_bytes()
                except Exception as e:
                    self._json(500, {"error": str(e)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith("/artifact/"):
                rest = path[len("/artifact/"):]
                if "/" not in rest:
                    self._json(400, {"error": "bad path"})
                    return
                jid, name = rest.split("/", 1)
                art = work / jid / name
                if not art.exists() or not art.is_file():
                    self._json(404, {"error": "not found"})
                    return
                data = art.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._json(404, {"error": "no such route"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/run":
                self._json(404, {"error": "no such route"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                stage_data = body.get("stage") or {}
                stage = RunStage.model_validate(stage_data)
            except Exception as e:
                self._json(400, {"error": f"bad stage: {e}"})
                return
            job_id = uuid.uuid4().hex[:12]
            job_dir = work / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            with _JOBS_LOCK:
                _JOBS[job_id] = {
                    "status": RunStatus.PENDING.value,
                    "stage_id": stage.id,
                }
            threading.Thread(
                target=_run_stage_job,
                args=(job_id, stage, job_dir),
                name=f"worker-{job_id}",
                daemon=True,
            ).start()
            self._json(202, {"run_id": job_id, "status": RunStatus.PENDING.value})

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name=f"worker-http-{port}", daemon=True).start()
    return server


__all__ = [
    "WorkerNode",
    "WorkerPool",
    "dispatch",
    "serve_worker",
]
