//! KLayout-DRX-subset rule deck parser.
//!
//! Grammar (line-oriented; `#` introduces a comment):
//!
//! ```text
//! LAYER <name> = <gds_layer> [ / <datatype> ]
//! RULE  <name> : <layer>.width  < <um>          [= "<message>"]
//! RULE  <name> : <layer>.space  < <um>          [= "<message>"]
//! RULE  <name> : <inner>.enclosed_by(<outer>) < <um> [= "<message>"]
//! RULE  <name> : <a>.not(<b>) -> <result>             [= "<message>"]
//! ```
//!
//! Parsed by hand — `nom` is in the dep tree for future extensions but the
//! grammar is small enough that a hand-rolled scan is clearer here.

use crate::rules::ast::{DensityDirection, LayerSpec, Rule, RuleDeck};
use crate::{DrcError, Result};

pub fn parse_deck(input: &str) -> Result<RuleDeck> {
    let mut deck = RuleDeck {
        name: String::from("deck"),
        ..Default::default()
    };

    for (lineno, raw) in input.lines().enumerate() {
        let line = strip_comment(raw).trim();
        if line.is_empty() {
            continue;
        }
        if let Some(rest) = line.strip_prefix("LAYER ") {
            let (name, spec) = parse_layer(rest)
                .map_err(|e| DrcError::RuleParse(format!("line {}: {}", lineno + 1, e)))?;
            deck.layers.insert(name, spec);
        } else if let Some(rest) = line.strip_prefix("RULE ") {
            let rule = parse_rule(rest)
                .map_err(|e| DrcError::RuleParse(format!("line {}: {}", lineno + 1, e)))?;
            deck.rules.push(rule);
        } else if let Some(rest) = line.strip_prefix("DECK ") {
            deck.name = rest.trim().trim_matches('"').to_string();
        } else {
            return Err(DrcError::RuleParse(format!(
                "line {}: unrecognized statement: {}",
                lineno + 1,
                line
            )));
        }
    }

    Ok(deck)
}

fn strip_comment(s: &str) -> &str {
    match s.find('#') {
        Some(i) => &s[..i],
        None => s,
    }
}

/// Parse "name = 68" or "name = 68 / 0".
fn parse_layer(s: &str) -> std::result::Result<(String, LayerSpec), String> {
    let (name, rhs) = s
        .split_once('=')
        .ok_or_else(|| "expected '=' in LAYER".to_string())?;
    let name = name.trim().to_string();
    let rhs = rhs.trim();
    let (layer_s, datatype_s) = match rhs.split_once('/') {
        Some((a, b)) => (a.trim(), b.trim()),
        None => (rhs, "0"),
    };
    let layer: u16 = layer_s
        .parse()
        .map_err(|_| format!("invalid layer number: {layer_s}"))?;
    let datatype: u16 = datatype_s
        .parse()
        .map_err(|_| format!("invalid datatype: {datatype_s}"))?;
    Ok((name, LayerSpec { layer, datatype }))
}

/// Parse the body of a RULE statement (everything after "RULE ").
fn parse_rule(s: &str) -> std::result::Result<Rule, String> {
    // <name> : <body> [= "<message>"]
    let (name_part, rest) = s
        .split_once(':')
        .ok_or_else(|| "expected ':' after rule name".to_string())?;
    let name = name_part.trim().to_string();

    let (body, message) = match rest.split_once('=') {
        Some((b, m)) => {
            let m = m.trim().trim_matches('"').to_string();
            (b.trim(), m)
        }
        None => (rest.trim(), String::new()),
    };

    // density:  <layer>.density window <um> [<|>] <pct>
    if let Some((layer, tail)) = body.split_once(".density") {
        let layer = layer.trim().to_string();
        let tail = tail.trim();
        // Expect: "window <num>" then operator then number.
        let rest = tail
            .strip_prefix("window")
            .ok_or_else(|| "expected 'window' after .density".to_string())?
            .trim();
        // Find operator '<' or '>'. We can't reuse parse_lt_value because
        // we also need to support '>'.
        let (window_str, op_idx, op) = {
            let mut idx = None;
            let mut op_ch = '<';
            for (i, c) in rest.char_indices() {
                if c == '<' || c == '>' {
                    idx = Some(i);
                    op_ch = c;
                    break;
                }
            }
            let i = idx.ok_or_else(|| "expected '<' or '>' in density rule".to_string())?;
            (rest[..i].trim().to_string(), i, op_ch)
        };
        let window_um: f64 = window_str
            .parse()
            .map_err(|_| format!("invalid density window: {window_str}"))?;
        let pct_str = rest[op_idx + 1..].trim();
        let pct: f64 = pct_str
            .parse()
            .map_err(|_| format!("invalid density threshold: {pct_str}"))?;
        let direction = if op == '<' {
            DensityDirection::Below
        } else {
            DensityDirection::Above
        };
        let msg = if message.is_empty() {
            format!("{layer} density violation")
        } else {
            message
        };
        return Ok(Rule::Density {
            layer,
            window_um,
            pct,
            direction,
            name,
            message: msg,
        });
    }

    // width / space:   <layer>.width < <um>     (or .space)
    if let Some((layer, tail)) = body.split_once(".width") {
        let min_um = parse_lt_value(tail)?;
        let msg = if message.is_empty() {
            format!("{} minimum width violation", layer.trim())
        } else {
            message
        };
        return Ok(Rule::Width {
            layer: layer.trim().to_string(),
            min_um,
            name,
            message: msg,
        });
    }
    if let Some((layer, tail)) = body.split_once(".space") {
        let min_um = parse_lt_value(tail)?;
        let msg = if message.is_empty() {
            format!("{} minimum spacing violation", layer.trim())
        } else {
            message
        };
        return Ok(Rule::Space {
            layer: layer.trim().to_string(),
            min_um,
            name,
            message: msg,
            intra_layer: true,
        });
    }
    // enclosure:  <inner>.enclosed_by(<outer>) < <um>
    if let Some((inner, tail)) = body.split_once(".enclosed_by(") {
        let (outer, tail) = tail
            .split_once(')')
            .ok_or_else(|| "missing ')' in enclosed_by".to_string())?;
        let min_um = parse_lt_value(tail)?;
        let msg = if message.is_empty() {
            format!("{} not enclosed by {}", inner.trim(), outer.trim())
        } else {
            message
        };
        return Ok(Rule::Enclosure {
            inner: inner.trim().to_string(),
            outer: outer.trim().to_string(),
            min_um,
            name,
            message: msg,
        });
    }
    // not: <a>.not(<b>) -> <result>
    if let Some((a, tail)) = body.split_once(".not(") {
        let (b, tail) = tail
            .split_once(')')
            .ok_or_else(|| "missing ')' in not()".to_string())?;
        let result = tail
            .split_once("->")
            .map(|(_, r)| r.trim().to_string())
            .unwrap_or_else(|| format!("{}_not_{}", a.trim(), b.trim()));
        let msg = if message.is_empty() {
            format!("{} not {}", a.trim(), b.trim())
        } else {
            message
        };
        return Ok(Rule::Not {
            a: a.trim().to_string(),
            b: b.trim().to_string(),
            result,
            name,
            message: msg,
        });
    }
    Err(format!("unrecognized rule body: {body}"))
}

/// Parse "< 0.14" or "<0.14" -> 0.14
fn parse_lt_value(s: &str) -> std::result::Result<f64, String> {
    let s = s.trim();
    let s = s
        .strip_prefix('<')
        .ok_or_else(|| format!("expected '<' before threshold, got: {s}"))?
        .trim();
    s.parse::<f64>()
        .map_err(|_| format!("invalid threshold: {s}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_simple_deck() {
        let src = r#"
            # Comment
            LAYER met1 = 68
            LAYER li1 = 67 / 0
            RULE met1.W.1 : met1.width < 0.14 = "M1 width"
            RULE met1.S.1 : met1.space < 0.14
        "#;
        let deck = parse_deck(src).unwrap();
        assert_eq!(deck.layers.len(), 2);
        assert_eq!(deck.rules.len(), 2);
        assert_eq!(deck.layers["met1"].layer, 68);
        match &deck.rules[0] {
            Rule::Width { min_um, layer, .. } => {
                assert!((*min_um - 0.14).abs() < 1e-9);
                assert_eq!(layer, "met1");
            }
            _ => panic!("expected width"),
        }
    }

    #[test]
    fn rejects_unknown_statement() {
        assert!(parse_deck("FOO bar").is_err());
    }
}
