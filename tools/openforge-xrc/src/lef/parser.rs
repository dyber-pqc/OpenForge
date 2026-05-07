//! LEF parser — minimal subset: collects MACRO names and their pins.
//!
//! For xRC v0.1 we only need macro/pin information so we can map DEF
//! connections to logical cell pins. Layer geometry is not yet used.

use crate::error::{Result, XrcError};

#[derive(Debug, Clone, Default)]
pub struct LefLibrary {
    pub macros: Vec<LefMacro>,
    pub layers: Vec<LefLayer>,
}

#[derive(Debug, Clone)]
pub struct LefMacro {
    pub name: String,
    pub pins: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct LefLayer {
    pub name: String,
    pub kind: String, // "ROUTING", "CUT", etc.
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
    fn err(&self, msg: impl Into<String>) -> XrcError {
        XrcError::LefParse {
            line: self.line,
            msg: msg.into(),
        }
    }
}

pub fn parse(src: &str) -> Result<LefLibrary> {
    let mut t = Tokens::new(src);
    let mut lib = LefLibrary::default();

    while let Some(tok) = t.next_tok() {
        match tok {
            "MACRO" => {
                let name = t.next_tok().ok_or_else(|| t.err("MACRO name expected"))?;
                let m = parse_macro(&mut t, name)?;
                lib.macros.push(m);
            }
            "LAYER" => {
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("LAYER name expected"))?
                    .to_string();
                let kind = parse_layer_kind(&mut t, &name)?;
                lib.layers.push(LefLayer { name, kind });
            }
            "END" => {
                // top-level "END LIBRARY" — just consume next token if any.
                let _ = t.next_tok();
            }
            _ => { /* tolerate unknown top-level tokens */ }
        }
    }
    Ok(lib)
}

/// Parse a MACRO body until "END <name>". Collect PIN names.
fn parse_macro(t: &mut Tokens<'_>, name: &str) -> Result<LefMacro> {
    let mut pins: Vec<String> = Vec::new();
    let target = format!("__END_MACRO__{name}");
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in MACRO"))?;
        match tok {
            "PIN" => {
                let pname = t
                    .next_tok()
                    .ok_or_else(|| t.err("PIN name expected"))?
                    .to_string();
                // Skip until "END <pname>".
                loop {
                    let pt = t.next_tok().ok_or_else(|| t.err("EOF in PIN"))?;
                    if pt == "END" {
                        if let Some(lbl) = t.next_tok() {
                            if lbl == pname {
                                break;
                            }
                        }
                    }
                }
                pins.push(pname);
            }
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END label expected"))?;
                if lbl == name {
                    return Ok(LefMacro {
                        name: name.to_string(),
                        pins,
                    });
                }
                // else: nested END, keep going (shouldn't happen if PIN handler ate it).
            }
            _ => { /* skip everything else: SIZE, OBS, FOREIGN, etc. */ }
        }
        let _ = target.len(); // silence dead-code warning for 'target' (kept for clarity)
    }
}

fn parse_layer_kind(t: &mut Tokens<'_>, name: &str) -> Result<String> {
    // The next "TYPE" attribute tells us what kind of layer this is.
    let mut kind = String::from("UNKNOWN");
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in LAYER"))?;
        match tok {
            "TYPE" => {
                let v = t.next_tok().ok_or_else(|| t.err("TYPE value"))?;
                kind = v.to_string();
                // consume trailing ';'
                if let Some(s) = t.next_tok() {
                    if s != ";" {
                        // Some LEFs don't use ';' — best-effort.
                    }
                }
            }
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END label expected"))?;
                if lbl == name {
                    return Ok(kind);
                }
            }
            _ => {}
        }
    }
}
