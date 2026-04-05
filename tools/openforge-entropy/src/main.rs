use clap::Parser;

#[derive(Parser)]
#[command(name = "openforge-entropy")]
#[command(about = "Entropy flow analyzer for cryptographic RTL designs")]
#[command(version)]
struct Cli {
    /// Source files to analyze
    #[arg(required = true)]
    files: Vec<String>,

    /// Entropy source signals (signal:bits_per_sample)
    #[arg(long, value_delimiter = ',')]
    sources: Vec<String>,

    /// Entropy sink signals (signal:required_bits)
    #[arg(long, value_delimiter = ',')]
    sinks: Vec<String>,

    /// Output format (text, json)
    #[arg(long, default_value = "text")]
    format: String,
}

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();
    let cli = Cli::parse();

    println!("OpenForge Entropy Flow Analyzer");
    println!("================================");
    println!("Sources: {:?}", cli.sources);
    println!("Sinks: {:?}", cli.sinks);
    println!("Files: {:?}", cli.files);

    // TODO: Build entropy flow graph, detect reductions, verify paths
    println!("\nAnalysis not yet implemented. Coming in Phase 5.");

    Ok(())
}
