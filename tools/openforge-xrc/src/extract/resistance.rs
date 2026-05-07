//! Per-segment resistance: R = sheet_R * length / width, plus via R.
//!
//! v0.2: multi-cut via support — total via array R is the single-cut R
//! divided by the number of cuts (parallel resistors).

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

/// Resistance contribution of a via array between two layers.
///
/// `tech.via(name).resistance_ohm` is the *per-cut* resistance; for a
/// multi-cut array we divide by the cut count (parallel combination).
pub fn via_resistance(tech: &TechFile, via_name: &str) -> f64 {
    match tech.via(via_name) {
        Some(v) => {
            let n = v.cut_count.max(1) as f64;
            v.resistance_ohm / n
        }
        None => 0.0,
    }
}
