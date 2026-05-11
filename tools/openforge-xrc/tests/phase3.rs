//! Phase 3: pattern-matched extraction + multi-corner support tests.

use openforge_xrc::extract::patterns::{self, LocalGeom};
use openforge_xrc::tech::Corner;
use openforge_xrc::{def, extract, lef, tech};

#[test]
fn pattern_matcher_classifies_clean_parallel_run() {
    let t = tech::load("sky130A").unwrap();
    let mut g = LocalGeom::new(&t, "met1", 10.0, 0.14).expect("met1 layer");
    g.neighbor_count = 1;
    g.spacing_um = Some(0.30);
    let (name, c) = patterns::classify(&g, &t).expect("a pattern matched");
    assert_eq!(name, "line_to_line_same_layer");
    assert!(c > 0.0, "non-zero capacitance expected");
    // Side-fringe scaling should make this strictly larger than the
    // single-line ST baseline at the same geometry.
    let mut clean = g.clone();
    clean.neighbor_count = 0;
    clean.spacing_um = None;
    let (_, c_clean) = patterns::classify(&clean, &t).unwrap();
    assert!(
        c > c_clean,
        "parallel run should have higher cap than isolated wire ({c} vs {c_clean})"
    );
}

#[test]
fn pattern_matcher_isolated_wire_uses_single_line() {
    let t = tech::load("sky130A").unwrap();
    let g = LocalGeom::new(&t, "met2", 5.0, 0.14).unwrap();
    let (name, _) = patterns::classify(&g, &t).unwrap();
    assert_eq!(name, "single_line_over_plane");
}

#[test]
fn pattern_matcher_t_junction_priority() {
    let t = tech::load("sky130A").unwrap();
    let mut g = LocalGeom::new(&t, "met1", 5.0, 0.14).unwrap();
    g.has_corner = true;
    let (name, _) = patterns::classify(&g, &t).unwrap();
    assert_eq!(name, "t_junction");
}

#[test]
fn multi_corner_produces_ordered_totals() {
    // Re-extract the tiny fixture at min/typ/max and confirm strict ordering.
    let def_ast = def::parse_file("tests/fixtures/tiny.def").expect("tiny.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("tiny.lef");

    let totals: Vec<f64> = [Corner::Min, Corner::Typ, Corner::Max]
        .iter()
        .map(|c| {
            let tf = tech::load("sky130A").unwrap().with_corner(*c);
            extract::extract(&def_ast, &lef_lib, &tf).total_c_ff()
        })
        .collect();

    assert!(
        totals[0] < totals[1] && totals[1] < totals[2],
        "expected min < typ < max, got {:?}",
        totals
    );
    // Endpoints should differ from typ by ~10%.
    let dev_min = (totals[1] - totals[0]) / totals[1];
    let dev_max = (totals[2] - totals[1]) / totals[1];
    assert!(
        (0.08..=0.12).contains(&dev_min),
        "min deviation should be ~10%, got {dev_min}"
    );
    assert!(
        (0.08..=0.12).contains(&dev_max),
        "max deviation should be ~10%, got {dev_max}"
    );
}

#[test]
fn counter_total_within_phase2_baseline() {
    let def_path = "../../examples/asic-counter-sky130/build/routing/routed.def";
    if !std::path::Path::new(def_path).exists() {
        eprintln!("skipping: {def_path} not present");
        return;
    }
    let def_ast = def::parse_file(def_path).expect("parse routed.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);
    let total_c = result.total_c_ff();

    // Phase 2 baseline was ~1734 fF, but that figure was inflated by a
    // cross-layer coupling bug that treated each diagonal-segment bbox as
    // its true conductor footprint and by an unbounded 1/spacing kernel
    // for same-layer coupling. Both are now fixed (see
    // `extract::cross_layer` + `extract::coupling`); the post-fix counter
    // total lands in the ~500 fF range, consistent with hand-calc
    // (~0.075 fF/µm self-cap × 2250 µm + modest coupling).
    let baseline = 510.0_f64;
    let lo = baseline * 0.80;
    let hi = baseline * 1.20;
    assert!(
        (lo..=hi).contains(&total_c),
        "counter total C {total_c} outside ±20% of Phase 2 baseline {baseline}"
    );
}

#[test]
fn pattern_classify_returns_some_for_all_layers() {
    // Make sure the pattern library covers every routing layer in sky130A.
    let t = tech::load("sky130A").unwrap();
    for lp in &t.layers {
        let g = LocalGeom::new(&t, &lp.name, 1.0, lp.min_width_um);
        assert!(g.is_some(), "LocalGeom failed for layer {}", lp.name);
        let res = patterns::classify(&g.unwrap(), &t);
        assert!(res.is_some(), "no pattern matched for {}", lp.name);
    }
}
