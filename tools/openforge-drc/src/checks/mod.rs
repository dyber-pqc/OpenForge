//! Check engine: dispatches a `Rule` to its concrete checker.

pub mod density;
pub mod enclosure;
pub mod space;
pub mod width;

use crate::gds::Layout;
use crate::rules::ast::{DensityDirection, LayerSpec, Rule};
use crate::violation::Violation;
use crate::Result;
use rayon::prelude::*;
use std::collections::HashMap;

pub fn run_rule(
    rule: &Rule,
    layout: &Layout,
    _layers: &HashMap<String, LayerSpec>,
) -> Result<Vec<Violation>> {
    match rule {
        Rule::Width {
            layer,
            min_um,
            name,
            message,
        } => Ok(width::check_width(layout, layer, *min_um, name, message)),
        Rule::Space {
            layer,
            min_um,
            name,
            message,
            ..
        } => Ok(space::check_space(layout, layer, *min_um, name, message)),
        Rule::Enclosure {
            inner,
            outer,
            min_um,
            name,
            message,
        } => Ok(enclosure::check_enclosure(
            layout, inner, outer, *min_um, name, message,
        )),
        Rule::Density {
            layer,
            window_um,
            pct,
            direction,
            name,
            message,
        } => {
            let dir = match direction {
                DensityDirection::Below => density::DensityDirection::Below,
                DensityDirection::Above => density::DensityDirection::Above,
            };
            Ok(density::check_density(
                layout, layer, *window_um, *pct, dir, name, message,
            ))
        }
        // `not` is still stubbed - it produces a derived layer set with no
        // direct violations of its own.
        Rule::Not { .. } => Ok(Vec::new()),
    }
}

/// Run every rule in `rules` against `layout`, in parallel. Independent
/// rules don't share mutable state so this is a simple `par_iter`.
pub fn run_rules(
    rules: &[Rule],
    layout: &Layout,
    layers: &HashMap<String, LayerSpec>,
) -> Result<Vec<Violation>> {
    // Collect into Result<Vec<Vec<Violation>>>; flatten on success.
    let per_rule: std::result::Result<Vec<Vec<Violation>>, crate::DrcError> = rules
        .par_iter()
        .map(|rule| run_rule(rule, layout, layers))
        .collect();
    Ok(per_rule?.into_iter().flatten().collect())
}
