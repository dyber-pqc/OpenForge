"""Analysis routes -- STA, power, DRC, LVS."""

from __future__ import annotations

import asyncio
import logging
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
_log = logging.getLogger(__name__)


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


def _finish_job(job_id: UUID, success: bool) -> None:
    """Mark a job as completed or failed."""
    job = _analysis_jobs.get(job_id)
    if job is not None:
        _analysis_jobs[job_id] = JobBase(
            job_id=job.job_id,
            project_id=job.project_id,
            status=JobStatus.completed if success else JobStatus.failed,
            created_at=job.created_at,
            finished_at=datetime.utcnow(),
        )


# ---------------------------------------------------------------------------
# Timing (STA) -- dispatches OpenSTAEngine via asyncio
# ---------------------------------------------------------------------------

async def _dispatch_timing(job_id: UUID, body: TimingRequest) -> None:
    """Background task: run STA engine and store results."""
    try:
        _analysis_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.running,
            created_at=_analysis_jobs[job_id].created_at,
        )

        from openforge.physical.timing import TimingAnalyzer

        analyzer = TimingAnalyzer()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: analyzer.run_analysis(
                liberty=body.liberty,
                netlist=body.netlist,
                sdc=body.sdc if body.sdc else "constraints.sdc",
            ),
        )

        _timing_results[job_id] = TimingResult(
            job_id=job_id,
            wns_ns=result.wns,
            tns_ns=result.tns,
            paths=[
                {
                    "startpoint": p.start_point,
                    "endpoint": p.end_point,
                    "slack_ns": p.slack_ns,
                    "levels": len(p.stages),
                    "path_type": p.path_type,
                }
                for p in result.paths[:20]
            ],
        )
        _finish_job(job_id, True)
    except Exception as exc:
        _log.exception("Timing analysis failed for job %s", job_id)
        _finish_job(job_id, False)


@router.post("/timing", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_timing_analysis(body: TimingRequest) -> JobBase:
    """Run static timing analysis.

    Dispatched asynchronously -- poll ``GET /analyze/timing/{job_id}``
    for results.
    """
    job = _create_job(body.project_id)
    asyncio.create_task(_dispatch_timing(job.job_id, body))
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
# Power -- dispatches PowerAnalyzer via asyncio
# ---------------------------------------------------------------------------

async def _dispatch_power(job_id: UUID, body: PowerRequest) -> None:
    """Background task: run power analysis and store results."""
    try:
        _analysis_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.running,
            created_at=_analysis_jobs[job_id].created_at,
        )

        from openforge.physical.power import PowerAnalyzer

        analyzer = PowerAnalyzer()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: analyzer.run_power_analysis(
                liberty="sky130_fd_sc_hd__tt_025C_1v80.lib",
                netlist=body.netlist,
                sdc="constraints.sdc",
                activity_file=body.activity if body.activity else None,
            ),
        )

        _power_results[job_id] = PowerResult(
            job_id=job_id,
            total_mw=result.total_mw,
            dynamic_mw=result.dynamic_mw,
            leakage_mw=result.leakage_mw,
            breakdown={
                "internal": result.internal_mw,
                "switching": result.switching_mw,
                **result.by_hierarchy,
            },
        )
        _finish_job(job_id, True)
    except Exception as exc:
        _log.exception("Power analysis failed for job %s", job_id)
        _finish_job(job_id, False)


@router.post("/power", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_power_analysis(body: PowerRequest) -> JobBase:
    """Run power analysis (dynamic + leakage)."""
    job = _create_job(body.project_id)
    asyncio.create_task(_dispatch_power(job.job_id, body))
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
# DRC -- dispatches Magic DRC engine via asyncio
# ---------------------------------------------------------------------------

async def _dispatch_drc(job_id: UUID, body: DrcRequest) -> None:
    """Background task: run DRC and store results."""
    try:
        _analysis_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.running,
            created_at=_analysis_jobs[job_id].created_at,
        )

        from openforge.physical.drc_lvs import DRCRunner

        runner = DRCRunner()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: runner.run_drc(body.layout),
        )

        _drc_results[job_id] = DrcResult(
            job_id=job_id,
            violation_count=result.total_count,
            violations=[
                {
                    "rule": v.rule,
                    "message": v.message,
                    "x": v.x,
                    "y": v.y,
                    "layer": v.layer,
                    "severity": v.severity,
                }
                for v in result.violations[:200]
            ],
            clean=result.passed,
        )
        _finish_job(job_id, True)
    except Exception as exc:
        _log.exception("DRC failed for job %s", job_id)
        _finish_job(job_id, False)


@router.post("/drc", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_drc(body: DrcRequest) -> JobBase:
    """Run design rule check."""
    job = _create_job(body.project_id)
    asyncio.create_task(_dispatch_drc(job.job_id, body))
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
# LVS -- dispatches Netgen LVS engine via asyncio
# ---------------------------------------------------------------------------

async def _dispatch_lvs(job_id: UUID, body: LvsRequest) -> None:
    """Background task: run LVS and store results."""
    try:
        _analysis_jobs[job_id] = JobBase(
            job_id=job_id,
            project_id=body.project_id,
            status=JobStatus.running,
            created_at=_analysis_jobs[job_id].created_at,
        )

        from openforge.physical.drc_lvs import LVSRunner

        runner = LVSRunner()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: runner.run_lvs(
                layout_netlist=body.layout,
                schematic_netlist=body.schematic,
            ),
        )

        _lvs_results[job_id] = LvsResult(
            job_id=job_id,
            match=result.match,
            device_count=result.device_count_layout,
            net_count=result.net_count,
            mismatches=[{"detail": m} for m in result.mismatches],
        )
        _finish_job(job_id, True)
    except Exception as exc:
        _log.exception("LVS failed for job %s", job_id)
        _finish_job(job_id, False)


@router.post("/lvs", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_lvs(body: LvsRequest) -> JobBase:
    """Run layout vs. schematic check."""
    job = _create_job(body.project_id)
    asyncio.create_task(_dispatch_lvs(job.job_id, body))
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
