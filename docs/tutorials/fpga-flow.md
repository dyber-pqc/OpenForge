# Tutorial: FPGA Flow -- iCEBreaker Blinky

This tutorial walks through a complete FPGA design flow using OpenForge, targeting the [iCEBreaker](https://1bitsquared.com/products/icebreaker) board with its Lattice iCE40UP5K FPGA. You will write a blinking LED module, synthesize it with Yosys, place and route with nextpnr, generate a bitstream, and program the board.

## Prerequisites

- OpenForge installed ([Installation guide](../getting-started/installation.md))
- FPGA tools installed: Yosys, nextpnr-ice40, icestorm (icepack, iceprog)
- An iCEBreaker board connected via USB (optional -- you can complete synthesis and P&R without hardware)

Verify tool installation:

```bash
yosys --version
nextpnr-ice40 --version
icepack --help
```

## Step 1: Create the Project

=== "GUI"

    1. Open OpenForge and click **File > New Project**
    2. Set the project name to `icebreaker-blinky`
    3. Set the target to **FPGA** and the device family to `ice40-up5k`
    4. Click **Create**

=== "CLI"

    ```bash
    openforge init icebreaker-blinky --target ice40-up5k --top blinky
    cd icebreaker-blinky
    ```

## Step 2: Write the RTL

Create `src/blinky.v` with a simple counter-based LED blinker:

```verilog
`timescale 1ns / 1ps

module blinky (
    input  wire clk,       // 12 MHz oscillator on iCEBreaker
    output wire led_r,     // Red LED (active low)
    output wire led_g      // Green LED (active low)
);

    // 24-bit counter at 12 MHz gives ~1.4s full cycle
    reg [23:0] counter = 24'd0;

    always @(posedge clk) begin
        counter <= counter + 1'b1;
    end

    // Red LED toggles at ~0.7s (bit 23)
    // Green LED toggles at ~0.35s (bit 22)
    assign led_r = ~counter[23];
    assign led_g = ~counter[22];

endmodule
```

The iCEBreaker has a 12 MHz oscillator. A 24-bit counter divides that down to visible blink rates. The LEDs are active-low, so we invert the counter bits.

## Step 3: Pin Constraints

Create `constraints/icebreaker.pcf` to map ports to physical FPGA pins:

```
# iCEBreaker pin constraints
# 12 MHz oscillator
set_io clk 35

# On-board LEDs (active low accent LEDs accent accent accent)
set_io led_r 11
set_io led_g 37
```

!!! tip "Pin Planner"
    You can also assign pins graphically using the **Pin Planner** panel in the desktop app. Open it from **View > Pin Planner**, then drag signals onto the package pin diagram.

## Step 4: Configure the Project

Update `openforge.yaml`:

```yaml
project:
  name: "icebreaker-blinky"
  top_module: "blinky"

design:
  sources:
    - src/blinky.v
  constraints:
    - constraints/icebreaker.pcf

fpga:
  family: ice40
  device: up5k
  package: sg48
```

## Step 5: Synthesize

=== "GUI"

    1. In the **Flow Navigator**, expand **FPGA** and click **Synthesize**
    2. The console shows Yosys output as it parses your Verilog and maps to iCE40 cells
    3. When done, the **Synthesis** panel shows resource utilization:
        - Logic cells used (LUT4 + carry chains)
        - I/O pins used
        - PLLs, RAMs, and DSP blocks

    <!-- Screenshot: Flow Navigator with Synthesis step highlighted green -->

=== "CLI"

    ```bash
    openforge fpga synth --top blinky
    ```

    Expected output:

    ```
    [INFO] Running Yosys for iCE40 synthesis...
    [INFO] Synthesis complete
    [INFO]   LUT4:     26
    [INFO]   DFF:      24
    [INFO]   IO:       3
    [INFO]   Netlist: synth_build/blinky.json
    ```

Yosys maps your RTL to the iCE40 primitive cells: SB_LUT4 for combinational logic, SB_DFF for flip-flops, and SB_IO for I/O buffers.

## Step 6: Place and Route

=== "GUI"

    1. Click **FPGA > Place & Route** in the Flow Navigator
    2. nextpnr runs placement and routing, optimizing for timing
    3. The **Layout** panel shows the placed cells on the iCE40 die
    4. Timing results appear in the **Timing** panel

    <!-- Screenshot: Layout viewer showing placed cells on iCE40 die -->

=== "CLI"

    ```bash
    openforge fpga pnr
    ```

    Expected output:

    ```
    [INFO] Running nextpnr-ice40...
    [INFO] Device: iCE40UP5K (sg48)
    [INFO] Placement: 26/5280 LCs used (0.5%)
    [INFO] Routing: complete
    [INFO] Fmax: 78.3 MHz (target: 12 MHz) -- timing met
    [INFO] Output: pnr_build/blinky.asc
    ```

!!! note "Timing closure"
    nextpnr reports the maximum achievable frequency (Fmax). For this simple design, Fmax will be well above the 12 MHz clock, so timing is easily met.

## Step 7: Generate Bitstream

=== "GUI"

    Click **FPGA > Generate Bitstream** in the Flow Navigator. This runs `icepack` to convert the ASCII placement file to a binary bitstream.

=== "CLI"

    ```bash
    openforge fpga bitstream
    ```

    This produces `pnr_build/blinky.bin` -- the binary bitstream file ready for programming.

## Step 8: Program the Board

Connect your iCEBreaker board via USB.

=== "GUI"

    1. Click **FPGA > Program** in the Flow Navigator
    2. OpenForge detects the iCEBreaker over USB and programs the SRAM
    3. The LEDs start blinking immediately

    For persistent programming (writes to flash so the design survives power cycles):

    1. Click **FPGA > Program (Flash)** or use the dropdown menu on the Program button

=== "CLI"

    ```bash
    # SRAM programming (volatile, immediate)
    openforge fpga flash --sram

    # Flash programming (persistent)
    openforge fpga flash
    ```

## Understanding the Output Files

| File | Description |
|---|---|
| `synth_build/blinky.json` | Yosys JSON netlist with iCE40 cells |
| `synth_build/blinky.v` | Gate-level Verilog netlist |
| `pnr_build/blinky.asc` | nextpnr ASCII placement and routing |
| `pnr_build/blinky.bin` | Binary bitstream for iCE40 |

## Troubleshooting

**nextpnr fails with "no route found"**
:   Your design may be too large for the device, or pin constraints conflict with the device's routing fabric. Check the pin assignments in your PCF file against the iCEBreaker schematic.

**iceprog cannot find the device**
:   Ensure the iCEBreaker is connected via USB and the FTDI driver is installed. On Linux, you may need udev rules:

    ```bash
    echo 'ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6010", MODE="0660", GROUP="plugdev"' | \
      sudo tee /etc/udev/rules.d/99-icebreaker.rules
    sudo udevadm control --reload-rules
    ```

**Timing violations**
:   If Fmax is below your target frequency, consider pipelining or reducing combinational depth. The Timing panel shows the critical path.

## Next Steps

- Modify the design to add a UART transmitter and send counter values to your PC
- Try targeting the ECP5 (Lattice) for a larger FPGA
- Add a testbench and simulate before programming -- see the [Verification tutorial](verification.md)
- Explore the [Pin Planner](../guide/pin-planner.md) for graphical pin assignment
