"""Analysis routes -- STA, power, DRC, LVS."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

from openforge_api.models.schemas import (
    DrcRequest,
    DrcResult,
    JobBase,
    JobStatus,
    LvsRequest,
    LvsResult,
    PowerRequest,
    PowerResult,
    TimingRequest,
    TimingResult,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory stores (placeholder)
# ---------------------------------------------------------------------------

_analysis_jobs: dict[UUID, JobBase] = {}
_timing_results: dict[UUID, TimingResult] = {}
_power_results: dict[UUID, PowerResult] = {}
_drc_results: dict[UUID, DrcResult] = {}
_lvs_results: dict[UUID, LvsResult] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_job(project_id: UUID) -> JobBase:
    """Create and store a new analysis job."""
    job_id = uuid4()
    now = datetime.utcnow()
    job = JobBase(
        job_id=job_id,
        project_id=project_id,
        status=JobStatus.queued,
        created_at=now,
    )
    _analysis_jobs[job_id] = job
    return job


def _get_job_or_404(job_id: UUID) -> JobBase:
    job = _analysis_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return job


# ---------------------------------------------------------------------------
# Timing (STA)
# ---------------------------------------------------------------------------

@router.post("/timing", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_timing_analysis(body: TimingRequest) -> JobBase:
    """Run static timing analysis.

    Dispatched asynchronously -- poll ``GET /analyze/timing/{job_id}``
    for results.
    """
    job = _create_job(body.project_id)
    # TODO: Dispatch STA engine
    return job


@router.get("/timing/{job_id}", response_model=TimingResult)
async def get_timing_results(job_id: UUID) -> TimingResult:
    """Get timing analysis results (WNS, TNS, critical paths, histogram)."""
    _get_job_or_404(job_id)
    result = _timing_results.get(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Timing results not yet available",
        )
    return result


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------

@router.post("/power", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_power_analysis(body: PowerRequest) -> JobBase:
    """Run power analysis (dynamic + leakage)."""
    job = _create_job(body.project_id)
    # TODO: Dispatch power engine
    return job


@router.get("/power/{job_id}", response_model=PowerResult)
async def get_power_results(job_id: UUID) -> PowerResult:
    """Get power analysis results."""
    _get_job_or_404(job_id)
    result = _power_results.get(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Power results not yet available",
        )
    return result


# ---------------------------------------------------------------------------
# DRC
# ---------------------------------------------------------------------------

@router.post("/drc", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_drc(body: DrcRequest) -> JobBase:
    """Run design rule check."""
    job = _create_job(body.project_id)
    # TODO: Dispatch DRC engine
    return job


@router.get("/drc/{job_id}", response_model=DrcResult)
async def get_drc_results(job_id: UUID) -> DrcResult:
    """Get DRC results."""
    _get_job_or_404(job_id)
    result = _drc_results.get(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="DRC results not yet available",
        )
    return result


# ---------------------------------------------------------------------------
# LVS
# ---------------------------------------------------------------------------

@router.post("/lvs", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_lvs(body: LvsRequest) -> JobBase:
    """Run layout vs. schematic check."""
    job = _create_job(body.project_id)
    # TODO: Dispatch LVS engine
    return job


@router.get("/lvs/{job_id}", response_model=LvsResult)
async def get_lvs_results(job_id: UUID) -> LvsResult:
    """Get LVS results."""
    _get_job_or_404(job_id)
    result = _lvs_results.get(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LVS results not yet available",
        )
    return result
