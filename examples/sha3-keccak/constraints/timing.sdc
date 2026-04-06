# SHA3 Keccak round timing constraints
# Combinational design - single clock cycle for one round
create_clock -name clk -period 20.0

# Input/output delays
set_input_delay -clock clk 1.0 [get_ports state_in]
set_input_delay -clock clk 1.0 [get_ports round_constant]
set_output_delay -clock clk 1.0 [get_ports state_out]
