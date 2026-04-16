# API Reference

The OpenForge REST API provides programmatic access to all design, verification, and analysis operations. It enables remote execution, web-based interfaces, and CI/CD integration.

## Starting the Server

```bash
openforge serve --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker run -d -p 8000:8000 openforge/openforge openforge-api
```

The API server runs on FastAPI with automatic OpenAPI documentation available at:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

## Authentication

The API supports JWT token authentication for multi-user deployments. For local development, authentication is disabled by default.

```bash
# Get a token
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "changeme"}'

# Use the token
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/projects/
```

## Endpoints

### System

#### `GET /health`

Health check endpoint.

**Response:**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### Projects

#### `GET /projects/`

List all projects.

#### `POST /projects/`

Create a new project.

**Request body:**

```json
{
  "name": "my-counter",
  "top_module": "counter",
  "target_pdk": "sky130",
  "sources": ["src/counter.v"],
  "constraints": ["constraints/timing.sdc"]
}
```

#### `GET /projects/{project_id}`

Get project details.

#### `DELETE /projects/{project_id}`

Delete a project.

### Synthesis

#### `POST /synth/run`

Run synthesis on a project.

**Request body:**

```json
{
  "project_id": "my-counter",
  "top_module": "counter",
  "target_pdk": "sky130"
}
```

**Response:**

```json
{
  "success": true,
  "gate_count": 42,
  "area_um2": 327.6,
  "cell_usage": {
    "sky130_fd_sc_hd__dfxtp_1": 8,
    "sky130_fd_sc_hd__and2_1": 7,
    "sky130_fd_sc_hd__inv_1": 12
  },
  "netlist_path": "synth_build/counter.json",
  "duration": 1.4
}
```

#### `GET /synth/status/{job_id}`

Check synthesis job status.

### Verification

#### `POST /verify/simulate`

Run a simulation.

**Request body:**

```json
{
  "project_id": "my-counter",
  "testbench": "tb/counter_tb.v",
  "tool": "icarus",
  "timeout_seconds": 300
}
```

**Response:**

```json
{
  "success": true,
  "duration": 0.3,
  "wave_file": "sim_build/dump.vcd",
  "test_results": [
    {"name": "Reset value", "status": "pass"},
    {"name": "Count to 10", "status": "pass"}
  ]
}
```

#### `POST /verify/formal`

Run formal verification.

**Request body:**

```json
{
  "project_id": "my-counter",
  "properties": ["properties/counter_props.sv"],
  "engine": "smtbmc",
  "depth": 20
}
```

### Analysis

#### `POST /analyze/timing`

Run static timing analysis.

**Response:**

```json
{
  "wns": 2.34,
  "tns": 0.0,
  "timing_met": true,
  "critical_paths": [
    {
      "slack": 2.34,
      "startpoint": "counter_reg[0]",
      "endpoint": "counter_reg[7]",
      "levels": 8,
      "data_delay": 7.66
    }
  ]
}
```

#### `POST /analyze/power`

Run power analysis.

### Crypto

#### `POST /crypto/ct-check`

Run constant-time verification.

#### `POST /crypto/sca`

Run side-channel analysis.

#### `POST /crypto/fips`

Run FIPS compliance checks.

### Files

#### `GET /files/{project_id}/{path}`

Read a file from a project.

#### `PUT /files/{project_id}/{path}`

Write a file to a project.

### Tools

#### `GET /tools/`

List available EDA tools and their installation status.

**Response:**

```json
{
  "tools": [
    {"name": "yosys", "installed": true, "version": "0.38", "path": "/usr/bin/yosys"},
    {"name": "openroad", "installed": true, "version": "2.0", "path": "/usr/bin/openroad"},
    {"name": "iverilog", "installed": true, "version": "12.0", "path": "/usr/bin/iverilog"}
  ]
}
```

### Waveforms

#### `GET /waveforms/{project_id}/{file}`

Stream waveform data from a VCD/FST file.

### WebSocket

#### `WS /ws`

WebSocket endpoint for real-time job status and console output streaming.

**Message format:**

```json
{
  "type": "output",
  "job_id": "synth-001",
  "line": "[INFO] Synthesis complete in 1.4s"
}
```

#### `WS /ws/jobs`

WebSocket endpoint for job queue status updates.

## Auto-Generated API Docs

Full API documentation is auto-generated from the FastAPI source code. Run the server and visit `/docs` for the interactive Swagger UI, or run:

```bash
python installer/generate_docs.py
```

This generates Markdown reference pages from the Python source into `docs/api/` for offline reading. The generator extracts module docstrings, class definitions, method signatures, and type annotations from all five packages (core, CLI, API, desktop, crypto).

## Python Client

You can use any HTTP client to interact with the API. Here is an example with `httpx`:

```python
import httpx

client = httpx.Client(base_url="http://localhost:8000")

# Run synthesis
response = client.post("/synth/run", json={
    "project_id": "my-counter",
    "top_module": "counter",
    "target_pdk": "sky130",
})
result = response.json()
print(f"Gate count: {result['gate_count']}")
print(f"Area: {result['area_um2']} um^2")
```
