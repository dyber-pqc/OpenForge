//! Phase 3 — series/parallel folding tests.

use openforge_lvs::run_lvs;

#[test]
fn three_parallel_resistors_fold_to_one() {
    // Three 3 kΩ resistors in parallel == 1 kΩ.
    let layout = r#"
.subckt rpar a b
R1 a b 3k
R2 a b 3k
R3 a b 3k
.ends rpar
"#;
    // Schematic with one equivalent resistor.
    let schem = r#"
.subckt rpar a b
R1 a b 1k
.ends rpar
"#;
    let rpt = run_lvs(layout, schem, "rpar").unwrap();
    assert!(rpt.matched, "expected MATCH, got: {:?}", rpt.reason);
    // Pre-normalization device counts are reported.
    assert_eq!(rpt.device_count_layout, 3);
    assert_eq!(rpt.device_count_schem, 1);
}

#[test]
fn three_series_resistors_fold_to_one() {
    let layout = r#"
.subckt rser a b
R1 a m1 1k
R2 m1 m2 1k
R3 m2 b 1k
.ends rser
"#;
    let schem = r#"
.subckt rser a b
R1 a b 3k
.ends rser
"#;
    let rpt = run_lvs(layout, schem, "rser").unwrap();
    assert!(rpt.matched, "expected MATCH, got: {:?}", rpt.reason);
    assert_eq!(rpt.device_count_layout, 3);
}

#[test]
fn four_parallel_nmos_fingers_fold_with_summed_width() {
    // Four 0.21u NMOS fingers should match one 0.84u NMOS.
    let layout = r#"
.subckt nfet d g s b
M1 d g s b nmos w=0.21u l=0.15u
M2 d g s b nmos w=0.21u l=0.15u
M3 d g s b nmos w=0.21u l=0.15u
M4 d g s b nmos w=0.21u l=0.15u
.ends nfet
"#;
    let schem = r#"
.subckt nfet d g s b
M1 d g s b nmos w=0.84u l=0.15u
.ends nfet
"#;
    let rpt = run_lvs(layout, schem, "nfet").unwrap();
    assert!(rpt.matched, "expected MATCH, got: {:?}", rpt.reason);
    assert_eq!(rpt.device_count_layout, 4);
    assert_eq!(rpt.device_count_schem, 1);
}

#[test]
fn mismatched_parallel_count_still_does_not_match() {
    // 3 parallel R's in layout fold to 1, but schematic explicitly has 2
    // separate (non-parallel) resistors going through different nets.
    let layout = r#"
.subckt rmix a b
R1 a b 1k
R2 a b 1k
R3 a b 1k
.ends rmix
"#;
    // Different topology: 2 resistors in series — folds to 1 too, but with
    // value 2k not 333.33Ω, AND parameter strings differ.
    let schem = r#"
.subckt rmix a b
R1 a m 1k
R2 m b 1k
.ends rmix
"#;
    let rpt = run_lvs(layout, schem, "rmix").unwrap();
    assert!(
        !rpt.matched,
        "expected MISMATCH: parallel 1k||1k||1k != series 1k+1k"
    );
}

#[test]
fn parallel_caps_sum() {
    let layout = r#"
.subckt cpar a b
C1 a b 1p
C2 a b 2p
.ends cpar
"#;
    let schem = r#"
.subckt cpar a b
C1 a b 3p
.ends cpar
"#;
    let rpt = run_lvs(layout, schem, "cpar").unwrap();
    assert!(rpt.matched, "expected MATCH, got: {:?}", rpt.reason);
}

#[test]
fn different_mosfet_models_do_not_fold_together() {
    // Two parallel devices with different models must NOT fold.
    let layout = r#"
.subckt mix d g s b
M1 d g s b nmos w=0.5u l=0.15u
M2 d g s b pmos w=0.5u l=0.15u
.ends mix
"#;
    let schem = r#"
.subckt mix d g s b
M1 d g s b nmos w=1.0u l=0.15u
.ends mix
"#;
    let rpt = run_lvs(layout, schem, "mix").unwrap();
    assert!(!rpt.matched, "should not fold across different models");
}
