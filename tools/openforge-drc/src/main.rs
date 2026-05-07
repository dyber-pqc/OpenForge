//! `openforge-drc` CLI.

use anyhow::{Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use std::fs;
use std::io::Write;
use std::path::PathBuf;

use openforge_drc::gds::reader::read_gds_with_layers;
use openforge_drc::rdb::write_rdb;
use openforge_drc::rules::parse_deck;
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

        /// DRC rule deck.
        #[arg(long)]
        rules: PathBuf,

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
            tech,
            output,
            format,
        } => run_check(gds, rules, tech, output, format),
    }
}

fn run_check(
    gds: PathBuf,
    rules_path: PathBuf,
    tech: String,
    output: Option<PathBuf>,
    format: OutputFormat,
) -> Result<()> {
    println!("Loading GDS: {}", gds.display());
    let rules_src = fs::read_to_string(&rules_path)
        .with_context(|| format!("reading {}", rules_path.display()))?;
    println!("Parsing rule deck: {}", rules_path.display());
    let deck = parse_deck(&rules_src).context("parsing rule deck")?;
    println!(
        "Found {} rule{} across {} layer{}.",
        deck.rules.len(),
        if deck.rules.len() == 1 { "" } else { "s" },
        deck.layers.len(),
        if deck.layers.len() == 1 { "" } else { "s" },
    );

    let layout = read_gds_with_layers(&gds, &deck.layers).context("reading GDS")?;

    let mut all = Vec::<Violation>::new();
    for rule in &deck.rules {
        let v = checks::run_rule(rule, &layout, &deck.layers)?;
        let label = match rule {
            openforge_drc::rules::ast::Rule::Width {
                name,
                min_um,
                layer,
                ..
            } => format!("{name} (min width {min_um} um on {layer})"),
            openforge_drc::rules::ast::Rule::Space {
                name,
                min_um,
                layer,
                ..
            } => format!("{name} (min space {min_um} um on {layer})"),
            openforge_drc::rules::ast::Rule::Enclosure { name, .. }
            | openforge_drc::rules::ast::Rule::Not { name, .. } => name.clone(),
        };
        println!(
            "Checking {}... {} violation{}",
            label,
            v.len(),
            if v.len() == 1 { "" } else { "s" }
        );
        all.extend(v);
    }

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
