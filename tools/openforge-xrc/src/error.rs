use thiserror::Error;

#[derive(Debug, Error)]
pub enum XrcError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("DEF parse error at line {line}: {msg}")]
    DefParse { line: usize, msg: String },

    #[error("LEF parse error at line {line}: {msg}")]
    LefParse { line: usize, msg: String },

    #[error("Tech file error: {0}")]
    Tech(String),

    #[error("Unknown layer: {0}")]
    UnknownLayer(String),

    #[error("Extraction error: {0}")]
    Extract(String),
}

pub type Result<T> = std::result::Result<T, XrcError>;
