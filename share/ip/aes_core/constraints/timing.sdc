# OpenForge EDA - AES-128 Core Timing Constraints
# Target: sky130 PDK, 50 MHz operation

# Primary clock
create_clock -name clk -period 20.0 [get_ports clk]

# Input delays (external setup/hold)
set_input_delay -clock clk -max 5.0 [get_ports {s_axi_*}]
set_input_delay -clock clk -min 1.0 [get_ports {s_axi_*}]
set_input_delay -clock clk -max 2.0 [get_ports rst_n]

# Output delays
set_output_delay -clock clk -max 5.0 [get_ports {s_axi_*}]

# False paths on reset
set_false_path -from [get_ports rst_n]

# Max fanout for S-Box outputs (critical path)
set_max_fanout 16 [get_ports clk]
