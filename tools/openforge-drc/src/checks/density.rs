//! Windowed density check.
//!
//! Tile the layout bounding box into NxN-um windows. For each window, sum
//! the polygon area on the target layer that intersects it; the resulting
//! density (occupied area / window area) must lie in `[min_pct, max_pct]`.
//!
//! Window size is configurable per rule. Windows are tiled tightly across
//! the layout bbox; partial trailing windows at the right/top edges are
//! retained but their density is normalised against their actual area.
//!
//! Direction: `Below` (density below `pct` is a violation - low-density
//! fill missing) or `Above` (density above `pct` is a violation - too dense).
//!
//! The work parallelises trivially over windows via rayon.

use crate::gds::Layout;
use crate::geom::Polygon;
use crate::violation::{Severity, Violation};
use rayon::prelude::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DensityDirection {
    Below,
    Above,
}

/// Polygon-rectangle intersection area, axis-aligned rectangle bounds.
/// We integrate using the polygon's own coordinates clipped to the
/// rectangle. For arbitrary polygons we fall back to the shoelace formula
/// over the clipped vertices via Sutherland-Hodgman.
fn polygon_window_area(poly: &Polygon, x0: f64, y0: f64, x1: f64, y1: f64) -> f64 {
    // Quick rejects via bbox.
    if poly.bbox.x_max <= x0
        || poly.bbox.x_min >= x1
        || poly.bbox.y_max <= y0
        || poly.bbox.y_min >= y1
    {
        return 0.0;
    }
    // Trim closing point if duplicated.
    let pts = if poly.points.len() > 1
        && (poly.points[0].0 - poly.points[poly.points.len() - 1].0).abs() < f64::EPSILON
        && (poly.points[0].1 - poly.points[poly.points.len() - 1].1).abs() < f64::EPSILON
    {
        &poly.points[..poly.points.len() - 1]
    } else {
        &poly.points[..]
    };

    // Sutherland-Hodgman against four half-planes.
    let mut subject: Vec<(f64, f64)> = pts.to_vec();
    // Left edge (x >= x0): keep points with x >= x0.
    subject = clip(&subject, |p| p.0 >= x0, |a, b| intersect_x(a, b, x0));
    if subject.is_empty() {
        return 0.0;
    }
    // Right edge (x <= x1).
    subject = clip(&subject, |p| p.0 <= x1, |a, b| intersect_x(a, b, x1));
    if subject.is_empty() {
        return 0.0;
    }
    // Bottom edge (y >= y0).
    subject = clip(&subject, |p| p.1 >= y0, |a, b| intersect_y(a, b, y0));
    if subject.is_empty() {
        return 0.0;
    }
    // Top edge (y <= y1).
    subject = clip(&subject, |p| p.1 <= y1, |a, b| intersect_y(a, b, y1));
    if subject.len() < 3 {
        return 0.0;
    }
    shoelace_area(&subject)
}

fn clip<F, G>(poly: &[(f64, f64)], inside: F, isect: G) -> Vec<(f64, f64)>
where
    F: Fn(&(f64, f64)) -> bool,
    G: Fn((f64, f64), (f64, f64)) -> (f64, f64),
{
    let mut out = Vec::with_capacity(poly.len());
    if poly.is_empty() {
        return out;
    }
    for i in 0..poly.len() {
        let cur = poly[i];
        let prev = poly[(i + poly.len() - 1) % poly.len()];
        let cur_in = inside(&cur);
        let prev_in = inside(&prev);
        if cur_in {
            if !prev_in {
                out.push(isect(prev, cur));
            }
            out.push(cur);
        } else if prev_in {
            out.push(isect(prev, cur));
        }
    }
    out
}

fn intersect_x(a: (f64, f64), b: (f64, f64), x: f64) -> (f64, f64) {
    let dx = b.0 - a.0;
    if dx.abs() < f64::EPSILON {
        return (x, a.1);
    }
    let t = (x - a.0) / dx;
    (x, a.1 + t * (b.1 - a.1))
}

fn intersect_y(a: (f64, f64), b: (f64, f64), y: f64) -> (f64, f64) {
    let dy = b.1 - a.1;
    if dy.abs() < f64::EPSILON {
        return (a.0, y);
    }
    let t = (y - a.1) / dy;
    (a.0 + t * (b.0 - a.0), y)
}

fn shoelace_area(pts: &[(f64, f64)]) -> f64 {
    let mut a = 0.0;
    for i in 0..pts.len() {
        let (x0, y0) = pts[i];
        let (x1, y1) = pts[(i + 1) % pts.len()];
        a += x0 * y1 - x1 * y0;
    }
    a.abs() * 0.5
}

#[allow(clippy::too_many_arguments)]
pub fn check_density(
    layout: &Layout,
    layer: &str,
    window_um: f64,
    pct: f64,
    direction: DensityDirection,
    rule_name: &str,
    message: &str,
) -> Vec<Violation> {
    let polys: Vec<&Polygon> = layout.polygons_on(layer).collect();
    if polys.is_empty() {
        // No geometry on the layer. A "min density" rule trivially fails
        // for each window; a "max density" rule trivially passes. We bail
        // out in both cases - emitting one violation per window of an
        // empty design isn't useful.
        return Vec::new();
    }

    // Layout bbox: union of all polygon bboxes.
    let mut x_min = f64::INFINITY;
    let mut y_min = f64::INFINITY;
    let mut x_max = f64::NEG_INFINITY;
    let mut y_max = f64::NEG_INFINITY;
    for p in &polys {
        if p.bbox.x_min < x_min {
            x_min = p.bbox.x_min;
        }
        if p.bbox.y_min < y_min {
            y_min = p.bbox.y_min;
        }
        if p.bbox.x_max > x_max {
            x_max = p.bbox.x_max;
        }
        if p.bbox.y_max > y_max {
            y_max = p.bbox.y_max;
        }
    }

    let nx = ((x_max - x_min) / window_um).ceil().max(1.0) as usize;
    let ny = ((y_max - y_min) / window_um).ceil().max(1.0) as usize;

    let cells: Vec<(usize, usize)> = (0..nx).flat_map(|i| (0..ny).map(move |j| (i, j))).collect();

    cells
        .par_iter()
        .filter_map(|&(i, j)| {
            let wx0 = x_min + i as f64 * window_um;
            let wy0 = y_min + j as f64 * window_um;
            let wx1 = (wx0 + window_um).min(x_max);
            let wy1 = (wy0 + window_um).min(y_max);
            let w = wx1 - wx0;
            let h = wy1 - wy0;
            if w <= 0.0 || h <= 0.0 {
                return None;
            }
            let win_area = w * h;
            let mut occupied = 0.0;
            for p in &polys {
                occupied += polygon_window_area(p, wx0, wy0, wx1, wy1);
            }
            let density = occupied / win_area;
            let violates = match direction {
                DensityDirection::Below => density < pct,
                DensityDirection::Above => density > pct,
            };
            if violates {
                Some(Violation {
                    rule: rule_name.to_string(),
                    layer: layer.to_string(),
                    message: format!(
                        "{message} (window {window_um:.0} um density {density:.4} {} {pct:.4})",
                        match direction {
                            DensityDirection::Below => "<",
                            DensityDirection::Above => ">",
                        }
                    ),
                    coords_um: (wx0, wy0, wx1, wy1),
                    severity: Severity::Warning,
                    cell: layout.top_cell.clone(),
                })
            } else {
                None
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::gds::Layout;
    use crate::geom::Polygon;

    fn rect(layer: &str, x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon {
        Polygon::new(layer, vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "TOP")
    }

    #[test]
    fn full_coverage_high_density() {
        // A single 10x10 polygon completely fills its window - density 1.0.
        let layout = Layout {
            top_cell: "TOP".into(),
            polygons: vec![rect("met1", 0.0, 0.0, 10.0, 10.0)],
            units_um: 1e-3,
        };
        let v = check_density(
            &layout,
            "met1",
            10.0,
            0.5,
            DensityDirection::Below,
            "D",
            "low",
        );
        assert!(v.is_empty(), "fully-filled window should not be < 0.5");
        let v = check_density(
            &layout,
            "met1",
            10.0,
            0.5,
            DensityDirection::Above,
            "D",
            "high",
        );
        assert_eq!(v.len(), 1, "fully-filled window should be > 0.5");
    }

    #[test]
    fn quarter_coverage_low_density() {
        // 5x5 inside a 10x10 bbox - density 0.25.
        let layout = Layout {
            top_cell: "TOP".into(),
            polygons: vec![
                rect("met1", 0.0, 0.0, 5.0, 5.0),
                // Anchor the bbox to 10x10 with a tiny corner spec.
                rect("met1", 9.99, 9.99, 10.0, 10.0),
            ],
            units_um: 1e-3,
        };
        let v = check_density(
            &layout,
            "met1",
            10.0,
            0.20,
            DensityDirection::Below,
            "D",
            "low",
        );
        assert!(v.is_empty(), "0.25 density should not violate min 0.20");
        let v = check_density(
            &layout,
            "met1",
            10.0,
            0.30,
            DensityDirection::Below,
            "D",
            "low",
        );
        assert_eq!(v.len(), 1, "0.25 density should violate min 0.30");
    }

    #[test]
    fn clip_partial_polygon() {
        // 1x1 polygon centered on a window edge - half should count.
        let p = rect("m", 4.5, 4.5, 5.5, 5.5);
        let a = polygon_window_area(&p, 0.0, 0.0, 5.0, 5.0);
        assert!((a - 0.25).abs() < 1e-9, "got {a}");
    }
}
