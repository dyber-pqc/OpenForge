//! LEF (Library Exchange Format) — minimal subset for xRC.

pub mod parser;
pub use parser::{LefLayer, LefLibrary, LefMacro};

use crate::error::Result;
use std::path::Path;

pub fn parse_file(path: impl AsRef<Path>) -> Result<LefLibrary> {
    let s = std::fs::read_to_string(path.as_ref())?;
    parser::parse(&s)
}

pub fn parse_str(src: &str) -> Result<LefLibrary> {
    parser::parse(src)
}
