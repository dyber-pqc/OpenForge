# openforge-drc

OpenForge DRC engine — a fast Rust-based design rule checker, intended as a
drop-in replacement for KLayout DRC on common width/space/enclosure rules.

This is **v0.1**: the foundation. It reads GDSII, parses a small subset of
KLayout's DRX rule language, runs `width` and `space` checks, and emits
violations as KLayout-compatible RDB XML.

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

## Rule deck syntax

```text
# Comments start with '#'.
LAYER met1 = 68            # default datatype = 0
LAYER li1  = 67 / 0

RULE met1.W.1 : met1.width  < 0.14 = "M1 minimum width"
RULE met1.S.1 : met1.space  < 0.14 = "M1 minimum spacing"
RULE met1.E.1 : licon.enclosed_by(li1) < 0.06 = "li enclosure of licon"
RULE my.NOT.1 : nwell.not(diff) -> nwell_only
```

## Supported in v0.1

- `width`  — minimum interior width per polygon
- `space`  — minimum edge-to-edge spacing between polygons on the same layer
- RDB XML output (KLayout compatible)
- text + JSON output

## Planned

- `enclosure` and `not` (parsed today, but no checks emitted)
- Boolean ops (`and`, `or`, `xor`) over derived layer sets
- Spatial index (`rstar`) replacing the O(N^2) pre-filter in `space`
- Density and antenna checks
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
