# SDC constraints for PicoRV32 RISC-V CPU
# Target frequency: 50 MHz (20 ns period) - relaxed starting point for sky130
# unithd. PicoRV32 datasheet claims 250 MHz on Xilinx 7-series; sky130 std-cell
# typically lands in the 50-100 MHz range without aggressive retiming.

create_clock -name clk -period 20.0 [get_ports clk]

# Clock uncertainty (jitter + skew budget)
set_clock_uncertainty 0.50 [get_clocks clk]

# Clock transition (slew)
set_clock_transition 0.20 [get_clocks clk]

# Conservative I/O delays: 30% of period in / 30% of period out
# Note: OpenROAD's SDC parser does not support remove_from_collection; iterate
# explicitly so we don't constrain the clock port itself.
foreach port [all_inputs] {
    if {[get_property $port full_name] ne "clk"} {
        set_input_delay -clock clk -max 6.0 $port
        set_input_delay -clock clk -min 1.0 $port
    }
}
set_output_delay -clock clk -max 6.0 [all_outputs]
set_output_delay -clock clk -min 1.0 [all_outputs]

# Driving cell for inputs
set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 -pin Y [all_inputs]

# Output load (typical pad load ~5 fF)
set_load 0.005 [all_outputs]
