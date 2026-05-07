//! KLayout-compatible RDB (Report DataBase) XML output.
//!
//! Produces a small subset of the format that KLayout's marker browser
//! understands. We hand-write the XML with `quick-xml` to keep dependency
//! surface area small and the output deterministic.

use crate::rules::ast::RuleDeck;
use crate::violation::Violation;
use crate::{DrcError, Result};
use quick_xml::events::{BytesDecl, BytesEnd, BytesStart, BytesText, Event};
use quick_xml::Writer;
use std::collections::BTreeSet;
use std::io::Write;

pub fn write_rdb<W: Write>(
    mut writer: W,
    deck_name: &str,
    tool_label: &str,
    deck: &RuleDeck,
    top_cell: &str,
    violations: &[Violation],
) -> Result<()> {
    let mut buf = Vec::<u8>::new();
    {
        let mut w = Writer::new(&mut buf);
        w.write_event(Event::Decl(BytesDecl::new("1.0", Some("utf-8"), None)))
            .map_err(|e| DrcError::Xml(e.to_string()))?;
        write_start(&mut w, "report-database")?;
        write_text_elem(
            &mut w,
            "description",
            &format!("{tool_label} - {deck_name}"),
        )?;

        // Categories — emit one per rule defined in the deck so the report
        // is self-describing even if the rule produced zero violations.
        write_start(&mut w, "categories")?;
        for rule in &deck.rules {
            write_start(&mut w, "category")?;
            write_text_elem(&mut w, "name", rule.name())?;
            write_text_elem(&mut w, "description", &rule.description())?;
            write_end(&mut w, "category")?;
        }
        write_end(&mut w, "categories")?;

        // Cells — the union of cells we actually saw plus the top cell.
        let mut cells: BTreeSet<&str> = BTreeSet::new();
        cells.insert(top_cell);
        for v in violations {
            cells.insert(v.cell.as_str());
        }
        write_start(&mut w, "cells")?;
        for c in &cells {
            write_start(&mut w, "cell")?;
            write_text_elem(&mut w, "name", c)?;
            write_end(&mut w, "cell")?;
        }
        write_end(&mut w, "cells")?;

        // Items.
        write_start(&mut w, "items")?;
        for v in violations {
            write_start(&mut w, "item")?;
            write_text_elem(&mut w, "category", &v.rule)?;
            write_text_elem(&mut w, "cell", &v.cell)?;
            write_start(&mut w, "values")?;
            let (x0, y0, x1, y1) = v.coords_um;
            let poly = format!(
                "polygon: (({x0:.4},{y0:.4};{x1:.4},{y0:.4};{x1:.4},{y1:.4};{x0:.4},{y1:.4}))"
            );
            write_text_elem(&mut w, "value", &poly)?;
            write_text_elem(&mut w, "value", &format!("text: {}", v.message))?;
            write_end(&mut w, "values")?;
            write_end(&mut w, "item")?;
        }
        write_end(&mut w, "items")?;
        write_end(&mut w, "report-database")?;
    }
    writer.write_all(&buf)?;
    Ok(())
}

fn write_start<W: Write>(w: &mut Writer<W>, tag: &str) -> Result<()> {
    w.write_event(Event::Start(BytesStart::new(tag)))
        .map_err(|e| DrcError::Xml(e.to_string()))?;
    Ok(())
}
fn write_end<W: Write>(w: &mut Writer<W>, tag: &str) -> Result<()> {
    w.write_event(Event::End(BytesEnd::new(tag)))
        .map_err(|e| DrcError::Xml(e.to_string()))?;
    Ok(())
}
fn write_text_elem<W: Write>(w: &mut Writer<W>, tag: &str, text: &str) -> Result<()> {
    write_start(w, tag)?;
    w.write_event(Event::Text(BytesText::new(text)))
        .map_err(|e| DrcError::Xml(e.to_string()))?;
    write_end(w, tag)?;
    Ok(())
}
