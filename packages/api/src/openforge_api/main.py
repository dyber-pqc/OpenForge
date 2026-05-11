"""OpenForge API server entry point."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openforge_api import __version__
from openforge_api.auth import router as auth_router
from openforge_api.cloud_dispatch import register_handlers
from openforge_api.job_queue import get_queue
from openforge_api.routes import (
    analysis,
    crypto,
    files,
    projects,
    signoff,
    synthesis,
    tools,
    verification,
    waveforms,
    ws,
)
from openforge_api.websocket import router as ws_jobs_router
from openforge_api.websocket import setup_websocket

app = FastAPI(
    title="OpenForge EDA API",
    version=__version__,
    description="REST API for the OpenForge open-source hardware design & verification toolkit.",
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers ----
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(verification.router, prefix="/verify", tags=["verification"])
app.include_router(synthesis.router, prefix="/synth", tags=["synthesis"])
app.include_router(signoff.router, prefix="/signoff", tags=["signoff"])
app.include_router(analysis.router, prefix="/analyze", tags=["analysis"])
app.include_router(waveforms.router, prefix="/waveforms", tags=["waveforms"])
app.include_router(crypto.router, prefix="/crypto", tags=["crypto"])
app.include_router(files.router, prefix="/files", tags=["files"])
app.include_router(tools.router, prefix="/tools", tags=["tools"])
app.include_router(ws.router, tags=["websocket"])
app.include_router(ws_jobs_router, tags=["jobs-ws"])
app.include_router(auth_router, tags=["auth"])


@app.on_event("startup")
async def _phase9_startup() -> None:
    register_handlers()
    setup_websocket(app)
    queue = get_queue()
    await queue.start()


@app.on_event("shutdown")
async def _phase9_shutdown() -> None:
    queue = get_queue()
    await queue.stop()


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Health-check endpoint."""
    return {"status": "ok", "version": __version__}


def run() -> None:
    """Start the API server (used by the console-script entry point)."""
    uvicorn.run(
        "openforge_api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    run()
