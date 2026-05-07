//! DRX built-in function reference.
//!
//! For v0.3 the actual semantics live in `interpreter.rs` as direct method
//! dispatch — there's no general-purpose value system to plumb through.
//! This module documents the supported surface so it's discoverable in
//! one place; future versions may move evaluation here.
//!
//! Top-level functions:
//!   - `input(layer)` / `input(layer, datatype)` -> primitive layer
//!   - `report(name)`                              -> sets deck name
//!
//! Methods on a layer expression:
//!   - `.width(min[, metric])`   -> rule (after `.output`)
//!   - `.space(min[, metric])`   -> rule
//!   - `.enclosing(other, min)`  -> rule
//!   - `.inside(other)`          -> derived layer
//!   - `.outside(other)`         -> derived layer
//!   - `.not(other)`             -> derived layer
//!   - `.and(other)`             -> derived layer
//!   - `.or(other)`              -> derived layer
//!   - `.density(window)`        -> intermediate (chain `.range(min,max)`)
//!   - `.with_length`/`.angles`  -> parsed but not enforced
//!
//! Methods on a measurement chain:
//!   - `.output(name, message)`  -> emits the rule
//!
//! Anything else logs a warning at interpret time and is skipped, so a real
//! deck with unsupported constructs still produces a usable partial set of
//! checks rather than failing outright.

/// List of method names recognised by the DRX interpreter (for diagnostics).
pub const KNOWN_METHODS: &[&str] = &[
    "width",
    "space",
    "enclosing",
    "enclose",
    "inside",
    "outside",
    "not",
    "and",
    "or",
    "density",
    "range",
    "with_length",
    "without_length",
    "angles",
    "rectangles",
    "edges",
    "merged",
    "output",
];
