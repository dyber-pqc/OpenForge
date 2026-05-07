//! Minimum-spacing check.
//!
//! v0.2 algorithm: build an R-tree over polygon bounding boxes, then for
//! each polygon query only neighbors within `min_space + max_polygon_dim`.
//! On sparse layouts this is effectively O(N log N) instead of the O(N^2)
//! pairwise scan in v0.1.
//!
//! Touching/overlapping polygons (distance 0) on the same layer are *not*
//! a spacing violation - they're a single net.

use crate::gds::Layout;
use crate::geom::ops::polygon_distance;
use crate::geom::Polygon;
use crate::violation::{Severity, Violation};
use rstar::{RTree, RTreeObject, AABB};

/// Tiny wrapper so an `rstar::RTree` can index polygons by index.
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

pub fn check_space(
    layout: &Layout,
    layer: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let polys: Vec<&Polygon> = layout.polygons_on(layer).collect();
    if polys.len() < 2 {
        return Vec::new();
    }

    // Largest polygon dimension - controls how far we have to search around
    // a query bbox to be sure we don't miss a true neighbor.
    let mut max_dim = 0.0_f64;
    for p in &polys {
        let w = p.bbox.x_max - p.bbox.x_min;
        let h = p.bbox.y_max - p.bbox.y_min;
        let d = w.max(h);
        if d > max_dim {
            max_dim = d;
        }
    }

    let items: Vec<IndexedBbox> = polys
        .iter()
        .enumerate()
        .map(|(idx, p)| IndexedBbox {
            idx,
            aabb: AABB::from_corners([p.bbox.x_min, p.bbox.y_min], [p.bbox.x_max, p.bbox.y_max]),
        })
        .collect();
    let tree = RTree::bulk_load(items);

    const EPS: f64 = 1e-9;
    let mut out = Vec::new();
    for (i, a) in polys.iter().enumerate() {
        // Search envelope: bbox expanded by min_um on each side, then we
        // still have to handle the case that another polygon is *contained*
        // within that envelope only because its bbox is itself larger than
        // min_um. The R-tree's `locate_in_envelope_intersecting` handles
        // both directions: any candidate whose bbox intersects ours grown
        // by min_um is returned.
        let query = AABB::from_corners(
            [a.bbox.x_min - min_um, a.bbox.y_min - min_um],
            [a.bbox.x_max + min_um, a.bbox.y_max + min_um],
        );
        let _ = max_dim; // (intentionally unused: rstar's intersection
                         // query already returns every polygon whose bbox
                         // touches our grown envelope, regardless of size)

        for cand in tree.locate_in_envelope_intersecting(&query) {
            let j = cand.idx;
            // Only emit each pair once.
            if j <= i {
                continue;
            }
            let b = polys[j];
            let bbox_gap = a.bbox.gap(&b.bbox);
            if bbox_gap > min_um {
                continue;
            }
            let d = polygon_distance(a, b);
            if d <= EPS {
                continue;
            }
            if d + EPS < min_um {
                let x_min = a.bbox.x_min.min(b.bbox.x_min);
                let y_min = a.bbox.y_min.min(b.bbox.y_min);
                let x_max = a.bbox.x_max.max(b.bbox.x_max);
                let y_max = a.bbox.y_max.max(b.bbox.y_max);
                out.push(Violation {
                    rule: rule_name.to_string(),
                    layer: layer.to_string(),
                    message: format!("{message} (measured {d:.4} um < {min_um:.4} um)"),
                    coords_um: (x_min, y_min, x_max, y_max),
                    severity: Severity::Error,
                    cell: a.cell.clone(),
                });
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::gds::Layout;
    use crate::geom::Polygon;

    fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon {
        Polygon::new("met1", vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "TOP")
    }

    fn layout_of(polys: Vec<Polygon>) -> Layout {
        Layout {
            top_cell: "TOP".into(),
            polygons: polys,
            units_um: 1e-3,
        }
    }

    #[test]
    fn rtree_finds_violation() {
        // Two rectangles 0.05 um apart - violates 0.14 spacing.
        let lo = layout_of(vec![rect(0.0, 0.0, 1.0, 1.0), rect(1.05, 0.0, 2.0, 1.0)]);
        let v = check_space(&lo, "met1", 0.14, "S", "violation");
        assert_eq!(v.len(), 1, "got: {v:?}");
    }

    #[test]
    fn rtree_skips_well_separated() {
        let lo = layout_of(vec![rect(0.0, 0.0, 1.0, 1.0), rect(10.0, 0.0, 11.0, 1.0)]);
        let v = check_space(&lo, "met1", 0.14, "S", "violation");
        assert!(v.is_empty());
    }

    #[test]
    fn rtree_touching_not_violation() {
        // Edge-touching polygons share a net - not a violation.
        let lo = layout_of(vec![rect(0.0, 0.0, 1.0, 1.0), rect(1.0, 0.0, 2.0, 1.0)]);
        let v = check_space(&lo, "met1", 0.14, "S", "violation");
        assert!(v.is_empty());
    }
}
