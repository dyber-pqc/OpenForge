# PCB Breakout Board - ESP32 Development Board

A 2-layer PCB breakout board for the ESP32-WROOM-32 module with onboard voltage regulation, status LEDs, and GPIO pin headers.

## Features

- **ESP32-WROOM-32** Wi-Fi + Bluetooth MCU module (4MB flash)
- **AMS1117-3.3V** LDO regulator (5V USB input to 3.3V)
- **USB Micro-B** connector for power
- **4 status LEDs** (green power, blue/yellow/red on GPIO2/4/5) with 330 ohm current limiting resistors
- **2x 2.54mm pin headers** (2x10 each) breaking out all GPIO pins
- **Decoupling**: 2x 10uF bulk caps + 4x 100nF ceramic caps
- **Pull-ups**: 10k on EN and IO0 (for boot mode selection)
- **Board size**: 50 x 80 mm, 2-layer, 1.6mm FR4

## Bill of Materials

| Ref       | Part                   | Package   | Qty | Est. Cost |
|-----------|------------------------|-----------|-----|-----------|
| U1        | ESP32-WROOM-32         | Module    | 1   | $2.80     |
| U2        | AMS1117-3.3            | SOT-223   | 1   | $0.15     |
| J1        | USB Micro-B            | SMD       | 1   | $0.30     |
| J2, J3    | Pin Header 2x10 2.54mm | THT       | 2   | $0.20     |
| D1-D4     | LED 0805               | 0805      | 4   | $0.10     |
| R1-R4     | 330 ohm                | 0805      | 4   | $0.02     |
| R5, R6    | 10k ohm                | 0805      | 2   | $0.02     |
| C1, C2    | 10uF                   | 1206      | 2   | $0.05     |
| C3-C6     | 100nF                  | 0805      | 4   | $0.02     |
| **Total** |                        |           |     | **~$4.00** |

## Estimated Fabrication Cost (JLCPCB)

- 5 boards (2-layer, 50x80mm, 1.6mm, HASL): ~$2.00 + shipping
- SMT assembly (economic): ~$8.00 per board for SMD parts
- **Total per board**: ~$14 assembled, ~$4 components-only + hand solder

## Prerequisites

- OpenForge Desktop or CLI

## How to Run

### OpenForge CLI

```bash
cd examples/pcb-breakout-board
openforge run               # ERC + DRC + BOM + Gerber export
openforge run --stage bom   # generate BOM only
```

### OpenForge Desktop

1. File > Open Project and select this folder.
2. The Schematic Editor shows the full circuit.
3. Switch to the Layout panel to see the board with placed components.
4. Click **Run Flow** to execute ERC, DRC, and generate outputs.

## File Structure

```
pcb-breakout-board/
  openforge.yaml           # Project configuration
  schematic/breakout.json  # Schematic netlist
  board/breakout.json      # PCB layout with placements and traces
  build/                   # Generated Gerbers, BOM (after running)
```

## Design Notes

- Ground plane on bottom copper layer for good return path
- Decoupling caps placed close to ESP32 power pins
- USB connector at board edge for easy cable access
- Regulator near USB to keep high-current 5V traces short
- LEDs grouped in corner for visibility

<!-- Screenshot placeholder: 3D board render -->
