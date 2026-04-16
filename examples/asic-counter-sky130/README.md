# ASIC Counter - SkyWater sky130 Full RTL-to-GDS Flow

An 8-bit synchronous up-counter taken through the complete ASIC physical design flow using the open-source SkyWater 130nm PDK and OpenROAD toolchain.

## Design

- **Module**: `counter` -- 8-bit up-counter with synchronous reset, enable, and overflow flag
- **Target frequency**: 100 MHz (10 ns clock period)
- **PDK**: SkyWater sky130A (`sky130_fd_sc_hd` standard cells)
- **Corners**: TT (25C, 1.80V), SS (-40C, 1.60V), FF (125C, 1.95V)

## ASIC Flow Stages

| Stage        | Tool      | Input                | Output                      |
|--------------|-----------|----------------------|-----------------------------|
| Lint         | Verilator | `rtl/counter.v`      | Lint report                 |
| Synthesis    | Yosys     | RTL + Liberty        | Gate-level netlist          |
| Floorplan    | OpenROAD  | Netlist + DEF        | Floorplan DEF               |
| Placement    | OpenROAD  | Floorplan DEF        | Placed DEF                  |
| CTS          | OpenROAD  | Placed DEF           | CTS DEF                     |
| Routing      | OpenROAD  | CTS DEF              | Routed DEF + netlist        |
| STA          | OpenSTA   | Routed netlist + SDC | Timing reports              |
| DRC          | Magic     | Routed DEF           | DRC report                  |
| LVS          | Netgen    | Layout vs. netlist   | LVS report                  |
| GDS Export   | Magic     | Routed DEF           | `counter.gds`               |

## Prerequisites

- [SkyWater PDK](https://github.com/google/skywater-pdk) installed (`$PDK_ROOT` set)
- [Yosys](https://github.com/YosysHQ/yosys) for synthesis
- [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) for P&R
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA) for timing analysis
- [Magic](https://github.com/RTimothyEdwards/magic) for DRC and GDS export
- [Netgen](https://github.com/RTimothyEdwards/netgen) for LVS
- [Icarus Verilog](http://iverilog.icarus.com/) for simulation (optional)

## How to Run

### OpenForge CLI

```bash
cd examples/asic-counter-sky130
openforge run                     # full flow: lint through GDS
openforge run --stage synth       # stop after synthesis
openforge run --stage sta         # stop after timing analysis
```

### OpenForge Desktop

1. File > Open Project and select this folder.
2. The Synthesis panel shows the Yosys configuration.
3. Click **Run Flow** for the full ASIC flow.
4. Check the Reports panel for timing, DRC, and LVS results.

### Standalone OpenROAD

```bash
# First, synthesize with Yosys
yosys -p "read_verilog rtl/counter.v; synth -top counter; \
    dfflibmap -liberty \$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib; \
    abc -liberty \$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib; \
    write_verilog build/counter_synth.v"

# Then run the full P&R flow
openroad -exit scripts/run_flow.tcl
```

### Simulation

```bash
iverilog -o build/counter_tb.vvp rtl/counter.v tb/counter_tb.v
vvp build/counter_tb.vvp
# View waveforms: gtkwave counter_tb.vcd
```

## Expected Results

- **Synthesis**: ~40 cells, 9 flip-flops (8 count + 1 overflow)
- **Timing (TT corner)**: Positive slack at 100 MHz
- **Simulation**: `PASS: all counter tests passed`
- **DRC**: Clean (no violations)
- **LVS**: Match

## File Structure

```
asic-counter-sky130/
  openforge.yaml           # Project configuration
  rtl/counter.v            # RTL source
  constraints/counter.sdc  # Timing constraints
  tb/counter_tb.v          # Simulation testbench
  scripts/run_flow.tcl     # Standalone OpenROAD script
  build/                   # Generated outputs (after running)
```

<!-- Screenshot placeholder: layout viewer showing placed-and-routed counter -->
