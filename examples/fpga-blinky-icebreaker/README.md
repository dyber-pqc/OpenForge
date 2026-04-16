# FPGA Blinky - iCEBreaker Board

LED blinky pattern targeting the [iCEBreaker FPGA](https://1bitsquared.com/products/icebreaker) development board (Lattice iCE40 UP5K).

## What It Does

A 24-bit free-running counter divides the 12 MHz on-board oscillator to drive five LEDs at different blink rates, creating a cascading light pattern:

| LED  | Counter Bit | Frequency |
|------|-------------|-----------|
| LED1 | bit 23      | ~0.7 Hz   |
| LED2 | bit 22      | ~1.4 Hz   |
| LED3 | bit 21      | ~2.9 Hz   |
| LED4 | bit 20      | ~5.7 Hz   |
| LED5 | bit 23 inv  | ~0.7 Hz   |

LED5 is the on-board green LED (active-low), so it mirrors LED1 inverted.

## Prerequisites

- [Yosys](https://github.com/YosysHQ/yosys) (synthesis)
- [nextpnr-ice40](https://github.com/YosysHQ/nextpnr) (place & route)
- [IceStorm](https://github.com/YosysHQ/icestorm) (bitstream tools: icepack, iceprog)
- [Icarus Verilog](http://iverilog.icarus.com/) (simulation, optional)

Install the full open-source toolchain via [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build/releases).

## How to Run

### OpenForge CLI

```bash
cd examples/fpga-blinky-icebreaker
openforge run           # runs full flow: lint -> synth -> pnr -> bitstream
openforge run --stage synth   # run only up to synthesis
```

### OpenForge Desktop

1. Open the project folder in OpenForge Desktop (File > Open Project).
2. The Hierarchy panel shows the `blinky` module.
3. Click **Run Flow** to execute the full FPGA flow.
4. The bitstream file appears in the build output directory.

### Manual (standalone tools)

```bash
# Synthesis
yosys -p "read_verilog rtl/blinky.v; synth_ice40 -top blinky -json build/blinky.json"

# Place & Route
nextpnr-ice40 --up5k --package sg48 --pcf constraints/icebreaker.pcf \
    --json build/blinky.json --asc build/blinky.asc

# Bitstream
icepack build/blinky.asc build/blinky.bin

# Program the board
iceprog build/blinky.bin
```

### Simulation

```bash
iverilog -o build/blinky_tb.vvp rtl/blinky.v tb/blinky_tb.v
vvp build/blinky_tb.vvp
# View waveforms: gtkwave blinky_tb.vcd
```

## Expected Results

- **Synthesis**: ~30 LUTs, 24 flip-flops
- **Simulation**: `PASS: blinky testbench completed - 1000 cycles, LEDs toggled correctly`
- **On hardware**: LEDs blink at visibly different rates in a cascading pattern

## Board Pin Mapping

Uses the iCEBreaker v1.0e pinout. See `constraints/icebreaker.pcf` for full pin assignments.

<!-- Screenshot placeholder: board photo with LEDs lit -->
