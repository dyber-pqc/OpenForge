//! Taint propagation engine for constant-time analysis.
//!
//! Tracks how secret data flows through RTL assignments.

use std::collections::HashSet;

/// Propagate taint through design assignments.
///
/// Starting from initially tainted (secret) signals, follows all
/// dataflow assignments to mark derived signals as tainted.
pub fn propagate(
    tainted: &mut HashSet<String>,
    _source_files: &[String],
) -> anyhow::Result<()> {
    // TODO: Parse source files with sv-parser, extract assignments,
    // and iteratively propagate taint until fixed point.
    //
    // Algorithm:
    // 1. Build assignment graph: for each `assign lhs = f(rhs1, rhs2, ...)`
    // 2. If any rhs signal is tainted, mark lhs as tainted
    // 3. Repeat until no new signals are tainted (fixed point)
    //
    // Handle:
    // - Continuous assignments (assign)
    // - Procedural assignments (always blocks)
    // - Module port connections (hierarchical propagation)
    // - Ternary operators (condition taints both branches)

    let _initial_count = tainted.len();

    // Fixed-point iteration placeholder
    let mut _changed = true;
    while _changed {
        _changed = false;
        // For each assignment in parsed AST:
        //   if any rhs operand in tainted:
        //     if tainted.insert(lhs): changed = true
        break; // TODO: Remove when implementing
    }

    Ok(())
}
