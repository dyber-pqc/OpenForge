//! Connectivity graph for LVS comparison.

pub mod builder;
pub mod normalize;

use petgraph::graph::{Graph, NodeIndex};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Node {
    Net {
        name: String,
        is_port: bool,
    },
    Device {
        kind: String,
        name: String,
        model: String,
        params: HashMap<String, String>,
    },
}

impl Node {
    pub fn label(&self) -> String {
        match self {
            Node::Net { name, is_port } => {
                if *is_port {
                    format!("port:{name}")
                } else {
                    format!("net:{name}")
                }
            }
            Node::Device {
                kind, name, model, ..
            } => format!("dev:{kind}:{model}:{name}"),
        }
    }

    pub fn is_device(&self) -> bool {
        matches!(self, Node::Device { .. })
    }

    pub fn is_net(&self) -> bool {
        matches!(self, Node::Net { .. })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Edge {
    pub device_pin: String,
}

pub struct ConnGraph {
    pub graph: Graph<Node, Edge, petgraph::Undirected>,
    pub net_to_idx: HashMap<String, NodeIndex>,
    pub device_to_idx: HashMap<String, NodeIndex>,
    pub subckt_name: String,
}

pub use builder::build_graph;
