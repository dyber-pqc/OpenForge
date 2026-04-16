# Flow Navigator

The Flow Navigator is a Vivado-style panel on the left side of the window that organizes the full ASIC/FPGA design flow into collapsible sections. Each item represents a design step that can be executed with a single click.

## Overview

The Flow Navigator provides a sequential view of the design process. Steps are organized into categories and show real-time status indicators.

### Status Indicators

Each flow step displays a colored dot indicating its current state:

| Color | Status | Meaning |
|---|---|---|
| Gray | Not Started | Step has not been run |
| Blue | In Progress | Step is currently running |
| Green | Completed | Step finished successfully |
| Red | Error | Step failed -- check console for details |

## Flow Categories

### Design Entry

| Step | Action | Description |
|---|---|---|
| Add Sources | Opens file dialog | Add Verilog/VHDL/constraint files to the project |
| Set Top Module | Opens module selector | Choose the top-level module for synthesis |
| Elaborate | Runs elaboration | Parse RTL and build the module hierarchy |

### Synthesis

| Step | Action | Description |
|---|---|---|
| Run Synthesis | Invokes Yosys | Synthesize RTL to gate-level netlist |
| Open Schematic | Opens Synthesis panel | View the gate-level schematic |
| Report Utilization | Opens Synthesis panel | View cell usage and area |

### FPGA (visible when targeting an FPGA device)

| Step | Action | Description |
|---|---|---|
| Synthesize | Runs Yosys for FPGA | Map to FPGA primitives |
| Place & Route | Runs nextpnr | Place and route on the FPGA device |
| Generate Bitstream | Runs icepack/ecppack | Create the programming bitstream |
| Program | Runs iceprog | Flash the bitstream to hardware |

### Physical Design (visible when targeting an ASIC PDK)

| Step | Action | Description |
|---|---|---|
| Init Floorplan | Defines die/core area | Set up the chip floorplan |
| Run Placement | Runs OpenROAD | Place standard cells |
| Run CTS | Runs OpenROAD | Synthesize clock trees |
| Run Routing | Runs OpenROAD | Route all signals |
| Run P&R (Full) | Runs complete flow | Execute all physical design steps |

### Simulation

| Step | Action | Description |
|---|---|---|
| Compile | Compiles testbench | Compile RTL + testbench with simulator |
| Run Simulation | Executes simulation | Run the compiled simulation |
| Open Waveform | Opens waveform viewer | View VCD/FST output |

### Analysis

| Step | Action | Description |
|---|---|---|
| Run STA | Runs OpenSTA | Static timing analysis |
| Report Timing | Opens Timing panel | View timing paths and slack |
| Report Power | Runs power analysis | Estimate power consumption |

### Signoff

| Step | Action | Description |
|---|---|---|
| Run DRC | Runs Magic | Design rule checking |
| Run LVS | Runs Netgen | Layout vs. schematic |
| Write GDSII | Exports GDS | Generate final layout file |

## How to Use

### Running Steps

1. Click any step name to execute it
2. The step's status indicator turns blue (in progress)
3. Console output streams in the Console panel at the bottom
4. When complete, the indicator turns green (success) or red (error)
5. Downstream steps remain gray until their prerequisites complete

### Step Dependencies

The Flow Navigator enforces a logical ordering:

- **Synthesis** must complete before **Physical Design** or **FPGA P&R**
- **Placement** must complete before **CTS**
- **CTS** must complete before **Routing**
- **Routing** must complete before **DRC/LVS/GDSII**

If you try to run a step before its prerequisites, OpenForge will either run the prerequisites first or prompt you to run them.

### Expanding and Collapsing

- Click the category header (e.g., "Synthesis") to expand or collapse that section
- All sections are expanded by default
- The navigator scrolls to show the currently active step

## Customization

### Visible Sections

The visible flow categories depend on your project type:

| Project Type | Visible Categories |
|---|---|
| ASIC (PDK target) | Design Entry, Synthesis, Physical Design, Simulation, Analysis, Signoff |
| FPGA (device target) | Design Entry, Synthesis, FPGA, Simulation |
| PCB | Design Entry, Schematic, Layout, Manufacturing |
| Analog | Design Entry, SPICE Simulation, Analysis |

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+S` | Run Synthesis |
| `Ctrl+Shift+R` | Run Simulation |
| `Ctrl+Shift+P` | Run P&R |
| `Ctrl+Shift+T` | Run STA |
| `F5` | Run the next logical step |
| `Ctrl+F` | Toggle Flow Navigator visibility |

## TCL Equivalent

Every Flow Navigator step has a corresponding TCL command:

```tcl
# Synthesis
synth_design -top counter

# Physical Design
init_floorplan -die_area {0 0 200 200} -core_area {20 20 180 180}
place_design
clock_tree_synthesis
route_design

# Simulation
compile_sim -top counter_tb
run_sim

# Analysis
report_timing -max_paths 50
report_power

# Signoff
run_drc
run_lvs
write_gds output.gds
```
