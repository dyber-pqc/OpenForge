//! DEF parser — handwritten, token-stream based. Implements the subset of DEF
//! needed for parasitic extraction: DESIGN, UNITS, DIEAREA, COMPONENTS, NETS
//! (with ROUTED segments). Sufficient for OpenROAD-emitted routed DEFs.

use super::ast::{Component, Def, Net, RoutePoint, RouteSeg};
use crate::error::{Result, XrcError};

/// Stream of whitespace-separated tokens, with line tracking for diagnostics.
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
        // skip whitespace + comments
        while self.pos < self.src.len() {
            let c = self.src.as_bytes()[self.pos];
            if c == b'\n' {
                self.line += 1;
                self.pos += 1;
            } else if c.is_ascii_whitespace() {
                self.pos += 1;
            } else if c == b'#' {
                // Line comment.
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
        while self.pos < self.src.len() {
            let c = self.src.as_bytes()[self.pos];
            if c.is_ascii_whitespace() {
                break;
            }
            self.pos += 1;
        }
        Some(&self.src[start..self.pos])
    }

    fn expect(&mut self, want: &str) -> Result<()> {
        match self.next_tok() {
            Some(t) if t == want => Ok(()),
            Some(t) => Err(XrcError::DefParse {
                line: self.line,
                msg: format!("expected '{want}', got '{t}'"),
            }),
            None => Err(XrcError::DefParse {
                line: self.line,
                msg: format!("expected '{want}', got EOF"),
            }),
        }
    }

    fn err(&self, msg: impl Into<String>) -> XrcError {
        XrcError::DefParse {
            line: self.line,
            msg: msg.into(),
        }
    }
}

/// Parse a full DEF source string.
pub fn parse(src: &str) -> Result<Def> {
    let mut t = Tokens::new(src);
    let mut design = String::new();
    let mut units_per_micron = 1000.0_f64;
    let mut die_area = ((0_i64, 0_i64), (0_i64, 0_i64));
    let mut components: Vec<Component> = Vec::new();
    let mut nets: Vec<Net> = Vec::new();

    while let Some(tok) = t.next_tok() {
        match tok {
            // Single-line statements (terminated by `;`):
            "VERSION" | "DIVIDERCHAR" | "BUSBITCHARS" | "NAMESCASESENSITIVE" | "ROW" | "TRACKS"
            | "GCELLGRID" => {
                skip_to_semi(&mut t)?;
            }
            // Multi-line sections (have a count, then content, then `END <name>`):
            "PROPERTYDEFINITIONS"
            | "VIAS"
            | "PINS"
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
                design = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected design name"))?
                    .to_string();
                skip_to_semi(&mut t)?;
            }
            "UNITS" => {
                t.expect("DISTANCE")?;
                t.expect("MICRONS")?;
                let n = t.next_tok().ok_or_else(|| t.err("expected units number"))?;
                units_per_micron = n
                    .parse::<f64>()
                    .map_err(|_| t.err(format!("bad units number: {n}")))?;
                skip_to_semi(&mut t)?;
            }
            "DIEAREA" => {
                die_area = parse_diearea(&mut t)?;
            }
            "COMPONENTS" => {
                let _count = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected component count"))?;
                skip_to_semi(&mut t)?;
                parse_components(&mut t, &mut components)?;
            }
            "NETS" => {
                let _count = t.next_tok().ok_or_else(|| t.err("expected net count"))?;
                skip_to_semi(&mut t)?;
                parse_nets(&mut t, &mut nets)?;
            }
            "END" => {
                // Could be END DESIGN, or end-of-section sentinel we already handled.
                let _ = t.next_tok(); // consume label (e.g. DESIGN)
                if !components.is_empty() || !nets.is_empty() || !design.is_empty() {
                    break;
                }
            }
            _ => {
                // Unknown top-level keyword: skip to next ';' to be tolerant.
                skip_to_semi(&mut t).ok();
            }
        }
    }

    Ok(Def {
        design,
        units_per_micron,
        die_area,
        components,
        nets,
    })
}

fn skip_to_semi(t: &mut Tokens<'_>) -> Result<()> {
    while let Some(tok) = t.next_tok() {
        if tok == ";" {
            return Ok(());
        }
    }
    Err(t.err("unexpected EOF before ';'"))
}

/// Skip generic section: read until "END <name>".
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

fn parse_diearea(t: &mut Tokens<'_>) -> Result<((i64, i64), (i64, i64))> {
    let mut pts: Vec<(i64, i64)> = Vec::new();
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in DIEAREA"))?;
        match tok {
            "(" => {
                let x = read_int(t)?;
                let y = read_int(t)?;
                t.expect(")")?;
                pts.push((x, y));
            }
            ";" => break,
            _ => return Err(t.err(format!("unexpected '{tok}' in DIEAREA"))),
        }
    }
    if pts.len() < 2 {
        return Err(t.err("DIEAREA needs ≥2 points"));
    }
    let xmin = pts.iter().map(|p| p.0).min().unwrap();
    let ymin = pts.iter().map(|p| p.1).min().unwrap();
    let xmax = pts.iter().map(|p| p.0).max().unwrap();
    let ymax = pts.iter().map(|p| p.1).max().unwrap();
    Ok(((xmin, ymin), (xmax, ymax)))
}

fn read_int(t: &mut Tokens<'_>) -> Result<i64> {
    let s = t.next_tok().ok_or_else(|| t.err("expected integer"))?;
    // Some DEFs use '*' as "previous coordinate" — caller handles that;
    // here we only accept plain integers.
    s.parse::<i64>()
        .map_err(|_| t.err(format!("bad integer: '{s}'")))
}

fn parse_components(t: &mut Tokens<'_>, comps: &mut Vec<Component>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in COMPONENTS"))?;
        match tok {
            "END" => {
                let _ = t.next_tok(); // "COMPONENTS"
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
                let mut placement: Option<(i64, i64)> = None;
                let mut orient = String::from("N");
                loop {
                    let nt = t.next_tok().ok_or_else(|| t.err("EOF in component"))?;
                    if nt == ";" {
                        break;
                    }
                    if nt == "+" {
                        let kw = t
                            .next_tok()
                            .ok_or_else(|| t.err("expected keyword after '+'"))?;
                        match kw {
                            "PLACED" | "FIXED" | "COVER" => {
                                t.expect("(")?;
                                let x = read_int(t)?;
                                let y = read_int(t)?;
                                t.expect(")")?;
                                let o = t.next_tok().ok_or_else(|| t.err("expected orient"))?;
                                placement = Some((x, y));
                                orient = o.to_string();
                            }
                            _ => {
                                // Skip remainder of this '+' clause until next '+' or ';'.
                                // Best-effort: do nothing, loop continues consuming tokens.
                            }
                        }
                    }
                }
                comps.push(Component {
                    name,
                    macro_name,
                    placement,
                    orient,
                });
            }
            _ => return Err(t.err(format!("unexpected '{tok}' in COMPONENTS"))),
        }
    }
}

fn parse_nets(t: &mut Tokens<'_>, nets: &mut Vec<Net>) -> Result<()> {
    loop {
        let tok = t.next_tok().ok_or_else(|| t.err("EOF in NETS"))?;
        match tok {
            "END" => {
                let _ = t.next_tok(); // "NETS"
                return Ok(());
            }
            "-" => {
                let name = t
                    .next_tok()
                    .ok_or_else(|| t.err("expected net name"))?
                    .to_string();
                let mut connections: Vec<(String, String)> = Vec::new();
                let mut routes: Vec<RouteSeg> = Vec::new();
                // Connection list: ( inst pin ) ( inst pin ) ...
                // until we hit a '+' or ';'.
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
                        // Optional + SYNTHESIZED etc inside paren — read until ')'
                        loop {
                            let pt = t.next_tok().ok_or_else(|| t.err("EOF in conn"))?;
                            if pt == ")" {
                                break;
                            }
                        }
                        connections.push((inst, pin));
                    } else if nt == "+" {
                        let kw = t.next_tok().ok_or_else(|| t.err("expected '+' keyword"))?;
                        match kw {
                            "ROUTED" | "NEW" => {
                                let seg = parse_routed(t)?;
                                routes.push(seg);
                                // After parse_routed, last token consumed was the segment
                                // terminator (';' or another '+' marker); handle below.
                                // But our parse_routed stops *before* the trailing semicolon
                                // or '+' so the outer loop continues correctly.
                            }
                            "USE" | "SOURCE" | "WEIGHT" | "NONDEFAULTRULE" | "FIXED" | "COVER"
                            | "SHIELDNET" | "PROPERTY" | "XTALK" | "PATTERN" => {
                                // Skip the remainder of this '+' clause until the next
                                // '+' or ';'.  Most just take one token.
                                let _ = t.next_tok();
                            }
                            _ => {}
                        }
                    }
                }
                nets.push(Net {
                    name,
                    connections,
                    routes,
                });
            }
            _ => return Err(t.err(format!("unexpected '{tok}' in NETS"))),
        }
    }
}

/// Parse a ROUTED / NEW path. DEF syntax:
///   ROUTED <layer> ( x y [ext] ) [ ( x y ) | ( * y ) | ( x * ) | <viaName> ]*
///
/// The path can be punctuated by via names (no parens) which place a via at
/// the most recent point. We stop when we encounter a token that starts a new
/// statement: '+', ';' or end of stream — and we *push that token back* by
/// rewinding the cursor.
fn parse_routed(t: &mut Tokens<'_>) -> Result<RouteSeg> {
    let layer = t
        .next_tok()
        .ok_or_else(|| t.err("expected layer in ROUTED"))?
        .to_string();
    let mut points: Vec<RoutePoint> = Vec::new();
    let mut last_x: i64 = 0;
    let mut last_y: i64 = 0;

    loop {
        // Snapshot position so we can rewind on a stop token.
        let saved_pos = t.pos;
        let saved_line = t.line;
        let nt = match t.next_tok() {
            Some(s) => s,
            None => break,
        };
        match nt {
            "(" => {
                let xs = t.next_tok().ok_or_else(|| t.err("expected x"))?;
                let ys = t.next_tok().ok_or_else(|| t.err("expected y"))?;
                let x = if xs == "*" {
                    last_x
                } else {
                    xs.parse::<i64>()
                        .map_err(|_| t.err(format!("bad x: '{xs}'")))?
                };
                let y = if ys == "*" {
                    last_y
                } else {
                    ys.parse::<i64>()
                        .map_err(|_| t.err(format!("bad y: '{ys}'")))?
                };
                // Optional extension value (integer) before ')'.
                loop {
                    let ext = t.next_tok().ok_or_else(|| t.err("EOF in route point"))?;
                    if ext == ")" {
                        break;
                    }
                    // ignore extension and any other tokens inside parens
                }
                last_x = x;
                last_y = y;
                points.push(RoutePoint { x, y, via: None });
            }
            "+" | ";" => {
                // End of this routed segment — rewind so the caller sees the token.
                t.pos = saved_pos;
                t.line = saved_line;
                break;
            }
            "TAPER" | "TAPERRULE" => {
                // Non-default rule indicator (or `TAPERRULE <rule_name>`).
                // The latter takes a rule-name argument we just discard.
                if nt == "TAPERRULE" {
                    let _ = t.next_tok();
                }
            }
            "MASK" | "RECT" | "VIRTUAL" => {
                // Layer/shape qualifiers we don't need for parasitics.
                let _ = t.next_tok();
            }
            other => {
                // A bare token here is a via name placed at the last point.
                if let Some(p) = points.last_mut() {
                    p.via = Some(other.to_string());
                } else {
                    return Err(t.err(format!("unexpected token '{other}' in ROUTED")));
                }
            }
        }
    }

    Ok(RouteSeg { layer, points })
}
