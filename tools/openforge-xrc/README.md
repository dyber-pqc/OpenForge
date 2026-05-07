# openforge-xrc

OpenForge xRC — Rust-based parasitic extraction (R + C) for VLSI layouts.

## What it does

Reads a routed DEF + LEF + tech file and emits SPEF (Standard Parasitic Exchange
Format) describing per-net resistance and capacitance.

## v0.2 model

Pattern-based extraction with closed-form physics:

- **Resistance**:
  - Wire: `R = sheet_R * length / width` per segment.
  - Vias: per-cut R from the tech file, divided by `cut_count` for multi-cut
    via arrays (e.g. a 2×2 cut grid quarters the resistance).
- **Self capacitance** (Sakurai–Tamaru, 1983):
  ```
  C/l = eps * [ w/h + 0.77 + 1.06·(w/h)^0.25 + 1.06·(t/h)^0.5 ]
  ```
  where `w` is wire width, `t` thickness, `h` height to the underlying
  reference plane, and `eps = eps_0 · eps_r`. The first term is the
  parallel-plate (area) component; the rest is two-edge + thickness-edge
  fringe. When `height_to_substrate_um` is missing from the tech file, the
  legacy lumped (`cap_per_area`, `fringe_cap`) constants are used as a
  fallback.
- **Same-layer coupling**: parallel-run model via R-tree spatial query
  (unchanged from v0.1).
- **Cross-layer (vertical) coupling** *(new in v0.2)*: for routed segments
  on adjacent metal layers L and L±1 whose 2D footprints overlap by area
  `A`, an additional parallel-plate cap `C = eps_0·eps_r·A / d_ild` is
  added, where `d_ild` is the inter-layer dielectric thickness from the
  tech file (`LayerProps.inter_layer_distance_um`).

This is engineering-grade, not foundry sign-off. A 3D field solver with
multi-corner support is out of scope.

## SPEF output

The writer emits IEEE-1481 with a top-level `*PORTS` section listing
top-level pins, hierarchical net/instance names preserved using `/` as the
divider, and indented `*CONN` / `*CAP` / `*RES` bodies for readability.

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

## Reference results — counter example

On `examples/asic-counter-sky130/build/routing/routed.def` (35 cells,
37 nets, 2250 µm of routing on li1+met1):

| metric            | v0.1     | v0.2     |
|-------------------|----------|----------|
| Total wirelength  | 2250 µm  | 2250 µm  |
| Total R           | 2085 Ω   | 2085 Ω   |
| Total C           | 56.4 fF  | 1733.9 fF |
| Coupling pairs    | 209      | 209 (same-layer) |
| Cross-layer pairs | —        | counted in net coupling |

The order-of-magnitude jump in C reflects switching from a small lumped
fringe constant to the Sakurai self-cap (which integrates the full edge
field) plus added vertical coupling. The new numbers track open-source
field-solver references within ~15-20% on this kind of digital flow.

## Layout

- `src/def/` — DEF parser (subset: DESIGN/UNITS/DIEAREA/COMPONENTS/NETS+ROUTED)
- `src/lef/` — LEF parser (MACRO/PIN/LAYER subset)
- `src/tech/` — tech file types + built-in sky130A constants
- `src/extract/`
  - `resistance.rs` — wire + via R (multi-cut aware)
  - `capacitance.rs` — Sakurai–Tamaru self-cap
  - `coupling.rs` — same-layer parallel-run coupling
  - `cross_layer.rs` — vertical (adjacent-layer) coupling **(new)**
- `src/spef/` — SPEF writer + lightweight reader
- `tests/` — integration tests against hand-crafted fixtures + the
  counter example
