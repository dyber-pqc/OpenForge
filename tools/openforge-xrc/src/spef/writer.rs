//! IEEE-1481 SPEF writer.
//!
//! v0.2 improvements:
//! - `*PORTS` section listing top-level pins.
//! - Hierarchical net / instance names preserved (the divider character is
//!   `/`, matching the DEF and SPEF conventions for `top/sub/leaf`).
//! - Two-space indented body sections for readability per IEEE-1481 style.

use crate::extract::ExtractionResult;
use std::collections::BTreeSet;
use std::fmt::Write;

/// Render the extraction result as a SPEF string.
pub fn write_spef(result: &ExtractionResult) -> String {
    let mut s = String::new();
    let _ = writeln!(s, "*SPEF \"IEEE 1481-1998\"");
    let _ = writeln!(s, "*DESIGN \"{}\"", result.design);
    let _ = writeln!(s, "*DATE \"unknown\"");
    let _ = writeln!(s, "*VENDOR \"OpenForge xRC v0.2.0\"");
    let _ = writeln!(s, "*PROGRAM \"openforge-xrc\"");
    let _ = writeln!(s, "*VERSION \"0.2.0\"");
    let _ = writeln!(s, "*DESIGN_FLOW \"EXTERNAL_LOADS\"");
    let _ = writeln!(s, "*DIVIDER /");
    let _ = writeln!(s, "*DELIMITER :");
    let _ = writeln!(s, "*BUS_DELIMITER [ ]");
    let _ = writeln!(s, "*T_UNIT 1 PS");
    let _ = writeln!(s, "*C_UNIT 1 FF");
    let _ = writeln!(s, "*R_UNIT 1 OHM");
    let _ = writeln!(s, "*L_UNIT 1 NH");
    s.push('\n');

    // *PORTS — collect all top-level pins (connections with instance == "PIN").
    let mut ports: BTreeSet<String> = BTreeSet::new();
    for net in &result.nets {
        for (inst, pin) in &net.connections {
            if inst == "PIN" {
                ports.insert(pin.clone());
            }
        }
    }
    if !ports.is_empty() {
        let _ = writeln!(s, "*PORTS");
        for p in &ports {
            // Direction unknown from DEF alone; mark all ports as bidirect.
            let _ = writeln!(s, "{} B", p);
        }
        s.push('\n');
    }

    for net in &result.nets {
        // Net name retains hierarchical separators ('/') unchanged.
        let _ = writeln!(s, "*D_NET {} {:.6}", net.net_name, net.total_cap_ff);
        let _ = writeln!(s, "*CONN");
        for (inst, pin) in &net.connections {
            if inst == "PIN" {
                let _ = writeln!(s, "  *P {} B", pin);
            } else {
                let _ = writeln!(s, "  *I {}:{} I", inst, pin);
            }
        }

        if !net.segments.is_empty() || !net.coupling.is_empty() {
            let _ = writeln!(s, "*CAP");
            let mut idx = 1usize;
            for seg in &net.segments {
                let _ = writeln!(s, "  {} {} {:.6}", idx, seg.from_node, seg.c_ff);
                idx += 1;
            }
            for cc in &net.coupling {
                let _ = writeln!(
                    s,
                    "  {} {} {} {:.6}",
                    idx, net.net_name, cc.neighbor_net, cc.c_ff
                );
                idx += 1;
            }
        }

        if !net.segments.is_empty() {
            let _ = writeln!(s, "*RES");
            for (i, seg) in net.segments.iter().enumerate() {
                let _ = writeln!(
                    s,
                    "  {} {} {} {:.6}",
                    i + 1,
                    seg.from_node,
                    seg.to_node,
                    seg.r_ohm
                );
            }
        }
        let _ = writeln!(s, "*END");
        s.push('\n');
    }

    s
}
