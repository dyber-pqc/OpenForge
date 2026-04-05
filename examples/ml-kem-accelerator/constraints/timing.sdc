# ML-KEM Accelerator Timing Constraints
# Target: 200 MHz (5ns period) on SKY130

# Clock definition
create_clock -name clk -period 5.0 [get_ports clk]

# Clock uncertainty (jitter + skew)
set_clock_uncertainty 0.2 [get_clocks clk]

# Input delays (assume 2ns from external register)
set_input_delay -clock clk 2.0 [get_ports {cmd cmd_valid data_in data_in_valid rng_data rng_valid zeroize}]

# Output delays (assume 2ns to external register)
set_output_delay -clock clk 2.0 [get_ports {cmd_ready done error data_out data_out_valid data_in_ready rng_ready self_test_pass health_test_fail}]

# False paths: reset and zeroize are asynchronous
set_false_path -from [get_ports rst_n]
set_false_path -from [get_ports zeroize]

# Multicycle path for NTT butterfly (2-cycle pipeline)
# set_multicycle_path 2 -setup -from [get_pins u_ntt_butterfly/a_in*] -to [get_pins u_ntt_butterfly/a_out*]
# set_multicycle_path 2 -setup -from [get_pins u_ntt_butterfly/b_in*] -to [get_pins u_ntt_butterfly/b_out*]
