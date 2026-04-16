# PCB Panel Group

The PCB panels provide schematic capture, board layout, component management, design rule checking, and manufacturing file export for printed circuit board design.

## PCB Designer Panel

The main PCB layout environment with a multi-layer board editor.

### Features

- **Multi-layer support**: 2-layer through 16-layer stackup configurations
- **Interactive routing**: Manual trace routing with DRC-aware snap and push
- **Auto-router**: Automated trace routing for simple to moderate board complexity
- **Copper pour**: Ground and power plane fills with thermal relief
- **Design rules**: Configurable minimum trace width, clearance, via sizes
- **3D preview**: Board visualization with component models

### Board Setup

| Parameter | Description | Typical |
|---|---|---|
| Board outline | PCB shape and dimensions | Rectangular |
| Layer count | Number of copper layers | 2 or 4 |
| Board thickness | Overall PCB thickness | 1.6 mm |
| Copper weight | Copper thickness | 1 oz (35 um) |
| Min trace width | Minimum routing width | 0.15 mm |
| Min clearance | Minimum gap between conductors | 0.15 mm |
| Min via drill | Minimum via hole diameter | 0.3 mm |

## PCB Stackup Editor

Configure the PCB layer stack for multi-layer boards.

### Features

- Visual layer stack representation
- Dielectric material selection (FR4, Rogers, polyimide)
- Impedance calculator for controlled-impedance traces
- Prepreg and core thickness configuration
- Standard stackup templates (2L, 4L, 6L)

### Example 4-Layer Stackup

| Layer | Type | Thickness | Material |
|---|---|---|---|
| F.Cu | Signal | 35 um | Copper |
| Prepreg | Dielectric | 200 um | FR4 |
| In1.Cu | Ground plane | 35 um | Copper |
| Core | Dielectric | 1.0 mm | FR4 |
| In2.Cu | Power plane | 35 um | Copper |
| Prepreg | Dielectric | 200 um | FR4 |
| B.Cu | Signal | 35 um | Copper |

## PCB Router

Interactive and automated routing engine.

### Manual Routing

1. Select the **Route** tool from the toolbar (shortcut: `X`)
2. Click a source pad to begin routing
3. Click to place corners
4. The router highlights DRC violations in real time
5. Double-click or press `Enter` to finish the trace

### Auto-Routing

1. Click **Route > Auto-Route** in the toolbar
2. Select which nets to route (all, unrouted only, or selected nets)
3. The auto-router processes nets in priority order (power first, then signals)
4. Review results and manually fix any suboptimal routes

### Routing Options

| Option | Description |
|---|---|
| Trace width | Width for the current route |
| Via type | Through-hole, blind, buried |
| Net class | Apply pre-defined width/clearance rules |
| Differential pair | Route differential signal pairs with matched length |

## Component Browser

Search and place components from library databases.

### Features

- Search by keyword, part number, or category
- Preview component symbol (schematic) and footprint (PCB)
- View datasheet links
- Compatible with KiCad component libraries
- Custom library import

## ERC Panel (Electrical Rule Check)

Validates the schematic for electrical errors before layout.

### Check Categories

| Category | Examples |
|---|---|
| Connectivity | Unconnected pins, floating nets |
| Power | Missing power connections, shorted rails |
| Pin conflicts | Output-to-output, bidirectional conflicts |
| Hierarchy | Missing hierarchical connections |

### Usage

1. Click **Run ERC** in the schematic toolbar
2. Errors appear in a categorized list
3. Click an error to highlight the affected schematic elements
4. Fix issues and re-run until clean

## DRC Panel (Design Rule Check)

Validates the PCB layout against manufacturing rules.

### Check Categories

| Category | Description |
|---|---|
| Clearance | Copper-to-copper, copper-to-edge spacing |
| Width | Minimum trace width violations |
| Via | Drill size, annular ring |
| Silk | Silkscreen overlap with pads |
| Unrouted | Incomplete connections |
| Courtyard | Component courtyard overlaps |

## Manufacturing Export

Export files for PCB fabrication:

### Gerber Files (RS-274X)

| Layer | File Extension | Description |
|---|---|---|
| F.Cu | `.gbr` | Front copper |
| B.Cu | `.gbr` | Back copper |
| F.SilkS | `.gbr` | Front silkscreen |
| B.SilkS | `.gbr` | Back silkscreen |
| F.Mask | `.gbr` | Front solder mask |
| B.Mask | `.gbr` | Back solder mask |
| Edge.Cuts | `.gbr` | Board outline |

### Drill Files (Excellon)

| File | Description |
|---|---|
| PTH.drl | Plated through-holes |
| NPTH.drl | Non-plated through-holes |

### Additional Exports

- **BOM (Bill of Materials)** -- CSV with reference designators, values, and footprints
- **Pick and Place** -- Component positions for automated assembly
- **IPC-D-356 Netlist** -- Electrical test netlist for bare board testing

### CLI

```bash
openforge pcb gerber --output gerber/
openforge pcb bom --output bom.csv
openforge pcb drc
openforge pcb erc
```
