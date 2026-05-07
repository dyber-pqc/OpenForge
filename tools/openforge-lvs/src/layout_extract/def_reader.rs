//! Minimal DEF reader for LVS layout extraction.
//!
//! Adapted from `tools/openforge-xrc/src/def/parser.rs`. We only need the
//! design name, the COMPONENTS list, the PINS list (top-level ports), and
//! the NETS connection lists. Routing geometry is ignored.
//!
//! Includes the ROW / TRACKS / GCELLGRID and TAPER fixes carried over from
//! the xrc parser.

use crate::error::{LvsError, Result};
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct DefData {
    pub design: String,
    pub components: Vec<DefComponent>,
    /// Top-level pins: (pin_name, direction).
    pub pins: Vec<DefPin>,
    pub nets: Vec<DefNet>,
}

#[derive(Debug, Clone)]
pub struct DefComponent {
    pub name: String,
    pub macro_name: String,
}

#[derive(Debug, Clone)]
pub struct DefPin {
    pub name: String,
    pub direction: String,
    /// The net name this PIN is associated with (PIN ... + NET <net>).
    pub net: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct DefNet {
    pub name: String,
    /// (instance, pin) — for top-level pin connections, instance == "PIN"
    /// and pin == net pin name.
    pub connections: Vec<(String, String)>,
}

pub fn parse_def_file(path: impl AsRef<Path>) -> Result<DefData> {
    let s = std::fs::read_to_string(path.as_ref())?;
    parse_def_str(&s)
}

pub fn parse_def_str(src: &str) -> Result<DefData> {
    let mut t = Tokens::new(src);
    let mut out = DefData::default();

    while let Some(tok) = t.next_tok() {
        match tok {
            // Single-statement keywords terminated by ';'.
            // Carries forward the xrc fix: ROW / TRACKS / GCELLGRID are
            // single-line statements, NOT sections, so we skip to ';'.
            "VERSION" | "DIVIDERCHAR" | "BUSBITCHARS" | "NAMESCASESENSITIVE" | "ROW" | "TRACKS"
            | "GCELLGRID" => {
                skip_to_semi(&mut t)?;
            }
            // True multi-line sections (END <name> sentinel).
            "PROPERTYDEFINITIONS"
            | "VIAS"
            | "SPECIALNETS"
            | "NONDEFAULTRULES"
            | "REGIONS"
            | "GROUPS"
            | "BLOCKAGES"
            | "FILLS"
            | "STYLES"
            | "SLOTS"
            | "BEGINEXT" => {
                skip_section(&mut t, tok)?;
            }
            "DESIGN" => {
                out.design = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected design name"))?
                    .to_string();
                skip_to_semi(&mut t)?;
            }
            "UNITS" => {
                skip_to_semi(&mut t)?;
            }
            "DIEAREA" => {
                skip_to_semi(&mut t)?;
            }
            "COMPONENTS" => {
                let _count = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected component count"))?;
                skip_to_semi(&mut t)?;
                parse_components(&mut t, &mut out.components)?;
            }
            "PINS" => {
                let _count = t.next_tok().ok_or_else(|| t.err("expected pin count"))?;
                skip_to_semi(&mut t)?;
                parse_pins(&mut t, &mut out.pins)?;
            }
            "NETS" => {
                let _count = t.next_tok().ok_or_else(|| t.err("expected net count"))?;
                skip_to_semi(&mut t)?;
                parse_nets(&mut t, &mut out.nets)?;
            }
            "END" => {
                let _ = t.next_tok();
                if !out.components.is_empty() || !out.nets.is_empty() || !out.design.is_empty() {
                    break;
                }
            }
            _ => {
                skip_to_semi(&mut t).ok();
            }
        }
    }

    Ok(out)
}

struct Tokens<'a> {
    src: &'a str,
    pos: usize,
    line: usize,
}

impl<'a> Tokens<'a> {
    fn new(src: &'a str) -> Self {
        Self {
            src,
            pos: 0,
            line: 1,
        }
    }
    fn next_tok(&mut self) -> Option<&'a str> {
        while self.pos < self.src.len() {
            let c = self.src.as_bytes()[self.pos];
            if c == b'\n' {
                self.line += 1;
                self.pos += 1;
            } else if c.is_ascii_whitespace() {
                self.pos += 1;
            } else if c == b'#' {
                while self.pos < self.src.len() && self.src.as_bytes()[self.pos] != b'\n' {
                    self.pos += 1;
                }
            } else {
                break;
            }
        }
        if self.pos >= self.src.len() {
            return None;
        }
        let start = self.pos;
        while self.pos < self.src.len() && !self.src.as_bytes()[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }
        Some(&self.src[start..self.pos])
    }
    fn err(&self, msg: impl Into<String>) -> LvsError {
        LvsError::Parse {
            line: self.line,
            msg: msg.into(),
        }
    }
}

fn skip_to_semi(t: &mut Tokens<'_>) -> Result<()> {
    while let Some(tok) = t.next_tok() {
        if tok == ";" {
            return Ok(());
        }
    }
    Err(t.err("unexpected EOF before ';'"))
}

fn skip_section(t: &mut Tokens<'_>, name: &str) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in section"))?;
        if tok == "END" {
            if let Some(label) = t.next_tok() {
                if label == name {
                    return Ok(());
                }
            }
        }
    }
}

fn parse_components(t: &mut Tokens<'_>, comps: &mut Vec<DefComponent>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in COMPONENTS"))?;
        match tok {
            "END" => {
                let _ = t.next_tok();
                return Ok(());
            }
            "-" => {
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected comp name"))?
                    .to_string();
                let macro_name = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected macro name"))?
                    .to_string();
                loop {
                    let nt = t.next_tok().ok_or_else(|| t.err("EOF in component"))?;
                    if nt == ";" {
                        break;
                    }
                }
                comps.push(DefComponent { name, macro_name });
            }
            _ => return Err(t.err(format!("unexpected '{tok}' in COMPONENTS"))),
        }
    }
}

fn parse_pins(t: &mut Tokens<'_>, pins: &mut Vec<DefPin>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in PINS"))?;
        match tok {
            "END" => {
                let _ = t.next_tok();
                return Ok(());
            }
            "-" => {
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected pin name"))?
                    .to_string();
                let mut direction = String::from("INOUT");
                let mut net: Option<String> = None;
                loop {
                    let nt = t.next_tok().ok_or_else(|| t.err("EOF in pin"))?;
                    if nt == ";" {
                        break;
                    }
                    if nt == "+" {
                        let kw = t.next_tok().ok_or_else(|| t.err("expected '+' kw"))?;
                        match kw {
                            "NET" => {
                                let n = t.next_tok().ok_or_else(|| t.err("NET name"))?;
                                net = Some(n.to_string());
                            }
                            "DIRECTION" => {
                                let d = t.next_tok().ok_or_else(|| t.err("DIRECTION"))?;
                                direction = d.to_string();
                            }
                            _ => { /* skip remainder; we tolerate stray tokens */ }
                        }
                    }
                }
                pins.push(DefPin {
                    name,
                    direction,
                    net,
                });
            }
            _ => return Err(t.err(format!("unexpected '{tok}' in PINS"))),
        }
    }
}

fn parse_nets(t: &mut Tokens<'_>, nets: &mut Vec<DefNet>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in NETS"))?;
        match tok {
            "END" => {
                let _ = t.next_tok();
                return Ok(());
            }
            "-" => {
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected net name"))?
                    .to_string();
                let mut connections: Vec<(String, String)> = Vec::new();
                loop {
                    let nt = t.next_tok().ok_or_else(|| t.err("EOF in net"))?;
                    if nt == ";" {
                        break;
                    }
                    if nt == "(" {
                        let inst = t
                            .next_tok()
                            .ok_or_else(|| t.err("expected inst"))?
                            .to_string();
                        let pin = t
                            .next_tok()
                            .ok_or_else(|| t.err("expected pin"))?
                            .to_string();
                        loop {
                            let pt = t.next_tok().ok_or_else(|| t.err("EOF in conn"))?;
                            if pt == ")" {
                                break;
                            }
                        }
                        connections.push((inst, pin));
                    } else if nt == "+" {
                        let kw = t.next_tok().ok_or_else(|| t.err("expected '+' kw"))?;
                        match kw {
                            "ROUTED" | "NEW" => {
                                // Skip routing geometry until next '+' or ';'.
                                skip_routed(t)?;
                            }
                            "USE" | "SOURCE" | "WEIGHT" | "NONDEFAULTRULE" | "FIXED" | "COVER"
                            | "SHIELDNET" | "PROPERTY" | "XTALK" | "PATTERN" => {
                                let _ = t.next_tok();
                            }
                            _ => {}
                        }
                    }
                }
                nets.push(DefNet { name, connections });
            }
            _ => return Err(t.err(format!("unexpected '{tok}' in NETS"))),
        }
    }
}

/// Skip routing geometry of a ROUTED/NEW segment, stopping just before the
/// next '+' or the terminating ';'. Carries forward the TAPER / TAPERRULE
/// fix from xrc: `TAPERRULE` takes a name argument.
fn skip_routed(t: &mut Tokens<'_>) -> Result<()> {
    // Layer name first.
    let _layer = t.next_tok().ok_or_else(|| t.err("ROUTED layer"))?;
    loop {
        let saved_pos = t.pos;
        let saved_line = t.line;
        let nt = match t.next_tok() {
            Some(s) => s,
            None => return Ok(()),
        };
        match nt {
            "(" => {
                // ( x y [ext] )
                loop {
                    let pt = t.next_tok().ok_or_else(|| t.err("EOF in route point"))?;
                    if pt == ")" {
                        break;
                    }
                }
            }
            "+" | ";" => {
                // Rewind so caller sees this token.
                t.pos = saved_pos;
                t.line = saved_line;
                return Ok(());
            }
            "TAPER" => { /* flag, no arg */ }
            "TAPERRULE" => {
                let _ = t.next_tok();
            }
            "MASK" | "RECT" | "VIRTUAL" => {
                let _ = t.next_tok();
            }
            _ => { /* via name or qualifier — ignore */ }
        }
    }
}
