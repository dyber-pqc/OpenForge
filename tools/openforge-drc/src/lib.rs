//! OpenForge DRC engine — fast Rust-based design rule checker.
//!
//! v0.1 supports `width` and `space` rules on GDSII layouts and emits
//! KLayout-compatible RDB XML reports.

pub mod checks;
pub mod gds;
pub mod geom;
pub mod rdb;
pub mod rules;
pub mod violation;

pub use violation::{Severity, Violation};

use thiserror::Error;

/// Top-level error type for the DRC engine.
#[derive(Debug, Error)]
pub enum DrcError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("GDS parse error: {0}")]
    Gds(String),

    #[error("rule deck parse error: {0}")]
    RuleParse(String),

    #[error("XML write error: {0}")]
    Xml(String),

    #[error("unknown layer: {0}")]
    UnknownLayer(String),
}

pub type Result<T> = std::result::Result<T, DrcError>;

/// Run a full DRC check pass.
///
/// Loads the GDS, parses the rule deck, executes all rules in the deck and
/// returns the collected violations.
pub fn run(gds_path: &std::path::Path, deck: &rules::ast::RuleDeck) -> Result<Vec<Violation>> {
    let layout = gds::reader::read_gds(gds_path)?;
    checks::run_rules(&deck.rules, &layout, &deck.layers)
}
