# UART Transmitter timing constraints
# Target: 100 MHz system clock
create_clock -name clk -period 10.0 [get_ports clk]

# Input delays
set_input_delay -clock clk 2.0 [get_ports {rst_n tx_data tx_valid}]

# Output delays
set_output_delay -clock clk 2.0 [get_ports {tx_out tx_ready tx_active}]
