//! Inter-layer minimum spacing (separation) check.
//!
//! Differs from `space.rs` in two ways:
//!   - Operates across two distinct layers.
//!   - Touching/overlapping shapes (distance ≤ 0) ARE violations, because
//!     the two layers belong to different nets.

use crate::gds::Layout;
use crate::geom::ops::polygon_distance;
use crate::geom::Polygon;
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

pub fn check_separation(
    layout: &Layout,
    layer_a: &str,
    layer_b: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let a_polys: Vec<&Polygon> = layout.polygons_on(layer_a).collect();
    let b_polys: Vec<&Polygon> = layout.polygons_on(layer_b).collect();
    if a_polys.is_empty() || b_polys.is_empty() {
        return Vec::new();
    }

    let items: Vec<IndexedBbox> = b_polys
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
    for a in &a_polys {
        let query = AABB::from_corners(
            [a.bbox.x_min - min_um, a.bbox.y_min - min_um],
            [a.bbox.x_max + min_um, a.bbox.y_max + min_um],
        );
        for cand in tree.locate_in_envelope_intersecting(&query) {
            let b = b_polys[cand.idx];
            let bbox_gap = a.bbox.gap(&b.bbox);
            if bbox_gap > min_um {
                continue;
            }
            let d = polygon_distance(a, b);
            // Inter-layer: any distance below min_um (including touching/
            // overlap at d == 0) is a violation.
            if d + EPS < min_um {
                let x_min = a.bbox.x_min.min(b.bbox.x_min);
                let y_min = a.bbox.y_min.min(b.bbox.y_min);
                let x_max = a.bbox.x_max.max(b.bbox.x_max);
                let y_max = a.bbox.y_max.max(b.bbox.y_max);
                out.push(Violation {
                    rule: rule_name.to_string(),
                    layer: format!("{layer_a}/{layer_b}"),
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
    fn detects_close_pair_across_layers() {
        let l = lo(vec![
            rect("nwell", 0.0, 0.0, 1.0, 1.0),
            rect("diff", 1.05, 0.0, 2.0, 1.0),
        ]);
        let v = check_separation(&l, "nwell", "diff", 0.34, "S", "msg");
        assert_eq!(v.len(), 1);
    }

    #[test]
    fn touching_across_layers_is_violation() {
        let l = lo(vec![
            rect("nwell", 0.0, 0.0, 1.0, 1.0),
            rect("diff", 1.0, 0.0, 2.0, 1.0),
        ]);
        let v = check_separation(&l, "nwell", "diff", 0.34, "S", "msg");
        assert_eq!(v.len(), 1, "edge-touching across distinct layers fails");
    }

    #[test]
    fn far_apart_passes() {
        let l = lo(vec![
            rect("nwell", 0.0, 0.0, 1.0, 1.0),
            rect("diff", 5.0, 0.0, 6.0, 1.0),
        ]);
        let v = check_separation(&l, "nwell", "diff", 0.34, "S", "msg");
        assert!(v.is_empty());
    }
}
