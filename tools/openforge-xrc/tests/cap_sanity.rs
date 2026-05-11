//! Sanity tests on capacitance magnitudes.
//!
//! These tests pin the extractor to known-answer geometries: hand-built
//! DEFs for which we can compute the expected total cap analytically and
//! demand the extractor land within a generous tolerance. They exist to
//! catch unit-conversion or formula-scale regressions that bloat totals
//! by orders of magnitude — the kind of bug a tight per-net unit test
//! would miss because individual entries still look numerically sensible.

use openforge_xrc::{def, extract, lef, tech};
use std::path::Path;

const TINY_LEF: &str = "tests/fixtures/tiny.lef";

/// 100 parallel-run pairs of 1mm met1 wires at min spacing.
///
/// 200 wires total (100 pairs), each 1000 µm long on met1 (w=0.14 µm),
/// laid out as horizontal stripes spaced 0.42 µm apart in Y so each
/// adjacent pair has 0.28 µm edge-to-edge spacing (well above the
/// MIN_SPACING_UM floor). Successive pairs are spaced widely enough to
/// avoid coupling between groups.
///
/// Per-pair coupling (Sakurai-Tamaru area + fringe per wire ≈ 75 fF/mm,
/// so 200 wires × 75 fF ≈ 15 pF for self-cap; plus same-layer coupling
/// of 100 pairs × 0.035·1000·0.36/0.28 ≈ 4.5 pF). Total expected order
/// ~10-30 pF (1e4-3e4 fF). This test demands [3e3, 1e5] fF — three
/// orders of magnitude tolerance, which is enough to catch 1e9-scale
/// unit bugs while accommodating the simple analytic estimate.
#[test]
fn parallel_run_pairs_total_cap_in_picofarad_range() {
    // 100 pairs of 1mm-long horizontal met1 wires.
    // DEF UNITS DISTANCE MICRONS 1000 → integer coords are nm.
    // Wire width = 0.14 µm; pair edge-to-edge spacing 0.28 µm
    // → centerline spacing = 0.42 µm = 420 nm. Pair-to-pair gap = 5 µm.
    let mut def = String::new();
    def.push_str("VERSION 5.8 ;\nDESIGN sanity ;\nUNITS DISTANCE MICRONS 1000 ;\n");
    def.push_str("DIEAREA ( 0 0 ) ( 1100000 600000 ) ;\n");
    def.push_str("COMPONENTS 0 ;\nEND COMPONENTS\n");
    let n_pairs: i64 = 100;
    def.push_str(&format!("NETS {} ;\n", n_pairs * 2));
    let pair_dy_nm: i64 = 420; // 0.42 µm centerline spacing
    let group_dy_nm: i64 = 5000; // 5 µm gap between pairs
    let x0: i64 = 1000; // start at 1 µm
    let x1: i64 = 1_001_000; // end at 1001 µm → 1000 µm long
    for i in 0..n_pairs {
        let y_base = 1000 + i * group_dy_nm;
        for k in 0..2 {
            let y = y_base + k * pair_dy_nm;
            // Net name unique per wire so coupling is between different nets.
            def.push_str(&format!(
                "- n{}_{} + ROUTED met1 ( {} {} ) ( {} * ) ;\n",
                i, k, x0, y, x1
            ));
        }
    }
    def.push_str("END NETS\nEND DESIGN\n");

    let path = std::env::temp_dir().join("openforge_xrc_sanity_parallel.def");
    std::fs::write(&path, def).expect("write sanity def");
    let def_ast = def::parse_file(path.to_str().expect("path utf8")).expect("parse def");
    let lef_lib = lef::parse_file(TINY_LEF).expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("load sky130A");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);

    let total_c = result.total_c_ff();
    // Expected: 200 wires × ~75 fF/mm × 1 mm self-cap ≈ 15,000 fF, plus
    // ~5,000 fF coupling. Demand [3,000, 100,000] fF — wide enough that
    // formula tweaks don't trip the test, narrow enough to catch any
    // unit-conversion blow-up of 100× or more.
    assert!(
        (3_000.0..=100_000.0).contains(&total_c),
        "parallel-run total C {total_c} fF outside [3e3, 1e5] sanity range — \
         likely a unit-scale regression in extract::{{coupling,cross_layer}}"
    );
    // Also pin the wirelength so we know the DEF parsed correctly.
    let wl = result.total_wirelength_um();
    assert!(
        (199_000.0..=201_000.0).contains(&wl),
        "expected ~200,000 µm of wire, got {wl}"
    );
}

/// PicoRV32 regression: full routed.def must yield a total cap in the
/// physically plausible 1e5–1e8 fF window (100 pF – 100 nF) for ~1.9 mm
/// of sky130 routing. Skipped when the fixture is absent so CI without
/// synthesised examples still passes.
#[test]
fn picorv32_total_cap_in_nanofarad_range() {
    let def_path = "../../examples/asic-picorv32-sky130/build/routing/routed.def";
    if !Path::new(def_path).exists() {
        eprintln!("skipping: {def_path} not present (run synthesis to enable)");
        return;
    }
    let def_ast = def::parse_file(def_path).expect("parse picorv32 routed.def");
    let lef_lib = lef::parse_file(TINY_LEF).expect("parse tiny.lef");
    let tech_file = tech::load("sky130A").expect("load sky130A");
    let result = extract::extract(&def_ast, &lef_lib, &tech_file);

    let total_c = result.total_c_ff();
    // Pre-fix this number was 4.78e14 fF (~478 PF). Post-fix should land
    // in the nF range for a chip with ~1.9 mm of routed wire.
    assert!(
        (1.0e5..=1.0e8).contains(&total_c),
        "picorv32 total C {total_c} fF outside plausible [1e5, 1e8] window"
    );
}
