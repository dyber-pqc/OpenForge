//! Hierarchical LVS match.
//!
//! When both the schematic and layout SPICE sources expose the same
//! `.SUBCKT` definitions, we can match each subcircuit definition in
//! isolation rather than flattening everything into one giant graph.
//!
//! Strategy:
//!   1. For every subckt name that appears in *both* netlists, build a
//!      [`ConnGraph`] for its definition (after normalization) and run VF2.
//!   2. If all common subckt definitions match, run the top-level match
//!      treating subckt instances as opaque primitives.
//!   3. If any common subckt fails to match, return that failure with the
//!      offending subckt name in the reason — callers can then choose to
//!      flatten and retry.

use crate::error::Result;
use crate::graph::{build_graph, normalize::normalize_subckt};
use crate::matcher::{run_isomorphism, MatchOutcome};
use crate::spice::Netlist;

/// Outcome of a hierarchical match.
#[derive(Debug, Clone)]
pub struct HierResult {
    /// Names of subckts that matched (sorted).
    pub matched_subckts: Vec<String>,
    /// Outcome at the top level.
    pub top_outcome: MatchOutcome,
    /// If a sub-block mismatched, this carries `(name, reason)`.
    pub failed_subckt: Option<(String, String)>,
}

impl HierResult {
    pub fn matched(&self) -> bool {
        self.failed_subckt.is_none() && matches!(self.top_outcome, MatchOutcome::Match)
    }
}

/// Run a hierarchical match between two parsed netlists for `top`.
pub fn run_hierarchical(layout: &Netlist, schem: &Netlist, top: &str) -> Result<HierResult> {
    use crate::error::LvsError;

    // 1. Identify common subckt names (excluding the top, which we always
    //    match last as the outer shell).
    let mut common: Vec<String> = layout
        .library
        .keys()
        .filter(|k| schem.library.contains_key(*k) && k.as_str() != top)
        .cloned()
        .collect();
    common.sort();

    let mut matched_subckts: Vec<String> = Vec::new();
    for name in &common {
        let mut lay = layout
            .library
            .get(name)
            .cloned()
            .ok_or_else(|| LvsError::UnknownTop(name.clone()))?;
        let mut sch = schem
            .library
            .get(name)
            .cloned()
            .ok_or_else(|| LvsError::UnknownTop(name.clone()))?;
        normalize_subckt(&mut lay);
        normalize_subckt(&mut sch);
        let lg = build_graph(&lay)?;
        let sg = build_graph(&sch)?;
        match run_isomorphism(&lg, &sg) {
            MatchOutcome::Match => matched_subckts.push(name.clone()),
            MatchOutcome::Mismatch { reason } => {
                return Ok(HierResult {
                    matched_subckts,
                    top_outcome: MatchOutcome::Mismatch {
                        reason: format!("subckt '{name}': {reason}"),
                    },
                    failed_subckt: Some((name.clone(), reason)),
                });
            }
        }
    }

    // 2. Top-level match (subckt instances treated as opaque).
    let mut lay_top = layout
        .library
        .get(top)
        .cloned()
        .ok_or_else(|| LvsError::UnknownTop(top.to_string()))?;
    let mut sch_top = schem
        .library
        .get(top)
        .cloned()
        .ok_or_else(|| LvsError::UnknownTop(top.to_string()))?;
    normalize_subckt(&mut lay_top);
    normalize_subckt(&mut sch_top);
    let lg = build_graph(&lay_top)?;
    let sg = build_graph(&sch_top)?;
    let top_outcome = run_isomorphism(&lg, &sg);

    Ok(HierResult {
        matched_subckts,
        top_outcome,
        failed_subckt: None,
    })
}
