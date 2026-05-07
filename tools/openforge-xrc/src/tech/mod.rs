//! Technology file: per-layer R/C constants and via resistances.

pub mod ast;
pub mod sky130;

use crate::error::{Result, XrcError};
use std::path::Path;

pub use ast::{LayerProps, TechFile, ViaProps};

/// Load a tech file. Recognised values:
///   * "sky130A" → built-in constants
///   * any other value: treated as a path to a JSON tech file
pub fn load(name_or_path: &str) -> Result<TechFile> {
    if name_or_path == "sky130A" {
        return Ok(sky130::sky130a_tech());
    }
    let p = Path::new(name_or_path);
    if p.exists() {
        let s = std::fs::read_to_string(p)?;
        let t: TechFile = serde_json::from_str(&s)
            .map_err(|e| XrcError::Tech(format!("bad JSON tech file: {e}")))?;
        return Ok(t);
    }
    Err(XrcError::Tech(format!(
        "unknown tech '{name_or_path}' (not 'sky130A' and not a path)"
    )))
}
