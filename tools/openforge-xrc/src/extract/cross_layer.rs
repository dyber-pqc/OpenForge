//! Cross-layer (vertical) coupling capacitance.
//!
//! For each pair of routed segments on adjacent metal layers (L and L±1)
//! whose 2D footprints overlap, we add a parallel-plate cap:
//!
//! ```text
//!   C_xlayer = eps_0 * eps_r * A_overlap / d_ild     [fF]
//! ```
//!
//! where `A_overlap` is the projected overlap area in µm², `d_ild` is the
//! inter-layer dielectric thickness in µm (from `LayerProps.inter_layer_distance_um`),
//! eps_0 = 8.854e-3 fF/µm, and eps_r ≈ 4.2 for sky130 ILD.
//!
//! This is the standard parallel-plate model — sufficient when the wires
//! are wide compared to the ILD thickness; thin-wire fringe is handled by
//! the per-segment fringe term.

use rstar::{primitives::Rectangle, RTree, RTreeObject, AABB};

use super::SegmentGeom;
use crate::tech::TechFile;

/// Vacuum permittivity in fF/µm. (eps_0 = 8.854e-12 F/m = 8.854e-3 fF/µm)
pub const EPS0_FF_PER_UM: f64 = 8.854e-3;
/// Effective relative permittivity of the inter-layer dielectric (sky130 ILD).
pub const EPS_R_ILD: f64 = 4.2;

#[derive(Debug, Clone)]
pub struct CrossLayerResult {
    /// (net_a, net_b) → cross-layer cap in fF.
    pub pairs: Vec<((String, String), f64)>,
}

#[derive(Debug, Clone)]
struct SegBox {
    rect: Rectangle<[f64; 2]>,
    net_idx: usize,
    layer: String,
    bbox: (f64, f64, f64, f64), // xlo, ylo, xhi, yhi
    /// True footprint area of the wire (length × width), used to clamp
    /// the projected-overlap area: a diagonal segment's bounding box
    /// can be orders of magnitude larger than the actual conductor area.
    footprint_area_um2: f64,
}

impl rstar::RTreeObject for SegBox {
    type Envelope = AABB<[f64; 2]>;
    fn envelope(&self) -> Self::Envelope {
        self.rect.envelope()
    }
}

fn seg_bbox(seg: &SegmentGeom) -> (f64, f64, f64, f64) {
    let (x0, y0) = seg.start;
    let (x1, y1) = seg.end;
    let half_w = seg.width_um * 0.5;
    let xlo = x0.min(x1) - half_w;
    let xhi = x0.max(x1) + half_w;
    let ylo = y0.min(y1) - half_w;
    let yhi = y0.max(y1) + half_w;
    (xlo, ylo, xhi, yhi)
}

/// Compute cross-layer coupling caps for all pairs of nets.
pub fn compute(
    tech: &TechFile,
    net_names: &[String],
    segments: &[(usize, SegmentGeom)],
) -> CrossLayerResult {
    let mut entries: Vec<SegBox> = Vec::with_capacity(segments.len());
    for (idx, seg) in segments {
        let bbox = seg_bbox(seg);
        let lo = [bbox.0, bbox.1];
        let hi = [bbox.2, bbox.3];
        let dx = seg.end.0 - seg.start.0;
        let dy = seg.end.1 - seg.start.1;
        let length = (dx * dx + dy * dy).sqrt();
        let footprint_area_um2 = length * seg.width_um;
        entries.push(SegBox {
            rect: Rectangle::from_corners(lo, hi),
            net_idx: *idx,
            layer: seg.layer.clone(),
            bbox,
            footprint_area_um2,
        });
    }
    let tree = RTree::bulk_load(entries.clone());

    use std::collections::HashMap;
    let mut acc: HashMap<(usize, usize), f64> = HashMap::new();

    for a in &entries {
        let env = a.rect.envelope();
        for b in tree.locate_in_envelope_intersecting(&env) {
            if b.net_idx <= a.net_idx {
                continue; // dedup pairs
            }
            if a.layer == b.layer {
                continue; // same-layer handled by coupling::compute
            }
            // Only adjacent layers count: a is above b, or b is above a.
            let lower = if is_directly_above(tech, &b.layer, &a.layer) {
                b
            } else if is_directly_above(tech, &a.layer, &b.layer) {
                a
            } else {
                continue;
            };
            let lp_lower = match tech.layer(&lower.layer) {
                Some(l) => l,
                None => continue,
            };
            let d = match lp_lower.inter_layer_distance_um {
                Some(v) if v > 0.0 => v,
                _ => continue,
            };
            // Projected overlap area in (x,y) of the two bounding boxes.
            // For Manhattan wires this is exactly the conductor overlap; for
            // diagonal segments the bbox can be orders of magnitude larger
            // than the actual wire footprint, so clamp by the smaller of the
            // two true wire areas (length × width).
            let ox = (a.bbox.2.min(b.bbox.2) - a.bbox.0.max(b.bbox.0)).max(0.0);
            let oy = (a.bbox.3.min(b.bbox.3) - a.bbox.1.max(b.bbox.1)).max(0.0);
            let bbox_area = ox * oy;
            if bbox_area <= 0.0 {
                continue;
            }
            let max_real = a.footprint_area_um2.min(b.footprint_area_um2);
            let area = bbox_area.min(max_real);
            // C = eps0 * eps_r * A / d
            let c = EPS0_FF_PER_UM * EPS_R_ILD * area / d;
            *acc.entry((a.net_idx, b.net_idx)).or_default() += c;
        }
    }

    let mut pairs: Vec<((String, String), f64)> = acc
        .into_iter()
        .map(|((i, j), c)| ((net_names[i].clone(), net_names[j].clone()), c))
        .collect();
    pairs.sort_by(|x, y| x.0.cmp(&y.0));
    CrossLayerResult { pairs }
}

/// Returns true if `upper` is the layer directly above `lower` (per tech).
fn is_directly_above(tech: &TechFile, lower: &str, upper: &str) -> bool {
    match tech.layer(lower).and_then(|l| l.above_layer.as_deref()) {
        Some(name) => name == upper,
        None => false,
    }
}
