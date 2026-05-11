# Sign-off Report — Caravel `user_proj_example`

**Status:** scaffold — to be filled after the first end-to-end flow run.
**Phase 3 binaries under test:** `openforge-drc`, `openforge-lvs`, `openforge-xrc`.

This file mirrors the structure of
`examples/asic-picorv32-sky130/SIGNOFF_REPORT.md`. Run the flow per the README,
then drop real numbers into the placeholder cells below.

---

## Flow status

| Stage | Status | Artifact |
| --- | --- | --- |
| Synth (Yosys) | _TBD_ | `build/synth/netlist.v` |
| Floorplan | _TBD_ | `build/floorplan/floorplan.def` (600×600 µm) |
| Placement | _TBD_ | `build/placement/placed.def` |
| CTS | _TBD_ | `build/cts/cts.def` |
| Global route | _TBD_ | `build/routing/route.guide` |
| Detail route | _TBD_ | `build/routing/routed.def`, `routed.v` |
| GDS export | _TBD_ | `build/gds_export/user_proj_example.gds` |
| xRC | _TBD_ | `build/xrc/user_proj_example.{min,typ,max}.spef` |
| LVS | _TBD_ | `build/lvs/lvs.json` |
| DRC | _TBD_ | `build/drc/drc.txt` |

## Synth — cell count

| Metric | Value |
| --- | ---: |
| Total cells | _TBD (~1,000–2,000 expected)_ |
| Sequential cells (DFFs) | _TBD_ |
| Combinational cells | _TBD_ |
| Estimated area (µm²) | _TBD_ |

## LVS — `user_proj_example` (routed.def vs routed.v)

| Metric | Layout | Schematic |
| --- | ---: | ---: |
| Devices | _TBD_ | _TBD_ |
| Nets    | _TBD_ | _TBD_ |

**Verdict:** _TBD (target: MATCH)_

## xRC — corner sweep

| Metric | min | typ | max |
| --- | ---: | ---: | ---: |
| Total wirelength (µm) | _TBD_ | _TBD_ | _TBD_ |
| Total R (Ω) | _TBD_ | _TBD_ | _TBD_ |
| Total C (fF) | _TBD_ | _TBD_ | _TBD_ |
| Coupling pairs | _TBD_ | _TBD_ | _TBD_ |

SPEF expected at `build/xrc/user_proj_example.{min,typ,max}.spef`. Sanity
bound: total C should land in `[10⁴, 10⁷]` fF for a ~1.5K-cell counter on
sky130 — anything outside that range is the same xRC scaling bug fixed in
`d8b8ccb` resurfacing.

## DRC

| Metric | Value |
| --- | --- |
| Rule deck | `tools/openforge-drc/tests/fixtures/sky130_subset.drc` (DRX) |
| Rules loaded | _TBD_ |
| Violations | _TBD_ |

## Notes

- This design intentionally targets the **smaller** caravel_user_project
  variant (~1–2K cells), not the full management SoC (~50K cells). The
  bigger run is tracked as a stretch goal in the README.
- If the routing fails to converge at 30% utilization on a 600×600 µm die,
  follow the same playbook used for picorv32: drop utilization, raise die
  area, cap `routing.droute_end_iter` so a writable `routed.def` still
  lands deterministically.
