//! Minimal Yosys-style gate-level Verilog parser for LVS.
//!
//! Recognised constructs:
//!   * `module name (port, port, ...);`
//!   * `input`, `output`, `inout`, `wire` declarations (single-bit or
//!     `[hi:lo]` bus). Buses are expanded into individual nets named
//!     `name[index]`.
//!   * Cell instantiations of the form
//!     `cell_type inst_name ( .pin(net), ... );`
//!     where `net` may be a single identifier, a bit-select `id[i]`, or
//!     a literal `1'b0` / `1'b1` (mapped to constants `__TIE0__` /
//!     `__TIE1__`).
//!
//! Anything else is skipped tolerantly. The output is a `Subckt`
//! pin-aligned to the LEF macro pin order, exactly like the layout
//! extractor produces, so the two graphs are directly comparable.

pub mod parser;

pub use parser::{parse_verilog_file, parse_verilog_str, VerilogModule};

use crate::error::{LvsError, Result};
use crate::layout_extract::LefLibrary;
use crate::spice::{Device, Subckt};
use std::collections::HashMap;

/// Convert a parsed `VerilogModule` into a LVS-ready `Subckt`, using the
/// LEF library to canonicalise instance pin order.
pub fn to_subckt(m: &VerilogModule, lef: &LefLibrary) -> Result<Subckt> {
    let mut devices: Vec<Device> = Vec::with_capacity(m.instances.len());
    let mut dangling: usize = 0;
    for inst in &m.instances {
        let macro_def = lef.find(&inst.cell).ok_or_else(|| {
            LvsError::Graph(format!(
                "instance '{}' uses cell '{}' which is not in the provided LEF",
                inst.name, inst.cell
            ))
        })?;
        let mut nodes: Vec<String> = Vec::with_capacity(macro_def.pins.len());
        for pin in &macro_def.pins {
            match inst.connections.get(&pin.name) {
                Some(net) => nodes.push(net.clone()),
                None => {
                    if is_power_pin(&pin.name) {
                        nodes.push(format!("__PWR__{}", pin.name));
                    } else {
                        dangling += 1;
                        nodes.push(format!("__DANGLING__{dangling}"));
                    }
                }
            }
        }
        devices.push(Device::SubcktInst {
            name: inst.name.clone(),
            nodes,
            subckt: inst.cell.clone(),
            params: HashMap::new(),
        });
    }

    Ok(Subckt {
        name: m.name.clone(),
        ports: m.ports.clone(),
        devices,
        subckts: Vec::new(),
    })
}

fn is_power_pin(name: &str) -> bool {
    matches!(
        name,
        "VPWR" | "VGND" | "VPB" | "VNB" | "VDD" | "VSS" | "VDDPE" | "VSSE"
    )
}
