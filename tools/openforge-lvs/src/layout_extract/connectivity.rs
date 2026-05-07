//! Build a `Subckt` from DEF + LEF: each component becomes a `SubcktInst`
//! whose `subckt` is the LEF macro name. The order of pins on the
//! `SubcktInst` matches the order of pins declared in the LEF macro, so
//! the LVS graph builder labels edges as `p0`, `p1`, ... consistently
//! between layout and schematic (the Verilog parser does the same).

use super::{DefData, LefLibrary};
use crate::error::{LvsError, Result};
use crate::spice::{Device, Subckt};
use std::collections::HashMap;

/// Extract the top-level subckt from a DEF + LEF pair.
///
/// `top` selects the design name (must match `DESIGN <name>` in the DEF).
pub fn extract_subckt(def: &DefData, lef: &LefLibrary, top: &str) -> Result<Subckt> {
    if def.design != top {
        return Err(LvsError::Graph(format!(
            "DEF design '{}' does not match requested top '{}'",
            def.design, top
        )));
    }

    // 1. Determine top-level ports from PINS.
    let ports: Vec<String> = def.pins.iter().map(|p| p.name.clone()).collect();

    // 2. Build a quick lookup of net-name -> connections, and remember
    //    which PIN each top-level pin is wired to (PIN ... + NET <net>).
    //    For DEF connections, the marker `(PIN <pinname>)` denotes a
    //    top-level port connection.

    // Build connections per (instance, pin_index). For each net, we walk its
    // connection list and emit edges (instance, lef_pin_index, net_name).
    //
    // Output devices are SubcktInst with `nodes[i]` = net connected to the
    // i-th LEF pin. Unconnected pins get a synthetic dangling net name to
    // preserve graph structure.

    // Map: (instance_name, pin_name) -> net_name
    let mut inst_pin_to_net: HashMap<(String, String), String> = HashMap::new();
    for net in &def.nets {
        for (inst, pin) in &net.connections {
            if inst == "PIN" {
                // Top-level port connection: pin == port name. The port is
                // already in `ports`; nothing to do for instance map.
                continue;
            }
            inst_pin_to_net.insert((inst.clone(), pin.clone()), net.name.clone());
        }
    }

    // 3. For each component, look up its LEF macro to get the canonical
    //    pin order, then emit a SubcktInst.
    let mut devices: Vec<Device> = Vec::with_capacity(def.components.len());
    let mut dangling_counter: usize = 0;

    for comp in &def.components {
        let macro_def = lef.find(&comp.macro_name).ok_or_else(|| {
            LvsError::Graph(format!(
                "component '{}' uses macro '{}' which is not in the provided LEF",
                comp.name, comp.macro_name
            ))
        })?;
        // Skip purely physical-only cells (no signal pins) if needed; the
        // LEF for sky130 power-only cells (decap, fill, tap) has no signal
        // pins, but we still emit them as zero-pin devices so the device
        // counts include them. The schematic should also include them if
        // it does, otherwise the histograms will diverge — which is the
        // correct LVS behaviour.
        let mut nodes: Vec<String> = Vec::with_capacity(macro_def.pins.len());
        for pin in &macro_def.pins {
            // Power pins (VPWR/VGND/VPB/VNB) are typically handled via
            // SPECIALNETS in DEF and are not in instance NET connections.
            // Skip pins whose direction is not SIGNAL/INPUT/OUTPUT/INOUT
            // when there's no NET connection — represent them as a shared
            // synthetic net per pin name so layout/schematic both treat
            // them uniformly. For LVS correctness, the schematic-side
            // Verilog would also omit power pins.
            let key = (comp.name.clone(), pin.name.clone());
            let net = match inst_pin_to_net.get(&key) {
                Some(n) => n.clone(),
                None => {
                    if is_power_pin(&pin.name) {
                        // Use a stable synthetic name shared across all
                        // instances so both sides see the same power net.
                        format!("__PWR__{}", pin.name)
                    } else {
                        dangling_counter += 1;
                        format!("__DANGLING__{dangling_counter}")
                    }
                }
            };
            nodes.push(net);
        }
        devices.push(Device::SubcktInst {
            name: comp.name.clone(),
            nodes,
            subckt: comp.macro_name.clone(),
            params: HashMap::new(),
        });
    }

    Ok(Subckt {
        name: top.to_string(),
        ports,
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
