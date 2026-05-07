//! End-to-end tests against the DRX parser using the sky130-subset fixture.

use openforge_drc::rules::ast::{BoolOp, Rule};
use openforge_drc::rules::{looks_like_drx, parse_deck_auto, parse_drx};
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
fn parses_sky130_subset_fixture() {
    let src = fs::read_to_string(fixture("sky130_subset.drc")).unwrap();
    let deck = parse_drx(&src).expect("parse fixture");
    assert_eq!(deck.name, "sky130A subset DRC");
    // 6 input() calls -> 6 primitive layers.
    assert!(deck.layers.len() >= 6, "got {}", deck.layers.len());

    // 1 derived layer (diff_outside_well).
    assert_eq!(deck.derived.len(), 1);
    assert_eq!(deck.derived[0].op, BoolOp::Outside);

    // Rules emitted: li.1, li.2, met1.1, met1.2, li.4, diff.1, met1.D.min, met1.D.max
    assert_eq!(deck.rules.len(), 8, "got {:#?}", deck.rules);
}

#[test]
fn auto_detect_recognises_drx() {
    let src = fs::read_to_string(fixture("sky130_subset.drc")).unwrap();
    assert!(looks_like_drx(&src));
    let deck = parse_deck_auto(&src).unwrap();
    assert!(!deck.rules.is_empty());
}

#[test]
fn auto_detect_falls_back_to_simple() {
    let src = fs::read_to_string(fixture("simple.drc")).unwrap();
    assert!(!looks_like_drx(&src));
    let deck = parse_deck_auto(&src).unwrap();
    // 3 rules in simple.drc.
    assert_eq!(deck.rules.len(), 3);
}

#[test]
fn input_with_default_datatype() {
    let src = "li1 = input(67)\nli1.width(0.17).output(\"w\", \"m\")\n";
    let deck = parse_drx(src).unwrap();
    let spec = deck.layers.values().next().unwrap();
    assert_eq!(spec.datatype, 0);
    assert_eq!(spec.layer, 67);
}

#[test]
fn unknown_method_warns_but_doesnt_fail() {
    // `.smooth(0.05)` isn't supported; the deck should still parse.
    let src = r#"
        li1 = input(67, 20)
        li1.smooth(0.05).width(0.17).output("li.x", "smoothed")
    "#;
    // Either the deck parses with a warning, or the chain produces no rule.
    // What matters is we don't return a hard error.
    let r = parse_drx(src);
    assert!(r.is_ok(), "{r:?}");
}

#[test]
fn rules_reference_synthetic_or_derived_layer_names() {
    let src = fs::read_to_string(fixture("sky130_subset.drc")).unwrap();
    let deck = parse_drx(&src).unwrap();
    let mut found_derived = false;
    for r in &deck.rules {
        if let Rule::Width { layer, .. } = r {
            if layer.starts_with("__derived_") {
                found_derived = true;
            }
        }
    }
    assert!(
        found_derived,
        "expected at least one rule on a derived layer"
    );
}
