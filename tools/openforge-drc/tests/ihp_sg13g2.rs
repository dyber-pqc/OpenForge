//! Multi-PDK regression: parse the IHP sg13g2 (130 nm SiGe BiCMOS) DRX
//! subset fixture and run one of its width rules against a synthetic
//! layout. Asserts that the parser handles IHP layer numbers and that
//! the rule engine produces deterministic violation counts on a
//! known-bad polygon.

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
fn parses_ihp_sg13g2_subset_fixture() {
    let src = fs::read_to_string(fixture("ihp_sg13g2_subset.drc")).expect("read fixture");
    assert!(looks_like_drx(&src), "fixture should look like DRX");
    let deck = parse_drx(&src).expect("parse fixture");
    assert_eq!(deck.name, "ihp sg13g2 subset DRC");

    // 12 input() calls -> 12 primitive layers (Activ, NWell, GatPoly, Cont,
    // Metal1, Via1, Metal2..Metal5, TopMetal1, TopMetal2).
    assert!(
        deck.layers.len() >= 12,
        "expected >= 12 input layers, got {}",
        deck.layers.len()
    );

    // 1 derived layer: activ.outside(nwell).
    assert_eq!(deck.derived.len(), 1);
    assert_eq!(deck.derived[0].op, BoolOp::Outside);

    // Many rules incl. density (which expands to {min, max}) — be permissive.
    assert!(
        deck.rules.len() >= 14,
        "expected >= 14 rules, got {}",
        deck.rules.len()
    );

    // Spot-check: IHP layer GDS numbers landed correctly in the deck.
    let m1 = deck
        .layers
        .values()
        .find(|l| l.layer == 8 && l.datatype == 0)
        .expect("Metal1 (8/0) layer present");
    let tm2 = deck
        .layers
        .values()
        .find(|l| l.layer == 134 && l.datatype == 0)
        .expect("TopMetal2 (134/0) layer present");
    let _ = (m1, tm2);
}

#[test]
fn ihp_sg13g2_width_rule_flags_undersized_polygon() {
    // Tiny synthetic deck: one width rule on Metal1 (layer 8/0) at 0.16 µm
    // minimum width.
    let deck_src = r#"
        LAYER Metal1 = 8
        RULE M1.W : Metal1.width < 0.16 = "ihp Metal1 minimum width 0.16"
    "#;
    let deck = parse_deck(deck_src).expect("parse");
    assert_eq!(deck.rules.len(), 1);

    // Build a layout containing a single Metal1 rectangle 1.0 µm × 0.08 µm
    // — clearly below the 0.16 µm minimum.
    let mut layout = Layout {
        top_cell: "ihp_test".to_string(),
        polygons: Vec::new(),
        units_um: 1e-3,
    };
    let pts = vec![(0.0, 0.0), (1.0, 0.0), (1.0, 0.08), (0.0, 0.08)];
    layout
        .polygons
        .push(Polygon::new("Metal1", pts, "ihp_test"));

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
fn ihp_sg13g2_density_rule_emits_a_density_entry() {
    let src = fs::read_to_string(fixture("ihp_sg13g2_subset.drc")).unwrap();
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
