# Caravel mgmt SoC — Sign-off Report

## Summary

Full Caravel management SoC (`mgmt_core` from
`efabless/caravel_mgmt_soc_litex`) taken into the OpenForge RTL→GDS flow on
sky130A. **Synthesis cleared at ~23k cells; floorplan blocked on missing
macro-LEF plumbing in the flow engine.**

## Toolchain

- Yosys 0.33 (sky130_fd_sc_hd liberty mapping, ABC -dch)
- OpenROAD 26Q1-2947-g77806f977f
- sky130A PDK from Volare
- Backend: WSL (host Windows 11)

## Stage results

| Stage      | Status   | Time   | Notes                                                   |
|------------|----------|--------|---------------------------------------------------------|
| lint       | failed   | 0.1 s  | `verible-verilog-lint` not installed (non-blocking)     |
| synth      | success  | 11.9 s | 23,064 sky130_fd_sc_hd cells mapped                     |
| floorplan  | failed   | 0.8 s  | `[ERROR ORD-2013] instance RAM128 LEF master not found` |
| placement  | skipped  | —      | gated on floorplan                                      |
| cts        | skipped  | —      |                                                          |
| routing    | skipped  | —      |                                                          |
| sta        | skipped  | —      |                                                          |
| signoff    | skipped  | —      |                                                          |

## Synthesis numbers

- RTL files compiled: `defines.v`, `VexRiscv_MinDebugCache.v`,
  `RAM_blackbox.v`, `mgmt_core.v` (~12k lines total before blackboxing
  the DFFRAMs).
- Hierarchy: `mgmt_core → VexRiscv → InstructionCache`, plus 2 blackbox
  DFFRAM macros (RAM128, RAM256).
- Mapped cell count: **23,064** sky130_fd_sc_hd cells in
  `build/synth/netlist.v`.
- This is roughly 3× larger than the picorv32 reference (~7.9k cells),
  matching the brief's "10k–20k" expectation reasonably well — the
  VexRiscv core is meatier than picorv32.

## Why floorplan failed (and what it means)

The DFFRAM banks (`RAM128`, `RAM256`) are **hard macros**, not
synthesisable RTL. The upstream `RAM128.v` / `RAM256.v` files are
pre-mapped sky130 std-cell netlists, but in a real flow they're
delivered as LEF + GDS abstractions. We blackbox them in synthesis (so
yosys doesn't try to expand 100k lines of hand-laid std-cells), then
the floorplan stage needs the macro LEF to know their footprint.

OpenForge's auto-generated `floorplan.tcl` currently emits:

```tcl
read_lef $::env(PDK_ROOT)/sky130A/.../sky130_fd_sc_hd__nom.tlef
read_lef $::env(PDK_ROOT)/sky130A/.../sky130_fd_sc_hd.lef
read_liberty ...
read_verilog ../synth/netlist.v
link_design mgmt_core
```

It does **not** yet plumb additional `read_lef` lines for project-supplied
hard macros. The macro LEFs are vendored at `lef/RAM128.lef` and
`lef/RAM256.lef` (also `gds/*.gds.gz`), ready to go.

## What's needed to make it route

1. **Flow-engine: add `macro_lefs:` yaml key.** Floorplan stage should
   accept a list of extra LEF paths and emit `read_lef` for each before
   `read_verilog`. ~10-line change in `packages/core/src/openforge/flow/full_flow.py`
   in the floorplan tcl generator.
2. **Macro placement.** With ~12k extra std-cell-equivalent area locked
   into two RAM blocks, the floorplan needs explicit `place_macro` calls
   (or `macro_placement -global`) to pin them before global place.
3. **PDN over macros.** Power distribution needs straps over the macros;
   `pdngen` config tweak.
4. After 1-3, expected: ~30 min global+detail route to a writable
   `routed.def`, similar runtime to picorv32 once the macro overhead is
   accounted for.

## Files for next attempt

- `openforge.yaml` — top, RTL, SDC, floorplan/placement/routing keys all
  set; just add `macro_lefs: [lef/RAM128.lef, lef/RAM256.lef]` once the
  yaml schema supports it.
- `lef/RAM128.lef`, `lef/RAM256.lef` — DFFRAM macro abstractions.
- `gds/RAM128.gds.gz`, `gds/RAM256.gds.gz` — DFFRAM GDS for final
  GDS merge in sign-off.

## Time budget

Total wall-clock for this scaffold + try-to-run: ~25 min.
