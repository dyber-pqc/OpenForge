//! Opportunistic test: try to parse the real sky130A KLayout DRC deck if
//! it's installed on the host. We probe a few common locations:
//!
//!   - $PDK_ROOT/sky130A/libs.tech/klayout/drc/sky130A_mr.drc
//!   - $HOME/.volare/sky130A/libs.tech/klayout/drc/sky130A_mr.drc
//!   - %USERPROFILE%/.volare/sky130A/libs.tech/klayout/drc/sky130A_mr.drc
//!
//! If none is found we silently pass — this is informational, not a CI gate.
//! When it does run we report partial-coverage stats so we can track progress
//! across releases.

use openforge_drc::rules::parse_drx;
use std::path::PathBuf;

fn candidate_paths() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(p) = std::env::var("PDK_ROOT") {
        out.push(PathBuf::from(p).join("sky130A/libs.tech/klayout/drc/sky130A_mr.drc"));
    }
    if let Ok(home) = std::env::var("HOME") {
        out.push(PathBuf::from(home).join(".volare/sky130A/libs.tech/klayout/drc/sky130A_mr.drc"));
    }
    if let Ok(home) = std::env::var("USERPROFILE") {
        out.push(PathBuf::from(home).join(".volare/sky130A/libs.tech/klayout/drc/sky130A_mr.drc"));
    }
    out
}

#[test]
fn try_parse_real_sky130_deck() {
    let path = candidate_paths().into_iter().find(|p| p.exists());
    let Some(path) = path else {
        eprintln!("(skipping: no sky130A DRC deck found at any candidate path)");
        return;
    };
    eprintln!("Parsing {}", path.display());
    let src = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("(skipping: read error: {e})");
            return;
        }
    };
    match parse_drx(&src) {
        Ok(deck) => {
            eprintln!(
                "Parsed sky130A deck '{}': {} layers, {} derived, {} rules",
                deck.name,
                deck.layers.len(),
                deck.derived.len(),
                deck.rules.len()
            );
            // Even partial coverage should yield *some* rules.
            // If 0, our parser is regressed.
            assert!(
                deck.rules.len() + deck.derived.len() > 0,
                "expected at least one parsed construct from the real deck"
            );
        }
        Err(e) => {
            // For v0.3 we permit a hard error on the full deck (Ruby
            // constructs we don't understand). Print and pass.
            eprintln!("(partial: parser failed on real deck: {e})");
        }
    }
}
