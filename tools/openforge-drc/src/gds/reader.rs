//! Read a GDSII file into a flat list of polygons (one cell, no hierarchy
//! flattening for v0.1 — we just take the top cell's geometry).

use crate::geom::Polygon;
use crate::rules::ast::LayerSpec;
use crate::{DrcError, Result};
use std::collections::HashMap;
use std::path::Path;

/// A loaded layout. Polygons are tagged by *layer name* so check code never
/// has to know about GDS layer numbers.
#[derive(Debug, Clone, Default)]
pub struct Layout {
    /// Top cell name (used for RDB output).
    pub top_cell: String,
    /// All polygons in the design.
    pub polygons: Vec<Polygon>,
    /// User units per database unit (= unit_in_meters / 1e-6).
    pub units_um: f64,
}

impl Layout {
    pub fn polygons_on<'a>(&'a self, layer: &'a str) -> impl Iterator<Item = &'a Polygon> + 'a {
        self.polygons.iter().filter(move |p| p.layer == layer)
    }
}

/// Read a GDS file. The supplied `layers` map lets us assign layer names
/// to polygons based on (gds_layer, gds_datatype). If a polygon is on a
/// (layer, datatype) pair not in the map, it is dropped.
///
/// In v0.1 we read all polygons across all cells and tag them with the
/// top cell name; this is sufficient for flat layouts.
pub fn read_gds_with_layers(path: &Path, layers: &HashMap<String, LayerSpec>) -> Result<Layout> {
    let lib = gds21::GdsLibrary::load(path).map_err(|e| DrcError::Gds(e.to_string()))?;

    // Build reverse lookup: (layer_no, datatype) -> name.
    // datatype defaults to 0 if unspecified.
    let mut by_id: HashMap<(i16, i16), String> = HashMap::new();
    for (name, spec) in layers {
        by_id.insert((spec.layer as i16, spec.datatype as i16), name.clone());
    }

    // Use first/top cell as the top cell. gds21 doesn't expose explicit
    // "top cell"; convention: first cell with no parent.
    let top_cell = lib
        .structs
        .first()
        .map(|s| s.name.clone())
        .unwrap_or_else(|| "TOP".to_string());

    // Database-unit size in microns. (db_unit() returns meters per DB unit.)
    let units_um = lib.units.db_unit() / 1e-6;

    let mut polygons = Vec::new();
    for s in &lib.structs {
        for elem in &s.elems {
            if let gds21::GdsElement::GdsBoundary(b) = elem {
                let layer_id = (b.layer, b.datatype);
                let layer_name = match by_id.get(&layer_id) {
                    Some(n) => n.clone(),
                    None => continue,
                };
                let pts: Vec<(f64, f64)> =
                    b.xy.iter()
                        .map(|p| (p.x as f64 * units_um, p.y as f64 * units_um))
                        .collect();
                if pts.len() >= 3 {
                    polygons.push(Polygon::new(layer_name, pts, &s.name));
                }
            }
            // BOX elements (rare) — treat like a rectangle boundary.
            if let gds21::GdsElement::GdsBox(b) = elem {
                let layer_id = (b.layer, b.boxtype);
                let layer_name = match by_id.get(&layer_id) {
                    Some(n) => n.clone(),
                    None => continue,
                };
                let pts: Vec<(f64, f64)> =
                    b.xy.iter()
                        .map(|p| (p.x as f64 * units_um, p.y as f64 * units_um))
                        .collect();
                if pts.len() >= 3 {
                    polygons.push(Polygon::new(layer_name, pts, &s.name));
                }
            }
        }
    }

    Ok(Layout {
        top_cell,
        polygons,
        units_um,
    })
}

/// Convenience: read a GDS without an explicit layer map. All boundaries
/// are tagged with a synthetic name "L<layer>D<datatype>".
pub fn read_gds(path: &Path) -> Result<Layout> {
    let lib = gds21::GdsLibrary::load(path).map_err(|e| DrcError::Gds(e.to_string()))?;
    let top_cell = lib
        .structs
        .first()
        .map(|s| s.name.clone())
        .unwrap_or_else(|| "TOP".to_string());
    let units_um = lib.units.db_unit() / 1e-6;

    let mut polygons = Vec::new();
    for s in &lib.structs {
        for elem in &s.elems {
            if let gds21::GdsElement::GdsBoundary(b) = elem {
                let name = format!("L{}D{}", b.layer, b.datatype);
                let pts: Vec<(f64, f64)> =
                    b.xy.iter()
                        .map(|p| (p.x as f64 * units_um, p.y as f64 * units_um))
                        .collect();
                if pts.len() >= 3 {
                    polygons.push(Polygon::new(name, pts, &s.name));
                }
            }
        }
    }
    Ok(Layout {
        top_cell,
        polygons,
        units_um,
    })
}
