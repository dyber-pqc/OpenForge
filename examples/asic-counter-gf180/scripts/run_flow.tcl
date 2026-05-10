# run_flow.tcl - OpenROAD Tcl script for full ASIC P&R flow on gf180mcuC.
#
# Usage:
#   openroad -exit scripts/run_flow.tcl
#
# Requires:
#   - PDK_ROOT pointing to a gf180mcu PDK install (e.g. via volare).
#   - Synthesized netlist in build/counter_synth.v (from Yosys).
#-----------------------------------------------------------------------------

set design_name "counter"
set pdk_root $::env(PDK_ROOT)
set lib_dir  "$pdk_root/gf180mcuC/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
set tech_dir "$pdk_root/gf180mcuC/libs.tech/openlane/gf180mcu_fd_sc_mcu7t5v0"
set build_dir "build"

file mkdir $build_dir

# ----- Read technology -------------------------------------------------------
read_liberty "$lib_dir/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib"
read_lef "$tech_dir/lef/gf180mcu_5LM_1TM_9K_9t_tech.lef"
read_lef "$tech_dir/lef/gf180mcu_fd_sc_mcu7t5v0.lef"

# ----- Read design -----------------------------------------------------------
read_verilog "$build_dir/counter_synth.v"
link_design $design_name

# ----- Read constraints ------------------------------------------------------
read_sdc "constraints/counter.sdc"

# ----- Floorplan -------------------------------------------------------------
# Slightly bigger die: 180nm cells are ~2.5x larger than 130nm.
initialize_floorplan \
    -die_area  "0 0 200 200" \
    -core_area "20 20 180 180" \
    -site      GF18T

source "$tech_dir/tracks.info"

# Power grid (gf180 standard cell pin names: VDD/VSS/VPB/VNB).
add_global_connection -net VDD -pin_pattern "^VDD$" -power
add_global_connection -net VSS -pin_pattern "^VSS$" -ground
add_global_connection -net VDD -pin_pattern "^VPB$" -power
add_global_connection -net VSS -pin_pattern "^VNB$" -ground

set_voltage_domain -power VDD -ground VSS

define_pdn_grid -name "core_grid" -pins "Metal4 Metal5"
add_pdn_stripe -grid "core_grid" -layer Metal1 -width 0.56 -followpins
add_pdn_stripe -grid "core_grid" -layer Metal4 -width 1.6  -pitch 30.0 -offset 15.0
add_pdn_stripe -grid "core_grid" -layer Metal5 -width 1.6  -pitch 30.0 -offset 15.0
add_pdn_connect -grid "core_grid" -layers "Metal1 Metal4"
add_pdn_connect -grid "core_grid" -layers "Metal4 Metal5"
pdngen

# ----- Placement -------------------------------------------------------------
global_placement -density 0.55
detailed_placement
check_placement

# ----- Clock Tree Synthesis --------------------------------------------------
set_wire_rc -clock -layer "Metal3"
clock_tree_synthesis \
    -buf_list "gf180mcu_fd_sc_mcu7t5v0__clkbuf_4 gf180mcu_fd_sc_mcu7t5v0__clkbuf_8 gf180mcu_fd_sc_mcu7t5v0__clkbuf_16" \
    -root_buf "gf180mcu_fd_sc_mcu7t5v0__clkbuf_16"
repair_clock_nets
detailed_placement
check_placement

# ----- Routing ---------------------------------------------------------------
set_global_routing_layer_adjustment Metal2-Metal5 0.5
set_routing_layers -signal Metal1-Metal5 -clock Metal3-Metal5
global_route
detailed_route

# ----- Write outputs ---------------------------------------------------------
write_def "$build_dir/${design_name}_routed.def"
write_verilog "$build_dir/${design_name}_routed.v"

report_checks -path_delay min_max -fields {slew cap input_pins nets} \
    -format full_clock_expanded \
    > "$build_dir/timing_report.txt"

report_tns > "$build_dir/tns_report.txt"
report_wns > "$build_dir/wns_report.txt"

puts "Flow complete. Outputs in $build_dir/"
exit
