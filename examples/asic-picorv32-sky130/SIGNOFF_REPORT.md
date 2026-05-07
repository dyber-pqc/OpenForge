# Sign-off Smoke Test Report

**Date:** 2026-05-07
**Phase 3 binaries under test:** `openforge-drc`, `openforge-lvs`, `openforge-xrc`

## Artifacts used

The PicoRV32 example (`examples/asic-picorv32-sky130/`) has **no build artifacts**
on disk — the Yosys/OpenROAD flow has not produced `routed.def` or `final.gds`
yet. Per the task brief, the smoke test was instead run against the
**counter fallback** at `examples/asic-counter-sky130/`, which has a complete
set of post-route artifacts:

- `build/routing/routed.def`
- `build/routing/routed.v`
- `build/synth/netlist.v`
- `build/gds_export/counter.gds`
- LEF: `share/pdk/sky130/lef/sky130_fd_sc_hd.lef`
- DRC rules: `tools/openforge-drc/tests/fixtures/sky130_subset.drc`

## 1. DRC (`openforge-drc check`)

| Metric | Value |
| --- | --- |
| Rule deck | `sky130_subset.drc` (DRX format) |
| Rules loaded | **8** rules across **6** layers |
| Derived layers materialised | 1 |
| **Total violations** | **721,702** |
| Output | `drc.json` |

Rule deck warning: `line 4: report() does not yield a layer` (cosmetic).

The violation count is enormous because the counter GDS has no fill / no
explicit DRC clean-up; nearly every li/met1 shape trips width/spacing/density.

## 2. LVS (`openforge-lvs check`)

Layout side: routed DEF + LEF. Schematic side: gate-level Verilog netlist
(`build/synth/netlist.v`), top = `counter`.

| Metric | Layout | Schematic |
| --- | --- | --- |
| Devices | 35 | 31 |
| Nets    | 42 | 38 |

**Verdict: MISMATCH** — `device count mismatch: layout=35, schematic=31`.

VF2 graph isomorphism halted before producing matched pairs (likely because
the counts diverge before refinement). Most plausible cause: physical-only
cells (tap / decap / fill) are present in the routed DEF but absent from the
synthesis netlist. Worth a follow-up to make the LVS engine filter physical
cells by LEF class.

## 3. xRC (`openforge-xrc extract`) — corner sweep

DEF: 35 components, 37 nets, 2 routing layers used. Total wirelength: 2250.0 um.
Note: 0 cells were loaded from the LEF (the non-merged sky130_fd_sc_hd.lef
parses cleanly but doesn't expose pin geometry the extractor recognises);
the merged LEF crashes the parser (see Failures below).

| Corner | Total R (Ω) | Total C (fF) | Worst net C (fF) | Coupling pairs |
| ---: | ---: | ---: | ---: | ---: |
| min | 2084.9 | 1565.7 | 395.57 | 209 |
| typ | 2084.9 | 1739.6 | 439.52 | 209 |
| max | 2084.9 | 1913.6 | 483.47 | 209 |

R is corner-invariant (geometry-only); C scales ~min:typ:max ≈ 0.82 : 0.91 : 1.00,
which matches the expected sky130 inter-layer cap derate spread. Coupling pair
count is identical across corners (adjacency is geometric); 26,806 pairs
were skipped as below the adjacency threshold.

## Failures observed

1. **xRC LEF parser crashes on merged sky130 LEF.**
   `share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef`:
   ```
   Error: parsing LEF
   Caused by: LEF parse error at line 68384: EOF in PIN
   ```
   Worked around by using the non-merged LEF. The merged file is valid
   (OpenROAD reads it); the openforge-xrc LEF parser is choking on a `PIN`
   block near EOF.

2. **LVS does not skip physical-only cells.** The 4-device / 4-net
   layout-vs-schematic gap is almost certainly tap / decap cells included
   from the routed DEF. Engine should filter LEF `CLASS CORE SPACER` /
   `CLASS CORE WELLTAP` / `CLASS CORE ANTENNACELL` before VF2.

3. **PicoRV32 has no post-route artifacts.** The full Yosys+OpenROAD flow
   for the picorv32 example has not been run on this checkout; nothing in
   `examples/asic-picorv32-sky130/build/` exists.

## Headline numbers

- DRC: 8 rules / **721,702** violations
- LVS: 35 vs 31 devices, 42 vs 38 nets — **MISMATCH**
- xRC: R = 2084.9 Ω (all corners), C = 1565.7 / 1739.6 / 1913.6 fF (min/typ/max),
  209 coupling pairs.
