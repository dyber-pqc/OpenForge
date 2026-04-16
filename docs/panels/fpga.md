# FPGA Panel Group

The FPGA panels manage FPGA-specific workflows: target device selection, synthesis for FPGA architectures, pin assignment, bitstream generation, and on-chip debugging.

## FPGA Target Panel

Configures the target FPGA device and displays resource utilization relative to the device capacity.

### Supported Families

| Family | Vendor | Tool Chain |
|---|---|---|
| iCE40 | Lattice | Yosys + nextpnr-ice40 + icestorm |
| ECP5 | Lattice | Yosys + nextpnr-ecp5 + Project Trellis |
| Gowin | Gowin | Yosys + nextpnr-gowin + Apicula |
| Xilinx 7-series | AMD/Xilinx | Yosys synthesis + Vivado P&R (optional) |

### Features

- Device selector with part number, package, and speed grade
- Resource capacity display (LUTs, FFs, BRAMs, DSPs, I/Os)
- Post-synthesis utilization as a percentage of capacity
- Utilization bar charts per resource type

### Configuration

```yaml
fpga:
  family: ice40
  device: up5k
  package: sg48
```

Or via TCL:

```tcl
set_target_device ice40-up5k-sg48
```

## Pin Planner

Graphical pin assignment tool showing the FPGA package footprint.

### Features

- **Package diagram**: Interactive view of all FPGA pins with labels
- **Drag and drop**: Assign signals to pins by dragging from the signal list
- **Pin types**: Color-coded by function (GPIO, clock, power, configuration)
- **Constraint export**: Generates PCF (iCE40) or XDC (Xilinx) constraint files
- **Conflict detection**: Highlights conflicting assignments (same pin, incompatible I/O standards)

### Usage

1. Open the Pin Planner (**View > Pin Planner**)
2. The left panel lists all unassigned top-level ports
3. The right panel shows the FPGA package diagram
4. Drag a port name onto a pin, or right-click a pin and select **Assign Signal**
5. Assigned pins turn from gray to colored (input=blue, output=green, bidirectional=yellow)
6. Click **Export Constraints** to save the pin assignments

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+N` | Open Pin Planner |
| `Delete` | Unassign selected pin |
| `Ctrl+F` | Search pins |
| `+` / `-` | Zoom package diagram |

## Constraint Editor

Text-based editor for timing and pin constraints with syntax highlighting.

### Supported Formats

| Format | Target | Description |
|---|---|---|
| SDC | All | Synopsys Design Constraints (timing) |
| PCF | iCE40 | Physical Constraints File (pin assignments) |
| LPF | ECP5 | Lattice Preference File |
| XDC | Xilinx | Xilinx Design Constraints |

### Features

- Syntax highlighting for each constraint format
- Auto-completion for constraint commands
- Inline validation (highlights invalid pin names or syntax errors)
- SDC command palette with templates for common constraints

## FPGA Synthesis and Bitstream

The FPGA flow runs through these steps:

1. **Synthesize** -- Yosys maps RTL to FPGA primitives (LUT4, DFF, carry chains)
2. **Place & Route** -- nextpnr assigns cells to physical locations and routes signals
3. **Generate Bitstream** -- icepack/ecppack converts placement to a binary bitstream
4. **Program** -- iceprog/openFPGAloader writes the bitstream to the FPGA

Each step is available as a button in the Flow Navigator under the FPGA section.

### TCL Commands

```tcl
synth_fpga                        # Synthesize for FPGA
program_fpga                      # Program the connected board
set_target_device ice40-up5k-sg48 # Set target device
```

### CLI Commands

```bash
openforge fpga synth --top blinky
openforge fpga pnr
openforge fpga bitstream
openforge fpga flash              # Program flash (persistent)
openforge fpga flash --sram       # Program SRAM (volatile)
```

## ILA Debug Panel

In-system logic analyzer for runtime debugging of FPGA designs.

### Features

- Define trigger conditions on internal signals
- Capture waveform data from the running FPGA via JTAG
- Display captured data in the waveform viewer
- Configure sample depth and trigger position

### Usage

1. Instrument your design with ILA debug cores during synthesis
2. Program the FPGA
3. Open the ILA Debug panel
4. Set trigger conditions (e.g., `enable == 1 && count == 8'hFF`)
5. Arm the trigger and wait for capture
6. View captured waveforms in the integrated waveform viewer

## Common Workflows

### Complete FPGA Design Cycle

1. Write RTL and constraints
2. Set the target device in the FPGA Target panel
3. Assign pins in the Pin Planner
4. Run Synthesis + P&R + Bitstream
5. Program the board
6. Debug with ILA if needed
7. Iterate

### Migrating Between FPGA Families

1. Change the target device in the FPGA Target panel
2. Update pin constraints for the new package
3. Re-run synthesis and P&R -- Yosys handles the technology mapping automatically
