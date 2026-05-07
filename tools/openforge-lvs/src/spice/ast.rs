//! AST for a SPICE netlist subset.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Device {
    Mosfet {
        name: String,
        drain: String,
        gate: String,
        source: String,
        body: String,
        model: String,
        params: HashMap<String, String>,
    },
    Resistor {
        name: String,
        n1: String,
        n2: String,
        value_ohm: f64,
    },
    Capacitor {
        name: String,
        n1: String,
        n2: String,
        value_f: f64,
    },
    SubcktInst {
        name: String,
        nodes: Vec<String>,
        subckt: String,
        params: HashMap<String, String>,
    },
}

impl Device {
    pub fn name(&self) -> &str {
        match self {
            Device::Mosfet { name, .. }
            | Device::Resistor { name, .. }
            | Device::Capacitor { name, .. }
            | Device::SubcktInst { name, .. } => name,
        }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            Device::Mosfet { .. } => "mosfet",
            Device::Resistor { .. } => "resistor",
            Device::Capacitor { .. } => "capacitor",
            Device::SubcktInst { .. } => "subckt",
        }
    }

    /// Returns (pin_name, net_name) pairs.
    pub fn pins(&self) -> Vec<(String, String)> {
        match self {
            Device::Mosfet {
                drain,
                gate,
                source,
                body,
                ..
            } => vec![
                ("drain".into(), drain.clone()),
                ("gate".into(), gate.clone()),
                ("source".into(), source.clone()),
                ("body".into(), body.clone()),
            ],
            Device::Resistor { n1, n2, .. } | Device::Capacitor { n1, n2, .. } => {
                vec![("n1".into(), n1.clone()), ("n2".into(), n2.clone())]
            }
            Device::SubcktInst { nodes, .. } => nodes
                .iter()
                .enumerate()
                .map(|(i, n)| (format!("p{i}"), n.clone()))
                .collect(),
        }
    }

    /// Returns the device "model" string for matching: mosfet model name,
    /// "R"/"C" for passives, or the subckt name.
    pub fn model_signature(&self) -> String {
        match self {
            Device::Mosfet { model, .. } => model.clone(),
            Device::Resistor { .. } => "R".into(),
            Device::Capacitor { .. } => "C".into(),
            Device::SubcktInst { subckt, .. } => subckt.clone(),
        }
    }

    pub fn params(&self) -> HashMap<String, String> {
        match self {
            Device::Mosfet { params, .. } | Device::SubcktInst { params, .. } => params.clone(),
            Device::Resistor { value_ohm, .. } => {
                let mut m = HashMap::new();
                m.insert("value".into(), format!("{value_ohm}"));
                m
            }
            Device::Capacitor { value_f, .. } => {
                let mut m = HashMap::new();
                m.insert("value".into(), format!("{value_f}"));
                m
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct Subckt {
    pub name: String,
    pub ports: Vec<String>,
    pub devices: Vec<Device>,
    pub subckts: Vec<Subckt>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Netlist {
    pub top: Subckt,
    pub library: HashMap<String, Subckt>,
}
