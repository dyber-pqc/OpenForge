# Quick Start

Five-minute walkthroughs for each major design flow. Each section assumes you have OpenForge installed and EDA tools available (see [Installation](installation.md)).

## FPGA Quick Start

Target: synthesize a blinky LED design for the Lattice iCE40 and generate a bitstream.

=== "GUI"

    1. **File > New Project** -- name it `blinky`, set target to `ice40-hx8k`
    2. Create `src/blinky.v`:

        ```verilog
        module blinky (
            input  wire clk,
            output reg  led
        );
            reg [23:0] counter = 0;
            always @(posedge clk) begin
                counter <= counter + 1;
                led <= counter[23];
            end
        endmodule
        ```

    3. Create `constraints/pins.pcf`:

        ```
        set_io clk 35
        set_io led 99
        ```

    4. In the **Flow Navigator**, click **FPGA > Synthesize**
    5. Click **FPGA > Place & Route**
    6. Click **FPGA > Generate Bitstream**
    7. Connect your board and click **FPGA > Program**

=== "CLI"

    ```bash
    openforge init blinky --target ice40-hx8k
    # Add blinky.v and pins.pcf as above, then:
    openforge fpga synth --top blinky
    openforge fpga pnr
    openforge fpga bitstream
    openforge fpga flash
    ```

The full FPGA flow produces:

```
synth_build/blinky.json    # Yosys netlist
pnr_build/blinky.asc       # nextpnr placement
pnr_build/blinky.bin       # Bitstream
```

!!! tip "Supported FPGA families"
    OpenForge supports iCE40 (via icestorm/nextpnr-ice40), ECP5 (via nextpnr-ecp5), and Gowin devices. Xilinx support uses Yosys for synthesis with Vivado for P&R when available.

## ASIC Quick Start

Target: synthesize an 8-bit counter for the SkyWater 130nm PDK and run it through physical design.

=== "GUI"

    1. **File > New Project** -- name it `counter-asic`, set PDK to `sky130`
    2. Add your RTL to `src/counter.v` (see the [First Project](first-project.md) guide for the full source)
    3. Create `constraints/timing.sdc`:

        ```tcl
        create_clock -name clk -period 10.0 [get_ports clk]
        ```

    4. **Flow Navigator > Synthesis > Run Synthesis** -- Yosys synthesizes against sky130_fd_sc_hd
    5. **Flow Navigator > Physical Design > Run P&R** -- OpenROAD runs floorplanning, placement, CTS, and routing
    6. **Flow Navigator > Signoff > Run DRC** -- Magic checks design rules
    7. **Flow Navigator > Signoff > Run LVS** -- Netgen checks layout vs. schematic
    8. **Flow Navigator > Physical Design > Write GDSII** -- Export the final layout

=== "CLI"

    ```bash
    openforge init counter-asic --pdk sky130 --top counter
    # Add RTL and constraints, then:
    openforge synth
    openforge pnr
    openforge drc
    openforge lvs
    openforge gds
    ```

Output files:

```
synth_build/counter.v        # Gate-level netlist
synth_build/counter.json     # Yosys JSON netlist
pnr_build/counter_placed.def # Placed DEF
pnr_build/counter_routed.def # Routed DEF
pnr_build/counter.gds        # Final GDSII
reports/drc_report.rpt        # DRC results
reports/lvs_report.rpt        # LVS results
```

!!! note "PDK setup required"
    ASIC flows require the SKY130 PDK to be installed. Run `openforge pdk install sky130` or use the **Tools > PDK Manager** dialog.

## PCB Quick Start

Target: create a simple ESP32 breakout board with power regulation and pin headers.

=== "GUI"

    1. **File > New Project** -- name it `esp32-breakout`, set type to **PCB**
    2. Open the **Schematic Editor** panel
    3. Place components from the built-in library:
        - ESP32-WROOM-32 module
        - AMS1117-3.3 voltage regulator
        - Decoupling capacitors (100nF, 10uF)
        - 2x20 pin headers
        - USB-C connector
    4. Wire the schematic: power rails, GPIO breakout, boot/reset buttons
    5. Run **ERC** (Electrical Rule Check) from the toolbar
    6. Switch to **PCB Layout** and define the board outline
    7. Run the **auto-router** or manually route traces
    8. Run **DRC** to check clearances and trace widths
    9. **File > Export > Gerber** to generate manufacturing files

=== "CLI"

    ```bash
    openforge init esp32-breakout --type pcb
    # Edit schematic in the GUI, then export:
    openforge pcb drc
    openforge pcb gerber --output gerber/
    ```

Output files:

```
gerber/
  esp32-breakout-F_Cu.gbr      # Front copper
  esp32-breakout-B_Cu.gbr      # Back copper
  esp32-breakout-F_SilkS.gbr   # Front silkscreen
  esp32-breakout-Edge_Cuts.gbr  # Board outline
  esp32-breakout.drl            # Drill file
  esp32-breakout-job.gbrjob     # Job file for fab
```

## Verification Quick Start

Run a testbench and check coverage in under a minute:

=== "GUI"

    1. Open an existing project with a testbench (e.g., the `simple-counter` example)
    2. Open the **Testbench** panel -- it discovers test files automatically
    3. Click **Run All**
    4. Green/red indicators show pass/fail per test
    5. Open the **Waveform** panel to inspect signals
    6. Open the **Coverage Dashboard** to see line and toggle coverage percentages

=== "CLI"

    ```bash
    cd examples/simple-counter
    openforge sim
    openforge coverage report
    ```

For formal verification:

```bash
openforge formal --depth 20
```

## What's Next

- **[FPGA Tutorial](../tutorials/fpga-flow.md)** -- Full iCEBreaker blinky tutorial with detailed explanations
- **[ASIC Tutorial](../tutorials/asic-flow.md)** -- Complete SKY130 RTL-to-GDSII walkthrough
- **[PCB Tutorial](../tutorials/pcb-flow.md)** -- ESP32 breakout from schematic to Gerber
- **[Panel Reference](../panels/overview.md)** -- Learn what every panel does
