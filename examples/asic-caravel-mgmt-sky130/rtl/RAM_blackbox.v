// Blackbox stubs for the DFFRAM hard macros used by mgmt_core.
//
// The original RAM128.v / RAM256.v in caravel_mgmt_soc_litex are
// pre-mapped sky130 std-cell netlists (DFFRAM). They instantiate raw
// sky130_fd_sc_hd__* cells which Yosys cannot resolve during *RTL*
// synthesis without the full liberty-derived blackbox set. In a real
// Caravel sign-off these are LEF/GDS hard macros, not synthesised.
//
// For this open-source flow demo we model them as blackboxes so synthesis
// of mgmt_core's surrounding logic can complete and produce a meaningful
// cell count. The macros would be brought in at floorplan time via
// `read_lef` of the DFFRAM macro LEF and abstract placement.
//
// (* blackbox *) tells Yosys to keep the module as an opaque cell.

(* blackbox *)
module RAM128 (
    input              CLK,
    input  [3:0]       WE0,
    input              EN0,
    input  [6:0]       A0,
    input  [31:0]      Di0,
    output [31:0]      Do0
);
endmodule

(* blackbox *)
module RAM256 (
    input              CLK,
    input  [3:0]       WE0,
    input              EN0,
    input  [7:0]       A0,
    input  [31:0]      Di0,
    output [31:0]      Do0
);
endmodule
