//! Pattern-matched per-segment capacitance.
//!
//! For each segment we build a [`LocalGeom`] snapshot summarising its
//! local environment (dominant same-layer neighbour, presence of
//! crossover on an adjacent layer, corner/T-junction at endpoints) and
//! hand it to [`patterns::classify`]. If a pattern matches, we use its
//! capacitance value; otherwise we fall back to the Sakurai–Tamaru
//! closed-form supplied by [`super::capacitance::wire_capacitance`].

use rstar::{primitives::Rectangle, RTree, AABB};

use super::patterns::{self, LocalGeom};
use super::SegmentGeom;
use crate::extract::coupling::SPACING_THRESHOLD_UM;
use crate::tech::TechFile;

/// Per-segment classification result.
#[derive(Debug, Clone)]
pub struct SegmentClassification {
    pub pattern: &'static str,
    pub c_ff: f64,
}

#[derive(Debug, Clone)]
struct Indexed {
    rect: Rectangle<[f64; 2]>,
    seg: SegmentGeom,
    bbox: (f64, f64, f64, f64),
}

impl rstar::RTreeObject for Indexed {
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

fn is_horizontal(s: &SegmentGeom) -> bool {
    (s.start.1 - s.end.1).abs() < 1e-9
}
fn is_vertical(s: &SegmentGeom) -> bool {
    (s.start.0 - s.end.0).abs() < 1e-9
}

/// Run pattern classification across all segments. Returns one entry
/// per input segment, in input order. The pattern's reported `c_ff`
/// supersedes the Sakurai–Tamaru baseline for that segment.
pub fn classify_all(
    tech: &TechFile,
    segments: &[(usize, SegmentGeom)],
) -> Vec<SegmentClassification> {
    // Build an R-tree indexed on each segment's bbox padded by the
    // spacing threshold so we can quickly find local neighbours.
    let mut entries: Vec<Indexed> = Vec::with_capacity(segments.len());
    for (_, seg) in segments {
        let (x0, y0) = seg.start;
        let (x1, y1) = seg.end;
        let pad = SPACING_THRESHOLD_UM + seg.width_um * 0.5;
        let lo = [x0.min(x1) - pad, y0.min(y1) - pad];
        let hi = [x0.max(x1) + pad, y0.max(y1) + pad];
        let bbox = seg_bbox(seg);
        entries.push(Indexed {
            rect: Rectangle::from_corners(lo, hi),
            seg: seg.clone(),
            bbox,
        });
    }
    let tree = RTree::bulk_load(entries.clone());

    let mut out: Vec<SegmentClassification> = Vec::with_capacity(segments.len());

    for (_, seg) in segments {
        let g = match LocalGeom::new(tech, &seg.layer, seg_length(seg), seg.width_um) {
            Some(g) => g,
            None => {
                out.push(SegmentClassification {
                    pattern: "unknown_layer",
                    c_ff: 0.0,
                });
                continue;
            }
        };
        let g = annotate(g, seg, &tree, tech);
        let (pattern, c) = match patterns::classify(&g, tech) {
            Some(v) => v,
            None => {
                // Fallback: Sakurai-Tamaru via existing helper.
                let c = super::capacitance::wire_capacitance(
                    tech,
                    &seg.layer,
                    seg_length(seg),
                    seg.width_um,
                );
                ("sakurai_fallback", c)
            }
        };
        out.push(SegmentClassification { pattern, c_ff: c });
    }
    out
}

fn seg_length(s: &SegmentGeom) -> f64 {
    let dx = s.end.0 - s.start.0;
    let dy = s.end.1 - s.start.1;
    (dx * dx + dy * dy).sqrt()
}

/// Populate neighbour / crossover / corner flags on `g` by querying the
/// spatial index built from all routed segments.
fn annotate(
    mut g: LocalGeom,
    seg: &SegmentGeom,
    tree: &RTree<Indexed>,
    tech: &TechFile,
) -> LocalGeom {
    let bbox = seg_bbox(seg);
    let env = AABB::from_corners(
        [bbox.0 - SPACING_THRESHOLD_UM, bbox.1 - SPACING_THRESHOLD_UM],
        [bbox.2 + SPACING_THRESHOLD_UM, bbox.3 + SPACING_THRESHOLD_UM],
    );

    let mut neighbor_count = 0usize;
    let mut min_spacing: Option<f64> = None;
    let mut has_crossover = false;
    let mut has_corner = false;

    for cand in tree.locate_in_envelope_intersecting(&env) {
        // Skip the segment itself (same coords).
        if std::ptr::eq(&cand.seg.layer, &seg.layer)
            && cand.seg.start == seg.start
            && cand.seg.end == seg.end
            && (cand.seg.width_um - seg.width_um).abs() < 1e-9
        {
            continue;
        }
        if cand.seg.layer == seg.layer {
            // Same-layer parallel?
            if let Some(s) = same_layer_spacing(seg, &cand.seg) {
                if s > 0.0 && s <= SPACING_THRESHOLD_UM {
                    neighbor_count += 1;
                    min_spacing = Some(min_spacing.map_or(s, |m| m.min(s)));
                }
            }
            // Corner: shared endpoint and orthogonal direction.
            if shares_endpoint(seg, &cand.seg) && perpendicular(seg, &cand.seg) {
                has_corner = true;
            }
        } else if is_adjacent_layer(tech, &seg.layer, &cand.seg.layer)
            && perpendicular(seg, &cand.seg)
        {
            // Crossover: adjacent layer, perpendicular, bbox overlaps.
            let ox = (bbox.2.min(cand.bbox.2) - bbox.0.max(cand.bbox.0)).max(0.0);
            let oy = (bbox.3.min(cand.bbox.3) - bbox.1.max(cand.bbox.1)).max(0.0);
            if ox * oy > 0.0 {
                has_crossover = true;
            }
        }
    }

    g.neighbor_count = neighbor_count;
    g.spacing_um = min_spacing;
    g.has_crossover = has_crossover;
    g.has_corner = has_corner;
    g
}

fn same_layer_spacing(a: &SegmentGeom, b: &SegmentGeom) -> Option<f64> {
    if is_horizontal(a) && is_horizontal(b) {
        let ax0 = a.start.0.min(a.end.0);
        let ax1 = a.start.0.max(a.end.0);
        let bx0 = b.start.0.min(b.end.0);
        let bx1 = b.start.0.max(b.end.0);
        let ov = (ax1.min(bx1) - ax0.max(bx0)).max(0.0);
        if ov <= 0.0 {
            return None;
        }
        let s = (a.start.1 - b.start.1).abs() - 0.5 * (a.width_um + b.width_um);
        Some(s)
    } else if is_vertical(a) && is_vertical(b) {
        let ay0 = a.start.1.min(a.end.1);
        let ay1 = a.start.1.max(a.end.1);
        let by0 = b.start.1.min(b.end.1);
        let by1 = b.start.1.max(b.end.1);
        let ov = (ay1.min(by1) - ay0.max(by0)).max(0.0);
        if ov <= 0.0 {
            return None;
        }
        let s = (a.start.0 - b.start.0).abs() - 0.5 * (a.width_um + b.width_um);
        Some(s)
    } else {
        None
    }
}

fn shares_endpoint(a: &SegmentGeom, b: &SegmentGeom) -> bool {
    let eq = |p: (f64, f64), q: (f64, f64)| (p.0 - q.0).abs() < 1e-6 && (p.1 - q.1).abs() < 1e-6;
    eq(a.start, b.start) || eq(a.start, b.end) || eq(a.end, b.start) || eq(a.end, b.end)
}

fn perpendicular(a: &SegmentGeom, b: &SegmentGeom) -> bool {
    (is_horizontal(a) && is_vertical(b)) || (is_vertical(a) && is_horizontal(b))
}

fn is_adjacent_layer(tech: &TechFile, a: &str, b: &str) -> bool {
    let above_of = |x: &str| tech.layer(x).and_then(|l| l.above_layer.clone());
    above_of(a).as_deref() == Some(b) || above_of(b).as_deref() == Some(a)
}
