//! Multi-PDK regression: extract parasitics on a routed segment using the
//! built-in IHP sg13g2 (130 nm SiGe BiCMOS) tech file. Asserts that the
//! tech loads, the layer stack is consistent, and a DEF route on `Metal1`
//! produces non-zero R/C across all three corners.

use openforge_xrc::extract::capacitance;
use openforge_xrc::tech::{self, Corner};
use openforge_xrc::{def, extract, lef};

const IHP_LEF: &str = "VERSION 5.7 ;
NAMESCASESENSITIVE ON ;
BUSBITCHARS \"[]\" ;
DIVIDERCHAR \"/\" ;

LAYER Metal1
  TYPE ROUTING ;
END Metal1

LAYER Metal2
  TYPE ROUTING ;
END Metal2

MACRO sg13g2_inv_1
  PIN A
    DIRECTION INPUT ;
  END A
  PIN Y
    DIRECTION OUTPUT ;
  END Y
END sg13g2_inv_1

END LIBRARY
";

const IHP_DEF: &str = "VERSION 5.8 ;
DESIGN ihp_tiny ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
COMPONENTS 2 ;
- a sg13g2_inv_1 + PLACED ( 1000 1000 ) N ;
- b sg13g2_inv_1 + PLACED ( 5000 1000 ) N ;
END COMPONENTS
NETS 1 ;
- net1 ( a Y ) ( b A )
  + ROUTED Metal1 ( 1500 1500 ) ( 4500 1500 0 ) ;
END NETS
END DESIGN
";

#[test]
fn ihp_sg13g2_tech_loads_and_has_expected_layers() {
    let t = tech::load("ihp_sg13g2").expect("load ihp_sg13g2");
    assert_eq!(t.name, "ihp_sg13g2");
    for name in [
        "Metal1",
        "Metal2",
        "Metal3",
        "Metal4",
        "Metal5",
        "TopMetal1",
        "TopMetal2",
    ] {
        assert!(t.layer(name).is_some(), "missing layer {name}");
    }
    // Top metal has no layer above; intermediate layers do.
    assert!(t.layer("TopMetal2").unwrap().above_layer.is_none());
    assert_eq!(
        t.layer("Metal1").unwrap().above_layer.as_deref(),
        Some("Metal2")
    );
    assert_eq!(
        t.layer("Metal5").unwrap().above_layer.as_deref(),
        Some("TopMetal1")
    );
    // Reasonable physical numbers.
    assert!(t.layer("Metal1").unwrap().sheet_resistance_ohm > 0.0);
    // Top aluminum is much thicker than back-end Cu.
    assert!(t.layer("TopMetal2").unwrap().thickness_um > t.layer("Metal1").unwrap().thickness_um);
    // Top Al has lower sheet R than back-end Cu (it's much thicker).
    assert!(
        t.layer("TopMetal2").unwrap().sheet_resistance_ohm
            < t.layer("Metal1").unwrap().sheet_resistance_ohm
    );
    assert!(!t.vias.is_empty());
    assert!(t.via_between("Metal1", "Metal2").is_some());
    assert!(t.via_between("Metal5", "TopMetal1").is_some());
    assert!(t.via_between("TopMetal1", "TopMetal2").is_some());

    // Aliases also resolve.
    assert!(tech::load("IHPSG13G2").is_ok());
    assert!(tech::load("ihp-sg13g2").is_ok());
}

#[test]
fn ihp_sg13g2_extracts_nonzero_parasitics() {
    let def_ast = def::parse_str(IHP_DEF).expect("parse def");
    let lef_lib = lef::parse_str(IHP_LEF).expect("parse lef");
    let tech_file = tech::load("ihp_sg13g2").expect("tech");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);

    assert_eq!(result.nets.len(), 1);
    let n = &result.nets[0];
    assert_eq!(n.net_name, "net1");

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

    let (c_area, c_fringe) = capacitance::wire_capacitance_split(&tech_file, "Metal1", 3.0, 0.16);
    assert!(c_area + c_fringe > 0.0);
    assert!(
        n.total_cap_ff > 0.0,
        "expected non-zero C, got {}",
        n.total_cap_ff
    );
}

#[test]
fn ihp_sg13g2_corner_scaling_works() {
    let def_ast = def::parse_str(IHP_DEF).expect("parse def");
    let lef_lib = lef::parse_str(IHP_LEF).expect("parse lef");
    let base = tech::load("ihp_sg13g2").expect("tech");

    let mut caps = Vec::new();
    for c in [Corner::Min, Corner::Typ, Corner::Max] {
        let t = base.clone().with_corner(c);
        let r = extract::extract(&def_ast, &lef_lib, &t);
        caps.push(r.nets[0].total_cap_ff);
    }
    assert!(
        caps[0] < caps[1] && caps[1] < caps[2],
        "corner ordering violated: min={}, typ={}, max={}",
        caps[0],
        caps[1],
        caps[2]
    );
}
