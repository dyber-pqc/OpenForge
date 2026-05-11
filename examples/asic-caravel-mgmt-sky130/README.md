# asic-caravel-mgmt-sky130

The **full Caravel management SoC** (`mgmt_core`) on SkyWater sky130. This is
the actual digital management harness from
[efabless/caravel_mgmt_soc_litex](https://github.com/efabless/caravel_mgmt_soc_litex)
— wraps a VexRiscv RISC-V core, two DFFRAM banks (RAM128 + RAM256), Wishbone
intercon, GPIO/SPI/UART, housekeeping, flash controller, etc.

## Why `mgmt_core` and not `caravel`?

The top-level `caravel.v` wraps the digital `mgmt_core` plus pad ring,
analog IP (LDO, bandgap, POR), and SerDes — none of which can be
synthesised from RTL. `mgmt_core` is the digital heart of the SoC and the
honest target for an open-source RTL→GDS flow.

To switch tops to `mgmt_core_wrapper` (adds a few buffer/protect levels),
edit `openforge.yaml`:

```yaml
top_module: mgmt_core_wrapper
rtl_sources:
  - rtl/mgmt_core_wrapper.v
  # plus everything mgmt_core needs
```

## Files

| File                                    | Purpose                                          |
|-----------------------------------------|--------------------------------------------------|
| `openforge.yaml`                        | Full ASIC flow                                   |
| `rtl/mgmt_core.v`                       | Top — Caravel mgmt SoC core                      |
| `rtl/mgmt_core_wrapper.v`               | Optional outer wrapper                           |
| `rtl/VexRiscv_MinDebugCache.v`          | RISC-V core with cache + min debug               |
| `rtl/RAM128.v` / `rtl/RAM256.v`         | Original DFFRAM netlists (NOT used directly)     |
| `rtl/RAM_blackbox.v`                    | Blackbox stubs for the DFFRAM macros             |
| `rtl/picorv32.v`                        | Reference; not wired into mgmt_core              |
| `rtl/defines.v`                         | Caravel `defines.v`                              |
| `lef/RAM128.lef`, `lef/RAM256.lef`      | DFFRAM hard-macro LEF (for floorplan import)     |
| `gds/RAM128.gds.gz`, `gds/RAM256.gds.gz`| DFFRAM hard-macro GDS (for sign-off)             |
| `constraints/mgmt_core.sdc`             | 50 MHz `core_clk` + I/O delays                   |

## DFFRAM macros — important

`RAM128.v` / `RAM256.v` from upstream are **pre-mapped sky130 std-cell
netlists** that instantiate raw `sky130_fd_sc_hd__*` cells (incl. taps,
clock buffers, ebufns). In a real Caravel sign-off these are hard macros
delivered as LEF + GDS, not synthesised. We model them as `(* blackbox *)`
in `rtl/RAM_blackbox.v` so synthesis of the surrounding logic completes
cleanly.

The actual macro LEF/GDS are vendored under `lef/` and `gds/` for the
floorplan and sign-off stages — but wiring extra LEFs into OpenForge's
auto-generated `floorplan.tcl` is currently a manual edit (see Status
below).

## Running

```bash
# from repo root
python -c "
from pathlib import Path
import sys; sys.path.insert(0, 'packages/core/src')
from openforge.flow.full_flow import FullFlowRunner, FullFlowConfig
cfg = FullFlowConfig(
    top_module='mgmt_core',
    rtl_files=[
        'rtl/defines.v',
        'rtl/VexRiscv_MinDebugCache.v',
        'rtl/RAM_blackbox.v',
        'rtl/mgmt_core.v',
    ],
    sdc_file='constraints/mgmt_core.sdc',
    pdk='sky130A', target_freq_mhz=50.0,
    floorplan_utilization=0.25,
    floorplan_die_area=[0,0,1500,1500],
    floorplan_core_area=[40,40,1460,1460],
    floorplan_site='unithd',
    placement_target_density=0.35,
    routing_droute_end_iter=6,
    skip_drc=True, skip_lvs=True,
    output_dir='build',
)
FullFlowRunner(cfg, work_dir=Path('examples/asic-caravel-mgmt-sky130')).run()
"
```

## Status

- **Synthesis**: WORKS. ~23,064 mapped sky130_fd_sc_hd cells (mgmt_core
  surrounding logic + VexRiscv core; DFFRAM banks blackboxed). Took ~12 s.
- **Floorplan**: BLOCKED. OpenROAD reports
  `[ERROR ORD-2013] instance RAM128 LEF master RAM128 not found.`
  The auto-generated `floorplan.tcl` only loads the std-cell tech LEF;
  it doesn't yet plumb extra macro LEFs. The `lef/RAM128.lef` and
  `lef/RAM256.lef` files needed are vendored — they just need to be
  added to the script via two more `read_lef` lines plus `place_macro`
  calls.
- **CTS / Routing / Sign-off**: not reached — gated on floorplan.

To unblock, OpenForge's floorplan stage needs a `macro_lefs:` yaml key
that flows into the generated TCL. That's a flow-engine change tracked
separately, not an example-deck issue.

## Tuning notes

- 1500 × 1500 µm die at 0.25 utilization is conservative. Once routing is
  unblocked, a tighter die (~1100 × 1100 µm at 0.35 util) is realistic.
- 50 MHz clock is realistic for mgmt_core on sky130 sc_hd; the upstream
  Caravel sign-off uses similar.

## License

Caravel and its components are Apache-2.0 (see file headers). DFFRAM
macros are also Apache-2.0 from the efabless/caravel_mgmt_soc_litex repo.
