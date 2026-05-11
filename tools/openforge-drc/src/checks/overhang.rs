//! Overhang check: every polygon on `inner` must sit inside some polygon
//! on `outer` with at least `min_um` of clearance on every edge.
//!
//! Geometrically this is the same condition as `enclosure.rs`, but the
//! Magic translator surfaces it as a distinct primitive (`overhang outer
//! inner d`) and the violation message references the outer layer as the
//! offender (it's the layer that's not extending far enough), not the
//! inner. So we re-implement it here rather than rewriting in terms of
//! `Rule::Enclosure` so each variant produces a faithful report.
//!
//! Bounding-box approximation matches `enclosure.rs` (good for the
//! axis-aligned routing/via shapes overhang rules typically apply to).

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

fn bbox_overhangs(outer: &Bbox, inner: &Bbox, margin: f64) -> bool {
    inner.x_min - outer.x_min >= margin
        && outer.x_max - inner.x_max >= margin
        && inner.y_min - outer.y_min >= margin
        && outer.y_max - inner.y_max >= margin
}

pub fn check_overhang(
    layout: &Layout,
    outer_layer: &str,
    inner_layer: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let inners: Vec<&Polygon> = layout.polygons_on(inner_layer).collect();
    let outers: Vec<&Polygon> = layout.polygons_on(outer_layer).collect();
    if inners.is_empty() {
        return Vec::new();
    }

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
        let q = AABB::from_corners(
            [inner.bbox.x_min, inner.bbox.y_min],
            [inner.bbox.x_max, inner.bbox.y_max],
        );
        let mut ok = false;
        for cand in tree.locate_in_envelope_intersecting(&q) {
            let outer = outers[cand.idx];
            if bbox_overhangs(&outer.bbox, &inner.bbox, min_um) {
                ok = true;
                break;
            }
        }
        if !ok {
            out.push(Violation {
                rule: rule_name.to_string(),
                layer: outer_layer.to_string(),
                message: format!(
                    "{message} ({outer_layer} must overhang {inner_layer} by {min_um:.4} um)"
                ),
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
    fn sufficient_overhang_passes() {
        let l = lo(vec![
            rect("met1", 0.0, 0.0, 1.0, 1.0),
            rect("via", 0.2, 0.2, 0.8, 0.8),
        ]);
        let v = check_overhang(&l, "met1", "via", 0.1, "O", "fail");
        assert!(v.is_empty());
    }

    #[test]
    fn insufficient_overhang_fails() {
        let l = lo(vec![
            rect("met1", 0.0, 0.0, 1.0, 1.0),
            rect("via", 0.05, 0.05, 0.95, 0.95),
        ]);
        let v = check_overhang(&l, "met1", "via", 0.1, "O", "need 0.1");
        assert_eq!(v.len(), 1);
        assert_eq!(v[0].layer, "met1");
    }
}
