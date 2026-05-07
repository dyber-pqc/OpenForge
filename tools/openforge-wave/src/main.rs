//! `openforge-wave` CLI -- waveform inspection and conversion tool.

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

use openforge_wave::{json_export, Value, WaveformData};

#[derive(Parser)]
#[command(
    name = "openforge-wave",
    about = "High-performance VCD/FST waveform parser and converter",
    version
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Print summary information about a waveform file.
    Info {
        /// Path to the waveform file (VCD or FST).
        file: PathBuf,
    },
    /// Dump value changes for a specific signal.
    Dump {
        /// Path to the waveform file.
        file: PathBuf,
        /// Signal name (hierarchical, e.g. "top.cpu.clk").
        #[arg(short, long)]
        signal: String,
        /// Start time (inclusive). Defaults to 0.
        #[arg(long, default_value_t = 0)]
        start: u64,
        /// End time (inclusive). Defaults to the total simulation time.
        #[arg(long)]
        end: Option<u64>,
    },
    /// Convert a waveform file to JSON for the web viewer.
    Convert {
        /// Input waveform file (VCD or FST).
        input: PathBuf,
        /// Output JSON file path.
        output: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Command::Info { file } => cmd_info(&file),
        Command::Dump {
            file,
            signal,
            start,
            end,
        } => cmd_dump(&file, &signal, start, end),
        Command::Convert { input, output } => cmd_convert(&input, &output),
    }
}

fn cmd_info(file: &PathBuf) -> Result<()> {
    let waveform = load(file)?;

    println!("File:        {}", file.display());
    println!(
        "Timescale:   {} {}",
        waveform.timescale.magnitude, waveform.timescale.unit
    );
    println!("Total time:  {}", waveform.total_time);
    println!("Signals:     {}", waveform.signals.len());
    println!();

    // Print signal list with types and widths.
    println!("{:<40} {:>6} {:>10}", "Signal", "Width", "Type");
    println!("{}", "-".repeat(58));
    for sig in &waveform.signals {
        println!("{:<40} {:>6} {:>10?}", sig.name, sig.width, sig.signal_type);
    }

    Ok(())
}

fn cmd_dump(file: &PathBuf, signal_name: &str, start: u64, end: Option<u64>) -> Result<()> {
    let waveform = load(file)?;
    let end = end.unwrap_or(waveform.total_time);

    let signal = waveform
        .signals
        .iter()
        .find(|s| s.name == signal_name)
        .ok_or_else(|| {
            anyhow::anyhow!(
                "signal '{}' not found. Use 'info' to list available signals.",
                signal_name
            )
        })?;

    println!(
        "Signal: {} (width={}, type={:?})",
        signal.name, signal.width, signal.signal_type
    );
    println!(
        "Time range: {} -- {} (timescale: {} {})",
        start, end, waveform.timescale.magnitude, waveform.timescale.unit
    );
    println!();
    let time_hdr = "Time";
    let val_hdr = "Value";
    println!("{time_hdr:>12}  {val_hdr}");
    println!("{}", "-".repeat(40));

    for vc in &signal.values {
        if vc.time < start {
            continue;
        }
        if vc.time > end {
            break;
        }
        let val_str = format_value(&vc.value);
        println!("{:>12}  {}", vc.time, val_str);
    }

    Ok(())
}

fn cmd_convert(input: &PathBuf, output: &PathBuf) -> Result<()> {
    let waveform = load(input)?;

    json_export::export_json(&waveform, output)
        .with_context(|| format!("failed to write JSON to {}", output.display()))?;

    println!(
        "Converted {} ({} signals, time 0..{}) -> {}",
        input.display(),
        waveform.signals.len(),
        waveform.total_time,
        output.display()
    );

    Ok(())
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn load(file: &PathBuf) -> Result<WaveformData> {
    openforge_wave::load(file).with_context(|| format!("failed to parse {}", file.display()))
}

fn format_value(value: &Value) -> String {
    match value {
        Value::Binary(bytes) => {
            if bytes.len() == 1 {
                format!("{}", bytes[0])
            } else {
                // Format as hex for multi-byte values.
                let hex: String = bytes.iter().map(|b| format!("{:02x}", b)).collect();
                format!("0x{}", hex.trim_start_matches('0').max("0"))
            }
        }
        Value::Real(f) => format!("{}", f),
        Value::String(s) => s.clone(),
    }
}
