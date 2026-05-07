//! Check engine: dispatches a `Rule` to its concrete checker.

pub mod space;
pub mod width;

use crate::gds::Layout;
use crate::rules::ast::{LayerSpec, Rule};
use crate::violation::Violation;
use crate::Result;
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
        // Enclosure / Not are stubbed for v0.1 — no violations emitted.
        Rule::Enclosure { .. } | Rule::Not { .. } => Ok(Vec::new()),
    }
}
