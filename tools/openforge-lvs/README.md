# openforge-lvs

OpenForge LVS — Rust-based Layout-vs-Schematic checker.

## What it does

Compares a layout description against a schematic netlist and reports whether
they describe the same circuit. Comparison is performed by graph isomorphism
(VF2) on a connectivity graph that treats nets and devices as nodes and
pin-to-net connections as labelled edges.

## Supported inputs (v0.2)

### Layout side

- An extracted SPICE netlist (`--layout file.spice`), or
- A routed design as DEF + LEF (`--layout-def routed.def --layout-lef
  cells.lef`). Each placed component becomes an opaque primitive whose
  "model" is the LEF macro name; connectivity is taken from the DEF `NETS`
  section. The layout extractor handles ROW / TRACKS / GCELLGRID single-line
  statements and `TAPER` / `TAPERRULE` route qualifiers. Multiple
  `--layout-lef` files may be supplied.

### Schematic side

- SPICE (`.sp`/`.spice`/`.cir`): MOSFETs (`M...`), resistors (`R...`),
  capacitors (`C...`), and subcircuit instances (`X...`).
- Gate-level Verilog (`.v`): output of synthesis tools like Yosys, with
  named-port instantiations:

  ```verilog
  sky130_fd_sc_hd__inv_1 _27_ ( .A(_28_), .Y(_29_) );
  ```

The schematic format is auto-detected from the file extension.

## Cell semantics

Standard cells (e.g. `sky130_fd_sc_hd__nor2_1`) are treated as opaque
primitives in v0.2 — the LVS comparison uses pin-level connectivity only,
not the internal transistor network of the cell. This matches how
synthesised gate-level netlists are represented and how layout DEFs are
emitted by OpenROAD.

Power pins (`VPWR` / `VGND` / `VPB` / `VNB`) declared in a LEF macro but
not connected through the DEF `NETS` section are wired to a synthetic
shared net (e.g. `__PWR__VPWR`) on both sides, so they don't break
isomorphism.

## CLI

SPICE-vs-SPICE (legacy v0.1 path):

```
openforge-lvs check \
    --layout    design_extracted.spice \
    --schematic design.spice \
    --top       inverter
```

DEF + LEF vs gate-level Verilog:

```
openforge-lvs check \
    --layout-def routed.def \
    --layout-lef cells.lef [more.lef ...] \
    --schematic  netlist.v \
    --top        counter
```

DEF + LEF vs SPICE (X-style instantiations of the same cells):

```
openforge-lvs check \
    --layout-def routed.def \
    --layout-lef cells.lef \
    --schematic  netlist.spice \
    --top        counter
```

Writes a JSON report to `lvs.json` (override with `--report`).

Exit code is `0` on MATCH, `1` on MISMATCH, `2` on parse/IO errors.

## Roadmap

- v0.3: Series/parallel device folding, parameter tolerance, hierarchical LVS,
  bus-port name reconciliation between Verilog and DEF (presently both must
  use the same `name[index]` notation).
- v0.4: Property checks (permeability, area), connectivity-only fallback,
  open-cell transistor-level expansion (drop the "opaque primitive"
  assumption).

## License

GPL-3.0-or-later.
