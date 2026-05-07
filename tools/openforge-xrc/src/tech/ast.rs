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

/// Process corner. Affects the effective dielectric permittivity (and
/// hence all capacitances) by ±10% as a stand-in for a per-foundry
/// corner deck.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Corner {
    /// Best-case: low-k corner (k_eff scaled down).
    Min,
    /// Typical (default).
    #[default]
    Typ,
    /// Worst-case: high-k corner (k_eff scaled up).
    Max,
}

impl Corner {
    /// Multiplier applied to capacitance values for this corner.
    pub fn cap_scale(self) -> f64 {
        match self {
            Corner::Min => 0.90,
            Corner::Typ => 1.00,
            Corner::Max => 1.10,
        }
    }

    /// Short string label, suitable for SPEF filename suffixes.
    pub fn label(self) -> &'static str {
        match self {
            Corner::Min => "min",
            Corner::Typ => "typ",
            Corner::Max => "max",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TechFile {
    pub name: String,
    pub layers: Vec<LayerProps>,
    pub vias: Vec<ViaProps>,
    /// Active corner. Not serialized (always loads as Typ); set via CLI.
    #[serde(skip, default)]
    pub corner: CornerSetting,
}

/// Newtype around `Corner` that participates in the `Default` derive on
/// `TechFile`. Serde skips the field; defaults to `Corner::Typ`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CornerSetting(pub Corner);

impl Default for CornerSetting {
    fn default() -> Self {
        CornerSetting(Corner::Typ)
    }
}

impl TechFile {
    /// Currently-active corner (defaults to Typ).
    pub fn current_corner(&self) -> Corner {
        self.corner.0
    }

    /// Set active corner (consuming).
    pub fn with_corner(mut self, c: Corner) -> Self {
        self.corner = CornerSetting(c);
        self
    }

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
