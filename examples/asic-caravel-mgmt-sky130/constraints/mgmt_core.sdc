# SDC for Caravel mgmt_core (full Caravel management SoC) on sky130_fd_sc_hd.
# 50 MHz core clock — Caravel ships at varied rates (10-50 MHz typical mgmt
# operating point); 50 MHz is realistic and matches the picorv32 example.
# Period: 20 ns.

create_clock -name core_clk -period 20.0 [get_ports core_clk]

set_clock_uncertainty 0.50 [get_clocks core_clk]
set_clock_transition  0.20 [get_clocks core_clk]

# I/O delay budget: 30% of period in/out. Iterate explicitly so we don't
# constrain the clock port itself — OpenROAD's SDC parser does NOT support
# `remove_from_collection`. Same workaround pattern as picorv32.sdc.
foreach port [all_inputs] {
    if {[get_property $port full_name] ne "core_clk"} {
        set_input_delay -clock core_clk -max 6.0 $port
        set_input_delay -clock core_clk -min 1.0 $port
    }
}
set_output_delay -clock core_clk -max 6.0 [all_outputs]
set_output_delay -clock core_clk -min 1.0 [all_outputs]

set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 -pin Y [all_inputs]
set_load 0.005 [all_outputs]
