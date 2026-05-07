//! Tokenizer for the DRX (Ruby-subset) DSL.
//!
//! We tokenise into a small set of categories: identifiers, numbers (with
//! optional `.um` suffix), strings, symbols (`:foo`), and the punctuation
//! we care about (`.`, `,`, `(`, `)`, `=`, `:`). Newlines are preserved as
//! a `Newline` token because Ruby is line-significant in this subset.
//!
//! Ruby-specific quirks we handle:
//!   - `#` to end-of-line is a comment
//!   - Strings can be `"..."` or `'...'`
//!   - Keyword args appear as `name:` immediately followed by a value
//!     (we tokenise `name:` as Ident then Colon; the parser handles it)
//!   - Numbers may be followed by `.um`, `.nm`, `.mm` — we eat the unit and
//!     normalise to microns at lex time so the parser sees a plain f64.

use crate::{DrcError, Result};

#[derive(Debug, Clone, PartialEq)]
pub enum Tok {
    Ident(String),
    /// Already normalised to microns.
    Num(f64),
    Str(String),
    /// `:foo`
    Sym(String),
    Dot,
    Comma,
    LParen,
    RParen,
    LBrace,
    RBrace,
    LBracket,
    RBracket,
    Eq,
    Colon,
    Newline,
}

#[derive(Debug, Clone)]
pub struct Token {
    pub tok: Tok,
    pub line: usize,
}

pub fn tokenize(src: &str) -> Result<Vec<Token>> {
    let mut out = Vec::new();
    let mut line = 1usize;
    let bytes = src.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i] as char;
        // Comment.
        if c == '#' {
            while i < bytes.len() && bytes[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        if c == '\n' {
            // Collapse runs of blank lines into a single Newline.
            if !matches!(
                out.last(),
                Some(Token {
                    tok: Tok::Newline,
                    ..
                }) | None
            ) {
                out.push(Token {
                    tok: Tok::Newline,
                    line,
                });
            }
            line += 1;
            i += 1;
            continue;
        }
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        // Line-continuation backslash.
        if c == '\\' && i + 1 < bytes.len() && bytes[i + 1] == b'\n' {
            i += 2;
            line += 1;
            continue;
        }
        // String.
        if c == '"' || c == '\'' {
            let quote = bytes[i];
            i += 1;
            let start = i;
            while i < bytes.len() && bytes[i] != quote {
                if bytes[i] == b'\\' && i + 1 < bytes.len() {
                    i += 2;
                    continue;
                }
                if bytes[i] == b'\n' {
                    line += 1;
                }
                i += 1;
            }
            if i >= bytes.len() {
                return Err(DrcError::RuleParse(format!(
                    "line {line}: unterminated string"
                )));
            }
            let s = std::str::from_utf8(&bytes[start..i])
                .map_err(|e| DrcError::RuleParse(format!("line {line}: {e}")))?
                .to_string();
            i += 1;
            out.push(Token {
                tok: Tok::Str(s),
                line,
            });
            continue;
        }
        // Symbol :foo
        if c == ':' {
            // Could be a Ruby symbol, or just a `:` (e.g. inside hash).
            if i + 1 < bytes.len() && (bytes[i + 1] as char).is_alphabetic() {
                let start = i + 1;
                let mut j = start;
                while j < bytes.len() && is_ident_char(bytes[j] as char) {
                    j += 1;
                }
                let s = std::str::from_utf8(&bytes[start..j]).unwrap().to_string();
                out.push(Token {
                    tok: Tok::Sym(s),
                    line,
                });
                i = j;
                continue;
            } else {
                out.push(Token {
                    tok: Tok::Colon,
                    line,
                });
                i += 1;
                continue;
            }
        }
        if c.is_ascii_digit()
            || (c == '-' && i + 1 < bytes.len() && (bytes[i + 1] as char).is_ascii_digit())
        {
            let start = i;
            if c == '-' {
                i += 1;
            }
            while i < bytes.len() && ((bytes[i] as char).is_ascii_digit() || bytes[i] == b'.') {
                // Stop on `.` if followed by a unit suffix or non-digit (so
                // we don't eat the dot in `met1.width(0.14)` or `1.um`).
                if bytes[i] == b'.' {
                    if i + 1 >= bytes.len() {
                        break;
                    }
                    let nxt = bytes[i + 1] as char;
                    if !nxt.is_ascii_digit() {
                        break;
                    }
                }
                i += 1;
            }
            let num_str = std::str::from_utf8(&bytes[start..i]).unwrap();
            let mut value: f64 = num_str
                .parse()
                .map_err(|_| DrcError::RuleParse(format!("line {line}: bad number '{num_str}'")))?;
            // Optional unit: `.um`, `.nm`, `.mm`. `.um` is the canonical sky130
            // form (`1.um`, `100.um`). Bare numbers also default to microns.
            if i < bytes.len() && bytes[i] == b'.' {
                let suffix_start = i + 1;
                let mut j = suffix_start;
                while j < bytes.len() && (bytes[j] as char).is_alphabetic() {
                    j += 1;
                }
                let suf = std::str::from_utf8(&bytes[suffix_start..j]).unwrap();
                match suf {
                    "um" => {
                        i = j;
                    }
                    "nm" => {
                        value *= 1e-3;
                        i = j;
                    }
                    "mm" => {
                        value *= 1e3;
                        i = j;
                    }
                    "" => {
                        // dangling `.` — leave it for the parser as Dot
                    }
                    _ => {
                        // unknown suffix — leave the dot alone
                    }
                }
            }
            out.push(Token {
                tok: Tok::Num(value),
                line,
            });
            continue;
        }
        if is_ident_start(c) {
            let start = i;
            while i < bytes.len() && is_ident_char(bytes[i] as char) {
                i += 1;
            }
            // A trailing `?` or `!` is a valid Ruby method-name char.
            if i < bytes.len() && (bytes[i] == b'?' || bytes[i] == b'!') {
                i += 1;
            }
            let s = std::str::from_utf8(&bytes[start..i]).unwrap().to_string();
            out.push(Token {
                tok: Tok::Ident(s),
                line,
            });
            continue;
        }
        let single = match c {
            '.' => Tok::Dot,
            ',' => Tok::Comma,
            '(' => Tok::LParen,
            ')' => Tok::RParen,
            '{' => Tok::LBrace,
            '}' => Tok::RBrace,
            '[' => Tok::LBracket,
            ']' => Tok::RBracket,
            '=' => {
                // Eat `==`, `=>` as a single Eq for our subset (treat both as
                // assignment-ish; we don't really use them, the parser will
                // skip if it doesn't fit).
                if i + 1 < bytes.len() && (bytes[i + 1] == b'=' || bytes[i + 1] == b'>') {
                    i += 2;
                    out.push(Token { tok: Tok::Eq, line });
                    continue;
                }
                Tok::Eq
            }
            ';' => {
                // Treat `;` like a newline.
                if !matches!(
                    out.last(),
                    Some(Token {
                        tok: Tok::Newline,
                        ..
                    }) | None
                ) {
                    out.push(Token {
                        tok: Tok::Newline,
                        line,
                    });
                }
                i += 1;
                continue;
            }
            _ => {
                return Err(DrcError::RuleParse(format!(
                    "line {line}: unexpected char {c:?}"
                )));
            }
        };
        out.push(Token { tok: single, line });
        i += 1;
    }
    // Trailing newline so parser doesn't have to special-case EOF.
    if !matches!(
        out.last(),
        Some(Token {
            tok: Tok::Newline,
            ..
        }) | None
    ) {
        out.push(Token {
            tok: Tok::Newline,
            line,
        });
    }
    Ok(out)
}

fn is_ident_start(c: char) -> bool {
    c.is_alphabetic() || c == '_'
}

fn is_ident_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

#[cfg(test)]
mod tests {
    use super::*;

    fn toks(src: &str) -> Vec<Tok> {
        tokenize(src).unwrap().into_iter().map(|t| t.tok).collect()
    }

    #[test]
    fn simple_input() {
        let t = toks("met1 = input(68, 20)\n");
        assert!(matches!(t[0], Tok::Ident(ref s) if s == "met1"));
        assert!(matches!(t[1], Tok::Eq));
        assert!(matches!(t[2], Tok::Ident(ref s) if s == "input"));
        assert!(matches!(t[3], Tok::LParen));
        assert!(matches!(t[4], Tok::Num(n) if (n - 68.0).abs() < 1e-9));
    }

    #[test]
    fn um_suffix() {
        let t = toks("100.um");
        assert!(matches!(t[0], Tok::Num(n) if (n - 100.0).abs() < 1e-9));
    }

    #[test]
    fn nm_suffix() {
        let t = toks("500.nm");
        // 500 nm = 0.5 um
        assert!(matches!(t[0], Tok::Num(n) if (n - 0.5).abs() < 1e-9));
    }

    #[test]
    fn comments_and_strings() {
        let t = toks("# hi\nreport(\"sky130A DRC\")\n");
        assert!(matches!(t[0], Tok::Ident(ref s) if s == "report"));
        assert!(matches!(t[1], Tok::LParen));
        assert!(matches!(t[2], Tok::Str(ref s) if s == "sky130A DRC"));
    }

    #[test]
    fn method_chain() {
        let t = toks("li1.width(0.17)");
        assert!(matches!(t[0], Tok::Ident(_)));
        assert!(matches!(t[1], Tok::Dot));
        assert!(matches!(t[2], Tok::Ident(ref s) if s == "width"));
    }
}
