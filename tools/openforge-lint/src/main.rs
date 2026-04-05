use clap::Parser;

#[derive(Parser)]
#[command(name = "openforge-lint")]
#[command(about = "Fast RTL linting engine for OpenForge EDA")]
#[command(version)]
struct Cli {
    /// Source files to lint
    #[arg(required = true)]
    files: Vec<String>,

    /// Output format (text, json, sarif)
    #[arg(long, default_value = "text")]
    format: String,

    /// Enable crypto-specific lint rules
    #[arg(long)]
    crypto: bool,
}

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();
    let cli = Cli::parse();

    println!("OpenForge RTL Linter");
    println!("====================");
    println!("Files: {:?}", cli.files);
    println!("Crypto rules: {}", cli.crypto);

    // TODO: Parse with sv-parser, apply lint rules
    println!("\nLinting not yet implemented. Delegating to Verible for now.");

    Ok(())
}
