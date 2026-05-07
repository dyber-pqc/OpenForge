//! Polygon operations: distance, edge measurement.
//!
//! Backed by the `geo` crate. Kept narrow on purpose for v0.1.

use super::polygon::Polygon;
use geo::{Distance, Euclidean};
use geo_types::{Coord, LineString, Polygon as GeoPolygon};

/// Convert our polygon to a `geo` Polygon (no holes).
pub fn to_geo(p: &Polygon) -> GeoPolygon<f64> {
    let coords: Vec<Coord<f64>> = p.points.iter().map(|&(x, y)| Coord { x, y }).collect();
    GeoPolygon::new(LineString::from(coords), vec![])
}

/// Edge-to-edge distance between two polygons, 0 if they touch or overlap.
pub fn polygon_distance(a: &Polygon, b: &Polygon) -> f64 {
    let ga = to_geo(a);
    let gb = to_geo(b);
    Euclidean.distance(&ga, &gb)
}

/// Approximate minimum interior "width" of a polygon by checking the
/// distance between every pair of non-adjacent edges and taking the
/// minimum. For axis-aligned rectangles this is just min(width, height).
///
/// This is intentionally simple — a real DRC engine uses the medial axis
/// or shrink/grow operations. For v0.1 it works well enough on the kinds
/// of polygons routers emit.
pub fn min_polygon_width(p: &Polygon) -> f64 {
    let n = p.points.len();
    if n < 3 {
        return 0.0;
    }
    // Trim duplicate closing point if present.
    let last = p.points[n - 1];
    let first = p.points[0];
    let effective =
        if (last.0 - first.0).abs() < f64::EPSILON && (last.1 - first.1).abs() < f64::EPSILON {
            n - 1
        } else {
            n
        };
    if effective < 3 {
        return 0.0;
    }

    // For an axis-aligned rectangle, fast-path on the bbox.
    let bw = p.bbox.width();
    let bh = p.bbox.height();
    if effective == 4 && is_axis_aligned_rect(p) {
        return bw.min(bh);
    }

    // General case: distance between non-adjacent edges.
    let mut min_d = f64::INFINITY;
    for i in 0..effective {
        let a0 = p.points[i];
        let a1 = p.points[(i + 1) % effective];
        for j in (i + 2)..effective {
            // Skip the edge that wraps around to be adjacent to edge i.
            if i == 0 && j == effective - 1 {
                continue;
            }
            let b0 = p.points[j];
            let b1 = p.points[(j + 1) % effective];
            let d = segment_segment_distance(a0, a1, b0, b1);
            if d < min_d {
                min_d = d;
            }
        }
    }
    if min_d.is_finite() {
        min_d
    } else {
        bw.min(bh)
    }
}

fn is_axis_aligned_rect(p: &Polygon) -> bool {
    if p.points.len() < 4 {
        return false;
    }
    for i in 0..4 {
        let (x0, y0) = p.points[i];
        let (x1, y1) = p.points[(i + 1) % 4];
        if (x0 - x1).abs() > f64::EPSILON && (y0 - y1).abs() > f64::EPSILON {
            return false;
        }
    }
    true
}

fn segment_segment_distance(a0: (f64, f64), a1: (f64, f64), b0: (f64, f64), b1: (f64, f64)) -> f64 {
    point_segment_distance(a0, b0, b1)
        .min(point_segment_distance(a1, b0, b1))
        .min(point_segment_distance(b0, a0, a1))
        .min(point_segment_distance(b1, a0, a1))
}

fn point_segment_distance(p: (f64, f64), s0: (f64, f64), s1: (f64, f64)) -> f64 {
    let dx = s1.0 - s0.0;
    let dy = s1.1 - s0.1;
    let len2 = dx * dx + dy * dy;
    if len2 < f64::EPSILON {
        let ex = p.0 - s0.0;
        let ey = p.1 - s0.1;
        return (ex * ex + ey * ey).sqrt();
    }
    let t = (((p.0 - s0.0) * dx + (p.1 - s0.1) * dy) / len2).clamp(0.0, 1.0);
    let cx = s0.0 + t * dx;
    let cy = s0.1 + t * dy;
    let ex = p.0 - cx;
    let ey = p.1 - cy;
    (ex * ex + ey * ey).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::geom::Polygon;

    fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon {
        Polygon::new("L", vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "TOP")
    }

    #[test]
    fn rectangle_min_width() {
        let r = rect(0.0, 0.0, 0.10, 1.0);
        assert!((min_polygon_width(&r) - 0.10).abs() < 1e-9);
    }

    #[test]
    fn rectangle_distance() {
        let a = rect(0.0, 0.0, 1.0, 1.0);
        let b = rect(2.0, 0.0, 3.0, 1.0);
        assert!((polygon_distance(&a, &b) - 1.0).abs() < 1e-9);
    }
}
