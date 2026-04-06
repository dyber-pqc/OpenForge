# OpenROAD P&R script for simple counter on SKY130
read_lef /mnt/h/openforge/share/pdk/sky130/lef/sky130hd.tlef
read_lef /mnt/h/openforge/share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef
read_liberty /mnt/h/openforge/share/pdk/sky130/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /mnt/h/openforge/examples/simple-counter/synth_build/netlist.v
link_design counter

# Read constraints
read_sdc /mnt/h/openforge/examples/simple-counter/constraints/timing.sdc

# Floorplan: auto-size with 50% utilization
initialize_floorplan -utilization 50 -aspect_ratio 1 -core_space 2 -site unithd

# Make tracks for routing
make_tracks

# Place pins on available metal layers
place_pins -hor_layers met1 -ver_layers met2

# Global placement
global_placement -density 0.6

# Detailed placement
detailed_placement
improve_placement

# Report
report_design_area
report_checks -path_delay max

# Write DEF output
write_def /mnt/h/openforge/examples/simple-counter/pnr_build/counter_placed.def

puts "\n=== P&R Complete ==="
puts "Design: counter"
puts "PDK: SKY130"

exit
