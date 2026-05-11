//! Integration tests for the v0.4 DRX primitives:
//! `.separation`, `.area`, `.overhang`, `.surround`, `.notch`.
//!
//! Each test builds a tiny in-memory `Layout` with a known-answer geometry
//! and runs only the new rule kind, so the violation count is deterministic.

use openforge_drc::checks;
use openforge_drc::geom::Polygon;
use openforge_drc::rules::ast::Rule;
use openforge_drc::rules::parse_drx;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

fn fixtures_dir() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p
}

fn rect(layer: &str, x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon {
    Polygon::new(layer, vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "TOP")
}

fn layout(polys: Vec<Polygon>) -> openforge_drc::gds::Layout {
    openforge_drc::gds::Layout {
        top_cell: "TOP".into(),
        polygons: polys,
        units_um: 1e-3,
    }
}

#[test]
fn fixture_parses_into_expected_rules() {
    let src = fs::read_to_string(fixtures_dir().join("drx_extended.drc")).unwrap();
    let deck = parse_drx(&src).unwrap();
    // 5 emitted rules: separation, area, overhang, surround (-> Enclosure),
    // notch.
    assert_eq!(deck.rules.len(), 5, "deck rules: {:#?}", deck.rules);

    let kinds: Vec<&str> = deck
        .rules
        .iter()
        .map(|r| match r {
            Rule::Separation { .. } => "separation",
            Rule::Area { .. } => "area",
            Rule::Overhang { .. } => "overhang",
            Rule::Enclosure { .. } => "enclosure",
            Rule::Notch { .. } => "notch",
            other => panic!("unexpected rule kind: {other:?}"),
        })
        .collect();
    assert!(kinds.contains(&"separation"));
    assert!(kinds.contains(&"area"));
    assert!(kinds.contains(&"overhang"));
    assert!(kinds.contains(&"enclosure"));
    assert!(kinds.contains(&"notch"));
}

#[test]
fn separation_violation_counts() {
    // Two pairs:
    //   - nwell at x=0..1, diff at x=1.05..2.05 (gap 0.05 < 0.34) -> violation
    //   - nwell at x=10..11, diff at x=20..21 (gap 9 > 0.34) -> ok
    let lo = layout(vec![
        rect("nwell", 0.0, 0.0, 1.0, 1.0),
        rect("diff", 1.05, 0.0, 2.05, 1.0),
        rect("nwell", 10.0, 0.0, 11.0, 1.0),
        rect("diff", 20.0, 0.0, 21.0, 1.0),
    ]);
    let rule = Rule::Separation {
        layer_a: "nwell".into(),
        layer_b: "diff".into(),
        min_um: 0.34,
        name: "S".into(),
        message: "nw-diff".into(),
    };
    let v = checks::run_rule(&rule, &lo, &HashMap::new()).unwrap();
    assert_eq!(v.len(), 1, "got {v:#?}");
}

#[test]
fn area_violation_counts() {
    // 3 polygons: 0.01 (fail), 1.0 (pass), 0.05 (fail) for min 0.083.
    let lo = layout(vec![
        rect("met1", 0.0, 0.0, 0.1, 0.1),
        rect("met1", 5.0, 5.0, 6.0, 6.0),
        rect("met1", 10.0, 10.0, 10.5, 10.1),
    ]);
    let rule = Rule::Area {
        layer: "met1".into(),
        min_um2: 0.083,
        name: "A".into(),
        message: "min met1 area".into(),
    };
    let v = checks::run_rule(&rule, &lo, &HashMap::new()).unwrap();
    assert_eq!(v.len(), 2, "got {v:#?}");
}

#[test]
fn overhang_violation_counts() {
    // met1 outers (1.0 wide) with via insides:
    //   pair 1: via has 0.1 margin -> ok (req 0.06)
    //   pair 2: via has 0.02 margin -> fail (< 0.06)
    let lo = layout(vec![
        rect("met1", 0.0, 0.0, 1.0, 1.0),
        rect("via", 0.1, 0.1, 0.9, 0.9),
        rect("met1", 5.0, 0.0, 6.0, 1.0),
        rect("via", 5.02, 0.02, 5.98, 0.98),
    ]);
    let rule = Rule::Overhang {
        outer: "met1".into(),
        inner: "via".into(),
        min_um: 0.06,
        name: "O".into(),
        message: "met1 over via".into(),
    };
    let v = checks::run_rule(&rule, &lo, &HashMap::new()).unwrap();
    assert_eq!(v.len(), 1, "got {v:#?}");
    assert_eq!(v[0].layer, "met1");
}

#[test]
fn surround_alias_runs_as_enclosure() {
    // poly surrounds diff: surround is parsed as enclosing,
    // emits Rule::Enclosure with outer=poly, inner=diff.
    let src = r#"
        diff = input(65, 20)
        poly = input(66, 20)
        poly.surround(diff, 0.04).output("p.S", "poly surround diff")
    "#;
    let deck = parse_drx(src).unwrap();
    assert_eq!(deck.rules.len(), 1);
    match &deck.rules[0] {
        Rule::Enclosure {
            inner,
            outer,
            min_um,
            ..
        } => {
            assert_eq!(outer, "L66D20");
            assert_eq!(inner, "L65D20");
            assert!((*min_um - 0.04).abs() < 1e-9);
        }
        other => panic!("expected Enclosure, got {other:?}"),
    }

    // Geometric: poly outer 0..1, diff inner 0.05..0.95 -> margin 0.05 > 0.04 -> ok.
    let lo = layout(vec![
        rect("L66D20", 0.0, 0.0, 1.0, 1.0),
        rect("L65D20", 0.05, 0.05, 0.95, 0.95),
    ]);
    let v = checks::run_rule(&deck.rules[0], &lo, &deck.layers).unwrap();
    assert!(v.is_empty(), "got {v:#?}");

    // Now insufficient margin (0.02 < 0.04) -> fail.
    let lo = layout(vec![
        rect("L66D20", 0.0, 0.0, 1.0, 1.0),
        rect("L65D20", 0.02, 0.02, 0.98, 0.98),
    ]);
    let v = checks::run_rule(&deck.rules[0], &lo, &deck.layers).unwrap();
    assert_eq!(v.len(), 1);
}

#[test]
fn notch_violation_counts() {
    // U-shape with a 0.05-wide slot - violates a 0.14 notch rule.
    let pts = vec![
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.525, 1.0),
        (0.525, 0.5),
        (0.475, 0.5),
        (0.475, 1.0),
        (0.0, 1.0),
    ];
    let polys = vec![Polygon::new("met1", pts, "TOP")];
    let lo = layout(polys);
    let rule = Rule::Notch {
        layer: "met1".into(),
        min_um: 0.14,
        name: "N".into(),
        message: "met1 notch".into(),
    };
    let v = checks::run_rule(&rule, &lo, &HashMap::new()).unwrap();
    assert_eq!(v.len(), 1, "got {v:#?}");
}
