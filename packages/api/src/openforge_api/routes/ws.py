"""WebSocket endpoint for live updates during verification/simulation runs."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Active WebSocket connections
_connections: set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket for streaming live tool output and job status updates."""
    await websocket.accept()
    _connections.add(websocket)

    try:
        while True:
            # Keep connection alive, receive client messages
            data = await websocket.receive_text()
            msg = json.loads(data)

            # Handle client commands
            match msg.get("type"):
                case "ping":
                    await websocket.send_json({"type": "pong"})
                case "subscribe":
                    # Subscribe to job updates
                    job_id = msg.get("job_id")
                    await websocket.send_json({
                        "type": "subscribed",
                        "job_id": job_id,
                    })
                case _:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg.get('type')}",
                    })
    except WebSocketDisconnect:
        _connections.discard(websocket)
    except Exception:
        _connections.discard(websocket)


async def broadcast(message: dict[str, Any]) -> None:
    """Broadcast a message to all connected WebSocket clients."""
    dead: set[WebSocket] = set()
    for ws in _connections:
        try:
            await ws.send_json(message)
        except Exception:
            dead.add(ws)
    _connections -= dead


async def send_job_update(
    job_id: str,
    status: str,
    step: str | None = None,
    output: str | None = None,
) -> None:
    """Send a job status update to all connected clients."""
    await broadcast({
        "type": "job_update",
        "job_id": job_id,
        "status": status,
        "step": step,
        "output": output,
    })


async def send_tool_output(
    job_id: str,
    tool: str,
    line: str,
    level: str = "info",
) -> None:
    """Stream a line of tool output to connected clients."""
    await broadcast({
        "type": "tool_output",
        "job_id": job_id,
        "tool": tool,
        "line": line,
        "level": level,
    })
