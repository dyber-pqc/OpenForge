# Panel Reference Overview

OpenForge's desktop application uses a dockable panel architecture inspired by Vivado and Visual Studio Code. Every panel is a Qt dock widget that can be moved, resized, floated, tabbed, or hidden. This page provides an overview of all available panels organized by function.

## Panel Architecture

Panels are accessible from the **View** menu or the **Flow Navigator**. The default layout arranges panels by workflow:

- **Left**: Flow Navigator, File Explorer, Hierarchy Browser
- **Center**: Code Editor, Layout Viewer, Schematic Viewer
- **Bottom**: Console, Testbench Results, Waveform Viewer
- **Right**: Properties, Reports, Timing

You can rearrange panels by dragging their title bars. Save and restore layouts via **View > Save Layout** and **View > Restore Layout**.

!!! tip "Keyboard shortcut"
    Press `Ctrl+Shift+P` to open the command palette and quickly switch to any panel by name.

## Panel Groups

### Design Entry

| Panel | Description | Shortcut |
|---|---|---|
| [Code Editor](../guide/code-editor.md) | Tabbed editor with Verilog/VHDL syntax highlighting, auto-completion, and minimap | `Ctrl+E` |
| [Hierarchy Browser](../guide/activity-bar.md) | Tree view of the RTL module hierarchy with ports and instances | `Ctrl+H` |
| [Flow Navigator](../guide/flow-navigator.md) | Vivado-style collapsible flow steps with status indicators | `Ctrl+F` |
| Properties | Design properties inspector -- shows attributes of selected objects | -- |
| Console | TCL command console with log output, severity coloring, and history | `Ctrl+`` ` |

### Synthesis

| Panel | Description |
|---|---|
| [Synthesis](synthesis.md) | Resource utilization, cell usage, hierarchy, schematic viewer, message browser |
| IP Catalog | Browse and instantiate reusable IP cores |
| Cell Library | View available standard cells from the target PDK |

### Physical Design

| Panel | Description |
|---|---|
| [Physical Design](physical.md) | P&R flow control, floorplan configuration, placement/routing statistics |
| Layout Viewer | Interactive DEF/GDS viewer with layer controls, zoom, cell selection |
| Floorplan Editor | Graphical floorplan creation with die/core areas, blockages, power rings |
| PDN Synthesizer | Power distribution network configuration and analysis |
| GDS Viewer | GDSII file viewer with layer coloring and cell browsing |

### Timing and Analysis

| Panel | Description |
|---|---|
| [Timing Analysis](timing.md) | Slack histogram, critical path browser, path detail, SDC summary |
| Path Browser | Detailed timing path exploration with cell delays |
| STA What-If | Interactive timing exploration with virtual clock adjustments |
| PBA/Xtalk | Path-based analysis and crosstalk impact estimation |

### Verification

| Panel | Description |
|---|---|
| [Verification](verification.md) | Testbench management, simulation runner, waveform viewer |
| Testbench | Test discovery, execution control, pass/fail results tree |
| Waveform | VCD/FST waveform viewer with dual cursors, markers, analog traces |
| Formal | Formal property verification with counterexample viewer |
| Coverage Dashboard | Line, toggle, branch, and FSM coverage reports |
| Regression Runner | Batch test execution with parallel job support |
| Equivalence | Pre/post-synthesis equivalence checking |

### FPGA

| Panel | Description |
|---|---|
| [FPGA](fpga.md) | FPGA target selection, resource utilization, bitstream generation |
| Pin Planner | Graphical pin assignment on the FPGA package diagram |
| Constraint Editor | SDC/XDC/PCF constraint editing with syntax highlighting |
| ILA Debug | In-system logic analyzer for runtime FPGA debugging |

### PCB

| Panel | Description |
|---|---|
| [PCB](pcb.md) | Schematic editor, PCB layout, stackup editor, auto-router |
| Component Browser | Search and place components from KiCad libraries |
| ERC Panel | Electrical rule check results |
| PCB Router | Interactive and auto-routing engine |
| PCB Stackup | Layer stack configuration for multi-layer boards |

### Sign-off

| Panel | Description |
|---|---|
| [Sign-off](signoff.md) | DRC browser, LVS debugger, power sign-off, IR drop overlay |
| DRC Browser | Design rule violation list with layout highlighting |
| LVS Debugger | Layout-vs-schematic mismatch analysis |
| Signoff Dashboard | Consolidated pass/fail status for all sign-off checks |
| IR Drop Overlay | Voltage drop visualization on the layout |

### Security and Crypto

| Panel | Description |
|---|---|
| Security | Six-tab crypto analysis: Overview, Constant-Time, Side-Channel, FIPS, Entropy, Fault Injection |

### Collaboration and Workflow

| Panel | Description |
|---|---|
| Git | Built-in Git integration with diff viewer, commit, branch management |
| AI Assistant | AI-powered design assistance for RTL writing, debugging, optimization |
| Log Aggregator | Unified log view across all tools with filtering and search |
| Worker Status | Background job monitor showing running synthesis/simulation/P&R tasks |
| Reports | Consolidated flow results with timing, coverage, and security summaries |

## Panel Theme

All panels use the **Catppuccin Mocha** dark theme with consistent color coding:

| Color | Meaning |
|---|---|
| Green (`#a6e3a1`) | Pass, success, timing met |
| Red (`#f38ba8`) | Fail, error, timing violated |
| Yellow (`#f9e2af`) | Warning, near-critical |
| Blue (`#89b4fa`) | Info, in-progress, primary action |
| Purple (`#cba6f7`) | Selected, highlighted |
| Teal (`#94e2d5`) | Accent, secondary info |
