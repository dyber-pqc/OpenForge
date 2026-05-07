//! Regression test: parse the real sky130 merged LEF.
//!
//! The merged LEF (`sky130_fd_sc_hd_merged.lef`) contains the full set of
//! property statements found in production cell libraries — antenna props,
//! USE/SHAPE/MUSTJOIN, multi-PORT pins, OBS blocks, etc. Earlier versions
//! of the parser crashed at line ~68384 with "EOF in PIN" because the
//! PIN-body state machine couldn't tell a property statement from a nested
//! END. This test guards against that regression.
//!
//! The test is gated on the file's existence so it skips cleanly on dev
//! machines / CI runners that don't have the PDK installed.

use openforge_xrc::lef;

const SKY130_MERGED_LEF: &str = "../../share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef";

#[test]
fn parse_sky130_merged_lef() {
    if !std::path::Path::new(SKY130_MERGED_LEF).exists() {
        eprintln!("skipping: {SKY130_MERGED_LEF} not present");
        return;
    }
    let lib = lef::parse_file(SKY130_MERGED_LEF).expect("parse sky130 merged LEF");
    assert!(
        lib.macros.len() > 100,
        "expected > 100 macros in sky130 hd library, got {}",
        lib.macros.len()
    );
    // Every macro should have collected at least its power/ground pins.
    let with_pins = lib.macros.iter().filter(|m| !m.pins.is_empty()).count();
    assert!(
        with_pins > 100,
        "expected > 100 macros with pins, got {with_pins}"
    );
}
