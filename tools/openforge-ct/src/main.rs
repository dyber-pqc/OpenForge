use clap::Parser;
use openforge_ct::CTAnalyzer;
use tracing_subscriber::EnvFilter;

#[derive(Parser)]
#[command(name = "openforge-ct")]
#[command(about = "Constant-time analysis for cryptographic RTL designs")]
#[command(version)]
struct Cli {
    /// Source files to analyze
    #[arg(required = true)]
    files: Vec<String>,

    /// Signals to mark as secret (comma-separated)
    #[arg(long, value_delimiter = ',')]
    secrets: Vec<String>,

    /// Signals to mark as public (comma-separated)
    #[arg(long, value_delimiter = ',')]
    public: Vec<String>,

    /// Output format (text, json, sarif)
    #[arg(long, default_value = "text")]
    format: String,

    /// Generate formal SVA properties
    #[arg(long)]
    formal: bool,

    /// Output file for formal properties
    #[arg(long)]
    formal_output: Option<String>,
}

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .init();

    let cli = Cli::parse();

    let mut analyzer = CTAnalyzer::new(cli.files);

    for secret in &cli.secrets {
        analyzer.mark_secret(secret);
    }

    for public in &cli.public {
        analyzer.mark_public(public);
    }

    let report = analyzer.analyze()?;

    match cli.format.as_str() {
        "json" => {
            println!("{}", serde_json::to_string_pretty(&serde_json::json!({
                "violations": report.violations.len(),
                "tainted_signals": report.tainted_signals.len(),
                "formal_properties": report.formal_properties.len(),
            }))?);
        }
        _ => {
            println!("OpenForge Constant-Time Analysis Report");
            println!("========================================");
            println!("Signals analyzed: {}", report.total_signals_analyzed);
            println!("Tainted signals: {}", report.tainted_signals.len());
            println!("Violations: {}", report.violations.len());
            println!();

            if report.violations.is_empty() {
                println!("PASS: No constant-time violations detected.");
            } else {
                for v in &report.violations {
                    println!("  FAIL: {v}");
                }
            }

            if cli.formal {
                println!("\nGenerated {} formal properties", report.formal_properties.len());
                if let Some(output) = &cli.formal_output {
                    let content = report.formal_properties.join("\n\n");
                    std::fs::write(output, content)?;
                    println!("Written to {output}");
                }
            }
        }
    }

    if report.violations.is_empty() {
        std::process::exit(0);
    } else {
        std::process::exit(1);
    }
}
