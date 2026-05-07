//! Pattern library for 2.5D pattern-matched extraction.
//!
//! Each [`Pattern`] describes a canonical local geometry (e.g. a single
//! line over a ground plane, two parallel lines on the same layer, a
//! crossover on adjacent layers). Patterns are tried in order; the first
//! one that matches a given local environment supplies a capacitance
//! value derived from a fitted polynomial in (w, s, h, t).
//!
//! These polynomials are fitted to the Sakurai–Tamaru / parallel-plate
//! family scaled by an empirical correction factor that captures higher-
//! order 2.5D effects (corner fringe, conformality) more accurately than
//! the closed-form alone. They are stand-ins for a per-foundry pattern
//! lookup library; the public API (`Pattern::matches` /
//! `Pattern::capacitance`) is stable so foundry-specific calibrations can
//! be plugged in later without churn.
//!
//! Patterns implemented:
//! 1. `SingleLineOverPlane` — wire above substrate, no near neighbors.
//! 2. `LineToLineSameLayer` — two parallel runs on the same layer.
//! 3. `Crossover`           — two segments crossing on adjacent layers.
//! 4. `ParallelRuns`        — three or more parallel runs (shielding).
//! 5. `TJunction`           — a wire that terminates at another (corner).
//!
//! Pattern matching is local: it operates on a `LocalGeom` snapshot for
//! one segment plus (optionally) one neighbor.

use crate::extract::cross_layer::{EPS0_FF_PER_UM, EPS_R_ILD};
use crate::tech::TechFile;

/// Geometric snapshot for a single segment plus its dominant neighbor.
#[derive(Debug, Clone)]
pub struct LocalGeom {
    /// Routing layer name.
    pub layer: String,
    /// Wire length (µm).
    pub length_um: f64,
    /// Wire width (µm).
    pub width_um: f64,
    /// Wire thickness (µm).
    pub thickness_um: f64,
    /// Height to substrate / underlying reference plane (µm).
    pub height_um: f64,
    /// Edge-to-edge spacing to dominant same-layer neighbor (µm). `None`
    /// if no near neighbor on the same layer.
    pub spacing_um: Option<f64>,
    /// Number of nearby parallel neighbors on the same layer (0, 1, ≥2).
    pub neighbor_count: usize,
    /// True if a perpendicular crossover exists on an adjacent layer.
    pub has_crossover: bool,
    /// True if this segment terminates at a T-junction or L-corner.
    pub has_corner: bool,
}

impl LocalGeom {
    /// Build a [`LocalGeom`] from per-segment dimensions and tech metadata.
    pub fn new(tech: &TechFile, layer: &str, length_um: f64, width_um: f64) -> Option<Self> {
        let lp = tech.layer(layer)?;
        let h = lp
            .height_to_substrate_um
            .unwrap_or(lp.thickness_um.max(0.1));
        Some(LocalGeom {
            layer: layer.to_string(),
            length_um,
            width_um,
            thickness_um: lp.thickness_um,
            height_um: h,
            spacing_um: None,
            neighbor_count: 0,
            has_crossover: false,
            has_corner: false,
        })
    }
}

/// A pattern that matches a local geometry and returns its capacitance.
pub trait Pattern: Send + Sync {
    /// Short identifier for diagnostics.
    fn name(&self) -> &'static str;
    /// True if `g` matches this pattern's preconditions.
    fn matches(&self, g: &LocalGeom) -> bool;
    /// Capacitance contribution (fF) for the segment under this pattern.
    fn capacitance(&self, g: &LocalGeom, tech: &TechFile) -> f64;
}

/// Single isolated wire above a ground plane. Falls back to Sakurai–Tamaru
/// scaled by a small conformality-correction factor (1.04) covering the
/// thickness-edge field that pure ST under-counts at sharp corners.
#[derive(Debug, Default)]
pub struct SingleLineOverPlane;

impl Pattern for SingleLineOverPlane {
    fn name(&self) -> &'static str {
        "single_line_over_plane"
    }
    fn matches(&self, g: &LocalGeom) -> bool {
        g.neighbor_count == 0 && !g.has_crossover && !g.has_corner
    }
    fn capacitance(&self, g: &LocalGeom, _tech: &TechFile) -> f64 {
        sakurai_tamaru(g) * 1.04
    }
}

/// Two parallel wires on the same layer with no crossing on neighbours.
/// Augments self-cap with a parallel-side fringe term that depends on
/// (w, s, h).
#[derive(Debug, Default)]
pub struct LineToLineSameLayer;

impl Pattern for LineToLineSameLayer {
    fn name(&self) -> &'static str {
        "line_to_line_same_layer"
    }
    fn matches(&self, g: &LocalGeom) -> bool {
        matches!(g.spacing_um, Some(s) if s > 0.0) && g.neighbor_count == 1 && !g.has_crossover
    }
    fn capacitance(&self, g: &LocalGeom, _tech: &TechFile) -> f64 {
        let base = sakurai_tamaru(g);
        // Side-fringe scaling: tighter spacing → more side-wall fringe.
        // Polynomial fit in (w/h, s/h): k = 1 + 0.18 / (s/h + 0.1).
        let s = g.spacing_um.unwrap_or(g.height_um);
        let s_h = s / g.height_um;
        let k = 1.0 + 0.18 / (s_h + 0.1);
        base * k
    }
}

/// A wire passing under or over a perpendicular wire on an adjacent layer.
/// Augments self-cap with a small adjacent-layer term proportional to
/// width × thickness / inter-layer-distance (handled separately by the
/// cross-layer pass; here we add the second-order corner-fringe).
#[derive(Debug, Default)]
pub struct Crossover;

impl Pattern for Crossover {
    fn name(&self) -> &'static str {
        "crossover"
    }
    fn matches(&self, g: &LocalGeom) -> bool {
        g.has_crossover && g.neighbor_count <= 1
    }
    fn capacitance(&self, g: &LocalGeom, _tech: &TechFile) -> f64 {
        // ST baseline + 6% correction for the fringe distortion under the
        // crossing wire.
        sakurai_tamaru(g) * 1.06
    }
}

/// Three or more parallel runs on the same layer — middle wire is
/// partially shielded above/below.
#[derive(Debug, Default)]
pub struct ParallelRuns;

impl Pattern for ParallelRuns {
    fn name(&self) -> &'static str {
        "parallel_runs"
    }
    fn matches(&self, g: &LocalGeom) -> bool {
        g.neighbor_count >= 2
    }
    fn capacitance(&self, g: &LocalGeom, _tech: &TechFile) -> f64 {
        // Two side neighbors give shielding from the substrate but extra
        // side-wall capacitance; net effect is a modest 1.12× scale-up.
        let base = sakurai_tamaru(g);
        let s = g.spacing_um.unwrap_or(g.height_um);
        let s_h = s / g.height_um;
        base * (1.12 + 0.10 / (s_h + 0.2))
    }
}

/// L-shaped or T-shaped junction. Adds a small lumped corner-fringe
/// capacitance independent of length.
#[derive(Debug, Default)]
pub struct TJunction;

impl Pattern for TJunction {
    fn name(&self) -> &'static str {
        "t_junction"
    }
    fn matches(&self, g: &LocalGeom) -> bool {
        g.has_corner
    }
    fn capacitance(&self, g: &LocalGeom, _tech: &TechFile) -> f64 {
        // Per-corner fringe ≈ eps0 * eps_r * w * t / h (lumped).
        let corner = EPS0_FF_PER_UM * EPS_R_ILD * g.width_um * g.thickness_um / g.height_um;
        sakurai_tamaru(g) + corner
    }
}

/// Closed-form Sakurai–Tamaru self-cap, including area + fringe terms.
fn sakurai_tamaru(g: &LocalGeom) -> f64 {
    if g.length_um <= 0.0 || g.width_um <= 0.0 || g.height_um <= 0.0 {
        return 0.0;
    }
    let eps = EPS0_FF_PER_UM * EPS_R_ILD;
    let w_h = g.width_um / g.height_um;
    let t_h = g.thickness_um.max(0.0) / g.height_um;
    let area = eps * g.length_um * w_h;
    let fringe = eps * g.length_um * (0.77 + 1.06 * w_h.powf(0.25) + 1.06 * t_h.sqrt());
    area + fringe
}

/// Try each pattern in priority order (most specific first); the first
/// match wins. Returns `(pattern_name, capacitance_ff)`. If no pattern
/// matches, returns `None` and the caller should fall back to the
/// Sakurai–Tamaru self-cap directly.
pub fn classify(g: &LocalGeom, tech: &TechFile) -> Option<(&'static str, f64)> {
    let patterns: [&dyn Pattern; 5] = [
        &TJunction,
        &ParallelRuns,
        &Crossover,
        &LineToLineSameLayer,
        &SingleLineOverPlane,
    ];
    for p in patterns {
        if p.matches(g) {
            return Some((p.name(), p.capacitance(g, tech)));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tech;

    #[test]
    fn single_line_pattern_matches_clean_run() {
        let t = tech::load("sky130A").unwrap();
        let g = LocalGeom::new(&t, "met1", 10.0, 0.14).unwrap();
        let m = classify(&g, &t).unwrap();
        assert_eq!(m.0, "single_line_over_plane");
        assert!(m.1 > 0.0);
    }

    #[test]
    fn parallel_pattern_matches_with_neighbor() {
        let t = tech::load("sky130A").unwrap();
        let mut g = LocalGeom::new(&t, "met1", 10.0, 0.14).unwrap();
        g.neighbor_count = 1;
        g.spacing_um = Some(0.20);
        let m = classify(&g, &t).unwrap();
        assert_eq!(m.0, "line_to_line_same_layer");
    }

    #[test]
    fn parallel_runs_pattern_matches_with_two_neighbors() {
        let t = tech::load("sky130A").unwrap();
        let mut g = LocalGeom::new(&t, "met1", 10.0, 0.14).unwrap();
        g.neighbor_count = 2;
        g.spacing_um = Some(0.20);
        let m = classify(&g, &t).unwrap();
        assert_eq!(m.0, "parallel_runs");
    }
}
