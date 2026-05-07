//! Minimum-width check.

use crate::gds::Layout;
use crate::geom::ops::min_polygon_width;
use crate::violation::{Severity, Violation};

pub fn check_width(
    layout: &Layout,
    layer: &str,
    min_um: f64,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let mut out = Vec::new();
    for poly in layout.polygons_on(layer) {
        let w = min_polygon_width(poly);
        // A small numerical tolerance avoids spurious failures on
        // floating-point round-off from GDS db-unit conversion.
        const EPS: f64 = 1e-9;
        if w + EPS < min_um {
            out.push(Violation {
                rule: rule_name.to_string(),
                layer: layer.to_string(),
                message: format!("{message} (measured {w:.4} um < {min_um:.4} um)"),
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
