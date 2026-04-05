"""Synthesis job routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from openforge_api.models.schemas import (
    JobBase,
    JobStatus,
    SynthesisOptimization,
    SynthesisRequest,
    SynthesisResult,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory stores (placeholder)
# ---------------------------------------------------------------------------

_synth_jobs: dict[UUID, JobBase] = {}
_synth_results: dict[UUID, SynthesisResult] = {}
_synth_netlists: dict[UUID, str] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def start_synthesis(body: SynthesisRequest) -> JobBase:
    """Start a synthesis job.

    The job is dispatched asynchronously; poll ``GET /synth/{job_id}``
    for status updates.
    """
    job_id = uuid4()
    now = datetime.utcnow()

    job = JobBase(
        job_id=job_id,
        project_id=body.project_id,
        status=JobStatus.queued,
        created_at=now,
    )

    # TODO: Dispatch to task queue
    #   from openforge_api.tasks import run_synthesis
    #   run_synthesis.delay(str(job_id), body.model_dump())
    _synth_jobs[job_id] = job
    return job


@router.get("/{job_id}", response_model=JobBase)
async def get_synthesis_status(job_id: UUID) -> JobBase:
    """Get the current status of a synthesis job."""
    job = _synth_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Synthesis job not found")
    return job


@router.get("/{job_id}/results", response_model=SynthesisResult)
async def get_synthesis_results(job_id: UUID) -> SynthesisResult:
    """Get synthesis results including gate count, area, cell usage, and timing."""
    if job_id not in _synth_jobs:
        raise HTTPException(status_code=404, detail="Synthesis job not found")

    result = _synth_results.get(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Synthesis results not yet available",
        )
    return result


@router.get("/{job_id}/netlist")
async def download_netlist(job_id: UUID) -> Response:
    """Download the synthesised netlist for a completed job."""
    if job_id not in _synth_jobs:
        raise HTTPException(status_code=404, detail="Synthesis job not found")

    netlist = _synth_netlists.get(job_id)
    if netlist is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Netlist not yet available",
        )

    return Response(
        content=netlist,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=synth_{job_id}.v"},
    )
