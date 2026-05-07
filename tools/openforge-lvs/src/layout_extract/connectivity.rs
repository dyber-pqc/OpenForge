//! Build a `Subckt` from DEF + LEF: each component becomes a `SubcktInst`
//! whose `subckt` is the LEF macro name. The order of pins on the
//! `SubcktInst` matches the order of pins declared in the LEF macro, so
//! the LVS graph builder labels edges as `p0`, `p1`, ... consistently
//! between layout and schematic (the Verilog parser does the same).

use super::{DefData, LefLibrary, PhysicalFilter};
use crate::error::{LvsError, Result};
use crate::spice::{Device, Subckt};
use std::collections::{BTreeMap, HashMap};

/// Summary of physical-only cells filtered out during extraction.
#[derive(Debug, Clone, Default)]
pub struct FilteredCells {
    /// Total number of component instances dropped.
    pub total: usize,
    /// Per-LEF-macro counts (sorted, for stable display).
    pub by_macro: BTreeMap<String, usize>,
}

impl FilteredCells {
    /// Render a one-line human summary, e.g.
    /// `"filtered 4 physical-only cells: sky130_fd_sc_hd__tap_1×3, sky130_fd_sc_hd__decap_3×1"`.
    pub fn render_summary(&self) -> String {
        if self.total == 0 {
            return "filtered 0 physical-only cells".to_string();
        }
        // Sort entries by descending count, then by name for determinism.
        let mut items: Vec<(&String, &usize)> = self.by_macro.iter().collect();
        items.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
        let parts: Vec<String> = items.iter().map(|(m, c)| format!("{m}×{c}")).collect();
        format!(
            "filtered {} physical-only cells: {}",
            self.total,
            parts.join(", ")
        )
    }
}

/// Extract the top-level subckt from a DEF + LEF pair, applying the default
/// sky130 physical-only filter (tap / decap / fill / antenna diode cells).
///
/// `top` selects the design name (must match `DESIGN <name>` in the DEF).
pub fn extract_subckt(def: &DefData, lef: &LefLibrary, top: &str) -> Result<Subckt> {
    let (sub, _) = extract_subckt_with_filter(def, lef, top, &PhysicalFilter::default())?;
    Ok(sub)
}

/// Extract the top-level subckt with an explicit physical-only filter,
/// returning both the subckt and a summary of dropped cells.
pub fn extract_subckt_with_filter(
    def: &DefData,
    lef: &LefLibrary,
    top: &str,
    filter: &PhysicalFilter,
) -> Result<(Subckt, FilteredCells)> {
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
    //    pin order, then emit a SubcktInst. Skip cells whose master
    //    matches the physical-only filter (tap / decap / fill / diode by
    //    default for sky130) — these are P&R artifacts that never appear
    //    in the schematic and would otherwise cause a false-positive
    //    device-count mismatch.
    let mut devices: Vec<Device> = Vec::with_capacity(def.components.len());
    let mut dangling_counter: usize = 0;
    let mut filtered = FilteredCells::default();

    for comp in &def.components {
        if filter.matches(&comp.macro_name) {
            filtered.total += 1;
            *filtered
                .by_macro
                .entry(comp.macro_name.clone())
                .or_insert(0) += 1;
            continue;
        }
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

    Ok((
        Subckt {
            name: top.to_string(),
            ports,
            devices,
            subckts: Vec::new(),
        },
        filtered,
    ))
}

fn is_power_pin(name: &str) -> bool {
    matches!(
        name,
        "VPWR" | "VGND" | "VPB" | "VNB" | "VDD" | "VSS" | "VDDPE" | "VSSE"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_filter_matches_sky130_physical_only_cells() {
        let f = PhysicalFilter::default();
        // Should match these (P&R-only artifacts):
        for name in [
            "sky130_fd_sc_hd__tap_1",
            "sky130_fd_sc_hd__tapvpwrvgnd_1",
            "sky130_fd_sc_hd__decap_3",
            "sky130_fd_sc_hd__decap_12",
            "sky130_fd_sc_hd__fill_1",
            "sky130_fd_sc_hd__fill_2",
            "sky130_fd_sc_hd__fill_8",
            "sky130_fd_sc_hd__diode_2",
        ] {
            assert!(f.matches(name), "default filter should match {name}");
        }
        // Should NOT match real signal cells:
        for name in [
            "sky130_fd_sc_hd__inv_1",
            "sky130_fd_sc_hd__nand2_1",
            "sky130_fd_sc_hd__dfxtp_1",
            "sky130_fd_sc_hd__clkbuf_4",
            "sky130_fd_sc_hd__a21oi_1",
            "sky130_fd_sc_hd__lpflow_isobufsrc_1",
            "sky130_fd_sc_hs__tap_1", // different library -> not filtered
        ] {
            assert!(
                !f.matches(name),
                "default filter must not match signal cell {name}"
            );
        }
    }

    #[test]
    fn disabled_filter_matches_nothing() {
        let f = PhysicalFilter::disabled();
        assert!(!f.matches("sky130_fd_sc_hd__tap_1"));
        assert!(!f.matches("sky130_fd_sc_hd__inv_1"));
    }

    #[test]
    fn custom_filter_regex_compiles_and_matches() {
        let f = PhysicalFilter::new(Some(r"^FILLER_.*")).expect("valid regex");
        assert!(f.matches("FILLER_X1"));
        assert!(!f.matches("AND2X1"));
    }

    #[test]
    fn invalid_filter_regex_returns_error() {
        let res = PhysicalFilter::new(Some(r"["));
        assert!(res.is_err(), "expected regex compile error");
    }

    #[test]
    fn filtered_cells_summary_renders_descending_then_alpha() {
        let mut by_macro = BTreeMap::new();
        by_macro.insert("sky130_fd_sc_hd__tap_1".to_string(), 3);
        by_macro.insert("sky130_fd_sc_hd__decap_3".to_string(), 1);
        by_macro.insert("sky130_fd_sc_hd__fill_1".to_string(), 1);
        let f = FilteredCells { total: 5, by_macro };
        let s = f.render_summary();
        assert!(s.starts_with("filtered 5 physical-only cells: "));
        // Highest count first.
        assert!(s.contains("sky130_fd_sc_hd__tap_1×3"));
        let pos_tap = s.find("tap_1×3").unwrap();
        let pos_decap = s.find("decap_3×1").unwrap();
        assert!(pos_tap < pos_decap, "tap should appear before decap");
    }

    #[test]
    fn empty_filtered_cells_summary() {
        let f = FilteredCells::default();
        assert_eq!(f.render_summary(), "filtered 0 physical-only cells");
    }
}
