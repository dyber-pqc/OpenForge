//! End-to-end integration test:
//!   1. Generate a small GDS in-memory containing one violation (a met1 box
//!      that's 0.10 um wide — below the 0.14 um width threshold).
//!   2. Run DRC against the simple.drc rule deck.
//!   3. Assert exactly one violation, on rule met1.W.1.
//!   4. Verify the emitted RDB XML is parseable.

use gds21::{GdsBoundary, GdsElement, GdsLibrary, GdsPoint, GdsStruct, GdsUnits};
use openforge_drc::checks;
use openforge_drc::gds::reader::read_gds_with_layers;
use openforge_drc::rdb::write_rdb;
use openforge_drc::rules::parse_deck;
use std::fs;
use std::path::PathBuf;
use tempfile::tempdir;

/// Build a GDS file with a single rectangle on met1 (layer 68) that is
/// 0.10 um wide x 1.0 um tall — i.e. one width violation. DB unit is 1 nm
/// (the gds21 default), so coordinates are integers in nanometers.
fn write_test_gds(path: &std::path::Path) {
    let units = GdsUnits::default(); // 1 nm DB unit, 1 um user unit
    let xy = GdsPoint::vec(&[
        (0, 0),
        (100, 0),    // 100 nm = 0.10 um wide
        (100, 1000), // 1000 nm = 1.0 um tall
        (0, 1000),
        (0, 0),
    ]);
    let boundary = GdsBoundary {
        layer: 68,
        datatype: 0,
        xy,
        ..Default::default()
    };
    let mut s = GdsStruct::new("TOP");
    s.elems.push(GdsElement::GdsBoundary(boundary));

    let lib = GdsLibrary {
        name: "test".to_string(),
        units,
        structs: vec![s],
        ..Default::default()
    };
    lib.save(path).expect("save gds");
}

fn fixtures_dir() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p
}

#[test]
fn detects_single_width_violation_and_writes_rdb() {
    let dir = tempdir().unwrap();
    let gds_path = dir.path().join("test.gds");
    write_test_gds(&gds_path);

    let deck_src = fs::read_to_string(fixtures_dir().join("simple.drc")).unwrap();
    let deck = parse_deck(&deck_src).expect("parse deck");
    assert_eq!(deck.rules.len(), 3);

    let layout = read_gds_with_layers(&gds_path, &deck.layers).expect("read gds");
    assert_eq!(layout.polygons.len(), 1);

    let mut all = Vec::new();
    for rule in &deck.rules {
        all.extend(checks::run_rule(rule, &layout, &deck.layers).unwrap());
    }
    assert_eq!(all.len(), 1, "expected exactly 1 violation, got {all:#?}");
    assert_eq!(all[0].rule, "met1.W.1");
    assert_eq!(all[0].layer, "met1");

    // Write the RDB and verify it round-trips through quick-xml as
    // well-formed XML containing the expected tags.
    let rdb_path = dir.path().join("out.rdb");
    let f = fs::File::create(&rdb_path).unwrap();
    write_rdb(
        f,
        &deck.name,
        "OpenForge DRC test",
        &deck,
        &layout.top_cell,
        &all,
    )
    .unwrap();

    let xml = fs::read_to_string(&rdb_path).unwrap();
    assert!(xml.contains("<report-database>"));
    assert!(xml.contains("<category>"));
    assert!(xml.contains("met1.W.1"));
    assert!(xml.contains("<item>"));

    // Parse with quick-xml to confirm well-formedness.
    let mut reader = quick_xml::Reader::from_str(&xml);
    reader.config_mut().trim_text(true);
    let mut buf = Vec::new();
    let mut depth = 0i32;
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(quick_xml::events::Event::Start(_)) => depth += 1,
            Ok(quick_xml::events::Event::End(_)) => depth -= 1,
            Ok(quick_xml::events::Event::Eof) => break,
            Err(e) => panic!("XML parse error: {e}"),
            _ => {}
        }
        buf.clear();
    }
    assert_eq!(depth, 0, "unbalanced XML tags");
}

#[test]
fn detects_no_violations_when_layout_is_clean() {
    let dir = tempdir().unwrap();
    let gds_path = dir.path().join("clean.gds");

    // 0.20 um x 1.0 um rectangle on met1 — passes width >= 0.14 um.
    let units = GdsUnits::default();
    let xy = GdsPoint::vec(&[(0, 0), (200, 0), (200, 1000), (0, 1000), (0, 0)]);
    let boundary = GdsBoundary {
        layer: 68,
        datatype: 0,
        xy,
        ..Default::default()
    };
    let mut s = GdsStruct::new("TOP");
    s.elems.push(GdsElement::GdsBoundary(boundary));
    let lib = GdsLibrary {
        name: "clean".to_string(),
        units,
        structs: vec![s],
        ..Default::default()
    };
    lib.save(&gds_path).unwrap();

    let deck_src = fs::read_to_string(fixtures_dir().join("simple.drc")).unwrap();
    let deck = parse_deck(&deck_src).unwrap();
    let layout = read_gds_with_layers(&gds_path, &deck.layers).unwrap();
    let mut all = Vec::new();
    for rule in &deck.rules {
        all.extend(checks::run_rule(rule, &layout, &deck.layers).unwrap());
    }
    assert_eq!(all.len(), 0);
}
