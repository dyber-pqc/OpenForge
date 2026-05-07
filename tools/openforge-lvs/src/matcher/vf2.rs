//! VF2 graph isomorphism wrapper.
//!
//! petgraph ships `is_isomorphic_matching` which implements VF2 for us; we
//! supply node and edge match predicates that encode LVS semantics:
//!
//!   * Two device nodes match iff same `kind` + same `model` + same param map.
//!   * Two net nodes match iff both are ports (and share the same name) OR
//!     both are non-port (anonymous) nets.
//!   * Edges match iff their pin labels are equal — except for symmetric
//!     2-terminal devices (R, C) where pin order is irrelevant; in that case
//!     we accept any pin label match.

use crate::graph::{ConnGraph, Edge, Node};

#[derive(Debug, Clone)]
pub enum MatchOutcome {
    Match,
    Mismatch { reason: String },
}

pub fn run_isomorphism(layout: &ConnGraph, schem: &ConnGraph) -> MatchOutcome {
    // Quick reject: device counts.
    let lay_devs = count_devices(layout);
    let sch_devs = count_devices(schem);
    if lay_devs != sch_devs {
        return MatchOutcome::Mismatch {
            reason: format!("device count mismatch: layout={lay_devs}, schematic={sch_devs}"),
        };
    }

    // Quick reject: device-kind / model histograms.
    let lay_hist = device_hist(layout);
    let sch_hist = device_hist(schem);
    if lay_hist != sch_hist {
        return MatchOutcome::Mismatch {
            reason: format!(
                "device-model histogram mismatch:\n  layout:    {lay_hist:?}\n  schematic: {sch_hist:?}"
            ),
        };
    }

    let nm = |a: &Node, b: &Node| -> bool {
        match (a, b) {
            (
                Node::Device {
                    kind: k1,
                    model: m1,
                    params: p1,
                    ..
                },
                Node::Device {
                    kind: k2,
                    model: m2,
                    params: p2,
                    ..
                },
            ) => k1 == k2 && m1 == m2 && p1 == p2,
            (
                Node::Net {
                    name: n1,
                    is_port: pa,
                },
                Node::Net {
                    name: n2,
                    is_port: pb,
                },
            ) => match (pa, pb) {
                (true, true) => n1 == n2,
                (false, false) => true,
                _ => false,
            },
            _ => false,
        }
    };

    let em = |a: &Edge, b: &Edge| -> bool {
        // Pins are labels on the device-side; for 2-terminal symmetric devices
        // (R, C) pin order is irrelevant. We approximate by accepting either
        // exact label match OR both labels being from {n1, n2}.
        if a.device_pin == b.device_pin {
            return true;
        }
        let symm = |p: &str| p == "n1" || p == "n2";
        symm(&a.device_pin) && symm(&b.device_pin)
    };

    if petgraph::algo::is_isomorphic_matching(&layout.graph, &schem.graph, nm, em) {
        MatchOutcome::Match
    } else {
        MatchOutcome::Mismatch {
            reason: "graphs are not isomorphic".into(),
        }
    }
}

fn count_devices(g: &ConnGraph) -> usize {
    g.graph.node_weights().filter(|n| n.is_device()).count()
}

fn device_hist(g: &ConnGraph) -> std::collections::BTreeMap<String, usize> {
    let mut out = std::collections::BTreeMap::new();
    for n in g.graph.node_weights() {
        if let Node::Device { kind, model, .. } = n {
            *out.entry(format!("{kind}:{model}")).or_insert(0) += 1;
        }
    }
    out
}
