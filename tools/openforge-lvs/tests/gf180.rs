//! Multi-PDK regression: LVS extraction with the gf180mcuC physical-only
//! filter. Builds a tiny DEF + LEF using gf180mcu standard cell names,
//! compares against a matching gate-level Verilog netlist, and checks
//! that the gf180 default filter drops physical-only fill / tap cells.

use openforge_lvs::layout_extract::{
    default_physical_only_for, extract_subckt_with_filter, parse_def_str, parse_lef_str,
    PhysicalFilter, DEFAULT_GF180MCU_PHYSICAL_ONLY, DEFAULT_SKY130_PHYSICAL_ONLY,
};
use openforge_lvs::run_lvs_def_verilog_filtered;

const GF180_LEF: &str = "VERSION 5.7 ;
NAMESCASESENSITIVE ON ;
BUSBITCHARS \"[]\" ;
DIVIDERCHAR \"/\" ;

LAYER Metal1
  TYPE ROUTING ;
END Metal1

MACRO gf180mcu_fd_sc_mcu7t5v0__inv_1
  PIN A
    DIRECTION INPUT ;
  END A
  PIN Y
    DIRECTION OUTPUT ;
  END Y
END gf180mcu_fd_sc_mcu7t5v0__inv_1

MACRO gf180mcu_fd_sc_mcu7t5v0__filltie
END gf180mcu_fd_sc_mcu7t5v0__filltie

MACRO gf180mcu_fd_sc_mcu7t5v0__filler_1
END gf180mcu_fd_sc_mcu7t5v0__filler_1

MACRO gf180mcu_fd_sc_mcu7t5v0__antenna
END gf180mcu_fd_sc_mcu7t5v0__antenna

END LIBRARY
";

const GF180_DEF: &str = "VERSION 5.8 ;
DESIGN gf180_tiny ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
COMPONENTS 5 ;
- a gf180mcu_fd_sc_mcu7t5v0__inv_1   + PLACED ( 1000 1000 ) N ;
- b gf180mcu_fd_sc_mcu7t5v0__inv_1   + PLACED ( 5000 1000 ) N ;
- t1 gf180mcu_fd_sc_mcu7t5v0__filltie + PLACED ( 2000 2000 ) N ;
- f1 gf180mcu_fd_sc_mcu7t5v0__filler_1 + PLACED ( 3000 2000 ) N ;
- d1 gf180mcu_fd_sc_mcu7t5v0__antenna + PLACED ( 4000 2000 ) N ;
END COMPONENTS
NETS 1 ;
- net1 ( a Y ) ( b A )
  + ROUTED Metal1 ( 1500 1500 ) ( 4500 1500 0 ) ;
END NETS
END DESIGN
";

const GF180_V: &str = "module gf180_tiny;
  wire net1;
  gf180mcu_fd_sc_mcu7t5v0__inv_1 a ( .A(in1), .Y(net1) );
  gf180mcu_fd_sc_mcu7t5v0__inv_1 b ( .A(net1), .Y(out1) );
endmodule
";

#[test]
fn gf180_default_filter_constants_present() {
    assert_ne!(
        DEFAULT_GF180MCU_PHYSICAL_ONLY, DEFAULT_SKY130_PHYSICAL_ONLY,
        "gf180 and sky130 default regexes must differ"
    );
    assert_eq!(
        default_physical_only_for("gf180mcuC"),
        Some(DEFAULT_GF180MCU_PHYSICAL_ONLY)
    );
    assert_eq!(
        default_physical_only_for("sky130A"),
        Some(DEFAULT_SKY130_PHYSICAL_ONLY)
    );
    assert_eq!(default_physical_only_for("nonsense"), None);
}

#[test]
fn gf180_filter_drops_physical_only_cells() {
    let f = PhysicalFilter::for_pdk("gf180mcuC").expect("build gf180 filter");
    // Physical-only cells in the gf180 mcu7t5v0 library:
    for c in [
        "gf180mcu_fd_sc_mcu7t5v0__filltie",
        "gf180mcu_fd_sc_mcu7t5v0__filldecap_4",
        "gf180mcu_fd_sc_mcu7t5v0__filler_1",
        "gf180mcu_fd_sc_mcu7t5v0__filler_8",
        "gf180mcu_fd_sc_mcu7t5v0__endcap",
        "gf180mcu_fd_sc_mcu7t5v0__antenna",
        "gf180mcu_fd_sc_mcu7t5v0__diode",
    ] {
        assert!(f.matches(c), "expected gf180 filter to match {c}");
    }
    // Real signal cells must NOT be filtered.
    for c in [
        "gf180mcu_fd_sc_mcu7t5v0__inv_1",
        "gf180mcu_fd_sc_mcu7t5v0__nand2_1",
        "gf180mcu_fd_sc_mcu7t5v0__dffq_1",
        // sky130 cells live in a different namespace, not filtered by the
        // gf180 regex.
        "sky130_fd_sc_hd__tap_1",
    ] {
        assert!(!f.matches(c), "gf180 filter should NOT match {c}");
    }
}

#[test]
fn gf180_extract_drops_fill_cells_only_signal_inv_remain() {
    let def = parse_def_str(GF180_DEF).expect("parse DEF");
    let lef = parse_lef_str(GF180_LEF).expect("parse LEF");
    let f = PhysicalFilter::for_pdk("gf180mcuC").unwrap();
    let (sub, dropped) = extract_subckt_with_filter(&def, &lef, "gf180_tiny", &f).expect("extract");

    // 5 components in DEF, 3 are physical-only -> 2 signal devices left.
    assert_eq!(
        sub.devices.len(),
        2,
        "expected 2 signal devices after filtering, got {}",
        sub.devices.len()
    );
    let total_dropped: usize = dropped.by_macro.values().sum();
    assert_eq!(
        total_dropped, 3,
        "expected 3 dropped fill/tap/antenna cells"
    );
}

#[test]
fn gf180_lvs_match_using_pdk_default_filter() {
    let f = PhysicalFilter::for_pdk("gf180mcuC").unwrap();
    let rpt = run_lvs_def_verilog_filtered(GF180_DEF, GF180_LEF, GF180_V, "gf180_tiny", &f)
        .expect("run lvs");
    assert!(
        rpt.matched,
        "expected MATCH after filtering gf180 fill cells; reason: {:?}",
        rpt.reason
    );
}
