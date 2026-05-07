//! Integration tests for the DEF + LEF layout extraction path.

use openforge_lvs::layout_extract::{extract_subckt, parse_def_str, parse_lef_str};
use openforge_lvs::{run_lvs_def_verilog, verilog::parse_verilog_str};
use std::path::Path;

const TINY_DEF: &str = include_str!("../../openforge-xrc/tests/fixtures/tiny.def");
const TINY_LEF: &str = include_str!("../../openforge-xrc/tests/fixtures/tiny.lef");

// Note: tiny.def has no PINS section, so the extracted Subckt has no ports.
// The Verilog must mirror that — no port list.
const TINY_V: &str = "module tiny;
  wire net1;
  sky130_fd_sc_hd__inv_1 a ( .A(in1), .Y(net1) );
  sky130_fd_sc_hd__inv_1 b ( .A(net1), .Y(out1) );
endmodule
";

#[test]
fn test_extract_def_simple() {
    let def = parse_def_str(TINY_DEF).expect("parse DEF");
    let lef = parse_lef_str(TINY_LEF).expect("parse LEF");

    assert_eq!(def.design, "tiny");
    assert_eq!(def.components.len(), 2);
    assert_eq!(def.nets.len(), 1);
    assert_eq!(def.nets[0].name, "net1");
    assert_eq!(def.nets[0].connections.len(), 2);

    let sub = extract_subckt(&def, &lef, "tiny").expect("extract");
    assert_eq!(sub.devices.len(), 2);
    // Two devices, one shared net 'net1'.
    let nets: std::collections::HashSet<String> = sub
        .devices
        .iter()
        .flat_map(|d| d.pins().into_iter().map(|(_, n)| n))
        .collect();
    assert!(nets.contains("net1"), "expected 'net1' in extracted nets");
}

#[test]
fn test_extract_def_to_lvs_match() {
    // The tiny DEF defines two inverters chained on net1; pin A of cell 'a'
    // and pin Y of cell 'b' are dangling. The Verilog netlist below mirrors
    // that exactly.
    let rpt = run_lvs_def_verilog(TINY_DEF, TINY_LEF, TINY_V, "tiny").expect("run lvs");
    assert!(rpt.matched, "expected MATCH, got: {:?}", rpt.reason);
    assert_eq!(rpt.device_count_layout, 2);
    assert_eq!(rpt.device_count_schem, 2);
}

#[test]
fn test_verilog_parser_basic() {
    let v = parse_verilog_str(TINY_V).expect("verilog parse");
    assert_eq!(v.name, "tiny");
    assert_eq!(v.instances.len(), 2);
    assert_eq!(v.instances[0].cell, "sky130_fd_sc_hd__inv_1");
    assert_eq!(v.instances[0].name, "a");
    assert_eq!(
        v.instances[0].connections.get("A").map(|s| s.as_str()),
        Some("in1")
    );
    assert_eq!(
        v.instances[0].connections.get("Y").map(|s| s.as_str()),
        Some("net1")
    );
}

#[test]
fn test_verilog_bus_expansion() {
    let src = "module top(a, b); input a; output [3:0] b; endmodule";
    let v = parse_verilog_str(src).expect("parse");
    // Bus port 'b' should expand to b[0]..b[3].
    assert!(v.ports.contains(&"a".to_string()));
    for i in 0..=3 {
        assert!(
            v.ports.contains(&format!("b[{i}]")),
            "expected b[{i}] in ports {:?}",
            v.ports
        );
    }
}

/// Killer demo: real routed counter design from `examples/asic-counter-sky130`.
/// Skipped gracefully if the bundled artifacts are missing.
#[test]
fn test_real_counter() {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let root = Path::new(manifest).join("../..");
    let def_path = root.join("examples/asic-counter-sky130/build/routing/routed.def");
    let v_path = root.join("examples/asic-counter-sky130/build/routing/routed.v");
    let lef_path = root.join("share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef");

    if !def_path.exists() || !v_path.exists() || !lef_path.exists() {
        eprintln!("test_real_counter: skipping (artifacts not present)");
        return;
    }

    let def_src = std::fs::read_to_string(&def_path).expect("read DEF");
    let lef_src = std::fs::read_to_string(&lef_path).expect("read LEF");
    let v_src = std::fs::read_to_string(&v_path).expect("read V");

    let rpt = run_lvs_def_verilog(&def_src, &lef_src, &v_src, "counter").expect("run lvs");
    assert!(
        rpt.matched,
        "real counter LVS expected MATCH; got reason: {:?}\n  layout={} sch={}",
        rpt.reason, rpt.device_count_layout, rpt.device_count_schem
    );
    assert_eq!(rpt.device_count_layout, rpt.device_count_schem);
}
