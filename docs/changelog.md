# Changelog

## v0.1.0 -- Initial Release

The first public release of OpenForge EDA, featuring a complete RTL-to-GDSII design flow with a Vivado-class desktop application.

### Desktop Application

- **Main window** with dockable panel architecture supporting 80+ panels
- **Catppuccin Mocha dark theme** across all panels and widgets
- **Flow Navigator** with Vivado-style collapsible sections and status indicators
- **Code Editor** with Verilog/SystemVerilog/VHDL syntax highlighting, auto-completion (QScintilla), bracket matching, minimap, and go-to-line
- **Console** with TCL command input, severity-colored log output, and command history
- **Hierarchy Browser** with module/port tree view and cross-probing to source
- **Properties panel** with context-sensitive attribute display
- **File Explorer** with project directory tree
- **New Project wizard** and project import dialogs
- **Tool Manager** for detecting, installing, and configuring EDA tool dependencies
- **Settings dialog** for application and project preferences
- **Extension Manager** for community plugin support

### Synthesis

- **Yosys integration** for RTL-to-gate synthesis targeting ASIC PDKs and FPGA architectures
- **Multi-PDK support**: SkyWater 130nm (sky130_fd_sc_hd, sky130_fd_sc_hs) and GlobalFoundries 180nm (gf180mcu)
- **Multi-corner synthesis**: tt, ss, ff process corners with appropriate Liberty files
- **Synthesis panel** with resource utilization tables, hierarchy browser, schematic viewer, and message browser
- **IP Catalog** for browsable, instantiable IP cores
- **Cell Library** viewer for PDK standard cells
- **Synthesis strategy** and **attributes** configuration dialogs

### Physical Design

- **OpenROAD integration** for floorplanning, placement, CTS, and routing
- **Physical Design panel** with flow control, stage progress, and design statistics
- **Layout Viewer** for DEF/GDS visualization with layer coloring (SKY130 metal stack), cell selection, zoom/pan, and tooltips
- **Floorplan Editor** with graphical die/core area definition
- **PDN Synthesizer** for power distribution network configuration
- **GDS Viewer** for GDSII file inspection
- **Path Browser** for timing path exploration
- **WSL2 integration** on Windows with automatic path translation

### Timing and Analysis

- **OpenSTA integration** for static timing analysis
- **Timing panel** with slack histogram, critical path browser, path detail view, and SDC constraint summary
- **Multi-corner timing**: tt/ss/ff corner analysis
- **STA What-If** panel for interactive timing exploration
- **PBA/Xtalk** panel for path-based analysis and crosstalk estimation
- **Power analysis** via OpenROAD with VCD activity support

### Verification

- **Simulation runners** for Icarus Verilog, Verilator, and GHDL
- **Cocotb support** for Python-based testbenches
- **Testbench panel** with test discovery, execution, pass/fail tree, and real-time console output
- **Waveform viewer** with three-pane layout (signal tree, value column, canvas), dual cursors, markers, minimap, analog traces, bus diamond rendering, and X/Z hatch patterns
- **Formal verification** via SymbiYosys with smtbmc, btor, aiger, and abc engines
- **Coverage Dashboard** with line, toggle, branch, and FSM metrics
- **Regression Runner** for batch test execution
- **Equivalence checking** panel

### FPGA

- **FPGA Target panel** for device selection (iCE40, ECP5, Gowin)
- **nextpnr integration** for FPGA place-and-route
- **Bitstream generation** via icestorm/Project Trellis
- **Pin Planner** with graphical package diagram and drag-and-drop assignment
- **Constraint Editor** with PCF/LPF/XDC/SDC syntax highlighting
- **ILA Debug** panel for in-system logic analysis

### PCB Design

- **PCB Designer** with multi-layer board layout
- **Schematic Editor** integration
- **Component Browser** with KiCad library support
- **PCB Router** with interactive and auto-routing
- **PCB Stackup Editor** for multi-layer configuration
- **ERC and DRC** checking
- **Gerber/Excellon export** for manufacturing

### Sign-off

- **Signoff Dashboard** with consolidated pass/fail status
- **Magic DRC** integration with violation browser and layout cross-probing
- **Netgen LVS** integration with mismatch debugging
- **IR Drop Overlay** for power integrity visualization
- **Power Sign-off** with static and dynamic power analysis

### Crypto Verification

- **Security Dashboard** with six analysis tabs: Overview, Constant-Time, Side-Channel, FIPS, Entropy, Fault Injection
- **Constant-time verification** for timing side-channel prevention
- **Side-channel analysis** with Hamming weight/distance models and TVLA
- **FIPS 140-3 compliance** checking (KAT, integrity, zeroization)
- **Entropy flow tracking** from source to sink
- **NTT validation** for Kyber/Dilithium lattice crypto

### Advanced Panels

- **AI Assistant** for design guidance and RTL generation
- **Git integration** with diff viewer, commit, and branch management
- **Block Design** editor for IP interconnection
- **AXI Checker** for bus protocol verification
- **CDC Panel** for clock domain crossing analysis
- **DFT Panel** for design-for-test insertion
- **Log Aggregator** for unified tool output
- **Worker Status** for background job monitoring
- **Report Viewer** for formatted report display
- **OpenLane Panel** for OpenLane flow integration
- **PDK Manager** for PDK download and configuration

### TCL Scripting

- **TCL console** with 60+ commands covering project management, synthesis, physical design, simulation, verification, FPGA, timing constraints, analysis, and utility operations
- **Script sourcing** for batch automation
- **Command history** and help system

### CLI

- **Typer-based CLI** with commands for init, synth, pnr, sta, drc, lvs, sim, formal, fpga, crypto, and serve
- **CI/CD ready** with JSON output and meaningful exit codes

### API

- **FastAPI REST server** with OpenAPI documentation
- **WebSocket streaming** for real-time job output
- **Job queue** with background execution and status polling
- **JWT authentication** for multi-user deployments
- **Cloud dispatch** for distributed tool execution

### Configuration

- **Pydantic v2 schema** for `openforge.yaml` project configuration
- **Hierarchical config**: project, design, verification, analysis, CI sections
- **Crypto verification config**: constant-time, side-channel, entropy, FIPS, NTT
- **Per-file metadata**: library assignment, language detection, testbench flags

### Example Projects

- `simple-counter` -- 8-bit counter with sky130 ASIC flow
- `aes-sbox` -- AES S-box with crypto verification
- `sha3-keccak` -- SHA3/Keccak hash function
- `ml-kem-accelerator` -- ML-KEM (Kyber) hardware accelerator
- `uart-tx` -- UART transmitter
- `spi-master` -- SPI master controller
