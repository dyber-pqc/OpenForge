use super::ast::{LayerProps, TechFile, ViaProps};

/// Built-in sky130A tech constants. Values approximate the OpenROAD process file.
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
                above_layer: None,
            },
            LayerProps {
                name: "met1".into(),
                sheet_resistance_ohm: 0.125,
                cap_per_area_ff_per_um2: 0.000064,
                fringe_cap_ff_per_um: 0.000031,
                min_width_um: 0.14,
                thickness_um: 0.36,
                above_layer: Some("li1".into()),
            },
            LayerProps {
                name: "met2".into(),
                sheet_resistance_ohm: 0.125,
                cap_per_area_ff_per_um2: 0.000035,
                fringe_cap_ff_per_um: 0.000031,
                min_width_um: 0.14,
                thickness_um: 0.36,
                above_layer: Some("met1".into()),
            },
            LayerProps {
                name: "met3".into(),
                sheet_resistance_ohm: 0.047,
                cap_per_area_ff_per_um2: 0.000022,
                fringe_cap_ff_per_um: 0.000027,
                min_width_um: 0.30,
                thickness_um: 0.85,
                above_layer: Some("met2".into()),
            },
            LayerProps {
                name: "met4".into(),
                sheet_resistance_ohm: 0.047,
                cap_per_area_ff_per_um2: 0.000018,
                fringe_cap_ff_per_um: 0.000026,
                min_width_um: 0.30,
                thickness_um: 0.85,
                above_layer: Some("met3".into()),
            },
            LayerProps {
                name: "met5".into(),
                sheet_resistance_ohm: 0.029,
                cap_per_area_ff_per_um2: 0.000014,
                fringe_cap_ff_per_um: 0.000022,
                min_width_um: 1.6,
                thickness_um: 1.26,
                above_layer: Some("met4".into()),
            },
        ],
        vias: vec![
            ViaProps {
                name: "L1M1_PR".into(),
                resistance_ohm: 9.5,
                between: ("li1".into(), "met1".into()),
            },
            ViaProps {
                name: "M1M2_PR".into(),
                resistance_ohm: 4.0,
                between: ("met1".into(), "met2".into()),
            },
            ViaProps {
                name: "M2M3_PR".into(),
                resistance_ohm: 4.0,
                between: ("met2".into(), "met3".into()),
            },
            ViaProps {
                name: "M3M4_PR".into(),
                resistance_ohm: 0.6,
                between: ("met3".into(), "met4".into()),
            },
            ViaProps {
                name: "M4M5_PR".into(),
                resistance_ohm: 0.4,
                between: ("met4".into(), "met5".into()),
            },
        ],
    }
}
