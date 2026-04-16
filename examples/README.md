# OpenForge Examples

Ready-to-run example projects demonstrating the full range of OpenForge EDA capabilities.

## Examples

| Example | Kind | Description |
|---------|------|-------------|
| [fpga-blinky-icebreaker](fpga-blinky-icebreaker/) | FPGA | LED blinky pattern on the iCEBreaker board (Lattice iCE40 UP5K), full open-source FPGA flow |
| [asic-counter-sky130](asic-counter-sky130/) | ASIC | 8-bit counter through the complete RTL-to-GDS flow on SkyWater sky130 with OpenROAD |
| [pcb-breakout-board](pcb-breakout-board/) | PCB | ESP32 breakout board with voltage regulator, LEDs, and GPIO headers |
| [spice-opamp-tia](spice-opamp-tia/) | Mixed | Transimpedance amplifier using a 5-transistor OTA, simulated with ngspice |
| [formal-fifo-proof](formal-fifo-proof/) | ASIC | Formal verification proving a synchronous FIFO never overflows, using SymbiYosys |

## Quick Start

Each example has its own `openforge.yaml` and `README.md`. To run any example:

```bash
cd examples/<example-name>
openforge run
```

Or open the example folder in OpenForge Desktop via File > Open Project.

## Existing Examples

Additional examples from earlier development:

| Example | Description |
|---------|-------------|
| [simple-counter](simple-counter/) | Basic counter with sky130 (legacy config format) |
| [spi-master](spi-master/) | SPI master controller |
| [uart-tx](uart-tx/) | UART transmitter |
| [aes-sbox](aes-sbox/) | AES S-box implementation |
| [sha3-keccak](sha3-keccak/) | SHA-3 Keccak permutation |
| [ml-kem-accelerator](ml-kem-accelerator/) | ML-KEM (Kyber) hardware accelerator |
