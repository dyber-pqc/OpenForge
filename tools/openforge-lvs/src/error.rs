//! Error types for openforge-lvs.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum LvsError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("SPICE parse error at line {line}: {msg}")]
    Parse { line: usize, msg: String },

    #[error("Unknown subckt '{0}' referenced as top")]
    UnknownTop(String),

    #[error("Graph build error: {0}")]
    Graph(String),

    #[error("Serialization error: {0}")]
    Serde(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, LvsError>;
