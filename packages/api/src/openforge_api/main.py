"""OpenForge API server entry point."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openforge_api import __version__
from openforge_api.routes import projects, verification, ws

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
app.include_router(ws.router, tags=["websocket"])

# TODO: Include synthesis router once implemented
# from openforge_api.routes import synthesis
# app.include_router(synthesis.router, prefix="/synth", tags=["synthesis"])

# TODO: Include waveforms router once implemented
# from openforge_api.routes import waveforms
# app.include_router(waveforms.router, prefix="/waveforms", tags=["waveforms"])


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
