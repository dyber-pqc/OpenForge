//! Eager materialisation of derived layers (boolean ops on polygon sets).
//!
//! For v0.3 we use bbox-level approximations for the boolean operations:
//!
//! - `inside(B)`:  keep polygons of A whose bbox is fully contained in
//!   some polygon-of-B's bbox.
//! - `outside(B)`: keep polygons of A whose bbox does NOT intersect any
//!   polygon-of-B's bbox.
//! - `not(B)`:     same as `outside(B)` for v0.3 (true subtraction needs
//!   polygon clipping; deferred).
//! - `and(B)`:     keep polygons of A whose bbox intersects any of B.
//! - `or(B)`:      union — emit copies of all polygons in A and B.
//!
//! These are coarse but correct for axis-aligned rectangular geometry,
//! which covers most cases that real PDK derived layers actually need
//! (e.g. "diff outside nwell" — both diff and nwell are rectangle-ish).
//! v0.4 will swap in true polygon clipping via the `geo` crate.

use crate::gds::Layout;
use crate::geom::Polygon;
use crate::rules::ast::{BoolOp, DerivedLayer};

/// Apply each derived-layer definition in order, appending the resulting
/// polygons to `layout.polygons` under the derived name. Layers appear in
/// declaration order so a later derived layer can reference an earlier one.
pub fn materialize_derived(layout: &mut Layout, derived: &[DerivedLayer]) {
    for d in derived {
        let new_polys = compute_op(layout, d);
        layout.polygons.extend(new_polys);
    }
}

fn compute_op(layout: &Layout, d: &DerivedLayer) -> Vec<Polygon> {
    let a_polys: Vec<&Polygon> = layout.polygons_on(&d.a).collect();
    let b_polys: Vec<&Polygon> = layout.polygons_on(&d.b).collect();
    match d.op {
        BoolOp::Inside => {
            let mut out = Vec::new();
            for a in &a_polys {
                if b_polys.iter().any(|b| bbox_contains(&b.bbox, &a.bbox)) {
                    out.push(rename(a, &d.name));
                }
            }
            out
        }
        BoolOp::Outside | BoolOp::Not => {
            let mut out = Vec::new();
            for a in &a_polys {
                let touches = b_polys.iter().any(|b| bbox_intersects(&a.bbox, &b.bbox));
                if !touches {
                    out.push(rename(a, &d.name));
                }
            }
            out
        }
        BoolOp::And => {
            let mut out = Vec::new();
            for a in &a_polys {
                if b_polys.iter().any(|b| bbox_intersects(&a.bbox, &b.bbox)) {
                    out.push(rename(a, &d.name));
                }
            }
            out
        }
        BoolOp::Or => {
            let mut out = Vec::with_capacity(a_polys.len() + b_polys.len());
            for a in &a_polys {
                out.push(rename(a, &d.name));
            }
            for b in &b_polys {
                out.push(rename(b, &d.name));
            }
            out
        }
    }
}

fn rename(p: &Polygon, new_layer: &str) -> Polygon {
    Polygon {
        layer: new_layer.to_string(),
        points: p.points.clone(),
        bbox: p.bbox,
        cell: p.cell.clone(),
    }
}

fn bbox_contains(outer: &crate::geom::Bbox, inner: &crate::geom::Bbox) -> bool {
    outer.x_min <= inner.x_min
        && outer.y_min <= inner.y_min
        && outer.x_max >= inner.x_max
        && outer.y_max >= inner.y_max
}

fn bbox_intersects(a: &crate::geom::Bbox, b: &crate::geom::Bbox) -> bool {
    !(a.x_max < b.x_min || b.x_max < a.x_min || a.y_max < b.y_min || b.y_max < a.y_min)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::gds::Layout;

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
    fn outside_filters_overlapping() {
        let mut l = lo(vec![
            rect("diff", 0.0, 0.0, 1.0, 1.0), // overlaps nwell
            rect("diff", 5.0, 5.0, 6.0, 6.0), // outside nwell
            rect("nwell", 0.5, 0.5, 2.0, 2.0),
        ]);
        materialize_derived(
            &mut l,
            &[DerivedLayer {
                name: "d_outside".into(),
                op: BoolOp::Outside,
                a: "diff".into(),
                b: "nwell".into(),
            }],
        );
        let derived: Vec<&Polygon> = l.polygons_on("d_outside").collect();
        assert_eq!(derived.len(), 1);
        assert_eq!(derived[0].bbox.x_min, 5.0);
    }

    #[test]
    fn or_unions_polygons() {
        let mut l = lo(vec![
            rect("a", 0.0, 0.0, 1.0, 1.0),
            rect("b", 5.0, 5.0, 6.0, 6.0),
        ]);
        materialize_derived(
            &mut l,
            &[DerivedLayer {
                name: "u".into(),
                op: BoolOp::Or,
                a: "a".into(),
                b: "b".into(),
            }],
        );
        assert_eq!(l.polygons_on("u").count(), 2);
    }

    #[test]
    fn inside_keeps_contained() {
        let mut l = lo(vec![
            rect("a", 0.5, 0.5, 0.7, 0.7),
            rect("b", 0.0, 0.0, 1.0, 1.0),
        ]);
        materialize_derived(
            &mut l,
            &[DerivedLayer {
                name: "i".into(),
                op: BoolOp::Inside,
                a: "a".into(),
                b: "b".into(),
            }],
        );
        assert_eq!(l.polygons_on("i").count(), 1);
    }
}
