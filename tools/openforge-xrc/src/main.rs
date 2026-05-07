//! openforge-xrc CLI.

use anyhow::{Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use openforge_xrc::tech::Corner;
use openforge_xrc::{def, extract, lef, spef, tech};
use std::path::PathBuf;

#[derive(Copy, Clone, Debug, ValueEnum)]
enum CornerArg {
    Min,
    Typ,
    Max,
    All,
}

#[derive(Parser, Debug)]
#[command(
    name = "openforge-xrc",
    version,
    about = "OpenForge xRC — Rust-based parasitic extraction (R+C) for VLSI"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Extract parasitics from a routed DEF and write SPEF.
    Extract {
        #[arg(long)]
        def: PathBuf,
        #[arg(long)]
        lef: PathBuf,
        #[arg(long, default_value = "sky130A")]
        tech: String,
        #[arg(long, short = 'o')]
        output: PathBuf,
        /// Process corner: `min`, `typ`, `max`, or `all` (writes 3 SPEFs).
        #[arg(long, value_enum, default_value_t = CornerArg::Typ)]
        corner: CornerArg,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Extract {
            def: def_path,
            lef: lef_path,
            tech: tech_name,
            output,
            corner,
        } => run_extract(def_path, lef_path, tech_name, output, corner),
    }
}

fn corner_output_path(base: &std::path::Path, c: Corner) -> PathBuf {
    let stem = base
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("output");
    let ext = base.extension().and_then(|s| s.to_str()).unwrap_or("spef");
    let new_name = format!("{stem}.{}.{}", c.label(), ext);
    base.with_file_name(new_name)
}

fn run_extract(
    def_path: PathBuf,
    lef_path: PathBuf,
    tech_name: String,
    output: PathBuf,
    corner_arg: CornerArg,
) -> Result<()> {
    println!(
        "[1/5] Parsing tech: {tech_name}{}",
        if tech_name == "sky130A" {
            " (built-in)"
        } else {
            ""
        }
    );
    let tech_file = tech::load(&tech_name).context("loading tech")?;
    println!(
        "      → {} layers, {} via types",
        tech_file.layers.len(),
        tech_file.vias.len()
    );

    println!("[2/5] Parsing LEF: {}", lef_path.display());
    let lef_lib = lef::parse_file(&lef_path).context("parsing LEF")?;
    println!("      → {} cells loaded", lef_lib.macros.len());

    println!("[3/5] Parsing DEF: {}", def_path.display());
    let def_ast = def::parse_file(&def_path).context("parsing DEF")?;
    let layers_used: std::collections::BTreeSet<&str> = def_ast
        .nets
        .iter()
        .flat_map(|n| n.routes.iter().map(|r| r.layer.as_str()))
        .collect();
    println!(
        "      → {} components, {} nets, {} routing layers used",
        def_ast.components.len(),
        def_ast.nets.len(),
        layers_used.len()
    );

    println!("[4/5] Extracting parasitics...");
    let corners: Vec<Corner> = match corner_arg {
        CornerArg::Min => vec![Corner::Min],
        CornerArg::Typ => vec![Corner::Typ],
        CornerArg::Max => vec![Corner::Max],
        CornerArg::All => vec![Corner::Min, Corner::Typ, Corner::Max],
    };
    let mut last_result: Option<extract::ExtractionResult> = None;
    for c in &corners {
        let tech_c = tech_file.clone().with_corner(*c);
        let result = extract::extract(&def_ast, &lef_lib, &tech_c);
        let out_path = if corners.len() > 1 {
            corner_output_path(&output, *c)
        } else {
            output.clone()
        };
        println!(
            "      → corner={}, {} nets processed",
            c.label(),
            result.nets.len()
        );
        println!("[5/5] Writing SPEF: {}", out_path.display());
        let spef_text = spef::write_spef(&result);
        std::fs::write(&out_path, &spef_text).context("writing SPEF")?;
        last_result = Some(result);
    }
    let result = last_result.unwrap_or_default();

    println!();
    println!("Summary:");
    println!("  Total wirelength: {:.1} um", result.total_wirelength_um());
    println!("  Total R:          {:.1} ohm", result.total_r_ohm());
    println!("  Total C:          {:.1} fF", result.total_c_ff());
    if let Some(w) = result.worst_net() {
        println!(
            "  Worst-case net:   {} (R={:.1} ohm, C={:.2} fF)",
            w.net_name, w.total_res_ohm, w.total_cap_ff
        );
    }
    let total_couples: usize = result.nets.iter().map(|n| n.coupling.len()).sum();
    println!(
        "  Coupling caps:    {} ({} skipped — adjacency below threshold)",
        total_couples / 2, // each pair listed on both nets
        result.coupling_skipped
    );

    Ok(())
}
