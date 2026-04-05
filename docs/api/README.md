# OpenForge REST API Reference

The OpenForge API provides a RESTful interface for managing hardware design projects, running verification jobs, and streaming live tool output. It powers the web IDE frontend and can be used standalone for CI/CD integration.

## Table of Contents

- [Running the Server](#running-the-server)
- [Authentication](#authentication)
- [Base URL](#base-url)
- [Endpoints](#endpoints)
  - [Health Check](#health-check)
  - [Projects](#projects)
  - [Verification Jobs](#verification-jobs)
- [WebSocket](#websocket)
- [Error Handling](#error-handling)

## Running the Server

```bash
# Via the console-script entry point
openforge-api

# Or directly with uvicorn
uvicorn openforge_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation is available at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc` (ReDoc) when the server is running.

## Authentication

Authentication is not enforced in the current development release. Future versions will integrate JWT-based authentication with Keycloak as the identity provider.

Planned authentication flow:
1. Obtain a JWT token from the Keycloak `/token` endpoint.
2. Pass the token in the `Authorization: Bearer <token>` header on all requests.
3. The API validates the token signature and extracts user claims.

## Base URL

```
http://localhost:8000
```

All endpoint paths below are relative to this base URL.

---

## Endpoints

### Health Check

#### `GET /health`

Returns server status and version.

**Response** `200 OK`:
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

### Projects

#### `GET /projects/`

List all projects.

**Response** `200 OK`:
```json
[
  {
    "id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
    "name": "my-crypto-core",
    "created_at": "2026-03-15T10:30:00Z"
  }
]
```

#### `POST /projects/`

Create a new project.

**Request body**:
```json
{
  "name": "my-crypto-core",
  "description": "AES-256 accelerator with constant-time guarantees",
  "template": "crypto-accelerator"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Project name (1-128 characters) |
| `description` | string | no | Project description (max 1024 characters) |
| `template` | string | no | Template to scaffold from: `crypto-accelerator`, `simple-counter`, or `empty` (default: `empty`) |

**Response** `201 Created`:
```json
{
  "id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
  "name": "my-crypto-core",
  "description": "AES-256 accelerator with constant-time guarantees",
  "template": "crypto-accelerator",
  "created_at": "2026-03-15T10:30:00Z",
  "updated_at": "2026-03-15T10:30:00Z"
}
```

#### `GET /projects/{project_id}`

Get a project by its UUID.

**Response** `200 OK`:
```json
{
  "id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
  "name": "my-crypto-core",
  "description": "AES-256 accelerator with constant-time guarantees",
  "template": "crypto-accelerator",
  "created_at": "2026-03-15T10:30:00Z",
  "updated_at": "2026-03-15T10:30:00Z"
}
```

**Response** `404 Not Found`:
```json
{
  "detail": "Project not found"
}
```

#### `DELETE /projects/{project_id}`

Delete a project and its associated files.

**Response** `204 No Content` (empty body on success).

**Response** `404 Not Found`:
```json
{
  "detail": "Project not found"
}
```

---

### Verification Jobs

#### `POST /verify/`

Submit a verification job. The job is dispatched asynchronously; poll `GET /verify/{job_id}` for status updates, or subscribe via WebSocket.

**Request body**:
```json
{
  "project_id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
  "engines": ["sim", "formal"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_id` | UUID | yes | The project to verify |
| `engines` | array | yes | Verification engines to run: `sim`, `formal`, `crypto` |

**Response** `202 Accepted`:
```json
{
  "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff",
  "project_id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
  "engines": ["sim", "formal"],
  "status": "queued",
  "created_at": "2026-03-15T10:35:00Z"
}
```

#### `GET /verify/{job_id}`

Get the current status of a verification job.

**Response** `200 OK`:
```json
{
  "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff",
  "project_id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
  "engines": ["sim", "formal"],
  "status": "running",
  "created_at": "2026-03-15T10:35:00Z",
  "finished_at": null
}
```

Job status values: `queued`, `running`, `passed`, `failed`, `error`.

#### `GET /verify/{job_id}/results`

Get full results for a completed verification job, including per-engine outcomes.

**Response** `200 OK`:
```json
{
  "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff",
  "project_id": "b3f1a2c4-5678-9abc-def0-1234567890ab",
  "status": "passed",
  "results": [
    {
      "engine": "sim",
      "status": "passed",
      "duration_s": 12.5,
      "log_url": "/logs/a1b2c3d4/sim.log",
      "summary": "All 15 tests passed"
    },
    {
      "engine": "formal",
      "status": "passed",
      "duration_s": 45.2,
      "log_url": "/logs/a1b2c3d4/formal.log",
      "summary": "BMC depth 100: all properties hold"
    }
  ],
  "created_at": "2026-03-15T10:35:00Z",
  "finished_at": "2026-03-15T10:36:02Z"
}
```

---

## WebSocket

#### `WS /ws`

Bidirectional WebSocket for live tool output streaming and job status notifications.

### Client-to-Server Messages

**Ping** (keep-alive):
```json
{"type": "ping"}
```

**Subscribe to job updates**:
```json
{"type": "subscribe", "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff"}
```

### Server-to-Client Messages

**Pong**:
```json
{"type": "pong"}
```

**Subscription confirmation**:
```json
{"type": "subscribed", "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff"}
```

**Job status update** (broadcast to all subscribers):
```json
{
  "type": "job_update",
  "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff",
  "status": "running",
  "step": "simulation",
  "output": null
}
```

**Live tool output** (streamed line-by-line during execution):
```json
{
  "type": "tool_output",
  "job_id": "a1b2c3d4-5678-9abc-def0-aabbccddeeff",
  "tool": "verilator",
  "line": "- Compiling top.sv...",
  "level": "info"
}
```

Output `level` values: `info`, `warning`, `error`.

**Error**:
```json
{
  "type": "error",
  "message": "Unknown message type: foobar"
}
```

---

## Error Handling

All error responses follow the standard FastAPI error format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request (validation error) |
| 404 | Resource not found |
| 422 | Unprocessable entity (Pydantic validation failure) |
| 500 | Internal server error |

Validation errors (422) include field-level details:

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    }
  ]
}
```

---

Copyright 2026 Dyber Inc. | [engineering@dyber.io](mailto:engineering@dyber.io)
