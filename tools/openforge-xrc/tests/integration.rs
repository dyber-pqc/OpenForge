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
    // C = 0.000064 * 3 * 0.14 + 0.000031 * 6 ≈ 2.688e-5 + 1.86e-4 ≈ 2.13e-4 fF
    let expected_c = 0.000064 * 3.0 * 0.14 + 0.000031 * 6.0;
    let c_err = (n.total_cap_ff - expected_c).abs() / expected_c;
    assert!(
        c_err < 0.05,
        "C out of tolerance: got {}, expected {}",
        n.total_cap_ff,
        expected_c
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
    // M1M2_PR has 4.0 ohm
    assert!(
        (via_r - 4.0).abs() < 1e-6,
        "via R should be 4.0, got {via_r}"
    );
    // Total R should include via R plus wire R on both segments.
    assert!(n.total_res_ohm > via_r);
}
