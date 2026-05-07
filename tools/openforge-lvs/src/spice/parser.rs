//! Minimal line-oriented SPICE parser sufficient for LVS v0.1.
//!
//! Supports:
//!   - `.subckt NAME port1 port2 ...`
//!   - `.ends [NAME]`
//!   - `Mxxx d g s b model w=.. l=.. ...`
//!   - `Rxxx n1 n2 value`
//!   - `Cxxx n1 n2 value`
//!   - `Xxxx n1 n2 ... subckt_name [params]`
//!   - `*` line comments and `;` inline comments
//!   - `+` continuation lines
//!
//! This is intentionally tolerant: unrecognized cards are skipped with a warning.

use super::ast::{Device, Netlist, Subckt};
use crate::error::{LvsError, Result};
use std::collections::HashMap;

/// Parse a numeric value with SPICE engineering suffix (e.g. "1k", "2.3u", "5meg").
fn parse_spice_number(s: &str) -> Option<f64> {
    let s = s.trim().to_ascii_lowercase();
    if s.is_empty() {
        return None;
    }
    // Greedily peel off trailing alpha suffix.
    let split = s.find(|c: char| c.is_ascii_alphabetic()).unwrap_or(s.len());
    let (num_part, suffix) = s.split_at(split);
    let base: f64 = num_part.parse().ok()?;
    let mult = match suffix {
        "" => 1.0,
        "f" => 1e-15,
        "p" => 1e-12,
        "n" => 1e-9,
        "u" => 1e-6,
        "m" => 1e-3,
        "k" => 1e3,
        "meg" => 1e6,
        "g" => 1e9,
        "t" => 1e12,
        _ => return None,
    };
    Some(base * mult)
}

/// Strip comments and join `+` continuation lines.
fn preprocess(src: &str) -> Vec<(usize, String)> {
    let mut out: Vec<(usize, String)> = Vec::new();
    for (idx, raw) in src.lines().enumerate() {
        let lineno = idx + 1;
        // Drop inline `;` comments.
        let line = match raw.find(';') {
            Some(i) => &raw[..i],
            None => raw,
        };
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            continue;
        }
        // Full-line comment.
        if trimmed.trim_start().starts_with('*') {
            continue;
        }
        if let Some(rest) = trimmed.trim_start().strip_prefix('+') {
            // Continuation: append to the previous logical line.
            if let Some(last) = out.last_mut() {
                last.1.push(' ');
                last.1.push_str(rest.trim());
                continue;
            }
        }
        out.push((lineno, trimmed.trim().to_string()));
    }
    out
}

fn tokenize(line: &str) -> Vec<String> {
    line.split_whitespace().map(|s| s.to_string()).collect()
}

/// Split `key=value` token; otherwise return None.
fn kv(tok: &str) -> Option<(String, String)> {
    let eq = tok.find('=')?;
    Some((tok[..eq].to_ascii_lowercase(), tok[eq + 1..].to_string()))
}

fn parse_mosfet(lineno: usize, toks: &[String]) -> Result<Device> {
    // M<name> d g s b model [params...]
    if toks.len() < 6 {
        return Err(LvsError::Parse {
            line: lineno,
            msg: format!("MOSFET line needs at least 6 tokens, got {}", toks.len()),
        });
    }
    let name = toks[0].clone();
    let drain = toks[1].clone();
    let gate = toks[2].clone();
    let source = toks[3].clone();
    let body = toks[4].clone();
    let model = toks[5].clone();
    let mut params = HashMap::new();
    for t in &toks[6..] {
        if let Some((k, v)) = kv(t) {
            params.insert(k, v);
        }
    }
    Ok(Device::Mosfet {
        name,
        drain,
        gate,
        source,
        body,
        model,
        params,
    })
}

fn parse_passive_r(lineno: usize, toks: &[String]) -> Result<Device> {
    if toks.len() < 4 {
        return Err(LvsError::Parse {
            line: lineno,
            msg: "Resistor needs name n1 n2 value".into(),
        });
    }
    let value_ohm = parse_spice_number(&toks[3]).ok_or_else(|| LvsError::Parse {
        line: lineno,
        msg: format!("bad resistor value '{}'", toks[3]),
    })?;
    Ok(Device::Resistor {
        name: toks[0].clone(),
        n1: toks[1].clone(),
        n2: toks[2].clone(),
        value_ohm,
    })
}

fn parse_passive_c(lineno: usize, toks: &[String]) -> Result<Device> {
    if toks.len() < 4 {
        return Err(LvsError::Parse {
            line: lineno,
            msg: "Capacitor needs name n1 n2 value".into(),
        });
    }
    let value_f = parse_spice_number(&toks[3]).ok_or_else(|| LvsError::Parse {
        line: lineno,
        msg: format!("bad capacitor value '{}'", toks[3]),
    })?;
    Ok(Device::Capacitor {
        name: toks[0].clone(),
        n1: toks[1].clone(),
        n2: toks[2].clone(),
        value_f,
    })
}

fn parse_subckt_inst(lineno: usize, toks: &[String]) -> Result<Device> {
    // Xname n1 n2 ... subckt_name [k=v...]
    if toks.len() < 3 {
        return Err(LvsError::Parse {
            line: lineno,
            msg: "Subckt instance needs name nodes... subckt".into(),
        });
    }
    let name = toks[0].clone();
    // Split params off the tail.
    let mut params = HashMap::new();
    let mut last_node = toks.len();
    for (i, t) in toks.iter().enumerate().skip(1) {
        if t.contains('=') {
            last_node = i;
            break;
        }
    }
    for t in &toks[last_node..] {
        if let Some((k, v)) = kv(t) {
            params.insert(k, v);
        }
    }
    if last_node < 3 {
        return Err(LvsError::Parse {
            line: lineno,
            msg: "Subckt instance has no nodes/subckt name".into(),
        });
    }
    let subckt = toks[last_node - 1].clone();
    let nodes = toks[1..last_node - 1].to_vec();
    Ok(Device::SubcktInst {
        name,
        nodes,
        subckt,
        params,
    })
}

fn parse_device(lineno: usize, toks: &[String]) -> Result<Option<Device>> {
    let head = &toks[0];
    let prefix = head.chars().next().unwrap_or(' ').to_ascii_uppercase();
    Ok(Some(match prefix {
        'M' => parse_mosfet(lineno, toks)?,
        'R' => parse_passive_r(lineno, toks)?,
        'C' => parse_passive_c(lineno, toks)?,
        'X' => parse_subckt_inst(lineno, toks)?,
        _ => return Ok(None), // Skip unsupported devices silently.
    }))
}

pub fn parse_netlist(src: &str) -> Result<Netlist> {
    let lines = preprocess(src);
    let mut library: HashMap<String, Subckt> = HashMap::new();
    let mut top = Subckt {
        name: "__toplevel__".into(),
        ..Default::default()
    };

    let mut stack: Vec<Subckt> = Vec::new();

    for (lineno, line) in lines {
        let toks = tokenize(&line);
        if toks.is_empty() {
            continue;
        }
        let head = toks[0].to_ascii_lowercase();

        if head == ".subckt" {
            if toks.len() < 2 {
                return Err(LvsError::Parse {
                    line: lineno,
                    msg: ".subckt missing name".into(),
                });
            }
            let mut sc = Subckt {
                name: toks[1].clone(),
                ..Default::default()
            };
            // Ports = remaining tokens that don't contain '='.
            for t in &toks[2..] {
                if t.contains('=') {
                    break;
                }
                sc.ports.push(t.clone());
            }
            stack.push(sc);
            continue;
        }
        if head == ".ends" {
            let sc = stack.pop().ok_or_else(|| LvsError::Parse {
                line: lineno,
                msg: ".ends without matching .subckt".into(),
            })?;
            if let Some(parent) = stack.last_mut() {
                parent.subckts.push(sc.clone());
            }
            library.insert(sc.name.clone(), sc);
            continue;
        }
        if head.starts_with('.') {
            // Skip other directives (.model, .global, .end, .include, etc.)
            continue;
        }

        let dev_opt = parse_device(lineno, &toks)?;
        if let Some(dev) = dev_opt {
            if let Some(parent) = stack.last_mut() {
                parent.devices.push(dev);
            } else {
                top.devices.push(dev);
            }
        }
    }

    if !stack.is_empty() {
        return Err(LvsError::Parse {
            line: 0,
            msg: format!(
                "Unterminated .subckt blocks: {:?}",
                stack.iter().map(|s| &s.name).collect::<Vec<_>>()
            ),
        });
    }

    Ok(Netlist { top, library })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_inverter() {
        let src = r#"
.subckt inverter in out vdd vss
M1 out in vss vss nmos_rvt w=0.42 l=0.15
M2 out in vdd vdd pmos_rvt w=0.84 l=0.15
.ends inverter
"#;
        let nl = parse_netlist(src).unwrap();
        let inv = nl.library.get("inverter").unwrap();
        assert_eq!(inv.ports, vec!["in", "out", "vdd", "vss"]);
        assert_eq!(inv.devices.len(), 2);
    }

    #[test]
    fn parses_resistor_value() {
        let approx = |a: Option<f64>, b: f64| (a.unwrap() - b).abs() < 1e-18;
        assert!(approx(parse_spice_number("1k"), 1e3));
        assert!(approx(parse_spice_number("2.5u"), 2.5e-6));
        assert!(approx(parse_spice_number("3meg"), 3e6));
    }
}
