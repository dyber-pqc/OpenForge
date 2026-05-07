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
}

impl Rule {
    pub fn name(&self) -> &str {
        match self {
            Rule::Width { name, .. }
            | Rule::Space { name, .. }
            | Rule::Enclosure { name, .. }
            | Rule::Not { name, .. } => name,
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
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RuleDeck {
    pub name: String,
    pub layers: HashMap<String, LayerSpec>,
    pub rules: Vec<Rule>,
}
