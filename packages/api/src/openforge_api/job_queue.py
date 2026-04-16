"""Async job queue for long-running EDA tasks.

In-memory implementation backed by ``asyncio.Queue``. The design intentionally
mirrors the surface area of Celery / RQ so a Redis-backed worker pool can be
swapped in later without changing call sites.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Lifecycle states for a job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(Enum):
    """All EDA job types the queue knows how to dispatch."""

    SYNTHESIS = "synthesis"
    SIMULATION = "simulation"
    TIMING_ANALYSIS = "timing_analysis"
    PNR = "pnr"
    DRC = "drc"
    LVS = "lvs"
    GDS_EXPORT = "gds_export"
    POWER = "power"
    CDC = "cdc"
    CRYPTO = "crypto"
    REGRESSION = "regression"
    FORMAL = "formal"


@dataclass
class Job:
    """A unit of work managed by the queue."""

    id: str = field(default_factory=lambda: str(uuid4()))
    type: JobType = JobType.SYNTHESIS
    status: JobStatus = JobStatus.QUEUED
    project_id: str = ""
    user_id: str = ""
    payload: dict = field(default_factory=dict)
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    progress: float = 0.0
    log_lines: list[str] = field(default_factory=list)
    worker_id: Optional[int] = None

    def to_dict(self) -> dict:
        """Serialize the job to a JSON-friendly dict."""
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "payload": self.payload,
            "result": self.result,
            "error": self.error,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "log_lines": self.log_lines,
            "worker_id": self.worker_id,
        }

    @property
    def duration(self) -> Optional[float]:
        """Wallclock duration of the run in seconds, if finished."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def append_log(self, line: str) -> None:
        """Append a single log line to the job."""
        self.log_lines.append(line)

    def set_progress(self, value: float) -> None:
        """Clamp + set progress in [0, 1]."""
        if value < 0.0:
            value = 0.0
        if value > 1.0:
            value = 1.0
        self.progress = value


JobHandler = Callable[[Job], Awaitable[dict]]
SubscriberCallback = Callable[[Job], Any]


class JobQueue:
    """Async in-memory job queue with subscriber notifications."""

    def __init__(self, max_workers: int = 4):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._jobs: dict[str, Job] = {}
        self._handlers: dict[JobType, JobHandler] = {}
        self._subscribers: list[SubscriberCallback] = []
        self._workers: list[asyncio.Task] = []
        self._max_workers = max_workers
        self._running = False
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Start the worker pool."""
        if self._running:
            return
        self._running = True
        for i in range(self._max_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"job-worker-{i}")
            self._workers.append(task)
        logger.info("JobQueue started with %d workers", self._max_workers)

    async def stop(self) -> None:
        """Stop the worker pool, cancelling in-flight tasks."""
        self._running = False
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except (asyncio.CancelledError, Exception):
                pass
        self._workers.clear()
        logger.info("JobQueue stopped")

    # ------------------------------------------------------------------ handlers
    def register_handler(self, job_type: JobType, handler: JobHandler) -> None:
        """Register an async handler for a particular job type."""
        self._handlers[job_type] = handler
        logger.debug("Registered handler for %s", job_type.value)

    def has_handler(self, job_type: JobType) -> bool:
        return job_type in self._handlers

    # ------------------------------------------------------------------ submit / query
    async def submit(self, job: Job) -> str:
        """Add a job to the queue."""
        async with self._lock:
            self._jobs[job.id] = job
        await self._queue.put(job)
        await self._notify(job)
        logger.info("Job submitted: %s (%s)", job.id, job.type.value)
        return job.id

    def get_job(self, job_id: str) -> Optional[Job]:
        """Look up a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        status: JobStatus | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> list[Job]:
        """Return jobs matching the given filters, newest first."""
        result = list(self._jobs.values())
        if status is not None:
            result = [j for j in result if j.status == status]
        if user_id is not None:
            result = [j for j in result if j.user_id == user_id]
        if project_id is not None:
            result = [j for j in result if j.project_id == project_id]
        result.sort(key=lambda j: j.created_at, reverse=True)
        if limit is not None:
            result = result[:limit]
        return result

    async def cancel(self, job_id: str) -> bool:
        """Mark a job as cancelled. Returns True if the job existed."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False
        self._cancelled.add(job_id)
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.utcnow()
        await self._notify(job)
        return True

    async def clear_finished(self) -> int:
        """Drop all completed/failed/cancelled jobs from the registry."""
        async with self._lock:
            ids = [
                jid
                for jid, j in self._jobs.items()
                if j.status
                in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
            ]
            for jid in ids:
                del self._jobs[jid]
        return len(ids)

    # ------------------------------------------------------------------ subscribers
    def subscribe(self, callback: SubscriberCallback) -> None:
        """Subscribe to job status updates."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: SubscriberCallback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def _notify(self, job: Job) -> None:
        for sub in list(self._subscribers):
            try:
                if asyncio.iscoroutinefunction(sub):
                    await sub(job)
                else:
                    sub(job)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Subscriber raised: %s", exc)

    # ------------------------------------------------------------------ worker
    async def _worker_loop(self, worker_id: int) -> None:
        """Continuously pull jobs and dispatch them to handlers."""
        logger.info("Worker %d starting", worker_id)
        while self._running:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                if job.id in self._cancelled or job.status == JobStatus.CANCELLED:
                    self._cancelled.discard(job.id)
                    continue

                handler = self._handlers.get(job.type)
                if handler is None:
                    job.status = JobStatus.FAILED
                    job.error = f"No handler registered for job type: {job.type.value}"
                    job.finished_at = datetime.utcnow()
                    await self._notify(job)
                    continue

                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                job.worker_id = worker_id
                await self._notify(job)

                try:
                    result = await handler(job)
                    job.result = result
                    job.status = JobStatus.COMPLETED
                    job.set_progress(1.0)
                except asyncio.CancelledError:
                    job.status = JobStatus.CANCELLED
                    job.error = "Cancelled"
                    raise
                except Exception as exc:
                    logger.exception("Job %s failed", job.id)
                    job.error = str(exc)
                    job.status = JobStatus.FAILED

                job.finished_at = datetime.utcnow()
                await self._notify(job)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Worker %d crashed: %s", worker_id, exc)
        logger.info("Worker %d stopped", worker_id)

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        """Return aggregate counts about the queue."""
        counts: dict[str, int] = {s.value: 0 for s in JobStatus}
        for j in self._jobs.values():
            counts[j.status.value] += 1
        return {
            "total": len(self._jobs),
            "by_status": counts,
            "workers": self._max_workers,
            "queue_depth": self._queue.qsize(),
            "running": self._running,
        }


# ----------------------------------------------------------------------- global
_global_queue: Optional[JobQueue] = None


def get_queue() -> JobQueue:
    """Return the process-wide JobQueue singleton."""
    global _global_queue
    if _global_queue is None:
        _global_queue = JobQueue()
    return _global_queue


def reset_queue() -> None:
    """Reset the global queue (intended for tests)."""
    global _global_queue
    _global_queue = None
