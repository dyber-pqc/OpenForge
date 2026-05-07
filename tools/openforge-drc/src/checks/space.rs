//! Minimum-spacing check.
//!
//! v0.1 algorithm: for every pair of polygons on the layer, if their
//! bbox-gap is below the threshold, compute true polygon distance and
//! emit a violation if it is below the threshold.
//!
//! The bbox-gap pre-filter keeps this O(N^2) in the worst case but linear
//! on sparse layouts. A spatial index will replace it in v0.2.

use crate::gds::Layout;
use crate::geom::ops::polygon_distance;
use crate::violation::{Severity, Violation};

pub fn check_space(
    layout: &Layout,
    layer: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let polys: Vec<_> = layout.polygons_on(layer).collect();
    let mut out = Vec::new();
    const EPS: f64 = 1e-9;
    for i in 0..polys.len() {
        for j in (i + 1)..polys.len() {
            let a = polys[i];
            let b = polys[j];
            let bbox_gap = a.bbox.gap(&b.bbox);
            if bbox_gap > min_um {
                continue;
            }
            let d = polygon_distance(a, b);
            // Touching/overlapping polygons (d == 0) on the same layer
            // are *not* a spacing violation — they're a single net.
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
