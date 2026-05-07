//! Layout extraction: build an LVS-comparable `Subckt` directly from a routed
//! DEF + LEF library, treating each standard cell as an opaque primitive.
//!
//! The schematic side (gate-level Verilog or X-style SPICE) instantiates the
//! same cells as primitives, so the resulting connectivity graphs are
//! isomorphic when the routing matches the netlist.

pub mod connectivity;
pub mod def_reader;
pub mod lef_reader;

pub use connectivity::extract_subckt;
pub use def_reader::{parse_def_file, parse_def_str, DefData};
pub use lef_reader::{parse_lef_file, parse_lef_str, LefLibrary, LefMacro};
