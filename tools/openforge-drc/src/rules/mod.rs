//! Rule deck parsing and AST.

pub mod ast;
pub mod drx;
pub mod parser;

pub use ast::{BoolOp, DerivedLayer, LayerSpec, Rule, RuleDeck};
pub use drx::{looks_like_drx, parse_drx};
pub use parser::parse_deck;

/// Auto-detect format and parse: DRX (Ruby-style) if it looks like one,
/// otherwise the simple `LAYER`/`RULE` format.
pub fn parse_deck_auto(src: &str) -> crate::Result<RuleDeck> {
    if looks_like_drx(src) {
        parse_drx(src)
    } else {
        parse_deck(src)
    }
}
