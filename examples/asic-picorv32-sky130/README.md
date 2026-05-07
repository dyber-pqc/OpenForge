# asic-picorv32-sky130

PicoRV32 RISC-V CPU taken through the OpenForge RTL-to-GDS flow on the
SkyWater sky130 PDK. Used as a sign-off scale-up target for the Rust DRC,
XRC, and STA tools — the counter design is too small to stress them.

## Source

`rtl/picorv32.v` is the canonical PicoRV32 from
[YosysHQ/picorv32](https://github.com/YosysHQ/picorv32) (single-file core,
ISC licensed; see the file's own header). ~3050 lines of Verilog, ~3000
mapped sky130_fd_sc_hd cells after synthesis.

## Files

| File                          | Purpose                                          |
|-------------------------------|--------------------------------------------------|
| `openforge.yaml`              | ASIC flow (lint -> synth -> P&R -> STA/DRC/LVS) |
| `rtl/picorv32.v`              | RISC-V core RTL                                  |
| `constraints/picorv32.sdc`    | 50 MHz clock + I/O delay constraints             |
| `tb/picorv32_tb.v`            | 100-cycle smoke testbench (NOP feed)             |

## Running

Requires sky130A PDK and the OpenROAD/Yosys/Magic toolchain on the host.

```bash
# from repo root
python -c "
from openforge.flow.full import FullFlowRunner
r = FullFlowRunner('examples/asic-picorv32-sky130/openforge.yaml',
                   backend='wsl')
r.run()
"
```

After the flow completes, run the Rust sign-off tools:

```bash
cargo build --release

# DRC
target/release/openforge-drc check \
    examples/asic-picorv32-sky130/build/gds_export/picorv32.gds \
    --rules tools/openforge-drc/tests/fixtures/simple.drc \
    --tech sky130A \
    --output picorv32.rdb

# Parasitic extraction
target/release/openforge-xrc extract \
    --def examples/asic-picorv32-sky130/build/routing/picorv32.routed.def \
    --lef $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef \
    --tech sky130A \
    --output picorv32.spef
```

## Tuning notes

- Initial die size is 600x600 um at 0.55 utilization. PicoRV32 packs into
  ~250-300 um square at sky130 sc_hd density 0.6, so this is conservative.
  Shrink for a tighter run; grow if the router can't close.
- 50 MHz period (20 ns) is intentionally relaxed. 100 MHz is feasible on
  sky130 sc_hd with retiming (`abc -dch -retime`) but not in this stock deck.

## Results

This example was authored as a scale-up target. The full flow has not been
run yet on this checkout — running it requires a populated `$PDK_ROOT`
pointing at sky130A, which is not in this environment. See the "Running"
section above to reproduce.

When run, populate this section with:

- Synthesis cell count, post-mapping area
- Die / core dimensions, achieved utilization
- WNS / TNS / runtime per stage
- DRC violation count from `openforge-drc`
- Total R, C, wirelength from `openforge-xrc`
