//! Taint propagation engine for constant-time analysis.
//!
//! Parses SystemVerilog source using `sv-parser`, builds an assignment
//! dependency graph, and iteratively propagates taint from secret signals
//! through all dataflow edges until a fixed point is reached.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use sv_parser::{parse_sv, SyntaxTree, RefNode};
use tracing::{debug, info, warn};

// ── Assignment graph ─────────────────────────────────────────────────────

/// A single dataflow edge: `lhs` depends on every signal in `rhs_deps`.
#[derive(Debug, Clone)]
struct Assignment {
    lhs: String,
    rhs_deps: Vec<String>,
    file: String,
    line: usize,
}

/// Intermediate representation of a module's port connections for
/// hierarchical taint propagation.
#[derive(Debug, Clone)]
struct PortConnection {
    /// Name of the instantiated module.
    instance_module: String,
    /// Formal port name inside the instantiated module.
    formal: String,
    /// Actual signal connected in the parent scope.
    actual: String,
}

/// Collected dataflow information from parsing.
#[derive(Debug, Default)]
struct DesignInfo {
    assignments: Vec<Assignment>,
    port_connections: Vec<PortConnection>,
}

// ── Identifier extraction helpers ────────────────────────────────────────

/// Walk a `sv_parser` syntax tree node and collect all simple identifiers
/// referenced within it.  This is intentionally broad -- it grabs every
/// `SimpleIdentifier` to capture all signals on the RHS of assignments,
/// condition expressions, etc.
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
            // Recurse into children
            for child in node {
                collect_identifiers_inner(tree, &child, out);
            }
        }
    }
}

/// Try to extract the LHS target identifier from a net/variable lvalue node.
fn extract_lhs_name(tree: &SyntaxTree, node: &RefNode) -> Option<String> {
    // The LHS of an assignment eventually resolves to a SimpleIdentifier
    // (possibly with part-selects which we ignore for taint purposes).
    let ids = collect_identifiers(tree, node);
    ids.into_iter().next()
}

// ── SV parsing & assignment extraction ───────────────────────────────────

/// Parse one SystemVerilog file and extract assignments + port connections.
fn parse_file(path: &str) -> anyhow::Result<DesignInfo> {
    let file_path = Path::new(path);
    if !file_path.exists() {
        warn!("Source file not found: {path}");
        return Ok(DesignInfo::default());
    }

    // sv-parser needs a defines map and include paths
    let defines = HashMap::new();
    let includes: Vec<std::path::PathBuf> = vec![file_path.parent().unwrap_or(Path::new(".")).to_path_buf()];

    let result = parse_sv(path, &defines, &includes, false, false);
    let (tree, _) = match result {
        Ok(r) => r,
        Err(e) => {
            warn!("Failed to parse {path}: {e}");
            return Ok(DesignInfo::default());
        }
    };

    let mut info = DesignInfo::default();

    for node in &tree {
        match node {
            // ── Continuous assignment: `assign lhs = rhs;` ───────────
            RefNode::ContinuousAssign(ca) => {
                process_continuous_assign(&tree, &RefNode::ContinuousAssign(ca), path, &mut info);
            }

            // ── Procedural blocks: `always`, `always_comb`, `always_ff` ─
            RefNode::AlwaysConstruct(ac) => {
                process_always_block(&tree, &RefNode::AlwaysConstruct(ac), path, &mut info);
            }

            // ── Module instantiation for port mapping ────────────────
            RefNode::ModuleInstantiation(mi) => {
                process_module_instantiation(&tree, &RefNode::ModuleInstantiation(mi), &mut info);
            }

            _ => {}
        }
    }

    info!(
        "Parsed {path}: {} assignments, {} port connections",
        info.assignments.len(),
        info.port_connections.len()
    );
    Ok(info)
}

/// Extract assignments from a continuous-assign statement.
fn process_continuous_assign(
    tree: &SyntaxTree,
    node: &RefNode,
    file: &str,
    info: &mut DesignInfo,
) {
    // A continuous assign can contain multiple comma-separated assignments.
    // Each `NetAssignment` has a `net_lvalue` and an expression.
    let mut current_lhs: Option<String> = None;
    let mut collecting_rhs = false;
    let mut rhs_ids: Vec<String> = Vec::new();

    for child in node {
        match &child {
            RefNode::NetLvalue(_) => {
                // Flush previous assignment if any
                if let Some(lhs) = current_lhs.take() {
                    if !rhs_ids.is_empty() {
                        info.assignments.push(Assignment {
                            lhs,
                            rhs_deps: std::mem::take(&mut rhs_ids),
                            file: file.to_string(),
                            line: 0,
                        });
                    }
                }
                current_lhs = extract_lhs_name(tree, &child);
                collecting_rhs = false;
            }
            RefNode::Symbol(s) => {
                if let Some(text) = tree.get_str(s) {
                    if text.trim() == "=" {
                        collecting_rhs = true;
                    }
                }
            }
            _ => {
                if collecting_rhs {
                    let ids = collect_identifiers(tree, &child);
                    // Filter out the LHS from RHS dependencies
                    for id in ids {
                        if current_lhs.as_deref() != Some(&id) {
                            rhs_ids.push(id);
                        }
                    }
                }
            }
        }
    }

    // Flush last assignment
    if let Some(lhs) = current_lhs {
        if !rhs_ids.is_empty() {
            info.assignments.push(Assignment {
                lhs,
                rhs_deps: rhs_ids,
                file: file.to_string(),
                line: 0,
            });
        }
    }
}

/// Extract assignments from procedural (always) blocks.
///
/// Inside always blocks we look for `BlockingAssignment` and
/// `NonblockingAssignment` nodes to build dataflow edges.
fn process_always_block(
    tree: &SyntaxTree,
    node: &RefNode,
    file: &str,
    info: &mut DesignInfo,
) {
    for child in node {
        match &child {
            RefNode::BlockingAssignment(_) | RefNode::NonblockingAssignment(_) => {
                extract_procedural_assignment(tree, &child, file, info);
            }
            // Recurse to find nested assignments inside if/case/for
            _ => {
                process_always_block(tree, &child, file, info);
            }
        }
    }
}

/// Extract a single procedural assignment.
fn extract_procedural_assignment(
    tree: &SyntaxTree,
    node: &RefNode,
    file: &str,
    info: &mut DesignInfo,
) {
    let mut lhs_name: Option<String> = None;
    let mut past_eq = false;
    let mut rhs_ids: Vec<String> = Vec::new();

    for child in node {
        match &child {
            RefNode::VariableLvalue(_) => {
                lhs_name = extract_lhs_name(tree, &child);
            }
            RefNode::Symbol(s) => {
                if let Some(text) = tree.get_str(s) {
                    let t = text.trim();
                    if t == "=" || t == "<=" {
                        past_eq = true;
                    }
                }
            }
            _ => {
                if past_eq {
                    let ids = collect_identifiers(tree, &child);
                    for id in ids {
                        if lhs_name.as_deref() != Some(&id) {
                            rhs_ids.push(id);
                        }
                    }
                }
            }
        }
    }

    if let Some(lhs) = lhs_name {
        if !rhs_ids.is_empty() {
            info.assignments.push(Assignment {
                lhs,
                rhs_deps: rhs_ids,
                file: file.to_string(),
                line: 0,
            });
        }
    }
}

/// Extract port connections from module instantiations for hierarchical
/// taint propagation.
fn process_module_instantiation(
    tree: &SyntaxTree,
    node: &RefNode,
    info: &mut DesignInfo,
) {
    let mut module_name: Option<String> = None;

    for child in node {
        match &child {
            RefNode::ModuleIdentifier(_) => {
                let ids = collect_identifiers(tree, &child);
                module_name = ids.into_iter().next();
            }
            RefNode::NamedPortConnection(_) => {
                // Named port: .formal(actual)
                let ids = collect_identifiers(tree, &child);
                if ids.len() >= 2 {
                    if let Some(ref modname) = module_name {
                        info.port_connections.push(PortConnection {
                            instance_module: modname.clone(),
                            formal: ids[0].clone(),
                            actual: ids[1].clone(),
                        });
                    }
                }
            }
            RefNode::OrderedPortConnection(_) => {
                // Positional port connections -- we collect identifiers
                // but can't easily map to formal names without the module
                // definition, so we treat them as potential taint bridges.
                let ids = collect_identifiers(tree, &child);
                if let (Some(ref modname), Some(actual)) = (&module_name, ids.into_iter().next()) {
                    info.port_connections.push(PortConnection {
                        instance_module: modname.clone(),
                        formal: format!("__positional_{}", info.port_connections.len()),
                        actual,
                    });
                }
            }
            _ => {}
        }
    }
}

// ── Fixed-point taint propagation ────────────────────────────────────────

/// Propagate taint through design assignments.
///
/// Starting from initially tainted (secret) signals, follows all
/// dataflow assignments to mark derived signals as tainted.  Reaches a
/// fixed point when no new signals become tainted in an iteration.
///
/// Handles:
/// - Continuous assignments (`assign lhs = f(rhs1, rhs2, ...)`)
/// - Procedural assignments in `always` blocks
/// - Ternary operators (condition taints both branches -- captured by
///   the generic RHS identifier collection)
/// - Concatenation and bit-select (captured by identifier collection)
/// - Module port connections (hierarchical propagation)
pub fn propagate(
    tainted: &mut HashSet<String>,
    source_files: &[String],
) -> anyhow::Result<()> {
    // Phase 1: Parse all source files and collect assignments
    let mut all_assignments: Vec<Assignment> = Vec::new();
    let mut all_port_conns: Vec<PortConnection> = Vec::new();

    for file in source_files {
        let info = parse_file(file)?;
        all_assignments.extend(info.assignments);
        all_port_conns.extend(info.port_connections);
    }

    info!(
        "Taint propagation: {} initial tainted signals, {} assignments, {} port connections",
        tainted.len(),
        all_assignments.len(),
        all_port_conns.len()
    );

    // Phase 2: Build port-connection taint bridges.
    // If a tainted signal is connected to a module port, the formal port
    // and vice versa should both be considered tainted.
    let mut port_bridges: Vec<(String, String)> = Vec::new();
    for pc in &all_port_conns {
        // Bidirectional bridge: taint flows both ways through ports
        let formal_qualified = format!("{}.{}", pc.instance_module, pc.formal);
        port_bridges.push((pc.actual.clone(), formal_qualified.clone()));
        port_bridges.push((formal_qualified, pc.actual.clone()));
    }

    // Phase 3: Fixed-point iteration
    let mut iteration = 0;
    loop {
        let mut changed = false;
        iteration += 1;

        // Propagate through assignments
        for assign in &all_assignments {
            if tainted.contains(&assign.lhs) {
                continue;
            }
            let any_rhs_tainted = assign.rhs_deps.iter().any(|dep| tainted.contains(dep));
            if any_rhs_tainted {
                debug!(
                    "Taint propagated: {} <- [{}] ({}:{})",
                    assign.lhs,
                    assign.rhs_deps.join(", "),
                    assign.file,
                    assign.line
                );
                tainted.insert(assign.lhs.clone());
                changed = true;
            }
        }

        // Propagate through port connections
        for (from, to) in &port_bridges {
            if tainted.contains(from) && !tainted.contains(to) {
                debug!("Taint propagated through port: {from} -> {to}");
                tainted.insert(to.clone());
                changed = true;
            }
        }

        if !changed {
            break;
        }

        // Safety limit to prevent infinite loops on pathological inputs
        if iteration > 1000 {
            warn!("Taint propagation hit iteration limit (1000); stopping early");
            break;
        }
    }

    info!(
        "Taint propagation converged after {iteration} iterations: {} tainted signals",
        tainted.len()
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fixed_point_simple_chain() {
        // Simulate a -> b -> c chain
        let assignments = vec![
            Assignment {
                lhs: "b".into(),
                rhs_deps: vec!["a".into()],
                file: "test.sv".into(),
                line: 1,
            },
            Assignment {
                lhs: "c".into(),
                rhs_deps: vec!["b".into()],
                file: "test.sv".into(),
                line: 2,
            },
            Assignment {
                lhs: "d".into(),
                rhs_deps: vec!["x".into()],
                file: "test.sv".into(),
                line: 3,
            },
        ];

        let mut tainted: HashSet<String> = HashSet::new();
        tainted.insert("a".into());

        // Manual propagation (bypassing file parsing)
        let mut iteration = 0;
        loop {
            let mut changed = false;
            iteration += 1;
            for assign in &assignments {
                if tainted.contains(&assign.lhs) {
                    continue;
                }
                if assign.rhs_deps.iter().any(|d| tainted.contains(d)) {
                    tainted.insert(assign.lhs.clone());
                    changed = true;
                }
            }
            if !changed || iteration > 100 {
                break;
            }
        }

        assert!(tainted.contains("a"));
        assert!(tainted.contains("b"));
        assert!(tainted.contains("c"));
        assert!(!tainted.contains("d")); // not reachable from a
    }

    #[test]
    fn test_propagation_with_empty_files() {
        let mut tainted: HashSet<String> = HashSet::new();
        tainted.insert("secret_key".into());

        // Propagate with no actual files -- should not panic
        let result = propagate(&mut tainted, &[]);
        assert!(result.is_ok());
        assert!(tainted.contains("secret_key"));
    }
}
