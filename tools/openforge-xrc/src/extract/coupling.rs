//! Adjacent-net coupling capacitance via R-tree spatial query.
//!
//! v0.1 model: same-layer parallel runs. For two parallel segments on the
//! same layer with overlap length L_ov and edge-to-edge spacing s,
//!
//! ```text
//! C_coup ≈ (L_ov * thickness) * eps0 * eps_r / s     (in fF)
//! ```
//!
//! For sky130-like dielectrics we fold eps0*eps_r into a single constant
//! `K_COUP` (fF/um per um of overlap, per um of thickness, per um of spacing).
//! With eps0 = 8.854e-3 fF/um and an effective eps_r ≈ 4 (oxide), K ≈ 0.035.

use rstar::{primitives::Rectangle, RTree, RTreeObject, AABB};

use super::SegmentGeom;
use crate::tech::TechFile;

const K_COUP: f64 = 0.035; // fF/um · (thickness/spacing dimensionless ratio)
/// Spacing threshold (um) beyond which we ignore coupling.
pub const SPACING_THRESHOLD_UM: f64 = 2.0;

/// Adjacent-net coupling capacitance result.
#[derive(Debug, Clone)]
pub struct CouplingResult {
    /// (net_a, net_b) → cap in fF.
    pub pairs: Vec<((String, String), f64)>,
    /// Number of pair candidates skipped due to insufficient overlap.
    pub skipped: usize,
}

#[derive(Debug, Clone)]
struct SegRect {
    rect: Rectangle<[f64; 2]>,
    net_idx: usize,
    layer: String,
    /// Original geometry for refinement.
    seg: SegmentGeom,
}

impl rstar::RTreeObject for SegRect {
    type Envelope = AABB<[f64; 2]>;
    fn envelope(&self) -> Self::Envelope {
        self.rect.envelope()
    }
}

/// Compute coupling caps between all pairs of nets, returning aggregated
/// per-pair fF values. `segments` is a flat list of `(net_idx, geom)`.
pub fn compute(
    tech: &TechFile,
    net_names: &[String],
    segments: &[(usize, SegmentGeom)],
) -> CouplingResult {
    let mut entries: Vec<SegRect> = Vec::with_capacity(segments.len());
    for (idx, seg) in segments {
        let (x0, y0) = seg.start;
        let (x1, y1) = seg.end;
        let half_w = seg.width_um * 0.5;
        // Inflate by SPACING_THRESHOLD_UM to find neighbors.
        let pad = SPACING_THRESHOLD_UM + half_w;
        let lo = [x0.min(x1) - pad, y0.min(y1) - pad];
        let hi = [x0.max(x1) + pad, y0.max(y1) + pad];
        entries.push(SegRect {
            rect: Rectangle::from_corners(lo, hi),
            net_idx: *idx,
            layer: seg.layer.clone(),
            seg: seg.clone(),
        });
    }
    let tree = RTree::bulk_load(entries.clone());

    use std::collections::HashMap;
    let mut acc: HashMap<(usize, usize), f64> = HashMap::new();
    let mut skipped = 0usize;

    for a in &entries {
        let env = a.rect.envelope();
        for b in tree.locate_in_envelope_intersecting(&env) {
            if b.net_idx <= a.net_idx {
                continue; // dedup pairs
            }
            if a.layer != b.layer {
                continue; // v0.1: same-layer only
            }
            let c = pair_coupling(tech, &a.seg, &b.seg);
            if c <= 0.0 {
                skipped += 1;
                continue;
            }
            *acc.entry((a.net_idx, b.net_idx)).or_default() += c;
        }
    }

    let mut pairs: Vec<((String, String), f64)> = acc
        .into_iter()
        .map(|((i, j), c)| ((net_names[i].clone(), net_names[j].clone()), c))
        .collect();
    pairs.sort_by(|x, y| x.0.cmp(&y.0));

    CouplingResult { pairs, skipped }
}

/// Coupling between two same-layer segments. Only parallel orthogonal-axis
/// runs (both horizontal or both vertical) are modeled in v0.1.
fn pair_coupling(tech: &TechFile, a: &SegmentGeom, b: &SegmentGeom) -> f64 {
    if a.layer != b.layer {
        return 0.0;
    }
    let lp = match tech.layer(&a.layer) {
        Some(l) => l,
        None => return 0.0,
    };

    let a_horiz = (a.start.1 - a.end.1).abs() < 1e-9;
    let a_vert = (a.start.0 - a.end.0).abs() < 1e-9;
    let b_horiz = (b.start.1 - b.end.1).abs() < 1e-9;
    let b_vert = (b.start.0 - b.end.0).abs() < 1e-9;

    let (overlap, spacing) = if a_horiz && b_horiz {
        let ax0 = a.start.0.min(a.end.0);
        let ax1 = a.start.0.max(a.end.0);
        let bx0 = b.start.0.min(b.end.0);
        let bx1 = b.start.0.max(b.end.0);
        let ov = (ax1.min(bx1) - ax0.max(bx0)).max(0.0);
        let s = (a.start.1 - b.start.1).abs() - 0.5 * (a.width_um + b.width_um);
        (ov, s)
    } else if a_vert && b_vert {
        let ay0 = a.start.1.min(a.end.1);
        let ay1 = a.start.1.max(a.end.1);
        let by0 = b.start.1.min(b.end.1);
        let by1 = b.start.1.max(b.end.1);
        let ov = (ay1.min(by1) - ay0.max(by0)).max(0.0);
        let s = (a.start.0 - b.start.0).abs() - 0.5 * (a.width_um + b.width_um);
        (ov, s)
    } else {
        return 0.0;
    };

    if overlap <= 0.0 || spacing <= 0.0 || spacing > SPACING_THRESHOLD_UM {
        return 0.0;
    }
    K_COUP * overlap * lp.thickness_um / spacing
}
