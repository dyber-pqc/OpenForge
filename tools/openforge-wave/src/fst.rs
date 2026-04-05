//! FST (Fast Signal Trace) format parser -- stub.
//!
//! FST is a high-performance waveform format created by Tony Bybell for
//! GtkWave. Key characteristics:
//!
//! - **Block-compressed**: Signal data is stored in compressed blocks
//!   (typically LZ4 or zlib), enabling much smaller file sizes than VCD.
//!
//! - **Random access**: A hierarchical index allows seeking directly to any
//!   time region without scanning the entire file, making it ideal for
//!   interactive waveform viewers.
//!
//! - **Columnar storage**: Values for each signal are stored contiguously
//!   rather than interleaved by time, which improves compression ratios
//!   and cache locality when reading individual signals.
//!
//! - **Header section**: Contains hierarchy, signal definitions, timescale,
//!   and metadata -- similar to the VCD header but in a binary format.
//!
//! - **Data section**: Compressed blocks of value changes indexed by time
//!   ranges and signal groups.
//!
//! TODO: Implement FST parsing. The recommended approach is:
//!   1. Parse the file header (magic bytes, version, metadata).
//!   2. Read the hierarchy block to reconstruct signal definitions.
//!   3. Build a block index mapping time ranges to file offsets.
//!   4. Decompress and decode value-change blocks on demand.
//!   5. Optionally support memory-mapped I/O for large files.
//!
//! Reference: <https://gtkwave.sourceforge.net/gtkwave.pdf> appendix on FST.

use std::path::Path;

use crate::{WaveError, WaveformData};

/// Parse an FST file. Currently unimplemented.
pub fn parse_fst(_path: &Path) -> crate::Result<WaveformData> {
    // TODO: Implement FST format parsing.
    //
    // The FST binary format (magic: 0x00 0x46 0x53 0x54) consists of:
    //   - File header block (type 0): version, timescale, date, etc.
    //   - Hierarchy block (type 1): compressed scope/var tree.
    //   - Value change data blocks (type 2..N): compressed signal data.
    //   - Geometry block: signal widths and types.
    //   - Blackout regions: time ranges with no data.
    //
    // Each data block stores a time range and delta-encoded value changes
    // for a group of signals, compressed with zlib or LZ4.
    Err(WaveError::Fst(
        "FST format support coming soon -- use VCD for now".to_string(),
    ))
}
