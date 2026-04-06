# OpenForge Floorplan -- sky130
read_lef sky130_fd_sc_hd.tlef
read_lef sky130_fd_sc_hd_merged.lef
read_liberty H:\openforge\share\pdk\sky130\lib\sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog H:\openforge\examples\simple-counter\synth_build\netlist.v
link_design counter
read_sdc H:\openforge\examples\simple-counter\constraints\timing.sdc

initialize_floorplan -die_area {0.000 0.000 140.300 141.440} -core_area {20.240 21.760 120.060 119.680} -site unithd
make_tracks
place_pins -hor_layer met3 -ver_layer met2

write_def H:\openforge\examples\simple-counter\openlane_build\floorplan\floorplan.def
report_design_area
exit
