# Synthesis Panel

The Synthesis panel provides Vivado-quality reporting of synthesis results including resource utilization, cell hierarchy, schematic viewing, and message browsing. It populates automatically after running synthesis via the Flow Navigator or TCL console.

## Description

The panel is organized into tabbed sub-views:

- **Resource Utilization** -- Summary of gate count, cell usage, and area estimates
- **Hierarchy** -- Module hierarchy tree with per-module resource breakdown
- **Cell Usage** -- Detailed table of every standard cell type used and its count
- **Schematic** -- Interactive gate-level schematic viewer
- **Messages** -- Yosys warnings, info, and error messages

## Key Features

### Resource Utilization

The utilization tab shows:

| Metric | Description |
|---|---|
| Total gate count | Number of logic cells after technology mapping |
| Area (um^2) | Estimated silicon area based on PDK cell sizes |
| Timing estimate | Initial timing estimate from synthesis |
| Cell usage | Pie chart / bar chart of cell type distribution |

For FPGA targets, utilization shows LUT, FF, BRAM, DSP, and I/O usage as a fraction of device capacity.

### Hierarchy Browser

The hierarchy tree mirrors the RTL module structure with synthesis statistics at each level:

- Click a module to see its specific cell count and area contribution
- Expand instances to see sub-module resource usage
- Right-click to cross-probe to the source code or schematic

### Schematic Viewer

The interactive schematic renders the gate-level netlist as a circuit diagram:

- Standard cell symbols (AND, OR, XOR, MUX, DFF) with proper IEEE shapes
- Net connections with routing
- Zoom and pan with mouse wheel and drag
- Click any cell to see its properties in the Properties panel
- Right-click for cross-probing to RTL source

### Message Browser

All Yosys output messages categorized by severity:

| Severity | Color | Description |
|---|---|---|
| Error | Red | Synthesis failed -- must fix |
| Warning | Yellow | Potential issues (inferred latches, width mismatches) |
| Info | Blue | Informational (optimization stats, mapping details) |

## How to Use

1. Configure your project's `openforge.yaml` with source files and target PDK
2. Run synthesis via:
    - Flow Navigator: click **Synthesis > Run Synthesis**
    - TCL console: `synth_design -top <module>`
    - CLI: `openforge synth`
3. The panel populates automatically when synthesis completes
4. Review utilization to ensure the design fits your target
5. Check messages for warnings about inferred latches, combinational loops, or width mismatches

## Configuration Options

Synthesis behavior is controlled by the project config and TCL commands:

```yaml
project:
  top_module: "counter"
  target_pdk: "sky130"    # sky130, gf180mcu, or FPGA family
```

TCL commands for synthesis control:

```tcl
synth_design -top counter               # Run synthesis
synth_design -top counter -part sky130   # Specify target
opt_design                               # Post-synthesis optimization
report_utilization                       # Print utilization summary
report_area                              # Print area breakdown
report_timing -max_paths 10             # Print timing summary
```

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+S` | Run synthesis |
| `Ctrl+R` | Refresh results |
| `Ctrl+F` | Search in messages |
| `+` / `-` | Zoom schematic |
| `F` | Fit schematic to view |

## Common Workflows

### Iterating on Synthesis

1. Edit RTL in the code editor
2. Press `Ctrl+Shift+S` to re-run synthesis
3. Check utilization changes in the Resource tab
4. Review new warnings in the Messages tab

### Comparing Synthesis Strategies

1. Run synthesis with default settings
2. Note gate count and area
3. Change optimization settings (e.g., area vs. speed)
4. Re-run and compare results

### Cross-Probing

Right-click any cell in the schematic or hierarchy to:

- **Go to Source** -- jump to the RTL line that generated this cell
- **Go to Layout** -- highlight this cell in the Layout viewer (post-P&R)
- **Show Properties** -- display cell attributes in the Properties panel
