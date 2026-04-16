# Verification Panel Group

The verification panels manage testbench execution, waveform viewing, code coverage, formal proofs, and regression testing. Together they provide a complete verification environment comparable to commercial tools.

## Testbench Panel

The Testbench panel discovers, manages, and runs simulation testbenches.

### Features

- **Automatic discovery**: Finds testbench files from `openforge.yaml` configuration
- **Multi-simulator support**: Icarus Verilog, Verilator, GHDL
- **Cocotb integration**: Runs Python-based testbenches via cocotb
- **Test tree**: Hierarchical view of all tests with pass/fail status icons
- **Real-time output**: Console output streams as simulation runs
- **Parallel execution**: Run multiple tests simultaneously

### Test Status Indicators

| Icon | Color | Status |
|---|---|---|
| Empty circle | Gray | Not run |
| Quarter circle | Yellow | Running |
| Filled circle | Green | Passed |
| Filled circle | Red | Failed |
| X mark | Red | Error (compile failure) |
| Empty circle | Gray | Skipped |

### Usage

1. Open the Testbench panel (**View > Testbench**)
2. Tests appear automatically from your project config
3. Select individual tests or click **Run All**
4. Results update in real time
5. Double-click a failed test to view its output
6. The waveform viewer opens automatically after simulation

### Configuration

```yaml
verification:
  simulation:
    tool: icarus          # icarus, verilator, or ghdl
    testbenches:
      - tb/counter_tb.v
      - tb/counter_tb.py  # Cocotb testbench
    coverage:
      line: true
      toggle: true
    timeout_seconds: 300
    plusargs:
      SEED: "12345"
```

## Waveform Panel

A Vivado-quality waveform viewer for VCD and FST files with dual cursors, markers, analog traces, and bus rendering.

### Features

- **Three-pane layout**: Signal tree, value column, waveform canvas
- **Dual cursors**: Place two cursors to measure time differences
- **Markers**: Named bookmarks at specific times
- **Minimap**: Overview of the entire simulation timeline
- **Bus rendering**: Diamond transitions with hex value annotations
- **Analog traces**: Continuous waveform rendering for analog signals
- **X/Z rendering**: Hatch patterns for unknown and high-impedance values

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `+` / `-` | Zoom in / out |
| `F` | Zoom to fit |
| `Left` / `Right` | Move cursor |
| `Shift+Left/Right` | Move cursor 2 |
| `Ctrl+G` | Go to time |
| `M` | Place marker at cursor |
| `Delete` | Remove selected signal |
| `Ctrl+A` | Add signal dialog |

### Loading Waveforms

=== "GUI"

    - Automatic: Opens after simulation
    - Manual: **File > Open Waveform** or the **Load** button in the waveform toolbar
    - TCL: `open_waveform path/to/dump.vcd`

=== "CLI"

    ```bash
    openforge wave sim_build/dump.vcd
    ```

## Coverage Dashboard

Displays code coverage metrics collected during simulation.

### Metrics

| Type | Description |
|---|---|
| Line coverage | Percentage of HDL source lines executed |
| Toggle coverage | Percentage of signals that toggled both 0->1 and 1->0 |
| Branch coverage | Percentage of if/else and case branches taken |
| FSM coverage | Percentage of FSM states and transitions visited |

### Features

- Per-module coverage breakdown
- Source code annotation showing uncovered lines
- Coverage merging across multiple simulation runs
- Trend tracking over regression history

## Formal Panel

Manages formal property verification using SymbiYosys.

### Features

- Property file management (SVA, PSL)
- Engine selection: smtbmc, btor, aiger, abc
- Configurable proof depth
- Results display: PROVEN / FAILED / UNKNOWN per property
- Counterexample trace viewer for failed properties
- Cross-probing from counterexample to RTL source

### Usage

1. Add SVA property files to your project
2. Open the Formal panel
3. Set the proof depth (20 cycles is a good default)
4. Click **Run Formal**
5. Green checkmarks indicate proven properties
6. Red X marks indicate counterexamples -- click to view the failing trace

## Regression Runner

Manages batch test execution for large verification suites.

### Features

- Run all tests with a single click
- Parallel execution across multiple cores
- Pass/fail summary with failure triage
- Re-run failed tests only
- History tracking with trend graphs
- Export results as JUnit XML for CI integration

## Equivalence Panel

Verifies that the pre-synthesis RTL and post-synthesis gate-level netlist are functionally equivalent.

### Usage

1. Run synthesis to produce a gate-level netlist
2. Open the Equivalence panel
3. Click **Run Equivalence Check**
4. Results show: EQUIVALENT or list of mismatched outputs

This catches synthesis bugs or misconfigured optimization passes that could alter design behavior.
