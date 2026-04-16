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
    import asyncio

    # Engine class mapping for probing installed state
    _ENGINE_MAP: dict[str, tuple[str, str]] = {
        "yosys": ("openforge.engine.yosys", "YosysEngine"),
        "openroad": ("openforge.engine.openroad", "OpenROADEngine"),
        "verilator": ("openforge.engine.verilator", "VerilatorEngine"),
        "iverilog": ("openforge.engine.icarus", "IcarusEngine"),
        "magic": ("openforge.engine.magic", "MagicEngine"),
        "netgen": ("openforge.engine.netgen", "NetgenEngine"),
        "klayout": ("openforge.engine.klayout", "KLayoutEngine"),
        "opensta": ("openforge.engine.opensta", "OpenSTAEngine"),
    }

    loop = asyncio.get_running_loop()

    async def _check(name: str, info: ToolInfo) -> ToolInfo:
        if name not in _ENGINE_MAP:
            return info
        mod_name, cls_name = _ENGINE_MAP[name]
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            engine_cls = getattr(mod, cls_name)
            engine = engine_cls()
            installed = await loop.run_in_executor(None, engine.check_installed)
            version = ""
            if installed:
                version = await loop.run_in_executor(None, engine.version)
            return ToolInfo(
                name=info.name,
                display_name=info.display_name,
                version=version if installed else None,
                installed=installed,
                docker_image=info.docker_image,
                description=info.description,
            )
        except Exception:
            return info

    results = await asyncio.gather(
        *[_check(name, info) for name, info in _KNOWN_TOOLS.items()]
    )
    return list(results)


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

    import asyncio

    async def _pull(j_id: UUID, image: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "pull", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    asyncio.create_task(_pull(job.job_id, tool.docker_image))
    return job
