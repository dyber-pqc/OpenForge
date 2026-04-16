"""Synthesis job routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from openforge_api.models.schemas import (
    JobBase,
    JobStatus,
    SynthesisRequest,
    SynthesisResult,
)

router = APIRouter()
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory stores (placeholder)
# ---------------------------------------------------------------------------

_synth_jobs: dict[UUID, JobBase] = {}
_synth_results: dict[UUID, SynthesisResult] = {}
_synth_netlists: dict[UUID, str] = {}


# ---------------------------------------------------------------------------
# Async dispatch
# ---------------------------------------------------------------------------

async def _dispatch_synthesis(job_id: UUID, body: SynthesisRequest) -> None:
    """Background task: run synthesis via SynthesisRunner."""
    try:
        _synth_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.running,
            created_at=_synth_jobs[job_id].created_at,
        )

        from openforge.synthesis.runner import SynthesisRunner

        # Resolve project path from project_id (placeholder -- use projects dir)
        project_path = Path.cwd()
        runner = SynthesisRunner(project_path, config=None)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: runner.run_synthesis(
                sources=[],  # filled from project file list
                top_module="top",
                pdk=body.target_pdk,
            ),
        )

        _synth_results[job_id] = SynthesisResult(
            job_id=job_id,
            gate_count=result.gate_count,
            area_um2=result.area_um2,
            cell_usage=result.cell_usage,
            timing_met=result.timing_estimate_ns >= 0,
            worst_slack_ns=result.timing_estimate_ns,
            netlist_url=f"/synth/{job_id}/netlist",
        )

        # Store netlist content if available
        if hasattr(result, "netlist_content") and result.netlist_content:
            _synth_netlists[job_id] = result.netlist_content

        _synth_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.completed if result.success else JobStatus.failed,
            created_at=_synth_jobs[job_id].created_at,
            finished_at=datetime.utcnow(),
        )
    except Exception:
        _log.exception("Synthesis failed for job %s", job_id)
        _synth_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.failed,
            created_at=_synth_jobs[job_id].created_at,
            finished_at=datetime.utcnow(),
        )


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

    _synth_jobs[job_id] = job
    asyncio.create_task(_dispatch_synthesis(job_id, body))
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
