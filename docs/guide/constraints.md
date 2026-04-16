# Constraint Editor

The Constraint Editor provides a dedicated environment for writing and managing timing constraints (SDC), pin constraints (PCF/XDC), and design rule constraints. It offers syntax highlighting, command templates, and inline validation.

## Constraint Types

### SDC (Synopsys Design Constraints)

SDC is the industry-standard format for timing constraints, used for both ASIC and FPGA designs.

```tcl
# Clock definition
create_clock -name clk -period 10.0 [get_ports clk]

# Generated clock (e.g., PLL output)
create_generated_clock -name pll_clk -source [get_ports clk] \
    -divide_by 2 [get_pins pll/clk_out]

# I/O delays
set_input_delay  -clock clk 2.0 [get_ports {data_in[*]}]
set_output_delay -clock clk 2.0 [get_ports {data_out[*]}]

# False paths (paths that should not be timed)
set_false_path -from [get_clocks clk_a] -to [get_clocks clk_b]

# Multicycle paths
set_multicycle_path 2 -setup -from [get_pins reg_a/Q] -to [get_pins reg_b/D]

# Max delay constraints
set_max_delay 5.0 -from [get_ports async_in] -to [get_pins sync_reg/D]
```

### PCF (Physical Constraints File)

PCF format is used for Lattice iCE40 FPGA pin assignments:

```
set_io clk 35
set_io led_r 11
set_io led_g 37
set_io spi_mosi 14
set_io spi_miso 17
set_io spi_sck 15
set_io spi_cs_n 16
```

### XDC (Xilinx Design Constraints)

XDC format combines timing and pin constraints for Xilinx FPGAs:

```tcl
# Pin assignments
set_property PACKAGE_PIN W5 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]

# Clock constraint
create_clock -period 10.0 -name sys_clk [get_ports clk]
```

## Editor Features

### Syntax Highlighting

The editor highlights constraint keywords, clock names, port references, and numeric values:

| Token | Color | Examples |
|---|---|---|
| Commands | Blue | `create_clock`, `set_input_delay` |
| Options | Teal | `-name`, `-period`, `-clock` |
| Ports/pins | Green | `[get_ports clk]`, `[get_pins reg/D]` |
| Numbers | Peach | `10.0`, `2.5` |
| Comments | Gray | `# timing constraints` |

### Command Templates

Right-click in the editor or use the command palette to insert constraint templates:

| Template | Inserts |
|---|---|
| Clock | `create_clock -name <name> -period <period> [get_ports <port>]` |
| Input delay | `set_input_delay -clock <clk> <delay> [get_ports <ports>]` |
| Output delay | `set_output_delay -clock <clk> <delay> [get_ports <ports>]` |
| False path | `set_false_path -from <source> -to <dest>` |
| Max delay | `set_max_delay <value> -from <source> -to <dest>` |

### Validation

The editor validates constraints as you type:

- **Missing ports**: Warns if a referenced port does not exist in the design
- **Invalid syntax**: Highlights TCL syntax errors
- **Conflicting constraints**: Flags contradictory timing requirements

## TCL Console Integration

All constraint commands can also be entered interactively in the TCL console:

```tcl
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay -clock clk 2.0 [get_ports {rst_n enable}]
set_output_delay -clock clk 2.0 [get_ports {count overflow}]
report_clocks
```

The `report_clocks` command displays all defined clocks and their properties.

## Best Practices

!!! tip "Constrain all clocks"
    Every clock in your design must have a `create_clock` or `create_generated_clock` constraint. Unconstrained clocks result in unchecked timing paths.

!!! tip "Use realistic I/O delays"
    Set input and output delays based on the actual board-level timing. For a first pass, use 20-30% of the clock period as a reasonable estimate.

!!! warning "False paths must be justified"
    Only use `set_false_path` for paths that genuinely never transfer data synchronously. Incorrect false paths hide real timing violations.

## Common Constraint Patterns

### Single-Clock Design

```tcl
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay  -clock clk 2.0 [all_inputs]
set_output_delay -clock clk 2.0 [all_outputs]
```

### Multi-Clock with CDC

```tcl
create_clock -name clk_a -period 10.0 [get_ports clk_a]
create_clock -name clk_b -period 8.0 [get_ports clk_b]
set_false_path -from [get_clocks clk_a] -to [get_clocks clk_b]
set_false_path -from [get_clocks clk_b] -to [get_clocks clk_a]
```

### Asynchronous Reset

```tcl
set_false_path -from [get_ports rst_n]
```

### Generated Clock from Counter

```tcl
create_generated_clock -name clk_div2 \
    -source [get_ports clk] \
    -divide_by 2 \
    [get_pins divider/clk_out]
```
