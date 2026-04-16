"""Crypto verification routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

from openforge_api.models.schemas import (
    CryptoAnalysisRequest,
    CryptoAnalysisResult,
    CryptoAnalysisType,
    JobBase,
    JobStatus,
    SecurityScore,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory stores (placeholder)
# ---------------------------------------------------------------------------

_crypto_jobs: dict[UUID, tuple[JobBase, CryptoAnalysisType]] = {}
_crypto_results: dict[UUID, CryptoAnalysisResult] = {}
_security_scores: dict[UUID, SecurityScore] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_crypto_job(
    body: CryptoAnalysisRequest,
    analysis_type: CryptoAnalysisType,
) -> JobBase:
    """Create and store a new crypto analysis job."""
    job_id = uuid4()
    now = datetime.utcnow()
    job = JobBase(
        job_id=job_id,
        project_id=body.project_id,
        status=JobStatus.queued,
        created_at=now,
    )
    _crypto_jobs[job_id] = (job, analysis_type)
    return job


# ---------------------------------------------------------------------------
# Analysis endpoints
# ---------------------------------------------------------------------------


@router.post("/constant-time", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_constant_time_analysis(body: CryptoAnalysisRequest) -> JobBase:
    """Run constant-time analysis on a cryptographic module."""
    return _create_crypto_job(body, CryptoAnalysisType.constant_time)


@router.post("/side-channel", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_side_channel_analysis(body: CryptoAnalysisRequest) -> JobBase:
    """Run side-channel analysis simulation."""
    return _create_crypto_job(body, CryptoAnalysisType.side_channel)


@router.post("/fips", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_fips_compliance(body: CryptoAnalysisRequest) -> JobBase:
    """Run FIPS 140-3 compliance checks."""
    return _create_crypto_job(body, CryptoAnalysisType.fips)


@router.post("/entropy", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_entropy_analysis(body: CryptoAnalysisRequest) -> JobBase:
    """Run entropy flow analysis."""
    return _create_crypto_job(body, CryptoAnalysisType.entropy)


@router.post("/fault-injection", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_fault_injection(body: CryptoAnalysisRequest) -> JobBase:
    """Run fault-injection campaign against a cryptographic module."""
    return _create_crypto_job(body, CryptoAnalysisType.fault_injection)


@router.post("/ntt-validation", response_model=JobBase, status_code=status.HTTP_202_ACCEPTED)
async def run_ntt_validation(body: CryptoAnalysisRequest) -> JobBase:
    """Run NTT (Number Theoretic Transform) correctness validation."""
    return _create_crypto_job(body, CryptoAnalysisType.ntt_validation)


# ---------------------------------------------------------------------------
# Result retrieval
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_model=CryptoAnalysisResult)
async def get_crypto_result(job_id: UUID) -> CryptoAnalysisResult:
    """Get the result of a crypto analysis job."""
    if job_id not in _crypto_jobs:
        raise HTTPException(status_code=404, detail="Crypto analysis job not found")

    result = _crypto_results.get(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crypto analysis results not yet available",
        )
    return result


@router.get("/security-score/{project_id}", response_model=SecurityScore)
async def get_security_score(project_id: UUID) -> SecurityScore:
    """Get the aggregate security score for a project.

    Combines results from all crypto analyses run against the project.
    """
    score = _security_scores.get(project_id)
    if score is None:
        raise HTTPException(
            status_code=404,
            detail="No security score available for this project",
        )
    return score
