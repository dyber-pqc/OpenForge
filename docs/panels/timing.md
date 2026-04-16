# Timing Analysis Panel

The Timing Analysis panel provides Vivado-quality static timing analysis (STA) visualization with slack histograms, critical path browsing, path detail views, and SDC constraint summaries. It uses OpenSTA as the backend timing engine.

## Description

Static timing analysis verifies that all signals arrive at their destinations within the required time window. The panel displays timing results across four tabs:

- **Slack Histogram** -- Distribution of path slack values across the design
- **Critical Paths** -- Ranked list of worst-case timing paths
- **Path Detail** -- Cell-by-cell delay breakdown for a selected path
- **SDC Summary** -- Applied timing constraints

## Key Features

### Slack Histogram

A bar chart showing the distribution of setup slack across all timing paths:

| Color | Meaning |
|---|---|
| Green (`#a6e3a1`) | Timing met -- positive slack |
| Yellow (`#f9e2af`) | Near-critical -- slack within 10% of the clock period |
| Red (`#f38ba8`) | Timing violated -- negative slack |

The histogram axes:

- **X-axis**: Slack value in nanoseconds
- **Y-axis**: Number of paths in each slack bin

### Critical Path Browser

A sortable table of timing paths ranked by slack:

| Column | Description |
|---|---|
| Slack | Path slack in ns (negative = violated) |
| Startpoint | Launch flip-flop or input port |
| Endpoint | Capture flip-flop or output port |
| Path group | Clock domain grouping |
| Levels | Number of logic levels in the path |
| Data delay | Combinational data path delay |
| Clock skew | Clock arrival time difference between launch and capture |

Click any path to view its detailed cell-by-cell breakdown in the Path Detail tab.

### Path Detail View

For a selected timing path, shows every cell in the path with:

| Column | Description |
|---|---|
| Cell | Standard cell instance name |
| Cell type | Library cell (e.g., `sky130_fd_sc_hd__and2_1`) |
| Delay (ns) | Cell propagation delay |
| Arrival (ns) | Cumulative signal arrival time |
| Transition (ns) | Input slew / output transition time |
| Fanout | Number of loads on the output net |
| Capacitance (fF) | Output net capacitance |

The path is also highlighted in the Layout panel via cross-probing.

### SDC Summary

Displays all timing constraints applied to the design:

| Constraint | Details |
|---|---|
| Clocks | Name, period, waveform |
| Input delays | Port, clock, delay value |
| Output delays | Port, clock, delay value |
| False paths | Source, through, destination |
| Multicycle paths | Multiplier, source, destination |

## How to Use

1. Run synthesis and P&R (timing requires a placed/routed design for accurate results)
2. Run STA via:
    - Flow Navigator: **Analysis > Run STA**
    - TCL: `report_timing -max_paths 100`
    - CLI: `openforge sta`
3. Review the slack histogram for an overall picture
4. Sort critical paths by slack to find the worst violations
5. Click the worst path to see the cell-by-cell delay breakdown
6. Use the information to guide RTL changes or physical design adjustments

## Configuration

Timing analysis settings in `openforge.yaml`:

```yaml
analysis:
  timing:
    tool: opensta
    clock_period: 10.0      # Target clock period in ns
    sdc_files:
      - constraints/timing.sdc
```

TCL commands:

```tcl
report_timing -max_paths 50        # Show top 50 worst paths
report_timing -from clk -to out    # Filter paths by endpoint
report_clocks                       # List all clock definitions
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay -clock clk 2.0 [get_ports data_in]
set_output_delay -clock clk 2.0 [get_ports data_out]
```

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+T` | Open timing panel |
| `Enter` | View selected path detail |
| `Ctrl+F` | Search paths |
| `Ctrl+G` | Go to path by index |
| `N` / `P` | Next / previous path |

## Common Workflows

### Fixing Timing Violations

When paths have negative slack:

1. Identify the critical path in the path browser
2. Look at the path detail for the largest cell delay contributors
3. Common fixes:
    - **Long combinational chains**: Add pipeline registers to break the path
    - **High fanout**: Add buffers to reduce load on critical nets
    - **Clock skew**: Adjust CTS parameters or add clock buffers
    - **Slow cells**: Use higher-drive-strength cells (e.g., `_2` instead of `_1`)

### Multi-Corner Analysis

For production sign-off, analyze timing at multiple PVT corners:

| Corner | Process | Voltage | Temperature | Use |
|---|---|---|---|---|
| tt | Typical | 1.80V | 25C | Nominal design |
| ss | Slow | 1.60V | 100C | Worst-case setup |
| ff | Fast | 1.95V | -40C | Worst-case hold |

OpenForge loads the appropriate Liberty files for each corner automatically based on the PDK configuration.

### Cross-Probing

Right-click any cell in the path detail to:

- **Show in Layout** -- highlight the cell in the physical layout
- **Show in Schematic** -- locate the cell in the gate-level schematic
- **Show in Source** -- jump to the RTL line that generated this logic
