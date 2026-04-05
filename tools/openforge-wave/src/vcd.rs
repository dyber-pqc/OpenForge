//! High-performance streaming VCD (Value Change Dump) parser.
//!
//! Parses IEEE Std 1364 VCD files using a line-oriented streaming approach
//! that avoids loading the entire file into memory.

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use crate::{
    Result, Signal, SignalType, TimeUnit, Timescale, Value, ValueChange, WaveError, WaveformData,
};

// ---------------------------------------------------------------------------
// Internal types
// ---------------------------------------------------------------------------

/// Signal definition collected during header parsing.
#[derive(Debug, Clone)]
struct VarDef {
    signal_type: SignalType,
    width: u32,
    id_code: String,
    /// Fully-qualified hierarchical name (e.g. "top.cpu.alu.result").
    full_name: String,
}

/// Transient parser state.
struct VcdParser {
    /// Current line number (1-based) for error reporting.
    line_no: usize,
    /// Scope stack used to build hierarchical signal names.
    scope_stack: Vec<String>,
    /// Timescale parsed from the header.
    timescale: Timescale,
    /// Variable definitions keyed by VCD identifier code.
    vars: HashMap<String, VarDef>,
    /// Ordered list of identifier codes matching insertion order.
    var_order: Vec<String>,
    /// Accumulated value changes keyed by VCD identifier code.
    changes: HashMap<String, Vec<ValueChange>>,
    /// The most recent `#time` value.
    current_time: u64,
    /// Maximum time seen.
    max_time: u64,
    /// Whether we are inside a $dumpoff region (all signals X).
    _in_dumpoff: bool,
}

impl VcdParser {
    fn new() -> Self {
        Self {
            line_no: 0,
            scope_stack: Vec::new(),
            timescale: Timescale::default(),
            vars: HashMap::new(),
            var_order: Vec::new(),
            changes: HashMap::new(),
            current_time: 0,
            max_time: 0,
            _in_dumpoff: false,
        }
    }

    fn err(&self, msg: impl Into<String>) -> WaveError {
        WaveError::VcdParse {
            line: self.line_no,
            message: msg.into(),
        }
    }

    /// Build the fully-qualified name for a signal given the current scope.
    fn qualified_name(&self, short_name: &str) -> String {
        if self.scope_stack.is_empty() {
            short_name.to_string()
        } else {
            format!("{}.{}", self.scope_stack.join("."), short_name)
        }
    }

    // ------------------------------------------------------------------
    // Header parsing
    // ------------------------------------------------------------------

    fn parse_timescale(&mut self, tokens: &[&str]) -> Result<()> {
        // Tokens may arrive as ["1ns"] or ["1", "ns"] depending on VCD writer.
        let combined = tokens.join("");
        let combined = combined.trim();
        if combined.is_empty() {
            return Err(self.err("empty $timescale"));
        }

        // Split magnitude from unit.
        let (mag_str, unit_str) = split_magnitude_unit(combined);
        let magnitude: u64 = mag_str.parse().map_err(|_| {
            self.err(format!("invalid timescale magnitude: '{mag_str}'"))
        })?;
        let unit = parse_time_unit(unit_str)
            .ok_or_else(|| self.err(format!("unknown time unit: '{unit_str}'")))?;

        self.timescale = Timescale { magnitude, unit };
        Ok(())
    }

    fn parse_var(&mut self, tokens: &[&str]) -> Result<()> {
        // $var <type> <width> <id_code> <name> $end
        if tokens.len() < 4 {
            return Err(self.err("$var requires at least 4 tokens"));
        }
        let sig_type = parse_signal_type(tokens[0])
            .ok_or_else(|| self.err(format!("unknown variable type: '{}'", tokens[0])))?;
        let width: u32 = tokens[1]
            .parse()
            .map_err(|_| self.err(format!("invalid width: '{}'", tokens[1])))?;
        let id_code = tokens[2].to_string();
        // The name may contain a bit-select suffix like [7:0]; join remaining
        // tokens (excluding a trailing $end already stripped by caller).
        let name = tokens[3..].join(" ");
        // Strip any trailing bit range like " [7:0]" from the name.
        let name = name.split('[').next().unwrap_or(&name).trim().to_string();

        let full_name = self.qualified_name(&name);

        let def = VarDef {
            signal_type: sig_type,
            width,
            id_code: id_code.clone(),
            full_name,
        };

        if !self.vars.contains_key(&id_code) {
            self.var_order.push(id_code.clone());
            self.changes.insert(id_code.clone(), Vec::new());
        }
        self.vars.insert(id_code, def);

        Ok(())
    }

    // ------------------------------------------------------------------
    // Value-change parsing
    // ------------------------------------------------------------------

    fn parse_value_change(&mut self, line: &str) -> Result<()> {
        let line = line.trim();
        if line.is_empty() {
            return Ok(());
        }

        let first = line.as_bytes()[0];

        match first {
            // Scalar value changes: 0id, 1id, xid, zid, Xid, Zid
            b'0' | b'1' | b'x' | b'X' | b'z' | b'Z' => {
                let bit_char = line.as_bytes()[0];
                let id_code = &line[1..];
                if id_code.is_empty() {
                    return Err(self.err("scalar value change missing identifier"));
                }
                let value = scalar_to_value(bit_char);
                self.record_change(id_code, value);
            }
            // Vector binary: b/B
            b'b' | b'B' => {
                let rest = &line[1..];
                let (bits, id_code) = split_value_id(rest)
                    .ok_or_else(|| self.err("malformed binary value change"))?;
                let value = binary_string_to_value(bits);
                self.record_change(id_code, value);
            }
            // Real value: r/R
            b'r' | b'R' => {
                let rest = &line[1..];
                let (val_str, id_code) = split_value_id(rest)
                    .ok_or_else(|| self.err("malformed real value change"))?;
                let f: f64 = val_str.parse().map_err(|_| {
                    self.err(format!("invalid real value: '{val_str}'"))
                })?;
                self.record_change(id_code, Value::Real(f));
            }
            // String value: s/S
            b's' | b'S' => {
                let rest = &line[1..];
                let (val_str, id_code) = split_value_id(rest)
                    .ok_or_else(|| self.err("malformed string value change"))?;
                self.record_change(id_code, Value::String(val_str.to_string()));
            }
            _ => {
                // Ignore unrecognized lines in value section (tolerant parsing).
            }
        }

        Ok(())
    }

    fn record_change(&mut self, id_code: &str, value: Value) {
        if let Some(changes) = self.changes.get_mut(id_code) {
            changes.push(ValueChange {
                time: self.current_time,
                value,
            });
        }
        // Unknown id codes are silently ignored (some VCD writers emit aliases).
    }

    // ------------------------------------------------------------------
    // Assemble final output
    // ------------------------------------------------------------------

    fn finish(self) -> WaveformData {
        let mut signals = Vec::with_capacity(self.var_order.len());
        for id in &self.var_order {
            if let Some(def) = self.vars.get(id) {
                let values = self
                    .changes
                    .get(id)
                    .cloned()
                    .unwrap_or_default();
                signals.push(Signal {
                    name: def.full_name.clone(),
                    width: def.width,
                    id: def.id_code.clone(),
                    values,
                    signal_type: def.signal_type,
                });
            }
        }

        WaveformData {
            signals,
            timescale: self.timescale,
            total_time: self.max_time,
        }
    }
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Parse a VCD file at `path` and return the waveform data.
pub fn parse_vcd(path: &Path) -> Result<WaveformData> {
    let file = File::open(path)?;
    let reader = BufReader::with_capacity(256 * 1024, file);
    let mut parser = VcdParser::new();

    // We process the file in two logical phases but in a single pass:
    //   1. Header: everything up to and including $enddefinitions $end.
    //   2. Value changes: #time markers and value lines.
    let mut in_header = true;
    // Buffer for multi-line header commands (e.g. $timescale ... $end).
    let mut cmd_name: Option<String> = None;
    let mut cmd_tokens: Vec<String> = Vec::new();

    for line_result in reader.lines() {
        let line = line_result?;
        parser.line_no += 1;
        let trimmed = line.trim();

        if trimmed.is_empty() {
            continue;
        }

        if in_header {
            // Accumulate tokens for multi-line header commands.
            let words: Vec<&str> = trimmed.split_whitespace().collect();

            for word in &words {
                if word.starts_with('$') && *word != "$end" {
                    // Start of a new command.
                    cmd_name = Some(word.to_string());
                    cmd_tokens.clear();
                } else if *word == "$end" {
                    // End of current command -- dispatch.
                    if let Some(ref name) = cmd_name {
                        parser.dispatch_header_cmd(name, &cmd_tokens)?;
                    }
                    cmd_name = None;
                    cmd_tokens.clear();
                } else if cmd_name.is_some() {
                    cmd_tokens.push(word.to_string());
                }
            }

            // Detect end of header.
            if trimmed.contains("$enddefinitions") {
                in_header = false;
                // Reset command state for the value section.
                cmd_name = None;
                cmd_tokens.clear();
            }
        } else {
            // Value-change section.
            parse_value_section_line(&mut parser, trimmed)?;
        }
    }

    Ok(parser.finish())
}

// ---------------------------------------------------------------------------
// Header command dispatch
// ---------------------------------------------------------------------------

impl VcdParser {
    fn dispatch_header_cmd(&mut self, name: &str, tokens: &[String]) -> Result<()> {
        let refs: Vec<&str> = tokens.iter().map(|s| s.as_str()).collect();
        match name {
            "$timescale" => self.parse_timescale(&refs),
            "$scope" => {
                // $scope <type> <name> $end
                if refs.len() >= 2 {
                    self.scope_stack.push(refs[1].to_string());
                }
                Ok(())
            }
            "$upscope" => {
                self.scope_stack.pop();
                Ok(())
            }
            "$var" => self.parse_var(&refs),
            // Silently ignore $comment, $date, $version, $dumpvars header,
            // and any other unrecognized commands.
            _ => Ok(()),
        }
    }
}

// ---------------------------------------------------------------------------
// Value-section line dispatch
// ---------------------------------------------------------------------------

fn parse_value_section_line(parser: &mut VcdParser, line: &str) -> Result<()> {
    if line.is_empty() {
        return Ok(());
    }

    let first = line.as_bytes()[0];

    match first {
        b'#' => {
            // Time marker.
            let time_str = &line[1..];
            let time: u64 = time_str
                .trim()
                .parse()
                .map_err(|_| parser.err(format!("invalid time value: '{time_str}'")))?;
            parser.current_time = time;
            if time > parser.max_time {
                parser.max_time = time;
            }
        }
        b'$' => {
            // Section markers inside value data.
            let word = line.split_whitespace().next().unwrap_or("");
            match word {
                "$dumpvars" | "$end" | "$dumpon" | "$comment" => {
                    // $dumpvars: initial values follow -- parse like normal changes.
                    // $dumpon: resume recording.
                    if word == "$dumpon" {
                        parser._in_dumpoff = false;
                    }
                }
                "$dumpoff" => {
                    parser._in_dumpoff = true;
                }
                _ => {
                    // Skip unknown $ keywords and any tokens until $end.
                }
            }
        }
        _ => {
            parser.parse_value_change(line)?;
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/// Split a combined magnitude+unit string like "1ns" into ("1", "ns").
fn split_magnitude_unit(s: &str) -> (&str, &str) {
    let idx = s
        .find(|c: char| c.is_alphabetic())
        .unwrap_or(s.len());
    (&s[..idx], &s[idx..])
}

fn parse_time_unit(s: &str) -> Option<TimeUnit> {
    match s.to_lowercase().as_str() {
        "s" => Some(TimeUnit::S),
        "ms" => Some(TimeUnit::Ms),
        "us" => Some(TimeUnit::Us),
        "ns" => Some(TimeUnit::Ns),
        "ps" => Some(TimeUnit::Ps),
        "fs" => Some(TimeUnit::Fs),
        _ => None,
    }
}

fn parse_signal_type(s: &str) -> Option<SignalType> {
    match s.to_lowercase().as_str() {
        "wire" => Some(SignalType::Wire),
        "reg" => Some(SignalType::Reg),
        "integer" => Some(SignalType::Integer),
        "real" | "realtime" => Some(SignalType::Real),
        "parameter" => Some(SignalType::Parameter),
        // Treat other types (event, supply0, supply1, tri, etc.) as Wire.
        _ => Some(SignalType::Wire),
    }
}

/// Convert a scalar VCD bit character to a `Value`.
fn scalar_to_value(ch: u8) -> Value {
    match ch {
        b'0' => Value::Binary(vec![0]),
        b'1' => Value::Binary(vec![1]),
        b'x' | b'X' => Value::String("x".to_string()),
        b'z' | b'Z' => Value::String("z".to_string()),
        _ => Value::String(String::from(ch as char)),
    }
}

/// Convert a VCD binary string like "10110xz1" to a `Value`.
///
/// If the string contains only '0' and '1', it is packed into bytes.
/// Otherwise, it is stored as a `Value::String` to preserve x/z information.
fn binary_string_to_value(bits: &str) -> Value {
    let has_xz = bits.bytes().any(|b| matches!(b, b'x' | b'X' | b'z' | b'Z'));
    if has_xz {
        return Value::String(bits.to_string());
    }

    // Pack pure binary into bytes, MSB-first.
    let bit_count = bits.len();
    let byte_count = (bit_count + 7) / 8;
    let mut bytes = vec![0u8; byte_count];

    for (i, ch) in bits.bytes().enumerate() {
        if ch == b'1' {
            let bit_pos = bit_count - 1 - i; // bit 0 is LSB
            let byte_idx = byte_count - 1 - (bit_pos / 8);
            let bit_idx = bit_pos % 8;
            bytes[byte_idx] |= 1 << bit_idx;
        }
    }

    Value::Binary(bytes)
}

/// Split a value+id string like "10110 abc" into ("10110", "abc").
/// The separator is whitespace.
fn split_value_id(s: &str) -> Option<(&str, &str)> {
    let s = s.trim();
    let idx = s.find(char::is_whitespace)?;
    let value = &s[..idx];
    let id = s[idx..].trim_start();
    if id.is_empty() {
        None
    } else {
        Some((value, id))
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_test_vcd(content: &str) -> tempfile::NamedTempFile {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        f.write_all(content.as_bytes()).unwrap();
        f.flush().unwrap();
        f
    }

    #[test]
    fn test_split_magnitude_unit() {
        assert_eq!(split_magnitude_unit("1ns"), ("1", "ns"));
        assert_eq!(split_magnitude_unit("100ps"), ("100", "ps"));
        assert_eq!(split_magnitude_unit("10us"), ("10", "us"));
    }

    #[test]
    fn test_binary_string_to_value_pure() {
        let v = binary_string_to_value("1010");
        match v {
            Value::Binary(bytes) => assert_eq!(bytes, vec![0b00001010]),
            _ => panic!("expected Binary"),
        }
    }

    #[test]
    fn test_binary_string_to_value_with_xz() {
        let v = binary_string_to_value("10x1");
        match v {
            Value::String(s) => assert_eq!(s, "10x1"),
            _ => panic!("expected String"),
        }
    }

    #[test]
    fn test_parse_simple_vcd() {
        let vcd = "\
$timescale 1ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 8 \" data [7:0] $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b00000000 \"
$end
#0
1!
#5
0!
b10101010 \"
#10
1!
";
        let f = write_test_vcd(vcd);
        let result = parse_vcd(f.path()).unwrap();

        assert_eq!(result.timescale.magnitude, 1);
        assert_eq!(result.timescale.unit, TimeUnit::Ns);
        assert_eq!(result.signals.len(), 2);
        assert_eq!(result.total_time, 10);

        let clk = &result.signals[0];
        assert_eq!(clk.name, "top.clk");
        assert_eq!(clk.width, 1);
        // Should have changes from $dumpvars + #0 + #5 + #10
        assert!(clk.values.len() >= 3);

        let data = &result.signals[1];
        assert_eq!(data.name, "top.data");
        assert_eq!(data.width, 8);
    }

    #[test]
    fn test_parse_real_signals() {
        let vcd = "\
$timescale 1ps $end
$scope module top $end
$var real 64 # voltage $end
$upscope $end
$enddefinitions $end
#0
r1.5 #
#100
r2.7 #
#200
r0.0 #
";
        let f = write_test_vcd(vcd);
        let result = parse_vcd(f.path()).unwrap();

        assert_eq!(result.signals.len(), 1);
        let sig = &result.signals[0];
        assert_eq!(sig.signal_type, SignalType::Real);
        assert_eq!(sig.values.len(), 3);
        match &sig.values[0].value {
            Value::Real(v) => assert!((v - 1.5).abs() < f64::EPSILON),
            _ => panic!("expected Real"),
        }
    }

    #[test]
    fn test_nested_scopes() {
        let vcd = "\
$timescale 1ns $end
$scope module top $end
$scope module cpu $end
$scope module alu $end
$var wire 1 A result $end
$upscope $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
1A
";
        let f = write_test_vcd(vcd);
        let result = parse_vcd(f.path()).unwrap();

        assert_eq!(result.signals.len(), 1);
        assert_eq!(result.signals[0].name, "top.cpu.alu.result");
    }

    #[test]
    fn test_comment_handling() {
        let vcd = "\
$comment This is a test VCD file $end
$timescale 10ns $end
$scope module top $end
$var wire 1 ! clk $end
$upscope $end
$enddefinitions $end
#0
0!
";
        let f = write_test_vcd(vcd);
        let result = parse_vcd(f.path()).unwrap();
        assert_eq!(result.timescale.magnitude, 10);
        assert_eq!(result.signals.len(), 1);
    }
}
