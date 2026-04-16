# Project Structure

Every OpenForge project is defined by an `openforge.yaml` configuration file at the project root. This file tells OpenForge where to find source files, which PDK to target, how to run simulation, and what analysis to perform.

## Directory Layout

A typical OpenForge project has this structure:

```
my-project/
  openforge.yaml          # Project configuration (required)
  src/                    # RTL source files (.v, .sv, .vhd)
  tb/                     # Testbench files (.v, .sv, .py)
  constraints/            # Timing constraints (.sdc) and pin constraints (.pcf, .xdc)
  properties/             # Formal verification properties (.sv)
  models/                 # SPICE models, IP blocks
  synth_build/            # Synthesis output (generated)
  sim_build/              # Simulation output (generated)
  pnr_build/              # Place-and-route output (generated)
  reports/                # Analysis reports (generated)
  share/pdk/              # Local PDK files (optional)
```

The `synth_build/`, `sim_build/`, `pnr_build/`, and `reports/` directories are created automatically by OpenForge and contain generated artifacts.

## Configuration Reference

The `openforge.yaml` file uses a Pydantic v2 schema defined in `packages/core/src/openforge/config/schema.py`. Below is the complete reference.

### project

Top-level project metadata.

```yaml
project:
  name: "my-counter"              # Project name
  top_module: "counter"           # Top-level module for synthesis
  target_pdk: "sky130"            # Target PDK: sky130, gf180mcu, or null for FPGA
  include_dirs:                   # Additional include search paths
    - src/include
  defines:                        # Verilog preprocessor defines
    SYNTHESIS: "1"
  language_version: "sv2017"      # v2005, sv2012, sv2017, vhdl93, vhdl2008
```

### design

Source file and constraint specifications.

```yaml
design:
  sources:                        # Glob patterns for RTL source files
    - src/*.v
    - src/**/*.sv
  includes:                       # Include search directories
    - src/include
  constraints:                    # SDC / constraint files
    - constraints/timing.sdc
    - constraints/pins.pcf
```

### verification.simulation

Simulation runner configuration.

```yaml
verification:
  simulation:
    tool: icarus                  # icarus, verilator, or ghdl
    testbenches:                  # Glob patterns for testbench files
      - tb/*_tb.v
      - tb/*_tb.py
    coverage:
      line: true                  # Statement coverage
      toggle: true                # Signal toggle coverage
      branch: false               # Branch coverage
      fsm: false                  # FSM state coverage
    plusargs:                      # Extra +arg values for simulator
      SEED: "42"
    timeout_seconds: 300          # Max simulation time
```

### verification.formal

Formal verification configuration.

```yaml
verification:
  formal:
    tool: symbiyosys              # Only symbiyosys currently
    properties:                   # SVA / PSL property files
      - properties/counter_props.sv
    engines:                      # Solver engines
      - smtbmc                    # smtbmc, btor, aiger, abc
    depth: 20                     # Bounded proof depth
```

### verification.crypto_verification

Cryptographic hardware verification suite.

```yaml
verification:
  crypto_verification:
    constant_time:
      secrets:
        - key_in
        - plaintext
      public:
        - ciphertext

    side_channel:
      power_model: hamming_weight   # hamming_weight, hamming_distance, toggle_count
      tvla_threshold: 4.5           # t-test threshold
      num_traces: 10000             # Number of simulation traces

    entropy_analysis:
      sources:
        - trng_out
      sinks:
        - prng_seed

    fips_compliance:
      level: "1"                    # FIPS 140-3 level: 1, 2, 3, or 4
      checks:
        - kat                       # Known Answer Test
        - integrity                 # Module integrity
        - zeroize                   # Key zeroization

    ntt_validation:
      standard: kyber               # kyber, dilithium, or custom
      exhaustive: false
```

### analysis.timing

Static timing analysis configuration.

```yaml
analysis:
  timing:
    tool: opensta                 # Only opensta currently
    clock_period: 10.0            # Target clock period in nanoseconds
    sdc_files:                    # Additional SDC files
      - constraints/extra.sdc
```

### analysis.power

Power analysis configuration.

```yaml
analysis:
  power:
    tool: openroad                # Only openroad currently
    activity_file: sim_build/dump.vcd  # SAIF or VCD file
    corner: typical               # PVT corner name
```

### ci_integration

CI/CD settings for automated builds.

```yaml
ci_integration:
  github_actions: true            # Generate GitHub Actions workflow
  on_push: true                   # Run on push events
  on_pr: true                     # Run on pull request events
  nightly: false                  # Nightly regression runs
  extra_steps:                    # Custom CI step references
    - coverage-upload
```

## Example: Complete Configuration

```yaml
project:
  name: "aes-sbox"
  top_module: "aes_sbox"
  target_pdk: "sky130"

design:
  sources:
    - src/aes_sbox.sv
    - src/gf_mult.sv
  constraints:
    - constraints/timing.sdc

verification:
  simulation:
    tool: verilator
    testbenches:
      - tb/aes_sbox_tb.sv
    coverage:
      line: true
      toggle: true
      branch: true
    timeout_seconds: 120

  formal:
    tool: symbiyosys
    properties:
      - properties/aes_props.sv
    engines:
      - smtbmc
    depth: 30

  crypto_verification:
    constant_time:
      secrets: [key, plaintext]
      public: [sbox_out]
    side_channel:
      power_model: hamming_weight
      tvla_threshold: 4.5

analysis:
  timing:
    tool: opensta
    clock_period: 5.0
  power:
    tool: openroad
    activity_file: sim_build/dump.vcd

ci_integration:
  github_actions: true
  on_push: true
```

## Creating Projects

### From the GUI

**File > New Project** opens a dialog where you set the project name, location, target PDK, and top module. OpenForge generates the directory structure and a starter `openforge.yaml`.

### From the CLI

```bash
openforge init <name> [options]
```

Options:

| Flag | Description |
|---|---|
| `--pdk <name>` | Target PDK (sky130, gf180mcu) |
| `--top <module>` | Top module name |
| `--target <device>` | FPGA target device |
| `--type <type>` | Project type: rtl, fpga, pcb, analog |

### From the TCL Console

```tcl
create_project my-project /path/to/directory
set_top counter
set_target_pdk sky130
add_sources src/counter.v
```

## Opening Existing Projects

OpenForge detects projects by the presence of `openforge.yaml` in a directory.

=== "GUI"

    **File > Open Project** and navigate to the project directory.

=== "CLI"

    ```bash
    cd /path/to/project
    openforge synth   # Commands auto-detect openforge.yaml
    ```

=== "TCL"

    ```tcl
    open_project /path/to/project
    ```
