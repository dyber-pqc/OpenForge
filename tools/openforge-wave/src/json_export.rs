//! JSON export for the web waveform viewer.
//!
//! Produces a JSON structure optimised for the SvelteKit-based waveform
//! viewer in `packages/web/`.

use serde::Serialize;
use std::io::Write;
use std::path::Path;

use crate::{Result, WaveError, WaveformData};

/// Compact signal representation for the web viewer.
///
/// Value changes are split into parallel `times` and `values` arrays for
/// efficient typed-array transfer to the browser.
#[derive(Serialize)]
struct WebSignal<'a> {
    name: &'a str,
    width: u32,
    id: &'a str,
    signal_type: &'a crate::SignalType,
    times: Vec<u64>,
    values: Vec<&'a crate::Value>,
}

/// Top-level JSON envelope for the web viewer.
#[derive(Serialize)]
struct WebWaveform<'a> {
    timescale_magnitude: u64,
    timescale_unit: String,
    total_time: u64,
    signal_count: usize,
    signals: Vec<WebSignal<'a>>,
}

/// Write waveform data as JSON to the given writer.
pub fn write_json<W: Write>(waveform: &WaveformData, writer: W) -> Result<()> {
    let signals: Vec<WebSignal<'_>> = waveform
        .signals
        .iter()
        .map(|s| {
            let times = s.values.iter().map(|vc| vc.time).collect();
            let values = s.values.iter().map(|vc| &vc.value).collect();
            WebSignal {
                name: &s.name,
                width: s.width,
                id: &s.id,
                signal_type: &s.signal_type,
                times,
                values,
            }
        })
        .collect();

    let web = WebWaveform {
        timescale_magnitude: waveform.timescale.magnitude,
        timescale_unit: waveform.timescale.unit.to_string(),
        total_time: waveform.total_time,
        signal_count: waveform.signals.len(),
        signals,
    };

    serde_json::to_writer_pretty(writer, &web).map_err(|e| WaveError::Io(e.into()))
}

/// Write waveform data as JSON to a file.
pub fn export_json<P: AsRef<Path>>(waveform: &WaveformData, path: P) -> Result<()> {
    let file = std::fs::File::create(path)?;
    let writer = std::io::BufWriter::new(file);
    write_json(waveform, writer)
}
