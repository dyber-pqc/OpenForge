# Tutorial: PCB Flow -- ESP32 Breakout Board

This tutorial walks through designing a simple ESP32 breakout board in OpenForge, from schematic capture through PCB layout to Gerber file export. The board breaks out the ESP32-WROOM-32 module's GPIO pins to standard 2.54mm headers with onboard power regulation.

## Prerequisites

- OpenForge installed ([Installation guide](../getting-started/installation.md))
- KiCad libraries (installed automatically by OpenForge or via **Tools > Library Manager**)

!!! note "PCB flow maturity"
    The PCB flow in OpenForge integrates with KiCad's component libraries and file formats. Schematic capture and board layout are available in the desktop application with export to standard Gerber/Excellon formats.

## Step 1: Create the Project

=== "GUI"

    1. **File > New Project**
    2. Name: `esp32-breakout`
    3. Type: **PCB**
    4. Click **Create**

=== "CLI"

    ```bash
    openforge init esp32-breakout --type pcb
    cd esp32-breakout
    ```

## Step 2: Schematic Capture

Open the **Schematic Editor** panel. You will place components and wire them together to form the circuit.

### Bill of Materials

| Reference | Component | Value | Package |
|---|---|---|---|
| U1 | ESP32-WROOM-32 | -- | Module |
| U2 | AMS1117-3.3 | 3.3V LDO | SOT-223 |
| C1, C2 | Ceramic capacitor | 100nF | 0402 |
| C3 | Electrolytic capacitor | 10uF | 0805 |
| C4 | Ceramic capacitor | 10uF | 0805 |
| J1, J2 | Pin header | 1x20 | 2.54mm |
| J3 | USB Type-C | Power only | SMD |
| R1, R2 | Resistor | 10k | 0402 |
| SW1 | Tactile switch | Boot | 6mm |
| SW2 | Tactile switch | Reset | 6mm |

### Placing Components

=== "GUI"

    1. Open the **Component Browser** panel (right side)
    2. Search for `ESP32-WROOM-32` and drag it onto the schematic canvas
    3. Repeat for each component in the BOM
    4. Arrange components logically: power section on the left, ESP32 in the center, headers on the right

### Wiring the Schematic

Connect the following nets:

1. **Power**: USB VBUS (5V) -> AMS1117 input -> 3.3V output -> ESP32 VDD
2. **Decoupling**: C1 (100nF) near AMS1117 input, C3 (10uF) on AMS1117 output, C2 (100nF) near ESP32 power pins
3. **Boot circuit**: SW1 between GPIO0 and GND, with R1 (10k) pull-up to 3.3V
4. **Reset circuit**: SW2 between EN and GND, with R2 (10k) pull-up to 3.3V, C4 for debounce
5. **GPIO breakout**: Route all available ESP32 GPIOs to J1 and J2 pin headers
6. **Ground**: Common ground plane connecting all GND pins

=== "GUI"

    1. Click the **Wire** tool (shortcut: `W`)
    2. Click on the first pin, then click on the second pin to connect them
    3. Add power symbols (+3V3, +5V, GND) from the power symbol library
    4. Add net labels for named signals (TX, RX, SDA, SCL, etc.)

## Step 3: Electrical Rule Check

Before moving to layout, verify the schematic has no errors.

=== "GUI"

    1. Click **Run ERC** in the schematic toolbar
    2. The **ERC Panel** shows results categorized by severity
    3. Fix any errors (unconnected pins, shorted nets, missing power connections)
    4. Warnings for unconnected GPIO pins are expected on a breakout board

=== "CLI"

    ```bash
    openforge pcb erc
    ```

Common ERC issues:

- **Unconnected power pin**: Ensure every power pin has a connection or a "no connect" flag
- **Bidirectional pin conflict**: Add appropriate power flags to your power rails
- **Missing net connection**: Check that all wires are properly terminated at pins

## Step 4: Board Setup

=== "GUI"

    1. Switch to the **PCB Layout** panel
    2. Define the board outline: for this breakout, use a 50mm x 30mm rectangle
    3. Open the **Stackup Editor** to configure the layer stack:
        - 2-layer board: F.Cu, B.Cu
        - Board thickness: 1.6mm
        - Copper weight: 1 oz
    4. Set design rules:
        - Minimum trace width: 0.15mm
        - Minimum clearance: 0.15mm
        - Minimum via drill: 0.3mm

## Step 5: Component Placement

=== "GUI"

    1. All components from the schematic appear in the **PCB Layout** panel
    2. Place U1 (ESP32) in the center of the board
    3. Place U2 (AMS1117) near the USB connector at the board edge
    4. Place J1 and J2 (pin headers) along the long edges of the board
    5. Place J3 (USB-C) at one short edge
    6. Place decoupling capacitors close to their associated ICs
    7. Place SW1 and SW2 accessible near the board edge

    !!! tip "Placement tips"
        - Keep decoupling capacitors as close as possible to IC power pins
        - Place the USB connector at a board edge for easy cable access
        - Align pin headers for breadboard compatibility (2.54mm pitch, 25.4mm apart)

## Step 6: Routing

=== "GUI"

    Route traces between component pads:

    1. Route the power traces first (wider traces: 0.3mm for 3.3V and GND)
    2. Route signal traces at 0.15mm width
    3. Use the back copper layer for crossover traces
    4. Add a ground fill (copper pour) on both layers for EMI reduction

    The **Auto-Router** can handle simple boards:

    1. Click **Route > Auto-Route** in the toolbar
    2. Review the results and manually fix any suboptimal routes

=== "CLI"

    Interactive routing is a GUI operation. Use the desktop app for routing, then export:

    ```bash
    openforge pcb drc
    ```

## Step 7: Design Rule Check

=== "GUI"

    1. Click **Run DRC** in the PCB toolbar
    2. The DRC panel reports violations: clearance errors, unrouted nets, silk overlaps
    3. Click on each violation to highlight it in the layout
    4. Fix all errors before manufacturing

=== "CLI"

    ```bash
    openforge pcb drc
    ```

    ```
    [INFO] Running PCB DRC...
    [INFO] Clearance check: PASS
    [INFO] Width check: PASS
    [INFO] Unrouted nets: 0
    [INFO] DRC clean: 0 errors, 0 warnings
    ```

## Step 8: Generate Manufacturing Files

=== "GUI"

    1. **File > Export > Gerber/Drill**
    2. Select output directory
    3. Choose layers to export:
        - F.Cu, B.Cu (copper layers)
        - F.SilkS, B.SilkS (silkscreen)
        - F.Mask, B.Mask (solder mask)
        - Edge.Cuts (board outline)
    4. Click **Export**
    5. Drill files (Excellon format) are generated automatically

=== "CLI"

    ```bash
    openforge pcb gerber --output gerber/
    ```

## Output Files

```
gerber/
  esp32-breakout-F_Cu.gbr        # Front copper
  esp32-breakout-B_Cu.gbr        # Back copper
  esp32-breakout-F_SilkS.gbr     # Front silkscreen
  esp32-breakout-B_SilkS.gbr     # Back silkscreen
  esp32-breakout-F_Mask.gbr       # Front solder mask
  esp32-breakout-B_Mask.gbr       # Back solder mask
  esp32-breakout-Edge_Cuts.gbr    # Board outline
  esp32-breakout-PTH.drl          # Plated through-hole drill
  esp32-breakout-NPTH.drl         # Non-plated through-hole drill
  esp32-breakout-job.gbrjob       # Gerber job file
```

!!! tip "Ordering PCBs"
    Upload the complete `gerber/` directory as a ZIP file to your preferred PCB manufacturer (JLCPCB, PCBWay, OSH Park, etc.). Most manufacturers accept Gerber RS-274X format, which is what OpenForge generates.

## Troubleshooting

**Component not found in library**
:   Open **Tools > Library Manager** to search additional KiCad libraries or import custom footprints.

**DRC clearance violation**
:   Increase trace-to-trace clearance or reroute the offending traces. For tight areas, consider using smaller vias or moving to a 4-layer stackup.

**Unrouted nets after auto-routing**
:   The auto-router may fail on complex layouts. Manually route the remaining connections, or adjust component placement to simplify the routing.

## Next Steps

- Add a ground plane pour for better signal integrity
- Design a custom enclosure based on the board outline
- Add test points for debugging
- Explore the [PCB Stackup Editor](../panels/pcb.md) for multi-layer designs
