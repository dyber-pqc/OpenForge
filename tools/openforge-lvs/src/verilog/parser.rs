//! Hand-written tokeniser + parser for the gate-level Verilog subset.
//!
//! Tokenisation rules:
//!   * Whitespace separates tokens.
//!   * `//` line comments and `/* ... */` block comments are stripped.
//!   * The single-character punctuation `;`, `,`, `(`, `)`, `.`, `[`, `]`,
//!     `:`, `=` are emitted as their own tokens.
//!   * Everything else forms an identifier-or-number token.

use crate::error::{LvsError, Result};
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct VerilogModule {
    pub name: String,
    pub ports: Vec<String>,
    pub instances: Vec<Instance>,
}

#[derive(Debug, Clone)]
pub struct Instance {
    pub cell: String,
    pub name: String,
    /// pin_name -> net_name
    pub connections: HashMap<String, String>,
}

pub fn parse_verilog_file(path: impl AsRef<Path>) -> Result<VerilogModule> {
    let s = std::fs::read_to_string(path.as_ref())?;
    parse_verilog_str(&s)
}

pub fn parse_verilog_str(src: &str) -> Result<VerilogModule> {
    let toks = tokenize(src)?;
    let mut p = Parser { toks, pos: 0 };
    p.parse_module()
}

struct Parser {
    toks: Vec<Token>,
    pos: usize,
}

#[derive(Debug, Clone)]
struct Token {
    text: String,
    line: usize,
}

impl Parser {
    fn peek(&self) -> Option<&Token> {
        self.toks.get(self.pos)
    }
    fn bump(&mut self) -> Option<Token> {
        let t = self.toks.get(self.pos).cloned();
        if t.is_some() {
            self.pos += 1;
        }
        t
    }
    fn err(&self, msg: impl Into<String>) -> LvsError {
        let line = self.toks.get(self.pos).map(|t| t.line).unwrap_or(0);
        LvsError::Parse {
            line,
            msg: msg.into(),
        }
    }
    fn expect(&mut self, want: &str) -> Result<()> {
        match self.bump() {
            Some(t) if t.text == want => Ok(()),
            Some(t) => Err(LvsError::Parse {
                line: t.line,
                msg: format!("expected '{}', got '{}'", want, t.text),
            }),
            None => Err(self.err(format!("expected '{want}', got EOF"))),
        }
    }

    fn parse_module(&mut self) -> Result<VerilogModule> {
        // Skip until "module".
        loop {
            match self.bump() {
                Some(t) if t.text == "module" => break,
                Some(_) => continue,
                None => return Err(self.err("no 'module' keyword found")),
            }
        }
        let name = self
            .bump()
            .ok_or_else(|| self.err("expected module name"))?
            .text
            .clone();
        // Optional port list: ( a, b, c )
        let mut ports: Vec<String> = Vec::new();
        if let Some(t) = self.peek() {
            if t.text == "(" {
                self.bump();
                loop {
                    let nt = self
                        .bump()
                        .ok_or_else(|| self.err("EOF in module port list"))?
                        .clone();
                    match nt.text.as_str() {
                        ")" => break,
                        "," => continue,
                        _ => ports.push(nt.text.clone()),
                    }
                }
            }
        }
        self.expect(";")?;

        // Body: declarations + instances + endmodule.
        // Track bus widths so we can expand port buses into individual bits.
        let mut bus_widths: HashMap<String, (i64, i64)> = HashMap::new(); // name -> (hi, lo)
        let mut instances: Vec<Instance> = Vec::new();

        loop {
            let tok = match self.bump() {
                Some(t) => t.clone(),
                None => return Err(self.err("EOF before endmodule")),
            };
            match tok.text.as_str() {
                "endmodule" => break,
                "input" | "output" | "inout" | "wire" | "reg" => {
                    // Optional bus range, then comma-separated names, then ';'.
                    let range = self.try_parse_range()?;
                    loop {
                        let nm = self
                            .bump()
                            .ok_or_else(|| self.err("EOF in declaration"))?
                            .clone();
                        if nm.text == ";" {
                            break;
                        }
                        if nm.text == "," {
                            continue;
                        }
                        if let Some((hi, lo)) = range {
                            bus_widths.insert(nm.text.clone(), (hi, lo));
                        }
                    }
                }
                "assign" | "parameter" | "localparam" | "specify" | "endspecify" | "initial"
                | "always" | "generate" | "endgenerate" => {
                    // Skip until ';' (best-effort; gate-level Yosys output
                    // doesn't actually use these).
                    self.skip_to_semi();
                }
                ";" | "," => continue,
                "(" | ")" => continue,
                _ => {
                    // Likely an instance:  cell_type inst_name ( .pin(net), ... ) ;
                    // Be tolerant of escape-name `\<name> ` etc; our tokenizer
                    // already collapses these into a single token where possible.
                    let cell = tok.text.clone();
                    // Next must be the instance name, then '('.
                    let inst_name = self
                        .bump()
                        .ok_or_else(|| self.err("expected instance name"))?
                        .text
                        .clone();
                    // Optional parameter overrides #(.X(Y)) — skip.
                    if inst_name == "#" {
                        // skip '( ... )'
                        self.expect("(")?;
                        let mut depth = 1;
                        while depth > 0 {
                            let t = self.bump().ok_or_else(|| self.err("EOF in #()"))?;
                            match t.text.as_str() {
                                "(" => depth += 1,
                                ")" => depth -= 1,
                                _ => {}
                            }
                        }
                        // Now read real instance name.
                        let _real = self
                            .bump()
                            .ok_or_else(|| self.err("instance name after #()"))?;
                    }
                    self.expect("(")?;
                    let mut connections: HashMap<String, String> = HashMap::new();
                    loop {
                        let nt = self
                            .bump()
                            .ok_or_else(|| self.err("EOF in instance"))?
                            .clone();
                        match nt.text.as_str() {
                            ")" => break,
                            "," => continue,
                            "." => {
                                let pin = self
                                    .bump()
                                    .ok_or_else(|| self.err("expected pin name"))?
                                    .text
                                    .clone();
                                self.expect("(")?;
                                // Net expression: identifier, with optional [i] subscript,
                                // or a literal like 1'b0.
                                let net = self.parse_net_expr()?;
                                self.expect(")")?;
                                connections.insert(pin, net);
                            }
                            _ => {
                                // Positional connection, or stray junk; not
                                // supported for gate-level Yosys output, but
                                // tolerate by ignoring.
                            }
                        }
                    }
                    self.expect(";")?;
                    instances.push(Instance {
                        cell,
                        name: inst_name,
                        connections,
                    });
                }
            }
        }

        // Expand port buses.
        let mut expanded: Vec<String> = Vec::with_capacity(ports.len());
        for p in &ports {
            if let Some(&(hi, lo)) = bus_widths.get(p) {
                let (lo_i, hi_i) = if hi >= lo { (lo, hi) } else { (hi, lo) };
                for i in lo_i..=hi_i {
                    expanded.push(format!("{p}[{i}]"));
                }
            } else {
                expanded.push(p.clone());
            }
        }

        Ok(VerilogModule {
            name,
            ports: expanded,
            instances,
        })
    }

    fn try_parse_range(&mut self) -> Result<Option<(i64, i64)>> {
        if let Some(t) = self.peek() {
            if t.text == "[" {
                self.bump();
                let hi = self
                    .bump()
                    .ok_or_else(|| self.err("expected hi"))?
                    .text
                    .clone();
                self.expect(":")?;
                let lo = self
                    .bump()
                    .ok_or_else(|| self.err("expected lo"))?
                    .text
                    .clone();
                self.expect("]")?;
                let hi_i: i64 = hi
                    .parse()
                    .map_err(|_| self.err(format!("bad range hi: '{hi}'")))?;
                let lo_i: i64 = lo
                    .parse()
                    .map_err(|_| self.err(format!("bad range lo: '{lo}'")))?;
                return Ok(Some((hi_i, lo_i)));
            }
        }
        Ok(None)
    }

    /// Net expression: `id`, `id [ index ]`, `1'b0`, `1'b1`. Returns canonical name.
    fn parse_net_expr(&mut self) -> Result<String> {
        let first = self
            .bump()
            .ok_or_else(|| self.err("expected net expr"))?
            .clone();
        // Constants.
        if first.text == "1'b0" || first.text == "1'h0" {
            return Ok("__TIE0__".to_string());
        }
        if first.text == "1'b1" || first.text == "1'h1" {
            return Ok("__TIE1__".to_string());
        }
        // Possibly id[i]
        if let Some(t) = self.peek() {
            if t.text == "[" {
                self.bump();
                let idx = self
                    .bump()
                    .ok_or_else(|| self.err("expected bus index"))?
                    .text
                    .clone();
                // Could be id[hi:lo] — but for instance pins on gate-level
                // Yosys output, only single-bit selects are used.
                if let Some(nx) = self.peek() {
                    if nx.text == ":" {
                        // skip a slice expression
                        self.bump();
                        let _lo = self.bump();
                        self.expect("]")?;
                        return Ok(format!("{}[{}]", first.text, idx));
                    }
                }
                self.expect("]")?;
                return Ok(format!("{}[{}]", first.text, idx));
            }
        }
        Ok(first.text)
    }

    fn skip_to_semi(&mut self) {
        while let Some(t) = self.bump() {
            if t.text == ";" {
                return;
            }
        }
    }
}

/// Tokenize Verilog source.
fn tokenize(src: &str) -> Result<Vec<Token>> {
    let bytes = src.as_bytes();
    let mut out: Vec<Token> = Vec::new();
    let mut i = 0;
    let mut line = 1;
    while i < bytes.len() {
        let c = bytes[i];
        if c == b'\n' {
            line += 1;
            i += 1;
            continue;
        }
        if c.is_ascii_whitespace() {
            i += 1;
            continue;
        }
        // line comment
        if c == b'/' && i + 1 < bytes.len() && bytes[i + 1] == b'/' {
            while i < bytes.len() && bytes[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        // block comment
        if c == b'/' && i + 1 < bytes.len() && bytes[i + 1] == b'*' {
            i += 2;
            while i + 1 < bytes.len() && !(bytes[i] == b'*' && bytes[i + 1] == b'/') {
                if bytes[i] == b'\n' {
                    line += 1;
                }
                i += 1;
            }
            if i + 1 >= bytes.len() {
                return Err(LvsError::Parse {
                    line,
                    msg: "unterminated block comment".into(),
                });
            }
            i += 2;
            continue;
        }
        // single-char punctuation
        if matches!(
            c,
            b';' | b',' | b'(' | b')' | b'.' | b'[' | b']' | b':' | b'=' | b'#'
        ) {
            out.push(Token {
                text: (c as char).to_string(),
                line,
            });
            i += 1;
            continue;
        }
        // escaped name: \name<space>
        if c == b'\\' {
            i += 1;
            let start = i;
            while i < bytes.len() && !bytes[i].is_ascii_whitespace() {
                i += 1;
            }
            out.push(Token {
                text: format!("\\{}", &src[start..i]),
                line,
            });
            continue;
        }
        // quoted string (rare in netlists, but be safe)
        if c == b'"' {
            let start = i;
            i += 1;
            while i < bytes.len() && bytes[i] != b'"' {
                if bytes[i] == b'\n' {
                    line += 1;
                }
                i += 1;
            }
            i = (i + 1).min(bytes.len());
            out.push(Token {
                text: src[start..i].to_string(),
                line,
            });
            continue;
        }
        // identifier/number/literal: scan until whitespace or punctuation
        let start = i;
        while i < bytes.len() {
            let cc = bytes[i];
            if cc.is_ascii_whitespace() {
                break;
            }
            if matches!(
                cc,
                b';' | b',' | b'(' | b')' | b'.' | b'[' | b']' | b':' | b'=' | b'#'
            ) {
                break;
            }
            i += 1;
        }
        if i > start {
            out.push(Token {
                text: src[start..i].to_string(),
                line,
            });
        } else {
            // safety: don't infinite-loop on something weird
            i += 1;
        }
    }
    Ok(out)
}
