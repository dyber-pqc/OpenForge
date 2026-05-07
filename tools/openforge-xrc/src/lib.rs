//! OpenForge xRC — Rust-based parasitic extraction (R + C) for VLSI layouts.
//!
//! Reads a routed DEF + LEF + tech file, walks routing geometry, computes
//! per-segment R and C using pattern-based formulas, and emits SPEF.
//!
//! v0.1 scope: parallel-plate capacitance + length-based resistance + simple
//! same-layer coupling. 3D field solver and foundry calibration are out of
//! scope for this milestone.

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
