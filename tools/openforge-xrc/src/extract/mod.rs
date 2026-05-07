//! Parasitic extraction engine.

pub mod capacitance;
pub mod coupling;
pub mod resistance;

use crate::def::{Def, RouteSeg};
use crate::lef::LefLibrary;
use crate::tech::TechFile;

/// Geometric segment (post-conversion to microns) used by coupling.
#[derive(Debug, Clone)]
pub struct SegmentGeom {
    pub layer: String,
    pub start: (f64, f64),
    pub end: (f64, f64),
    pub width_um: f64,
}

#[derive(Debug, Clone)]
pub struct Segment {
    pub layer: String,
    pub from_node: String,
    pub to_node: String,
    pub length_um: f64,
    pub width_um: f64,
    pub r_ohm: f64,
    pub c_ff: f64,
}

#[derive(Debug, Clone)]
pub struct ViaContribution {
    pub via_name: String,
    pub r_ohm: f64,
}

#[derive(Debug, Clone)]
pub struct CouplingCap {
    pub neighbor_net: String,
    pub c_ff: f64,
}

#[derive(Debug, Clone)]
pub struct NetParasitics {
    pub net_name: String,
    pub total_cap_ff: f64,
    pub total_res_ohm: f64,
    pub segments: Vec<Segment>,
    pub vias: Vec<ViaContribution>,
    pub coupling: Vec<CouplingCap>,
    pub connections: Vec<(String, String)>,
    pub wirelength_um: f64,
}

/// Top-level extraction result.
#[derive(Debug, Clone, Default)]
pub struct ExtractionResult {
    pub design: String,
    pub nets: Vec<NetParasitics>,
    pub coupling_skipped: usize,
}

impl ExtractionResult {
    pub fn total_wirelength_um(&self) -> f64 {
        self.nets.iter().map(|n| n.wirelength_um).sum()
    }
    pub fn total_r_ohm(&self) -> f64 {
        self.nets.iter().map(|n| n.total_res_ohm).sum()
    }
    pub fn total_c_ff(&self) -> f64 {
        self.nets.iter().map(|n| n.total_cap_ff).sum()
    }
    /// Net with highest R*C product (rough proxy for "worst").
    pub fn worst_net(&self) -> Option<&NetParasitics> {
        self.nets.iter().max_by(|a, b| {
            let am = a.total_res_ohm * a.total_cap_ff;
            let bm = b.total_res_ohm * b.total_cap_ff;
            am.partial_cmp(&bm).unwrap_or(std::cmp::Ordering::Equal)
        })
    }
}

/// Run the extraction pipeline.
pub fn extract(def: &Def, _lef: &LefLibrary, tech: &TechFile) -> ExtractionResult {
    let upm = def.units_per_micron.max(1.0);
    let mut net_paras: Vec<NetParasitics> = Vec::with_capacity(def.nets.len());
    let mut all_geoms: Vec<(usize, SegmentGeom)> = Vec::new();
    let mut net_names: Vec<String> = Vec::with_capacity(def.nets.len());

    for (idx, net) in def.nets.iter().enumerate() {
        net_names.push(net.name.clone());
        let mut np = NetParasitics {
            net_name: net.name.clone(),
            total_cap_ff: 0.0,
            total_res_ohm: 0.0,
            segments: Vec::new(),
            vias: Vec::new(),
            coupling: Vec::new(),
            connections: net.connections.clone(),
            wirelength_um: 0.0,
        };

        let mut node_counter: usize = 0;
        let mut alloc_node = |np: &NetParasitics| -> String {
            // Use fresh name based on net + counter; closure borrows immutably,
            // so caller increments counter externally.
            format!("{}:{}", np.net_name, np.segments.len() + 1)
        };

        for r in &net.routes {
            extract_route(
                r,
                upm,
                tech,
                &mut np,
                &mut node_counter,
                &mut all_geoms,
                idx,
                &mut alloc_node,
            );
        }

        net_paras.push(np);
    }

    // Coupling pass.
    let cresult = coupling::compute(tech, &net_names, &all_geoms);
    // Distribute coupling caps to nets and add to total cap.
    use std::collections::HashMap;
    let mut by_net: HashMap<String, Vec<CouplingCap>> = HashMap::new();
    for ((a, b), c) in &cresult.pairs {
        by_net.entry(a.clone()).or_default().push(CouplingCap {
            neighbor_net: b.clone(),
            c_ff: *c,
        });
        by_net.entry(b.clone()).or_default().push(CouplingCap {
            neighbor_net: a.clone(),
            c_ff: *c,
        });
    }
    for np in &mut net_paras {
        if let Some(v) = by_net.remove(&np.net_name) {
            for cc in &v {
                np.total_cap_ff += cc.c_ff;
            }
            np.coupling = v;
        }
    }

    ExtractionResult {
        design: def.design.clone(),
        nets: net_paras,
        coupling_skipped: cresult.skipped,
    }
}

#[allow(clippy::too_many_arguments)]
fn extract_route(
    r: &RouteSeg,
    upm: f64,
    tech: &TechFile,
    np: &mut NetParasitics,
    _node_counter: &mut usize,
    geoms: &mut Vec<(usize, SegmentGeom)>,
    net_idx: usize,
    _alloc: &mut dyn FnMut(&NetParasitics) -> String,
) {
    let layer = r.layer.clone();
    let width_um = tech.layer(&layer).map(|l| l.min_width_um).unwrap_or(0.14);

    // Walk consecutive points; each pair forms a wire segment. Vias attached
    // to a point contribute a via resistance.
    for i in 0..r.points.len() {
        let p = &r.points[i];
        if let Some(via_name) = &p.via {
            let r_via = resistance::via_resistance(tech, via_name);
            np.total_res_ohm += r_via;
            np.vias.push(ViaContribution {
                via_name: via_name.clone(),
                r_ohm: r_via,
            });
        }
        if i + 1 < r.points.len() {
            let q = &r.points[i + 1];
            let x0 = p.x as f64 / upm;
            let y0 = p.y as f64 / upm;
            let x1 = q.x as f64 / upm;
            let y1 = q.y as f64 / upm;
            let dx = x1 - x0;
            let dy = y1 - y0;
            let length_um = (dx * dx + dy * dy).sqrt();
            if length_um <= 0.0 {
                continue;
            }
            let r_ohm = resistance::wire_resistance(tech, &layer, length_um, width_um);
            let c_ff = capacitance::wire_capacitance(tech, &layer, length_um, width_um);
            let from = format!("{}:{}", np.net_name, np.segments.len() + 1);
            let to = format!("{}:{}", np.net_name, np.segments.len() + 2);
            np.segments.push(Segment {
                layer: layer.clone(),
                from_node: from,
                to_node: to,
                length_um,
                width_um,
                r_ohm,
                c_ff,
            });
            np.total_res_ohm += r_ohm;
            np.total_cap_ff += c_ff;
            np.wirelength_um += length_um;
            geoms.push((
                net_idx,
                SegmentGeom {
                    layer: layer.clone(),
                    start: (x0, y0),
                    end: (x1, y1),
                    width_um,
                },
            ));
        }
    }
}
