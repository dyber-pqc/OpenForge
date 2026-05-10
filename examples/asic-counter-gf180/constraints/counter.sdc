# SDC constraints for 8-bit counter on gf180mcuC.
# Target frequency: 50 MHz (20 ns period). 180nm is ~2x slower than 130nm.

# Primary clock definition.
create_clock -name clk -period 20.0 [get_ports clk]

# Clock uncertainty (jitter + skew budget).
set_clock_uncertainty 0.5 [get_clocks clk]

# Clock transition (slew).
set_clock_transition 0.30 [get_clocks clk]

# Input delays relative to clock (assume 4 ns from pad to flop on 180nm).
set_input_delay  -clock clk -max 4.0 [get_ports rst]
set_input_delay  -clock clk -min 1.0 [get_ports rst]
set_input_delay  -clock clk -max 4.0 [get_ports en]
set_input_delay  -clock clk -min 1.0 [get_ports en]

# Output delays (assume 4 ns from flop to pad).
set_output_delay -clock clk -max 4.0 [get_ports count*]
set_output_delay -clock clk -min 1.0 [get_ports count*]
set_output_delay -clock clk -max 4.0 [get_ports overflow]
set_output_delay -clock clk -min 1.0 [get_ports overflow]

# Driving cell for inputs (gf180mcu 7t 5V std cells).
set_driving_cell -lib_cell gf180mcu_fd_sc_mcu7t5v0__inv_2 -pin Y [all_inputs]

# Output load (typical pad load ~10 fF on 180 nm).
set_load 0.010 [all_outputs]
