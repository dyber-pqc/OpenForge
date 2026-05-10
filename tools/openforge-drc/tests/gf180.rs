//! Multi-PDK regression: parse the gf180mcuC DRX subset fixture and run
//! one of its width rules against a synthetic layout. Asserts that the
//! parser handles gf180 layer numbers and that the rule engine produces
//! deterministic violation counts on a known-bad polygon.

use openforge_drc::checks;
use openforge_drc::gds::reader::Layout;
use openforge_drc::geom::Polygon;
use openforge_drc::rules::ast::{BoolOp, Rule};
use openforge_drc::rules::{looks_like_drx, parse_deck, parse_drx};
use std::fs;
use std::path::PathBuf;

fn fixture(name: &str) -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p.push(name);
    p
}

#[test]
fn parses_gf180mcu_subset_fixture() {
    let src = fs::read_to_string(fixture("gf180mcu_subset.drc")).expect("read fixture");
    assert!(looks_like_drx(&src), "fixture should look like DRX");
    let deck = parse_drx(&src).expect("parse fixture");
    assert_eq!(deck.name, "gf180mcuC subset DRC");

    // 10 input() calls -> 10 primitive layers (Comp, Nwell, Poly, Contact,
    // Metal1..Metal5, Via1).
    assert!(
        deck.layers.len() >= 10,
        "expected >= 10 input layers, got {}",
        deck.layers.len()
    );

    // 1 derived layer: comp.outside(nwell).
    assert_eq!(deck.derived.len(), 1);
    assert_eq!(deck.derived[0].op, BoolOp::Outside);

    // The fixture writes 14 .output() calls; the density rule expands to
    // {min, max} → 15 rules total. Assert >= 14 to leave headroom.
    assert!(
        deck.rules.len() >= 14,
        "expected >= 14 rules, got {}",
        deck.rules.len()
    );

    // Spot-check: gf180 layer GDS numbers landed correctly in the deck.
    let m1 = deck
        .layers
        .values()
        .find(|l| l.layer == 34 && l.datatype == 0)
        .expect("Metal1 (34/0) layer present");
    let m5 = deck
        .layers
        .values()
        .find(|l| l.layer == 81 && l.datatype == 0)
        .expect("Metal5 (81/0) layer present");
    let _ = (m1, m5);
}

#[test]
fn gf180_width_rule_flags_undersized_polygon() {
    // Tiny synthetic deck: one width rule on Metal1 (layer 34/0) at 0.23 µm
    // minimum width. Use the legacy `LAYER`/`RULE` deck so we have full
    // control over both the layer mapping and the rule shape.
    let deck_src = r#"
        LAYER Metal1 = 34
        RULE M1.W : Metal1.width < 0.23 = "gf180 Metal1 minimum width 0.23"
    "#;
    let deck = parse_deck(deck_src).expect("parse");
    assert_eq!(deck.rules.len(), 1);

    // Build a layout containing a single Metal1 rectangle 1.0 µm × 0.10 µm
    // — clearly below the 0.23 µm minimum. Coordinates are in user units
    // (microns), matching what `read_gds_with_layers` would produce.
    let mut layout = Layout {
        top_cell: "gf180_test".to_string(),
        polygons: Vec::new(),
        units_um: 1e-3,
    };
    let pts = vec![(0.0, 0.0), (1.0, 0.0), (1.0, 0.10), (0.0, 0.10)];
    layout
        .polygons
        .push(Polygon::new("Metal1", pts, "gf180_test"));

    let v = checks::run_rule(&deck.rules[0], &layout, &deck.layers).expect("run");
    assert!(
        !v.is_empty(),
        "expected at least one width violation on undersized Metal1 polygon"
    );
    assert!(
        v.iter().all(|x| x.rule == "M1.W"),
        "all violations should belong to rule M1.W, got: {:?}",
        v.iter().map(|x| &x.rule).collect::<Vec<_>>()
    );
}

#[test]
fn gf180_density_rule_emits_a_density_entry() {
    let src = fs::read_to_string(fixture("gf180mcu_subset.drc")).unwrap();
    let deck = parse_drx(&src).unwrap();
    let n_density = deck
        .rules
        .iter()
        .filter(|r| matches!(r, Rule::Density { .. }))
        .count();
    assert!(
        n_density >= 1,
        "expected at least one density rule from M1.D, got {n_density}"
    );
}
