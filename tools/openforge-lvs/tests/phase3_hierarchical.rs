//! Phase 3 — hierarchical match tests.

use openforge_lvs::run_lvs_hierarchical;

const HIER_SCH: &str = r#"
.subckt inv in out vdd vss
M1 out in vss vss nmos w=0.42u l=0.15u
M2 out in vdd vdd pmos w=0.84u l=0.15u
.ends inv

.subckt buf in out vdd vss
X1 in mid vdd vss inv
X2 mid out vdd vss inv
.ends buf
"#;

const HIER_LAY: &str = r#"
.subckt inv in out vdd vss
M1 out in vss vss nmos w=0.42u l=0.15u
M2 out in vdd vdd pmos w=0.84u l=0.15u
.ends inv

.subckt buf in out vdd vss
X1 in mid vdd vss inv
X2 mid out vdd vss inv
.ends buf
"#;

const HIER_LAY_BAD: &str = r#"
.subckt inv in out vdd vss
M1 out in vss vss nmos w=0.42u l=0.15u
.ends inv

.subckt buf in out vdd vss
X1 in mid vdd vss inv
X2 mid out vdd vss inv
.ends buf
"#;

#[test]
fn hierarchical_match_two_inverters_in_buf() {
    let (rpt, hr) = run_lvs_hierarchical(HIER_LAY, HIER_SCH, "buf").unwrap();
    assert!(
        rpt.matched,
        "expected hierarchical MATCH, got: {:?}",
        rpt.reason
    );
    assert!(
        hr.matched_subckts.contains(&"inv".to_string()),
        "expected 'inv' to be matched independently; got {:?}",
        hr.matched_subckts
    );
    assert!(hr.matched(), "HierResult should report success");
}

#[test]
fn hierarchical_mismatch_inside_subckt_is_reported() {
    let (rpt, hr) = run_lvs_hierarchical(HIER_LAY_BAD, HIER_SCH, "buf").unwrap();
    assert!(!rpt.matched);
    let reason = rpt.reason.unwrap_or_default();
    assert!(
        reason.contains("inv"),
        "expected reason to mention failing subckt 'inv'; got: {reason}"
    );
    assert!(hr.failed_subckt.is_some());
}

#[test]
fn hierarchical_match_when_no_shared_subckts_falls_back_to_top() {
    // Both sides only define 'top'; no shared sub-block. The hierarchical
    // call should still succeed by matching 'top' as a flat subckt.
    let sch = r#"
.subckt top a b
R1 a b 1k
.ends top
"#;
    let lay = r#"
.subckt top a b
R1 a b 1k
.ends top
"#;
    let (rpt, hr) = run_lvs_hierarchical(lay, sch, "top").unwrap();
    assert!(rpt.matched);
    assert!(hr.matched_subckts.is_empty());
}
