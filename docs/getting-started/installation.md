# Installation

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.12+ | 3.12.x |
| OS | Windows 10, macOS 12, Ubuntu 22.04 | Windows 11, macOS 14, Ubuntu 24.04 |
| RAM | 4 GB | 16 GB |
| Disk | 2 GB (base) | 10 GB (with PDKs) |
| Display | 1280x720 | 1920x1080 |

OpenForge requires **PySide6** (Qt 6) for the desktop application. It is installed automatically as a dependency.

## Install via pip

The simplest way to install OpenForge:

```bash
pip install openforge-eda
```

This installs the core library, CLI, desktop application, and API server. Launch the desktop app with:

```bash
openforge
```

Or start the API server:

```bash
openforge-api
```

## Install from Source

For development or to get the latest features:

```bash
git clone https://github.com/openforge/openforge.git
cd openforge
```

OpenForge uses [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
# Install uv if you don't have it
pip install uv

# Sync all workspace packages
uv sync

# Run the desktop application
uv run openforge

# Or run the CLI
uv run openforge-cli --help
```

!!! tip "Development mode"
    Running `uv sync` installs all packages in editable mode, so changes to source files take effect immediately.

## Docker

Run OpenForge without installing anything locally:

```bash
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd)/projects:/workspace \
  openforge/openforge
```

For headless CI/server use:

```bash
docker run -d -p 8000:8000 openforge/openforge openforge-api
```

The Docker image includes all EDA tool dependencies (Yosys, OpenROAD, Icarus Verilog, etc.) pre-installed.

## Windows Installer

A standalone Windows installer is available from the [Releases page](https://github.com/openforge/openforge/releases). The installer bundles Python, all dependencies, and optionally installs WSL2 with the EDA tool stack.

Download `OpenForge-Setup-x.y.z.exe` and follow the installation wizard.

## EDA Tool Dependencies

OpenForge orchestrates several open-source EDA tools. While the desktop app can manage these for you via **Tools > Tool Manager**, here are manual install instructions per platform:

### Required Tools

| Tool | Purpose | Minimum Version |
|---|---|---|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL synthesis | 0.35+ |
| [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) | Place and route | 2.0+ |
| [Icarus Verilog](https://github.com/steveicarus/iverilog) | Verilog simulation | 12.0+ |
| [Verilator](https://github.com/verilator/verilator) | Fast simulation / lint | 5.0+ |
| [Magic](https://github.com/RTimothyEdwards/magic) | DRC, extraction | 8.3+ |
| [Netgen](https://github.com/RTimothyEdwards/netgen) | LVS | 1.5+ |
| [KLayout](https://www.klayout.de/) | GDS viewer / DRC | 0.29+ |

### Optional Tools

| Tool | Purpose |
|---|---|
| [nextpnr](https://github.com/YosysHQ/nextpnr) | FPGA place and route |
| [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA) | Static timing analysis |
| [GHDL](https://github.com/ghdl/ghdl) | VHDL simulation |
| [SymbiYosys](https://github.com/YosysHQ/sby) | Formal verification |
| [ngspice](https://ngspice.sourceforge.io/) | SPICE simulation |
| [icestorm](https://github.com/YosysHQ/icestorm) | iCE40 bitstream tools |

### Ubuntu / Debian

```bash
# Core tools
sudo apt update
sudo apt install -y yosys iverilog verilator ghdl

# OpenROAD (from binary release)
wget https://github.com/The-OpenROAD-Project/OpenROAD/releases/latest/download/openroad_amd64.deb
sudo dpkg -i openroad_amd64.deb

# Magic and Netgen
sudo apt install -y magic netgen-lvs

# FPGA tools
sudo apt install -y nextpnr-ice40 nextpnr-ecp5 fpga-icestorm

# KLayout
sudo apt install -y klayout

# Formal verification
pip install sby
```

### macOS (Homebrew)

```bash
brew install yosys icarus-verilog verilator ghdl
brew install --cask klayout

# OpenROAD (build from source or use Docker)
brew install openroad

# Magic
brew install magic

# FPGA tools
brew install nextpnr icestorm
```

### Windows (WSL2)

OpenForge on Windows uses WSL2 to run Linux EDA tools. The desktop application automatically translates Windows paths to WSL2 mount paths.

```powershell
# Enable WSL2
wsl --install -d Ubuntu-24.04

# Inside WSL2, install tools as on Ubuntu
wsl -d Ubuntu-24.04
sudo apt update && sudo apt install -y yosys iverilog verilator magic netgen-lvs klayout
```

!!! note "Windows path translation"
    OpenForge automatically converts paths like `H:\projects\counter` to `/mnt/h/projects/counter` when calling WSL2 tools. No manual path conversion is needed.

### Tool Manager

The desktop application includes a built-in **Tool Manager** (accessible via **Tools > Manage EDA Tools**) that:

- Detects which tools are installed and their versions
- Downloads and installs missing tools (including WSL2 setup on Windows)
- Validates tool configurations
- Manages PDK installations

## PDK Installation

Process design kits are required for ASIC flows. OpenForge supports:

| PDK | Node | Foundry | Cell Libraries |
|---|---|---|---|
| SkyWater SKY130 | 130nm | SkyWater | sky130_fd_sc_hd, sky130_fd_sc_hs |
| GlobalFoundries GF180MCU | 180nm | GlobalFoundries | gf180mcu_fd_sc_mcu7t5v0 |

Install PDKs through the desktop app (**Tools > PDK Manager**) or via CLI:

```bash
openforge pdk install sky130
openforge pdk install gf180mcu
```

PDKs are stored in `~/.openforge/pdk/` by default, or in the project's `share/pdk/` directory.

## First-Run Wizard

When you launch OpenForge for the first time, the setup wizard will:

1. Check for installed EDA tools and report missing dependencies
2. Offer to install missing tools automatically
3. Prompt you to download PDKs for ASIC design
4. Configure default project settings (target PDK, simulation tool, etc.)
5. Create a sample project to verify the installation

You can re-run the wizard at any time from **Help > Run Setup Wizard**.

## Verifying the Installation

After installation, verify everything works:

```bash
# Check CLI version
openforge --version

# Run the built-in smoke test
openforge doctor

# Verify tool availability
openforge tools check
```

The `openforge doctor` command checks all tool dependencies and reports their status.

## Next Steps

- [Create your first project](first-project.md)
- [Quick start guide](quickstart.md)
- [ASIC tutorial with SKY130](../tutorials/asic-flow.md)
