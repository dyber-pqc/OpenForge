//! Graph normalization passes (series/parallel folding, etc.).
//!
//! v0.1: stub. Future passes will collapse series-connected resistors,
//! merge parallel identical mosfets, and canonicalize generated net names.

use super::ConnGraph;

/// No-op for v0.1.
pub fn normalize(_g: &mut ConnGraph) {
    // Intentionally empty.
}
