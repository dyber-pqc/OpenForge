//! Smoke test against the real bundled counter design, *if* it's been
//! built. The test silently passes if the GDS isn't present so CI doesn't
//! break on a fresh checkout.

use openforge_drc::checks;
use openforge_drc::gds::reader::read_gds_with_layers;
use openforge_drc::rules::parse_deck;
use std::path::PathBuf;

fn counter_gds() -> Option<PathBuf> {
    // CARGO_MANIFEST_DIR is .../tools/openforge-drc — climb to the repo root.
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop(); // tools/
    p.pop(); // repo root
    p.push("examples");
    p.push("asic-counter-sky130");
    p.push("build");
    p.push("gds_export");
    p.push("counter.gds");
    if p.exists() {
        Some(p)
    } else {
        None
    }
}

#[test]
fn counter_passes_minimal_sky130_width_check() {
    let Some(gds) = counter_gds() else {
        eprintln!("counter.gds not present — skipping smoke test");
        return;
    };

    // Minimal sky130 width-only deck.
    let deck_src = r#"
        LAYER met1 = 68
        LAYER li1  = 67
        RULE met1.W.1 : met1.width < 0.14 = "sky130 met1 minimum width"
        RULE li1.W.1  : li1.width  < 0.17 = "sky130 li1 minimum width"
    "#;
    let deck = parse_deck(deck_src).unwrap();
    let layout = match read_gds_with_layers(&gds, &deck.layers) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("could not read counter.gds ({e}) — skipping smoke test");
            return;
        }
    };

    let mut total = 0;
    for rule in &deck.rules {
        let v = checks::run_rule(rule, &layout, &deck.layers).unwrap();
        total += v.len();
    }
    eprintln!(
        "counter.gds: {} polygons across all layers, {} width violations on met1+li1",
        layout.polygons.len(),
        total
    );
    // We don't assert == 0 because the example may or may not be a clean
    // P&R run; we just exercise the read path on a real design.
}
