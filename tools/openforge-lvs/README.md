# openforge-lvs

OpenForge LVS — Rust-based Layout-vs-Schematic checker.

## What it does

Compares two SPICE netlists (one extracted from layout, one drawn as schematic)
and reports whether they describe the same circuit. Comparison is performed by
graph isomorphism (VF2) on a connectivity graph that treats nets and devices
as nodes and pin-to-net connections as labeled edges.

## Current scope (v0.1)

- SPICE-to-SPICE comparison only. Extraction from GDS/DEF is out of scope for v0.1.
- Supported devices: MOSFETs (`M...`), resistors (`R...`), capacitors (`C...`),
  and subcircuit instances (`X...`).
- Device match criterion: same kind, same model, identical declared params
  (e.g. `w`, `l`).
- Net match criterion: ports must match by name; internal nets are anonymous.

## Roadmap

- v0.2: Extract layout connectivity directly from GDS + LEF/DEF.
- v0.3: Series/parallel device folding, parameter tolerance, hierarchical LVS.
- v0.4: Property checks (permeability, area), connectivity-only fallback.

## CLI

```
openforge-lvs check \
    --layout    design_extracted.spice \
    --schematic design.spice \
    --top       inverter
```

Writes a JSON report to `lvs.json` (override with `--report`).

Exit code is `0` on MATCH, `1` on MISMATCH, `2` on parse/IO errors.

## License

GPL-3.0-or-later.
