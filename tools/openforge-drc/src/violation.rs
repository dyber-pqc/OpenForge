//! DRC violation type.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Severity {
    Error,
    Warning,
    Info,
}

impl std::fmt::Display for Severity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Severity::Error => write!(f, "error"),
            Severity::Warning => write!(f, "warning"),
            Severity::Info => write!(f, "info"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Violation {
    pub rule: String,
    pub layer: String,
    pub message: String,
    /// Bounding box of the violating geometry in user units (microns):
    /// (x_min, y_min, x_max, y_max).
    pub coords_um: (f64, f64, f64, f64),
    pub severity: Severity,
    /// Cell name where this violation occurred.
    pub cell: String,
}

impl std::fmt::Display for Violation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let (x0, y0, x1, y1) = self.coords_um;
        write!(
            f,
            "[{}] {} ({}): {} at ({:.4},{:.4})-({:.4},{:.4}) in {}",
            self.severity, self.rule, self.layer, self.message, x0, y0, x1, y1, self.cell
        )
    }
}
