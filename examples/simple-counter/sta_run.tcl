read_liberty /pdk/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog synth_build/netlist.v
link_design counter
read_sdc constraints/timing.sdc
report_checks -path_delay max -format full
report_checks -path_delay min -format full
report_tns
report_wns
exit
