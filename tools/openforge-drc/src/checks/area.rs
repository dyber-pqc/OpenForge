//! Minimum polygon-area check.
//!
//! Walks every polygon on `layer` and reports any whose signed area
//! (absolute value) is below `min_um2`. Uses the shoelace formula on the
//! polygon's outer ring — sufficient for the simple, hole-free polygons
//! the DRC engine handles in v0.x.

use crate::gds::Layout;
use crate::geom::Polygon;
use crate::violation::{Severity, Violation};

/// Shoelace area of a polygon's outer ring. Result is in the polygon's
/// native units (um^2 since polygon coords are in microns). Always returns
/// a non-negative number.
fn polygon_area(p: &Polygon) -> f64 {
    let n = p.points.len();
    if n < 3 {
        return 0.0;
    }
    // Trim duplicate closing point.
    let last = p.points[n - 1];
    let first = p.points[0];
    let m = if (last.0 - first.0).abs() < f64::EPSILON && (last.1 - first.1).abs() < f64::EPSILON {
        n - 1
    } else {
        n
    };
    if m < 3 {
        return 0.0;
    }
    let mut sum = 0.0;
    for i in 0..m {
        let (x0, y0) = p.points[i];
        let (x1, y1) = p.points[(i + 1) % m];
        sum += x0 * y1 - x1 * y0;
    }
    (sum * 0.5).abs()
}

pub fn check_area(
    layout: &Layout,
    layer: &str,
    min_um2: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    const EPS: f64 = 1e-12;
    let mut out = Vec::new();
    for poly in layout.polygons_on(layer) {
        let a = polygon_area(poly);
        if a + EPS < min_um2 {
            out.push(Violation {
                rule: rule_name.to_string(),
                layer: layer.to_string(),
                message: format!("{message} (measured {a:.6} um^2 < {min_um2:.6} um^2)"),
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

    fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon {
        Polygon::new("L", vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "TOP")
    }
    fn lo(polys: Vec<Polygon>) -> Layout {
        Layout {
            top_cell: "TOP".into(),
            polygons: polys,
            units_um: 1e-3,
        }
    }

    #[test]
    fn rect_area_correct() {
        let r = rect(0.0, 0.0, 2.0, 3.0);
        assert!((polygon_area(&r) - 6.0).abs() < 1e-9);
    }

    #[test]
    fn detects_too_small() {
        let l = lo(vec![rect(0.0, 0.0, 0.1, 0.1)]); // area 0.01
        let v = check_area(&l, "L", 0.083, "A", "small");
        assert_eq!(v.len(), 1);
    }

    #[test]
    fn passes_when_large_enough() {
        let l = lo(vec![rect(0.0, 0.0, 1.0, 1.0)]); // area 1.0
        let v = check_area(&l, "L", 0.083, "A", "small");
        assert!(v.is_empty());
    }
}
