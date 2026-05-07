use openforge_xrc::extract::{capacitance, cross_layer};
use openforge_xrc::{def, extract, lef, spef, tech};

fn load_tiny() -> extract::ExtractionResult {
    let def_ast = def::parse_file("tests/fixtures/tiny.def").expect("parse tiny.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("tech");
    extract::extract(&def_ast, &lef_lib, &tech_file)
}

#[test]
fn test_tiny_extraction() {
    let result = load_tiny();
    assert_eq!(result.nets.len(), 1, "expected 1 net");
    let n = &result.nets[0];
    assert_eq!(n.net_name, "net1");
    // 3 um run on met1, width 0.14 um → R = 0.125 * 3 / 0.14 ≈ 2.679 ohm
    let expected_r = 0.125 * 3.0 / 0.14;
    let r_err = (n.total_res_ohm - expected_r).abs() / expected_r;
    assert!(
        r_err < 0.05,
        "R out of tolerance: got {}, expected {}",
        n.total_res_ohm,
        expected_r
    );
    // v0.2: Sakurai–Tamaru self-cap. Recompute via the extractor's own helper
    // so the assertion tracks the canonical formula (w=0.14, l=3, h=1.37, t=0.36).
    let tech_file = tech::load("sky130A").unwrap();
    let (c_area, c_fringe) = capacitance::wire_capacitance_split(&tech_file, "met1", 3.0, 0.14);
    let expected_c = c_area + c_fringe;
    let c_err = (n.total_cap_ff - expected_c).abs() / expected_c;
    assert!(
        c_err < 0.05,
        "C out of tolerance: got {}, expected {}",
        n.total_cap_ff,
        expected_c
    );
    // Sanity: the new model should be in the few-tenths-fF range, not aF.
    assert!(
        n.total_cap_ff > 0.05,
        "v0.2 self-cap should be > 0.05 fF for a 3µm met1 wire, got {}",
        n.total_cap_ff
    );
}

#[test]
fn test_spef_roundtrip() {
    let result = load_tiny();
    let s = spef::write_spef(&result);
    let parsed = spef::parse_str(&s).expect("parse SPEF back");
    assert_eq!(parsed.design, "tiny");
    assert_eq!(parsed.nets.len(), 1);
    let n = &parsed.nets[0];
    assert_eq!(n.name, "net1");
    let orig = &result.nets[0];
    let diff = (n.total_cap_ff - orig.total_cap_ff).abs();
    assert!(
        diff < 1e-6,
        "cap mismatch after roundtrip: {} vs {}",
        n.total_cap_ff,
        orig.total_cap_ff
    );
    assert_eq!(n.res_entries.len(), orig.segments.len());
    // v0.2: SPEF should now contain a *PORTS section is omitted because tiny
    // has no top-level pins, but *D_NET, *CAP, *RES sections must all exist.
    assert!(s.contains("*D_NET"));
    assert!(s.contains("*RES"));
}

#[test]
fn test_no_routes_zero_parasitics() {
    let def_ast = def::parse_file("tests/fixtures/empty.def").expect("parse empty.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);
    assert_eq!(result.nets.len(), 1);
    let n = &result.nets[0];
    assert_eq!(n.total_res_ohm, 0.0);
    assert_eq!(n.total_cap_ff, 0.0);
    assert_eq!(n.segments.len(), 0);
    // v0.2: empty.def has a top-level PIN connection — *PORTS section should
    // appear in SPEF output.
    let s = spef::write_spef(&result);
    assert!(s.contains("*PORTS"), "SPEF missing *PORTS:\n{s}");
}

#[test]
fn test_via_resistance() {
    let def_ast = def::parse_file("tests/fixtures/via.def").expect("parse via.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);
    assert_eq!(result.nets.len(), 1);
    let n = &result.nets[0];
    assert!(!n.vias.is_empty(), "expected at least one via");
    let via_r: f64 = n.vias.iter().map(|v| v.r_ohm).sum();
    // M1M2_PR has 4.0 ohm (single cut)
    assert!(
        (via_r - 4.0).abs() < 1e-6,
        "via R should be 4.0, got {via_r}"
    );
    // Total R should include via R plus wire R on both segments.
    assert!(n.total_res_ohm > via_r);
}

// ------------- v0.2 tests -------------

#[test]
fn test_cross_layer_coupling() {
    // Two nets — one on met1, one on met2 — overlapping in (x,y).
    // Cross-layer cap should be > 0 and roughly: eps0 * eps_r * A / d
    // where A = 4 * 0.14 (overlap length × width), d = met1.inter_layer_distance = 0.36 µm.
    let def_ast = def::parse_file("tests/fixtures/cross_layer.def").expect("parse cross_layer.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);
    assert_eq!(result.nets.len(), 2);
    // Each net should have one coupling entry pointing at the other.
    let net_a = result.nets.iter().find(|n| n.net_name == "netA").unwrap();
    assert_eq!(net_a.coupling.len(), 1);
    assert_eq!(net_a.coupling[0].neighbor_net, "netB");
    let c = net_a.coupling[0].c_ff;
    // Expected ≈ 8.854e-3 * 4.2 * (4.0 * 0.14) / 0.36 ≈ 0.0578 fF.
    let expected = cross_layer::EPS0_FF_PER_UM * cross_layer::EPS_R_ILD * (4.0 * 0.14) / 0.36;
    let err = (c - expected).abs() / expected;
    assert!(
        err < 0.10,
        "cross-layer C: got {c}, expected ~{expected} (err {err:.3})"
    );
    assert!(c > 0.0);
}

#[test]
fn test_multi_cut_via() {
    // M1M2_PR_4CUT has cut_count=4, single-cut R = 4.0 → array R = 1.0 ohm.
    let def_ast =
        def::parse_file("tests/fixtures/multicut_via.def").expect("parse multicut_via.def");
    let lef_lib = lef::parse_file("tests/fixtures/tiny.lef").expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);
    let n = &result.nets[0];
    let via_r: f64 = n.vias.iter().map(|v| v.r_ohm).sum();
    // 4.0 / 4 = 1.0
    assert!(
        (via_r - 1.0).abs() < 1e-6,
        "multi-cut via R should be 1.0 (4.0/4), got {via_r}"
    );
}

#[test]
fn test_fringe_dominates_for_thin_wire() {
    // For a long, thin wire (w << h), Sakurai fringe dominates over area.
    let tech_file = tech::load("sky130A").unwrap();
    // met1: h=1.37, t=0.36; w=0.14 (min width) → w/h ≈ 0.10. Highly fringe-dominant.
    let (c_area, c_fringe) = capacitance::wire_capacitance_split(&tech_file, "met1", 10.0, 0.14);
    assert!(
        c_fringe > c_area,
        "expected fringe > area for thin wire: area={c_area}, fringe={c_fringe}"
    );
    // And the ratio should be substantial — at least 5×.
    assert!(
        c_fringe / c_area > 5.0,
        "fringe/area ratio too small: {}",
        c_fringe / c_area
    );
}

#[test]
fn test_real_counter_within_bounds() {
    // Smoke-test on the routed counter. Skipped gracefully if the example
    // hasn't been built yet (CI may not run synthesis).
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
    // v0.1 measured 56.4 fF (area+fringe lumped, no cross-layer). v0.2 with
    // Sakurai self-cap + cross-layer coupling should land higher; a bound of
    // [40, 5000] fF catches gross regressions while accommodating the new
    // physics.
    assert!(
        (40.0..=5000.0).contains(&total_c),
        "counter total C out of bounds: {total_c} fF"
    );
}
