//! Built-in tech-file constants for GlobalFoundries gf180mcuC (5V MCU flavour).
//!
//! Numbers are derived from the open-source `gf180mcu-pdk` repo (Google /
//! GlobalFoundries) and the gf180mcu OpenROAD platform configuration:
//!
//!   * <https://github.com/google/gf180mcu-pdk>
//!   * <https://gf180mcu-pdk.readthedocs.io/>
//!
//! gf180mcuC has five copper metal layers (Metal1..Metal5) plus a poly /
//! contact stack. Metal1..Metal4 are "thin" copper and Metal5 is "thick"
//! (top metal). The constants below are typical-corner approximations
//! suitable for analytical R/C extraction; they are not intended to replace
//! a full Quantus / Raphael deck. Layer names match the gf180mcu LEF
//! convention (`Metal1`..`Metal5`).
use super::ast::{CornerSetting, LayerProps, TechFile, ViaProps};

/// Built-in gf180mcuC tech constants.
///
/// `inter_layer_distance_um` is the vertical ILD thickness from each layer
/// to the next layer above. `height_to_substrate_um` is the distance from
/// the wire bottom to the underlying reference plane (used for the Sakurai
/// fringe model).
pub fn gf180mcu_c_tech() -> TechFile {
    TechFile {
        name: "gf180mcuC".to_string(),
        layers: vec![
            // Metal1: 0.28 µm minimum width, ~0.50 µm thick copper.
            LayerProps {
                name: "Metal1".into(),
                sheet_resistance_ohm: 0.090,
                cap_per_area_ff_per_um2: 0.000056,
                fringe_cap_ff_per_um: 0.000050,
                min_width_um: 0.23,
                thickness_um: 0.50,
                above_layer: Some("Metal2".into()),
                inter_layer_distance_um: Some(0.62),
                height_to_substrate_um: Some(0.92),
            },
            LayerProps {
                name: "Metal2".into(),
                sheet_resistance_ohm: 0.090,
                cap_per_area_ff_per_um2: 0.000031,
                fringe_cap_ff_per_um: 0.000048,
                min_width_um: 0.28,
                thickness_um: 0.50,
                above_layer: Some("Metal3".into()),
                inter_layer_distance_um: Some(0.62),
                height_to_substrate_um: Some(2.04),
            },
            LayerProps {
                name: "Metal3".into(),
                sheet_resistance_ohm: 0.090,
                cap_per_area_ff_per_um2: 0.000022,
                fringe_cap_ff_per_um: 0.000045,
                min_width_um: 0.28,
                thickness_um: 0.50,
                above_layer: Some("Metal4".into()),
                inter_layer_distance_um: Some(0.62),
                height_to_substrate_um: Some(3.16),
            },
            LayerProps {
                name: "Metal4".into(),
                sheet_resistance_ohm: 0.090,
                cap_per_area_ff_per_um2: 0.000017,
                fringe_cap_ff_per_um: 0.000043,
                min_width_um: 0.28,
                thickness_um: 0.50,
                above_layer: Some("Metal5".into()),
                inter_layer_distance_um: Some(0.85),
                height_to_substrate_um: Some(4.28),
            },
            // Metal5 is the thick top metal (~0.90 µm copper, 0.44 µm min width).
            LayerProps {
                name: "Metal5".into(),
                sheet_resistance_ohm: 0.040,
                cap_per_area_ff_per_um2: 0.000013,
                fringe_cap_ff_per_um: 0.000038,
                min_width_um: 0.44,
                thickness_um: 0.90,
                above_layer: None,
                inter_layer_distance_um: None,
                height_to_substrate_um: Some(5.63),
            },
        ],
        vias: vec![
            ViaProps {
                name: "Via1".into(),
                resistance_ohm: 4.5,
                between: ("Metal1".into(), "Metal2".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via1_4CUT".into(),
                resistance_ohm: 4.5,
                between: ("Metal1".into(), "Metal2".into()),
                cut_count: 4,
            },
            ViaProps {
                name: "Via2".into(),
                resistance_ohm: 4.5,
                between: ("Metal2".into(), "Metal3".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via3".into(),
                resistance_ohm: 4.5,
                between: ("Metal3".into(), "Metal4".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via4".into(),
                resistance_ohm: 1.2,
                between: ("Metal4".into(), "Metal5".into()),
                cut_count: 1,
            },
        ],
        corner: CornerSetting::default(),
    }
}
