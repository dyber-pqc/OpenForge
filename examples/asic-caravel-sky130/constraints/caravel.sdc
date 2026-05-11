# SDC constraints for Caravel user_proj_example
# Target frequency: 40 MHz (25 ns period). 40 MHz wb_clk_i is the standard
# Caravel management SoC clock — keeping the user project at the same domain
# avoids any CDC needs for the Wishbone interface.

create_clock -name wb_clk_i -period 25.0 [get_ports wb_clk_i]

# Clock uncertainty (jitter + skew budget)
set_clock_uncertainty 0.50 [get_clocks wb_clk_i]

# Clock transition (slew)
set_clock_transition 0.20 [get_clocks wb_clk_i]

# Conservative I/O delays: ~30% of period in / out.
# Note: OpenROAD's SDC parser does not support remove_from_collection; iterate
# explicitly so we don't constrain the clock port itself.
foreach port [all_inputs] {
    if {[get_property $port full_name] ne "wb_clk_i"} {
        set_input_delay -clock wb_clk_i -max 7.5 $port
        set_input_delay -clock wb_clk_i -min 1.0 $port
    }
}
set_output_delay -clock wb_clk_i -max 7.5 [all_outputs]
set_output_delay -clock wb_clk_i -min 1.0 [all_outputs]

# Driving cell for inputs
set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 -pin Y [all_inputs]

# Output load (typical pad load ~5 fF)
set_load 0.005 [all_outputs]
