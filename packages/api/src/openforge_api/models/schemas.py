"""Shared Pydantic v2 models for the OpenForge API."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

# ---------------------------------------------------------------------------
# Common / Job infrastructure
# ---------------------------------------------------------------------------

class JobStatus(StrEnum):
    """Lifecycle state for any asynchronous job."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    error = "error"


class JobBase(BaseModel):
    """Fields common to every job."""

    job_id: UUID
    project_id: UUID
    status: JobStatus
    created_at: datetime
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    """Request body for creating a project."""

    name: str = Field(..., min_length=1, max_length=128, examples=["my-crypto-core"])
    description: str = Field("", max_length=1024)
    template: str = Field("empty", examples=["crypto-accelerator", "simple-counter", "empty"])


class ProjectSummary(BaseModel):
    """Abbreviated project info for list views."""

    id: UUID
    name: str
    created_at: datetime


class ProjectDetail(BaseModel):
    """Full project representation."""

    id: UUID
    name: str
    description: str
    template: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

class SynthesisOptimization(StrEnum):
    """Optimisation target for synthesis."""

    area = "area"
    speed = "speed"
    balanced = "balanced"


class SynthesisRequest(BaseModel):
    """Request body to launch a synthesis job."""

    project_id: UUID
    target_pdk: str = Field(..., min_length=1, examples=["sky130", "gf180mcu"])
    optimization: SynthesisOptimization = SynthesisOptimization.balanced
    flatten: bool = False


class SynthesisResult(BaseModel):
    """Results produced by a completed synthesis job."""

    job_id: UUID
    gate_count: int
    area_um2: float = Field(..., description="Total cell area in um^2")
    cell_usage: dict[str, int] = Field(default_factory=dict, description="Cell name -> instance count")
    timing_met: bool
    worst_slack_ns: float | None = None
    netlist_url: str | None = None


# ---------------------------------------------------------------------------
# Timing / STA
# ---------------------------------------------------------------------------

class TimingRequest(BaseModel):
    """Request body to run static timing analysis."""

    project_id: UUID
    liberty: str = Field(..., description="Path or identifier for the Liberty (.lib) file")
    netlist: str = Field(..., description="Path or identifier for the gate-level netlist")
    sdc: str = Field("", description="Path or identifier for the SDC constraints file")


class TimingPath(BaseModel):
    """A single critical timing path."""

    startpoint: str
    endpoint: str
    slack_ns: float
    levels: int
    path_type: str = Field("setup", examples=["setup", "hold"])


class TimingResult(BaseModel):
    """Full timing analysis results."""

    job_id: UUID
    wns_ns: float = Field(..., description="Worst negative slack (ns)")
    tns_ns: float = Field(..., description="Total negative slack (ns)")
    paths: list[TimingPath] = Field(default_factory=list)
    histogram: dict[str, int] = Field(
        default_factory=dict,
        description="Slack-bin label -> path count",
    )


# ---------------------------------------------------------------------------
# Power / DRC / LVS  (request bodies)
# ---------------------------------------------------------------------------

class PowerRequest(BaseModel):
    """Request body for power analysis."""

    project_id: UUID
    netlist: str
    activity: str = Field("", description="Switching-activity file (SAIF/VCD)")
    corner: str = Field("typical", examples=["typical", "fast", "slow"])


class PowerResult(BaseModel):
    """Power analysis results."""

    job_id: UUID
    total_mw: float
    dynamic_mw: float
    leakage_mw: float
    breakdown: dict[str, float] = Field(default_factory=dict)


class DrcRequest(BaseModel):
    """Request body for DRC."""

    project_id: UUID
    layout: str = Field(..., description="GDS/OASIS layout identifier")
    rule_deck: str = Field("", description="Rule deck override")


class DrcResult(BaseModel):
    """DRC results."""

    job_id: UUID
    violation_count: int
    violations: list[dict[str, str | int | float]] = Field(default_factory=list)
    clean: bool


class LvsRequest(BaseModel):
    """Request body for LVS."""

    project_id: UUID
    layout: str
    schematic: str


class LvsResult(BaseModel):
    """LVS results."""

    job_id: UUID
    match: bool
    device_count: int
    net_count: int
    mismatches: list[dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------------

class SignalInfo(BaseModel):
    """Metadata for a single signal in a waveform file."""

    name: str
    width: int = 1
    scope: str = ""
    signal_type: str = Field("wire", examples=["wire", "reg", "integer"])


class WaveformMetadata(BaseModel):
    """Top-level metadata for an uploaded waveform."""

    id: UUID
    project_id: UUID
    filename: str
    format: str = Field(..., examples=["vcd", "fst"])
    signal_count: int
    time_start: int
    time_end: int
    time_unit: str = Field("ns", examples=["ps", "ns", "us", "ms"])
    uploaded_at: datetime


class SignalData(BaseModel):
    """Time-series data for one or more signals."""

    waveform_id: UUID
    signals: dict[str, list[tuple[int, str]]] = Field(
        ...,
        description="Signal name -> list of (time, value) transitions",
    )
    time_start: int
    time_end: int


# ---------------------------------------------------------------------------
# Crypto verification
# ---------------------------------------------------------------------------

class CryptoAnalysisType(StrEnum):
    """Kind of crypto analysis."""

    constant_time = "constant-time"
    side_channel = "side-channel"
    fips = "fips"
    entropy = "entropy"
    fault_injection = "fault-injection"
    ntt_validation = "ntt-validation"


class CryptoAnalysisRequest(BaseModel):
    """Generic request body for crypto analyses."""

    project_id: UUID
    target: str = Field(..., description="Module or function to analyze")
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)


class CryptoAnalysisResult(BaseModel):
    """Result of a single crypto analysis."""

    job_id: UUID
    analysis_type: CryptoAnalysisType
    status: JobStatus
    passed: bool
    score: float = Field(0.0, ge=0.0, le=100.0)
    findings: list[dict[str, str | int | float | bool]] = Field(default_factory=list)
    report_url: str | None = None


class SecurityScore(BaseModel):
    """Aggregate security posture for a project."""

    project_id: UUID
    overall_score: float = Field(..., ge=0.0, le=100.0)
    breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Analysis type -> individual score",
    )
    last_evaluated: datetime


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------

class FileNode(BaseModel):
    """A node in the project file tree."""

    name: str
    path: str
    is_dir: bool
    size: int = 0
    children: list[FileNode] = Field(default_factory=list)


class FileContent(BaseModel):
    """File content read/write payload."""

    path: str
    content: str
    language: str = Field("", description="Detected/specified language for syntax highlighting")


class FileCreateRequest(BaseModel):
    """Request to create a new file."""

    path: str
    content: str = ""
    is_dir: bool = False


class FileSearchResult(BaseModel):
    """A single grep match."""

    path: str
    line_number: int
    line: str


# ---------------------------------------------------------------------------
# Tool management
# ---------------------------------------------------------------------------

class ToolInfo(BaseModel):
    """Information about an EDA tool."""

    name: str
    display_name: str
    version: str | None = None
    installed: bool = False
    docker_image: str | None = None
    description: str = ""
