# OpenLane Interoperability

OpenForge ships a one-shot adapter that lets you bring an existing OpenLane
(1.x or 2.x) project into the OpenForge flow without rewriting your
`config.json`, then push the resulting build outputs back into OpenLane's
`runs/<tag>/` layout for downstream scripts.

## Importing an OpenLane project

```bash
openforge openlane import path/to/openlane-project/
```

This reads `config.json` (or `config.yaml`) at the given path and writes:

- `openforge.yaml` next to the OpenLane config -- ready to feed `openforge flow run`.
- `constraints/openlane.sdc` synthesised from `CLOCK_PORT` / `CLOCK_PERIOD`.

Use `--no-yaml` to preview the mapping without touching the project, or
`--no-sdc` to skip SDC generation if you already have constraints.

### Field mapping

| OpenLane key | OpenForge field |
| --- | --- |
| `DESIGN_NAME` | `project.top_module`, `project.name` |
| `VERILOG_FILES` (globs) | `design.sources` (expanded) |
| `VERILOG_INCLUDE_DIRS` | `design.includes`, `project.include_dirs` |
| `CLOCK_PORT` + `CLOCK_PERIOD` | synthesised SDC in `design.constraints` |
| `PDK` (sky130A, gf180mcuC, ...) | `project.target_pdk` |
| `DIE_AREA`, `FP_CORE_UTIL`, `PL_TARGET_DENSITY`, `FP_PDN_*PITCH`, `SYNTH_STRATEGY` | preserved under `openlane:` extra block |
| any other keys | preserved verbatim under `openlane.extra` |

## Exporting OpenForge results back to OpenLane

After running the OpenForge flow:

```bash
openforge openlane export build/ path/to/openlane-project/runs/openforge/
```

This populates the OpenLane run layout:

- `results/final/def/final.def`, `gds/final.gds`, `verilog/gl/final.v`,
  `sdf/final.sdf`, `spef/final.spef`, `sdc/final.sdc`
- `reports/synthesis/synthesis.stat.rpt` (from the yosys log)
- `reports/signoff/tritonRoute.drc` (synthesised from OpenForge's DRC JSON)
- `metrics.json` passthrough

Downstream OpenLane tooling (Caravel harness, MPW submission scripts, custom
post-processing) keeps working unchanged.

## Programmatic API

```python
from pathlib import Path
from openforge.integrations.openlane import (
    OpenLaneConfig,
    import_openlane,
    export_openlane_reports,
)

cfg = import_openlane(Path("path/to/openlane-project"))
print(cfg.project.top_module, cfg.design.sources)

export_openlane_reports(Path("build"), Path("runs/openforge"))
```
