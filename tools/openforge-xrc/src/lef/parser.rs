//! LEF parser — minimal subset: collects MACRO names and their pins.
//!
//! For xRC v0.1 we only need macro/pin information so we can map DEF
//! connections to logical cell pins. Layer geometry is not yet used.
//!
//! The parser is intentionally lenient — unknown property statements are
//! silently consumed up to their terminating `;` so that we accept the
//! full sky130 merged LEF (which carries antenna props, USE, SHAPE,
//! NETEXPR, MUSTJOIN, etc. inside PIN bodies).

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
        // Treat ';' as its own token so we can use it as a statement terminator.
        if self.src.as_bytes()[self.pos] == b';' {
            self.pos += 1;
            return Some(&self.src[start..self.pos]);
        }
        while self.pos < self.src.len() {
            let b = self.src.as_bytes()[self.pos];
            if b.is_ascii_whitespace() || b == b';' {
                break;
            }
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
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("MACRO name expected"))?
                    .to_string();
                let m = parse_macro(&mut t, &name)?;
                lib.macros.push(m);
            }
            "LAYER" => {
                // At top-level, LAYER introduces a layer definition block
                // ended by `END <name>`. (Inside MACRO/PIN/PORT, LAYER is a
                // single-line statement — handled separately there.)
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

/// Skip the rest of a single property statement, up to and including its
/// terminating `;`. Used for unknown keywords inside PIN/MACRO bodies so
/// that we don't accidentally consume the closing `END` of the enclosing
/// block.
fn skip_to_semi(t: &mut Tokens<'_>) {
    while let Some(tok) = t.next_tok() {
        if tok == ";" {
            return;
        }
    }
}

/// Parse the body of a `PORT ... END` block. PORT contains a sequence of
/// LAYER/RECT/POLYGON/PATH statements, all terminated by `;`, followed by
/// a bare `END`.
fn parse_port(t: &mut Tokens<'_>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in PORT"))?;
        match tok {
            "END" => return Ok(()),
            ";" => { /* stray separator */ }
            // Everything inside PORT is a property statement terminated by ';'.
            _ => skip_to_semi(t),
        }
    }
}

/// Parse the body of a `PIN ... END <name>` block.
fn parse_pin(t: &mut Tokens<'_>, pname: &str) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in PIN"))?;
        match tok {
            "PORT" => parse_port(t)?,
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END label expected"))?;
                if lbl == pname {
                    return Ok(());
                }
                // Mismatched label — be lenient and keep going. (Real LEFs
                // shouldn't hit this; bail rather than spin forever.)
                return Err(t.err(format!(
                    "PIN END label mismatch: expected {pname}, got {lbl}"
                )));
            }
            ";" => { /* stray */ }
            // DIRECTION, USE, SHAPE, MUSTJOIN, TAPERRULE, NETEXPR,
            // ANTENNA*, SUPPLYSENSITIVITY, GROUNDSENSITIVITY, PROPERTY, ...
            _ => skip_to_semi(t),
        }
    }
}

/// Parse a MACRO body until "END <name>". Collect PIN names.
fn parse_macro(t: &mut Tokens<'_>, name: &str) -> Result<LefMacro> {
    let mut pins: Vec<String> = Vec::new();
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in MACRO"))?;
        match tok {
            "PIN" => {
                let pname = t
                    .next_tok()
                    .ok_or_else(|| t.err("PIN name expected"))?
                    .to_string();
                parse_pin(t, &pname)?;
                pins.push(pname);
            }
            "OBS" => {
                // OBS body looks just like a PORT body: LAYER/RECT/... ; END
                parse_port(t)?;
            }
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END label expected"))?;
                if lbl == name {
                    return Ok(LefMacro {
                        name: name.to_string(),
                        pins,
                    });
                }
                // Unexpected mismatched END — bail rather than risk an infinite loop.
                return Err(t.err(format!(
                    "MACRO END label mismatch: expected {name}, got {lbl}"
                )));
            }
            ";" => { /* stray */ }
            // CLASS, FOREIGN, ORIGIN, SIZE, SYMMETRY, SITE, PROPERTY, ...
            _ => skip_to_semi(t),
        }
    }
}

fn parse_layer_kind(t: &mut Tokens<'_>, name: &str) -> Result<String> {
    // The next "TYPE" attribute tells us what kind of layer this is.
    let mut kind = String::from("UNKNOWN");
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in LAYER"))?;
        match tok {
            "TYPE" => {
                let v = t.next_tok().ok_or_else(|| t.err("TYPE value"))?.to_string();
                kind = v;
                // consume up to ';'
                skip_to_semi(t);
            }
            "END" => {
                let lbl = t.next_tok().ok_or_else(|| t.err("END label expected"))?;
                if lbl == name {
                    return Ok(kind);
                }
                // Unknown nested END — bail rather than loop.
                return Err(t.err(format!(
                    "LAYER END label mismatch: expected {name}, got {lbl}"
                )));
            }
            ";" => {}
            // Skip every other property statement (WIDTH, SPACING, PITCH, ...).
            _ => skip_to_semi(t),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_simple_macro_with_port() {
        let src = "
MACRO foo
  CLASS CORE ;
  SIZE 1.0 BY 2.0 ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met1 ;
        RECT 0 0 1 1 ;
    END
  END A
END foo
END LIBRARY
";
        let lib = parse(src).expect("parse ok");
        assert_eq!(lib.macros.len(), 1);
        assert_eq!(lib.macros[0].name, "foo");
        assert_eq!(lib.macros[0].pins, vec!["A".to_string()]);
    }

    #[test]
    fn parse_pin_with_antenna_and_extra_props() {
        // Exercises the property-passthrough for ANTENNA*, SHAPE, MUSTJOIN,
        // TAPERRULE, NETEXPR, SUPPLYSENSITIVITY, GROUNDSENSITIVITY.
        let src = "
MACRO bar
  PIN VPWR
    DIRECTION INOUT ;
    USE POWER ;
    SHAPE ABUTMENT ;
    MUSTJOIN VGND ;
    TAPERRULE myrule ;
    NETEXPR \"power VDD\" ;
    SUPPLYSENSITIVITY VPWR ;
    GROUNDSENSITIVITY VGND ;
    ANTENNAGATEAREA 1.5 ;
    ANTENNADIFFAREA 2.0 ;
    PORT
      LAYER met1 ;
        RECT 0 0 1 1 ;
      LAYER met2 ;
        RECT 0 0 1 1 ;
    END
    PORT
      LAYER met3 ;
        RECT 2 2 3 3 ;
    END
  END VPWR
  OBS
    LAYER met1 ;
      RECT 5 5 6 6 ;
  END
END bar
";
        let lib = parse(src).expect("parse ok");
        assert_eq!(lib.macros.len(), 1);
        assert_eq!(lib.macros[0].pins, vec!["VPWR".to_string()]);
    }

    #[test]
    fn parse_multiple_macros_with_obs() {
        let src = "
MACRO a
  PIN P
    PORT
      LAYER met1 ;
        RECT 0 0 1 1 ;
    END
  END P
END a
MACRO b
  PIN Q
    PORT LAYER met2 ; RECT 0 0 1 1 ; END
  END Q
  OBS LAYER met1 ; RECT 0 0 5 5 ; END
END b
";
        let lib = parse(src).expect("parse ok");
        assert_eq!(lib.macros.len(), 2);
        assert_eq!(lib.macros[0].name, "a");
        assert_eq!(lib.macros[1].name, "b");
    }
}
