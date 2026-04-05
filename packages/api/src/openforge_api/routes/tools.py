"""Tool status and installation routes."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

from openforge_api.models.schemas import JobBase, JobStatus, ToolInfo

router = APIRouter()


# ---------------------------------------------------------------------------
# Known tools registry (placeholder)
# ---------------------------------------------------------------------------

_KNOWN_TOOLS: dict[str, ToolInfo] = {
    "yosys": ToolInfo(
        name="yosys",
        display_name="Yosys",
        docker_image="hdlc/yosys:latest",
        description="Open-source synthesis suite",
    ),
    "openroad": ToolInfo(
        name="openroad",
        display_name="OpenROAD",
        docker_image="openroad/openroad:latest",
        description="RTL-to-GDS flow (place & route, STA, CTS)",
    ),
    "verilator": ToolInfo(
        name="verilator",
        display_name="Verilator",
        docker_image="verilator/verilator:latest",
        description="Fast Verilog/SystemVerilog simulator",
    ),
    "iverilog": ToolInfo(
        name="iverilog",
        display_name="Icarus Verilog",
        docker_image="hdlc/iverilog:latest",
        description="Verilog simulation and synthesis tool",
    ),
    "magic": ToolInfo(
        name="magic",
        display_name="Magic VLSI",
        docker_image="hdlc/magic:latest",
        description="Layout editor, DRC, extraction, and LVS",
    ),
    "netgen": ToolInfo(
        name="netgen",
        display_name="Netgen",
        docker_image="hdlc/netgen:latest",
        description="LVS netlist comparison",
    ),
    "klayout": ToolInfo(
        name="klayout",
        display_name="KLayout",
        docker_image="hdlc/klayout:latest",
        description="Layout viewer and DRC/LVS engine",
    ),
    "opensta": ToolInfo(
        name="opensta",
        display_name="OpenSTA",
        docker_image="openroad/opensta:latest",
        description="Static timing analysis",
    ),
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List all known EDA tools with installed status and version."""
    # TODO: Probe Docker for actual installed state and versions
    return list(_KNOWN_TOOLS.values())


@router.get("/{name}", response_model=ToolInfo)
async def get_tool(name: str) -> ToolInfo:
    """Get details for a specific EDA tool."""
    tool = _KNOWN_TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")
    return tool


@router.post(
    "/{name}/install",
    response_model=JobBase,
    status_code=status.HTTP_202_ACCEPTED,
)
async def install_tool(name: str) -> JobBase:
    """Trigger installation (Docker pull) of an EDA tool.

    Returns a job that can be polled for progress.
    """
    tool = _KNOWN_TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")

    if tool.docker_image is None:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{name}' does not have a Docker image configured",
        )

    from datetime import datetime

    job = JobBase(
        job_id=uuid4(),
        project_id=UUID("00000000-0000-0000-0000-000000000000"),  # system job
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
    )

    # TODO: Dispatch docker pull task
    #   from openforge_api.tasks import pull_docker_image
    #   pull_docker_image.delay(str(job.job_id), tool.docker_image)
    return job
