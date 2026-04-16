# SDC constraints for 8-bit counter
# Target frequency: 100 MHz (10 ns period)

# Primary clock definition
create_clock -name clk -period 10.0 [get_ports clk]

# Clock uncertainty (jitter + skew budget)
set_clock_uncertainty 0.25 [get_clocks clk]

# Clock transition (slew)
set_clock_transition 0.15 [get_clocks clk]

# Input delays relative to clock (assume 2 ns from pad to flop)
set_input_delay  -clock clk -max 2.0 [get_ports rst]
set_input_delay  -clock clk -min 0.5 [get_ports rst]
set_input_delay  -clock clk -max 2.0 [get_ports en]
set_input_delay  -clock clk -min 0.5 [get_ports en]

# Output delays (assume 2 ns from flop to pad)
set_output_delay -clock clk -max 2.0 [get_ports count*]
set_output_delay -clock clk -min 0.5 [get_ports count*]
set_output_delay -clock clk -max 2.0 [get_ports overflow]
set_output_delay -clock clk -min 0.5 [get_ports overflow]

# Driving cell for inputs
set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 -pin Y [all_inputs]

# Output load (typical pad load ~5 fF)
set_load 0.005 [all_outputs]
