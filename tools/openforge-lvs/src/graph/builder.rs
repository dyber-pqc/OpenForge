//! Build a `ConnGraph` from a parsed `Subckt`.

use super::{ConnGraph, Edge, Node};
use crate::error::{LvsError, Result};
use crate::spice::{Device, Subckt};
use petgraph::Graph;
use std::collections::HashMap;

pub fn build_graph(sc: &Subckt) -> Result<ConnGraph> {
    let mut graph: Graph<Node, Edge, petgraph::Undirected> = Graph::new_undirected();
    let mut net_to_idx: HashMap<String, petgraph::graph::NodeIndex> = HashMap::new();
    let mut device_to_idx: HashMap<String, petgraph::graph::NodeIndex> = HashMap::new();

    let port_set: std::collections::HashSet<&String> = sc.ports.iter().collect();

    // Pre-create port nodes so they exist even if unused.
    for p in &sc.ports {
        let idx = graph.add_node(Node::Net {
            name: p.clone(),
            is_port: true,
        });
        net_to_idx.insert(p.clone(), idx);
    }

    let get_or_make_net = |graph: &mut Graph<Node, Edge, petgraph::Undirected>,
                           net_to_idx: &mut HashMap<String, petgraph::graph::NodeIndex>,
                           name: &str|
     -> petgraph::graph::NodeIndex {
        if let Some(&idx) = net_to_idx.get(name) {
            return idx;
        }
        let is_port = port_set.contains(&name.to_string());
        let idx = graph.add_node(Node::Net {
            name: name.to_string(),
            is_port,
        });
        net_to_idx.insert(name.to_string(), idx);
        idx
    };

    for dev in &sc.devices {
        let dev_node = Node::Device {
            kind: dev.kind().to_string(),
            name: dev.name().to_string(),
            model: dev.model_signature(),
            params: canonical_params(dev),
        };
        let dev_idx = graph.add_node(dev_node);
        if device_to_idx
            .insert(dev.name().to_string(), dev_idx)
            .is_some()
        {
            return Err(LvsError::Graph(format!(
                "duplicate device name '{}'",
                dev.name()
            )));
        }
        for (pin, net) in dev.pins() {
            let net_idx = get_or_make_net(&mut graph, &mut net_to_idx, &net);
            graph.add_edge(dev_idx, net_idx, Edge { device_pin: pin });
        }
    }

    Ok(ConnGraph {
        graph,
        net_to_idx,
        device_to_idx,
        subckt_name: sc.name.clone(),
    })
}

/// Filter params to those that affect device matching.
fn canonical_params(dev: &Device) -> HashMap<String, String> {
    let raw = dev.params();
    // For mosfets keep w/l only; for others keep value.
    match dev {
        Device::Mosfet { .. } => raw
            .into_iter()
            .filter(|(k, _)| k == "w" || k == "l")
            .collect(),
        _ => raw,
    }
}
