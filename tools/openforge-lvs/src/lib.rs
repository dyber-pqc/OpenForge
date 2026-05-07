//! OpenForge LVS — public library API.
//!
//! See `README.md` for current scope and roadmap.

pub mod error;
pub mod graph;
pub mod layout_extract;
pub mod matcher;
pub mod report;
pub mod spice;
pub mod verilog;

use crate::error::{LvsError, Result};
use crate::graph::{build_graph, ConnGraph, Node};
use crate::layout_extract::{parse_def_str, parse_lef_str, LefLibrary};
use crate::matcher::{run_isomorphism, MatchOutcome};
use crate::report::LvsReport;
use crate::spice::{parse_netlist, Subckt};
use crate::verilog::parse_verilog_str;

/// Parse + extract the named subckt from a SPICE source string.
pub fn load_subckt(src: &str, top: &str) -> Result<Subckt> {
    let nl = parse_netlist(src)?;
    nl.library
        .get(top)
        .cloned()
        .ok_or_else(|| LvsError::UnknownTop(top.to_string()))
}

/// High-level: run LVS on two SPICE source strings.
pub fn run_lvs(layout_src: &str, schem_src: &str, top: &str) -> Result<LvsReport> {
    let lay = load_subckt(layout_src, top)?;
    let sch = load_subckt(schem_src, top)?;

    let lay_g = build_graph(&lay)?;
    let sch_g = build_graph(&sch)?;

    Ok(build_report(&lay_g, &sch_g, top))
}

/// Run LVS where the layout is supplied as DEF + LEF and the schematic is
/// supplied as a (gate-level) Verilog source string. Both inputs reference
/// standard cells declared in the LEF library; the cells are treated as
/// opaque primitives.
pub fn run_lvs_def_verilog(
    def_src: &str,
    lef_src: &str,
    verilog_src: &str,
    top: &str,
) -> Result<LvsReport> {
    let def = parse_def_str(def_src)?;
    let lef = parse_lef_str(lef_src)?;
    let lay = layout_extract::extract_subckt(&def, &lef, top)?;

    let v = parse_verilog_str(verilog_src)?;
    if v.name != top {
        return Err(LvsError::UnknownTop(format!(
            "verilog top '{}' does not match requested '{}'",
            v.name, top
        )));
    }
    let sch = verilog::to_subckt(&v, &lef)?;

    let lay_g = build_graph(&lay)?;
    let sch_g = build_graph(&sch)?;
    Ok(build_report(&lay_g, &sch_g, top))
}

/// Run LVS where the layout is DEF + LEF and the schematic is SPICE
/// (X-style subckt instantiations of the same cells).
pub fn run_lvs_def_spice(
    def_src: &str,
    lef_src: &str,
    spice_src: &str,
    top: &str,
) -> Result<LvsReport> {
    let def = parse_def_str(def_src)?;
    let lef = parse_lef_str(lef_src)?;
    let lay = layout_extract::extract_subckt(&def, &lef, top)?;
    let sch = load_subckt(spice_src, top)?;

    let lay_g = build_graph(&lay)?;
    let sch_g = build_graph(&sch)?;
    Ok(build_report(&lay_g, &sch_g, top))
}

/// Read the supplied LEF sources (one or many) and combine them.
pub fn load_lef_files<P: AsRef<std::path::Path>>(paths: &[P]) -> Result<LefLibrary> {
    let mut lib = LefLibrary::default();
    for p in paths {
        let s = std::fs::read_to_string(p.as_ref())?;
        let other = parse_lef_str(&s)?;
        lib.merge(other);
    }
    Ok(lib)
}

fn build_report(layout: &ConnGraph, schem: &ConnGraph, top: &str) -> LvsReport {
    let net_count_layout = layout.graph.node_weights().filter(|n| n.is_net()).count();
    let net_count_schem = schem.graph.node_weights().filter(|n| n.is_net()).count();
    let device_count_layout = layout
        .graph
        .node_weights()
        .filter(|n| n.is_device())
        .count();
    let device_count_schem = schem.graph.node_weights().filter(|n| n.is_device()).count();

    let outcome = run_isomorphism(layout, schem);
    let (matched, reason) = match outcome {
        MatchOutcome::Match => (true, None),
        MatchOutcome::Mismatch { reason } => (false, Some(reason)),
    };

    let matched_pairs = if matched {
        pair_devices_by_model_order(layout, schem)
    } else {
        Vec::new()
    };

    LvsReport {
        matched,
        top: top.to_string(),
        net_count_layout,
        net_count_schem,
        device_count_layout,
        device_count_schem,
        mismatched_nets: Vec::new(),
        mismatched_devices: Vec::new(),
        matched_pairs,
        reason,
    }
}

/// Best-effort pairing: for each model in layout, pair to schematic device of
/// the same model in declaration order. Useful only after VF2 confirms match.
fn pair_devices_by_model_order(layout: &ConnGraph, schem: &ConnGraph) -> Vec<(String, String)> {
    let mut by_model_sch: std::collections::HashMap<String, Vec<String>> =
        std::collections::HashMap::new();
    for n in schem.graph.node_weights() {
        if let Node::Device { model, name, .. } = n {
            by_model_sch
                .entry(model.clone())
                .or_default()
                .push(name.clone());
        }
    }
    let mut pairs = Vec::new();
    for n in layout.graph.node_weights() {
        if let Node::Device { model, name, .. } = n {
            if let Some(list) = by_model_sch.get_mut(model) {
                if !list.is_empty() {
                    let other = list.remove(0);
                    pairs.push((name.clone(), other));
                }
            }
        }
    }
    pairs
}
