# Sign-off Panel Group

The sign-off panels consolidate all pre-tapeout verification checks: design rule checking (DRC), layout vs. schematic (LVS), power integrity analysis, and a unified sign-off dashboard. These checks are mandatory before submitting a design for manufacturing.

## Signoff Dashboard

A unified status view showing pass/fail for every sign-off check.

### Features

- **Checklist view**: All sign-off items with status (Pass/Fail/Not Run)
- **One-click run**: Execute all checks sequentially
- **Progress tracking**: Stage completion with timestamps
- **Report export**: Generate a consolidated sign-off report

### Checklist Items

| Check | Tool | Description |
|---|---|---|
| DRC | Magic / KLayout | Manufacturing design rule compliance |
| LVS | Netgen | Layout matches schematic |
| STA | OpenSTA | All timing constraints met |
| ERC | Internal | Electrical rule check (PCB) |
| Power | OpenROAD | IR drop within limits |
| Antenna | Magic | Antenna rule violations |
| Density | Magic | Metal density within foundry limits |

### Usage

1. Complete the P&R flow (routed design required)
2. Open the Signoff Dashboard (**View > Signoff Dashboard**)
3. Click **Run All Checks** to execute the complete sign-off suite
4. Each check runs sequentially and updates its status
5. Click any failed check to open its detailed result panel
6. Fix issues and re-run until all checks pass

## DRC Browser

Design Rule Check results browser with layout cross-probing.

### Features

- **Violation list**: Table of all DRC violations with type, layer, and coordinates
- **Severity filtering**: Filter by error type (spacing, width, enclosure, etc.)
- **Layout highlight**: Click a violation to zoom to its location in the Layout panel
- **Waiver support**: Mark known-good violations as waived with justification

### Common DRC Rules (SKY130)

| Rule | Description | Minimum |
|---|---|---|
| Metal spacing | Minimum gap between same-layer metals | Varies by layer |
| Metal width | Minimum trace width | Varies by layer |
| Via enclosure | Minimum metal overlap around vias | Per via type |
| Poly spacing | Minimum polysilicon spacing | 0.21 um |
| Diffusion spacing | Minimum active area spacing | 0.27 um |

### Running DRC

=== "GUI"

    Flow Navigator: **Signoff > Run DRC** or the dedicated DRC button

=== "CLI"

    ```bash
    openforge drc
    ```

=== "TCL"

    ```tcl
    run_drc
    report_drc
    ```

## LVS Debugger

Layout vs. Schematic comparison with mismatch debugging.

### Features

- **Extraction**: Extracts a netlist from the physical layout
- **Comparison**: Compares extracted netlist against gate-level schematic
- **Mismatch browser**: Lists device and net mismatches
- **Cross-probing**: Highlight mismatched elements in both the schematic and layout
- **Detailed reports**: Shows exactly which devices or nets differ

### Mismatch Types

| Type | Description |
|---|---|
| Device mismatch | Extra or missing transistors/cells |
| Net mismatch | Different connectivity between layout and schematic |
| Parameter mismatch | Device dimensions differ (W, L) |
| Port mismatch | Top-level ports do not match |

### Running LVS

=== "GUI"

    Flow Navigator: **Signoff > Run LVS**

=== "CLI"

    ```bash
    openforge lvs
    ```

=== "TCL"

    ```tcl
    run_lvs
    report_lvs
    ```

## IR Drop Overlay

Visualizes voltage drop across the power distribution network.

### Features

- **Heatmap overlay**: Color-coded IR drop values on the layout
- **Threshold markers**: Highlight areas exceeding the acceptable voltage drop
- **Per-layer analysis**: View IR drop contribution per metal layer
- **Hot spot identification**: Automatic detection of worst-case drop locations

### Acceptable Limits

| Parameter | Typical Limit |
|---|---|
| VDD IR drop | < 5% of nominal (e.g., < 90 mV for 1.8V) |
| VSS IR drop | < 5% of nominal |

### Usage

1. Ensure the PDN (power distribution network) is synthesized
2. Open the IR Drop Overlay panel
3. Run analysis -- the overlay renders on top of the Layout panel
4. Red areas indicate excessive voltage drop
5. Fix by adding more power stripes or widening existing ones

## Power Sign-off

Comprehensive power analysis for the design.

### Features

- **Static power**: Leakage power estimation from Liberty files
- **Dynamic power**: Switching power from VCD activity data
- **Total power**: Combined static + dynamic power report
- **Per-module breakdown**: Power contribution by module hierarchy
- **Corner analysis**: Power at different PVT corners

### Configuration

```yaml
analysis:
  power:
    tool: openroad
    activity_file: sim_build/dump.vcd
    corner: typical
```

### TCL Commands

```tcl
report_power
```

## Common Workflows

### Pre-Tapeout Checklist

1. Run DRC and fix all violations
2. Run LVS and fix all mismatches
3. Run STA and ensure all timing constraints are met
4. Run IR drop analysis and verify power integrity
5. Check metal density meets foundry requirements
6. Generate the consolidated sign-off report
7. Export GDSII for submission

### Iterating on DRC Fixes

1. Note the DRC violation type and location
2. Modify the P&R constraints or re-run routing with adjusted parameters
3. Re-run DRC to verify the fix
4. Repeat until DRC-clean

!!! warning "Do not waive DRC violations without justification"
    Foundries reject designs with unexplained DRC violations. Only waive violations that are intentional (e.g., antenna violations with built-in diode protection) and document the reason.
