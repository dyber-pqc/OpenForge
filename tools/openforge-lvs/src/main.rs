//! `openforge-lvs` CLI.

use clap::{Parser, Subcommand};
use openforge_lvs::{error::LvsError, run_lvs, run_lvs_def_spice, run_lvs_def_verilog};
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
    /// Run LVS comparison.
    ///
    /// Layout side: either an extracted SPICE netlist (`--layout`) OR a
    /// routed DEF together with a LEF library (`--layout-def` /
    /// `--layout-lef`).
    ///
    /// Schematic side: a single file (`--schematic`); the format is
    /// auto-detected from the extension. SPICE (`.sp`/`.spice`/`.cir`) and
    /// gate-level Verilog (`.v`) are supported.
    Check {
        /// Layout-extracted SPICE netlist (alternative to --layout-def).
        #[arg(long, conflicts_with = "layout_def")]
        layout: Option<PathBuf>,
        /// Routed DEF for the layout.
        #[arg(long = "layout-def", requires = "layout_lef")]
        layout_def: Option<PathBuf>,
        /// LEF library (may be repeated to merge multiple files).
        #[arg(long = "layout-lef", num_args = 1.., requires = "layout_def")]
        layout_lef: Vec<PathBuf>,
        /// Schematic netlist (SPICE or gate-level Verilog).
        #[arg(long)]
        schematic: PathBuf,
        /// Top subckt / module name to compare.
        #[arg(long)]
        top: String,
        /// JSON report path (default: lvs.json).
        #[arg(long, default_value = "lvs.json")]
        report: PathBuf,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Check {
            layout,
            layout_def,
            layout_lef,
            schematic,
            top,
            report,
        } => match cmd_check(layout, layout_def, layout_lef, &schematic, &top, &report) {
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SchKind {
    Spice,
    Verilog,
}

fn detect_schematic_kind(path: &std::path::Path) -> SchKind {
    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .map(|s| s.to_ascii_lowercase());
    match ext.as_deref() {
        Some("v") | Some("vh") | Some("sv") => SchKind::Verilog,
        _ => SchKind::Spice,
    }
}

fn cmd_check(
    layout_spice: Option<PathBuf>,
    layout_def: Option<PathBuf>,
    layout_lef: Vec<PathBuf>,
    schematic: &std::path::Path,
    top: &str,
    report: &std::path::Path,
) -> Result<bool, LvsError> {
    let sch_kind = detect_schematic_kind(schematic);
    println!(
        "[1/4] Reading schematic ({:?}): {}",
        sch_kind,
        schematic.display()
    );
    let sch_src = std::fs::read_to_string(schematic)?;

    let rpt = if let Some(def_path) = layout_def {
        if layout_lef.is_empty() {
            return Err(LvsError::Graph("--layout-def requires --layout-lef".into()));
        }
        println!("[2/4] Reading layout DEF: {}", def_path.display());
        let def_src = std::fs::read_to_string(&def_path)?;
        // Concatenate all LEF sources (the parser is whitespace-driven so
        // simple concatenation works).
        let mut lef_src = String::new();
        for p in &layout_lef {
            println!("       + LEF: {}", p.display());
            lef_src.push_str(&std::fs::read_to_string(p)?);
            lef_src.push('\n');
        }
        println!("[3/4] Building connectivity graphs...");
        println!("[4/4] Running graph isomorphism (VF2)...");
        match sch_kind {
            SchKind::Verilog => run_lvs_def_verilog(&def_src, &lef_src, &sch_src, top)?,
            SchKind::Spice => run_lvs_def_spice(&def_src, &lef_src, &sch_src, top)?,
        }
    } else if let Some(lay_path) = layout_spice {
        println!("[2/4] Reading layout SPICE: {}", lay_path.display());
        let lay_src = std::fs::read_to_string(&lay_path)?;
        if sch_kind != SchKind::Spice {
            return Err(LvsError::Graph(
                "Verilog schematic requires --layout-def + --layout-lef (DEF mode)".into(),
            ));
        }
        println!("[3/4] Building connectivity graphs...");
        println!("[4/4] Running graph isomorphism (VF2)...");
        run_lvs(&lay_src, &sch_src, top)?
    } else {
        return Err(LvsError::Graph(
            "must provide either --layout (SPICE) or --layout-def + --layout-lef".into(),
        ));
    };

    println!();
    println!("{}", rpt.render_human());

    let json = serde_json::to_string_pretty(&rpt)?;
    std::fs::write(report, json)?;
    println!("Report written to {}", report.display());

    Ok(rpt.matched)
}
