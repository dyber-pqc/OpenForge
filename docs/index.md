# OpenForge EDA

<div class="hero" markdown>

**Free, open-source silicon design from RTL to GDSII**

OpenForge is a complete electronic design automation platform that unifies FPGA prototyping, ASIC tapeout, PCB layout, verification, and analog simulation in a single desktop application with a Vivado-class interface.

</div>

## Quick Install

```bash
pip install openforge-eda
```

Or run from source:

```bash
git clone https://github.com/openforge/openforge.git
cd openforge
uv sync
uv run openforge
```

## Feature Overview

<div class="feature-grid" markdown>

<div class="feature-card" markdown>

### FPGA Prototyping

Target iCE40, ECP5, and Xilinx devices with integrated synthesis (Yosys), place-and-route (nextpnr), bitstream generation, and one-click programming. Full constraint editing and pin planning built in.

</div>

<div class="feature-card" markdown>

### ASIC Design

RTL-to-GDSII flow using SkyWater 130nm and GlobalFoundries 180nm open PDKs. Yosys synthesis, OpenROAD physical design, Magic DRC/LVS, and KLayout GDS viewing -- all orchestrated from a single project file.

</div>

<div class="feature-card" markdown>

### PCB Design

Schematic capture, component library management, multi-layer PCB routing with stackup editor, design rule checking, ERC, and Gerber/drill file export. Integrates with KiCad libraries.

</div>

<div class="feature-card" markdown>

### Verification

Testbench management with Icarus Verilog, Verilator, and GHDL. Cocotb Python testbenches, code coverage dashboards, regression runners, and formal verification with SymbiYosys. Built-in waveform viewer with VCD/FST support.

</div>

<div class="feature-card" markdown>

### Analog Simulation

SPICE simulation via ngspice with schematic-driven netlisting, transient/AC/DC analysis, and waveform overlay. Transistor-level layout editing for custom cells.

</div>

<div class="feature-card" markdown>

### Crypto Verification

Industry-first EDA security suite: constant-time verification, side-channel leakage analysis (TVLA), FIPS 140-3 compliance checking, entropy flow tracking, and fault injection testing for cryptographic hardware.

</div>

</div>

## Platform Architecture

OpenForge is structured as a Python monorepo with Rust performance tools:

| Package | Description |
|---------|-------------|
| `packages/core` | Core orchestration library -- engine wrappers, config schema, PDK management, synthesis/simulation runners |
| `packages/cli` | Command-line interface (Typer) for headless and CI workflows |
| `packages/api` | FastAPI REST server with WebSocket job streaming |
| `packages/desktop` | PySide6/Qt desktop application with 80+ dockable panels |
| `packages/web` | SvelteKit web frontend for remote/collaborative use |
| `packages/crypto` | Cryptographic verification suite (constant-time, SCA, FIPS) |
| `tools/` | Rust performance tools: waveform parser, linter, SCA engine, entropy analyzer |

## Comparison with Existing Tools

| Capability | OpenForge | Vivado | KiCad | OpenLane | Innovus |
|---|---|---|---|---|---|
| FPGA synthesis + P&R | Yes | Yes | -- | -- | -- |
| ASIC RTL-to-GDSII | Yes | -- | -- | Yes | Yes |
| PCB schematic + layout | Yes | -- | Yes | -- | -- |
| Formal verification | Yes | Limited | -- | -- | -- |
| Crypto security analysis | Yes | -- | -- | -- | -- |
| Waveform viewer | Built-in | Built-in | -- | -- | -- |
| Open source | Yes | No | Yes | Yes | No |
| Cross-platform GUI | Yes | Linux only | Yes | CLI only | Linux only |
| REST API / CI integration | Yes | TCL only | CLI | Yes | TCL only |
| TCL scripting console | Yes | Yes | -- | Yes | Yes |
| Price | Free | $3k+/seat | Free | Free | $100k+/seat |

## Getting Started

New to OpenForge? Start here:

1. **[Installation](getting-started/installation.md)** -- System requirements and install methods
2. **[First Project](getting-started/first-project.md)** -- Create, synthesize, and simulate your first design
3. **[Quick Start](getting-started/quickstart.md)** -- 5-minute walkthroughs for FPGA, ASIC, and PCB flows

## Tutorials

- [FPGA Flow: iCEBreaker Blinky](tutorials/fpga-flow.md) -- End-to-end FPGA design targeting the iCEBreaker board
- [ASIC Flow: SKY130 Counter](tutorials/asic-flow.md) -- RTL to GDSII with the SkyWater 130nm PDK
- [PCB Flow: ESP32 Breakout](tutorials/pcb-flow.md) -- Schematic to Gerber for a microcontroller board
- [Verification](tutorials/verification.md) -- Testbenches, coverage, and formal proofs
- [Analog Simulation](tutorials/analog.md) -- Op-amp SPICE simulation with ngspice
