# OpenForge EDA

**Free, open-source EDA platform for ASIC, FPGA, and PCB design.**

OpenForge integrates, extends, and orchestrates open-source EDA tools with security-focused analysis capabilities. Built for post-quantum cryptographic hardware development targeting FIPS 140-3 certification.

[![CI](https://github.com/openforge/openforge/actions/workflows/ci.yml/badge.svg)](https://github.com/openforge/openforge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/openforge-eda)](https://pypi.org/project/openforge-eda/)
[![Docker](https://img.shields.io/docker/pulls/openforge/openforge-eda)](https://hub.docker.com/r/openforge/openforge-eda)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

<!-- screenshot placeholder: replace with actual screenshot -->
<!-- ![OpenForge Desktop](docs/images/screenshot.png) -->

---

## Features

| Category | Capabilities |
|----------|-------------|
| **FPGA** | Yosys synthesis, nextpnr place-and-route (iCE40, ECP5), bitstream generation, openFPGALoader programming |
| **ASIC** | Yosys + ABC synthesis, OpenROAD P&R (floorplan, CTS, routing), STA via OpenSTA, DRC/LVS via Magic + Netgen |
| **Verification** | Verilator, Icarus Verilog, GHDL simulation; SymbiYosys formal; Cocotb testbench framework |
| **Crypto Security** | Constant-time analysis, side-channel simulation (TVLA, CPA), entropy flow, FIPS 140-3 compliance, fault injection |
| **Analog** | ngspice SPICE simulation, parasitic extraction via Magic |
| **AI/ML** | Design-space exploration, power/area prediction (planned) |
| **Desktop IDE** | Qt/PySide6 dark-theme IDE with waveform viewer, RTL editor, synthesis dashboard, timing analysis |
| **Web IDE** | SvelteKit + Monaco editor, canvas waveform viewer, real-time WebSocket updates |

---

## Quick Install

### pip (recommended)

```bash
pip install openforge-eda
```

With all optional dependencies:

```bash
pip install openforge-eda[full]
```

### Docker

```bash
docker pull openforge/openforge-eda:latest

# Run CLI
docker run --rm -v $(pwd):/workspace openforge/openforge-eda openforge synth --help

# Run API server
docker run -p 8000:8000 openforge/openforge-eda serve --port 8000
```

### From source

```bash
git clone https://github.com/openforge/openforge.git
cd openforge
pip install -e ".[dev]"

# Or with uv (recommended for development)
pip install uv
uv pip install -e packages/core -e packages/cli -e packages/desktop --system
```

---

## Quick Start

```bash
# 1. Check available EDA tools
openforge tools

# 2. Synthesize the example counter for iCE40
openforge synth examples/simple-counter/counter.v --target ice40-hx8k

# 3. Launch the desktop IDE
openforge-desktop
```

---

## Architecture

```
openforge/
|
|-- packages/
|   |-- core/           Python orchestration library (Pydantic v2)
|   |   |-- engine/       EDA tool wrappers (Yosys, OpenROAD, Verilator, ...)
|   |   |-- flow/         DAG-based verification flows
|   |   |-- synthesis/    Multi-pass Yosys synthesis pipeline
|   |   |-- physical/     OpenROAD P&R + STA + DRC/LVS
|   |   |-- runner/       Simulation + coverage runners
|   |   |-- parsers/      Liberty, LEF, DEF, SDC, Verilog parsers
|   |   +-- pdk/          PDK management (SKY130, GF180, IHP SG13G2, ASAP7)
|   |
|   |-- cli/            Typer CLI ("openforge" command)
|   |-- api/            FastAPI REST backend + WebSocket
|   |-- web/            SvelteKit + Tailwind frontend (SPA)
|   |-- desktop/        PySide6/Qt desktop IDE (dark theme, dockable panels)
|   +-- crypto/         Crypto verification suite
|
|-- tools/              Rust performance tools
|   |-- openforge-ct/     Constant-time analyzer
|   |-- openforge-sca/    Side-channel analysis engine
|   |-- openforge-entropy/ Entropy flow analyzer
|   |-- openforge-lint/   Fast RTL linter
|   +-- openforge-wave/   High-performance VCD/FST parser
|
|-- share/              SVA libraries, project templates, PDK configs
|-- installer/          Docker, Windows NSIS, release scripts
|-- examples/           Example designs (counter, AES S-box, etc.)
+-- tests/              Unit + integration tests
```

---

## Supported EDA Tools

| Category | Tool | Status |
|----------|------|--------|
| **Synthesis** | Yosys + ABC | Integrated |
| **FPGA P&R** | nextpnr (iCE40, ECP5) | Integrated |
| **ASIC P&R** | OpenROAD | Integrated |
| **Simulation** | Verilator, Icarus Verilog, GHDL | Integrated |
| **Formal** | SymbiYosys | Integrated |
| **Timing** | OpenSTA | Integrated |
| **DRC/LVS** | Magic, Netgen, KLayout | Integrated |
| **Analog** | ngspice | Integrated |
| **Programming** | openFPGALoader | Integrated |
| **Linting** | Verible | Integrated |

## Supported PDKs

| PDK | Node | License |
|-----|------|---------|
| SkyWater SKY130 | 130nm | Open Source |
| GlobalFoundries GF180MCU | 180nm | Open Source |
| IHP SG13G2 | 130nm | Open Source |
| ASAP7 | 7nm | Academic |

---

## Development

### Prerequisites

- Python 3.12+
- Rust 1.75+ (for performance tools)
- Node 20+ (for web frontend)
- PySide6 (for desktop app)

### Setup

```bash
git clone https://github.com/openforge/openforge.git
cd openforge

# Python (using uv)
pip install uv
uv pip install -e "packages/core[dev]" -e "packages/cli" -e "packages/desktop" --system

# Rust tools
cargo build --release

# Web frontend
cd packages/web && npm install && npm run dev

# Run tests
pytest packages/core/tests/ -v
cargo test --all
```

### Coding standards

- **Python**: 3.12+, type hints everywhere, Pydantic v2, ruff lint/format, pytest
- **Rust**: 2021 edition, clippy, thiserror, clap
- **TypeScript**: Strict TS, SvelteKit SPA mode, Tailwind CSS
- **Qt**: Dark theme (Catppuccin Mocha), dock widgets, QSS theming

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Run `ruff check packages/ && pytest packages/core/tests/`
5. Open a pull request

---

## License

Licensed under [Apache 2.0](LICENSE).

Copyright 2026 Dyber, Inc.
