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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ViaProps {
    pub name: String,
    /// Resistance per via cut, in ohms.
    pub resistance_ohm: f64,
    /// (lower_layer, upper_layer)
    pub between: (String, String),
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
