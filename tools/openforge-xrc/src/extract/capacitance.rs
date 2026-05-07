//! Per-segment self-capacitance to substrate / large reference plane.
//!
//! v0.2: Sakurai–Tamaru (1983) closed-form approximation. For a wire of
//! width `w`, thickness `t`, length `l` at height `h` above a ground plane
//! with dielectric permittivity `eps`,
//!
//! ```text
//!   C_total = eps * l * [ w/h
//!                       + 0.77
//!                       + 1.06 * (w/h)^0.25
//!                       + 1.06 * (t/h)^0.50 ]
//! ```
//!
//! The first term is the parallel-plate (area) component; the remaining
//! three capture two-edge fringe + thickness-edge fringe. References:
//! Sakurai & Tamaru, "Simple Formulas for Two- and Three-Dimensional
//! Capacitances", IEEE T-ED 1983.
//!
//! When the tech file does not specify `height_to_substrate_um`, we fall
//! back to the v0.1 lumped constants (`cap_per_area_ff_per_um2`,
//! `fringe_cap_ff_per_um`) so older configs keep working.

use crate::extract::cross_layer::{EPS0_FF_PER_UM, EPS_R_ILD};
use crate::tech::TechFile;

/// Total self-capacitance (area + fringe) in fF for a wire of given dimensions.
pub fn wire_capacitance(tech: &TechFile, layer: &str, length_um: f64, width_um: f64) -> f64 {
    if length_um <= 0.0 || width_um <= 0.0 {
        return 0.0;
    }
    let lp = match tech.layer(layer) {
        Some(l) => l,
        None => return 0.0,
    };
    let (c_area, c_fringe) = wire_capacitance_split(tech, layer, length_um, width_um);
    let _ = lp; // silence unused if all paths use early-return
    c_area + c_fringe
}

/// Returns `(C_area, C_fringe)` in fF — lets tests inspect the components.
pub fn wire_capacitance_split(
    tech: &TechFile,
    layer: &str,
    length_um: f64,
    width_um: f64,
) -> (f64, f64) {
    if length_um <= 0.0 || width_um <= 0.0 {
        return (0.0, 0.0);
    }
    let lp = match tech.layer(layer) {
        Some(l) => l,
        None => return (0.0, 0.0),
    };
    if let Some(h) = lp.height_to_substrate_um {
        if h > 0.0 {
            // Sakurai–Tamaru. eps in fF/µm = eps0 * eps_r.
            let eps = EPS0_FF_PER_UM * EPS_R_ILD;
            let w_h = width_um / h;
            let t_h = lp.thickness_um.max(0.0) / h;
            let c_area = eps * length_um * w_h;
            let c_fringe = eps * length_um * (0.77 + 1.06 * w_h.powf(0.25) + 1.06 * t_h.sqrt());
            return (c_area, c_fringe);
        }
    }
    // Fallback: legacy v0.1 lumped constants.
    let c_area = lp.cap_per_area_ff_per_um2 * length_um * width_um;
    let c_fringe = lp.fringe_cap_ff_per_um * 2.0 * length_um;
    (c_area, c_fringe)
}
