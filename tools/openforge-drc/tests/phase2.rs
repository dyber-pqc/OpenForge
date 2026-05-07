//! Phase-2 integration tests: enclosure, density, parallel runner,
//! and a counter-design performance budget.

use gds21::{GdsBoundary, GdsElement, GdsLibrary, GdsPoint, GdsStruct, GdsUnits};
use openforge_drc::checks;
use openforge_drc::gds::reader::read_gds_with_layers;
use openforge_drc::rules::parse_deck;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;
use tempfile::tempdir;

fn fixtures_dir() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p
}

/// Build a tiny GDS with:
///   - Two `outer` (layer 71) rectangles
///   - Two `inner` (layer 70) rectangles - one properly enclosed,
///     one with insufficient margin (only 0.05 um inside its outer).
fn write_enclosure_gds(path: &std::path::Path) {
    let units = GdsUnits::default(); // 1 nm DB unit, 1 um user unit

    fn rect(layer: i16, x0: i32, y0: i32, x1: i32, y1: i32) -> GdsBoundary {
        GdsBoundary {
            layer,
            datatype: 0,
            xy: GdsPoint::vec(&[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]),
            ..Default::default()
        }
    }

    let mut s = GdsStruct::new("TOP");
    // Outer #1: 0..1000 nm = 0..1.0 um. Inner with 0.2 um margin: pass.
    s.elems
        .push(GdsElement::GdsBoundary(rect(71, 0, 0, 1000, 1000)));
    s.elems
        .push(GdsElement::GdsBoundary(rect(70, 200, 200, 800, 800)));
    // Outer #2: 2000..3000 = 2.0..3.0 um. Inner with only 0.05 um margin: fail.
    s.elems
        .push(GdsElement::GdsBoundary(rect(71, 2000, 0, 3000, 1000)));
    s.elems
        .push(GdsElement::GdsBoundary(rect(70, 2050, 50, 2950, 950)));

    let lib = GdsLibrary {
        name: "enc".to_string(),
        units,
        structs: vec![s],
        ..Default::default()
    };
    lib.save(path).unwrap();
}

#[test]
fn enclosure_detects_insufficient_margin() {
    let dir = tempdir().unwrap();
    let p = dir.path().join("enc.gds");
    write_enclosure_gds(&p);

    let deck_src = fs::read_to_string(fixtures_dir().join("enclosure.drc")).unwrap();
    let deck = parse_deck(&deck_src).unwrap();
    let layout = read_gds_with_layers(&p, &deck.layers).unwrap();
    assert_eq!(layout.polygons.len(), 4);

    let v = checks::run_rules(&deck.rules, &layout, &deck.layers).unwrap();
    assert_eq!(v.len(), 1, "exactly one enclosure violation, got {v:#?}");
    assert_eq!(v[0].rule, "enc.E.1");
    assert_eq!(v[0].layer, "inner");
}

/// Build a GDS with one mostly-empty 100x100 um window on met1 (only a tiny
/// 1x1 um square) - should violate min-density 0.20.
fn write_low_density_gds(path: &std::path::Path) {
    let units = GdsUnits::default();
    fn rect(layer: i16, x0: i32, y0: i32, x1: i32, y1: i32) -> GdsBoundary {
        GdsBoundary {
            layer,
            datatype: 0,
            xy: GdsPoint::vec(&[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]),
            ..Default::default()
        }
    }
    let mut s = GdsStruct::new("TOP");
    // Tiny shape near origin
    s.elems
        .push(GdsElement::GdsBoundary(rect(68, 0, 0, 1000, 1000)));
    // Anchor a 100x100 um bbox with a 1x1 nm spec at (100000, 100000).
    s.elems.push(GdsElement::GdsBoundary(rect(
        68, 99999, 99999, 100000, 100000,
    )));
    let lib = GdsLibrary {
        name: "dens".into(),
        units,
        structs: vec![s],
        ..Default::default()
    };
    lib.save(path).unwrap();
}

#[test]
fn density_detects_too_empty_window() {
    let dir = tempdir().unwrap();
    let p = dir.path().join("d.gds");
    write_low_density_gds(&p);

    let deck_src = fs::read_to_string(fixtures_dir().join("density.drc")).unwrap();
    let deck = parse_deck(&deck_src).unwrap();
    let layout = read_gds_with_layers(&p, &deck.layers).unwrap();

    let v = checks::run_rules(&deck.rules, &layout, &deck.layers).unwrap();
    // Density should be ~1.0 in the (0,0)-(1,1) corner window and ~0 elsewhere.
    // We expect at least one min-density violation, no max-density violation.
    let min_violations = v.iter().filter(|x| x.rule == "met1.D.min").count();
    let max_violations = v.iter().filter(|x| x.rule == "met1.D.max").count();
    assert!(
        min_violations >= 1,
        "expected min-density violation in mostly-empty layout, got {v:?}"
    );
    assert_eq!(max_violations, 0);
}

#[test]
fn parser_accepts_density_rules() {
    let src = r#"
        LAYER m1 = 68
        RULE m1.D.lo : m1.density window 50 < 0.10 = "low"
        RULE m1.D.hi : m1.density window 50 > 0.95 = "high"
    "#;
    let deck = parse_deck(src).unwrap();
    assert_eq!(deck.rules.len(), 2);
}

/// Performance budget: the full simple.drc deck (3 rules) should complete
/// against the bundled counter.gds in well under 500 ms. This guards
/// against accidental quadratic regressions in the spacing path.
#[test]
fn counter_perf_under_budget() {
    let mut gds = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    gds.pop();
    gds.pop();
    gds.push("examples");
    gds.push("asic-counter-sky130");
    gds.push("build");
    gds.push("gds_export");
    gds.push("counter.gds");
    if !gds.exists() {
        eprintln!("counter.gds not present - skipping perf test");
        return;
    }
    let deck_src = fs::read_to_string(fixtures_dir().join("simple.drc")).unwrap();
    let deck = parse_deck(&deck_src).unwrap();
    let layout = match read_gds_with_layers(&gds, &deck.layers) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("could not read counter.gds: {e} - skipping");
            return;
        }
    };
    let t = Instant::now();
    let v = checks::run_rules(&deck.rules, &layout, &deck.layers).unwrap();
    let elapsed = t.elapsed();
    eprintln!(
        "counter.gds: {} polygons, {} violations, ran in {:?}",
        layout.polygons.len(),
        v.len(),
        elapsed
    );
    assert!(
        elapsed.as_millis() < 500,
        "DRC took {:?} - should be under 500 ms",
        elapsed
    );
}
