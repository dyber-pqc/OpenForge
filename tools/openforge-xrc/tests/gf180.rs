//! Multi-PDK regression: extract parasitics on a routed segment using the
//! built-in gf180mcuC tech file. Asserts that the tech loads, the layer
//! stack is consistent, and a DEF route on `Metal1` produces non-zero R/C
//! across all three corners.

use openforge_xrc::extract::capacitance;
use openforge_xrc::tech::{self, Corner};
use openforge_xrc::{def, extract, lef};

const GF180_LEF: &str = "VERSION 5.7 ;
NAMESCASESENSITIVE ON ;
BUSBITCHARS \"[]\" ;
DIVIDERCHAR \"/\" ;

LAYER Metal1
  TYPE ROUTING ;
END Metal1

LAYER Metal2
  TYPE ROUTING ;
END Metal2

MACRO gf180mcu_fd_sc_mcu7t5v0__inv_1
  PIN A
    DIRECTION INPUT ;
  END A
  PIN Y
    DIRECTION OUTPUT ;
  END Y
END gf180mcu_fd_sc_mcu7t5v0__inv_1

END LIBRARY
";

const GF180_DEF: &str = "VERSION 5.8 ;
DESIGN gf180_tiny ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
COMPONENTS 2 ;
- a gf180mcu_fd_sc_mcu7t5v0__inv_1 + PLACED ( 1000 1000 ) N ;
- b gf180mcu_fd_sc_mcu7t5v0__inv_1 + PLACED ( 5000 1000 ) N ;
END COMPONENTS
NETS 1 ;
- net1 ( a Y ) ( b A )
  + ROUTED Metal1 ( 1500 1500 ) ( 4500 1500 0 ) ;
END NETS
END DESIGN
";

#[test]
fn gf180_tech_loads_and_has_expected_layers() {
    let t = tech::load("gf180mcuC").expect("load gf180mcuC");
    assert_eq!(t.name, "gf180mcuC");
    for name in ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5"] {
        assert!(t.layer(name).is_some(), "missing layer {name}");
    }
    // Top metal has no layer above; intermediate layers do.
    assert!(t.layer("Metal5").unwrap().above_layer.is_none());
    assert_eq!(
        t.layer("Metal1").unwrap().above_layer.as_deref(),
        Some("Metal2")
    );
    // Reasonable physical numbers.
    assert!(t.layer("Metal1").unwrap().sheet_resistance_ohm > 0.0);
    assert!(t.layer("Metal5").unwrap().thickness_um > t.layer("Metal1").unwrap().thickness_um);
    assert!(!t.vias.is_empty());
    assert!(t.via_between("Metal1", "Metal2").is_some());
}

#[test]
fn gf180_extracts_nonzero_parasitics() {
    let def_ast = def::parse_str(GF180_DEF).expect("parse def");
    let lef_lib = lef::parse_str(GF180_LEF).expect("parse lef");
    let tech_file = tech::load("gf180mcuC").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);

    assert_eq!(result.nets.len(), 1);
    let n = &result.nets[0];
    assert_eq!(n.net_name, "net1");

    // 3 µm run on Metal1 (width 0.23 µm in the gf180 stack but the DEF
    // route uses LEF default; the extractor uses min_width as fallback).
    // Sheet resistance is 0.090 Ω/sq, so R is in the low-ohm range.
    assert!(
        n.total_res_ohm > 0.0,
        "expected non-zero R, got {}",
        n.total_res_ohm
    );
    assert!(
        n.total_res_ohm < 100.0,
        "R unreasonably large: {}",
        n.total_res_ohm
    );

    // Cap should be in the few-tenths-fF range (Sakurai-Tamaru).
    let (c_area, c_fringe) = capacitance::wire_capacitance_split(&tech_file, "Metal1", 3.0, 0.23);
    assert!(c_area + c_fringe > 0.0);
    assert!(
        n.total_cap_ff > 0.0,
        "expected non-zero C, got {}",
        n.total_cap_ff
    );
}

#[test]
fn gf180_corner_scaling_works() {
    let def_ast = def::parse_str(GF180_DEF).expect("parse def");
    let lef_lib = lef::parse_str(GF180_LEF).expect("parse lef");
    let base = tech::load("gf180mcuC").expect("tech");

    let mut caps = Vec::new();
    for c in [Corner::Min, Corner::Typ, Corner::Max] {
        let t = base.clone().with_corner(c);
        let r = extract::extract(&def_ast, &lef_lib, &t);
        caps.push(r.nets[0].total_cap_ff);
    }
    // Min < Typ < Max for capacitance under the corner scaling.
    assert!(
        caps[0] < caps[1] && caps[1] < caps[2],
        "corner ordering violated: min={}, typ={}, max={}",
        caps[0],
        caps[1],
        caps[2]
    );
}
