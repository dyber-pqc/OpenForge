//! DEF (Design Exchange Format) parser — minimal subset for xRC.

pub mod ast;
pub mod parser;

pub use ast::{Component, Def, Net, RoutePoint, RouteSeg};

use crate::error::Result;
use std::path::Path;

pub fn parse_file(path: impl AsRef<Path>) -> Result<Def> {
    let s = std::fs::read_to_string(path.as_ref())?;
    parser::parse(&s)
}

pub fn parse_str(src: &str) -> Result<Def> {
    parser::parse(src)
}
