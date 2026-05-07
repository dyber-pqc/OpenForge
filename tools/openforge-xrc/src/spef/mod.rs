//! SPEF (Standard Parasitic Exchange Format) — writer + simple reader.

pub mod writer;
pub use writer::write_spef;

use crate::error::{Result, XrcError};

/// Lightweight SPEF parsed form, exposing per-net totals only — sufficient
/// for round-trip tests.
#[derive(Debug, Default, Clone)]
pub struct ParsedSpef {
    pub design: String,
    pub nets: Vec<ParsedNet>,
}

#[derive(Debug, Clone)]
pub struct ParsedNet {
    pub name: String,
    pub total_cap_ff: f64,
    pub res_entries: Vec<(String, String, f64)>,
    pub cap_entries: Vec<(String, f64)>,
}

pub fn parse_str(s: &str) -> Result<ParsedSpef> {
    let mut out = ParsedSpef::default();
    let mut cur: Option<ParsedNet> = None;
    let mut mode: &str = "";
    for line in s.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with("//") {
            continue;
        }
        if let Some(rest) = line.strip_prefix("*DESIGN ") {
            out.design = rest.trim().trim_matches('"').to_string();
            continue;
        }
        if let Some(rest) = line.strip_prefix("*D_NET ") {
            if let Some(prev) = cur.take() {
                out.nets.push(prev);
            }
            let parts: Vec<&str> = rest.split_whitespace().collect();
            if parts.len() < 2 {
                return Err(XrcError::Extract(format!("bad D_NET: {line}")));
            }
            cur = Some(ParsedNet {
                name: parts[0].to_string(),
                total_cap_ff: parts[1].parse().unwrap_or(0.0),
                res_entries: Vec::new(),
                cap_entries: Vec::new(),
            });
            mode = "";
            continue;
        }
        if line == "*CAP" {
            mode = "cap";
            continue;
        }
        if line == "*RES" {
            mode = "res";
            continue;
        }
        if line == "*CONN" {
            mode = "conn";
            continue;
        }
        if line == "*END" {
            if let Some(prev) = cur.take() {
                out.nets.push(prev);
            }
            mode = "";
            continue;
        }
        if let Some(net) = cur.as_mut() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            match mode {
                "res" if parts.len() >= 4 => {
                    let r: f64 = parts[3].parse().unwrap_or(0.0);
                    net.res_entries
                        .push((parts[1].to_string(), parts[2].to_string(), r));
                }
                "cap" if parts.len() >= 3 => {
                    // Either "id node val" or "id netA netB val" (coupling) — store first form;
                    // coupling lines (4 fields) are aggregated as the value column shifts.
                    if parts.len() == 3 {
                        let c: f64 = parts[2].parse().unwrap_or(0.0);
                        net.cap_entries.push((parts[1].to_string(), c));
                    } else if parts.len() >= 4 {
                        let c: f64 = parts[3].parse().unwrap_or(0.0);
                        net.cap_entries.push((parts[1].to_string(), c));
                    }
                }
                _ => {}
            }
        }
    }
    if let Some(prev) = cur.take() {
        out.nets.push(prev);
    }
    Ok(out)
}
