# run_flow.tcl - OpenROAD Tcl script for full ASIC P&R flow
#
# Usage:
#   openroad -exit scripts/run_flow.tcl
#
# Requires:
#   - PDK_ROOT environment variable pointing to SkyWater PDK installation
#   - Synthesized netlist in build/counter_synth.v (from Yosys)
#
# This script can be invoked standalone outside of OpenForge.
#-----------------------------------------------------------------------------

set design_name "counter"
set pdk_root $::env(PDK_ROOT)
set lib_dir "$pdk_root/sky130A/libs.ref/sky130_fd_sc_hd"
set tech_dir "$pdk_root/sky130A/libs.tech/openlane/sky130_fd_sc_hd"
set build_dir "build"

file mkdir $build_dir

# ----- Read technology -------------------------------------------------------
read_liberty "$lib_dir/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
read_lef "$tech_dir/lef/sky130_fd_sc_hd.tlef"
read_lef "$tech_dir/lef/sky130_fd_sc_hd.lef"

# ----- Read design -----------------------------------------------------------
read_verilog "$build_dir/counter_synth.v"
link_design $design_name

# ----- Read constraints ------------------------------------------------------
read_sdc "constraints/counter.sdc"

# ----- Floorplan -------------------------------------------------------------
initialize_floorplan \
    -die_area  "0 0 100 100" \
    -core_area "10 10 90 90" \
    -site      unithd

source "$tech_dir/tracks.info"

# Power grid
add_global_connection -net VDD -pin_pattern "^VPWR$" -power
add_global_connection -net VSS -pin_pattern "^VGND$" -ground
add_global_connection -net VDD -pin_pattern "^VPB$"  -power
add_global_connection -net VSS -pin_pattern "^VNB$"  -ground

set_voltage_domain -power VDD -ground VSS

define_pdn_grid -name "core_grid" -pins "met4 met5"
add_pdn_stripe -grid "core_grid" -layer met1 -width 0.48 -followpins
add_pdn_stripe -grid "core_grid" -layer met4 -width 1.6 -pitch 27.14 -offset 13.57
add_pdn_stripe -grid "core_grid" -layer met5 -width 1.6 -pitch 27.2 -offset 13.6
add_pdn_connect -grid "core_grid" -layers "met1 met4"
add_pdn_connect -grid "core_grid" -layers "met4 met5"
pdngen

# ----- Placement -------------------------------------------------------------
global_placement -density 0.6

detailed_placement
check_placement

# ----- Clock Tree Synthesis --------------------------------------------------
set_wire_rc -clock \
    -layer "met3"

clock_tree_synthesis \
    -buf_list "sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_16" \
    -root_buf "sky130_fd_sc_hd__clkbuf_16"

repair_clock_nets

detailed_placement
check_placement

# ----- Routing ---------------------------------------------------------------
set_global_routing_layer_adjustment met2-met5 0.5
set_routing_layers -signal met1-met5 -clock met3-met5

global_route

detailed_route

# ----- Write outputs ---------------------------------------------------------
write_def "$build_dir/${design_name}_routed.def"
write_verilog "$build_dir/${design_name}_routed.v"

# ----- Timing report --------------------------------------------------------
report_checks -path_delay min_max -fields {slew cap input_pins nets} \
    -format full_clock_expanded \
    > "$build_dir/timing_report.txt"

report_tns > "$build_dir/tns_report.txt"
report_wns > "$build_dir/wns_report.txt"

puts "Flow complete. Outputs in $build_dir/"
exit
