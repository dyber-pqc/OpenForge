# SDC constraints for 8-bit counter on IHP sg13g2 (130 nm SiGe BiCMOS).
# Target frequency: 75 MHz (~13.3 ns period). 130 nm IHP is faster than
# gf180 but slower than sky130 1.8 V; 75 MHz is a comfortable target.

# Primary clock definition.
create_clock -name clk -period 13.33 [get_ports clk]

# Clock uncertainty (jitter + skew budget).
set_clock_uncertainty 0.30 [get_clocks clk]

# Clock transition (slew).
set_clock_transition 0.20 [get_clocks clk]

# Input delays relative to clock (assume 2.5 ns from pad to flop on 130 nm).
set_input_delay  -clock clk -max 2.5 [get_ports rst]
set_input_delay  -clock clk -min 0.5 [get_ports rst]
set_input_delay  -clock clk -max 2.5 [get_ports en]
set_input_delay  -clock clk -min 0.5 [get_ports en]

# Output delays (assume 2.5 ns from flop to pad).
set_output_delay -clock clk -max 2.5 [get_ports count*]
set_output_delay -clock clk -min 0.5 [get_ports count*]
set_output_delay -clock clk -max 2.5 [get_ports overflow]
set_output_delay -clock clk -min 0.5 [get_ports overflow]

# Driving cell for inputs (sg13g2 std cells).
set_driving_cell -lib_cell sg13g2_inv_2 -pin Y [all_inputs]

# Output load (typical pad load ~5 fF on 130 nm).
set_load 0.005 [all_outputs]
