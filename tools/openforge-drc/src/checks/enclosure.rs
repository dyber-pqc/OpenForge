//! Enclosure check: every polygon on `inner` must be enclosed by some
//! polygon on `outer` with at least `min_um` margin on every edge.
//!
//! v0.2 simplification: we treat both polygons by their bounding boxes for
//! the containment test. This is correct for the common case where outer
//! shapes are convex/rectangular (typical of routing layers, vias, wells)
//! and is what KLayout's `enclosing` operator approximates anyway when
//! shapes are box-like. A future iteration can swap in geo's `Contains`.

use crate::gds::Layout;
use crate::geom::{Bbox, Polygon};
use crate::violation::{Severity, Violation};
use rstar::{RTree, RTreeObject, AABB};

struct IndexedBbox {
    idx: usize,
    aabb: AABB<[f64; 2]>,
}

impl RTreeObject for IndexedBbox {
    type Envelope = AABB<[f64; 2]>;
    fn envelope(&self) -> Self::Envelope {
        self.aabb
    }
}

/// True if `outer` bbox encloses `inner` bbox by at least `margin` on every
/// side. (i.e. inner shrunk inward stays inside outer's interior).
fn bbox_encloses_with_margin(outer: &Bbox, inner: &Bbox, margin: f64) -> bool {
    inner.x_min - outer.x_min >= margin
        && outer.x_max - inner.x_max >= margin
        && inner.y_min - outer.y_min >= margin
        && outer.y_max - inner.y_max >= margin
}

pub fn check_enclosure(
    layout: &Layout,
    inner_layer: &str,
    outer_layer: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let inners: Vec<&Polygon> = layout.polygons_on(inner_layer).collect();
    let outers: Vec<&Polygon> = layout.polygons_on(outer_layer).collect();
    if inners.is_empty() {
        return Vec::new();
    }

    // R-tree over outer polygons, expanded by min_um so that any outer that
    // *could* enclose the inner shows up as a candidate.
    let items: Vec<IndexedBbox> = outers
        .iter()
        .enumerate()
        .map(|(idx, p)| IndexedBbox {
            idx,
            aabb: AABB::from_corners([p.bbox.x_min, p.bbox.y_min], [p.bbox.x_max, p.bbox.y_max]),
        })
        .collect();
    let tree = RTree::bulk_load(items);

    let mut out = Vec::new();
    for inner in &inners {
        // Any outer that contains the inner with margin must have a bbox
        // that, when shrunk by min_um, still contains inner's bbox.
        // Equivalently, inner.bbox must lie within outer.bbox shrunk by
        // min_um. Search outers whose bbox covers inner.bbox.
        let q = AABB::from_corners(
            [inner.bbox.x_min, inner.bbox.y_min],
            [inner.bbox.x_max, inner.bbox.y_max],
        );
        let mut enclosed = false;
        for cand in tree.locate_in_envelope_intersecting(&q) {
            let outer = outers[cand.idx];
            if bbox_encloses_with_margin(&outer.bbox, &inner.bbox, min_um) {
                enclosed = true;
                break;
            }
        }
        if !enclosed {
            out.push(Violation {
                rule: rule_name.to_string(),
                layer: inner_layer.to_string(),
                message: format!("{message} (need {min_um:.4} um of {outer_layer})"),
                coords_um: (
                    inner.bbox.x_min,
                    inner.bbox.y_min,
                    inner.bbox.x_max,
                    inner.bbox.y_max,
                ),
                severity: Severity::Error,
                cell: inner.cell.clone(),
            });
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::gds::Layout;
    use crate::geom::Polygon;

    fn rect(layer: &str, x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon {
        Polygon::new(layer, vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "TOP")
    }

    fn lo(polys: Vec<Polygon>) -> Layout {
        Layout {
            top_cell: "TOP".into(),
            polygons: polys,
            units_um: 1e-3,
        }
    }

    #[test]
    fn properly_enclosed_passes() {
        let l = lo(vec![
            rect("outer", 0.0, 0.0, 1.0, 1.0),
            rect("inner", 0.2, 0.2, 0.8, 0.8), // 0.2 um margin all around
        ]);
        let v = check_enclosure(&l, "inner", "outer", 0.1, "E", "fail");
        assert!(v.is_empty(), "got: {v:?}");
    }

    #[test]
    fn insufficient_margin_fails() {
        let l = lo(vec![
            rect("outer", 0.0, 0.0, 1.0, 1.0),
            rect("inner", 0.05, 0.05, 0.95, 0.95), // only 0.05 um margin
        ]);
        let v = check_enclosure(&l, "inner", "outer", 0.1, "E", "need 0.1");
        assert_eq!(v.len(), 1);
    }

    #[test]
    fn no_outer_at_all_fails() {
        let l = lo(vec![rect("inner", 0.0, 0.0, 1.0, 1.0)]);
        let v = check_enclosure(&l, "inner", "outer", 0.1, "E", "fail");
        assert_eq!(v.len(), 1);
    }
}
