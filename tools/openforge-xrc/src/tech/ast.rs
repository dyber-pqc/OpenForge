use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayerProps {
    pub name: String,
    /// Sheet resistance in ohm/sq.
    pub sheet_resistance_ohm: f64,
    /// Area capacitance in fF/um².
    pub cap_per_area_ff_per_um2: f64,
    /// Fringe capacitance in fF/um (per edge).
    pub fringe_cap_ff_per_um: f64,
    /// Minimum routing width in um.
    pub min_width_um: f64,
    /// Layer thickness in um.
    pub thickness_um: f64,
    /// Layer immediately above this routing layer (if any).
    pub above_layer: Option<String>,
    /// Vertical (inter-layer) dielectric thickness in um from this layer's
    /// top to `above_layer`'s bottom. Used for cross-layer (vertical) coupling
    /// capacitance. `None` for the top layer (no layer above).
    #[serde(default)]
    pub inter_layer_distance_um: Option<f64>,
    /// Distance (um) from this layer's bottom to the substrate / large
    /// reference plane. Used for the improved Sakurai fringe model.
    /// `None` falls back to `thickness_um` as a heuristic.
    #[serde(default)]
    pub height_to_substrate_um: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ViaProps {
    pub name: String,
    /// Resistance per via cut, in ohms.
    pub resistance_ohm: f64,
    /// (lower_layer, upper_layer)
    pub between: (String, String),
    /// Number of cuts in the via array (rows × cols). Defaults to 1 for a
    /// single-cut via. The effective via resistance is `resistance_ohm / cut_count`.
    #[serde(default = "default_cut_count")]
    pub cut_count: u32,
}

fn default_cut_count() -> u32 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TechFile {
    pub name: String,
    pub layers: Vec<LayerProps>,
    pub vias: Vec<ViaProps>,
}

impl TechFile {
    pub fn layer(&self, name: &str) -> Option<&LayerProps> {
        self.layers.iter().find(|l| l.name == name)
    }

    pub fn via(&self, name: &str) -> Option<&ViaProps> {
        self.vias.iter().find(|v| v.name == name)
    }

    /// Find a via type whose endpoints match (lower, upper) in either direction.
    pub fn via_between(&self, a: &str, b: &str) -> Option<&ViaProps> {
        self.vias.iter().find(|v| {
            (v.between.0 == a && v.between.1 == b) || (v.between.0 == b && v.between.1 == a)
        })
    }
}
