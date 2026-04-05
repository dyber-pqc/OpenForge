# OpenForge EDA

**Cloud-native electronic design automation platform for cryptographic hardware verification.**

OpenForge integrates, extends, and orchestrates open-source EDA tools with security-focused analysis capabilities that commercial vendors don't offer. Built for post-quantum cryptographic hardware development targeting FIPS 140-3 certification.

[![CI](https://github.com/dyber-pqc/OpenForge/actions/workflows/ci.yml/badge.svg)](https://github.com/dyber-pqc/OpenForge/actions)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## Key Features

### RTL-to-GDSII Flow
- **Synthesis** via Yosys with multi-pass ABC optimization (area/speed/balanced/low-power recipes)
- **Physical design** via OpenROAD (floorplan, placement, CTS, routing) with PDK-specific configs
- **Static timing analysis** via OpenSTA with full path parsing, slack histograms, MCMM
- **DRC/LVS** via Magic + Netgen with violation browsing
- **Layout viewing** with layer visualization, zoom/pan, cell/net highlighting

### Simulation & Verification
- **RTL simulation** via Verilator (cycle-accurate), Icarus Verilog, GHDL
- **Testbench framework** with Cocotb integration, test discovery, and live output streaming
- **Formal verification** via SymbiYosys with crypto-specific SVA property library
- **Waveform viewer** with dual cursors, markers, analog traces, bus decoding, minimap
- **Code coverage** collection and HTML reporting (line/toggle/FSM)

### Crypto Verification Suite (Dyber Security)
- **Constant-time analysis** -- taint propagation detecting secret-dependent branches, memory accesses, and variable-latency operations
- **Side-channel simulation** -- Hamming weight/distance power models, TVLA, CPA attack simulation
- **Entropy flow analysis** -- source-to-sink path verification with reduction detection
- **FIPS 140-3 compliance** -- key zeroization, self-test coverage, error handling, RNG health checks
- **NTT/polynomial validation** -- FIPS 203/204 reference comparison, butterfly formal proofs
- **Fault injection** -- glitch, bit-flip, and laser fault simulation with resilience scoring

### Desktop IDE (Qt/PySide6)
- Vivado-style dockable panel layout with dark theme
- RTL editor with syntax highlighting, code folding, real-time lint
- Waveform viewer with dual cursors, markers, edge navigation, minimap
- Synthesis results with resource utilization, cell usage, schematic viewer
- Timing analysis with slack histogram, critical path browser, constraint viewer
- Physical design flow control with metrics dashboard
- Testbench manager with test discovery, run/stop, pass/fail visualization
- Signal browser, properties inspector, hierarchy browser
- Splash screen with animated loading

### Web IDE (SvelteKit)
- Full IDE layout with resizable panels
- Monaco-based RTL editor with tab management
- Canvas-based waveform viewer with zoom/pan/cursors
- Synthesis, timing, and physical design dashboards
- Security score dashboard with ring charts
- Coverage visualization with annotated source
- Real-time updates via WebSocket

---

## Quick Start

```bash
# Install via pip
pip install openforge

# Initialize a project
openforge init my-design --template crypto-accelerator

# Check tool availability
openforge tools

# Run verification
openforge verify --all

# Synthesize
openforge synth --target sky130

# Launch desktop IDE
openforge-desktop

# Start API server (for web IDE)
openforge-api
```

---

## Architecture

```
openforge/
├── packages/
│   ├── core/           Python orchestration library
│   │   ├── config/       YAML project config (Pydantic v2)
│   │   ├── engine/       14 EDA tool wrappers
│   │   ├── flow/         DAG-based verification flows
│   │   ├── runner/       Simulation + coverage runners
│   │   ├── synthesis/    Yosys synthesis pipeline
│   │   ├── physical/     OpenROAD P&R + STA + DRC/LVS
│   │   ├── parsers/      Liberty, LEF, DEF, SDC, Verilog
│   │   ├── waveform/     VCD/FST loading
│   │   ├── pdk/          PDK management
│   │   ├── project/      Project management
│   │   └── report/       HTML/JSON/SARIF/JUnit generation
│   ├── cli/            Typer CLI (openforge command)
│   ├── api/            FastAPI backend + WebSocket
│   ├── web/            SvelteKit + Tailwind frontend
│   ├── desktop/        PySide6/Qt desktop application
│   └── crypto/         Crypto verification suite
├── tools/              Rust performance tools
│   ├── openforge-ct/     Constant-time analyzer
│   ├── openforge-sca/    Side-channel analysis
│   ├── openforge-entropy/ Entropy flow analyzer
│   ├── openforge-lint/   Fast RTL linter
│   └── openforge-wave/   High-performance VCD/FST parser
├── share/              SVA libraries, templates, PDK configs
├── docker/             Container definitions + compose
├── examples/           Example projects
└── tests/              Unit + integration tests
```

---

## Supported EDA Tools

| Category | Tool | Integration |
|----------|------|-------------|
| **Simulation** | Verilator | Compile + simulate with trace/coverage |
| | Icarus Verilog | Event-driven simulation |
| | GHDL | VHDL simulation |
| | Cocotb | Python testbench framework |
| **Formal** | SymbiYosys | BMC, k-induction, PDR |
| | Yosys | Formal backends + synthesis |
| **Synthesis** | Yosys + ABC | RTL-to-gate with Liberty mapping |
| **Physical** | OpenROAD | Floorplan, place, CTS, route |
| | KLayout | Layout viewing + DRC |
| | Magic | DRC + parasitic extraction |
| | Netgen | LVS comparison |
| **Timing** | OpenSTA | Multi-corner STA |
| **Linting** | Verible | SV lint + format |

## Supported PDKs

| PDK | Node | Status | Features |
|-----|------|--------|----------|
| SkyWater SKY130 | 130nm | Open Source | Digital + Analog, IO cells |
| GlobalFoundries GF180MCU | 180nm | Open Source | HV, thick oxide |
| IHP SG13G2 | 130nm | Open Source | BiCMOS, SiGe HBT |
| ASAP7 | 7nm | Academic | FinFET, predictive |
| GF22FDX, TSMC, Samsung, Intel | Various | Licensed | Via import wizard |

---

## File Parsers

OpenForge includes production-quality parsers for standard EDA formats:

| Format | Lines | Purpose |
|--------|-------|---------|
| Liberty (.lib) | 592 | Cell timing, power, area |
| LEF | 624 | Layer/via/macro geometry |
| DEF | 682 | Placed & routed design |
| SDC | 556 | Timing constraints |
| VCD | 617 (Rust) | Simulation waveforms |
| Verilog netlist | 348 | Gate-level schematic |

---

## Development

### Prerequisites
- Python 3.12+
- Rust 1.75+ (for performance tools)
- Node 20+ (for web frontend)
- PySide6 (for desktop app)

### Setup
```bash
# Clone
git clone https://github.com/dyber-pqc/OpenForge.git
cd OpenForge

# Python packages (using uv)
uv pip install -e "packages/core[dev]" -e "packages/cli" -e "packages/crypto"

# Rust tools
cargo build --release

# Web frontend
cd packages/web && npm install && npm run dev

# Run tests
pytest tests/
cargo test --all
```

### Coding Standards
- **Python**: 3.12+, type hints, Pydantic v2, ruff lint/format, pytest
- **Rust**: 2021 edition, clippy, thiserror, clap
- **TypeScript/Svelte**: Strict TS, SvelteKit SPA mode, Tailwind CSS
- **Qt/PySide6**: Dark theme (Catppuccin Mocha), dock widgets, QSS

---

## Project Statistics

| Component | Files | Lines |
|-----------|-------|-------|
| Python (core, CLI, API, desktop, crypto) | ~95 | ~21,500 |
| Rust (tools) | ~15 | ~1,560 |
| Svelte/TypeScript (web) | ~20 | ~2,480 |
| SystemVerilog/Verilog (examples, SVA) | ~5 | ~350 |
| Config/Docker/CI | ~25 | ~500 |
| **Total** | **~160** | **~27,400** |

---

## License

OpenForge Core Platform is licensed under [GPLv3](LICENSE).
Dyber IP Library and Security Suite are proprietary (subscription).

Copyright 2026 Dyber Inc. | [engineering@dyber.io](mailto:engineering@dyber.io)
