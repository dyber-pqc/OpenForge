# ASIC Counter - IHP sg13g2 Full RTL-to-GDS Flow

The same 8-bit synchronous up-counter as `examples/asic-counter-sky130/` and
`examples/asic-counter-gf180/`, retargeted to the open-source **IHP sg13g2**
PDK (130 nm SiGe BiCMOS, 1.2 V / 3.3 V / 5 V devices). This example proves
that OpenForge's tech abstraction handles all three of the major open PDKs:
SkyWater sky130A, GlobalFoundries gf180mcuC, and IHP sg13g2.

## Design

- **Module**: `counter` -- 8-bit up-counter with synchronous reset, enable,
  and overflow flag (verbatim copy of the sky130 RTL)
- **Target frequency**: 75 MHz (~13.3 ns clock period)
- **PDK**: `ihp_sg13g2` (130 nm SiGe BiCMOS, BSD-3 licensed open PDK)
- **Standard cells**: `sg13g2_stdcell`
- **Corners**: TT (1.20 V / 25 C), SS (1.08 V / 125 C), FF (1.32 V / -40 C)
- **Metal stack**: 5 thin Cu layers (Metal1..Metal5) + 2 thick Al top
  metals (TopMetal1, TopMetal2) — 7 routing layers total

## What is identical to the other PDK examples

- `rtl/counter.v` and `tb/counter_tb.v` — copied verbatim from
  `examples/asic-counter-sky130/`
- The flow stages (lint -> synth -> floorplan -> place -> CTS -> route -> STA -> DRC -> xRC -> LVS -> GDS)
- The OpenForge orchestration (`openforge.yaml`)

## What changes per PDK

| Item                | sky130A                  | gf180mcuC                 | ihp_sg13g2                  |
|---------------------|--------------------------|---------------------------|-----------------------------|
| Standard cell lib   | `sky130_fd_sc_hd`        | `gf180mcu_fd_sc_mcu7t5v0` | `sg13g2_stdcell`            |
| Voltage (typ)       | 1.80 V                   | 5.00 V                    | 1.20 V                      |
| Routing layers      | li1, met1..met5          | Metal1..Metal5            | Metal1..Metal5 + TM1, TM2   |
| Top metal           | met5 (1.6 µm Cu)         | Metal5 (0.9 µm Cu)        | TopMetal2 (3.0 µm Al)       |
| Min M1 width        | 0.14 µm                  | 0.23 µm                   | 0.16 µm                     |
| Default freq        | 100 MHz                  | 50 MHz                    | 75 MHz                      |
| Driving cell        | `sky130_fd_sc_hd__inv_2` | `gf180mcu_…__inv_2`       | `sg13g2_inv_2`              |
| Filltie / decap     | `sky130_…__{tap,decap,fill,diode}*` | `gf180mcu_…__{filltie,filldecap,filler,…}*` | `sg13g2_{decap,fill,tap,tielo,tiehi,cdummy,…}*` |

The OpenForge signoff binaries have `ihp_sg13g2` baked in as a built-in
tech, so the DRC/xRC/LVS stages run against a Rust process file -- no
Magic / Netgen / Quantus install needed for the smoke check.

## Prerequisites

- An IHP sg13g2 PDK install. The open PDK lives on GitHub:

  ```bash
  # Clone the IHP-Open-PDK repo (BSD-3 licensed)
  git clone https://github.com/IHP-GmbH/IHP-Open-PDK.git
  export PDK_ROOT=$PWD/IHP-Open-PDK
  ```

  The sg13g2 process tree is at `$PDK_ROOT/ihp-sg13g2/`. The standard
  cell library is at `$PDK_ROOT/ihp-sg13g2/libs.ref/sg13g2_stdcell/`.

- [Yosys](https://github.com/YosysHQ/yosys) for synthesis
- [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) for P&R
  (the IHP repo ships an `ihp-sg13g2` flow.tcl integration)
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA) for timing
- Optional: [Magic](https://github.com/RTimothyEdwards/magic) and
  [KLayout](https://www.klayout.de/) for cross-checking signoff against
  the vendor decks shipped under `libs.tech/klayout/`

## How to Run

> NOTE: this example is **not** wired into CI. The full RTL->GDS flow
> needs an IHP-Open-PDK clone, which is environment-dependent. The
> OpenForge signoff binaries (`openforge-drc`, `openforge-lvs`,
> `openforge-xrc`) ship with `ihp_sg13g2` as a built-in tech and have
> their own unit tests under `tools/openforge-{drc,lvs,xrc}/tests/ihp_sg13g2.rs`.

### OpenForge CLI

```bash
cd examples/asic-counter-ihp-sg13g2
openforge run                     # full flow: lint through GDS
openforge run --stage synth       # stop after synthesis
openforge run --stage sta         # stop after timing analysis
```

### OpenForge Desktop

1. **File > Open Project** and select this folder.
2. The Synthesis panel auto-detects the `sg13g2` Liberty target.
3. Click **Run Flow** for the full ASIC flow.
4. The Reports panel shows timing, DRC (`openforge-drc --tech ihp_sg13g2`),
   xRC, and LVS results.

### Signoff with built-in OpenForge engines

```bash
# Parasitic extraction with the ihp_sg13g2 built-in process file
openforge-xrc extract \
    --def build/counter_routed.def \
    --lef $PDK_ROOT/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef \
    --tech ihp_sg13g2 \
    --corner all \
    -o build/counter.spef

# LVS using the ihp_sg13g2-aware physical-only filter
openforge-lvs check \
    --layout-def build/counter_routed.def \
    --layout-lef $PDK_ROOT/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef \
    --schematic build/counter_routed.v \
    --tech ihp_sg13g2 \
    --top counter

# DRC against a custom IHP DRX deck (or use the bundled subset for a smoke check)
openforge-drc check build/counter.gds \
    --rules-drx $PDK_ROOT/ihp-sg13g2/libs.tech/klayout/tech/drc/sg13g2_minimal.drc \
    --tech ihp_sg13g2 \
    -o build/counter.drc.rdb
```

## Why a third PDK example?

Real EDA tools have to be PDK-portable. Shipping the same RTL on three
different open PDKs (sky130A, gf180mcuC, ihp_sg13g2) means the
`tools/openforge-{drc,lvs,xrc}/` crates exercise their tech abstraction
end-to-end, so a regression that quietly hard-codes one foundry's numbers
will fail the others' tests immediately.

IHP sg13g2 is particularly interesting because it adds:

- **SiGe HBTs** — RF / mixed-signal devices that the digital flow does
  not exercise, but that the LEF/GDS readers still see in the cell library
- **Two thick Al top metals** — TopMetal1 (~2 µm) and TopMetal2 (~3 µm),
  used for RF inductors. The xRC tech file has dramatically lower sheet R
  on these layers (0.010-0.014 Ω/sq vs 0.115 Ω/sq for back-end Cu),
  exercising a wider dynamic range than the all-Cu sky130 / gf180 stacks.

## File Structure

```
asic-counter-ihp-sg13g2/
  openforge.yaml           # Project configuration (PDK = ihp_sg13g2)
  rtl/counter.v            # RTL source (verbatim copy of sky130)
  constraints/counter.sdc  # Timing constraints (75 MHz, 1.2 V cells)
  tb/counter_tb.v          # Simulation testbench
  scripts/                 # (placeholder for OpenROAD scripts)
```
