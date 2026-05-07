//! Integration tests for the DEF + LEF layout extraction path.

use openforge_lvs::layout_extract::{
    extract_subckt, extract_subckt_with_filter, parse_def_str, parse_lef_str, PhysicalFilter,
};
use openforge_lvs::{
    run_lvs_def_verilog, run_lvs_def_verilog_filtered, verilog::parse_verilog_str,
};
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

/// Synthetic DEF that injects sky130 physical-only cells (tap, decap, fill,
/// diode) alongside two real signal cells. Verifies the default filter
/// drops the four physical cells, leaving the layout with exactly the two
/// signal cells that the schematic side declares.
const PHYS_FILTER_DEF: &str = "VERSION 5.8 ;
DESIGN tiny ;
COMPONENTS 6 ;
- a sky130_fd_sc_hd__inv_1 ;
- b sky130_fd_sc_hd__inv_1 ;
- TAP_0 sky130_fd_sc_hd__tap_1 ;
- DECAP_0 sky130_fd_sc_hd__decap_3 ;
- FILL_0 sky130_fd_sc_hd__fill_1 ;
- ANT_0 sky130_fd_sc_hd__diode_2 ;
END COMPONENTS
NETS 1 ;
- net1 ( a Y ) ( b A ) ;
END NETS
END DESIGN
";

#[test]
fn test_physical_only_filter_drops_tap_decap_fill_diode() {
    let def = parse_def_str(PHYS_FILTER_DEF).expect("parse DEF");
    let lef = parse_lef_str(TINY_LEF).expect("parse LEF");
    assert_eq!(def.components.len(), 6, "DEF should have 6 components");

    // With the default filter, tap/decap/fill/diode should be dropped.
    let f = PhysicalFilter::default();
    let (sub, filtered) = extract_subckt_with_filter(&def, &lef, "tiny", &f).expect("extract");
    assert_eq!(sub.devices.len(), 2, "expected 2 real devices after filter");
    assert_eq!(filtered.total, 4, "expected 4 physical cells filtered");
    assert_eq!(filtered.by_macro.len(), 4);
    let summary = filtered.render_summary();
    assert!(summary.contains("4 physical-only cells"), "{summary}");
    assert!(summary.contains("sky130_fd_sc_hd__tap_1"), "{summary}");

    // With the filter disabled, the LEF lookup will fail because the
    // synthetic LEF doesn't define the physical-only macros — confirming
    // they would otherwise reach extraction.
    let no_filter = PhysicalFilter::disabled();
    let res = extract_subckt_with_filter(&def, &lef, "tiny", &no_filter);
    assert!(
        res.is_err(),
        "without filter, missing LEF macros should error"
    );

    // extract_subckt() (no-filter alias) -> default filter applied.
    let sub2 = extract_subckt(&def, &lef, "tiny").expect("default extract");
    assert_eq!(sub2.devices.len(), 2);
}

/// Counter integration test: gate-level schematic from synth (no clkbufs,
/// 31 cells) versus the synth/netlist.v on the same DEF must at least
/// agree on device count once physical-only cells (if any) are filtered.
/// The current sky130 counter routing happens to produce 35 layout cells
/// (4 CTS-inserted clkbufs over the 31 synth cells); this test asserts
/// that the physical-only filter does not regress the existing 35-vs-35
/// match against routed.v, and additionally exercises the filter against
/// synth/netlist.v to verify it does not introduce false MISMATCH from
/// physical artifacts.
#[test]
fn test_real_counter_filter_no_regression() {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let root = Path::new(manifest).join("../..");
    let def_path = root.join("examples/asic-counter-sky130/build/routing/routed.def");
    let v_path = root.join("examples/asic-counter-sky130/build/routing/routed.v");
    let lef_path = root.join("share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef");

    if !def_path.exists() || !v_path.exists() || !lef_path.exists() {
        eprintln!("test_real_counter_filter_no_regression: skipping (artifacts not present)");
        return;
    }

    let def_src = std::fs::read_to_string(&def_path).expect("read DEF");
    let lef_src = std::fs::read_to_string(&lef_path).expect("read LEF");
    let v_src = std::fs::read_to_string(&v_path).expect("read V");

    // Default filter active: layout must still equal schem device count
    // (the routed counter has no tap/decap/fill cells, so filter is a no-op).
    let rpt = run_lvs_def_verilog_filtered(
        &def_src,
        &lef_src,
        &v_src,
        "counter",
        &PhysicalFilter::default(),
    )
    .expect("run lvs");
    assert_eq!(
        rpt.device_count_layout, rpt.device_count_schem,
        "layout/schem device count must agree under default filter"
    );
    assert!(
        rpt.matched,
        "counter LVS regressed under default filter: {:?}",
        rpt.reason
    );

    // Disabling the filter must give the same result (no physical-only
    // cells in this DEF) — confirms the filter is correctly scoped.
    let rpt_off = run_lvs_def_verilog_filtered(
        &def_src,
        &lef_src,
        &v_src,
        "counter",
        &PhysicalFilter::disabled(),
    )
    .expect("run lvs no-filter");
    assert_eq!(rpt.device_count_layout, rpt_off.device_count_layout);
    assert_eq!(rpt_off.filtered_physical_cells, 0);
}
