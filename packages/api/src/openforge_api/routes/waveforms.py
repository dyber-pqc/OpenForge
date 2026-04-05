"""Waveform management routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, UploadFile, status

from openforge_api.models.schemas import (
    SignalData,
    SignalInfo,
    WaveformMetadata,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory stores (placeholder)
# ---------------------------------------------------------------------------

_waveforms: dict[UUID, WaveformMetadata] = {}
_waveform_signals: dict[UUID, list[SignalInfo]] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=WaveformMetadata, status_code=status.HTTP_201_CREATED)
async def upload_waveform(
    file: UploadFile,
    project_id: UUID = Query(..., description="Project the waveform belongs to"),
) -> WaveformMetadata:
    """Upload a VCD or FST waveform file.

    The file is parsed asynchronously; signal metadata becomes
    available once parsing completes.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    suffix = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ("vcd", "fst"):
        raise HTTPException(status_code=400, detail="Only VCD and FST files are supported")

    waveform_id = uuid4()
    now = datetime.utcnow()

    # TODO: Persist file to storage and parse asynchronously
    _content = await file.read()

    metadata = WaveformMetadata(
        id=waveform_id,
        project_id=project_id,
        filename=file.filename,
        format=suffix,
        signal_count=0,
        time_start=0,
        time_end=0,
        uploaded_at=now,
    )
    _waveforms[waveform_id] = metadata
    _waveform_signals[waveform_id] = []

    return metadata


@router.get("/{waveform_id}", response_model=WaveformMetadata)
async def get_waveform_metadata(waveform_id: UUID) -> WaveformMetadata:
    """Get metadata for an uploaded waveform file."""
    wf = _waveforms.get(waveform_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Waveform not found")
    return wf


@router.get("/{waveform_id}/signals", response_model=list[SignalInfo])
async def list_signals(
    waveform_id: UUID,
    search: str = Query("", description="Substring filter on signal name"),
    scope: str = Query("", description="Filter by hierarchy scope"),
    limit: int = Query(500, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> list[SignalInfo]:
    """List signals in a waveform with optional search and filter."""
    if waveform_id not in _waveforms:
        raise HTTPException(status_code=404, detail="Waveform not found")

    signals = _waveform_signals.get(waveform_id, [])

    if search:
        signals = [s for s in signals if search.lower() in s.name.lower()]
    if scope:
        signals = [s for s in signals if s.scope.startswith(scope)]

    return signals[offset : offset + limit]


@router.get("/{waveform_id}/data", response_model=SignalData)
async def get_signal_data(
    waveform_id: UUID,
    signals: str = Query(..., description="Comma-separated signal names"),
    start: int = Query(0, ge=0, description="Start time"),
    end: int = Query(0, ge=0, description="End time (0 = full range)"),
) -> SignalData:
    """Get time-series data for selected signals within a time range.

    Returns data in a JSON format compatible with the web WaveformViewer
    component.
    """
    wf = _waveforms.get(waveform_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Waveform not found")

    signal_names = [s.strip() for s in signals.split(",") if s.strip()]
    if not signal_names:
        raise HTTPException(status_code=400, detail="At least one signal name is required")

    effective_end = end if end > 0 else wf.time_end

    # TODO: Read actual waveform data from parsed file
    return SignalData(
        waveform_id=waveform_id,
        signals={name: [] for name in signal_names},
        time_start=start,
        time_end=effective_end,
    )
