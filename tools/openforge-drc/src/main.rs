//! `openforge-drc` CLI.

use anyhow::{Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use std::fs;
use std::io::Write;
use std::path::PathBuf;

use openforge_drc::checks::derived::materialize_derived;
use openforge_drc::gds::reader::read_gds_with_layers;
use openforge_drc::rdb::write_rdb;
use openforge_drc::rules::{parse_deck_auto, parse_drx};
use openforge_drc::{checks, Violation};

const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Clone, Copy, ValueEnum)]
enum OutputFormat {
    Text,
    Rdb,
    Json,
}

#[derive(Parser, Debug)]
#[command(
    name = "openforge-drc",
    version,
    about = "OpenForge DRC engine — fast Rust-based design rule checker"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Run DRC on a GDSII layout.
    Check {
        /// Input GDSII file.
        gds: PathBuf,

        /// DRC rule deck (legacy `LAYER`/`RULE` format, or auto-detected DRX).
        #[arg(long)]
        rules: Option<PathBuf>,

        /// DRC rule deck in KLayout DRX (Ruby-style) format.
        #[arg(long = "rules-drx")]
        rules_drx: Option<PathBuf>,

        /// Technology label (cosmetic; baked into the RDB description).
        #[arg(long, default_value = "unknown")]
        tech: String,

        /// Output file (RDB XML by default).
        #[arg(long, short = 'o')]
        output: Option<PathBuf>,

        /// Output format.
        #[arg(long, value_enum, default_value_t = OutputFormat::Rdb)]
        format: OutputFormat,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Check {
            gds,
            rules,
            rules_drx,
            tech,
            output,
            format,
        } => run_check(gds, rules, rules_drx, tech, output, format),
    }
}

fn run_check(
    gds: PathBuf,
    rules_path: Option<PathBuf>,
    rules_drx_path: Option<PathBuf>,
    tech: String,
    output: Option<PathBuf>,
    format: OutputFormat,
) -> Result<()> {
    println!("Loading GDS: {}", gds.display());
    let (rules_path_used, deck) = match (rules_path, rules_drx_path) {
        (None, None) => {
            anyhow::bail!("must supply --rules or --rules-drx");
        }
        (Some(_), Some(_)) => {
            anyhow::bail!("only one of --rules or --rules-drx may be supplied");
        }
        (None, Some(p)) => {
            let src = fs::read_to_string(&p).with_context(|| format!("reading {}", p.display()))?;
            println!("Parsing DRX deck: {}", p.display());
            let deck = parse_drx(&src).context("parsing DRX deck")?;
            (p, deck)
        }
        (Some(p), None) => {
            let src = fs::read_to_string(&p).with_context(|| format!("reading {}", p.display()))?;
            println!("Parsing rule deck (auto-detect): {}", p.display());
            let deck = parse_deck_auto(&src).context("parsing rule deck")?;
            (p, deck)
        }
    };
    let _ = rules_path_used;
    println!(
        "Found {} rule{} across {} layer{}.",
        deck.rules.len(),
        if deck.rules.len() == 1 { "" } else { "s" },
        deck.layers.len(),
        if deck.layers.len() == 1 { "" } else { "s" },
    );

    let mut layout = read_gds_with_layers(&gds, &deck.layers).context("reading GDS")?;
    if !deck.derived.is_empty() {
        println!("Materialising {} derived layer(s)...", deck.derived.len());
        materialize_derived(&mut layout, &deck.derived);
    }

    // Run all rules in parallel. Per-rule progress logging would require a
    // serialised pre-pass; for now we just summarise totals after the fact.
    for rule in &deck.rules {
        println!("  - {}: {}", rule.name(), rule.description());
    }
    let all: Vec<Violation> = checks::run_rules(&deck.rules, &layout, &deck.layers)?;

    println!();
    println!(
        "Total: {} violation{}.",
        all.len(),
        if all.len() == 1 { "" } else { "s" }
    );

    if let Some(out_path) = output {
        let tool_label = format!("OpenForge DRC v{VERSION} - {tech}");
        match format {
            OutputFormat::Rdb => {
                let f = fs::File::create(&out_path)
                    .with_context(|| format!("creating {}", out_path.display()))?;
                write_rdb(f, &deck.name, &tool_label, &deck, &layout.top_cell, &all)
                    .context("writing RDB")?;
                println!("RDB written to {}", out_path.display());
            }
            OutputFormat::Text => {
                let mut f = fs::File::create(&out_path)
                    .with_context(|| format!("creating {}", out_path.display()))?;
                writeln!(f, "# {tool_label}")?;
                for v in &all {
                    writeln!(f, "{v}")?;
                }
                println!("Text report written to {}", out_path.display());
            }
            OutputFormat::Json => {
                let f = fs::File::create(&out_path)
                    .with_context(|| format!("creating {}", out_path.display()))?;
                serde_json::to_writer_pretty(f, &all).context("writing JSON")?;
                println!("JSON written to {}", out_path.display());
            }
        }
    } else if matches!(format, OutputFormat::Text) {
        for v in &all {
            println!("{v}");
        }
    }

    Ok(())
}
