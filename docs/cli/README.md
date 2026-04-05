# OpenForge CLI Reference

The `openforge` command-line tool provides access to all OpenForge EDA operations: project initialization, linting, simulation, synthesis, verification, analysis, and reporting.

## Table of Contents

- [Installation](#installation)
- [Global Options](#global-options)
- [Commands](#commands)
  - [init](#openforge-init)
  - [lint](#openforge-lint)
  - [sim](#openforge-sim)
  - [synth](#openforge-synth)
  - [verify](#openforge-verify)
  - [analyze](#openforge-analyze)
  - [report](#openforge-report)
  - [tools](#openforge-tools)
- [Configuration via openforge.yaml](#configuration-via-openforgeyaml)

## Installation

```bash
# Install from PyPI
pip install openforge

# Or install from source (development mode)
uv pip install -e "packages/core[dev]" -e "packages/cli"
```

## Global Options

```
openforge [OPTIONS] COMMAND [ARGS]

Options:
  -V, --version    Show the OpenForge version and exit.
  --help           Show help message and exit.
```

---

## Commands

### `openforge init`

Create a new OpenForge project from a template.

```
openforge init <name> [OPTIONS]
```

**Arguments**:
| Argument | Required | Description |
|----------|----------|-------------|
| `name` | yes | Project name (used as directory name and top module) |

**Options**:
| Flag | Default | Description |
|------|---------|-------------|
| `--template, -t` | `empty` | Project template: `crypto-accelerator`, `simple-counter`, or `empty` |

**Examples**:
```bash
# Create an empty project
openforge init my-design

# Create a crypto accelerator project with full verification config
openforge init aes-core --template crypto-accelerator

# Create a simple counter with testbench
openforge init counter --template simple-counter
```

**Generated structure** (crypto-accelerator template):
```
aes-core/
├── openforge.yaml          Project configuration
├── src/
│   ├── aes-core.sv         Placeholder RTL module
│   └── include/            Include directory
├── tb/
│   └── tb_aes-core.sv      Basic testbench
├── constraints/
│   └── timing.sdc          Clock constraint (10ns)
└── formal/                 Formal verification properties
```

---

### `openforge lint`

Run Verible lint on HDL source files.

```
openforge lint [path]
```

**Arguments**:
| Argument | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Path to the design directory containing `openforge.yaml` |

**Examples**:
```bash
# Lint the current directory
openforge lint

# Lint a specific project
openforge lint ./projects/my-design
```

The linter reads the `design.sources` glob patterns from `openforge.yaml` to find source files.

---

### `openforge sim`

Compile and run RTL simulation.

```
openforge sim [path] [OPTIONS]
```

**Arguments**:
| Argument | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Path to the design directory |

**Options**:
| Flag | Default | Description |
|------|---------|-------------|
| `--tool, -t` | `verilator` | Simulator backend: `verilator`, `icarus`, or `ghdl` |
| `--waves / --no-waves, -w` | `--waves` | Enable or disable waveform tracing |
| `--timeout` | `300` | Simulation timeout in seconds |

**Examples**:
```bash
# Run simulation with Verilator (default)
openforge sim

# Run with Icarus Verilog, no waveforms, 60s timeout
openforge sim --tool icarus --no-waves --timeout 60

# Simulate a specific project
openforge sim ./projects/counter --tool verilator
```

On success, the waveform file path is printed. Use the desktop IDE or web waveform viewer to inspect traces.

---

### `openforge synth`

Synthesize the design for a target PDK.

```
openforge synth [path] [OPTIONS]
```

**Arguments**:
| Argument | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Path to the design directory |

**Options**:
| Flag | Default | Description |
|------|---------|-------------|
| `--target, -t` | `sky130` | Target PDK: `sky130`, `gf180mcu`, `asap7`, `nangate45` |
| `--top` | from config | Top-level module name (overrides `openforge.yaml`) |
| `--output, -o` | `build` | Output directory for synthesis artifacts |

**Examples**:
```bash
# Synthesize for SkyWater 130nm
openforge synth

# Synthesize for ASAP7 with explicit top module
openforge synth --target asap7 --top aes_sbox

# Custom output directory
openforge synth --target gf180mcu --output artifacts/synth
```

Synthesis uses Yosys with ABC optimization and Liberty-based cell mapping for the target PDK. Results include the gate-level netlist, area statistics, and resource utilization.

---

### `openforge verify`

Run verification engines on a design.

```
openforge verify [path] [OPTIONS]
```

**Arguments**:
| Argument | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Path to the design directory |

**Options**:
| Flag | Description |
|------|-------------|
| `--sim, -s` | Run simulation-based verification |
| `--formal, -f` | Run formal verification (SymbiYosys BMC/k-induction) |
| `--crypto, -c` | Run crypto-specific property checks (constant-time, SCA, FIPS) |
| `--all, -a` | Run all verification engines |

At least one engine flag must be provided, or use `--all`.

**Examples**:
```bash
# Run all verification engines
openforge verify --all

# Run only simulation
openforge verify --sim

# Run formal and crypto verification on a specific project
openforge verify ./projects/aes-core --formal --crypto
```

---

### `openforge analyze`

Analyze design metrics (area, timing, power estimates).

```
openforge analyze [path] [OPTIONS]
```

**Arguments**:
| Argument | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Path to the design directory |

**Options**:
| Flag | Description |
|------|-------------|
| `--timing` | Run static timing analysis via OpenSTA |
| `--power` | Run power estimation |
| `--area` | Show area statistics |

If no flags are provided, defaults to `--timing --area`.

**Examples**:
```bash
# Run timing and area analysis (default)
openforge analyze

# Full analysis with power
openforge analyze --timing --power --area
```

---

### `openforge report`

Generate a verification or synthesis report.

```
openforge report [path] [OPTIONS]
```

**Arguments**:
| Argument | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Path to the design directory |

**Options**:
| Flag | Default | Description |
|------|---------|-------------|
| `--format, -f` | `html` | Report format: `html`, `json`, `sarif`, `junit` |
| `--output, -o` | `reports/` | Output directory for generated reports |

**Examples**:
```bash
# Generate an HTML report
openforge report

# Generate SARIF for CI integration
openforge report --format sarif --output ci-reports/

# Generate JUnit XML for test runners
openforge report --format junit --output test-results/
```

---

### `openforge tools`

Check availability and versions of all EDA tools.

```
openforge tools
```

Prints a status table showing which tools are installed and their versions:

```
       OpenForge Tool Status
┌────────────┬─────────┬─────────┐
│ Tool       │ Status  │ Version │
├────────────┼─────────┼─────────┤
│ verilator  │ OK      │ 5.024   │
│ yosys      │ OK      │ 0.40    │
│ verible    │ Missing │ -       │
│ iverilog   │ OK      │ 12.0    │
│ ghdl       │ Missing │ -       │
│ symbiyosys │ OK      │ 0.42    │
│ opensta    │ Missing │ -       │
└────────────┴─────────┴─────────┘
```

---

## Configuration via openforge.yaml

All CLI commands read project settings from `openforge.yaml` in the design directory. Here is an annotated example:

```yaml
# ── Project metadata ─────────────────────────────────────────────
project:
  name: "aes-accelerator"         # Project name (used as default top module)
  top_module: "aes_accelerator"   # Top-level module name
  target_pdk: "sky130"            # Target PDK for synthesis

# ── Design sources ───────────────────────────────────────────────
design:
  sources:                        # Glob patterns for RTL files
    - src/*.sv
    - src/*.v
  includes:                       # Include search directories
    - src/include/
  constraints:                    # Timing constraint files (SDC)
    - constraints/timing.sdc

# ── Verification ─────────────────────────────────────────────────
verification:
  simulation:
    tool: verilator               # Simulator: verilator, icarus, ghdl
    testbenches:
      - tb/tb_aes_accelerator.sv
    coverage:
      line: true                  # Line coverage
      toggle: true                # Toggle coverage
      fsm: true                   # FSM state coverage

  formal:
    tool: symbiyosys              # Formal tool: symbiyosys
    properties:                   # SVA property files
      - formal/crypto_properties.sv
    depth: 100                    # BMC depth

  crypto_verification:            # Crypto-specific checks
    constant_time:
      enabled: true
      secrets: [secret_key]       # Signal names treated as secret
      public: [ciphertext]        # Signal names treated as public

    side_channel:
      enabled: true
      power_model: hamming_distance  # hamming_weight, hamming_distance, toggle_count
      tvla_threshold: 4.5
      num_traces: 10000

    fips_compliance:
      enabled: true
      level: "140-3 Level 2"
      checks:
        - key_zeroization
        - self_test_coverage

# ── Analysis ─────────────────────────────────────────────────────
analysis:
  timing:
    tool: opensta
    clock_period: "10.0ns"        # Target clock period
```

The full Pydantic v2 schema is defined in `packages/core/src/openforge/config/schema.py`. Unrecognized fields are rejected (`extra = "forbid"`).

---

Copyright 2026 Dyber Inc. | [engineering@dyber.io](mailto:engineering@dyber.io)
