//! End-to-end LVS tests.

use openforge_lvs::{run_lvs, spice::parse_netlist};

const INV_SCH: &str = include_str!("fixtures/inv_sch.spice");
const INV_LAY: &str = include_str!("fixtures/inv_lay.spice");
const INV_BAD: &str = include_str!("fixtures/inv_bad.spice");
const RDIV_SCH: &str = include_str!("fixtures/rdiv_sch.spice");
const RDIV_LAY: &str = include_str!("fixtures/rdiv_lay.spice");

#[test]
fn test_inverter_matches() {
    let rpt = run_lvs(INV_LAY, INV_SCH, "inverter").unwrap();
    assert!(rpt.matched, "expected MATCH, got: {:?}", rpt.reason);
    assert_eq!(rpt.device_count_layout, 2);
    assert_eq!(rpt.device_count_schem, 2);
    assert_eq!(rpt.matched_pairs.len(), 2);
}

#[test]
fn test_inverter_mismatches() {
    let rpt = run_lvs(INV_BAD, INV_SCH, "inverter").unwrap();
    assert!(!rpt.matched);
    let reason = rpt.reason.unwrap_or_default();
    assert!(
        reason.contains("histogram") || reason.contains("nmos") || reason.contains("pmos"),
        "expected device-type divergence in reason; got: {reason}"
    );
}

#[test]
fn test_round_trip_json() {
    let nl = parse_netlist(INV_SCH).unwrap();
    let json = serde_json::to_string(&nl).unwrap();
    let nl2: openforge_lvs::spice::Netlist = serde_json::from_str(&json).unwrap();
    let inv = nl.library.get("inverter").unwrap();
    let inv2 = nl2.library.get("inverter").unwrap();
    assert_eq!(inv, inv2);
}

#[test]
fn test_resistor_only() {
    let rpt = run_lvs(RDIV_LAY, RDIV_SCH, "rdiv").unwrap();
    assert!(rpt.matched, "expected MATCH, reason={:?}", rpt.reason);
    assert_eq!(rpt.device_count_layout, 3);
}

#[test]
fn test_unknown_top() {
    let err = run_lvs(INV_SCH, INV_SCH, "nonexistent").err().unwrap();
    let msg = format!("{err}");
    assert!(msg.contains("nonexistent"));
}
