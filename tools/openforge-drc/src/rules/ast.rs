//! Rule deck abstract syntax tree.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Mapping from a layer *name* (e.g. "met1") to its GDS (layer, datatype).
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct LayerSpec {
    pub layer: u16,
    pub datatype: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Rule {
    Width {
        layer: String,
        min_um: f64,
        name: String,
        message: String,
    },
    Space {
        layer: String,
        min_um: f64,
        name: String,
        message: String,
        intra_layer: bool,
    },
    Enclosure {
        inner: String,
        outer: String,
        min_um: f64,
        name: String,
        message: String,
    },
    Not {
        a: String,
        b: String,
        result: String,
        name: String,
        message: String,
    },
    Density {
        layer: String,
        window_um: f64,
        pct: f64,
        /// `Below` => violation when density < pct (min-density rule).
        /// `Above` => violation when density > pct (max-density rule).
        direction: DensityDirection,
        name: String,
        message: String,
    },
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum DensityDirection {
    Below,
    Above,
}

impl Rule {
    pub fn name(&self) -> &str {
        match self {
            Rule::Width { name, .. }
            | Rule::Space { name, .. }
            | Rule::Enclosure { name, .. }
            | Rule::Not { name, .. }
            | Rule::Density { name, .. } => name,
        }
    }

    pub fn description(&self) -> String {
        match self {
            Rule::Width { layer, min_um, .. } => {
                format!("Minimum width of {layer} ({min_um} um)")
            }
            Rule::Space { layer, min_um, .. } => {
                format!("Minimum spacing on {layer} ({min_um} um)")
            }
            Rule::Enclosure {
                inner,
                outer,
                min_um,
                ..
            } => format!("Minimum enclosure of {inner} by {outer} ({min_um} um)"),
            Rule::Not { a, b, .. } => format!("{a} not {b}"),
            Rule::Density {
                layer,
                window_um,
                pct,
                direction,
                ..
            } => {
                let cmp = match direction {
                    DensityDirection::Below => "min",
                    DensityDirection::Above => "max",
                };
                format!("{cmp} density on {layer} window {window_um} um pct {pct}")
            }
        }
    }
}

/// A boolean operation between two layers (primitive or already-derived).
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum BoolOp {
    /// Polygons of A that lie entirely inside any polygon of B.
    Inside,
    /// Polygons of A that have any part outside every polygon of B.
    Outside,
    /// A minus B (set subtraction; bbox-approximated in v0.3).
    Not,
    /// A intersect B.
    And,
    /// A union B.
    Or,
}

/// A derived layer produced by a boolean op on already-named layers.
/// Materialised once before the check phase.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DerivedLayer {
    pub name: String,
    pub op: BoolOp,
    pub a: String,
    pub b: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RuleDeck {
    pub name: String,
    pub layers: HashMap<String, LayerSpec>,
    /// Derived layers in declaration order. Each entry's inputs must already
    /// be defined either as primitive layers or as earlier derived layers.
    pub derived: Vec<DerivedLayer>,
    pub rules: Vec<Rule>,
}
