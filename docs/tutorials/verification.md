# Tutorial: Verification -- Testbench, Coverage, and Formal

This tutorial covers the verification capabilities in OpenForge: writing and running testbenches with Icarus Verilog, measuring code coverage, running formal verification with SymbiYosys, and using the crypto verification suite for security-critical designs.

## Prerequisites

- OpenForge installed ([Installation guide](../getting-started/installation.md))
- Simulation tools: Icarus Verilog (iverilog) and/or Verilator
- Formal tools: SymbiYosys (sby) with Yosys
- An existing project with RTL -- we use the 8-bit counter from the [First Project](../getting-started/first-project.md) guide

## Part 1: Verilog Testbench

### Writing a Testbench

Create `tb/counter_tb.v` with a self-checking testbench:

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

    // Device under test
    counter dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .count(count),
        .overflow(overflow)
    );

    // VCD dump for waveform viewing
    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, counter_tb);
    end

    integer errors = 0;

    task check(input [7:0] expected, input [255:0] name);
    begin
        @(negedge clk);
        if (count !== expected) begin
            $display("  FAIL: %0s - count=%0d expected=%0d", name, count, expected);
            errors = errors + 1;
        end else begin
            $display("  PASS: %0s - count=%0d", name, count);
        end
    end
    endtask

    initial begin
        $display("========================================");
        $display("  Counter Testbench");
        $display("========================================");

        // Test 1: Reset
        rst_n = 0; enable = 0;
        repeat (3) @(posedge clk);
        @(posedge clk) rst_n = 1;
        check(0, "Reset value");

        // Test 2: Count 10 cycles
        @(negedge clk) enable = 1;
        repeat (10) @(posedge clk);
        check(10, "Count to 10");

        // Test 3: Hold while disabled
        @(negedge clk) enable = 0;
        repeat (5) @(posedge clk);
        check(11, "Hold while disabled");

        // Test 4: Resume counting
        @(negedge clk) enable = 1;
        repeat (5) @(posedge clk);
        check(16, "Resume counting");

        // Test 5: Reset mid-count
        @(posedge clk) rst_n = 0;
        @(posedge clk);
        check(0, "Reset mid-count");

        // Test 6: Overflow
        rst_n = 1; enable = 1;
        repeat (256) @(posedge clk);

        // Summary
        $display("========================================");
        if (errors == 0) $display("  ALL TESTS PASSED");
        else $display("  %0d TESTS FAILED", errors);
        $display("========================================");
        #20 $finish;
    end
endmodule
```

### Running the Testbench

=== "GUI"

    1. Open the **Testbench** panel (**View > Testbench**)
    2. The panel discovers `counter_tb.v` automatically from your project config
    3. Select the simulator: **Icarus Verilog** (default) or **Verilator**
    4. Click **Run All** to compile and simulate
    5. The test tree shows results with status indicators:
        - Green circle = PASS
        - Red circle = FAIL
        - Yellow circle = RUNNING
        - Gray circle = NOT RUN
    6. The console output shows each test's pass/fail messages
    7. The waveform viewer opens automatically with the VCD file

=== "CLI"

    ```bash
    openforge sim
    ```

    ```
    [INFO] Compiling with Icarus Verilog...
    [INFO] Running simulation...
    ========================================
      Counter Testbench
    ========================================
      PASS: Reset value - count=0
      PASS: Count to 10 - count=10
      PASS: Hold while disabled - count=11
      PASS: Resume counting - count=16
      PASS: Reset mid-count - count=0
    ========================================
      ALL TESTS PASSED
    ========================================
    [INFO] Simulation complete in 0.3s
    [INFO] Waveform: sim_build/dump.vcd
    ```

=== "TCL Console"

    ```tcl
    compile_sim -top counter_tb
    run_sim -time 500ns
    open_waveform sim_build/dump.vcd
    ```

### Cocotb Python Testbenches

OpenForge also supports [cocotb](https://www.cocotb.org/) testbenches written in Python:

Create `tb/counter_tb.py`:

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

@cocotb.test()
async def test_reset(dut):
    """Counter should be 0 after reset."""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.enable.value = 0
    await ClockCycles(dut.clk, 3)

    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    assert dut.count.value == 0, f"Expected 0, got {dut.count.value}"

@cocotb.test()
async def test_counting(dut):
    """Counter should increment when enabled."""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 1
    dut.enable.value = 1
    await ClockCycles(dut.clk, 10)

    await RisingEdge(dut.clk)
    assert dut.count.value == 10
```

Run cocotb tests the same way -- OpenForge detects `.py` testbenches and invokes cocotb automatically.

## Part 2: Code Coverage

OpenForge tracks code coverage during simulation to identify untested logic.

### Enabling Coverage

In `openforge.yaml`:

```yaml
verification:
  simulation:
    coverage:
      line: true      # Statement coverage
      toggle: true    # Signal toggle coverage
      branch: false   # Branch coverage (optional)
      fsm: false      # FSM state coverage (optional)
```

### Viewing Coverage

=== "GUI"

    1. Run simulation with coverage enabled
    2. Open the **Coverage Dashboard** panel (**View > Coverage Dashboard**)
    3. The dashboard shows:
        - Overall coverage percentage (line, toggle, branch)
        - Per-module coverage breakdown
        - Uncovered lines highlighted in the source editor
        - Toggle coverage showing which signals never toggled
    4. Click any module to see detailed line-by-line coverage

=== "CLI"

    ```bash
    openforge sim --coverage
    openforge coverage report
    ```

    ```
    Coverage Report: counter
    ========================
    Line coverage:   95.2% (20/21 lines)
    Toggle coverage: 87.5% (14/16 signals)
    
    Uncovered:
      counter.v:14  assign overflow = ... (overflow never asserted high)
    ```

!!! tip "Improving coverage"
    The coverage report identifies dead code and untested conditions. Write additional tests to cover edge cases like overflow, reset during specific states, and boundary conditions.

## Part 3: Formal Verification

Formal verification mathematically proves properties about your design without writing simulation vectors.

### Writing Assertions

Add SystemVerilog Assertions (SVA) to your RTL or a separate property file:

Create `properties/counter_props.sv`:

```systemverilog
module counter_props (
    input wire       clk,
    input wire       rst_n,
    input wire       enable,
    input wire [7:0] count,
    input wire       overflow
);

    // Property: after reset, count must be 0
    property p_reset;
        @(posedge clk) !rst_n |=> count == 0;
    endproperty
    assert property (p_reset);

    // Property: count increments by 1 when enabled
    property p_increment;
        @(posedge clk) disable iff (!rst_n)
        enable && (count < 8'hFF) |=> count == $past(count) + 1;
    endproperty
    assert property (p_increment);

    // Property: count holds when disabled
    property p_hold;
        @(posedge clk) disable iff (!rst_n)
        !enable |=> count == $past(count);
    endproperty
    assert property (p_hold);

    // Property: overflow only when count is max and enabled
    property p_overflow;
        @(posedge clk) disable iff (!rst_n)
        overflow |-> (count == 8'hFF) && enable;
    endproperty
    assert property (p_overflow);

endmodule
```

### Running Formal Verification

=== "GUI"

    1. Open the **Formal** panel (**View > Formal Verification**)
    2. Add your property file
    3. Set the proof depth (default: 20 cycles)
    4. Click **Run Formal**
    5. Results show each property as PROVEN, FAILED, or UNKNOWN:
        - Green = property proven for all reachable states up to depth
        - Red = counterexample found (click to view the trace)
        - Yellow = unknown (depth may be insufficient)

=== "CLI"

    ```bash
    openforge formal --depth 20
    ```

    ```
    [INFO] Running SymbiYosys formal verification...
    [INFO] Engine: smtbmc
    [INFO] Depth: 20 cycles
    [INFO] Results:
      PROVEN: p_reset
      PROVEN: p_increment
      PROVEN: p_hold
      PROVEN: p_overflow
    [INFO] All 4 properties proven
    ```

### Configuration

In `openforge.yaml`:

```yaml
verification:
  formal:
    tool: symbiyosys
    properties:
      - properties/counter_props.sv
    engines:
      - smtbmc
    depth: 20
```

Available engines: `smtbmc` (default, good for bounded proofs), `btor` (fast for small designs), `aiger` (unbounded via ABC), `abc` (direct ABC integration).

## Part 4: Crypto Verification

For cryptographic hardware, OpenForge provides specialized verification tools.

### Constant-Time Verification

Verifies that execution timing does not depend on secret data (preventing timing side-channel attacks):

```yaml
verification:
  crypto_verification:
    constant_time:
      secrets:
        - key_in
        - plaintext
      public:
        - ciphertext
```

=== "GUI"

    Open the **Security** panel > **Constant-Time** tab. Mark signals as secret or public, then run analysis. The panel highlights any data-dependent timing paths.

=== "CLI"

    ```bash
    openforge crypto ct-check
    ```

### Side-Channel Analysis

TVLA (Test Vector Leakage Assessment) analysis using power models:

```yaml
verification:
  crypto_verification:
    side_channel:
      power_model: hamming_weight
      tvla_threshold: 4.5
      num_traces: 10000
```

=== "GUI"

    Open the **Security** panel > **Side-Channel** tab. Configure the power model and run TVLA. The panel displays t-test results -- values exceeding the threshold (4.5) indicate potential leakage.

### FIPS 140-3 Compliance

Automated checking of FIPS requirements:

```yaml
verification:
  crypto_verification:
    fips_compliance:
      level: "1"
      checks:
        - kat           # Known Answer Tests
        - integrity     # Module integrity
        - zeroize       # Key zeroization
```

## Troubleshooting

**Simulation fails to compile**
:   Check that all source files are listed in `openforge.yaml` under `design.sources` and testbench files under `verification.simulation.testbenches`.

**Formal proof times out**
:   Reduce the depth or switch to a faster engine (`btor` for small designs). Complex designs may need manual abstraction.

**Coverage report shows 0%**
:   Ensure coverage is enabled in the config and you are using a simulator that supports it (Icarus or Verilator).

## Next Steps

- Add [UVM testbenches](../panels/verification.md) for more complex verification methodologies
- Use the [regression runner](../panels/verification.md) to manage test suites
- Explore [equivalence checking](../panels/verification.md) to verify pre- and post-synthesis equivalence
