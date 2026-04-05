use clap::Parser;

#[derive(Parser)]
#[command(name = "openforge-sca")]
#[command(about = "Side-channel analysis simulator for cryptographic RTL")]
#[command(version)]
struct Cli {
    /// Power trace input files (CSV or HDF5)
    #[arg(required = true)]
    traces: Vec<String>,

    /// Analysis mode
    #[arg(long, default_value = "tvla")]
    mode: String,

    /// Power model (hamming_weight, hamming_distance, switching)
    #[arg(long, default_value = "hamming_distance")]
    power_model: String,

    /// TVLA threshold (default: 4.5)
    #[arg(long, default_value = "4.5")]
    threshold: f64,

    /// Output report file
    #[arg(long, short)]
    output: Option<String>,
}

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();
    let cli = Cli::parse();

    println!("OpenForge Side-Channel Analysis");
    println!("================================");
    println!("Mode: {}", cli.mode);
    println!("Power model: {}", cli.power_model);
    println!("Threshold: {}", cli.threshold);
    println!("Trace files: {:?}", cli.traces);

    // TODO: Implement TVLA, CPA, and power model computation
    println!("\nAnalysis not yet implemented. Coming in Phase 5.");

    Ok(())
}
