# Minimal Netgen LVS setup file for sky130A. Real setup files include many
# more equate/permute lines; this fixture exercises every directive parsed
# by openforge.integrations.netgen.parse_netgen_setup.

# MOSFET source/drain port permutations.
permute "sky130_fd_pr__nfet_01v8" 1 3
permute "sky130_fd_pr__pfet_01v8" 1 3

# Treat layout-extracted device names as their schematic equivalents.
equate elements sky130_fd_pr__nfet_01v8 nfet_01v8
equate elements sky130_fd_pr__pfet_01v8 pfet_01v8

# Equate two MOSFET classes (alternate form).
equate classes {sky130_fd_pr__nfet_g5v0d10v5 nfet_g5v0d10v5}

# Drop phantom devices that Magic extracts but the schematic doesn't have.
ignore class sky130_fd_pr__cap_var_lvt

# Property handling.
property sky130_fd_pr__nfet_01v8 w tolerance 0.001
property sky130_fd_pr__pfet_01v8 as ignore
