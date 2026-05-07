# openforge-drc

OpenForge DRC engine — a fast Rust-based design rule checker, intended as a
drop-in replacement for KLayout DRC on common width/space/enclosure rules.

**v0.3** (this checkout) adds a **KLayout DRX-compatible parser** for the
Ruby-subset DSL used by the production sky130A and gf180mcuC decks. You can
now feed an existing `.drc` deck (e.g. `sky130A_mr.drc`) directly via
`--rules-drx` (or via `--rules`, which auto-detects the format).

v0.2 added an R-tree spatial index for spacing (10x+ speedup on large
designs), a real `enclosure` checker, a windowed `density` operator, and
parallel rule execution via rayon.

## CLI

```text
$ openforge-drc check counter.gds \
    --rules rules.drc \
    --tech sky130A \
    --output drc.rdb \
    --format rdb

Loading GDS: counter.gds
Parsing rule deck: rules.drc
Found 3 rules across 2 layers.
Checking met1.W.1 (min width 0.14 um on met1)... 0 violations
Checking met1.S.1 (min space 0.14 um on met1)... 0 violations
Checking li1.W.1 (min width 0.17 um on li1)... 0 violations

Total: 0 violations.
RDB written to drc.rdb
```

`--format` accepts `rdb` (KLayout XML, default), `text`, or `json`.

### Rule decks: two flavors

`--rules <path>` — auto-detects between the legacy simple format and the new
DRX (Ruby-subset) format. `--rules-drx <path>` forces DRX.

## Rule deck syntax: DRX (KLayout-compatible, v0.3)

Real sky130A / gf180mcuC decks ship in this format and can be used unchanged
on the supported subset:

```ruby
# sky130A subset
report("sky130A DRC")

li1     = input(67, 20)
licon   = input(66, 44)
met1    = input(68, 20)
nwell   = input(64, 20)
diff    = input(65, 20)

# Width / spacing.
li1.width(0.17).output("li.1", "Min width 0.17")
met1.width(0.14).output("met1.1", "Min width 0.14")
li1.space(0.17).output("li.2", "Min spacing 0.17")

# Enclosure.
li1.enclosing(licon, 0.08).output("li.4", "Min enclosure 0.08")

# Boolean op then width on the derived layer.
diff_outside_well = diff.outside(nwell)
diff_outside_well.width(0.15).output("diff.1", "Min diff width outside nwell")

# Density: emits two rules (min and max bounds).
met1.density(100).range(0.20, 0.80).output("met1.D", "Met1 density")
```

**Supported in v0.3:** `input(layer[, datatype])`, `report(name)`,
`.width`, `.space`, `.enclosing`, `.inside`, `.outside`, `.not`, `.and`,
`.or`, `.density(...).range(...)`, `.output(name, msg)`. Comments,
`.um`/`.nm`/`.mm` numeric suffixes, keyword args, and string/symbol
literals all work. `.with_length`, `.angles` and other unsupported
constructs are parsed and skipped with a warning, so a partial deck still
runs.

**Roadmap:** v0.4 — true polygon-clipping booleans (currently bbox-approximated
for derived layers), more metric modes (`euclidian` / `square` / `projection`),
`with_length`/`angles` enforcement. v0.5 — full Ruby DSL.

## Rule deck syntax: legacy simple format

```text
# Comments start with '#'.
LAYER met1 = 68            # default datatype = 0
LAYER li1  = 67 / 0

RULE met1.W.1 : met1.width  < 0.14 = "M1 minimum width"
RULE met1.S.1 : met1.space  < 0.14 = "M1 minimum spacing"
RULE met1.E.1 : licon.enclosed_by(li1) < 0.06 = "li enclosure of licon"
RULE my.NOT.1 : nwell.not(diff) -> nwell_only
RULE met1.D.min : met1.density window 100 < 0.20 = "min met1 density"
RULE met1.D.max : met1.density window 100 > 0.80 = "max met1 density"
```

## Supported

- `width`     — minimum interior width per polygon
- `space`     — minimum edge-to-edge spacing on the same layer
                (R-tree accelerated; near-linear on sparse layouts)
- `enclosure` — every `inner` polygon must be enclosed by some `outer`
                polygon with at least `min_um` margin on every side
- `density`   — windowed area density, with `<` for min and `>` for max,
                tile size in microns; parallel over windows via rayon
- Parallel rule execution (rayon) - independent rules run concurrently
- RDB XML output (KLayout compatible) plus text + JSON

## Planned

- `not` (parsed today, but no checks emitted)
- Boolean ops (`and`, `or`, `xor`) over derived layer sets
- Antenna checks
- Hierarchical layout flattening with cell instance arrays

## Tests

```bash
cd tools/openforge-drc
cargo test --release
```

The integration test (`tests/integration.rs`) builds a tiny GDS in-memory
with a known violation and verifies the engine reports exactly one. A
smoke test (`tests/counter_smoke.rs`) opportunistically runs against
`examples/asic-counter-sky130/build/gds_export/counter.gds` if it has been
generated; otherwise it silently passes.

## License

GPL-3.0-or-later (workspace default).
