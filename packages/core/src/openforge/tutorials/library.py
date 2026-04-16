"""Bundled tutorial library.

Every tutorial has real, executable steps. The bundled
``examples/simple-counter`` is used as the canonical ASIC walkthrough so
that new users can follow it without downloading extra content.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TutorialStep(BaseModel):
    title: str
    content: str  # markdown
    target_panel: str | None = None
    target_widget: str | None = None
    action: str | None = None  # 'click' | 'type' | 'wait' | 'observe'
    expected_state: str | None = None
    hint: str | None = None


class Tutorial(BaseModel):
    id: str
    title: str
    description: str
    persona: str  # fpga | asic | pcb | verification | analog
    duration_minutes: int
    difficulty: str  # beginner | intermediate | advanced
    prerequisites: list[str] = Field(default_factory=list)
    steps: list[TutorialStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FPGA: iCE40 blinky
# ---------------------------------------------------------------------------
_FPGA_BLINKY = Tutorial(
    id="fpga_blinky_ice40",
    title="iCEBreaker Blinky",
    description="Blink an LED on the iCEBreaker (Lattice iCE40UP5K). Covers project creation, constraints, yosys + nextpnr-ice40, and programming the board via openFPGALoader.",
    persona="fpga",
    duration_minutes=15,
    difficulty="beginner",
    prerequisites=["yosys", "nextpnr-ice40", "icepack", "openFPGALoader"],
    steps=[
        TutorialStep(
            title="Create a new iCE40 project",
            content="Click **File > New Project** and pick the **iCE40 FPGA** template. Name it `blinky` and choose the `iCEBreaker` board preset.",
            target_panel="welcome",
            action="click",
            hint="The template ships a pre-wired PCF for the iCEBreaker LEDs.",
        ),
        TutorialStep(
            title="Open the top module",
            content="In the **Project** tree, open `rtl/blinky.v`. It contains a simple 24-bit counter that drives `LED1` from its top bit.",
            target_panel="editor",
            action="observe",
        ),
        TutorialStep(
            title="Review constraints",
            content="Open `constraints/icebreaker.pcf`. You should see `set_io LED1 35` and `set_io clk 35`. These are the physical pin assignments.",
            target_panel="editor",
            action="observe",
        ),
        TutorialStep(
            title="Run synthesis",
            content="Click the **Synthesize** button in the toolbar, or run `run synth` from the TCL console. Yosys will read the RTL and emit a technology-mapped BLIF/JSON.",
            target_panel="synthesis",
            action="click",
            expected_state="synth_ok",
        ),
        TutorialStep(
            title="Place and route",
            content="Click **Place & Route**. nextpnr-ice40 packs, places, and routes for the UP5K part. Watch the progress in the console.",
            target_panel="physical",
            action="click",
            expected_state="pnr_ok",
        ),
        TutorialStep(
            title="Generate the bitstream",
            content="icepack runs automatically and writes `build/blinky.bin`. Check the Reports panel for resource usage (LUTs / FFs / BRAMs).",
            target_panel="reports",
            action="observe",
        ),
        TutorialStep(
            title="Program the board",
            content="Plug in your iCEBreaker and click **Program**. This invokes `openFPGALoader -b ice40_generic build/blinky.bin`. LED1 should start blinking at ~0.5 Hz.",
            target_panel="fpga_target",
            action="click",
            hint="No hardware? You can still simulate the design in the Testbench panel.",
        ),
        TutorialStep(
            title="Experiment",
            content="Try changing the counter width in `blinky.v` and re-running the flow. Observe how resource usage changes in the Reports panel.",
            target_panel="editor",
            action="observe",
        ),
    ],
)

# ---------------------------------------------------------------------------
# FPGA: ECP5 UART
# ---------------------------------------------------------------------------
_FPGA_UART_ECP5 = Tutorial(
    id="fpga_uart_echo_ecp5",
    title="ULX3S UART Loopback",
    description="Build a UART echo on the ULX3S (LFE5U-85F). Walks through nextpnr-ecp5, ecppack, and openFPGALoader.",
    persona="fpga",
    duration_minutes=20,
    difficulty="beginner",
    prerequisites=["yosys", "nextpnr-ecp5", "ecppack", "openFPGALoader"],
    steps=[
        TutorialStep(title="New ECP5 project", content="File > New Project > **ECP5 FPGA** > ULX3S 85F preset."),
        TutorialStep(title="Import UART core", content="Right-click `rtl/`, choose **Import IP**, and pick the `uart_tx` / `uart_rx` pair from the IP catalog."),
        TutorialStep(title="Wire top module", content="Edit `top.v` to wire RX directly to TX through a 16-byte FIFO."),
        TutorialStep(title="Constraints", content="Open `ulx3s_v20.lpf` and verify `LOCATE COMP \"rx\"` and `LOCATE COMP \"tx\"` are on the USB-UART pins."),
        TutorialStep(title="Synthesize", content="Click **Synthesize**. Inspect the generated `synth.json`.", target_panel="synthesis", action="click"),
        TutorialStep(title="Place and route", content="Click **Place & Route**. nextpnr-ecp5 will target `LFE5U-85F` at 25 MHz.", target_panel="physical", action="click"),
        TutorialStep(title="Pack bitstream", content="`ecppack` emits `top.bit`. Verify in Reports.", target_panel="reports"),
        TutorialStep(title="Program and test", content="Click **Program** then open a terminal at 115200 8N1 on the USB port. Anything you type should echo back."),
    ],
)

# ---------------------------------------------------------------------------
# FPGA: LiteX on Tang Nano
# ---------------------------------------------------------------------------
_FPGA_LITEX = Tutorial(
    id="fpga_litex_soc_tangnano",
    title="LiteX SoC on Tang Nano 9K",
    description="Generate a minimal LiteX-based RISC-V SoC targeting the Sipeed Tang Nano 9K (GW1NR-9).",
    persona="fpga",
    duration_minutes=30,
    difficulty="intermediate",
    prerequisites=["yosys", "nextpnr-gowin", "gowin_pack", "python3", "litex"],
    steps=[
        TutorialStep(title="LiteX project", content="File > New > **Gowin FPGA** > Tang Nano 9K > *LiteX SoC*."),
        TutorialStep(title="SoC config", content="The wizard emits `soc.py`. Edit to pick the CPU (vexriscv, femtorv, picorv32)."),
        TutorialStep(title="Generate HDL", content="Click **Generate SoC**. LiteX runs and drops `build/gateware/top.v`."),
        TutorialStep(title="Synthesize", content="Synthesize with yosys + Gowin plugin.", target_panel="synthesis"),
        TutorialStep(title="PnR", content="nextpnr-gowin places and routes.", target_panel="physical"),
        TutorialStep(title="Pack", content="gowin_pack writes `top.fs`.", target_panel="reports"),
        TutorialStep(title="Program", content="Use **openFPGALoader -b tangnano9k** to flash.", target_panel="fpga_target"),
        TutorialStep(title="Talk to the SoC", content="Open a serial monitor at 115200 and press Enter to get the LiteX BIOS prompt."),
    ],
)

# ---------------------------------------------------------------------------
# ASIC: sky130 counter (the bundled example)
# ---------------------------------------------------------------------------
_ASIC_COUNTER = Tutorial(
    id="asic_counter_sky130",
    title="ASIC Counter: RTL to GDSII on sky130",
    description="Walks through the bundled `examples/simple-counter` and produces a signed-off GDSII on SkyWater sky130A. This is the canonical ASIC flow tutorial.",
    persona="asic",
    duration_minutes=45,
    difficulty="intermediate",
    prerequisites=["yosys", "openroad", "magic", "netgen", "klayout"],
    steps=[
        TutorialStep(
            title="Open the example",
            content="Choose **File > Open Example > simple-counter**. The project contains `rtl/counter.v`, a constraints file, and an `openforge.yaml`.",
            target_panel="welcome",
            action="click",
        ),
        TutorialStep(
            title="Inspect the RTL",
            content="Open `rtl/counter.v`. It's a straightforward 8-bit synchronous counter with enable and reset. Notice the clock input is named `clk`.",
            target_panel="editor",
        ),
        TutorialStep(
            title="Set the PDK",
            content="In **Project Settings**, confirm PDK = `sky130A`. The wizard should have downloaded the PDK already; if not, run **Tools > Install PDK**.",
            target_panel="pdk_manager",
            action="observe",
        ),
        TutorialStep(
            title="Synthesize with yosys",
            content="Click **Run Synthesis**. Under the hood OpenForge issues `yosys -c synth.tcl` and loads the sky130A liberty. Check the netlist in `synth_build/counter.v`.",
            target_panel="synthesis",
            action="click",
            expected_state="synth_ok",
        ),
        TutorialStep(
            title="Floorplan",
            content="Click **Floorplan**. OpenROAD reads the netlist, computes a die/core area from utilization (default 60%), and emits `counter_floorplan.def`.",
            target_panel="physical",
            action="click",
            expected_state="floorplan_ok",
        ),
        TutorialStep(
            title="Placement",
            content="Click **Place**. Global + detailed placement run, producing `counter_placed.def`. Load it in the GDS / DEF viewer to inspect.",
            target_panel="layout",
            action="click",
        ),
        TutorialStep(
            title="CTS and Routing",
            content="Click **CTS** then **Route**. TritonCTS builds a balanced clock tree, then FastRoute + TritonRoute do global/detailed routing. Produces `counter_routed.def`.",
            target_panel="physical",
            action="click",
        ),
        TutorialStep(
            title="DRC in KLayout",
            content="Click **Run DRC**. KLayout runs the sky130 DRC deck and writes `drc_report.rpt`. Open the report - you should see 0 violations.",
            target_panel="reports",
            expected_state="drc_clean",
        ),
        TutorialStep(
            title="LVS with netgen",
            content="Click **Run LVS**. Magic extracts the netlist from layout, and netgen compares it against the synthesized verilog. The Reports panel should show **match**.",
            target_panel="reports",
            expected_state="lvs_match",
        ),
        TutorialStep(
            title="Export GDSII",
            content="Click **Export GDS**. KLayout writes `counter.gds`. You've just completed a full RTL-to-GDSII flow on an open PDK.",
            target_panel="layout",
            action="click",
        ),
    ],
)

# ---------------------------------------------------------------------------
# ASIC: Caravel MPW submission
# ---------------------------------------------------------------------------
_ASIC_CARAVEL = Tutorial(
    id="asic_caravel_submission",
    title="Caravel User Project",
    description="Generate an Efabless Caravel-compatible user project wrapper for the counter design.",
    persona="asic",
    duration_minutes=30,
    difficulty="advanced",
    prerequisites=["yosys", "openroad", "magic", "git"],
    steps=[
        TutorialStep(title="Start Caravel wrapper", content="File > New > **Caravel MPW** template."),
        TutorialStep(title="Import counter as submodule", content="Right-click `ip/`, **Import Design**, pick the simple-counter project."),
        TutorialStep(title="Wire user_project_wrapper", content="OpenForge auto-generates `user_project_wrapper.v` connecting the Wishbone/logic analyzer ports."),
        TutorialStep(title="Hardened macro", content="Click **Harden Macro**. Runs full RTL-to-GDS for the inner block."),
        TutorialStep(title="Top-level integration", content="Click **Harden Top**. Integrates the hardened macro into the Caravel user area."),
        TutorialStep(title="Pre-check", content="Click **Run Precheck** - executes the Efabless tape-out checks."),
        TutorialStep(title="Make manifest", content="OpenForge writes `manifest.json` and computes `info.yaml` for the MPW submission."),
        TutorialStep(title="Tag and submit", content="Commit, tag `mpw-submission`, and push. Caravel CI picks up the release."),
    ],
)

# ---------------------------------------------------------------------------
# PCB: breakout board
# ---------------------------------------------------------------------------
_PCB_BREAKOUT = Tutorial(
    id="pcb_breakout_board",
    title="0.1\" Breakout PCB",
    description="Design a simple 0.1\" pitch breakout board with headers. Covers schematic, layout, and gerber export.",
    persona="pcb",
    duration_minutes=25,
    difficulty="beginner",
    prerequisites=["kicad"],
    steps=[
        TutorialStep(title="New PCB project", content="File > New > **PCB only** template."),
        TutorialStep(title="Schematic", content="Drop a pin header (2x10) and a decoupling cap. Wire them up.", target_panel="schematic"),
        TutorialStep(title="Footprints", content="Assign `Pin_Header_2x10_P2.54mm_Vertical` and `C_0805`."),
        TutorialStep(title="Update PCB", content="Import netlist into the layout editor.", target_panel="pcb_designer"),
        TutorialStep(title="Place", content="Position the header and the cap."),
        TutorialStep(title="Route", content="Auto-route with the built-in router, or hand-route the traces."),
        TutorialStep(title="DRC", content="Run the built-in PCB DRC - must be clean before export."),
        TutorialStep(title="Export Gerbers", content="Click **Export Gerbers** to get a zip suitable for JLCPCB / PCBWay."),
    ],
)

# ---------------------------------------------------------------------------
# PCB: RP2040 carrier
# ---------------------------------------------------------------------------
_PCB_PICO = Tutorial(
    id="pcb_pi_pico_carrier",
    title="Raspberry Pi Pico Carrier",
    description="Design a 4-layer carrier board for the RP2040 with USB-C, UART, and I2C.",
    persona="pcb",
    duration_minutes=40,
    difficulty="intermediate",
    prerequisites=["kicad"],
    steps=[
        TutorialStep(title="New project", content="File > New > **PCB only** > blank 4-layer."),
        TutorialStep(title="Import Pico footprint", content="Use the IP catalog to drop a Pico-shaped module."),
        TutorialStep(title="USB-C connector", content="Add a USB-C receptacle, configure as UFP."),
        TutorialStep(title="Decoupling", content="Add 100 nF per power pin, plus a 10 uF bulk cap."),
        TutorialStep(title="Pin-outs", content="Break out UART0, I2C0, and 4 GPIOs to a 2x6 header."),
        TutorialStep(title="Impedance", content="Check the USB differential pair impedance with the built-in calculator (target 90 ohms)."),
        TutorialStep(title="Route 4 layers", content="Signal / GND / PWR / Signal stackup. Route diff pairs on top."),
        TutorialStep(title="3D preview", content="Switch to 3D view to verify the board visually."),
    ],
)

# ---------------------------------------------------------------------------
# Verification: SVA basics
# ---------------------------------------------------------------------------
_VERIF_ASSERT = Tutorial(
    id="verif_assertion_basics",
    title="SystemVerilog Assertions",
    description="Add SVA properties and cover points to the counter design and run them under Verilator.",
    persona="verification",
    duration_minutes=25,
    difficulty="beginner",
    prerequisites=["verilator"],
    steps=[
        TutorialStep(title="Open example", content="File > Open Example > simple-counter."),
        TutorialStep(title="Add assertions file", content="Create `rtl/counter_sva.sv` with a concurrent assertion checking the counter never skips values."),
        TutorialStep(title="Bind assertions", content="Use `bind counter counter_sva u_sva(.*);` in the testbench."),
        TutorialStep(title="Cover properties", content="Add `cover property` for the overflow case."),
        TutorialStep(title="Run Verilator", content="Click **Simulate**. Verilator runs with `--assert --cov`.", target_panel="testbench"),
        TutorialStep(title="View coverage", content="Open the Coverage panel - you should see the overflow bin hit.", target_panel="coverage_closure"),
        TutorialStep(title="Break the design", content="Change `count <= count + 1` to `count <= count + 2` and re-simulate. The assertion should fire."),
        TutorialStep(title="Waveform", content="Inspect the waveform at the failing time - the GTKWave panel auto-jumps to the assertion.", target_panel="waveform"),
    ],
)

# ---------------------------------------------------------------------------
# Verification: UVM-lite
# ---------------------------------------------------------------------------
_VERIF_UVM = Tutorial(
    id="verif_uvm_lite",
    title="UVM-Lite with Verilator",
    description="Stand up a minimal UVM-style testbench (driver, monitor, scoreboard) in SystemVerilog, running under Verilator.",
    persona="verification",
    duration_minutes=40,
    difficulty="advanced",
    prerequisites=["verilator"],
    steps=[
        TutorialStep(title="UVM-lite skeleton", content="File > New > **Verification** > *UVM-Lite testbench*. The template drops driver/monitor/scoreboard stubs."),
        TutorialStep(title="Interface", content="Define a `clocking block` in `dut_if.sv` around the DUT ports."),
        TutorialStep(title="Driver", content="Implement the `run_phase` to pull transactions off the sequencer and drive them onto the interface."),
        TutorialStep(title="Monitor", content="Sample the interface and publish transactions on an analysis port."),
        TutorialStep(title="Scoreboard", content="Compare monitored transactions against a golden reference model."),
        TutorialStep(title="Sequences", content="Write a smoke sequence and a random sequence."),
        TutorialStep(title="Run", content="Simulate with Verilator. Check the test summary in the console."),
        TutorialStep(title="Regression", content="Add the tests to the Regression panel and run overnight."),
    ],
)

# ---------------------------------------------------------------------------
# Analog: sky130 TIA
# ---------------------------------------------------------------------------
_ANALOG_TIA = Tutorial(
    id="analog_opamp_tia",
    title="Sky130 Transimpedance Amplifier",
    description="Design a single-ended transimpedance amplifier in sky130, simulate in ngspice, and plot the frequency response.",
    persona="analog",
    duration_minutes=45,
    difficulty="advanced",
    prerequisites=["ngspice", "magic", "xschem"],
    steps=[
        TutorialStep(title="Analog project", content="File > New > **Analog** > *sky130 opamp template*."),
        TutorialStep(title="Schematic", content="Open the schematic editor. Place a 5-transistor OTA and feedback resistor.", target_panel="spice_panel"),
        TutorialStep(title="Bias", content="Set Vdd=1.8, Ibias=5uA, input common-mode = Vdd/2."),
        TutorialStep(title="DC op point", content="Run **DC operating point**. Verify all transistors are in saturation.", target_panel="spice_simulator"),
        TutorialStep(title="AC sweep", content="Run an AC sweep from 10 Hz to 1 GHz. Plot gain and phase."),
        TutorialStep(title="Compensation", content="Adjust Cc until you get >60 degrees phase margin."),
        TutorialStep(title="Layout", content="Run **Auto Layout** to generate a sized, DRC-clean layout in magic.", target_panel="transistor_layout"),
        TutorialStep(title="Post-layout sim", content="Extract parasitics and re-run the AC sweep. Compare pre and post-layout."),
    ],
)


TUTORIALS: dict[str, Tutorial] = {
    _FPGA_BLINKY.id: _FPGA_BLINKY,
    _FPGA_UART_ECP5.id: _FPGA_UART_ECP5,
    _FPGA_LITEX.id: _FPGA_LITEX,
    _ASIC_COUNTER.id: _ASIC_COUNTER,
    _ASIC_CARAVEL.id: _ASIC_CARAVEL,
    _PCB_BREAKOUT.id: _PCB_BREAKOUT,
    _PCB_PICO.id: _PCB_PICO,
    _VERIF_ASSERT.id: _VERIF_ASSERT,
    _VERIF_UVM.id: _VERIF_UVM,
    _ANALOG_TIA.id: _ANALOG_TIA,
}


def by_persona(persona: str) -> list[Tutorial]:
    return [t for t in TUTORIALS.values() if t.persona == persona]


def featured() -> list[Tutorial]:
    """Three 'getting started' tutorials for the Welcome panel."""
    return [
        TUTORIALS["asic_counter_sky130"],
        TUTORIALS["fpga_blinky_ice40"],
        TUTORIALS["verif_assertion_basics"],
    ]
