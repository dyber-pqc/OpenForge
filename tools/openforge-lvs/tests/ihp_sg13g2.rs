//! Multi-PDK regression: LVS extraction with the IHP sg13g2 (130 nm SiGe
//! BiCMOS) physical-only filter. Builds a tiny DEF + LEF using sg13g2
//! standard cell names, compares against a matching gate-level Verilog
//! netlist, and checks that the IHP default filter drops physical-only
//! fill / tap / decap cells.

use openforge_lvs::layout_extract::{
    default_physical_only_for, extract_subckt_with_filter, parse_def_str, parse_lef_str,
    PhysicalFilter, DEFAULT_GF180MCU_PHYSICAL_ONLY, DEFAULT_IHP_SG13G2_PHYSICAL_ONLY,
    DEFAULT_SKY130_PHYSICAL_ONLY,
};
use openforge_lvs::run_lvs_def_verilog_filtered;

const IHP_LEF: &str = "VERSION 5.7 ;
NAMESCASESENSITIVE ON ;
BUSBITCHARS \"[]\" ;
DIVIDERCHAR \"/\" ;

LAYER Metal1
  TYPE ROUTING ;
END Metal1

MACRO sg13g2_inv_1
  PIN A
    DIRECTION INPUT ;
  END A
  PIN Y
    DIRECTION OUTPUT ;
  END Y
END sg13g2_inv_1

MACRO sg13g2_decap_4
END sg13g2_decap_4

MACRO sg13g2_fill_1
END sg13g2_fill_1

MACRO sg13g2_tap_1
END sg13g2_tap_1

MACRO sg13g2_tielo_1
END sg13g2_tielo_1

END LIBRARY
";

const IHP_DEF: &str = "VERSION 5.8 ;
DESIGN ihp_tiny ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
COMPONENTS 6 ;
- a sg13g2_inv_1 + PLACED ( 1000 1000 ) N ;
- b sg13g2_inv_1 + PLACED ( 5000 1000 ) N ;
- d1 sg13g2_decap_4 + PLACED ( 2000 2000 ) N ;
- f1 sg13g2_fill_1 + PLACED ( 3000 2000 ) N ;
- t1 sg13g2_tap_1 + PLACED ( 4000 2000 ) N ;
- l1 sg13g2_tielo_1 + PLACED ( 4500 2000 ) N ;
END COMPONENTS
NETS 1 ;
- net1 ( a Y ) ( b A )
  + ROUTED Metal1 ( 1500 1500 ) ( 4500 1500 0 ) ;
END NETS
END DESIGN
";

const IHP_V: &str = "module ihp_tiny;
  wire net1;
  sg13g2_inv_1 a ( .A(in1), .Y(net1) );
  sg13g2_inv_1 b ( .A(net1), .Y(out1) );
endmodule
";

#[test]
fn ihp_sg13g2_default_filter_constants_present() {
    assert_ne!(
        DEFAULT_IHP_SG13G2_PHYSICAL_ONLY, DEFAULT_SKY130_PHYSICAL_ONLY,
        "ihp and sky130 default regexes must differ"
    );
    assert_ne!(
        DEFAULT_IHP_SG13G2_PHYSICAL_ONLY, DEFAULT_GF180MCU_PHYSICAL_ONLY,
        "ihp and gf180 default regexes must differ"
    );
    assert_eq!(
        default_physical_only_for("ihp_sg13g2"),
        Some(DEFAULT_IHP_SG13G2_PHYSICAL_ONLY)
    );
    assert_eq!(
        default_physical_only_for("IHPSG13G2"),
        Some(DEFAULT_IHP_SG13G2_PHYSICAL_ONLY)
    );
    assert_eq!(default_physical_only_for("nonsense"), None);
}

#[test]
fn ihp_sg13g2_filter_drops_physical_only_cells() {
    let f = PhysicalFilter::for_pdk("ihp_sg13g2").expect("build ihp filter");
    for c in [
        "sg13g2_decap_4",
        "sg13g2_fill_1",
        "sg13g2_fill_2",
        "sg13g2_tap_1",
        "sg13g2_tielo_1",
        "sg13g2_tiehi_1",
        "sg13g2_cdummy",
        "sg13g2_antenna",
    ] {
        assert!(f.matches(c), "expected ihp filter to match {c}");
    }
    // Real signal cells must NOT be filtered.
    for c in [
        "sg13g2_inv_1",
        "sg13g2_nand2_1",
        "sg13g2_dfrbp_1",
        // Other PDK namespaces stay untouched.
        "sky130_fd_sc_hd__tap_1",
        "gf180mcu_fd_sc_mcu7t5v0__filltie",
    ] {
        assert!(!f.matches(c), "ihp filter should NOT match {c}");
    }
}

#[test]
fn ihp_sg13g2_extract_drops_physical_cells_only_signal_inv_remain() {
    let def = parse_def_str(IHP_DEF).expect("parse DEF");
    let lef = parse_lef_str(IHP_LEF).expect("parse LEF");
    let f = PhysicalFilter::for_pdk("ihp_sg13g2").unwrap();
    let (sub, dropped) = extract_subckt_with_filter(&def, &lef, "ihp_tiny", &f).expect("extract");

    // 6 components in DEF, 4 are physical-only (decap, fill, tap, tielo) -> 2 signal devices.
    assert_eq!(
        sub.devices.len(),
        2,
        "expected 2 signal devices after filtering, got {}",
        sub.devices.len()
    );
    let total_dropped: usize = dropped.by_macro.values().sum();
    assert_eq!(
        total_dropped, 4,
        "expected 4 dropped fill/tap/decap/tielo cells"
    );
}

#[test]
fn ihp_sg13g2_lvs_match_using_pdk_default_filter() {
    let f = PhysicalFilter::for_pdk("ihp_sg13g2").unwrap();
    let rpt =
        run_lvs_def_verilog_filtered(IHP_DEF, IHP_LEF, IHP_V, "ihp_tiny", &f).expect("run lvs");
    assert!(
        rpt.matched,
        "expected MATCH after filtering ihp fill cells; reason: {:?}",
        rpt.reason
    );
}
