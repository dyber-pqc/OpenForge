//! Control flow dependency checking for constant-time analysis.
//!
//! Detects when tainted (secret) signals influence control flow
//! decisions (if/case conditions) or memory addresses.

use std::collections::HashSet;
use crate::{CTViolation, SourceLocation};

/// Check for tainted control flow dependencies.
///
/// Scans all conditional statements (if, case, ternary) and reports
/// violations where the condition depends on tainted signals.
pub fn check(
    tainted: &HashSet<String>,
    _source_files: &[String],
) -> anyhow::Result<Vec<CTViolation>> {
    let mut violations = Vec::new();

    // TODO: Parse source files and check:
    //
    // 1. If/case conditions:
    //    if (tainted_signal) ...  -> VIOLATION
    //    case (tainted_signal) ... -> VIOLATION
    //
    // 2. Memory addresses:
    //    mem[tainted_signal] -> VIOLATION
    //    ram[addr] where addr is tainted -> VIOLATION
    //
    // 3. Variable-timing operations:
    //    tainted_signal / x -> VIOLATION (division may have data-dependent timing)
    //    tainted_signal % x -> VIOLATION
    //    Multipliers without fixed latency on tainted operands -> VIOLATION

    // Placeholder: detect common patterns by signal name
    for signal in tainted {
        if signal.contains("addr") || signal.contains("index") {
            violations.push(CTViolation::TaintedAddress {
                signal: signal.clone(),
                memory: "unknown".to_string(),
                location: SourceLocation::default(),
            });
        }
    }

    Ok(violations)
}
