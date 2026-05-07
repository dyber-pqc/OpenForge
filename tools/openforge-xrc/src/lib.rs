//! OpenForge xRC — Rust-based parasitic extraction (R + C) for VLSI layouts.
//!
//! Reads a routed DEF + LEF + tech file, walks routing geometry, computes
//! per-segment R and C using pattern-based formulas, and emits SPEF.
//!
//! v0.2 scope: Sakurai–Tamaru self-cap, multi-cut via R, same-layer
//! coupling, cross-layer (vertical) coupling, IEEE-1481 SPEF with `*PORTS`
//! and hierarchical names. 3D field solver and foundry calibration remain
//! out of scope.

pub mod def;
pub mod error;
pub mod extract;
pub mod lef;
pub mod spef;
pub mod tech;

pub use error::{Result, XrcError};
pub use extract::{extract, ExtractionResult, NetParasitics};
pub use spef::write_spef;
pub use tech::TechFile;
