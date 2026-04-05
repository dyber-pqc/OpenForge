# Timing constraints for simple counter
create_clock -name clk -period 10.0 [get_ports clk]

set_input_delay -clock clk 2.0 [get_ports {rst_n enable}]
set_output_delay -clock clk 2.0 [get_ports {count overflow}]
