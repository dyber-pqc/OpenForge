//! Graph normalization passes.
//!
//! Normalization runs at the [`Subckt`](crate::spice::Subckt) (AST) level
//! before the connectivity graph is built. The same passes are applied
//! symmetrically to both schematic and layout sides so that VF2 sees
//! comparable structures.
//!
//! Implemented passes:
//!
//!   * Parallel resistor folding — `R_eq = 1 / sum(1/R_i)`
//!   * Series resistor folding   — `R_eq = sum(R_i)` (degree-2 internal nets only)
//!   * Parallel capacitor folding — `C_eq = sum(C_i)`
//!   * Series capacitor folding   — `1/C_eq = sum(1/C_i)`
//!   * Multi-finger MOSFET folding — same gate/source/drain/body and same
//!     model collapse into one device whose width is the sum of fingers.
//!
//! Tolerances: parameter equality on mosfets is value-string based, matching
//! the rest of the matcher. Folding is deterministic (sorted iteration).

use crate::spice::{Device, Subckt};
use std::collections::{HashMap, HashSet};

/// Apply all normalization passes to `sc` in place.
pub fn normalize_subckt(sc: &mut Subckt) {
    // Recurse into nested subckts first.
    for child in &mut sc.subckts {
        normalize_subckt(child);
    }

    // Canonicalize w/l strings on all mosfets so that "0.84u" and "0.84e-6"
    // (and any sum-of-fingers result) compare equal.
    canonicalize_mosfet_dims(sc);

    // Iterate to a fixpoint: series folding can expose new parallel
    // candidates, and vice versa.
    loop {
        let before = sc.devices.len();
        fold_parallel_resistors(sc);
        fold_parallel_capacitors(sc);
        fold_parallel_mosfets(sc);
        fold_series_resistors(sc);
        fold_series_capacitors(sc);
        if sc.devices.len() == before {
            break;
        }
    }

    // After folding we re-canonicalize: parallel fold rewrites `w` itself.
    canonicalize_mosfet_dims(sc);
}

fn canonicalize_mosfet_dims(sc: &mut Subckt) {
    for d in &mut sc.devices {
        if let Device::Mosfet { params, .. } = d {
            for key in ["w", "l"] {
                if let Some(v) = params.get(key).cloned() {
                    if let Some(num) = parse_w(&v) {
                        params.insert(key.into(), format_w(num));
                    }
                }
            }
        }
    }
}

/// Legacy entry-point: takes a built [`ConnGraph`] and is a no-op.
///
/// Normalization happens on the AST before the graph is built; this stub
/// remains for API compatibility.
pub fn normalize(_g: &mut crate::graph::ConnGraph) {}

// ---------- Helpers ----------

/// Returns an unordered key for a 2-terminal device's net pair.
fn net_pair(a: &str, b: &str) -> (String, String) {
    if a <= b {
        (a.to_string(), b.to_string())
    } else {
        (b.to_string(), a.to_string())
    }
}

/// Set of all net names that appear as ports on `sc`.
fn port_set(sc: &Subckt) -> HashSet<String> {
    sc.ports.iter().cloned().collect()
}

/// Count how many devices touch each net.
fn net_degree(sc: &Subckt) -> HashMap<String, usize> {
    let mut deg: HashMap<String, usize> = HashMap::new();
    for d in &sc.devices {
        for (_, n) in d.pins() {
            *deg.entry(n).or_insert(0) += 1;
        }
    }
    deg
}

// ---------- Parallel folding ----------

fn fold_parallel_resistors(sc: &mut Subckt) {
    // Group resistors by unordered net pair.
    let mut groups: HashMap<(String, String), Vec<usize>> = HashMap::new();
    for (i, d) in sc.devices.iter().enumerate() {
        if let Device::Resistor { n1, n2, .. } = d {
            groups.entry(net_pair(n1, n2)).or_default().push(i);
        }
    }
    let mut to_remove: HashSet<usize> = HashSet::new();
    let mut updates: Vec<(usize, f64)> = Vec::new(); // (keep_idx, new_value)
    for (_, idxs) in groups {
        if idxs.len() < 2 {
            continue;
        }
        let mut inv_sum = 0.0_f64;
        for &i in &idxs {
            if let Device::Resistor { value_ohm, .. } = &sc.devices[i] {
                if *value_ohm <= 0.0 {
                    // Treat zero as a short — keep all such resistors as-is.
                    inv_sum = 0.0;
                    break;
                }
                inv_sum += 1.0 / value_ohm;
            }
        }
        if inv_sum <= 0.0 {
            continue;
        }
        let r_eq = 1.0 / inv_sum;
        let keep = idxs[0];
        updates.push((keep, r_eq));
        for &i in &idxs[1..] {
            to_remove.insert(i);
        }
    }
    for (i, v) in updates {
        if let Device::Resistor { value_ohm, .. } = &mut sc.devices[i] {
            *value_ohm = v;
        }
    }
    remove_indices(&mut sc.devices, &to_remove);
}

fn fold_parallel_capacitors(sc: &mut Subckt) {
    let mut groups: HashMap<(String, String), Vec<usize>> = HashMap::new();
    for (i, d) in sc.devices.iter().enumerate() {
        if let Device::Capacitor { n1, n2, .. } = d {
            groups.entry(net_pair(n1, n2)).or_default().push(i);
        }
    }
    let mut to_remove: HashSet<usize> = HashSet::new();
    let mut updates: Vec<(usize, f64)> = Vec::new();
    for (_, idxs) in groups {
        if idxs.len() < 2 {
            continue;
        }
        let mut sum = 0.0_f64;
        for &i in &idxs {
            if let Device::Capacitor { value_f, .. } = &sc.devices[i] {
                sum += value_f;
            }
        }
        let keep = idxs[0];
        updates.push((keep, sum));
        for &i in &idxs[1..] {
            to_remove.insert(i);
        }
    }
    for (i, v) in updates {
        if let Device::Capacitor { value_f, .. } = &mut sc.devices[i] {
            *value_f = v;
        }
    }
    remove_indices(&mut sc.devices, &to_remove);
}

/// Fold parallel mosfets that share gate/source/drain/body and model. The
/// surviving device's `w` parameter is the sum of widths.
fn fold_parallel_mosfets(sc: &mut Subckt) {
    // Key: (model, drain, gate, source, body, l-string)
    type Key = (String, String, String, String, String, String);
    let mut groups: HashMap<Key, Vec<usize>> = HashMap::new();
    for (i, d) in sc.devices.iter().enumerate() {
        if let Device::Mosfet {
            drain,
            gate,
            source,
            body,
            model,
            params,
            ..
        } = d
        {
            // Source and drain are not symmetric in our representation, but
            // for matching purposes we treat (drain,source) as an unordered
            // pair so mirror-symmetric multi-finger layouts collapse.
            let (sd_a, sd_b) = if drain <= source {
                (drain.clone(), source.clone())
            } else {
                (source.clone(), drain.clone())
            };
            let l = params.get("l").cloned().unwrap_or_default();
            let key: Key = (model.clone(), sd_a, gate.clone(), sd_b, body.clone(), l);
            groups.entry(key).or_default().push(i);
        }
    }

    let mut to_remove: HashSet<usize> = HashSet::new();
    // (keep_idx, summed_width_string)
    let mut updates: Vec<(usize, String)> = Vec::new();
    for (_, idxs) in groups {
        if idxs.len() < 2 {
            continue;
        }
        let mut total_w = 0.0_f64;
        let mut all_have_w = true;
        for &i in &idxs {
            if let Device::Mosfet { params, .. } = &sc.devices[i] {
                match params.get("w").and_then(|s| parse_w(s)) {
                    Some(w) => total_w += w,
                    None => {
                        all_have_w = false;
                        break;
                    }
                }
            }
        }
        if !all_have_w {
            continue;
        }
        let keep = idxs[0];
        updates.push((keep, format_w(total_w)));
        for &i in &idxs[1..] {
            to_remove.insert(i);
        }
    }
    for (i, w_str) in updates {
        if let Device::Mosfet { params, .. } = &mut sc.devices[i] {
            params.insert("w".into(), w_str);
        }
    }
    remove_indices(&mut sc.devices, &to_remove);
}

// ---------- Series folding ----------

/// Fold a chain of resistors that meet only at degree-2 internal (non-port)
/// nets into a single resistor whose value is the sum.
fn fold_series_resistors(sc: &mut Subckt) {
    let ports = port_set(sc);
    let deg = net_degree(sc);

    // Find a candidate internal net: degree 2 and connects exactly two
    // resistors (so that nothing else — capacitors, mosfets, subckt
    // instances — is attached).
    let mut net_resistors: HashMap<String, Vec<usize>> = HashMap::new();
    for (i, d) in sc.devices.iter().enumerate() {
        if let Device::Resistor { n1, n2, .. } = d {
            net_resistors.entry(n1.clone()).or_default().push(i);
            if n1 != n2 {
                net_resistors.entry(n2.clone()).or_default().push(i);
            }
        }
    }

    // Greedy pass: collapse one pair at a time until stable.
    loop {
        let mut collapsed = false;
        let candidates: Vec<String> = net_resistors
            .iter()
            .filter(|(net, idxs)| {
                !ports.contains(*net) && idxs.len() == 2 && deg.get(*net).copied().unwrap_or(0) == 2
            })
            .map(|(net, _)| net.clone())
            .collect();

        for net in candidates {
            let idxs = match net_resistors.get(&net) {
                Some(v) if v.len() == 2 => v.clone(),
                _ => continue,
            };
            let (mut i, mut j) = (idxs[0], idxs[1]);
            if i == j {
                continue;
            }
            // Ensure both still exist (not yet removed).
            match (sc.devices.get(i), sc.devices.get(j)) {
                (Some(Device::Resistor { .. }), Some(Device::Resistor { .. })) => {}
                _ => continue,
            }
            // Always keep the smaller index, remove the larger.
            if j < i {
                std::mem::swap(&mut i, &mut j);
            }
            let (r_i, r_j) = (i, j);
            // Extract endpoints.
            let (a, b, vi) = if let Device::Resistor {
                n1, n2, value_ohm, ..
            } = &sc.devices[r_i]
            {
                (n1.clone(), n2.clone(), *value_ohm)
            } else {
                continue;
            };
            let (c, d, vj) = if let Device::Resistor {
                n1, n2, value_ohm, ..
            } = &sc.devices[r_j]
            {
                (n1.clone(), n2.clone(), *value_ohm)
            } else {
                continue;
            };
            // Find shared net == `net`; remaining endpoints become new n1/n2.
            let pick_other = |x: &str, y: &str, shared: &str| -> Option<String> {
                if x == shared {
                    Some(y.to_string())
                } else if y == shared {
                    Some(x.to_string())
                } else {
                    None
                }
            };
            let new_n1 = match pick_other(&a, &b, &net) {
                Some(s) => s,
                None => continue,
            };
            let new_n2 = match pick_other(&c, &d, &net) {
                Some(s) => s,
                None => continue,
            };
            // Replace device i in place; remove device j.
            if let Device::Resistor {
                n1, n2, value_ohm, ..
            } = &mut sc.devices[r_i]
            {
                *n1 = new_n1.clone();
                *n2 = new_n2.clone();
                *value_ohm = vi + vj;
            }
            sc.devices.remove(r_j);
            let _ = (a, b, c, d);
            collapsed = true;
            break;
        }

        if !collapsed {
            break;
        }
        // Rebuild maps for the next iteration.
        let new_deg = net_degree(sc);
        let mut new_net_resistors: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, dev) in sc.devices.iter().enumerate() {
            if let Device::Resistor { n1, n2, .. } = dev {
                new_net_resistors.entry(n1.clone()).or_default().push(i);
                if n1 != n2 {
                    new_net_resistors.entry(n2.clone()).or_default().push(i);
                }
            }
        }
        // Replace via shadow assignment.
        net_resistors = new_net_resistors;
        // Update `deg` shadow.
        let _ = deg;
        let _new_deg = new_deg;
    }
}

/// Fold a chain of capacitors that meet only at degree-2 internal nets.
/// `1/C_eq = sum(1/C_i)`.
fn fold_series_capacitors(sc: &mut Subckt) {
    let ports = port_set(sc);

    loop {
        let deg = net_degree(sc);
        let mut net_caps: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, d) in sc.devices.iter().enumerate() {
            if let Device::Capacitor { n1, n2, .. } = d {
                net_caps.entry(n1.clone()).or_default().push(i);
                if n1 != n2 {
                    net_caps.entry(n2.clone()).or_default().push(i);
                }
            }
        }
        let target = net_caps
            .iter()
            .find(|(net, idxs)| {
                !ports.contains(*net) && idxs.len() == 2 && deg.get(*net).copied().unwrap_or(0) == 2
            })
            .map(|(n, v)| (n.clone(), v.clone()));
        let (net, idxs) = match target {
            Some(x) => x,
            None => break,
        };
        let (mut i, mut j) = (idxs[0], idxs[1]);
        if i == j {
            break;
        }
        if j < i {
            std::mem::swap(&mut i, &mut j);
        }
        let (a, b, vi) = if let Device::Capacitor {
            n1, n2, value_f, ..
        } = &sc.devices[i]
        {
            (n1.clone(), n2.clone(), *value_f)
        } else {
            break;
        };
        let (c, d, vj) = if let Device::Capacitor {
            n1, n2, value_f, ..
        } = &sc.devices[j]
        {
            (n1.clone(), n2.clone(), *value_f)
        } else {
            break;
        };
        if vi <= 0.0 || vj <= 0.0 {
            break;
        }
        let pick_other = |x: &str, y: &str, shared: &str| -> Option<String> {
            if x == shared {
                Some(y.to_string())
            } else if y == shared {
                Some(x.to_string())
            } else {
                None
            }
        };
        let new_n1 = match pick_other(&a, &b, &net) {
            Some(s) => s,
            None => break,
        };
        let new_n2 = match pick_other(&c, &d, &net) {
            Some(s) => s,
            None => break,
        };
        let new_c = 1.0 / (1.0 / vi + 1.0 / vj);
        if let Device::Capacitor {
            n1, n2, value_f, ..
        } = &mut sc.devices[i]
        {
            *n1 = new_n1;
            *n2 = new_n2;
            *value_f = new_c;
        }
        sc.devices.remove(j);
    }
}

// ---------- Width parsing ----------

/// Parse a SPICE-engineering-suffixed number (e.g. "0.42", "0.42u", "1k").
/// Also accepts plain scientific notation like "2.1e-7".
fn parse_w(s: &str) -> Option<f64> {
    let s = s.trim().to_ascii_lowercase();
    if s.is_empty() {
        return None;
    }
    // First try plain float (handles "2.1e-7", "0.42", "-1.5").
    if let Ok(v) = s.parse::<f64>() {
        return Some(v);
    }
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

fn format_w(w: f64) -> String {
    // Use a fixed-format with enough precision to round-trip typical IC
    // dimensions (down to femto units). We prefer scientific notation so
    // that "0.15u" (1.5e-7) and a sum of fingers compare equal even when
    // the magnitudes are tiny.
    if w == 0.0 {
        return "0".into();
    }
    // Round to 9 significant digits to absorb f64 sum noise.
    let mag = w.abs().log10().floor() as i32;
    let scale = 10f64.powi(8 - mag);
    let rounded = (w * scale).round() / scale;
    format!("{rounded:e}")
}

// ---------- Misc ----------

fn remove_indices<T>(v: &mut Vec<T>, idxs: &HashSet<usize>) {
    if idxs.is_empty() {
        return;
    }
    let mut sorted: Vec<usize> = idxs.iter().copied().collect();
    sorted.sort_unstable_by(|a, b| b.cmp(a));
    for i in sorted {
        if i < v.len() {
            v.remove(i);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spice::Device;

    fn r(name: &str, n1: &str, n2: &str, v: f64) -> Device {
        Device::Resistor {
            name: name.into(),
            n1: n1.into(),
            n2: n2.into(),
            value_ohm: v,
        }
    }

    fn c(name: &str, n1: &str, n2: &str, v: f64) -> Device {
        Device::Capacitor {
            name: name.into(),
            n1: n1.into(),
            n2: n2.into(),
            value_f: v,
        }
    }

    #[test]
    fn parallel_resistors_collapse() {
        let mut sc = Subckt {
            name: "t".into(),
            ports: vec!["a".into(), "b".into()],
            devices: vec![r("R1", "a", "b", 3.0), r("R2", "a", "b", 6.0)],
            subckts: vec![],
        };
        normalize_subckt(&mut sc);
        assert_eq!(sc.devices.len(), 1);
        if let Device::Resistor { value_ohm, .. } = &sc.devices[0] {
            assert!((*value_ohm - 2.0).abs() < 1e-9);
        } else {
            panic!("expected resistor");
        }
    }

    #[test]
    fn series_resistors_collapse() {
        let mut sc = Subckt {
            name: "t".into(),
            ports: vec!["a".into(), "b".into()],
            devices: vec![r("R1", "a", "mid", 1.0), r("R2", "mid", "b", 2.0)],
            subckts: vec![],
        };
        normalize_subckt(&mut sc);
        assert_eq!(sc.devices.len(), 1);
        if let Device::Resistor { value_ohm, .. } = &sc.devices[0] {
            assert!((*value_ohm - 3.0).abs() < 1e-9);
        }
    }

    #[test]
    fn parallel_capacitors_sum() {
        let mut sc = Subckt {
            name: "t".into(),
            ports: vec!["a".into(), "b".into()],
            devices: vec![c("C1", "a", "b", 1e-12), c("C2", "a", "b", 2e-12)],
            subckts: vec![],
        };
        normalize_subckt(&mut sc);
        assert_eq!(sc.devices.len(), 1);
        if let Device::Capacitor { value_f, .. } = &sc.devices[0] {
            assert!((*value_f - 3e-12).abs() < 1e-20);
        }
    }
}
