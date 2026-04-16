# Tutorial: ASIC Flow -- SKY130 Counter RTL to GDSII

This tutorial takes an 8-bit counter from RTL through synthesis, place-and-route, DRC, LVS, and GDSII export using the SkyWater 130nm open PDK. This is the same flow used to tape out real silicon on open shuttle programs like Google/Efabless MPW and ChipIgnite.

## Prerequisites

- OpenForge installed ([Installation guide](../getting-started/installation.md))
- SkyWater 130nm PDK installed: `openforge pdk install sky130`
- Tools: Yosys, OpenROAD, Magic, Netgen, KLayout
- On Windows, these tools run via WSL2 -- OpenForge handles path translation automatically

## Step 1: Create the Project

=== "GUI"

    1. **File > New Project**
    2. Name: `counter-asic`
    3. PDK: `sky130`
    4. Top module: `counter`
    5. Click **Create**

=== "CLI"

    ```bash
    openforge init counter-asic --pdk sky130 --top counter
    cd counter-asic
    ```

## Step 2: RTL Design

Create `src/counter.v`:

```verilog
`timescale 1ns / 1ps

module counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             enable,
    output reg  [WIDTH-1:0] count,
    output wire             overflow
);

    assign overflow = (count == {WIDTH{1'b1}}) & enable;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= {WIDTH{1'b0}};
        else if (enable)
            count <= count + 1'b1;
    end

endmodule
```

## Step 3: Timing Constraints

Create `constraints/timing.sdc`:

```tcl
# 100 MHz target clock
create_clock -name clk -period 10.0 [get_ports clk]

# I/O delays
set_input_delay  -clock clk 2.0 [get_ports {rst_n enable}]
set_output_delay -clock clk 2.0 [get_ports {count[*] overflow}]
```

## Step 4: Project Configuration

Update `openforge.yaml`:

```yaml
project:
  name: "counter-asic"
  top_module: "counter"
  target_pdk: "sky130"

design:
  sources:
    - src/counter.v
  constraints:
    - constraints/timing.sdc

verification:
  simulation:
    tool: icarus
    testbenches:
      - tb/counter_tb.v
    coverage:
      line: true
      toggle: true

analysis:
  timing:
    tool: opensta
    clock_period: 10.0
```

## Step 5: Synthesis

Synthesis maps your RTL to the sky130_fd_sc_hd standard cell library using Yosys.

=== "GUI"

    1. In the **Flow Navigator**, click **Synthesis > Run Synthesis**
    2. Yosys reads your Verilog, elaborates the design, and maps to sky130 cells
    3. The **Synthesis** panel shows results:
        - **Cell Usage**: `sky130_fd_sc_hd__dfxtp_1` (DFFs), `sky130_fd_sc_hd__fa_1` (full adders), `sky130_fd_sc_hd__inv_1` (inverters), etc.
        - **Area**: approximately 300-400 um^2 for an 8-bit counter
        - **Timing estimate**: initial timing from Yosys
    4. The **Schematic** tab shows the gate-level netlist graphically

    <!-- Screenshot: Synthesis panel with sky130 cell usage table -->

=== "CLI"

    ```bash
    openforge synth
    ```

    ```
    [INFO] Loading sky130_fd_sc_hd liberty: tt_025C_1v80
    [INFO] Running Yosys synthesis...
    [INFO] Synthesis complete in 1.4s
    [INFO]   Cell count: 42
    [INFO]   Area: 327.6 um^2
    [INFO]   Netlist: synth_build/counter.v
    ```

=== "TCL Console"

    ```tcl
    synth_design -top counter
    report_utilization
    report_area
    ```

The synthesis step produces:

- `synth_build/counter.v` -- Gate-level Verilog netlist using sky130 cells
- `synth_build/counter.json` -- Yosys JSON netlist for downstream tools

!!! note "Multi-corner synthesis"
    OpenForge supports multi-corner synthesis for sky130. The default corner is `tt` (typical-typical at 25C, 1.8V). You can also target `ss` (slow-slow, worst case) or `ff` (fast-fast, best case) by setting `corner: ss` in the config.

## Step 6: Floorplanning

Before placement, define the chip floorplan.

=== "GUI"

    1. Click **Physical Design > Init Floorplan** in the Flow Navigator
    2. The **Floorplan Editor** opens with a configurable die/core area
    3. Set die area and core utilization (e.g., 65% target density)
    4. Review the power distribution network (VDD/VSS rings and stripes)

=== "TCL Console"

    ```tcl
    init_floorplan -die_area {0 0 100 100} -core_area {10 10 90 90}
    ```

## Step 7: Place and Route

OpenROAD performs the full physical design flow: global placement, detailed placement, clock tree synthesis, global routing, and detailed routing.

=== "GUI"

    1. Click **Physical Design > Run P&R** in the Flow Navigator
    2. The console streams OpenROAD output as it progresses through each stage
    3. The progress bar shows: Floorplan -> Placement -> CTS -> Routing -> Signoff
    4. When complete, the **Layout** panel renders the placed and routed design
    5. You can toggle layer visibility, zoom into cells, and click cells for properties

    <!-- Screenshot: Layout viewer showing routed counter on sky130, with metal layers visible -->

=== "CLI"

    ```bash
    openforge pnr
    ```

    ```
    [INFO] Running OpenROAD P&R flow...
    [INFO] Stage: Global Placement (density 0.65)
    [INFO] Stage: Detailed Placement
    [INFO] Stage: Clock Tree Synthesis
    [INFO] Stage: Global Routing
    [INFO] Stage: Detailed Routing
    [INFO] P&R complete in 12.3s
    [INFO] DEF: pnr_build/counter_routed.def
    ```

=== "TCL Console"

    ```tcl
    place_design
    clock_tree_synthesis
    route_design
    write_def pnr_build/counter_routed.def
    ```

## Step 8: Static Timing Analysis

=== "GUI"

    1. Click **Analysis > Run STA** in the Flow Navigator
    2. The **Timing** panel populates with:
        - **Slack histogram**: bar chart showing slack distribution across all paths
        - **Critical paths**: sorted list of worst-case timing paths
        - **Path detail**: click any path to see the cell-by-cell delay breakdown
        - **SDC summary**: shows applied timing constraints

    Color coding: green = timing met, yellow = near-critical (< 10% margin), red = violated

=== "CLI"

    ```bash
    openforge sta
    ```

    ```
    [INFO] Running OpenSTA...
    [INFO] Worst negative slack (WNS): 2.34 ns
    [INFO] Total negative slack (TNS): 0.00 ns
    [INFO] All timing constraints met
    ```

## Step 9: Sign-off Checks

### Design Rule Check (DRC)

DRC verifies the layout meets the foundry's manufacturing rules.

=== "GUI"

    Click **Signoff > Run DRC**. Magic checks spacing, width, enclosure, and other rules. Results appear in the **DRC Browser** panel with clickable violations that highlight in the layout viewer.

=== "CLI"

    ```bash
    openforge drc
    ```

### Layout vs. Schematic (LVS)

LVS confirms the layout matches the intended circuit.

=== "GUI"

    Click **Signoff > Run LVS**. Netgen extracts the layout netlist and compares it to the synthesized gate-level netlist. A "clean" LVS means zero mismatches.

=== "CLI"

    ```bash
    openforge lvs
    ```

    ```
    [INFO] Running Netgen LVS...
    [INFO] Extracting layout netlist from DEF...
    [INFO] Comparing with gate-level netlist...
    [INFO] LVS clean: 0 mismatches
    ```

!!! warning "DRC/LVS must pass before tapeout"
    Foundries require a clean DRC and LVS report before accepting a design for manufacturing. Always fix all violations before generating the final GDSII.

## Step 10: GDSII Export

=== "GUI"

    Click **Physical Design > Write GDSII** or use the Flow Navigator's **Export GDS** step. The GDS viewer panel opens automatically showing the final layout.

=== "CLI"

    ```bash
    openforge gds
    ```

=== "TCL Console"

    ```tcl
    write_gds pnr_build/counter.gds
    ```

The final `counter.gds` file is ready for tapeout submission.

## Output File Summary

| File | Description |
|---|---|
| `synth_build/counter.v` | Gate-level netlist (Verilog) |
| `synth_build/counter.json` | Yosys JSON netlist |
| `pnr_build/counter_placed.def` | Placed DEF |
| `pnr_build/counter_routed.def` | Routed DEF |
| `pnr_build/counter.gds` | Final GDSII layout |
| `reports/drc_report.rpt` | DRC results |
| `reports/lvs_report.rpt` | LVS results |
| `reports/timing_report.rpt` | STA timing summary |

## Troubleshooting

**Synthesis error: "Cannot find liberty file"**
:   The sky130 PDK is not installed or not found. Run `openforge pdk install sky130` and verify the PDK path in **Tools > PDK Manager**.

**OpenROAD crashes with "no LEF/DEF"**
:   Ensure the PDK's tech LEF and cell LEF files are accessible. Check that `target_pdk: sky130` is set in `openforge.yaml`.

**DRC violations in metal spacing**
:   Common with aggressive utilization targets. Reduce the core density (e.g., from 0.75 to 0.60) and re-run P&R to give the router more space.

**LVS mismatches**
:   Usually caused by missing connections or extra parasitic devices. Check the LVS report for the specific mismatch type (net mismatch, device mismatch, or parameter mismatch).

## Next Steps

- Submit your GDSII to the [Efabless ChipIgnite](https://efabless.com/chipignite) shuttle for real silicon fabrication
- Add the [crypto verification suite](verification.md) for security-critical designs
- Try the [GF180MCU PDK](../getting-started/installation.md#pdk-installation) for a different process node
- Explore [multi-corner timing analysis](../panels/timing.md) for production sign-off
