# AES S-Box timing constraints
# Combinational design - constrain max delay through the S-Box
create_clock -name virtual_clk -period 10.0

# Input/output delays relative to virtual clock
set_input_delay -clock virtual_clk 0.0 [get_ports data_in]
set_output_delay -clock virtual_clk 0.0 [get_ports data_out]

# Max combinational delay through the S-Box lookup
set_max_delay 5.0 -from [get_ports data_in] -to [get_ports data_out]
