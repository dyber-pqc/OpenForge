# First Project

This guide walks you through creating an OpenForge project, adding RTL source files, running synthesis, simulating, and viewing results. By the end, you will have a working 8-bit counter design that has been synthesized for the SkyWater 130nm PDK and simulated with a passing testbench.

## Step 1: Create a New Project

=== "GUI"

    1. Launch OpenForge: `openforge` or `uv run openforge`
    2. Click **File > New Project** or press `Ctrl+N`
    3. In the New Project dialog:
        - **Project name**: `my-counter`
        - **Location**: Choose a directory on your machine
        - **Target PDK**: Select `sky130` (SkyWater 130nm)
        - **Top module**: `counter`
    4. Click **Create**

    OpenForge creates a project directory with this structure:

    <!-- Screenshot: New Project dialog with fields filled in -->

=== "CLI"

    ```bash
    openforge init my-counter --pdk sky130 --top counter
    cd my-counter
    ```

The generated project directory looks like this:

```
my-counter/
  openforge.yaml       # Project configuration
  src/                  # RTL source files
  tb/                   # Testbench files
  constraints/          # SDC timing constraints
  synth_build/          # Synthesis output (generated)
  sim_build/            # Simulation output (generated)
```

## Step 2: Add RTL Source

Create a Verilog counter module. OpenForge pre-populates a template, or you can write your own.

=== "GUI"

    1. In the **File Explorer** panel (left side), right-click `src/` and select **New File**
    2. Name it `counter.v`
    3. The built-in code editor opens with Verilog syntax highlighting

=== "CLI"

    Create `src/counter.v` with your editor of choice.

Write the following RTL:

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
        if (!rst_n) begin
            count <= {WIDTH{1'b0}};
        end else if (enable) begin
            count <= count + 1'b1;
        end
    end

endmodule
```

## Step 3: Set Timing Constraints

Create an SDC file to define the clock:

Create `constraints/timing.sdc`:

```tcl
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay -clock clk 2.0 [get_ports {rst_n enable}]
set_output_delay -clock clk 2.0 [get_ports {count overflow}]
```

This defines a 100 MHz clock (10 ns period) with 2 ns input/output delay margins.

## Step 4: Configure the Project

The `openforge.yaml` file ties everything together. OpenForge generated a starter config; update it to match your source files:

```yaml
project:
  name: "my-counter"
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
```

!!! tip "Configuration reference"
    See the [Project Structure guide](../guide/project-structure.md) for a complete reference of all `openforge.yaml` options.

## Step 5: Run Synthesis

=== "GUI"

    1. In the **Flow Navigator** panel (left side), click **Synthesis > Run Synthesis**
    2. The console shows Yosys output in real time
    3. When complete, the **Synthesis** panel populates with:
        - Gate count and cell usage breakdown
        - Area estimate in square micrometers
        - Timing estimate
        - Schematic viewer showing the gate-level netlist
        - Message browser with warnings

    <!-- Screenshot: Synthesis panel after successful run, showing cell usage table and schematic -->

=== "CLI"

    ```bash
    openforge synth
    ```

    Output:

    ```
    [INFO] Loading project: my-counter
    [INFO] Target PDK: sky130 (sky130_fd_sc_hd)
    [INFO] Running Yosys synthesis...
    [INFO] Synthesis complete in 1.2s
    [INFO]   Gate count: 42
    [INFO]   Area: 312.5 um^2
    [INFO]   Netlist: synth_build/counter.json
    ```

=== "TCL Console"

    In the OpenForge console panel at the bottom of the window:

    ```tcl
    synth_design -top counter
    report_utilization
    report_timing
    ```

The synthesized netlist is saved to `synth_build/counter.json` (Yosys JSON format) and `synth_build/counter.v` (gate-level Verilog).

## Step 6: Write a Testbench

Create `tb/counter_tb.v`:

```verilog
`timescale 1ns / 1ps

module counter_tb;
    reg clk = 0;
    reg rst_n = 0;
    reg enable = 0;
    wire [7:0] count;
    wire overflow;

    // 100 MHz clock
    always #5 clk = ~clk;

    counter dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .count(count),
        .overflow(overflow)
    );

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, counter_tb);
    end

    initial begin
        // Reset
        rst_n = 0; enable = 0;
        repeat (3) @(posedge clk);
        @(posedge clk) rst_n = 1;

        // Count 10 cycles
        @(negedge clk) enable = 1;
        repeat (10) @(posedge clk);
        @(negedge clk);
        if (count !== 10) $display("FAIL: expected 10, got %0d", count);
        else $display("PASS: count = %0d", count);

        // Disable
        enable = 0;
        repeat (5) @(posedge clk);
        @(negedge clk);
        if (count !== 11) $display("FAIL: expected hold at 11, got %0d", count);
        else $display("PASS: hold at %0d", count);

        $display("Testbench complete");
        #20 $finish;
    end
endmodule
```

## Step 7: Run Simulation

=== "GUI"

    1. Open the **Testbench** panel (**View > Testbench** or click it in the Flow Navigator)
    2. The panel discovers `counter_tb.v` automatically
    3. Click **Run All** to compile and simulate
    4. Results appear in the test tree: green circles for passing tests
    5. The **Waveform** panel opens automatically with the VCD output

    <!-- Screenshot: Testbench panel showing PASS results, waveform viewer below with clk/count/enable signals -->

=== "CLI"

    ```bash
    openforge sim
    ```

    Output:

    ```
    [INFO] Compiling with Icarus Verilog...
    [INFO] Running simulation...
    PASS: count = 10
    PASS: hold at 11
    Testbench complete
    [INFO] Simulation complete in 0.3s
    [INFO] Waveform: sim_build/dump.vcd
    ```

=== "TCL Console"

    ```tcl
    compile_sim -top counter_tb
    run_sim -time 500ns
    open_waveform sim_build/dump.vcd
    ```

## Step 8: View Waveforms

=== "GUI"

    The waveform viewer opens automatically after simulation. If not, go to **View > Waveform** and click **Load** to open `sim_build/dump.vcd`.

    The waveform panel provides:

    - **Signal tree** on the left -- expand modules, drag signals to the canvas
    - **Value column** showing current values at the cursor position
    - **Waveform canvas** with zoom, pan, dual cursors, and markers
    - **Minimap** for navigating large traces
    - Bus signals display as diamond transitions with hex values
    - Analog signals render as continuous waveforms

    Keyboard shortcuts:

    | Key | Action |
    |---|---|
    | `+` / `-` | Zoom in / out |
    | `F` | Zoom to fit all signals |
    | `Left` / `Right` | Move cursor |
    | `Ctrl+G` | Go to time |

    <!-- Screenshot: Waveform viewer with clk, rst_n, enable, count[7:0] signals -->

=== "CLI"

    ```bash
    openforge wave sim_build/dump.vcd
    ```

## Step 9: View Synthesis Results

=== "GUI"

    Open the **Synthesis** panel (**View > Synthesis**) to see:

    - **Resource Utilization** tab: gate count, cell breakdown, area estimate
    - **Hierarchy** tab: module tree with per-module statistics
    - **Schematic** tab: interactive gate-level schematic viewer
    - **Messages** tab: Yosys warnings and info messages

    <!-- Screenshot: Synthesis panel with utilization table and schematic view -->

=== "CLI"

    ```bash
    openforge report area
    openforge report timing
    ```

## What's Next

You now have a complete synthesis + simulation workflow. From here:

- [Run the ASIC tutorial](../tutorials/asic-flow.md) to take this counter through place-and-route to GDSII
- [Run the FPGA tutorial](../tutorials/fpga-flow.md) to target a physical FPGA board
- [Add formal verification](../tutorials/verification.md) to prove properties about your design
- [Explore the panel reference](../panels/overview.md) to learn about all available panels
