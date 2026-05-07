//! `openforge-lvs` CLI.

use clap::{Parser, Subcommand};
use openforge_lvs::{error::LvsError, run_lvs};
use std::path::PathBuf;
use std::process::ExitCode;

#[derive(Parser, Debug)]
#[command(
    name = "openforge-lvs",
    version,
    about = "OpenForge LVS — layout vs schematic checker"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Run LVS comparison between a layout-extracted SPICE and a schematic SPICE.
    Check {
        /// Layout-extracted SPICE netlist
        #[arg(long)]
        layout: PathBuf,
        /// Schematic SPICE netlist
        #[arg(long)]
        schematic: PathBuf,
        /// Top subckt name to compare
        #[arg(long)]
        top: String,
        /// JSON report path (default: lvs.json next to CWD)
        #[arg(long, default_value = "lvs.json")]
        report: PathBuf,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Check {
            layout,
            schematic,
            top,
            report,
        } => match cmd_check(&layout, &schematic, &top, &report) {
            Ok(matched) => {
                if matched {
                    ExitCode::SUCCESS
                } else {
                    ExitCode::from(1)
                }
            }
            Err(e) => {
                eprintln!("error: {e}");
                ExitCode::from(2)
            }
        },
    }
}

fn cmd_check(
    layout: &std::path::Path,
    schematic: &std::path::Path,
    top: &str,
    report: &std::path::Path,
) -> Result<bool, LvsError> {
    println!("[1/4] Parsing schematic: {}", schematic.display());
    let sch_src = std::fs::read_to_string(schematic)?;
    println!("[2/4] Parsing layout:    {}", layout.display());
    let lay_src = std::fs::read_to_string(layout)?;
    println!("[3/4] Building connectivity graphs...");
    println!("[4/4] Running graph isomorphism (VF2)...");

    let rpt = run_lvs(&lay_src, &sch_src, top)?;
    println!();
    println!("{}", rpt.render_human());

    let json = serde_json::to_string_pretty(&rpt)?;
    std::fs::write(report, json)?;
    println!("Report written to {}", report.display());

    Ok(rpt.matched)
}
