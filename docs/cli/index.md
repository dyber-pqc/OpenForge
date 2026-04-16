# CLI Reference

The OpenForge CLI provides command-line access to all design, verification, and analysis operations. It is designed for scripting, CI/CD pipelines, and headless server environments.

## Installation

The CLI is installed automatically with the `openforge-eda` package:

```bash
pip install openforge-eda
openforge --help
```

Or from source:

```bash
uv run openforge-cli --help
```

## Global Options

```
openforge [OPTIONS] COMMAND [ARGS]...

Options:
  --version         Show version and exit
  --verbose, -v     Increase output verbosity (repeat for debug: -vv)
  --quiet, -q       Suppress non-essential output
  --project PATH    Path to openforge.yaml (default: auto-detect in cwd)
  --help            Show help and exit
```

## Commands

### Project Management

#### `openforge init`

Create a new OpenForge project.

```bash
openforge init <name> [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--pdk <name>` | Target PDK (sky130, gf180mcu) | None |
| `--top <module>` | Top module name | `top` |
| `--target <device>` | FPGA target device | None |
| `--type <type>` | Project type: rtl, fpga, pcb, analog | rtl |
| `--path <dir>` | Output directory | `./<name>` |

Examples:

```bash
openforge init my-counter --pdk sky130 --top counter
openforge init blinky --target ice40-up5k --type fpga
openforge init breakout --type pcb
```

#### `openforge doctor`

Check system health and tool dependencies.

```bash
openforge doctor
```

Reports the status of all EDA tools (installed, version, path) and PDKs.

#### `openforge tools check`

Verify that required EDA tools are installed and accessible.

```bash
openforge tools check
```

### Synthesis

#### `openforge synth`

Run RTL synthesis using Yosys.

```bash
openforge synth [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--top <module>` | Override top module | From config |
| `--pdk <name>` | Override target PDK | From config |
| `--output <dir>` | Output directory | `synth_build/` |
| `--json` | Output results as JSON | Off |

```bash
openforge synth
openforge synth --top counter --pdk sky130
```

### Physical Design

#### `openforge pnr`

Run place-and-route using OpenROAD.

```bash
openforge pnr [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--density <float>` | Target core utilization (0.0-1.0) | 0.65 |
| `--output <dir>` | Output directory | `pnr_build/` |

#### `openforge gds`

Export GDSII layout.

```bash
openforge gds [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--output <file>` | Output GDS file path | `pnr_build/<top>.gds` |

### Timing and Analysis

#### `openforge sta`

Run static timing analysis using OpenSTA.

```bash
openforge sta [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--max-paths <n>` | Number of worst paths to report | 50 |
| `--corner <name>` | PVT corner (tt, ss, ff) | tt |

#### `openforge report`

Generate analysis reports.

```bash
openforge report <type> [OPTIONS]
```

Report types: `area`, `timing`, `power`, `utilization`, `clocks`, `io`.

```bash
openforge report area
openforge report timing --max-paths 100
openforge report power
```

### Sign-off

#### `openforge drc`

Run design rule checking using Magic.

```bash
openforge drc [OPTIONS]
```

#### `openforge lvs`

Run layout vs. schematic checking using Netgen.

```bash
openforge lvs [OPTIONS]
```

### Simulation

#### `openforge sim`

Compile and run simulation.

```bash
openforge sim [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--tool <name>` | Simulator: icarus, verilator, ghdl | From config |
| `--top <module>` | Testbench top module | From config |
| `--coverage` | Enable code coverage | From config |
| `--timeout <secs>` | Max simulation time in seconds | 300 |
| `--plusargs <k=v>` | Additional plusargs (repeatable) | From config |

```bash
openforge sim
openforge sim --tool verilator --coverage
openforge sim --plusargs SEED=42 --plusargs VERBOSE=1
```

#### `openforge wave`

Open a waveform file in the viewer.

```bash
openforge wave <file>
```

Supported formats: VCD, FST.

#### `openforge coverage`

Report code coverage from simulation.

```bash
openforge coverage report [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--format <fmt>` | Output format: text, html, json | text |
| `--output <file>` | Output file (for html/json) | stdout |

### Formal Verification

#### `openforge formal`

Run formal property verification using SymbiYosys.

```bash
openforge formal [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--depth <n>` | Proof depth in cycles | 20 |
| `--engine <name>` | Solver engine (smtbmc, btor, aiger, abc) | smtbmc |

### FPGA

#### `openforge fpga synth`

Synthesize for an FPGA target.

```bash
openforge fpga synth [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--top <module>` | Top module | From config |
| `--device <name>` | Target device | From config |

#### `openforge fpga pnr`

Run FPGA place-and-route.

```bash
openforge fpga pnr
```

#### `openforge fpga bitstream`

Generate a programming bitstream.

```bash
openforge fpga bitstream
```

#### `openforge fpga flash`

Program the FPGA.

```bash
openforge fpga flash [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--sram` | Volatile SRAM programming | Flash (persistent) |

### Crypto Verification

#### `openforge crypto ct-check`

Run constant-time verification.

```bash
openforge crypto ct-check
```

#### `openforge crypto sca`

Run side-channel analysis.

```bash
openforge crypto sca [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--traces <n>` | Number of simulation traces | 10000 |
| `--threshold <f>` | TVLA threshold | 4.5 |

#### `openforge crypto fips`

Run FIPS 140-3 compliance checks.

```bash
openforge crypto fips [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--level <n>` | FIPS level (1-4) | From config |

### PDK Management

#### `openforge pdk install`

Download and install a PDK.

```bash
openforge pdk install <name>
```

Available PDKs: `sky130`, `gf180mcu`.

#### `openforge pdk list`

List installed PDKs.

```bash
openforge pdk list
```

### API Server

#### `openforge serve`

Start the REST API server.

```bash
openforge serve [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--host <addr>` | Bind address | 0.0.0.0 |
| `--port <n>` | Port number | 8000 |
| `--reload` | Auto-reload on code changes | Off |

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Tool not found |
| 4 | Synthesis/simulation failure |
| 5 | Timing violation (STA) |
| 6 | DRC/LVS failure |

## CI/CD Integration

OpenForge CLI is designed for CI pipelines. Example GitHub Actions workflow:

```yaml
name: OpenForge CI
on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    container: openforge/openforge:latest
    steps:
      - uses: actions/checkout@v4
      - run: openforge doctor
      - run: openforge synth
      - run: openforge sim --coverage
      - run: openforge formal --depth 20
      - run: openforge sta
      - run: openforge drc
      - run: openforge lvs
```
