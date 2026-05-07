//! Per-segment capacitance: parallel-plate (area) + fringe (perimeter).

use crate::tech::TechFile;

/// C_total in fF for a wire of given length × width on `layer`.
///
/// Uses:
///   C_area   = cap_per_area * length * width
///   C_fringe = fringe_cap   * 2 * length     (two long edges)
pub fn wire_capacitance(tech: &TechFile, layer: &str, length_um: f64, width_um: f64) -> f64 {
    if length_um <= 0.0 || width_um <= 0.0 {
        return 0.0;
    }
    let lp = match tech.layer(layer) {
        Some(l) => l,
        None => return 0.0,
    };
    let c_area = lp.cap_per_area_ff_per_um2 * length_um * width_um;
    let c_fringe = lp.fringe_cap_ff_per_um * 2.0 * length_um;
    c_area + c_fringe
}
