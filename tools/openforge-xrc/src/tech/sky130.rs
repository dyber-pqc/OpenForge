use super::ast::{LayerProps, TechFile, ViaProps};

/// Built-in sky130A tech constants. Values approximate the OpenROAD process file.
///
/// `inter_layer_distance_um` is the vertical ILD thickness from each layer to
/// the next layer above, used for cross-layer coupling. `height_to_substrate_um`
/// is the distance from the wire bottom to the underlying reference plane,
/// used in the Sakurai fringe model.
pub fn sky130a_tech() -> TechFile {
    TechFile {
        name: "sky130A".to_string(),
        layers: vec![
            LayerProps {
                name: "li1".into(),
                sheet_resistance_ohm: 12.8,
                cap_per_area_ff_per_um2: 0.000087,
                fringe_cap_ff_per_um: 0.00038,
                min_width_um: 0.17,
                thickness_um: 0.10,
                above_layer: Some("met1".into()),
                // li1 → met1 ILD ~ 0.55 µm
                inter_layer_distance_um: Some(0.55),
                // li1 sits ~0.94 µm above the substrate (poly + cont).
                height_to_substrate_um: Some(0.94),
            },
            LayerProps {
                name: "met1".into(),
                sheet_resistance_ohm: 0.125,
                cap_per_area_ff_per_um2: 0.000064,
                fringe_cap_ff_per_um: 0.000031,
                min_width_um: 0.14,
                thickness_um: 0.36,
                above_layer: Some("met2".into()),
                inter_layer_distance_um: Some(0.36),
                height_to_substrate_um: Some(1.37),
            },
            LayerProps {
                name: "met2".into(),
                sheet_resistance_ohm: 0.125,
                cap_per_area_ff_per_um2: 0.000035,
                fringe_cap_ff_per_um: 0.000031,
                min_width_um: 0.14,
                thickness_um: 0.36,
                above_layer: Some("met3".into()),
                inter_layer_distance_um: Some(0.85),
                height_to_substrate_um: Some(2.00),
            },
            LayerProps {
                name: "met3".into(),
                sheet_resistance_ohm: 0.047,
                cap_per_area_ff_per_um2: 0.000022,
                fringe_cap_ff_per_um: 0.000027,
                min_width_um: 0.30,
                thickness_um: 0.85,
                above_layer: Some("met4".into()),
                inter_layer_distance_um: Some(0.85),
                height_to_substrate_um: Some(3.10),
            },
            LayerProps {
                name: "met4".into(),
                sheet_resistance_ohm: 0.047,
                cap_per_area_ff_per_um2: 0.000018,
                fringe_cap_ff_per_um: 0.000026,
                min_width_um: 0.30,
                thickness_um: 0.85,
                above_layer: Some("met5".into()),
                inter_layer_distance_um: Some(1.40),
                height_to_substrate_um: Some(4.85),
            },
            LayerProps {
                name: "met5".into(),
                sheet_resistance_ohm: 0.029,
                cap_per_area_ff_per_um2: 0.000014,
                fringe_cap_ff_per_um: 0.000022,
                min_width_um: 1.6,
                thickness_um: 1.26,
                above_layer: None,
                inter_layer_distance_um: None,
                height_to_substrate_um: Some(7.10),
            },
        ],
        vias: vec![
            ViaProps {
                name: "L1M1_PR".into(),
                resistance_ohm: 9.5,
                between: ("li1".into(), "met1".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "M1M2_PR".into(),
                resistance_ohm: 4.0,
                between: ("met1".into(), "met2".into()),
                cut_count: 1,
            },
            // Multi-cut variant: 2×2 array of cuts (parallel resistance ÷4).
            ViaProps {
                name: "M1M2_PR_4CUT".into(),
                resistance_ohm: 4.0,
                between: ("met1".into(), "met2".into()),
                cut_count: 4,
            },
            ViaProps {
                name: "M2M3_PR".into(),
                resistance_ohm: 4.0,
                between: ("met2".into(), "met3".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "M3M4_PR".into(),
                resistance_ohm: 0.6,
                between: ("met3".into(), "met4".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "M4M5_PR".into(),
                resistance_ohm: 0.4,
                between: ("met4".into(), "met5".into()),
                cut_count: 1,
            },
        ],
    }
}
