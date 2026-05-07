# openforge-xrc

OpenForge xRC — Rust-based parasitic extraction (R + C) for VLSI layouts.

## What it does

Reads a routed DEF + LEF + tech file and emits SPEF (Standard Parasitic Exchange
Format) describing per-net resistance and capacitance.

v0.1 uses pattern-based extraction:

- **Resistance**: `R = sheet_R * length / width` per wire segment, plus per-cut
  via resistance from the tech file.
- **Capacitance**: parallel-plate area cap + per-edge fringe cap.
- **Coupling**: same-layer parallel-run coupling via R-tree spatial query
  (skip cross-layer for v0.1).

This is engineering-grade, not foundry sign-off. A 3D field solver with
multi-corner support is out of scope for v0.1.

## Usage

```bash
openforge-xrc extract \
    --def design_routed.def \
    --lef cells.lef \
    --tech sky130A \
    --output design.spef
```

`--tech` accepts either a built-in name (`sky130A`) or a path to a JSON
tech file matching the `TechFile` schema.

## Layout

- `src/def/` — DEF parser (subset: DESIGN/UNITS/DIEAREA/COMPONENTS/NETS+ROUTED)
- `src/lef/` — LEF parser (MACRO/PIN/LAYER subset)
- `src/tech/` — tech file types + built-in sky130A constants
- `src/extract/` — extraction engine: resistance, capacitance, coupling
- `src/spef/` — SPEF writer + lightweight reader
- `tests/` — integration tests against hand-crafted fixtures
