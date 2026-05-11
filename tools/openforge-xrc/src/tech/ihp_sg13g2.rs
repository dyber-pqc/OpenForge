//! Built-in tech-file constants for IHP sg13g2 (130 nm SiGe BiCMOS).
//!
//! Numbers are derived from the open-source IHP-Open-PDK and the public
//! sg13g2 process documentation:
//!
//!   * <https://github.com/IHP-GmbH/IHP-Open-PDK>
//!   * <https://github.com/IHP-GmbH/IHP-Open-PDK/tree/main/ihp-sg13g2>
//!
//! sg13g2 has a 5-metal back-end + 2 thick top-metals (TopMetal1 ~2 µm Al,
//! TopMetal2 ~3 µm Al), giving a 7-routing-layer / 6-via stack from
//! `Metal1` up through `TopMetal2`. The constants below are typical-corner
//! approximations suitable for analytical R/C extraction; they are not a
//! substitute for a Quantus / Raphael deck.
//!
//! Sheet resistance / cap values are taken from the public IHP openPDK
//! `sg13g2.openPDK.tech` ranges where available; for anything not exposed
//! in the open PDK we fall back to scaled sky130 / gf180 130–180 nm
//! numbers (noted inline). All caps are per-corner Typ.
use super::ast::{CornerSetting, LayerProps, TechFile, ViaProps};

/// Built-in IHP sg13g2 tech constants.
///
/// Layer ordering (bottom -> top): Metal1, Metal2, Metal3, Metal4, Metal5,
/// TopMetal1, TopMetal2. Routing widths: Metal1 0.16 µm, Metal2..5 0.20 µm,
/// TopMetal1 1.64 µm, TopMetal2 1.64 µm (approximate IHP design-rule mins).
pub fn ihp_sg13g2_tech() -> TechFile {
    TechFile {
        name: "ihp_sg13g2".to_string(),
        layers: vec![
            // Metal1: ~0.42 µm Cu, sheet R ~0.115 Ω/sq (scaled from sky130 met1).
            LayerProps {
                name: "Metal1".into(),
                sheet_resistance_ohm: 0.115,
                cap_per_area_ff_per_um2: 0.000070,
                fringe_cap_ff_per_um: 0.000035,
                min_width_um: 0.16,
                thickness_um: 0.42,
                above_layer: Some("Metal2".into()),
                inter_layer_distance_um: Some(0.54),
                height_to_substrate_um: Some(0.95),
            },
            LayerProps {
                name: "Metal2".into(),
                sheet_resistance_ohm: 0.115,
                cap_per_area_ff_per_um2: 0.000038,
                fringe_cap_ff_per_um: 0.000033,
                min_width_um: 0.20,
                thickness_um: 0.49,
                above_layer: Some("Metal3".into()),
                inter_layer_distance_um: Some(0.54),
                height_to_substrate_um: Some(1.91),
            },
            LayerProps {
                name: "Metal3".into(),
                sheet_resistance_ohm: 0.115,
                cap_per_area_ff_per_um2: 0.000026,
                fringe_cap_ff_per_um: 0.000031,
                min_width_um: 0.20,
                thickness_um: 0.49,
                above_layer: Some("Metal4".into()),
                inter_layer_distance_um: Some(0.54),
                height_to_substrate_um: Some(2.94),
            },
            LayerProps {
                name: "Metal4".into(),
                sheet_resistance_ohm: 0.115,
                cap_per_area_ff_per_um2: 0.000019,
                fringe_cap_ff_per_um: 0.000029,
                min_width_um: 0.20,
                thickness_um: 0.49,
                above_layer: Some("Metal5".into()),
                inter_layer_distance_um: Some(0.54),
                height_to_substrate_um: Some(3.97),
            },
            LayerProps {
                name: "Metal5".into(),
                sheet_resistance_ohm: 0.115,
                cap_per_area_ff_per_um2: 0.000016,
                fringe_cap_ff_per_um: 0.000027,
                min_width_um: 0.20,
                thickness_um: 0.49,
                above_layer: Some("TopMetal1".into()),
                inter_layer_distance_um: Some(0.85),
                height_to_substrate_um: Some(5.00),
            },
            // TopMetal1 is ~2 µm thick aluminum (very low sheet R).
            LayerProps {
                name: "TopMetal1".into(),
                sheet_resistance_ohm: 0.014,
                cap_per_area_ff_per_um2: 0.000011,
                fringe_cap_ff_per_um: 0.000022,
                min_width_um: 1.64,
                thickness_um: 2.00,
                above_layer: Some("TopMetal2".into()),
                inter_layer_distance_um: Some(2.80),
                height_to_substrate_um: Some(6.34),
            },
            // TopMetal2 is the thick ~3 µm Al top metal (RFIC inductors).
            LayerProps {
                name: "TopMetal2".into(),
                sheet_resistance_ohm: 0.010,
                cap_per_area_ff_per_um2: 0.000007,
                fringe_cap_ff_per_um: 0.000018,
                min_width_um: 1.64,
                thickness_um: 3.00,
                above_layer: None,
                inter_layer_distance_um: None,
                height_to_substrate_um: Some(11.14),
            },
        ],
        vias: vec![
            // Cont (poly/active -> Metal1) — modelled inline as the bottom
            // contact stub for completeness.
            ViaProps {
                name: "Cont".into(),
                resistance_ohm: 12.0,
                between: ("GatPoly".into(), "Metal1".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via1".into(),
                resistance_ohm: 5.5,
                between: ("Metal1".into(), "Metal2".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via1_4CUT".into(),
                resistance_ohm: 5.5,
                between: ("Metal1".into(), "Metal2".into()),
                cut_count: 4,
            },
            ViaProps {
                name: "Via2".into(),
                resistance_ohm: 5.5,
                between: ("Metal2".into(), "Metal3".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via3".into(),
                resistance_ohm: 5.5,
                between: ("Metal3".into(), "Metal4".into()),
                cut_count: 1,
            },
            ViaProps {
                name: "Via4".into(),
                resistance_ohm: 5.5,
                between: ("Metal4".into(), "Metal5".into()),
                cut_count: 1,
            },
            // TopVia1 connects Metal5 to TopMetal1 — much larger plug, lower R.
            ViaProps {
                name: "TopVia1".into(),
                resistance_ohm: 1.5,
                between: ("Metal5".into(), "TopMetal1".into()),
                cut_count: 1,
            },
            // TopVia2 connects TopMetal1 to TopMetal2 (the thick Al stack).
            ViaProps {
                name: "TopVia2".into(),
                resistance_ohm: 0.6,
                between: ("TopMetal1".into(), "TopMetal2".into()),
                cut_count: 1,
            },
        ],
        corner: CornerSetting::default(),
    }
}
