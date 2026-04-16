lef read /mnt/h/openforge/share/pdk/sky130/lef/sky130hd.tlef
lef read /mnt/h/openforge/share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef
def read /mnt/h/openforge/examples/simple-counter/pnr_build/counter_placed.def
load counter
select top cell
drc check
set drc_count [drc listall count]
puts "DRC_VIOLATIONS: $drc_count"
drc listall why /mnt/h/openforge/examples/simple-counter/pnr_build/drc_magic_report.txt
quit -noprompt
