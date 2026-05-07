//! Minimal LEF reader for LVS layout extraction.
//!
//! Only the macro/pin name and pin direction are needed. Adapted from
//! `tools/openforge-xrc/src/lef/parser.rs`.

use crate::error::{LvsError, Result};
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct LefLibrary {
    pub macros: Vec<LefMacro>,
}

impl LefLibrary {
    pub fn find(&self, name: &str) -> Option<&LefMacro> {
        self.macros.iter().find(|m| m.name == name)
    }

    pub fn merge(&mut self, other: LefLibrary) {
        for m in other.macros {
            if !self.macros.iter().any(|x| x.name == m.name) {
                self.macros.push(m);
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct LefMacro {
    pub name: String,
    pub pins: Vec<LefPin>,
}

#[derive(Debug, Clone)]
pub struct LefPin {
    pub name: String,
    pub direction: String,
}

pub fn parse_lef_file(path: impl AsRef<Path>) -> Result<LefLibrary> {
    let s = std::fs::read_to_string(path.as_ref())?;
    parse_lef_str(&s)
}

pub fn parse_lef_str(src: &str) -> Result<LefLibrary> {
    let mut t = Tokens::new(src);
    let mut lib = LefLibrary::default();
    while let Some(tok) = t.next_tok() {
        match tok {
            "MACRO" => {
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("MACRO name expected"))?
                    .to_string();
                let m = parse_macro(&mut t, &name)?;
                lib.macros.push(m);
            }
            "END" => {
                let _ = t.next_tok();
            }
            _ => {}
        }
    }
    Ok(lib)
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

fn parse_macro(t: &mut Tokens<'_>, name: &str) -> Result<LefMacro> {
    let mut pins: Vec<LefPin> = Vec::new();
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in MACRO"))?;
        match tok {
            "PIN" => {
                let pname = t.next_tok().ok_or_else(|| t.err("PIN name"))?.to_string();
                let pin = parse_pin(t, &pname)?;
                pins.push(pin);
            }
            "OBS" => {
                // OBS body terminated by a bare "END" (no label).
                skip_unlabeled_end_block(t)?;
            }
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END label"))?;
                if lbl == name {
                    return Ok(LefMacro {
                        name: name.to_string(),
                        pins,
                    });
                }
                // Some other END/label combo we didn't consume — keep going.
            }
            _ => {}
        }
    }
}

fn parse_pin(t: &mut Tokens<'_>, pname: &str) -> Result<LefPin> {
    let mut direction = String::from("INOUT");
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in PIN"))?;
        match tok {
            "DIRECTION" => {
                let d = t.next_tok().ok_or_else(|| t.err("DIRECTION"))?;
                direction = d.to_string();
                // consume optional ';'
                let saved = t.pos;
                let saved_l = t.line;
                if let Some(n) = t.next_tok() {
                    if n != ";" {
                        t.pos = saved;
                        t.line = saved_l;
                    }
                }
            }
            "PORT" => {
                // PORT body terminated by a bare "END".
                skip_unlabeled_end_block(t)?;
            }
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END pin label"))?;
                if lbl == pname {
                    return Ok(LefPin {
                        name: pname.to_string(),
                        direction,
                    });
                }
            }
            _ => {}
        }
    }
}

/// Skip a block whose terminator is a bare `END` (no label). Used for
/// PORT and OBS bodies, which contain LAYER directives and RECT/POLYGON
/// statements but no nested PIN/PORT/OBS.
fn skip_unlabeled_end_block(t: &mut Tokens<'_>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in PORT/OBS"))?;
        if tok == "END" {
            return Ok(());
        }
    }
}
