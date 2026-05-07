//! KLayout DRX-compatible rule deck parser.
//!
//! DRX is a Ruby-subset DSL used by the production sky130A and gf180mcuC
//! KLayout DRC decks. We don't aim to be a full Ruby interpreter — we parse
//! the subset that real decks use and lower it to our existing `Rule` AST,
//! materialising derived layers (boolean ops) into the `Layout` up front.
//!
//! Supported (v0.3):
//!   - `<var> = input(layer, dtype)` and `input(layer)` (datatype defaults 0)
//!   - `report("name")` (informational; sets deck name)
//!   - `<layer>.width(min[, metric])`
//!   - `<layer>.space(min[, metric])`
//!   - `<layer>.enclosing(other, min)`
//!   - `<layer>.inside(other)`, `.outside(other)`, `.not(other)`,
//!     `.and(other)`, `.or(other)` produce derived layers (when assigned)
//!     or are chained then `.output(...)` is called
//!   - `<expr>.output("rule_name", "description")`
//!   - `<layer>.density(window: N.um).range(min, max)` parsed; emitted as
//!     two `Rule::Density` variants (min and max).
//!   - `<expr>.with_length(...)`, `.angles(...)` parsed and ignored (no-op)
//!   - Comments `# ...`, numbers with optional `.um` suffix, basic strings.
//!
//! Unsupported constructs log a warning and are skipped.

pub mod interpreter;
pub mod lexer;
pub mod parser;
pub mod stdlib;

use crate::rules::ast::RuleDeck;
use crate::Result;

/// True if the source looks like a DRX (Ruby-style) deck rather than the
/// older simple line-based format. We auto-detect on `input(` or `report(`.
pub fn looks_like_drx(src: &str) -> bool {
    for line in src.lines() {
        let l = match line.find('#') {
            Some(i) => &line[..i],
            None => line,
        };
        let l = l.trim();
        if l.is_empty() {
            continue;
        }
        if l.contains("input(") || l.starts_with("report(") || l.contains(".width(") {
            return true;
        }
    }
    false
}

/// Parse a DRX source string into a `RuleDeck`.
pub fn parse_drx(src: &str) -> Result<RuleDeck> {
    let tokens = lexer::tokenize(src)?;
    let stmts = parser::parse(&tokens)?;
    interpreter::interpret(stmts)
}
