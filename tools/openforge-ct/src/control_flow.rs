//! Control flow dependency checking for constant-time analysis.
//!
//! Detects when tainted (secret) signals influence:
//! - Control flow decisions (`if`/`case`/`?:` conditions)
//! - Memory/array index expressions
//! - Variable-latency operations (division, modulo) on tainted operands

use std::collections::{HashMap, HashSet};
use std::path::Path;

use sv_parser::{parse_sv, RefNode, SyntaxTree};
use tracing::{debug, info, warn};

use crate::{CTViolation, SourceLocation};

// ── Identifier extraction (shared with taint.rs logic) ───────────────────

/// Recursively collect all `SimpleIdentifier` text from a syntax node.
fn collect_identifiers(tree: &SyntaxTree, node: &RefNode) -> Vec<String> {
    let mut ids = Vec::new();
    collect_identifiers_inner(tree, node, &mut ids);
    ids
}

fn collect_identifiers_inner(tree: &SyntaxTree, node: &RefNode, out: &mut Vec<String>) {
    match node {
        RefNode::SimpleIdentifier(id) => {
            if let Some(text) = tree.get_str(id) {
                let name = text.trim().to_string();
                if !name.is_empty() {
                    out.push(name);
                }
            }
        }
        _ => {
            for child in node {
                collect_identifiers_inner(tree, &child, out);
            }
        }
    }
}

/// Try to extract a source location (line number) from a syntax node by
/// looking for the first `Locate` with position info.
fn extract_location(tree: &SyntaxTree, node: &RefNode, file: &str) -> SourceLocation {
    // Walk for the first identifier to get approximate location
    for child in node {
        if let RefNode::Locate(loc) = &child {
            // sv_parser::Locate has line/column
            return SourceLocation {
                file: file.to_string(),
                line: loc.offset, // byte offset as approximate line
                column: 0,
            };
        }
    }
    SourceLocation {
        file: file.to_string(),
        line: 0,
        column: 0,
    }
}

// ── Condition checking ───────────────────────────────────────────────────

/// Information about a detected condition expression.
#[derive(Debug)]
struct ConditionInfo {
    /// Identifiers referenced in the condition expression.
    signals: Vec<String>,
    /// The kind of condition (for the violation message).
    kind: ConditionKind,
    /// Source location of the condition.
    location: SourceLocation,
}

#[derive(Debug, Clone, Copy)]
enum ConditionKind {
    IfCondition,
    CaseSelector,
    TernaryCondition,
    ArrayIndex,
    DivisionOp,
    ModuloOp,
}

impl ConditionKind {
    fn label(self) -> &'static str {
        match self {
            Self::IfCondition => "branch",
            Self::CaseSelector => "branch",
            Self::TernaryCondition => "branch",
            Self::ArrayIndex => "address",
            Self::DivisionOp => "variable-latency",
            Self::ModuloOp => "variable-latency",
        }
    }

    fn description(self, signal: &str) -> String {
        match self {
            Self::IfCondition => format!("If/else condition depends on tainted signal '{signal}'"),
            Self::CaseSelector => format!("Case selector depends on tainted signal '{signal}'"),
            Self::TernaryCondition => {
                format!("Ternary condition depends on tainted signal '{signal}'")
            }
            Self::ArrayIndex => {
                format!("Array/memory index derived from tainted signal '{signal}'")
            }
            Self::DivisionOp => format!(
                "Division operand depends on tainted signal '{signal}' (data-dependent timing)"
            ),
            Self::ModuloOp => format!(
                "Modulo operand depends on tainted signal '{signal}' (data-dependent timing)"
            ),
        }
    }
}

// ── AST walking ──────────────────────────────────────────────────────────

/// Walk the entire syntax tree for one file and collect all condition
/// expressions, array index expressions, and variable-latency operations.
fn collect_conditions(tree: &SyntaxTree, file: &str) -> Vec<ConditionInfo> {
    let mut conditions = Vec::new();

    for node in tree {
        match &node {
            // ── if conditions ────────────────────────────────────
            RefNode::ConditionalStatement(cs) => {
                // The condition expression is the first child expression
                // after the `if` keyword.  We collect all identifiers in
                // the ConditionalStatement's condition predicate.
                process_if_condition(tree, &node, file, &mut conditions);
            }

            // ── case statements ──────────────────────────────────
            RefNode::CaseStatement(cs) => {
                process_case_selector(tree, &node, file, &mut conditions);
            }

            // ── ternary operator (cond_predicate ? a : b) ────────
            RefNode::CondPredicate(_) => {
                let signals = collect_identifiers(tree, &node);
                if !signals.is_empty() {
                    conditions.push(ConditionInfo {
                        signals,
                        kind: ConditionKind::TernaryCondition,
                        location: extract_location(tree, &node, file),
                    });
                }
            }

            // ── detect division and modulo operators ─────────────
            RefNode::BinaryOperator(op) => {
                if let Some(text) = tree.get_str(op) {
                    let t = text.trim();
                    if t == "/" || t == "%" {
                        // The operands are siblings; collect all identifiers
                        // from the parent expression context.  We flag the
                        // entire expression.
                        let kind = if t == "/" {
                            ConditionKind::DivisionOp
                        } else {
                            ConditionKind::ModuloOp
                        };
                        // Walk upward is not easy with sv-parser, so we
                        // flag the operator location and collect identifiers
                        // from the node itself.  The parent `Expression`
                        // node will be handled by collecting the immediate
                        // context identifiers.
                        conditions.push(ConditionInfo {
                            signals: vec![], // filled in by parent pass
                            kind,
                            location: SourceLocation {
                                file: file.to_string(),
                                line: 0,
                                column: 0,
                            },
                        });
                    }
                }
            }

            _ => {}
        }
    }

    // Second pass: find array index expressions `signal[expr]`
    collect_array_indices(tree, file, &mut conditions);

    // Third pass: find binary expressions with / or % and collect their
    // operand identifiers
    collect_variable_latency_ops(tree, file, &mut conditions);

    conditions
}

/// Extract condition identifiers from an if-statement.
fn process_if_condition(
    tree: &SyntaxTree,
    node: &RefNode,
    file: &str,
    conditions: &mut Vec<ConditionInfo>,
) {
    // In sv-parser, a ConditionalStatement contains a CondPredicate
    // as the condition.  We look for the first CondPredicate child.
    let mut found_cond = false;
    for child in node {
        if let RefNode::CondPredicate(_) = &child {
            let signals = collect_identifiers(tree, &child);
            if !signals.is_empty() {
                conditions.push(ConditionInfo {
                    signals,
                    kind: ConditionKind::IfCondition,
                    location: extract_location(tree, &child, file),
                });
            }
            found_cond = true;
            break;
        }
        // For simple if(expr), the expression may appear directly
        if !found_cond {
            if let RefNode::Expression(_) = &child {
                let signals = collect_identifiers(tree, &child);
                if !signals.is_empty() {
                    conditions.push(ConditionInfo {
                        signals,
                        kind: ConditionKind::IfCondition,
                        location: extract_location(tree, &child, file),
                    });
                    found_cond = true;
                }
            }
        }
    }
}

/// Extract the case selector expression from a case statement.
fn process_case_selector(
    tree: &SyntaxTree,
    node: &RefNode,
    file: &str,
    conditions: &mut Vec<ConditionInfo>,
) {
    // The case selector is the expression immediately after `case (`
    for child in node {
        if let RefNode::Expression(_) = &child {
            let signals = collect_identifiers(tree, &child);
            if !signals.is_empty() {
                conditions.push(ConditionInfo {
                    signals,
                    kind: ConditionKind::CaseSelector,
                    location: extract_location(tree, &child, file),
                });
            }
            break; // Only the first expression is the selector
        }
    }
}

/// Find all array index expressions (e.g., `mem[idx]`) and record the
/// index identifiers.
fn collect_array_indices(tree: &SyntaxTree, file: &str, conditions: &mut Vec<ConditionInfo>) {
    for node in tree {
        // sv-parser represents bit-select / part-select / array indexing
        // via `SelectExpression` or `ConstantBitSelect` etc.
        // We look for `BitSelect` and `IndexedRange` patterns.
        match &node {
            RefNode::BitSelect(_) | RefNode::ConstantBitSelect(_) => {
                let signals = collect_identifiers(tree, &node);
                // The first identifier is typically the array, the rest
                // are the index expression.
                if signals.len() >= 2 {
                    conditions.push(ConditionInfo {
                        signals: signals[1..].to_vec(),
                        kind: ConditionKind::ArrayIndex,
                        location: extract_location(tree, &node, file),
                    });
                }
            }
            _ => {}
        }
    }
}

/// Find binary expressions involving `/` or `%` and collect their operand
/// identifiers for variable-latency detection.
fn collect_variable_latency_ops(
    tree: &SyntaxTree,
    file: &str,
    conditions: &mut Vec<ConditionInfo>,
) {
    for node in tree {
        if let RefNode::BinaryExpression(_) = &node {
            // Check if this binary expression uses / or %
            let mut has_div = false;
            let mut has_mod = false;

            for child in &node {
                if let RefNode::BinaryOperator(op) = &child {
                    if let Some(text) = tree.get_str(op) {
                        let t = text.trim();
                        if t == "/" {
                            has_div = true;
                        } else if t == "%" {
                            has_mod = true;
                        }
                    }
                }
            }

            if has_div || has_mod {
                let signals = collect_identifiers(tree, &node);
                if !signals.is_empty() {
                    let kind = if has_div {
                        ConditionKind::DivisionOp
                    } else {
                        ConditionKind::ModuloOp
                    };
                    conditions.push(ConditionInfo {
                        signals,
                        kind,
                        location: extract_location(tree, &node, file),
                    });
                }
            }
        }
    }
}

// ── Public API ───────────────────────────────────────────────────────────

/// Check for tainted control flow dependencies.
///
/// Scans all conditional statements (if, case, ternary), array index
/// expressions, and variable-latency operations.  Reports a violation
/// whenever a tainted signal appears in one of these contexts.
pub fn check(
    tainted: &HashSet<String>,
    source_files: &[String],
) -> anyhow::Result<Vec<CTViolation>> {
    let mut violations = Vec::new();

    for file in source_files {
        if !Path::new(file).exists() {
            continue;
        }

        let defines = HashMap::new();
        let includes: Vec<std::path::PathBuf> = vec![Path::new(file)
            .parent()
            .unwrap_or(Path::new("."))
            .to_path_buf()];

        let (tree, _) = match parse_sv(file, &defines, &includes, false, false) {
            Ok(r) => r,
            Err(e) => {
                warn!("Failed to parse {file}: {e}");
                continue;
            }
        };

        let conditions = collect_conditions(&tree, file);

        for cond in &conditions {
            for signal in &cond.signals {
                if tainted.contains(signal) {
                    let violation = match cond.kind {
                        ConditionKind::IfCondition
                        | ConditionKind::CaseSelector
                        | ConditionKind::TernaryCondition => CTViolation::TaintedBranch {
                            signal: signal.clone(),
                            location: cond.location.clone(),
                            description: cond.kind.description(signal),
                        },
                        ConditionKind::ArrayIndex => CTViolation::TaintedAddress {
                            signal: signal.clone(),
                            memory: "inferred".to_string(),
                            location: cond.location.clone(),
                        },
                        ConditionKind::DivisionOp | ConditionKind::ModuloOp => {
                            CTViolation::VariableTimingOp {
                                operation: if matches!(cond.kind, ConditionKind::DivisionOp) {
                                    "division".to_string()
                                } else {
                                    "modulo".to_string()
                                },
                                operand: signal.clone(),
                                location: cond.location.clone(),
                            }
                        }
                    };

                    debug!("Violation: {violation}");
                    violations.push(violation);
                }
            }
        }
    }

    // Deduplicate: same signal + same kind at same location
    let mut seen: HashSet<String> = HashSet::new();
    violations.retain(|v| {
        let key = format!("{v}");
        seen.insert(key)
    });

    info!("Control flow check: {} violations found", violations.len());
    Ok(violations)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_condition_kind_labels() {
        assert_eq!(ConditionKind::IfCondition.label(), "branch");
        assert_eq!(ConditionKind::CaseSelector.label(), "branch");
        assert_eq!(ConditionKind::ArrayIndex.label(), "address");
        assert_eq!(ConditionKind::DivisionOp.label(), "variable-latency");
        assert_eq!(ConditionKind::ModuloOp.label(), "variable-latency");
    }

    #[test]
    fn test_check_with_no_files() {
        let tainted: HashSet<String> = ["secret_key".to_string()].into();
        let result = check(&tainted, &[]);
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_check_with_missing_file() {
        let tainted: HashSet<String> = ["secret_key".to_string()].into();
        let result = check(&tainted, &["nonexistent_file.sv".to_string()]);
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }
}
