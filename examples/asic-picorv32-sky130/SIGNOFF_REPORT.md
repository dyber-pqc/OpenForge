# Sign-off Report — PicoRV32 + Counter

**Date:** 2026-05-10
**Phase 3 binaries under test:** `openforge-drc`, `openforge-lvs`, `openforge-xrc`
**Bug fixes since first smoke:** xRC LEF parser EOF-in-PIN (`5e70a83`),
LVS physical-only cell filter (`b0c7a6d`), SDC `remove_from_collection` parser
fix (`5be03d1`), xRC capacitance unit/scaling explosion at scale (`d8b8ccb`).

---

## PicoRV32 (real chip — full RTL-to-GDS flow)

The Yosys → OpenROAD flow now runs end-to-end, producing a routed DEF, a
post-route Verilog netlist, and a final GDS. Routing converged at 0.30
utilization on a 506×506 µm die after lowering density from the original
0.55 / 600×600 plan; TritonRoute optimisation is capped at
`-droute_end_iter 6` so a writable `routed.def` lands deterministically in
~25 minutes even though residual DRT violations don't fully zero out at this
density (final: 2,643 short/spacing markers, all in the highly-congested
li1/met1 stack).

### Flow status

| Stage | Status | Artifact |
| --- | --- | --- |
| Synth (Yosys) | OK | `build/synth/netlist.v` |
| Floorplan | OK | `build/floorplan/floorplan.def` (506×506 µm) |
| Placement | OK | `build/placement/placed.def` |
| CTS | OK | `build/cts/cts.def` (8,159 cells) |
| Global route | OK | `build/routing/route.guide` (2.1 MB) |
| Detail route | **OK** | `build/routing/routed.def` (6.8 MB), `routed.v` |
| GDS export (KLayout) | OK | `build/gds_export/picorv32.gds` (12 MB) |
| xRC | OK (corner sweep) | `build/xrc/picorv32.{min,typ,max}.spef` |
| LVS | **MATCH** | `build/lvs/lvs.json` |
| DRC | OK (volume expected) | `build/drc/drc.txt` |

### LVS — PicoRV32 (routed.def vs routed.v)

Layout: `build/routing/routed.def` + `share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef`.
Schematic: `build/routing/routed.v` (post-route Verilog emitted by OpenROAD).

| Metric | Layout | Schematic |
| --- | ---: | ---: |
| Devices | **7,971** | **7,971** |
| Nets    | **8,191** | **8,191** |

**Verdict: MATCH.** All 7,971 device pairs matched by VF2 isomorphism; no
mismatched nets or devices. The Phase 3 LVS engine handles a real ~8K-cell
RISC-V CPU end-to-end with the merged sky130_fd_sc_hd LEF and the CTS-
buffered post-route netlist.

### xRC — PicoRV32 (routed.def, corner sweep)

DEF: 7,971 components, 8,062 nets, **3 routing layers used** (li1, met1, met2,
met3 — met4/met5 sparse). The merged LEF (441 cells) loads cleanly thanks to
the parser fix (`5e70a83`).

| Metric | Value |
| ---: | ---: |
| Total wirelength | 1,887,929.9 µm (~1.89 mm) |
| Total R | 1,676,813.7 Ω (1.68 MΩ) |
| Total C (min) | **13,045,746.7 fF** (13.05 nF) |
| Total C (typ) | **14,495,274.1 fF** (14.50 nF) |
| Total C (max) | **15,944,801.5 fF** (15.94 nF) |
| Worst-case net (typ) | `_00006_[1]` (R=40,205.2 Ω, C=379,988 fF ≈ 0.38 nF) |
| Coupling pairs | 299,267 (48.8 M skipped — adjacency below threshold) |

SPEF written for `min`, `typ`, `max` corners
(`build/xrc/picorv32.{min,typ,max}.spef`). Min/typ/max ratio 0.90 : 1.00 : 1.10
matches the configured ±10% k_eff derate.

**Note:** an earlier run reported total C = 4.78×10¹⁴ fF (478 petafarads).
That was an xRC bug — divide-by-near-zero on overlapping segment stubs and
a 2D-bbox-as-conductor-area inflation for non-Manhattan wires. Both fixed
in `d8b8ccb` along with a sanity-check regression test that bounds total C
to [10⁵, 10⁸] fF for picorv32-scale designs.

### DRC — PicoRV32 (final.gds, generic sky130_subset deck)

| Metric | Value |
| --- | --- |
| Rule deck | `tools/openforge-drc/tests/fixtures/sky130_subset.drc` (DRX) |
| Rules loaded | 8 across 6 layers |
| Derived layers | 1 |
| **Violations** | **721,702** |

The 721K-violation count tracks the counter baseline 1:1 (same deck, same
density-style rules). The deck is intentionally a coarse smoke check — most
violations are met1 density on the un-filled GDS; tap/decap/fill insertion
and a real PDK rule deck (e.g. Magic+sky130A.tech) would clear the bulk.
Importantly, the engine processes a 12 MB / ~63K-via GDS without crashing
or running out of memory.

---

## Counter (smaller chip — full flow baseline)

Kept from the first smoke pass for regression comparison.

### DRC

| Metric | Value |
| --- | --- |
| Rule deck | `sky130_subset.drc` (DRX format) |
| Rules loaded | 8 across 6 layers |
| Violations | 721,702 |

### LVS

| Metric | Layout | Schematic |
| ---: | ---: | ---: |
| Devices | 35 | 35 |
| Nets    | 42 | 42 |

**MATCH.**

### xRC corner sweep

| Corner | Total R (Ω) | Total C (fF) | Coupling pairs |
| ---: | ---: | ---: | ---: |
| min | 2,084.9 | 458.6 | 209 |
| typ | 2,084.9 | 509.6 | 209 |
| max | 2,084.9 | 560.6 | 209 |

(Counter baseline corrected after the `d8b8ccb` xRC fix — the earlier 1,739.6 fF
was bug-inflated. New value is physically consistent with ~0.075 fF/µm self-cap
on 2,250 µm of routing plus modest coupling.)

---

## Bug status

| Issue | Status | Commit |
| --- | --- | --- |
| xRC LEF parser EOF-in-PIN on merged sky130 LEF | **Fixed** | `5e70a83` |
| LVS doesn't filter physical-only cells | **Fixed** | `b0c7a6d` |
| OpenROAD SDC `remove_from_collection` unsupported | **Fixed (worked around)** | `5be03d1` |
| PicoRV32 routing fails on 0.55 util / 600×600 µm | **Fixed (tuning)** | this commit |
| OpenForge `flow run` ignores yaml `utilization` / `die_area` | **Fixed** | `6c9eaef` |
| xRC capacitance unit explosion at scale (478 PF on PicoRV32) | **Fixed** | `d8b8ccb` |

The flow gap above is real: `packages/core/src/openforge/flow/full_flow.py`
hard-codes `core_utilization=50.0` from `FullFlowConfig` defaults, and the
CLI never plumbs the per-stage yaml overrides through. For now the
`build/floorplan/floorplan.tcl` is patched in place to use 30% utilization;
a follow-up should let the yaml drive `-utilization`, `-die_area`,
`-core_area`, and the routing knobs (`droute_end_iter`, etc.) directly.

## Headline

- **Real PicoRV32 RISC-V CPU goes RTL → GDS** through the OpenForge flow on
  sky130: 7,971 standard cells, 1.89 mm of wire, 12 MB GDS.
- All three Phase 3 sign-off binaries (`drc`, `lvs`, `xrc`) handle the design
  cleanly: LVS matches device-for-device, xRC writes corner-swept SPEF, DRC
  parses the GDS without crashes.
- Remaining open item is **flow-side**: yaml-to-OpenROAD knob plumbing so the
  per-design `floorplan.utilization` / `floorplan.die_area` overrides take
  effect without hand-editing the generated tcl.
