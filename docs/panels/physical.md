# Physical Design Panel

The Physical Design panel controls the place-and-route (P&R) flow using OpenROAD and provides real-time feedback on floorplan configuration, placement density, routing congestion, and design statistics.

## Description

Physical design transforms a gate-level netlist into a placed and routed layout ready for manufacturing. The panel manages the five stages of the P&R flow:

1. **Floorplan** -- Die/core area definition, power ring generation, I/O placement
2. **Placement** -- Global and detailed placement of standard cells
3. **CTS** -- Clock tree synthesis for balanced clock distribution
4. **Routing** -- Global and detailed routing of signal and power nets
5. **Signoff** -- DRC, LVS, and final checks before GDSII export

## Key Features

### Flow Control

A stage progress bar at the top shows the current P&R stage with color-coded status:

| Stage | Status Colors |
|---|---|
| Not started | Gray |
| In progress | Blue (animated) |
| Completed | Green |
| Error | Red |

Run individual stages or the full flow:

- **Run All**: Execute the complete P&R pipeline
- **Run Stage**: Execute a single stage (e.g., placement only)
- **Cancel**: Stop the current operation

### Floorplan Configuration

| Parameter | Description | Default |
|---|---|---|
| Die area | Overall chip dimensions (um x um) | Auto-sized |
| Core area | Placeable region within the die | 80% of die |
| Core utilization | Target cell density (0.0 - 1.0) | 0.65 |
| Aspect ratio | Width-to-height ratio | 1.0 |
| Site | Placement site from PDK | Auto-detected |

### Placement Statistics

After placement completes:

| Metric | Description |
|---|---|
| Cell count | Total placed standard cells |
| Utilization | Actual density (cells / core area) |
| HPWL | Half-perimeter wire length (routing estimate) |
| Displacement | Average cell displacement from optimal position |

### Routing Statistics

After routing completes:

| Metric | Description |
|---|---|
| Total wirelength | Sum of all routed wire segments |
| Via count | Number of inter-layer vias |
| DRC violations | Routing DRC violations (should be 0) |
| Congestion | Routing congestion map overlay |

## How to Use

### Full ASIC Flow

1. Ensure synthesis is complete (gate-level netlist exists)
2. Configure floorplan parameters (or accept defaults)
3. Click **Run All** to execute the complete P&R flow
4. Monitor progress in the stage bar and console output
5. Review results in the statistics tables
6. Open the **Layout** panel to visualize the placed/routed design

### Individual Stages

For finer control, run stages individually:

=== "GUI"

    Use the stage buttons or Flow Navigator:

    1. **Init Floorplan** -- define die/core area
    2. **Run Placement** -- place cells
    3. **Run CTS** -- synthesize clock trees
    4. **Run Routing** -- route all nets
    5. **Write DEF** -- export the layout
    6. **Write GDS** -- generate GDSII

=== "TCL Console"

    ```tcl
    init_floorplan -die_area {0 0 200 200} -core_area {20 20 180 180}
    global_placement -density 0.65
    detailed_placement
    clock_tree_synthesis
    global_route
    detailed_route
    write_def pnr_build/counter_routed.def
    write_gds pnr_build/counter.gds
    ```

## Configuration Options

Physical design settings in `openforge.yaml`:

```yaml
project:
  target_pdk: "sky130"

# Floorplan settings (optional -- defaults are auto-calculated)
physical:
  core_utilization: 0.65
  aspect_ratio: 1.0
  clock_period: 10.0
```

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+P` | Run full P&R flow |
| `Ctrl+Shift+F` | Init floorplan |
| `Escape` | Cancel current operation |

## Common Workflows

### Adjusting Density for Timing Closure

If timing is not met after routing:

1. Reduce core utilization (e.g., 0.65 -> 0.55) to give the router more room
2. Re-run P&R
3. Check timing in the [Timing panel](timing.md)
4. Iterate until timing is met

### Exporting for External Tools

```tcl
write_def pnr_build/output.def    # For OpenROAD/third-party viewers
write_gds pnr_build/output.gds    # For KLayout, Magic
```

### Viewing the Layout

After P&R, the **Layout** panel renders the design:

- Metal layers with per-layer coloring (li1=purple, met1=blue, met2=green, met3=yellow, met4=orange, met5=red)
- Cell outlines with instance names
- Click any cell for properties
- Toggle layer visibility in the layer controls
- Zoom with scroll wheel, pan with click-drag
