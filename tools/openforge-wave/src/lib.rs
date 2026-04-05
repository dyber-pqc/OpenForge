//! OpenForge waveform parser library.
//!
//! Provides high-performance parsing for VCD (Value Change Dump) and FST
//! (Fast Signal Trace) waveform formats commonly used in digital design
//! verification.

pub mod fst;
pub mod json_export;
pub mod vcd;

use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

#[derive(Debug, Error)]
pub enum WaveError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("VCD parse error at line {line}: {message}")]
    VcdParse { line: usize, message: String },

    #[error("FST error: {0}")]
    Fst(String),

    #[error("unsupported format: {0}")]
    UnsupportedFormat(String),

    #[error("signal not found: {0}")]
    SignalNotFound(String),
}

pub type Result<T> = std::result::Result<T, WaveError>;

// ---------------------------------------------------------------------------
// Core data model
// ---------------------------------------------------------------------------

/// Top-level container for parsed waveform data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaveformData {
    pub signals: Vec<Signal>,
    pub timescale: Timescale,
    pub total_time: u64,
}

/// A single signal (wire, register, etc.) and its recorded value changes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Signal {
    pub name: String,
    pub width: u32,
    pub id: String,
    pub values: Vec<ValueChange>,
    pub signal_type: SignalType,
}

/// A single value change at a given simulation time.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValueChange {
    pub time: u64,
    pub value: Value,
}

/// Signal value representation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", content = "data")]
pub enum Value {
    /// Binary value stored as packed bytes (MSB-first). Each byte holds up to
    /// 8 bits; a 4-state bit is encoded as two bits (value, strength) but for
    /// simplicity we store the VCD character representation when x/z are
    /// present.
    Binary(Vec<u8>),
    /// IEEE-754 double-precision real.
    Real(f64),
    /// Arbitrary string value.
    String(String),
}

/// The type of a signal variable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SignalType {
    Wire,
    Reg,
    Integer,
    Real,
    Parameter,
}

/// Simulation timescale.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Timescale {
    pub magnitude: u64,
    pub unit: TimeUnit,
}

/// Time unit for the simulation timescale.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TimeUnit {
    S,
    Ms,
    Us,
    Ns,
    Ps,
    Fs,
}

impl std::fmt::Display for TimeUnit {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TimeUnit::S => write!(f, "s"),
            TimeUnit::Ms => write!(f, "ms"),
            TimeUnit::Us => write!(f, "us"),
            TimeUnit::Ns => write!(f, "ns"),
            TimeUnit::Ps => write!(f, "ps"),
            TimeUnit::Fs => write!(f, "fs"),
        }
    }
}

impl Default for Timescale {
    fn default() -> Self {
        Self {
            magnitude: 1,
            unit: TimeUnit::Ns,
        }
    }
}

// ---------------------------------------------------------------------------
// Public convenience loaders
// ---------------------------------------------------------------------------

/// Load a VCD file and return parsed waveform data.
pub fn load_vcd<P: AsRef<Path>>(path: P) -> Result<WaveformData> {
    vcd::parse_vcd(path.as_ref())
}

/// Load an FST file and return parsed waveform data.
///
/// FST support is not yet implemented.
pub fn load_fst<P: AsRef<Path>>(path: P) -> Result<WaveformData> {
    fst::parse_fst(path.as_ref())
}

/// Detect format from file extension and load.
pub fn load<P: AsRef<Path>>(path: P) -> Result<WaveformData> {
    let path = path.as_ref();
    match path.extension().and_then(|e| e.to_str()) {
        Some("vcd") => load_vcd(path),
        Some("fst") => load_fst(path),
        Some(ext) => Err(WaveError::UnsupportedFormat(ext.to_string())),
        None => Err(WaveError::UnsupportedFormat("(no extension)".to_string())),
    }
}
