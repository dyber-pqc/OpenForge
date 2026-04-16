read_liberty /pdk/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /work/synth_build/netlist.v
link_design counter
read_sdc /work/constraints/timing.sdc
report_power
exit
