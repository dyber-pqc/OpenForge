//! Notch (intra-polygon gap) check.
//!
//! A "notch" is a concave indentation cut into a single polygon's boundary.
//! In Magic this is `edge4way` applied to a single layer. For our purposes
//! we approximate: walk every pair of non-adjacent edges in each polygon,
//! and if two parallel edges face each other (their projections overlap
//! along their shared axis) with a gap below `min_um`, that gap is the
//! notch width.
//!
//! For a simple convex rectangle (4 vertices) no two non-adjacent edges
//! "face" each other across an interior segment in the notch sense, so the
//! check is a no-op (the bounding extent is what `width` already covers).
//! L- and U- shaped polygons surface their internal edges here.

use crate::gds::Layout;
use crate::violation::{Severity, Violation};

/// Returns Some(distance) if (a0,a1) and (b0,b1) are parallel axis-aligned
/// edges that face each other (their parallel-axis spans overlap and the
/// perpendicular distance between them is positive). Returns None otherwise.
fn facing_gap(a0: (f64, f64), a1: (f64, f64), b0: (f64, f64), b1: (f64, f64)) -> Option<f64> {
    const EPS: f64 = 1e-12;
    // Vertical edges (same x along the edge).
    if (a0.0 - a1.0).abs() < EPS && (b0.0 - b1.0).abs() < EPS {
        let dx = (a0.0 - b0.0).abs();
        if dx < EPS {
            return None;
        }
        let (a_lo, a_hi) = (a0.1.min(a1.1), a0.1.max(a1.1));
        let (b_lo, b_hi) = (b0.1.min(b1.1), b0.1.max(b1.1));
        let overlap = a_lo.max(b_lo) < a_hi.min(b_hi) - EPS;
        if overlap {
            return Some(dx);
        }
    }
    // Horizontal edges.
    if (a0.1 - a1.1).abs() < EPS && (b0.1 - b1.1).abs() < EPS {
        let dy = (a0.1 - b0.1).abs();
        if dy < EPS {
            return None;
        }
        let (a_lo, a_hi) = (a0.0.min(a1.0), a0.0.max(a1.0));
        let (b_lo, b_hi) = (b0.0.min(b1.0), b0.0.max(b1.0));
        let overlap = a_lo.max(b_lo) < a_hi.min(b_hi) - EPS;
        if overlap {
            return Some(dy);
        }
    }
    None
}

pub fn check_notch(
    layout: &Layout,
    layer: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    const EPS: f64 = 1e-9;
    let mut out = Vec::new();
    for poly in layout.polygons_on(layer) {
        let n = poly.points.len();
        if n < 6 {
            // A 4-vertex rectangle has no notch (any internal facing gap is
            // its bounding width, which `width` already covers).
            continue;
        }
        // Trim duplicate closing vertex if present.
        let last = poly.points[n - 1];
        let first = poly.points[0];
        let m =
            if (last.0 - first.0).abs() < f64::EPSILON && (last.1 - first.1).abs() < f64::EPSILON {
                n - 1
            } else {
                n
            };
        if m < 6 {
            continue;
        }
        let mut min_seen: Option<f64> = None;
        for i in 0..m {
            let a0 = poly.points[i];
            let a1 = poly.points[(i + 1) % m];
            for j in (i + 2)..m {
                if i == 0 && j == m - 1 {
                    // Adjacent (wrap-around) edge; skip.
                    continue;
                }
                let b0 = poly.points[j];
                let b1 = poly.points[(j + 1) % m];
                if let Some(d) = facing_gap(a0, a1, b0, b1) {
                    if d + EPS < min_um {
                        min_seen = Some(min_seen.map_or(d, |cur| cur.min(d)));
                    }
                }
            }
        }
        if let Some(d) = min_seen {
            out.push(Violation {
                rule: rule_name.to_string(),
                layer: layer.to_string(),
                message: format!("{message} (notch {d:.4} um < {min_um:.4} um)"),
                coords_um: (
                    poly.bbox.x_min,
                    poly.bbox.y_min,
                    poly.bbox.x_max,
                    poly.bbox.y_max,
                ),
                severity: Severity::Error,
                cell: poly.cell.clone(),
            });
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::geom::Polygon;

    fn lo(polys: Vec<Polygon>) -> Layout {
        Layout {
            top_cell: "TOP".into(),
            polygons: polys,
            units_um: 1e-3,
        }
    }

    #[test]
    fn rectangle_has_no_notch() {
        let r = Polygon::new(
            "L",
            vec![(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            "TOP",
        );
        let l = lo(vec![r]);
        let v = check_notch(&l, "L", 0.5, "N", "msg");
        assert!(v.is_empty());
    }

    #[test]
    fn u_shape_with_narrow_slot_fails() {
        // U-shape: outer 0..1.0 wide, 0..1.0 tall, with a 0.05-wide slot
        // cut from the top center down to y=0.5.
        // CCW vertices.
        let pts = vec![
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.525, 1.0),
            (0.525, 0.5),
            (0.475, 0.5),
            (0.475, 1.0),
            (0.0, 1.0),
        ];
        let p = Polygon::new("L", pts, "TOP");
        let l = lo(vec![p]);
        let v = check_notch(&l, "L", 0.14, "N", "narrow notch");
        assert_eq!(v.len(), 1);
    }

    #[test]
    fn u_shape_with_wide_slot_passes() {
        let pts = vec![
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.7, 1.0),
            (0.7, 0.5),
            (0.3, 0.5),
            (0.3, 1.0),
            (0.0, 1.0),
        ];
        let p = Polygon::new("L", pts, "TOP");
        let l = lo(vec![p]);
        let v = check_notch(&l, "L", 0.14, "N", "msg");
        assert!(v.is_empty());
    }
}
