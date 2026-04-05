# OpenForge EDA

Cloud-native electronic design automation platform for cryptographic hardware verification.

OpenForge integrates, extends, and orchestrates open-source EDA tools with security-focused analysis capabilities that commercial vendors don't offer. Built for post-quantum cryptographic hardware development.

## Features

- **Full RTL-to-GDSII flow** built on Yosys, OpenROAD, Verilator, and more
- **Crypto verification suite** -- constant-time analysis, side-channel simulation, FIPS compliance
- **Desktop IDE** (Qt/PySide6) with waveform viewer, layout editor, and hierarchy browser
- **Web IDE** (Svelte) for browser-based design and verification
- **Cloud-native** with Docker containers and Kubernetes orchestration

## Quick Start

```bash
# Install via pip
pip install openforge

# Initialize a project
openforge init my-design --template crypto-accelerator

# Run verification
openforge verify --all

# Launch desktop IDE
openforge-desktop
```

## Architecture

```
openforge/
  packages/core/     -- Python orchestration library
  packages/cli/      -- Command-line interface
  packages/api/      -- FastAPI backend
  packages/web/      -- Svelte frontend
  packages/desktop/  -- Qt/PySide6 desktop app
  packages/crypto/   -- Crypto verification suite
  tools/             -- Rust performance tools (CT analyzer, SCA, entropy)
```

## Supported Tools

| Category | Tools |
|----------|-------|
| Simulation | Verilator, Icarus Verilog, GHDL, Cocotb |
| Formal | SymbiYosys, Yosys, Z3, Bitwuzla |
| Synthesis | Yosys + ABC |
| Physical Design | OpenROAD, KLayout, Magic |
| Timing | OpenSTA |
| Linting | Verible, Slang |
| Security | ChipWhisperer, FOBOS, LeaVe, IODINE |

## Supported PDKs

- SkyWater SKY130 (open source)
- GlobalFoundries GF180MCU (open source)
- IHP SG13G2 (open source, BiCMOS)
- ASAP7 (academic 7nm)
- Licensed PDKs via import wizard (GF22FDX, TSMC, Samsung, Intel)

## License

OpenForge Core Platform is licensed under GPLv3.
Dyber IP Library and Security Suite are proprietary (subscription).

Copyright 2026 Dyber Inc.
