//! OpenForge Constant-Time Analyzer
//!
//! Analyzes RTL designs to verify constant-time execution properties
//! critical for cryptographic implementations.
//!
//! Checks:
//! - Control flow doesn't depend on secrets (tainted branches)
//! - Memory access patterns don't depend on secrets (tainted addresses)
//! - No variable-timing operations on secret data (div, mod on tainted operands)

pub mod taint;
pub mod control_flow;
pub mod formal_gen;

use std::collections::HashSet;
use std::path::Path;

#[derive(Debug, Clone)]
pub struct CTReport {
    pub violations: Vec<CTViolation>,
    pub tainted_signals: HashSet<String>,
    pub formal_properties: Vec<String>,
    pub total_signals_analyzed: usize,
}

#[derive(Debug, Clone)]
pub enum CTViolation {
    TaintedBranch {
        signal: String,
        location: SourceLocation,
        description: String,
    },
    TaintedAddress {
        signal: String,
        memory: String,
        location: SourceLocation,
    },
    VariableTimingOp {
        operation: String,
        operand: String,
        location: SourceLocation,
    },
}

#[derive(Debug, Clone, Default)]
pub struct SourceLocation {
    pub file: String,
    pub line: usize,
    pub column: usize,
}

pub struct CTAnalyzer {
    source_files: Vec<String>,
    secrets: HashSet<String>,
    public: HashSet<String>,
    tainted: HashSet<String>,
    violations: Vec<CTViolation>,
}

impl CTAnalyzer {
    pub fn new(source_files: Vec<String>) -> Self {
        Self {
            source_files,
            secrets: HashSet::new(),
            public: HashSet::new(),
            tainted: HashSet::new(),
            violations: Vec::new(),
        }
    }

    pub fn mark_secret(&mut self, signal: &str) {
        self.secrets.insert(signal.to_string());
        self.tainted.insert(signal.to_string());
    }

    pub fn mark_public(&mut self, signal: &str) {
        self.public.insert(signal.to_string());
    }

    pub fn analyze(&mut self) -> anyhow::Result<CTReport> {
        // Phase 1: Parse source files
        for file in &self.source_files {
            if Path::new(file).exists() {
                self.parse_and_analyze(file)?;
            }
        }

        // Phase 2: Propagate taint
        taint::propagate(&mut self.tainted, &self.source_files)?;

        // Phase 3: Check control flow
        let cf_violations = control_flow::check(&self.tainted, &self.source_files)?;
        self.violations.extend(cf_violations);

        // Phase 4: Generate formal properties
        let formal_props = formal_gen::generate(&self.secrets, &self.public);

        Ok(CTReport {
            violations: self.violations.clone(),
            tainted_signals: self.tainted.clone(),
            formal_properties: formal_props,
            total_signals_analyzed: self.tainted.len(),
        })
    }

    fn parse_and_analyze(&mut self, _file: &str) -> anyhow::Result<()> {
        // TODO: Use sv-parser to parse SystemVerilog and build dataflow graph
        Ok(())
    }
}

impl std::fmt::Display for CTViolation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CTViolation::TaintedBranch { signal, location, description } => {
                write!(f, "TAINTED_BRANCH: {} at {}:{} - {}", signal, location.file, location.line, description)
            }
            CTViolation::TaintedAddress { signal, memory, location } => {
                write!(f, "TAINTED_ADDR: {} -> {} at {}:{}", signal, memory, location.file, location.line)
            }
            CTViolation::VariableTimingOp { operation, operand, location } => {
                write!(f, "VAR_TIMING: {} on {} at {}:{}", operation, operand, location.file, location.line)
            }
        }
    }
}
