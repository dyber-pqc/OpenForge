//! Layout extraction: build an LVS-comparable `Subckt` directly from a routed
//! DEF + LEF library, treating each standard cell as an opaque primitive.
//!
//! The schematic side (gate-level Verilog or X-style SPICE) instantiates the
//! same cells as primitives, so the resulting connectivity graphs are
//! isomorphic when the routing matches the netlist.

pub mod connectivity;
pub mod def_reader;
pub mod lef_reader;

pub use connectivity::{extract_subckt, extract_subckt_with_filter, FilteredCells};
pub use def_reader::{parse_def_file, parse_def_str, DefData};
pub use lef_reader::{parse_lef_file, parse_lef_str, LefLibrary, LefMacro};

use crate::error::{LvsError, Result};
use regex::Regex;

/// Default regex matching sky130 physical-only cells: tap, decap, fill,
/// antenna diode. These cells carry no signal pins (or only power/well
/// taps) and are inserted by the place-and-route flow to satisfy density,
/// well-tap spacing, and antenna rules — they never appear in the
/// schematic / synthesized gate-level netlist, so they must be filtered
/// from the layout before LVS device-count comparison.
pub const DEFAULT_SKY130_PHYSICAL_ONLY: &str = r"^sky130_fd_sc_hd__(tap|decap|fill|diode).*";

/// Filter selecting physical-only cells to drop from layout extraction.
#[derive(Debug, Clone)]
pub struct PhysicalFilter {
    re: Option<Regex>,
}

impl PhysicalFilter {
    /// Build a filter from an explicit regex string. Pass `None` for the
    /// sky130 default.
    pub fn new(pattern: Option<&str>) -> Result<Self> {
        let pat = pattern.unwrap_or(DEFAULT_SKY130_PHYSICAL_ONLY);
        let re = Regex::new(pat).map_err(|e| {
            LvsError::Graph(format!("invalid --physical-only-filter regex '{pat}': {e}"))
        })?;
        Ok(Self { re: Some(re) })
    }

    /// A disabled filter: matches nothing.
    pub fn disabled() -> Self {
        Self { re: None }
    }

    /// True if the given LEF macro name should be filtered out.
    pub fn matches(&self, macro_name: &str) -> bool {
        match &self.re {
            Some(r) => r.is_match(macro_name),
            None => false,
        }
    }
}

impl Default for PhysicalFilter {
    fn default() -> Self {
        // Default construction uses the sky130 pattern, which is a valid
        // hard-coded regex; falling back to disabled on the (unreachable)
        // failure keeps `Default` total.
        Self::new(None).unwrap_or_else(|_| Self::disabled())
    }
}
