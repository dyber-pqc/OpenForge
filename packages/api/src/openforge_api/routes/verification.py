"""Verification job routes."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class VerificationEngine(str, Enum):
    sim = "sim"
    formal = "formal"
    crypto = "crypto"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    passed = "passed"
    failed = "failed"
    error = "error"


class VerifyRequest(BaseModel):
    """Request body to start a verification job."""

    project_id: UUID
    engines: list[VerificationEngine] = Field(
        ...,
        min_length=1,
        examples=[["sim", "formal"]],
    )


class VerifyJobSummary(BaseModel):
    """Returned when a job is created or its status is queried."""

    job_id: UUID
    project_id: UUID
    engines: list[VerificationEngine]
    status: JobStatus
    created_at: datetime
    finished_at: datetime | None = None


class EngineResult(BaseModel):
    """Result from a single verification engine."""

    engine: VerificationEngine
    status: JobStatus
    duration_s: float | None = None
    log_url: str | None = None
    summary: str = ""


class VerifyJobResults(BaseModel):
    """Full results for a completed verification job."""

    job_id: UUID
    project_id: UUID
    status: JobStatus
    results: list[EngineResult]
    created_at: datetime
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# In-memory store (placeholder)
# ---------------------------------------------------------------------------

_jobs: dict[UUID, VerifyJobResults] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=VerifyJobSummary, status_code=status.HTTP_202_ACCEPTED)
async def start_verification(body: VerifyRequest) -> VerifyJobSummary:
    """Submit a verification job.

    The job is dispatched asynchronously; poll GET /verify/{job_id} for status.
    """
    job_id = uuid4()
    now = datetime.utcnow()

    # Build placeholder results per engine
    engine_results = [
        EngineResult(engine=eng, status=JobStatus.queued)
        for eng in body.engines
    ]

    job = VerifyJobResults(
        job_id=job_id,
        project_id=body.project_id,
        status=JobStatus.queued,
        results=engine_results,
        created_at=now,
    )

    # TODO: Dispatch to Celery task queue
    #   from openforge_api.tasks import run_verification
    #   run_verification.delay(str(job_id), str(body.project_id), [e.value for e in body.engines])
    _jobs[job_id] = job

    return VerifyJobSummary(
        job_id=job_id,
        project_id=body.project_id,
        engines=body.engines,
        status=JobStatus.queued,
        created_at=now,
    )


@router.get("/{job_id}", response_model=VerifyJobSummary)
async def get_job_status(job_id: UUID) -> VerifyJobSummary:
    """Get the current status of a verification job."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Verification job not found")

    return VerifyJobSummary(
        job_id=job.job_id,
        project_id=job.project_id,
        engines=[r.engine for r in job.results],
        status=job.status,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@router.get("/{job_id}/results", response_model=VerifyJobResults)
async def get_job_results(job_id: UUID) -> VerifyJobResults:
    """Get full results for a verification job.

    Returns per-engine outcomes including logs and timing.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Verification job not found")
    return job
