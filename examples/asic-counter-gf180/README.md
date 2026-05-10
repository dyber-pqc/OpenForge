# ASIC Counter - GlobalFoundries gf180mcuC Full RTL-to-GDS Flow

The same 8-bit synchronous up-counter as `examples/asic-counter-sky130/`, retargeted to the open-source **GlobalFoundries 180 nm MCU (5 V)** PDK. The point of this example is to prove that OpenForge's tech abstraction is genuinely PDK-portable -- the RTL is identical; only the constraints, library names, and floorplan size change.

## Design

- **Module**: `counter` -- 8-bit up-counter with synchronous reset, enable, and overflow flag
- **Target frequency**: 50 MHz (20 ns clock period) -- 180 nm is ~2x slower than 130 nm
- **PDK**: `gf180mcuC` (5 V variant), `gf180mcu_fd_sc_mcu7t5v0` 7-track standard cells
- **Corners**: TT (25C, 5.00 V), SS (-40C, 4.50 V), FF (125C, 5.50 V)
- **Metal stack**: 5 layers (Metal1..Metal5), Metal5 is "thick" top metal

## What's identical to the sky130 example

- `rtl/counter.v` -- pure RTL, zero PDK dependence
- The flow stages (lint -> synth -> floorplan -> place -> CTS -> route -> STA -> DRC -> xRC -> LVS -> GDS)
- The OpenForge orchestration (`openforge.yaml`)

## What changes per PDK

| Item                | sky130A                                    | gf180mcuC                                          |
|---------------------|--------------------------------------------|----------------------------------------------------|
| Standard cell lib   | `sky130_fd_sc_hd`                          | `gf180mcu_fd_sc_mcu7t5v0`                          |
| Site                | `unithd`                                   | `GF18T`                                            |
| Voltage             | 1.80 V (1.60 / 1.95 corners)               | 5.00 V (4.50 / 5.50 corners)                       |
| Routing layer names | `li1`, `met1`..`met5`                      | `Metal1`..`Metal5` (no local-interconnect layer)   |
| Min M1 width        | 0.14 µm                                    | 0.23 µm                                            |
| Top-metal width     | 1.60 µm (`met5`)                           | 0.44 µm (`Metal5`)                                 |
| Default freq        | 100 MHz                                    | 50 MHz                                             |
| Driving cell        | `sky130_fd_sc_hd__inv_2`                   | `gf180mcu_fd_sc_mcu7t5v0__inv_2`                   |
| Filltie / decap     | `sky130_fd_sc_hd__{tap,decap,fill,diode}*` | `gf180mcu_fd_sc_mcu7t5v0__{filltie,filldecap,filler,endcap,antenna,diode}*` |

The OpenForge signoff binaries have `gf180mcuC` baked in as a built-in tech, so the DRC/xRC/LVS stages run against a Rust process file -- no Magic / Netgen / Quantus install needed for a smoke check.

## Prerequisites

- A gf180mcu PDK install. Easiest options:

  ```bash
  # Option 1: volare (recommended, used by OpenLane / efabless)
  pip install volare
  volare enable --pdk gf180mcu --version <version-hash>
  export PDK_ROOT=$HOME/.volare

  # Option 2: clone the PDK repo directly
  git clone https://github.com/google/gf180mcu-pdk
  export PDK_ROOT=$PWD/gf180mcu-pdk
  ```

- [Yosys](https://github.com/YosysHQ/yosys) for synthesis (with `gf180mcu` ABC liberty target)
- [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) for P&R
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA) for timing
- Optional: [Magic](https://github.com/RTimothyEdwards/magic) and [Netgen](https://github.com/RTimothyEdwards/netgen) for cross-checking against vendor signoff
- [Icarus Verilog](http://iverilog.icarus.com/) for simulation (optional)

## How to Run

### OpenForge CLI

```bash
cd examples/asic-counter-gf180
openforge run                     # full flow: lint through GDS
openforge run --stage synth       # stop after synthesis
openforge run --stage sta         # stop after timing analysis
```

### OpenForge Desktop

1. **File > Open Project** and select this folder.
2. The Synthesis panel auto-detects the `gf180mcu` Liberty target.
3. Click **Run Flow** for the full ASIC flow.
4. The Reports panel shows timing, DRC (`openforge-drc --tech gf180mcuC`), xRC, and LVS results.

### Standalone OpenROAD

```bash
yosys -p "read_verilog rtl/counter.v; synth -top counter; \
    dfflibmap -liberty \$PDK_ROOT/gf180mcuC/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib; \
    abc -liberty \$PDK_ROOT/gf180mcuC/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib; \
    write_verilog build/counter_synth.v"

openroad -exit scripts/run_flow.tcl
```

### Signoff with built-in OpenForge engines

```bash
# Parasitic extraction with the gf180mcuC built-in process file
openforge-xrc extract \
    --def build/counter_routed.def \
    --lef $PDK_ROOT/gf180mcuC/libs.tech/openlane/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef \
    --tech gf180mcuC \
    --corner all \
    -o build/counter.spef

# LVS using the gf180-aware physical-only filter
openforge-lvs check \
    --layout-def build/counter_routed.def \
    --layout-lef $PDK_ROOT/gf180mcuC/libs.tech/openlane/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef \
    --schematic build/counter_routed.v \
    --tech gf180mcuC \
    --top counter

# DRC against the bundled gf180mcuC subset deck (or the full vendor deck)
openforge-drc check build/counter.gds \
    --rules-drx $PDK_ROOT/gf180mcuC/libs.tech/klayout/drc/gf180mcuC_mr.drc \
    --tech gf180mcuC \
    -o build/counter.drc.rdb
```

## Expected Results

- **Synthesis**: ~50 cells (slightly more than sky130 due to wider drive strengths)
- **Timing (TT corner)**: Positive slack at 50 MHz
- **Simulation**: `PASS: all counter tests passed`
- **DRC**: Clean (no violations)
- **LVS**: Match
- **xRC**: Per-net SPEF for min/typ/max corners

## File Structure

```
asic-counter-gf180/
  openforge.yaml           # Project configuration (PDK = gf180mcuC)
  rtl/counter.v            # RTL source (identical to sky130)
  constraints/counter.sdc  # Timing constraints (50 MHz, 5 V cells)
  tb/counter_tb.v          # Simulation testbench
  scripts/run_flow.tcl     # Standalone OpenROAD script
  build/                   # Generated outputs (after running)
```

## Why two PDK examples?

Real EDA tools have to be PDK-portable -- the same checker should work against any process. By shipping the same RTL on both sky130 and gf180, the `tools/openforge-{drc,lvs,xrc}/` crates exercise their tech abstraction end-to-end in CI, so a regression that quietly hard-codes sky130 numbers will fail the gf180 tests immediately.
