# asic-caravel-sky130

Caravel `user_proj_example` — a Wishbone-attached counter from the
[Efabless caravel_user_project](https://github.com/efabless/caravel_user_project)
harness — wired through the OpenForge RTL→GDS flow on SkyWater sky130A.

## What this design is

Caravel is the Efabless harness chip used by every Open MPW / chipIgnite tape-out
on sky130. It wraps a user project area in a management SoC (PicoRV32 + flash
controller + GPIO/SPI/I2C). This example scaffolds the upstream
**`user_proj_example`**: a 32-bit counter exposed on the Wishbone bus and
mirrored to the user-area GPIO pads. It's the canonical "hello world" for the
Caravel flow.

| | |
| --- | --- |
| Top module | `user_proj_example` |
| Clock | `wb_clk_i` @ 40 MHz (25 ns) |
| Bus | Wishbone classic (32-bit) |
| GPIO | 38 user-area I/O |
| Logic analyzer | 128-bit |
| Expected synth cell count | **~1,000–2,000** sky130_fd_sc_hd cells |

For comparison: `asic-picorv32-sky130/` synthesises to ~7,971 cells; the full
Caravel **management SoC** (PicoRV32 + housekeeping + DLL + IO mux) is roughly
**50,000+ cells** and is intended as a future stretch goal — see
*Scaling up to full Caravel* below.

## Files

```
examples/asic-caravel-sky130/
├── openforge.yaml          # full RTL→GDS run definition
├── constraints/caravel.sdc # 40 MHz wb_clk_i + I/O delays
├── src/
│   ├── defines.v           # Caravel parameter macros
│   ├── user_proj_example.v # the actual counter design
│   └── user_project_wrapper.v  # harness wrapper (informational)
├── README.md               # this file
└── SIGNOFF_REPORT.md       # placeholders for first flow run
```

The RTL files were fetched verbatim from the upstream
`efabless/caravel_user_project` repo (Apache-2.0). To refresh:

```sh
curl -L -o src/user_proj_example.v \
  https://raw.githubusercontent.com/efabless/caravel_user_project/main/verilog/rtl/user_proj_example.v
curl -L -o src/user_project_wrapper.v \
  https://raw.githubusercontent.com/efabless/caravel_user_project/main/verilog/rtl/user_project_wrapper.v
curl -L -o src/defines.v \
  https://raw.githubusercontent.com/efabless/caravel_user_project/main/verilog/rtl/defines.v
```

## Running the flow

From the OpenForge repo root, with `PDK_ROOT` pointing at a sky130A install:

```sh
openforge flow run examples/asic-caravel-sky130/openforge.yaml
```

This walks the DAG: `lint → synth → floorplan → place → cts → route →
detail_route → sta → drc → lvs → gds`. Outputs land under
`examples/asic-caravel-sky130/build/` (gitignored — never committed).

Once the flow completes, populate `SIGNOFF_REPORT.md` with the same shape used
in `examples/asic-picorv32-sky130/SIGNOFF_REPORT.md` (cell counts, LVS device
match, xRC corner sweep, DRC violation totals).

### Floorplan tuning

The yaml ships with a 600×600 µm die at 30% utilization — chosen because that
combination landed a clean `routed.def` for the comparably-sized PicoRV32 on
the same tech (see `picorv32` SIGNOFF_REPORT for the convergence story). The
real Caravel user area is **2920×3520 µm**; if you want layout-accurate pin
placement matching the harness, override `floorplan.die_area` and
`floorplan.core_area` to those dimensions and supply a Caravel pin-config DEF.

## Scaling up to full Caravel (stretch goal)

To stress-test signoff against the full ~50K-cell Caravel management SoC:

1. Clone https://github.com/efabless/caravel into `src/caravel/` and pull the
   entire `verilog/rtl/` tree (mgmt_core_wrapper, housekeeping, DLL, etc.).
2. Change `top_module` to `caravel` and add every `verilog/rtl/*.v` to
   `rtl_sources` in dependency order (or use a Yosys `read_verilog -I` scan).
3. Bump `floorplan.die_area` to `[0, 0, 3588, 5188]` (the real Caravel die
   size in µm, minus the seal ring).
4. Expect ~50K-cell synth, multi-hour OpenROAD detail-route, and a GDS in
   the 200–500 MB range. The Phase 3 `openforge-{drc,lvs,xrc}` binaries
   should still load it — that scale is the reason this example exists.

Track that scale-up as a follow-up; the user_proj_example variant is what's
checked in here so the flow stays runnable in well under an hour.

## License

The RTL is Apache-2.0 (Efabless Corporation, 2020). The OpenForge flow
configuration is the same license as the rest of the repo.
