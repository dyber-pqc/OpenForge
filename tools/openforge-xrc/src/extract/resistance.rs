//! Per-segment resistance: R = sheet_R * length / width, plus via R.

use crate::tech::TechFile;

/// Wire resistance for a routed segment of given length and width on `layer`.
pub fn wire_resistance(tech: &TechFile, layer: &str, length_um: f64, width_um: f64) -> f64 {
    if width_um <= 0.0 || length_um <= 0.0 {
        return 0.0;
    }
    match tech.layer(layer) {
        Some(lp) => lp.sheet_resistance_ohm * length_um / width_um,
        None => 0.0,
    }
}

/// Resistance contribution of a via cut between two layers.
pub fn via_resistance(tech: &TechFile, via_name: &str) -> f64 {
    tech.via(via_name).map(|v| v.resistance_ohm).unwrap_or(0.0)
}
