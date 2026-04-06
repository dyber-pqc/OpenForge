read_liberty /pdk/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /work/synth_build/netlist.v
link_design counter
read_sdc /work/constraints/timing.sdc
report_checks -path_delay max -fields {slew cap input_pins nets}
report_wns
report_tns
exit
