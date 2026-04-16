"""WebSocket endpoints for real-time job updates and log streaming."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from openforge_api.job_queue import Job, JobStatus, get_queue

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Tracks active WebSocket clients and routes broadcasts."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self.log_subscriptions: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new connection."""
        await ws.accept()
        async with self._lock:
            self.active.append(ws)
        logger.info("WebSocket connected (active=%d)", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a connection from all tracking lists."""
        if ws in self.active:
            self.active.remove(ws)
        for job_id, subs in list(self.log_subscriptions.items()):
            if ws in subs:
                subs.remove(ws)
            if not subs:
                self.log_subscriptions.pop(job_id, None)
        logger.info("WebSocket disconnected (active=%d)", len(self.active))

    async def broadcast(self, data: dict) -> None:
        """Send a JSON message to all connected clients."""
        text = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in self.active[:]:
            try:
                await ws.send_text(text)
            except Exception as exc:
                logger.debug("Broadcast failed: %s", exc)
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, data: dict) -> None:
        """Send a JSON message to a specific client."""
        try:
            await ws.send_text(json.dumps(data))
        except Exception as exc:
            logger.debug("send_to failed: %s", exc)
            self.disconnect(ws)

    async def subscribe_log(self, job_id: str, ws: WebSocket) -> None:
        """Attach a websocket to a job's log stream."""
        async with self._lock:
            self.log_subscriptions.setdefault(job_id, []).append(ws)

    def connection_count(self) -> int:
        return len(self.active)


manager = ConnectionManager()


def _job_to_payload(job: Job) -> dict:
    """Serialize a Job for transport over the websocket."""
    return {
        "id": job.id,
        "type": job.type.value,
        "status": job.status.value,
        "project_id": job.project_id,
        "user_id": job.user_id,
        "progress": job.progress,
        "error": job.error,
        "result": job.result,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def _on_job_update(job: Job) -> None:
    """Subscriber callback: broadcast job updates to all websocket clients."""
    await manager.broadcast(
        {
            "type": "job_update",
            "job": _job_to_payload(job),
        }
    )


def setup_websocket(app: Any) -> None:
    """Register the websocket subscriber with the global queue."""
    queue = get_queue()
    queue.subscribe(_on_job_update)
    logger.info("WebSocket subscriber registered with JobQueue")


# ---------------------------------------------------------------- endpoints
@router.websocket("/ws/jobs")
async def websocket_jobs(ws: WebSocket) -> None:
    """Receive real-time job updates for every job in the system."""
    await manager.connect(ws)
    queue = get_queue()
    try:
        # Push the current state of the world so the client can render immediately.
        await manager.send_to(
            ws,
            {
                "type": "initial",
                "jobs": [_job_to_payload(j) for j in queue.list_jobs(limit=100)],
                "stats": queue.stats(),
            },
        )

        while True:
            try:
                data = await ws.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_to(ws, {"type": "error", "detail": "bad json"})
                continue

            kind = msg.get("type")
            if kind == "ping":
                await manager.send_to(ws, {"type": "pong"})
            elif kind == "subscribe":
                # Every connection already receives all broadcasts; this is
                # a no-op for now but preserved for API symmetry with the
                # per-user filtering story we want later.
                await manager.send_to(ws, {"type": "subscribed"})
            elif kind == "list":
                await manager.send_to(
                    ws,
                    {
                        "type": "list",
                        "jobs": [_job_to_payload(j) for j in queue.list_jobs(limit=100)],
                    },
                )
            elif kind == "cancel":
                job_id = msg.get("job_id", "")
                ok = await queue.cancel(job_id)
                await manager.send_to(ws, {"type": "cancel_ack", "job_id": job_id, "ok": ok})
            elif kind == "stats":
                await manager.send_to(ws, {"type": "stats", "stats": queue.stats()})
            else:
                await manager.send_to(ws, {"type": "error", "detail": f"unknown message: {kind}"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("WebSocket error: %s", exc)
    finally:
        manager.disconnect(ws)


@router.websocket("/ws/job/{job_id}/log")
async def websocket_job_log(ws: WebSocket, job_id: str) -> None:
    """Stream logs for a specific job."""
    await ws.accept()
    queue = get_queue()
    job = queue.get_job(job_id)
    if job is None:
        await ws.close(code=4404, reason="Job not found")
        return

    try:
        last_idx = 0
        # Replay any existing log lines so late subscribers don't miss context.
        while True:
            new_lines = job.log_lines[last_idx:]
            for line in new_lines:
                try:
                    await ws.send_text(line)
                except Exception:
                    return
            last_idx = len(job.log_lines)

            terminal = job.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            )
            if terminal:
                try:
                    await ws.send_text(f"[{job.status.value.upper()}]")
                    if job.error:
                        await ws.send_text(f"[ERROR] {job.error}")
                except Exception:
                    pass
                break

            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("log stream error: %s", exc)
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


@router.websocket("/ws/stats")
async def websocket_stats(ws: WebSocket) -> None:
    """Emit periodic queue statistics."""
    await ws.accept()
    queue = get_queue()
    try:
        while True:
            try:
                await ws.send_text(json.dumps({"type": "stats", "stats": queue.stats()}))
            except Exception:
                break
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
